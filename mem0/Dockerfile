FROM ubuntu:latest as builder
ARG VERSION=main
WORKDIR /workspace
RUN apt-get update && apt-get install -y git patch curl
RUN git clone --branch ${VERSION} --depth=1 https://github.com/mem0ai/mem0.git

RUN curl https://patch-diff.githubusercontent.com/raw/mem0ai/mem0/pull/4784.patch -o /tmp/4784.patch && \
    cd mem0 && \
    patch -p1 < /tmp/4784.patch && \
    patch -p1 <<'EOF'
diff --git a/server/main.py b/server/main.py
--- a/server/main.py
+++ b/server/main.py
@@ -73,6 +73,11 @@
     "history_db_path": HISTORY_DB_PATH,
 }

+import yaml
+CONFIG_PATH = os.environ.get("CONFIG_PATH", None)
+if CONFIG_PATH:
+    with open(CONFIG_PATH, "r") as f:
+        DEFAULT_CONFIG = yaml.safe_load(f)

 MEMORY_INSTANCE = Memory.from_config(DEFAULT_CONFIG)
EOF

FROM python:3.12

WORKDIR /app

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Copy requirements first for better caching
COPY --from=builder /workspace/mem0/server/requirements.txt .
RUN pip install -r requirements.txt

# Install mem0 in editable mode using Poetry
WORKDIR /app/packages
COPY --from=builder /workspace/mem0/pyproject.toml .
COPY --from=builder /workspace/mem0/poetry.lock .
COPY --from=builder /workspace/mem0/README.md .
COPY --from=builder /workspace/mem0/mem0 ./mem0
RUN pip install -e .[graph]
RUN pip install cohere

# Return to app directory and copy server code
WORKDIR /app
COPY --from=builder /workspace/mem0/server .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
