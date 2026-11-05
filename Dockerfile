FROM python:3.11-slim

LABEL org.opencontainers.image.title="Ultimate Media & *Arr Stack Control Center (mediarr-stack)"
LABEL org.opencontainers.image.description="시놀로지 NAS (DS920+) 맞춤형 Plex(HW) · Gluetun(Surfshark) · qBittorrent · Seerr · Prowlarr · Sonarr · Radarr · Bazarr 통합 관제 및 자동 프로비저닝 엔진"
LABEL org.opencontainers.image.authors="mingil"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul \
    PORT=8500

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8500/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8500"]
