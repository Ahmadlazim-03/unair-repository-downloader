FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
       amd64) checksum=e88c1d090740373fc606c1bafd81d9a5eadc642cce5667616e20e9d7a444f51c ;; \
       arm64) checksum=370e00bd2167960d1ecd1c3c1439715bbaa94a0a110a2040468670c9af6021b6 ;; \
       *) echo "Unsupported architecture: $arch"; exit 1 ;; esac \
    && curl -fsSL --retry 3 "https://github.com/windtf/wireproxy/releases/download/v1.1.3/wireproxy_linux_${arch}.tar.gz" -o /tmp/wireproxy.tar.gz \
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
    VPN_MODE=portal \
    WIREPROXY_VERSION=1.1.3

RUN wireproxy --version

COPY --chown=user:user backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --user -r backend/requirements.txt

COPY --chown=user:user backend ./backend

# Exercise Linux startup, including Landlock and SOCKS5, with throwaway keys.
# --version and --configtest exit before this startup stage.
RUN python -m backend.vpn_selftest

EXPOSE 7860 8787

CMD ["sh", "-c", "python -m backend.vpn_selftest && exec python -m uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-7860} --no-access-log --timeout-graceful-shutdown 120"]
