#!/usr/bin/env python3
"""
Kubernetes Upgrade Risk Assessment CLI.

Universal AI backend — supports Anthropic, OpenAI, OpenRouter, Ollama,
LM Studio, and any OpenAI-compatible endpoint.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Type alias for provider config entries
# ─────────────────────────────────────────────────────────────────────────────

ProviderConfig = dict

# ─────────────────────────────────────────────────────────────────────────────
# Provider Registry
# Each entry describes how to connect and what defaults to use.
# ─────────────────────────────────────────────────────────────────────────────

PROVIDERS: dict[str, ProviderConfig] = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "base_url": None,  # uses native SDK
        "default_model": "claude-3-5-sonnet-20241022",
        "env_key": "ANTHROPIC_API_KEY",
        "requires_key": True,
        "protocol": "anthropic",  # uses anthropic SDK directly
    },
    "openai": {
        "label": "OpenAI (ChatGPT)",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "env_key": "OPENAI_API_KEY",
        "requires_key": True,
        "protocol": "openai",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-3.5-sonnet",
        "env_key": "OPENROUTER_API_KEY",
        "requires_key": True,
        "protocol": "openai",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/k8s-upgrade-assessment",
            "X-Title": "K8s Upgrade Risk Assessment",
        },
    },
    "ollama": {
        "label": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.1:70b",
        "env_key": None,
        "requires_key": False,
        "protocol": "openai",
        "api_key": "ollama",  # ollama ignores the key but openai SDK needs one
    },
    "lmstudio": {
        "label": "LM Studio (local)",
        "base_url": "http://localhost:1234/v1",
        "default_model": "local-model",
        "env_key": None,
        "requires_key": False,
        "protocol": "openai",
        "api_key": "lm-studio",
    },
    "custom": {
        "label": "Custom / Self-hosted",
        "base_url": None,  # must pass --base-url
        "default_model": "default",
        "env_key": "CUSTOM_API_KEY",
        "requires_key": False,
        "protocol": "openai",
        "api_key": "custom",
    },
    "mock": {
        "label": "Mock / Simulated Assessment (Offline)",
        "base_url": None,
        "default_model": "simulated-model",
        "env_key": None,
        "requires_key": False,
        "protocol": "mock",
        "api_key": "mock-key",
    },
}

PROVIDER_NAMES: list[str] = list(PROVIDERS.keys())

SYSTEM_PROMPT = (
    "You are a Senior Kubernetes Platform Engineer with deep expertise in "
    "cluster upgrades, API deprecations, operator compatibility, and production "
    "risk assessment. Produce exhaustive, evidence-based, conservative reports "
    "in clean Markdown. Never hide uncertainty. Always err on the side of caution."
)


# ─────────────────────────────────────────────────────────────────────────────
# Dependency check — lazy import so missing SDK only errors for chosen provider
# ─────────────────────────────────────────────────────────────────────────────


def _require_openai():
    """Lazily import and return the OpenAI client class."""
    try:
        from openai import OpenAI  # noqa: PLC0415

        return OpenAI
    except ImportError:
        print("[ERROR] openai package not installed.")
        print("  Run: pip install openai")
        sys.exit(1)


def _require_anthropic():
    """Lazily import and return the anthropic module."""
    try:
        import anthropic  # noqa: PLC0415

        return anthropic
    except ImportError:
        print("[ERROR] anthropic package not installed.")
        print("  Run: pip install anthropic")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# kubectl helpers
# ─────────────────────────────────────────────────────────────────────────────


def run_kubectl(args: list[str]) -> str:
    """Run a kubectl command and return stdout, or a descriptive error string."""
    cmd = ["kubectl"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"[ERROR]: {result.stderr.strip()}"
        return result.stdout.strip() or "(empty)"
    except FileNotFoundError:
        return "[ERROR]: kubectl not found in PATH"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]: command timed out after 30s"
    except Exception as exc:  # noqa: BLE001
        return f"[EXCEPTION]: {exc}"


def gather_cluster_data(no_cluster: bool) -> dict:
    """Collect cluster state via kubectl or return offline placeholder data."""
    if no_cluster:
        print("  [--no-cluster] Offline mode — using placeholder data.")
        return _offline_placeholder()

    print("  Collecting cluster state via kubectl...")

    commands: dict[str, list[str]] = {
        "version": ["version", "--output=json"],
        "cluster_info": ["cluster-info"],
        "nodes": ["get", "nodes", "-o", "wide"],
        "nodes_yaml": ["get", "nodes", "-o", "yaml"],
        "namespaces": ["get", "ns"],
        "api_resources": ["api-resources"],
        "api_services": ["get", "apiservices"],
        "all_resources": ["get", "all", "-A"],
        "deployments": ["get", "deploy", "-A", "-o", "wide"],
        "statefulsets": ["get", "sts", "-A", "-o", "wide"],
        "daemonsets": ["get", "ds", "-A", "-o", "wide"],
        "jobs": ["get", "jobs", "-A"],
        "cronjobs": ["get", "cronjobs", "-A"],
        "crds": ["get", "crd"],
        "crds_yaml": ["get", "crd", "-o", "yaml"],
        "validating_webhooks": ["get", "validatingwebhookconfigurations"],
        "mutating_webhooks": ["get", "mutatingwebhookconfigurations"],
        "storage_classes": ["get", "sc"],
        "pvs": ["get", "pv"],
        "pvcs": ["get", "pvc", "-A"],
        "ingresses": ["get", "ingress", "-A"],
        "network_policies": ["get", "networkpolicies", "-A"],
        "pod_security": ["get", "podsecuritypolicies"],
        "cluster_roles": ["get", "clusterroles", "--no-headers"],
        "top_nodes": ["top", "nodes"],
        "top_pods": ["top", "pods", "-A", "--sort-by=memory"],
        "events": ["get", "events", "-A", "--sort-by=.lastTimestamp"],
        "services": ["get", "svc", "-A"],
        "config_maps": ["get", "configmaps", "-A", "--no-headers"],
    }

    sections: dict[str, str] = {}
    for key, cmd_args in commands.items():
        print(f"    → kubectl {' '.join(cmd_args)}")
        sections[key] = run_kubectl(cmd_args)

    return sections


def _offline_placeholder() -> dict:
    """Return rich placeholder cluster data for offline / demo mode."""
    return {
        "version": json.dumps(
            {
                "clientVersion": {"gitVersion": "v1.27.0"},
                "serverVersion": {"gitVersion": "v1.27.3"},
            }
        ),
        "nodes": (
            "NAME       STATUS   ROLES           AGE   VERSION   "
            "OS-IMAGE             CONTAINER-RUNTIME\n"
            "master-1   Ready    control-plane   90d   v1.27.3   "
            "Ubuntu 22.04.3 LTS   containerd://1.7.2\n"
            "worker-1   Ready    <none>          90d   v1.27.3   "
            "Ubuntu 22.04.3 LTS   containerd://1.7.2\n"
            "worker-2   Ready    <none>          89d   v1.27.3   "
            "Ubuntu 22.04.3 LTS   containerd://1.7.2"
        ),
        "namespaces": (
            "NAME              STATUS   AGE\n"
            "default           Active   90d\n"
            "kube-system       Active   90d\n"
            "monitoring        Active   60d\n"
            "ingress-nginx     Active   55d\n"
            "cert-manager      Active   55d\n"
            "argocd            Active   40d"
        ),
        "deployments": (
            "NAMESPACE       NAME                      READY   UP-TO-DATE   AVAILABLE   AGE\n"
            "kube-system     coredns                   2/2     2            2           90d\n"
            "monitoring      prometheus-operator        1/1     1            1           60d\n"
            "monitoring      grafana                   1/1     1            1           60d\n"
            "ingress-nginx   ingress-nginx-controller  1/1     1            1           55d\n"
            "cert-manager    cert-manager              1/1     1            1           55d\n"
            "argocd          argocd-server             1/1     1            1           40d"
        ),
        "crds": (
            "NAME\n"
            "certificates.cert-manager.io\n"
            "clusterissuers.cert-manager.io\n"
            "prometheusrules.monitoring.coreos.com\n"
            "servicemonitors.monitoring.coreos.com\n"
            "applications.argoproj.io\n"
            "appprojects.argoproj.io"
        ),
        "validating_webhooks": "NAME\ncert-manager-webhook\ningress-nginx-admission",
        "mutating_webhooks": "NAME\ncert-manager-webhook",
        "storage_classes": (
            "NAME              PROVISIONER                    RECLAIMPOLICY\n"
            "standard          kubernetes.io/no-provisioner   Delete\n"
            "gp2 (default)     kubernetes.io/aws-ebs          Delete"
        ),
        "pvs": "(no PVs found)",
        "pvcs": "(no PVCs found)",
        "top_nodes": (
            "NAME       CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%\n"
            "master-1   312m          8%    2048Mi           55%\n"
            "worker-1   890m         22%    4096Mi           52%\n"
            "worker-2   640m         16%    3200Mi           41%"
        ),
        "_offline_mode": "true",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────


_REPORT_SECTIONS = """\
## Your Task

