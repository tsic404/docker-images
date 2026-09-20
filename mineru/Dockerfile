ARG VERSION=mineru-4.0.3-released

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
#   - CUDA toolkit (13.0)
#   - PyTorch with GPU support
#   - vLLM inference engine
#   - Supported GPU architectures: Volta / Turing / Ampere / Ada Lovelace / Hopper / Blackwell
#     (Compute Capability 7.0 – 12.1)
# For CUDA 12.9 environments, use: vllm/vllm-openai:v0.21.0-cu129
FROM vllm/vllm-openai:v0.21.0

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
# Upstream uses: RUN python3 -m pip install -U 'mineru[torch]>=4.0,<5' --break-system-packages
#   (torch extra reuses the PyTorch already present in the vLLM base image)
# We maintain git clone for version-pinned builds.
COPY --from=builder /workspace/mineru-src /tmp/mineru-src
RUN python3 -m pip install -U '/tmp/mineru-src[torch]' --break-system-packages && \
    rm -rf /tmp/mineru-src && \
    python3 -m pip cache purge

# ── Model download (at container startup) ────────────────────────────────
# Models are downloaded on first container startup, not pre-baked into image.
# To persist models across container restarts, mount a volume at:
#   /root/.cache/huggingface
# Upstream pre-downloads models:
#   RUN /bin/bash -c "mineru-kit models download --tier standard --small-backend torch --vlm-engine vllm -s huggingface"
# Uncomment below to pre-download during image build (increases image size):
# RUN /bin/bash -c "mineru-kit models download --tier standard --small-backend torch --vlm-engine vllm -s huggingface"

# ── Runtime configuration ────────────────────────────────────────────────
# Model backend selection aligned with upstream:
#   - MINERU_MODEL_SMALL_BACKEND=torch: torch small model (reuses base image torch)
#   - MINERU_MODEL_VLM_ENGINE=vllm: VLM inference via the vLLM base image
# Model downloads at startup use the same flags (see model download above).
ENV MINERU_MODEL_SOURCE=local \
    MINERU_MODEL_SMALL_BACKEND=torch \
    MINERU_MODEL_VLM_ENGINE=vllm

WORKDIR /app

# entrypoint mirrors the official Dockerfile:
# forces MINERU_MODEL_SOURCE=local and passes through the CMD/args
ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
