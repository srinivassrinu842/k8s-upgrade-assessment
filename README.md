# Kubernetes Upgrade Risk Assessment CLI

> **AI-powered, provider-agnostic Kubernetes upgrade readiness tool.**  
> Connects to your cluster via `kubectl`, collects comprehensive state data, and uses any LLM to generate an exhaustive risk assessment report in Markdown.

[![CI/CD](https://github.com/your-org/k8s-upgrade-assessment/actions/workflows/ci-cd.yaml/badge.svg)](https://github.com/your-org/k8s-upgrade-assessment/actions/workflows/ci-cd.yaml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-blue?logo=docker)](https://ghcr.io/your-org/k8s-upgrade-assessment)
[![Coverage: 81%](https://img.shields.io/badge/coverage-81%25-brightgreen.svg)]()

---

## Table of Contents

- [Overview](#overview)
- [Supported AI Providers](#supported-ai-providers)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
  - [Local (Python)](#option-a--local-python)
  - [Docker](#option-b--docker-recommended)
- [Usage](#usage)
  - [Cloud providers](#cloud-providers)
  - [Local models (Ollama / LM Studio)](#local-models-ollama--lm-studio)
  - [Custom / self-hosted endpoint](#custom--self-hosted-endpoint)
  - [Offline / demo mode](#offline--demo-mode)
  - [All CLI flags](#all-cli-flags)
- [Docker Reference](#docker-reference)
  - [Build the image](#build-the-image)
  - [Run with a live cluster](#run-with-a-live-cluster)
  - [Run in offline mode](#run-in-offline-mode)
  - [Run with Ollama (fully local)](#run-with-ollama-fully-local)
- [Report Contents](#report-contents)
- [Output Format](#output-format)
- [Development](#development)
  - [Setup dev environment](#setup-dev-environment)
  - [Linting](#linting)
  - [Running tests](#running-tests)
  - [Project conventions](#project-conventions)
- [CI/CD Pipeline](#cicd-pipeline)
- [API Key Resolution](#api-key-resolution)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Overview

This CLI tool performs a **comprehensive, AI-driven Kubernetes upgrade feasibility assessment**. It:

1. Runs ~28 read-only `kubectl` commands to snapshot your cluster state
2. Builds a structured prompt embedding all gathered data
3. Streams an exhaustive analysis from your chosen LLM
4. Saves the full Markdown report to disk

The assessment covers API removals, CRD compatibility, controller/operator risks, webhooks, networking, storage, security policy changes, runtime compatibility, resource pressure, and produces a **Readiness Score (0–100)** with an **APPROVED / CONDITIONAL / NOT RECOMMENDED** executive decision.

> The tool is **100% read-only** — it never modifies your cluster state.

---

## Supported AI Providers

| Provider | `--provider` | API Key Needed | Default Model |
|---|---|:---:|---|
| **Anthropic Claude** | `anthropic` | ✅ | `claude-3-5-sonnet-20241022` |
| **OpenAI** | `openai` | ✅ | `gpt-4o` |
| **OpenRouter** | `openrouter` | ✅ | `anthropic/claude-3.5-sonnet` |
| **Ollama** (local) | `ollama` | ❌ | `llama3.1:70b` |
| **LM Studio** (local) | `lmstudio` | ❌ | `local-model` |
| **Custom / self-hosted** | `custom` | optional | `default` |

Any OpenAI-compatible endpoint works with `--provider custom --base-url <url>` — including vLLM, LocalAI, Jan, GPT4All, text-generation-webui, and more.

---

## Project Structure

```
k8s-upgrade-assessment/
├── main.py                        # CLI entry point — all application logic
├── tests/
│   ├── __init__.py
│   └── test_main.py               # 72 unit tests, 81% coverage
├── .github/
│   └── workflows/
│       └── ci-cd.yaml             # 6-job CI/CD pipeline
├── Dockerfile                     # 2-stage build (builder + runtime)
├── .dockerignore
├── pyproject.toml                 # Tool configuration (black, isort, mypy, pytest, coverage)
├── setup.cfg                      # flake8 configuration
├── requirements.txt               # Runtime dependencies
├── requirements-dev.txt           # Dev/CI dependencies
├── .env.example                   # API key template
├── .gitignore
└── reports/                       # Generated reports (git-ignored)
```

---

## Quick Start

### Option A — Local (Python)

**Requirements:** Python 3.11+, `kubectl` configured

```bash
# 1. Clone
git clone https://github.com/your-org/k8s-upgrade-assessment.git
cd k8s-upgrade-assessment

# 2. Install runtime dependencies
pip install -r requirements.txt

# 3. Set your API key
export ANTHROPIC_API_KEY=sk-ant-...    # Anthropic
# OR
export OPENAI_API_KEY=sk-...           # OpenAI
# OR
export OPENROUTER_API_KEY=sk-or-...    # OpenRouter
# Local providers (Ollama, LM Studio) need no key

# 4. Run
python main.py --source 1.27 --target 1.29
```

### Option B — Docker (recommended)

No Python installation needed. kubectl is bundled inside the image.

```bash
# Pull from GitHub Container Registry
docker pull ghcr.io/your-org/k8s-upgrade-assessment:latest

# Run against your live cluster
docker run --rm \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v ~/.kube:/root/.kube:ro \
  -v $(pwd)/reports:/app/reports \
  ghcr.io/your-org/k8s-upgrade-assessment:latest \
  --source 1.27 --target 1.29 --provider anthropic
```

---

## Usage

### Cloud providers

```bash
# Anthropic Claude (default provider)
python main.py --source 1.27 --target 1.29 --provider anthropic

# Specific Claude model
python main.py --source 1.27 --target 1.29 --provider anthropic \
  --model claude-opus-4-5-20251101

# OpenAI GPT-4o
python main.py --source 1.27 --target 1.29 --provider openai

# OpenAI with a different model
python main.py --source 1.27 --target 1.29 --provider openai \
  --model gpt-4-turbo

# OpenRouter — any model from openrouter.ai/models
python main.py --source 1.27 --target 1.29 --provider openrouter \
  --model mistralai/mistral-large

python main.py --source 1.27 --target 1.29 --provider openrouter \
  --model google/gemini-pro-1.5
```

### Local models (Ollama / LM Studio)

```bash
# Ollama — start server first: ollama serve
python main.py --source 1.27 --target 1.29 --provider ollama \
  --model llama3.1:70b

python main.py --source 1.27 --target 1.29 --provider ollama \
  --model deepseek-r1:70b

# LM Studio — start the local server in the LM Studio UI first
python main.py --source 1.27 --target 1.29 --provider lmstudio \
  --model lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF
```

> 💡 Local providers run **fully air-gapped** — no cluster data leaves your machine.

### Custom / self-hosted endpoint

```bash
# Any OpenAI-compatible server
python main.py --source 1.27 --target 1.29 \
  --provider custom \
  --base-url http://myserver:8000/v1 \
  --model my-model

# vLLM
python main.py --source 1.27 --target 1.29 \
  --provider custom \
  --base-url http://localhost:8000/v1 \
  --model meta-llama/Meta-Llama-3-70B-Instruct

# LocalAI
python main.py --source 1.27 --target 1.29 \
  --provider custom \
  --base-url http://localhost:8080/v1 \
  --model gpt-4
```

### Offline / demo mode

```bash
# No cluster access, no API key — uses rich built-in placeholder data
# Useful for CI smoke tests or evaluating the tool before connecting a cluster
python main.py --source 1.27 --target 1.29 --no-cluster
```

### All CLI flags

```
usage: k8s-upgrade [-h] --source SOURCE --target TARGET
                   [--provider {anthropic,openai,openrouter,ollama,lmstudio,custom}]
                   [--model MODEL]
                   [--base-url BASE_URL]
                   [--api-key API_KEY]
                   [--no-cluster]
                   [--output OUTPUT]

Options:
  --source SOURCE     Source Kubernetes version (e.g. 1.27)          [required]
  --target TARGET     Target Kubernetes version (e.g. 1.29)          [required]
  --provider          AI backend to use (default: anthropic)
  --model             Model name/slug — overrides provider default
  --base-url          API base URL — required for --provider custom
  --api-key           API key — overrides environment variable
  --no-cluster        Skip kubectl, use placeholder data (offline/demo mode)
  --output            Output file path (default: reports/k8s_upgrade_*.md)
  -h, --help          Show this help message and exit
```

---

## Docker Reference

### Build the image

```bash
# Build locally
docker build -t k8s-upgrade-assessment .

# Build with a specific kubectl version
docker build --build-arg KUBECTL_VERSION=v1.30.0 -t k8s-upgrade-assessment .
```

### Run with a live cluster

```bash
# Anthropic
docker run --rm \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v ~/.kube:/root/.kube:ro \
  -v $(pwd)/reports:/app/reports \
  k8s-upgrade-assessment \
  --source 1.27 --target 1.29 --provider anthropic

# OpenAI
docker run --rm \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v ~/.kube:/root/.kube:ro \
  -v $(pwd)/reports:/app/reports \
  k8s-upgrade-assessment \
  --source 1.28 --target 1.30 --provider openai

# OpenRouter
docker run --rm \
  -e OPENROUTER_API_KEY=$OPENROUTER_API_KEY \
  -v ~/.kube:/root/.kube:ro \
  -v $(pwd)/reports:/app/reports \
  k8s-upgrade-assessment \
  --source 1.27 --target 1.29 --provider openrouter \
  --model mistralai/mistral-large

# Multi-version jump (1.26 → 1.30)
docker run --rm \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v ~/.kube:/root/.kube:ro \
  -v $(pwd)/reports:/app/reports \
  k8s-upgrade-assessment \
  --source 1.26 --target 1.30
```

### Run in offline mode

```bash
# No cluster, no API key needed — great for CI smoke tests
docker run --rm \
  -v $(pwd)/reports:/app/reports \
  k8s-upgrade-assessment \
  --source 1.27 --target 1.29 --no-cluster --provider anthropic \
  --api-key dummy
```

### Run with Ollama (fully local, air-gapped)

```bash
# Ollama must be running on the host — use host networking so the container can reach it
docker run --rm \
  --network host \
  -v ~/.kube:/root/.kube:ro \
  -v $(pwd)/reports:/app/reports \
  k8s-upgrade-assessment \
  --source 1.27 --target 1.29 --provider ollama --model llama3.1:70b
```

### Volume mount reference

| Mount | Purpose |
|---|---|
| `-v ~/.kube:/root/.kube:ro` | Kubeconfig for live cluster access (read-only) |
| `-v $(pwd)/reports:/app/reports` | Output directory — reports appear here on the host |

---

## Report Contents

Every report covers 21 sections:

| # | Section | What it covers |
|---|---|---|
| 1 | **Cluster Inventory Summary** | Versions, nodes, runtimes, HA topology |
| 2 | **Workload Inventory** | Namespaces, deployments, statefulsets, daemonsets, jobs |
| 3 | **CRD Inventory** | All CRDs with group, kind, versions, storage version |
| 4 | **Controller / Operator Inventory** | Installed version, supported K8s range, risk class |
| 5 | **Release Notes Analysis** | Breaking changes for every minor version in range |
| 6 | **API Removal Analysis** | Every removed API found in cluster — CRITICAL if fatal |
| 7 | **Deprecated API Analysis** | Deprecated but not yet removed |
| 8 | **CRD Compatibility** | Storage version, deserialization, break risk YES/NO |
| 9 | **Controller Compatibility** | PASS → CRITICAL, timing: Before / After / Optional |
| 10 | **Admission Webhook Analysis** | Post-upgrade failure risk, FailurePolicy impact |
| 11 | **Networking Compatibility** | CNI, CoreDNS, ingress, kube-proxy |
| 12 | **Storage Compatibility** | CSI drivers, snapshot API, PV/PVC risks |
| 13 | **Security Compatibility** | PSP removal, Pod Security Admission, RBAC |
| 14 | **Runtime Compatibility** | CRI, containerd, OS, kernel |
| 15 | **Resource Pressure Analysis** | CPU/memory/eviction risks during upgrade |
| 16 | **Upgrade Simulation** | Per-area status: PASS → CRITICAL |
| 17 | **Failure Scenario Analysis** | 10 explicit YES/NO questions |
| 18 | **Risk Matrix Table** | 10 areas × Status / Severity / Explanation |
| 19 | **Readiness Score** | 0–100 with scoring legend |
| 20 | **Confidence Score** | % based on data completeness |
| 21 | **Executive Summary** | APPROVED / CONDITIONAL / NOT RECOMMENDED + action plan |

---

## Output Format

Reports are saved as Markdown files:

```
reports/k8s_upgrade_127_to_129_20241215_143022.md
```

The report header includes full traceability metadata:

```markdown
# Kubernetes Upgrade Risk Assessment
**Source:** v1.27 → **Target:** v1.29
**Generated:** 2024-12-15 14:30:22
**Provider:** Anthropic (Claude) · `claude-3-5-sonnet-20241022`
**Tool:** k8s-upgrade-assessment CLI
```

---

## Development

### Setup dev environment

```bash
# Clone
git clone https://github.com/your-org/k8s-upgrade-assessment.git
cd k8s-upgrade-assessment

# Install all dev dependencies (lint + test tools)
pip install -r requirements-dev.txt
```

### Linting

All lint tools are configured centrally in `pyproject.toml` and `setup.cfg`.

```bash
# Run all lint checks
flake8 main.py                    # style, logic, unused expressions
black --check main.py             # formatting
isort --check-only main.py        # import order
mypy main.py --ignore-missing-imports  # type checking

# Auto-fix formatting
black main.py && isort main.py
```

Expected output when clean:

```
flake8  ✓  (no output)
black   ✓  All done! ✨ 🍰 ✨
isort   ✓  All done! ✨ 🍰 ✨
mypy    ✓  Success: no issues found in 1 source file
```

### Running tests

```bash
# Run all tests with coverage
pytest tests/ -v --cov=main --cov-report=term-missing

# Run a specific test class
pytest tests/test_main.py::TestProviderRegistry -v

# Run with coverage threshold enforcement (75% minimum)
pytest tests/ --cov=main --cov-fail-under=75
```

**Current test results:**

```
72 passed in 0.26s
Coverage: 81% (178 statements, 33 missed)
```

**Test classes:**

| Class | Tests | What it covers |
|---|---|---|
| `TestProviderRegistry` | 8 | Provider config shape, required keys, protocols |
| `TestRunKubectl` | 7 | subprocess calls, error/timeout/not-found handling |
| `TestOfflinePlaceholder` | 6 | Placeholder data structure and content |
| `TestGatherClusterData` | 4 | Live vs offline routing, minimum sections collected |
| `TestBuildPrompt` | 8 | Prompt content, offline flag, private key exclusion |
| `TestResolveApiKey` | 8 | Priority chain: CLI → env → fallback → dummy → exit |
| `TestSaveReport` | 6 | File creation, metadata, UTF-8 encoding |
| `TestParseArgs` | 13 | All flags, defaults, invalid inputs, all providers |
| `TestCallLlmRouting` | 6 | Each provider routes to the correct backend |
| `TestMainIntegration` | 6 | End-to-end orchestration with mocked LLM |

### Project conventions

| Tool | Config location | Rule |
|---|---|---|
| black | `pyproject.toml` | `line-length = 120` |
| isort | `pyproject.toml` | `profile = "black"` |
| flake8 | `setup.cfg` | `max-line-length = 120` |
| mypy | `pyproject.toml` | `strict_optional = true` |
| pytest | `pyproject.toml` | `testpaths = ["tests"]` |
| coverage | `pyproject.toml` | `fail_under = 75` |

---

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci-cd.yaml`) runs 6 jobs:

```
push / PR
    │
    ▼
┌─────────┐     ┌──────────┐     ┌─────────────┐     ┌──────────────┐
│  lint   │────▶│   test   │────▶│ smoke-test  │────▶│ docker-build │
│         │     │ (3.11 +  │     │  (offline,  │     │ + trivy scan │
│ flake8  │     │  3.12)   │     │  no key)    │     │              │
│ black   │     │ coverage │     │             │     │              │
│ isort   │     │ codecov  │     │             │     │              │
│ mypy    │     │          │     │             │     │              │
└─────────┘     └──────────┘     └─────────────┘     └──────┬───────┘
                                                             │
                                              (main branch or v* tag only)
                                                             │
                                                    ┌────────▼────────┐
                                                    │    publish      │
                                                    │ ghcr.io multi-  │
                                                    │ arch amd64+arm64│
                                                    └────────┬────────┘
                                                             │
                                                    (v* tag only)
                                                             │
                                                    ┌────────▼────────┐
                                                    │    release      │
                                                    │ GitHub Release  │
                                                    │ + changelog     │
                                                    └─────────────────┘
```

| Job | Trigger | Actions |
|---|---|---|
| **lint** | every push / PR | flake8, black, isort, mypy |
| **test** | after lint | pytest on Python 3.11 + 3.12, coverage upload to Codecov |
| **smoke-test** | after test | `--help` check + offline prompt build (no API key) |
| **docker-build** | after smoke | Build image, Trivy CVE scan, upload SARIF to Security tab |
| **publish** | `main` branch or `v*` tag | Multi-arch image pushed to GHCR (`amd64` + `arm64`) |
| **release** | `v*` tag only | GitHub Release created with auto-generated changelog |

### Release a new version

```bash
git tag v1.2.0
git push origin v1.2.0
# → triggers: lint → test → smoke-test → docker-build → publish → release
```

### Required GitHub secrets

| Secret | Used by | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | publish, release | Push to GHCR, create release (auto-provided) |
| `CODECOV_TOKEN` | test | Upload coverage reports (optional) |

---

## API Key Resolution

The tool resolves API keys in this priority order:

```
1. --api-key <value>            CLI flag (highest priority)
2. <PROVIDER>_API_KEY           Provider-specific env var
   (ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY, CUSTOM_API_KEY)
3. LLM_API_KEY                  Generic fallback env var
4. Built-in dummy key           For local providers (Ollama, LM Studio)
5. Exit with error              For cloud providers with no key found
```

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
# Edit .env — only set the key for the provider you use
source .env
```

---

## Security Notes

- The tool is **read-only** — it only runs `kubectl get/top/version` commands
- The Docker image runs as a **non-root user** (`appuser`, UID 1001)
- The kubeconfig is mounted **read-only** (`-v ~/.kube:/root/.kube:ro`)
- For **fully air-gapped / zero-data-exfiltration** runs, use `--provider ollama` or `--provider lmstudio` — no data leaves your network
- The Docker image is scanned with **Trivy** on every CI run; results appear in the GitHub Security tab

---

## Troubleshooting

**`kubectl not found in PATH`**

```bash
# Local: ensure kubectl is installed and in PATH
which kubectl
kubectl version --client

# Docker: kubectl is bundled — if you see this error, rebuild the image
docker build --no-cache -t k8s-upgrade-assessment .
```

**`[ERROR] API key required for provider 'anthropic'`**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or pass inline:
python main.py --source 1.27 --target 1.29 --api-key sk-ant-...
```

**`[ERROR] --provider custom requires --base-url`**

```bash
python main.py --source 1.27 --target 1.29 \
  --provider custom \
  --base-url http://localhost:8000/v1 \
  --model my-model
```

**Ollama connection refused**

```bash
# Make sure ollama is running
ollama serve
# Then retry — or use --network host in Docker
docker run --rm --network host ...
```

**Report is empty / LLM returned nothing**

- Try a more capable model — small local models (< 7B) may not handle the prompt well
- Increase model context window if configurable
- Try `--no-cluster` first to verify the tool + API key work before using live data

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make changes — ensure all checks pass:
   ```bash
   black main.py && isort main.py
   flake8 main.py
   mypy main.py --ignore-missing-imports
   pytest tests/ --cov=main --cov-fail-under=75
   ```
4. Commit: `git commit -m "feat: my feature description"`
5. Push and open a Pull Request against `main`

All PRs must pass the full CI pipeline before merge.

---

## License

MIT — see [LICENSE](LICENSE)