Produce a COMPLETE Kubernetes Upgrade Feasibility, Compatibility, and Risk Assessment.

The report must cover ALL sections in order:

1. **Cluster Inventory Summary** — versions, nodes, runtimes, HA topology
2. **Workload Inventory** — namespaces, deployments, statefulsets, daemonsets, jobs
3. **CRD Inventory** — all CRDs with group, kind, versions, storage version
4. **Controller / Operator Inventory** — installed version, supported K8s range,
   risk classification
5. **Kubernetes Release Notes Analysis** — breaking changes, removals, deprecations
   for EVERY minor version between source and target (do NOT skip versions)
6. **API Removal Analysis** — for every removed API found in the cluster:
   Namespace / Object / Kind / Current API / Removal Version / Impact /
   Required Action — classify CRITICAL if workload fails
7. **Deprecated API Analysis** — APIs deprecated but not yet removed
8. **CRD Compatibility Analysis** — for each CRD: storage version supported?
   will objects deserialize? Could this CRD break? YES/NO + reason
9. **Controller Compatibility Analysis** — PASS / GOOD / WARNING / HIGH RISK /
   CRITICAL — upgrade timing: Before / After / Optional
10. **Admission Webhook Analysis** — can webhooks fail post-upgrade? FailurePolicy?
11. **Networking Compatibility** — CNI, CoreDNS, ingress, kube-proxy
12. **Storage Compatibility** — CSI drivers, snapshot API, PV/PVC risks
13. **Security Compatibility** — PSP removal, Pod Security Admission, RBAC changes
14. **Runtime Compatibility** — CRI, containerd/docker, OS, kernel
15. **Resource Pressure Analysis** — CPU/memory/eviction risks during upgrade
16. **Upgrade Simulation** — per area: Control Plane / Nodes / APIs / CRDs /
    Controllers / Networking / Storage / Security →
    PASS | GOOD | WARNING | HIGH RISK | CRITICAL + Reason
