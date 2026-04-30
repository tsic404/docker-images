FROM ubuntu:latest as fetcher
ARG VERSION=main
WORKDIR /workspace
RUN apt-get update && apt-get install -y git patch curl
RUN git clone --branch ${VERSION} --depth=1 https://github.com/mem0ai/mem0.git

FROM python:3.12-slim

WORKDIR /app

COPY --from=fetcher /workspace/mem0/server/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY --from=fetcher /workspace/mem0/server/ .

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
