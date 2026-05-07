ARG VERSION=mineru-3.1.6-released

# =============================================================================
# Stage 1: Builder/Fetcher — clone source at the exact release tag
# =============================================================================
FROM ubuntu:latest AS builder
ARG VERSION
WORKDIR /workspace
RUN apt-get update && apt-get install -y git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
RUN git clone --branch ${VERSION} --depth=1 \
    https://github.com/opendatalab/MinerU.git /workspace/mineru-src

# =============================================================================
# Stage 2: Runtime — vLLM base + MinerU + models
# =============================================================================
# vLLM base image provides:
#   - CUDA toolkit (12.x)
#   - PyTorch with GPU support
#   - vLLM inference engine
#   - Supported GPU architectures: Volta / Turing / Ampere / Ada Lovelace / Hopper / Blackwell
#     (Compute Capability 7.0 – 12.0)
FROM vllm/vllm-openai:v0.11.2

ARG VERSION

# ── System dependencies ──────────────────────────────────────────────────
# - fonts-noto-*: Chinese / CJK character rendering in PDF parsing
# - libgl1:       OpenCV support for image-based document processing
RUN apt-get update && \
    apt-get install -y \
        fonts-noto-core \
        fonts-noto-cjk \
        fontconfig \
        libgl1 && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ── Install MinerU from the version-pinned source ────────────────────────
# Using the cloned source ensures exact parity with the Git tag,
# including any unreleased patches between PyPI publishes.
COPY --from=builder /workspace/mineru-src /tmp/mineru-src
RUN python3 -m pip install -U '/tmp/mineru-src[core]' --break-system-packages && \
    rm -rf /tmp/mineru-src && \
    python3 -m pip cache purge

# ── Model download (at container startup) ────────────────────────────────
# Models are downloaded on first container startup, not pre-baked into image.
# To persist models across container restarts, mount a volume at:
#   /root/.cache/huggingface
# Comment the line below to enable pre-download during image build:
# RUN /bin/bash -c "mineru-models-download -s huggingface -m all"

# ── Runtime configuration ────────────────────────────────────────────────
ENV MINERU_MODEL_SOURCE=local

WORKDIR /app

# entrypoint mirrors the official Dockerfile:
# forces MINERU_MODEL_SOURCE=local and passes through the CMD/args
ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