17. **Failure Scenario Analysis** — YES/NO + reason for:
    - Could workloads fail to start?
    - Could controllers crash?
    - Could CRDs become unreadable?
    - Could CRD controllers stop reconciling?
    - Could admission webhooks block deployments?
    - Could storage become inaccessible?
    - Could networking break?
    - Could node upgrades fail?
    - Could kubelets fail to register?
    - Could the control plane fail?
18. **Risk Matrix Table** — APIs / CRDs / Controllers / Webhooks / Networking /
    Storage / Security / Runtime / Nodes / Control Plane →
    Status | Severity | Explanation
19. **Readiness Score** — XX/100
    (90-100 Ready · 75-89 Remediation needed · 50-74 Significant risk ·
    0-49 Not recommended)
20. **Confidence Score** — XX% based on data completeness
21. **Executive Summary**:
    UPGRADE DECISION: APPROVED / CONDITIONAL / NOT RECOMMENDED,
    Critical Issues, High Risks, Warnings, Required Actions Before Upgrade,
    Recommended Upgrade Order, Post-Upgrade Validations, Final Recommendation

---

## Mandatory Rules

For EVERY incompatibility found, output:
```
WHAT WILL BREAK:
WHEN IT WILL BREAK: (Control Plane Upgrade / Node Upgrade / Immediately After /
                     First Reconciliation / First Deployment)
IMPACT: (Outage / Partial Outage / Reconciliation Failure / Deployment Failure /
         Data Risk)
SEVERITY: (Critical / High / Medium / Low)
REMEDIATION:
```

