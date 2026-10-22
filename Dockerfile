# E5 — cloud_jarvis on Oracle Cloud (or any Docker host).
#
# Build:  docker build -t mark-jarvis-cloud .
# Run:    docker run -d --name jarvis-cloud --restart unless-stopped \
#             -v "$PWD/config:/app/config:ro" -v "$PWD/memory:/app/memory" \
#             mark-jarvis-cloud
#
# Credentials are NOT baked into the image. Mount config/ at runtime; the image
# starts without it and reports that it is in manual mode.

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime libs needed by numpy/psutil on slim; kept minimal on purpose.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt

COPY . .

# The container runs as an unprivileged user; mounted config/memory must be
# writable by uid 10001 if alerts need to write.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin jarvis \
    && chown -R jarvis:jarvis /app
USER jarvis

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import cloud_jarvis; print('ok')" || exit 1

CMD ["python", "cloud_jarvis.py"]
