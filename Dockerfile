FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ARG CODEX_VERSION=0.147.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install --global "@openai/codex@${CODEX_VERSION}" \
    && rm -rf /var/lib/apt/lists/* /root/.npm \
    && useradd --create-home --uid 10001 bob \
    && pip install --no-cache-dir uv==0.8.4
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY . .
COPY docker/entrypoint.sh /usr/local/bin/bob-entrypoint
RUN mkdir -p /data/client /data/codex /data/metadata \
    && chown -R bob:bob /app /data
USER bob
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
ENTRYPOINT ["/usr/local/bin/bob-entrypoint"]
CMD ["uv","run","uvicorn","server.app:app","--host","0.0.0.0","--port","8000"]