Classify findings as:
- ✅ Verified Issues
- ⚠️  Probable Issues
- 🔍 Possible Issues
- ❓ Unknown Risks

Unknown risks MUST reduce the confidence score.
Be exhaustive. Be conservative. Use Markdown headers, tables, code blocks, emoji.
"""


def build_prompt(source: str, target: str, cluster_data: dict) -> str:
    """Build the full assessment prompt with embedded cluster data."""
    data_dump = "\n\n".join(
        f"### {key.upper().replace('_', ' ')}\n```\n{value}\n```"
        for key, value in cluster_data.items()
        if not key.startswith("_")
    )

    offline_note = ""
    if cluster_data.get("_offline_mode"):
        offline_note = "\n> ⚠️  OFFLINE MODE: placeholder data — illustrative only.\n"

    header = (
        "You are a Senior Kubernetes Platform Engineer performing a comprehensive "
        "upgrade readiness review.\n"
        f"{offline_note}\n"
        f"## Upgrade Target\n\n"
        f"- SOURCE VERSION: {source}\n"
        f"- TARGET VERSION: {target}\n"
        f"- CLUSTER TYPE: Self-managed (kubeadm)\n\n"
        f"---\n\n"
        f"## Cluster Data Collected\n\n"
        f"{data_dump}\n\n"
        f"---\n\n"
    )
    return header + _REPORT_SECTIONS


# ─────────────────────────────────────────────────────────────────────────────
# AI backends
# ─────────────────────────────────────────────────────────────────────────────


def _stream_openai(
    prompt: str,
    provider_cfg: ProviderConfig,
    api_key: str,
    model: str,
    base_url: str,
) -> str:
    """Stream a response from any OpenAI-compatible endpoint."""
    OpenAI = _require_openai()
    client = OpenAI(api_key=api_key, base_url=base_url)
    extra_headers: dict = provider_cfg.get("extra_headers", {}) or {}

    stream = client.chat.completions.create(
        model=model,
        max_tokens=8000,
        stream=True,
        extra_headers=extra_headers if extra_headers else None,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    full: list[str] = []
    for chunk in stream:
        text = chunk.choices[0].delta.content or ""
        print(text, end="", flush=True)
        full.append(text)
    return "".join(full)


def _stream_anthropic(prompt: str, model: str, api_key: str) -> str:
    """Stream a response from the native Anthropic SDK."""
    anthropic = _require_anthropic()
    client = anthropic.Anthropic(api_key=api_key)

    full: list[str] = []
    with client.messages.stream(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            full.append(text)
    return "".join(full)


def _stream_mock(prompt: str, model: str) -> str:
    """Stream a simulated Kubernetes upgrade report for testing and demo purposes."""
    import time

    report = """## 1. Cluster Inventory Summary
- **Source Version:** v1.27.3
- **Target Version:** v1.29.0
- **Nodes:** 3 (1 control-plane, 2 workers)
- **OS:** Ubuntu 22.04.3 LTS
- **CRI:** containerd://1.7.2
- **Topology:** Single-control-plane dev/test cluster

## 2. Workload Inventory
- **Namespaces:** `default`, `kube-system`, `monitoring`, `ingress-nginx`, `cert-manager`, `argocd`
- **Deployments:** `coredns`, `prometheus-operator`, `grafana`,
  `ingress-nginx-controller`, `cert-manager`, `argocd-server`
- **CRDs:** `certificates.cert-manager.io`, `clusterissuers.cert-manager.io`,
  `prometheusrules.monitoring.coreos.com`, `servicemonitors.monitoring.coreos.com`,
  `applications.argoproj.io`, `appprojects.argoproj.io`

## 3. Kubernetes Release Notes Analysis (v1.27 → v1.29)
### v1.28 Major Changes
- **CSI Migration:** Storage limits enforcement for CSI drivers.
- **ValidatingAdmissionPolicy:** Graduated to Beta (enabled by default).

### v1.29 Major Changes
- **Legacy Cloud Providers:** Complete removal of in-tree cloud providers.
- **Kubelet:** ReadOnlyPort is deprecated and defaults to 0.

## 4. API Removal Analysis
- **Resource:** `policy/v1beta1` (PodSecurityPolicy)
  - **Status:** Removed in v1.25 (Still present in configurations but unsupported).
  - **Workloads Impacted:** None (verified).
