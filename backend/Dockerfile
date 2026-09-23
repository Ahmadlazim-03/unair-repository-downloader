FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
       amd64) checksum=c203d1f4c8726160e346d3f9ca7411e0b2029bc818a57cde993ee3711369bcaa ;; \
       arm64) checksum=0227e78366239d60e0e1953dfba4b4687e7932c4b75b149cd6e67e2d4e67d173 ;; \
       *) echo "Unsupported architecture: $arch"; exit 1 ;; esac \
    && curl -fsSL --retry 3 "https://github.com/windtf/wireproxy/releases/download/v1.0.8/wireproxy_linux_${arch}.tar.gz" -o /tmp/wireproxy.tar.gz \
    && echo "$checksum  /tmp/wireproxy.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/wireproxy.tar.gz -C /usr/local/bin wireproxy \
    && chmod +x /usr/local/bin/wireproxy \
    && wireproxy --version \
    && rm /tmp/wireproxy.tar.gz \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VPN_MODE=portal

RUN wireproxy --version

COPY --chown=user:user backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --user -r backend/requirements.txt

COPY --chown=user:user backend ./backend

EXPOSE 7860 8787

CMD ["sh", "-c", "python -m uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-7860} --no-access-log --timeout-graceful-shutdown 120"]
