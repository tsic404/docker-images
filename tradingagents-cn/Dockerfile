FROM ubuntu:latest as builder
WORKDIR /workspace
RUN apt-get update && apt-get install -y git
RUN git clone https://github.com/hsliuping/TradingAgents-CN.git

# 使用官方Python镜像替代GitHub Container Registry
FROM python:3.10-slim-bookworm

# 安装uv包管理器
RUN pip install uv

WORKDIR /app

RUN mkdir -p /app/data /app/logs

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    wkhtmltopdf \
    xvfb \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fonts-liberation \
    pandoc \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 启动Xvfb虚拟显示器
RUN echo '#!/bin/bash\nXvfb :99 -screen 0 1024x768x24 -ac +extension GLX &\nexport DISPLAY=:99\nexec "$@"' > /usr/local/bin/start-xvfb.sh \
    && chmod +x /usr/local/bin/start-xvfb.sh

COPY --from=builder /workspace/TradingAgents-CN/requirements.txt .

#多源轮询安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制日志配置文件
COPY --from=builder /workspace/TradingAgents-CN/config/ ./config/

COPY --from=builder /workspace/TradingAgents-CN/ .

EXPOSE 8501

CMD ["python", "-m", "streamlit", "run", "web/app.py", "--server.address=0.0.0.0", "--server.port=8501"]