- **Resource:** `flowcontrol.apiserver.k8s.io/v1beta2` (FlowSchema, PriorityLevelConfiguration)
  - **Status:** Removed in v1.29 (Migrate to `v1`).
  - **Workloads Impacted:** APIServer configuration.

## 5. Upgrade Simulation
- **Control Plane:** GOOD
- **Worker Nodes:** GOOD
- **APIs:** WARNING (check FlowControl versions)
- **Networking:** GOOD
- **Storage:** GOOD

## 6. Readiness Score: 88/100 (Remediation Needed)
- **Confidence Score:** 95% (Rich local data)

## 7. Executive Summary
- **Decision:** CONDITIONAL APPROVED
- **Actions Required:** Ensure all FlowSchema objects are migrated to
  `flowcontrol.apiserver.k8s.io/v1` before proceeding.
"""

    print("  [MOCK] Simulating AI analysis stream...")
    full_text = []
    for line in report.split("\n"):
        print(line)
        full_text.append(line)
        time.sleep(0.05)
    return "\n".join(full_text)


def call_llm(
    prompt: str,
    provider: str,
    api_key: str,
    model: str,
    base_url: str,
) -> str:
    """Universal LLM caller — routes to the correct backend."""
    cfg: ProviderConfig = PROVIDERS[provider]
    protocol: str = cfg["protocol"]

    print(f"\n  Provider  : {cfg['label']}")
    print(f"  Model     : {model}")
    print(f"  Endpoint  : {base_url or 'native SDK'}")
    print(f"  Protocol  : {protocol}")
    print("\n" + "─" * 70 + "\n")

    if protocol == "mock" or api_key.lower() == "dummy":
        if api_key.lower() == "dummy" and protocol != "mock":
            print("  ⚠️  WARNING: Dummy API key detected. Falling back to mock/simulation mode.")
        return _stream_mock(prompt, model)

    if protocol == "anthropic":
        return _stream_anthropic(prompt, model, api_key)
    return _stream_openai(prompt, cfg, api_key, model, base_url)


# ─────────────────────────────────────────────────────────────────────────────
# Report saver
# ─────────────────────────────────────────────────────────────────────────────


def save_report(
    content: str,
    source: str,
    target: str,
    provider: str,
    model: str,
    output: Optional[str],
) -> Path:
    """Persist the Markdown report to disk and return its Path."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    src_safe = source.replace(".", "")
    tgt_safe = target.replace(".", "")

    if output:
        out_path = Path(output)
    else:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        out_path = reports_dir / f"k8s_upgrade_{src_safe}_to_{tgt_safe}_{timestamp}.md"

    provider_label: str = PROVIDERS[provider]["label"]
    header = (
        f"# Kubernetes Upgrade Risk Assessment\n"
        f"**Source:** v{source} → **Target:** v{target}  \n"
        f"**Generated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
        f"**Provider:** {provider_label} · `{model}`  \n"
        f"**Tool:** k8s-upgrade-assessment CLI\n\n---\n\n"
    )
    out_path.write_text(header + content, encoding="utf-8")
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# API key resolver
# ─────────────────────────────────────────────────────────────────────────────


def resolve_api_key(provider: str, cli_key: Optional[str]) -> str:
    """
    Resolve the API key with the following priority:
    1. Explicit --api-key CLI flag
    2. Provider-specific environment variable
    3. Generic LLM_API_KEY fallback
    4. Hardcoded dummy key for local/keyless providers
    5. Exit with a clear error message
    """
    cfg: ProviderConfig = PROVIDERS[provider]

    if cli_key:
        return cli_key

    env_var: Optional[str] = cfg.get("env_key")
    if env_var:
        val = os.environ.get(env_var, "")
        if val:
            return val

    generic = os.environ.get("LLM_API_KEY", "")
    if generic:
        return generic

    if not cfg.get("requires_key"):
        return cfg.get("api_key", "no-key-required")

    env_hint = env_var or "LLM_API_KEY"
    print(f"\n[ERROR] API key required for provider '{provider}'.")
    print(f"  Set env var : {env_hint}=<your-key>")
    print("  Or pass    : --api-key <your-key>")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="k8s-upgrade",
        description="Kubernetes Upgrade Risk Assessment — Universal AI CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Supported providers: {', '.join(PROVIDER_NAMES)}

