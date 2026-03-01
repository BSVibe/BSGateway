FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml .
RUN uv pip install --system .

COPY . .

ENV PYTHONPATH=/app
ENV GATEWAY_CONFIG_PATH=/app/config/gateway.yaml

EXPOSE 4000

CMD ["litellm", "--config", "config/gateway.yaml", "--port", "4000", "--num_workers", "4"]
