# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — builder: install deps into a clean venv
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency manifest first for better layer caching
COPY requirements.txt .

# Create isolated venv and install deps
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip --no-cache-dir && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime: minimal image with kubectl + app
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="k8s-upgrade-assessment" \
      org.opencontainers.image.description="AI-powered Kubernetes upgrade risk assessment CLI" \
      org.opencontainers.image.source="https://github.com/your-org/k8s-upgrade-assessment" \
      org.opencontainers.image.licenses="MIT"

# Install kubectl
ARG KUBECTL_VERSION=v1.29.3
ARG TARGETARCH=amd64
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
       -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

# Activate venv for all subsequent commands
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

WORKDIR /app

# Copy application source
COPY main.py .

# Create reports output directory and set ownership
RUN mkdir -p /app/reports && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Mount points:
#   /app/reports     — output directory for generated reports
#   /root/.kube      — kubeconfig (when running against a live cluster)
VOLUME ["/app/reports"]

# Default: offline demo mode (safe default, no credentials needed)
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