Examples:
  # Anthropic Claude (default)
  python main.py --source 1.27 --target 1.29 --provider anthropic

  # OpenAI GPT-4o
  python main.py --source 1.27 --target 1.29 --provider openai

  # OpenRouter with a specific model
  python main.py --source 1.27 --target 1.29 --provider openrouter \\
    --model mistralai/mistral-large

  # Ollama local (no API key needed)
  python main.py --source 1.27 --target 1.29 --provider ollama \\
    --model llama3.1:70b

  # LM Studio local (no API key needed)
  python main.py --source 1.27 --target 1.29 --provider lmstudio \\
    --model lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF

  # Custom / self-hosted OpenAI-compatible endpoint
  python main.py --source 1.27 --target 1.29 --provider custom \\
    --base-url http://myserver:8000/v1 --model my-model

  # Offline / demo mode (no cluster, no kubectl)
  python main.py --source 1.27 --target 1.29 --no-cluster
        """,
    )

    parser.add_argument("--source", required=True, help="Source Kubernetes version (e.g. 1.27)")
    parser.add_argument("--target", required=True, help="Target Kubernetes version (e.g. 1.29)")
    parser.add_argument(
        "--provider",
        default="anthropic",
        choices=PROVIDER_NAMES,
        help=f"AI provider (default: anthropic). Choices: {', '.join(PROVIDER_NAMES)}",
    )
    parser.add_argument("--model", default=None, help="Model name/slug — overrides provider default")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override API base URL (useful for custom/self-hosted)",
    )
    parser.add_argument("--api-key", default=None, help="API key — overrides env var")
    parser.add_argument(
        "--no-cluster",
        action="store_true",
        help="Skip kubectl — use placeholder data (demo/offline mode)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output .md file path (default: reports/k8s_upgrade_*.md)",
    )
    return parser.parse_args()


def banner(source: str, target: str, provider: str, no_cluster: bool) -> None:
    """Print the startup banner."""
    label: str = PROVIDERS[provider]["label"]
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║      KUBERNETES UPGRADE RISK ASSESSMENT                         ║")
    print("║      Universal AI-Powered — Senior Platform Engineer Analysis   ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Source  : v{source}")
    print(f"  Target  : v{target}")
    print(f"  AI      : {label}")
    print(f"  Cluster : {'OFFLINE (--no-cluster)' if no_cluster else 'LIVE (kubectl)'}")
    print()


def main() -> None:
    """Entry point — orchestrates the four assessment stages."""
    args = parse_args()

    provider = args.provider
    cfg: ProviderConfig = PROVIDERS[provider]

    model: str = args.model or cfg["default_model"]
    base_url: str = args.base_url or cfg.get("base_url") or ""

    if provider == "custom" and not base_url:
        print("[ERROR] --provider custom requires --base-url <endpoint>")
        sys.exit(1)

    api_key = resolve_api_key(provider, args.api_key)
    banner(args.source, args.target, provider, args.no_cluster)

    # ── 1/4  Gather ───────────────────────────────────────────────────────────
    print("[1/4] Gathering cluster information...")
    cluster_data = gather_cluster_data(no_cluster=args.no_cluster)
    count = len([k for k in cluster_data if not k.startswith("_")])
    print(f"  ✓ Collected {count} data sections\n")

    # ── 2/4  Build prompt ─────────────────────────────────────────────────────
    print("[2/4] Building assessment prompt...")
    prompt = build_prompt(args.source, args.target, cluster_data)
    print(f"  ✓ Prompt size: {len(prompt):,} characters\n")

    # ── 3/4  Call LLM ─────────────────────────────────────────────────────────
    print("[3/4] Running AI analysis (streaming)...")
    report_content = call_llm(prompt, provider, api_key, model, base_url)

    # ── 4/4  Save ─────────────────────────────────────────────────────────────
    print("\n\n[4/4] Saving report...")
    out_path = save_report(report_content, args.source, args.target, provider, model, args.output)
    print(f"  ✓ Report saved → {out_path.resolve()}\n")
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║  Assessment complete. Review the report before any upgrade.     ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    main()
