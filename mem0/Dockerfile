FROM ubuntu:latest as builder
WORKDIR /workspace
RUN apt-get update && apt-get install -y git
RUN git clone --depth=1 https://github.com/mem0ai/mem0.git && \
    cd mem0 && \
    git fetch --tags --force && \
    git checkout $(git tag --sort=-v:refname | head -n 1)

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

# Return to app directory and copy server code
WORKDIR /app
COPY --from=builder /workspace/mem0/server .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
