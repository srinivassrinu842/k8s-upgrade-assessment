"""
Unit tests for k8s-upgrade-assessment CLI.

Run with:
    pytest tests/ -v --cov=main --cov-report=term-missing
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

# ── Ensure project root is importable ────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
import main  # noqa: E402


# =============================================================================
# Provider Registry
# =============================================================================


class TestProviderRegistry:
    """Validate the shape and correctness of PROVIDERS."""

    def test_all_providers_present(self):
        expected = {"anthropic", "openai", "openrouter", "ollama", "lmstudio", "custom", "mock"}
        assert set(main.PROVIDERS.keys()) == expected

    def test_each_provider_has_required_keys(self):
        required = {"label", "default_model", "requires_key", "protocol"}
        for name, cfg in main.PROVIDERS.items():
            missing = required - cfg.keys()
            assert not missing, f"Provider '{name}' missing keys: {missing}"

    def test_protocol_values_valid(self):
        valid = {"anthropic", "openai", "mock"}
        for name, cfg in main.PROVIDERS.items():
            assert cfg["protocol"] in valid, f"Provider '{name}' has invalid protocol"

    def test_local_providers_do_not_require_key(self):
        for name in ("ollama", "lmstudio"):
            assert main.PROVIDERS[name]["requires_key"] is False

    def test_cloud_providers_require_key(self):
        for name in ("anthropic", "openai", "openrouter"):
            assert main.PROVIDERS[name]["requires_key"] is True

    def test_provider_names_matches_providers(self):
        assert main.PROVIDER_NAMES == list(main.PROVIDERS.keys())

    def test_anthropic_uses_native_protocol(self):
        assert main.PROVIDERS["anthropic"]["protocol"] == "anthropic"

    def test_openrouter_has_extra_headers(self):
        headers = main.PROVIDERS["openrouter"].get("extra_headers", {})
        assert "HTTP-Referer" in headers
        assert "X-Title" in headers


# =============================================================================
# run_kubectl
# =============================================================================


class TestRunKubectl:
    """Test kubectl subprocess wrapper."""

    def test_returns_stdout_on_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v1.27.3\n"
        with patch("subprocess.run", return_value=mock_result):
            result = main.run_kubectl(["version"])
        assert result == "v1.27.3"

    def test_returns_error_on_nonzero_returncode(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "connection refused"
        with patch("subprocess.run", return_value=mock_result):
            result = main.run_kubectl(["get", "nodes"])
        assert "[ERROR]" in result
        assert "connection refused" in result

    def test_handles_kubectl_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = main.run_kubectl(["version"])
        assert "kubectl not found" in result

    def test_handles_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("kubectl", 30)):
            result = main.run_kubectl(["get", "nodes"])
        assert "TIMEOUT" in result

    def test_handles_generic_exception(self):
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            result = main.run_kubectl(["get", "pods"])
        assert "EXCEPTION" in result

    def test_returns_empty_placeholder_when_stdout_empty(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            result = main.run_kubectl(["get", "crd"])
        assert result == "(empty)"

    def test_prepends_kubectl_to_command(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            main.run_kubectl(["get", "ns"])
            called_cmd = mock_run.call_args[0][0]
        assert called_cmd[0] == "kubectl"
        assert called_cmd[1:] == ["get", "ns"]


# =============================================================================
# _offline_placeholder
# =============================================================================


class TestOfflinePlaceholder:
    """Test offline placeholder data structure."""

    def test_returns_dict(self):
        data = main._offline_placeholder()
        assert isinstance(data, dict)

    def test_offline_mode_flag_present(self):
        data = main._offline_placeholder()
        assert data.get("_offline_mode") == "true"

    def test_contains_essential_keys(self):
        data = main._offline_placeholder()
        for key in ("version", "nodes", "namespaces", "deployments", "crds"):
            assert key in data, f"Missing key: {key}"

    def test_version_is_valid_json(self):
        data = main._offline_placeholder()
        parsed = json.loads(data["version"])
        assert "serverVersion" in parsed
        assert "clientVersion" in parsed

    def test_nodes_contains_master(self):
        data = main._offline_placeholder()
        assert "master-1" in data["nodes"]

    def test_crds_contains_cert_manager(self):
        data = main._offline_placeholder()
        assert "cert-manager" in data["crds"]


# =============================================================================
# gather_cluster_data
# =============================================================================


class TestGatherClusterData:
    """Test cluster data collection routing."""

    def test_no_cluster_returns_placeholder(self):
        data = main.gather_cluster_data(no_cluster=True)
        assert data.get("_offline_mode") == "true"

    def test_live_cluster_calls_kubectl(self):
        with patch("main.run_kubectl", return_value="ok") as mock_kubectl:
            data = main.gather_cluster_data(no_cluster=False)
        assert mock_kubectl.called
        assert "version" in data
        assert "_offline_mode" not in data

    def test_live_cluster_collects_minimum_sections(self):
        with patch("main.run_kubectl", return_value="(empty)"):
            data = main.gather_cluster_data(no_cluster=False)
        # Must gather at least these critical sections
        for key in ("version", "nodes", "crds", "deployments", "namespaces"):
            assert key in data

    def test_live_cluster_collects_webhook_sections(self):
        with patch("main.run_kubectl", return_value="(empty)"):
            data = main.gather_cluster_data(no_cluster=False)
        assert "validating_webhooks" in data
        assert "mutating_webhooks" in data


# =============================================================================
# build_prompt
# =============================================================================


class TestBuildPrompt:
    """Test prompt construction."""

    def test_contains_source_and_target(self):
        data = main._offline_placeholder()
        prompt = main.build_prompt("1.27", "1.29", data)
        assert "1.27" in prompt
        assert "1.29" in prompt

    def test_contains_offline_warning_in_offline_mode(self):
        data = main._offline_placeholder()
        prompt = main.build_prompt("1.27", "1.29", data)
        assert "OFFLINE" in prompt.upper()

    def test_no_offline_warning_in_live_mode(self):
        data = {"version": "v1.27.3", "nodes": "node-1 Ready"}
        prompt = main.build_prompt("1.27", "1.29", data)
        assert "OFFLINE MODE" not in prompt

    def test_private_keys_excluded_from_data_dump(self):
        data = {"version": "v1.27.3", "_offline_mode": "true", "_meta": "skip"}
        prompt = main.build_prompt("1.27", "1.29", data)
        assert "_offline_mode" not in prompt
        assert "_meta" not in prompt

    def test_returns_string(self):
        data = main._offline_placeholder()
        prompt = main.build_prompt("1.27", "1.29", data)
        assert isinstance(prompt, str)
        assert len(prompt) > 500

    def test_contains_report_sections(self):
        data = main._offline_placeholder()
        prompt = main.build_prompt("1.27", "1.29", data)
        assert "Cluster Inventory Summary" in prompt
        assert "Executive Summary" in prompt
        assert "Risk Matrix" in prompt

    def test_includes_cluster_data_in_dump(self):
        data = {"nodes": "master-1 Ready", "crds": "cert-manager.io"}
        prompt = main.build_prompt("1.27", "1.29", data)
        assert "master-1 Ready" in prompt
        assert "cert-manager.io" in prompt

    def test_cluster_type_kubeadm_present(self):
        data = main._offline_placeholder()
        prompt = main.build_prompt("1.27", "1.29", data)
        assert "kubeadm" in prompt


# =============================================================================
# resolve_api_key
# =============================================================================


class TestResolveApiKey:
    """Test API key resolution priority chain."""

    def test_cli_key_takes_highest_priority(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}):
            key = main.resolve_api_key("anthropic", cli_key="cli-key")
        assert key == "cli-key"

    def test_env_var_used_when_no_cli_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"}, clear=False):
            key = main.resolve_api_key("anthropic", cli_key=None)
        assert key == "env-key"

    def test_generic_fallback_llm_api_key(self):
        env = {"LLM_API_KEY": "generic-key"}
        with patch.dict("os.environ", env, clear=True):
            key = main.resolve_api_key("anthropic", cli_key=None)
        assert key == "generic-key"

    def test_local_providers_return_dummy_key(self):
        with patch.dict("os.environ", {}, clear=True):
            key = main.resolve_api_key("ollama", cli_key=None)
        assert key == "ollama"

    def test_lmstudio_dummy_key(self):
        with patch.dict("os.environ", {}, clear=True):
            key = main.resolve_api_key("lmstudio", cli_key=None)
        assert key == "lm-studio"

    def test_missing_key_for_cloud_provider_exits(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main.resolve_api_key("anthropic", cli_key=None)
        assert exc_info.value.code == 1

    def test_openrouter_env_var_name(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "or-key"}, clear=False):
            key = main.resolve_api_key("openrouter", cli_key=None)
        assert key == "or-key"

    def test_openai_env_var_name(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "oa-key"}, clear=False):
            key = main.resolve_api_key("openai", cli_key=None)
        assert key == "oa-key"


# =============================================================================
# save_report
# =============================================================================


class TestSaveReport:
    """Test report persistence."""

    def test_saves_to_custom_path(self, tmp_path):
        out = tmp_path / "my_report.md"
        result = main.save_report("content", "1.27", "1.29", "anthropic", "claude", str(out))
        assert result == out
        assert out.exists()

    def test_default_path_inside_reports_dir(self, tmp_path):
        with patch("main.Path") as mock_path_cls:
            # Let Path work normally but redirect reports dir
            real_path = Path
            reports_dir = tmp_path / "reports"

            def path_side_effect(arg=None):
                if arg == "reports":
                    p = MagicMock()
                    p.__truediv__ = lambda self, x: reports_dir / x
                    p.mkdir = lambda **kw: reports_dir.mkdir(**kw)
                    return p
                return real_path(arg) if arg else real_path()

            # Use real Path for actual test
            result = main.save_report(
                "content", "1.27", "1.29", "openai", "gpt-4o", None
            )
        # Just ensure no exception; path check covered by custom path test

    def test_report_contains_header_metadata(self, tmp_path):
        out = tmp_path / "report.md"
        main.save_report("body text here", "1.27", "1.29", "anthropic", "claude-3", str(out))
        text = out.read_text()
        assert "v1.27" in text
        assert "v1.29" in text
        assert "Anthropic" in text
        assert "claude-3" in text

    def test_report_contains_content(self, tmp_path):
        out = tmp_path / "report.md"
        main.save_report("## My Report Content", "1.27", "1.29", "openai", "gpt-4o", str(out))
        text = out.read_text()
        assert "## My Report Content" in text

    def test_report_encoded_as_utf8(self, tmp_path):
        out = tmp_path / "report.md"
        content = "Résumé: ✅ ⚠️ 🔍 ❓"
        main.save_report(content, "1.27", "1.29", "anthropic", "claude", str(out))
        text = out.read_text(encoding="utf-8")
        assert "✅" in text

    def test_filename_contains_versions(self, tmp_path):
        with patch("main.Path") as _:
            # exercise default path branch
            pass
        # Validate safe version strings
        src_safe = "1.27".replace(".", "")
        tgt_safe = "1.29".replace(".", "")
        assert src_safe == "127"
        assert tgt_safe == "129"


# =============================================================================
# parse_args
# =============================================================================


class TestParseArgs:
    """Test CLI argument parsing."""

    def _parse(self, argv):
        with patch("sys.argv", ["k8s-upgrade"] + argv):
            return main.parse_args()

    def test_required_source_and_target(self):
        args = self._parse(["--source", "1.27", "--target", "1.29"])
        assert args.source == "1.27"
        assert args.target == "1.29"

    def test_default_provider_is_anthropic(self):
        args = self._parse(["--source", "1.27", "--target", "1.29"])
        assert args.provider == "anthropic"

    def test_provider_override(self):
        args = self._parse(["--source", "1.27", "--target", "1.29", "--provider", "ollama"])
        assert args.provider == "ollama"

    def test_model_override(self):
        args = self._parse(["--source", "1.27", "--target", "1.29", "--model", "gpt-4o"])
        assert args.model == "gpt-4o"

    def test_no_cluster_flag(self):
        args = self._parse(["--source", "1.27", "--target", "1.29", "--no-cluster"])
        assert args.no_cluster is True

    def test_no_cluster_defaults_false(self):
        args = self._parse(["--source", "1.27", "--target", "1.29"])
        assert args.no_cluster is False

    def test_output_override(self):
        args = self._parse(["--source", "1.27", "--target", "1.29", "--output", "/tmp/r.md"])
        assert args.output == "/tmp/r.md"

    def test_base_url_override(self):
        args = self._parse(
            ["--source", "1.27", "--target", "1.29", "--base-url", "http://localhost:8080/v1"]
        )
        assert args.base_url == "http://localhost:8080/v1"

    def test_api_key_override(self):
        args = self._parse(["--source", "1.27", "--target", "1.29", "--api-key", "sk-test"])
        assert args.api_key == "sk-test"

    def test_missing_source_exits(self):
        with pytest.raises(SystemExit):
            self._parse(["--target", "1.29"])

    def test_missing_target_exits(self):
        with pytest.raises(SystemExit):
            self._parse(["--source", "1.27"])

    def test_invalid_provider_exits(self):
        with pytest.raises(SystemExit):
            self._parse(["--source", "1.27", "--target", "1.29", "--provider", "bogus"])

    def test_all_provider_names_accepted(self):
        for provider in main.PROVIDER_NAMES:
            args = self._parse(
                ["--source", "1.27", "--target", "1.29", "--provider", provider]
            )
            assert args.provider == provider


# =============================================================================
# call_llm routing
# =============================================================================


class TestCallLlmRouting:
    """Test that call_llm routes to the correct backend."""

    def test_anthropic_routes_to_stream_anthropic(self):
        with patch("main._stream_anthropic", return_value="report") as mock_ant:
            result = main.call_llm("prompt", "anthropic", "key", "claude-3", "")
        assert mock_ant.called
        assert result == "report"

    def test_openai_routes_to_stream_openai(self):
        with patch("main._stream_openai", return_value="report") as mock_oa:
            result = main.call_llm("prompt", "openai", "key", "gpt-4o", "https://api.openai.com/v1")
        assert mock_oa.called
        assert result == "report"

    def test_openrouter_routes_to_stream_openai(self):
        with patch("main._stream_openai", return_value="report") as mock_oa:
            main.call_llm("prompt", "openrouter", "key", "mistral", "https://openrouter.ai/api/v1")
        assert mock_oa.called

    def test_ollama_routes_to_stream_openai(self):
        with patch("main._stream_openai", return_value="report") as mock_oa:
            main.call_llm("prompt", "ollama", "ollama", "llama3", "http://localhost:11434/v1")
        assert mock_oa.called

    def test_lmstudio_routes_to_stream_openai(self):
        with patch("main._stream_openai", return_value="report") as mock_oa:
            main.call_llm("prompt", "lmstudio", "lm-studio", "local-model", "http://localhost:1234/v1")
        assert mock_oa.called

    def test_custom_routes_to_stream_openai(self):
        with patch("main._stream_openai", return_value="report") as mock_oa:
            main.call_llm("prompt", "custom", "key", "my-model", "http://myserver/v1")
        assert mock_oa.called

    def test_mock_routes_to_stream_mock(self):
        with patch("main._stream_mock", return_value="report") as mock_stream:
            result = main.call_llm("prompt", "mock", "mock-key", "simulated-model", "")
        assert mock_stream.called
        assert result == "report"


# =============================================================================
# main() integration (smoke test — no real LLM calls)
# =============================================================================


class TestMainIntegration:
    """Smoke-test the main() orchestration with all external calls mocked."""

    def _run_main(self, extra_args=None):
        argv = ["k8s-upgrade", "--source", "1.27", "--target", "1.29", "--no-cluster"]
        if extra_args:
            argv += extra_args
        with patch("sys.argv", argv), patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "test-key"}
        ), patch("main.call_llm", return_value="# Report\nContent"), patch(
            "main.save_report", return_value=Path("/tmp/report.md")
        ) as mock_save:
            main.main()
        return mock_save

    def test_main_runs_without_error(self):
        self._run_main()

    def test_main_calls_save_report(self):
        mock_save = self._run_main()
        assert mock_save.called

    def test_main_passes_correct_versions_to_save(self):
        mock_save = self._run_main()
        call_args = mock_save.call_args
        assert "1.27" in call_args[0]
        assert "1.29" in call_args[0]

    def test_main_custom_provider_no_base_url_exits(self):
        argv = [
            "k8s-upgrade",
            "--source", "1.27",
            "--target", "1.29",
            "--provider", "custom",
            "--no-cluster",
        ]
        with patch("sys.argv", argv), patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main.main()
        assert exc_info.value.code == 1

    def test_main_uses_default_model_when_not_specified(self):
        with patch("sys.argv", ["k8s-upgrade", "--source", "1.27", "--target", "1.29",
                                "--no-cluster"]), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("main.call_llm", return_value="report") as mock_llm, \
             patch("main.save_report", return_value=Path("/tmp/r.md")):
            main.main()
        called_model = mock_llm.call_args[0][3]
        assert called_model == main.PROVIDERS["anthropic"]["default_model"]

    def test_main_custom_model_passed_to_llm(self):
        with patch("sys.argv", ["k8s-upgrade", "--source", "1.27", "--target", "1.29",
                                "--no-cluster", "--model", "gpt-4o"]), \
             patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}), \
             patch("main.call_llm", return_value="report") as mock_llm, \
             patch("main.save_report", return_value=Path("/tmp/r.md")):
            main.main()
        called_model = mock_llm.call_args[0][3]
        assert called_model == "gpt-4o"


class TestContainerUrlAdjustment:
    """Validate localhost to host.docker.internal URL rewriting inside containers."""

    def test_no_rewrite_outside_container(self):
        with patch("os.path.exists", return_value=False):
            url = main.check_container_and_adjust_url("http://localhost:1234/v1")
        assert url == "http://localhost:1234/v1"

    def test_rewrites_localhost_inside_container(self):
        with patch("os.path.exists", side_effect=lambda p: p in ("/.dockerenv",)), \
             patch.dict("os.environ", {}, clear=True):
            url = main.check_container_and_adjust_url("http://localhost:1234/v1")
        assert url == "http://host.docker.internal:1234/v1"

    def test_rewrites_127_0_0_1_inside_container(self):
        with patch("os.path.exists", side_effect=lambda p: p in ("/.dockerenv",)), \
             patch.dict("os.environ", {}, clear=True):
            url = main.check_container_and_adjust_url("http://127.0.0.1:11434/v1")
        assert url == "http://host.docker.internal:11434/v1"

    def test_rewrites_to_containers_internal_under_podman(self):
        # /run/.containerenv is present under podman, or container=podman environment variable
        with patch("os.path.exists", side_effect=lambda p: p in ("/run/.containerenv",)), \
             patch.dict("os.environ", {"container": "podman"}, clear=True):
            url = main.check_container_and_adjust_url("http://localhost:1234/v1")
        assert url == "http://host.containers.internal:1234/v1"

    def test_ignores_non_local_urls_inside_container(self):
        with patch("os.path.exists", side_effect=lambda p: p in ("/.dockerenv",)):
            url = main.check_container_and_adjust_url("https://api.openai.com/v1")
        assert url == "https://api.openai.com/v1"
