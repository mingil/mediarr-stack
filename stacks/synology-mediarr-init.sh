#!/bin/bash
# =============================================================================
# 🚀 시놀로지 NAS (DS920+) MEDIARR-STACK 원클릭 폴더 & 권한 초기화 스크립트
# (참고: mediarr-control-center 컨테이너가 부팅 시에도 자동으로 동일 작업을 수행합니다!)
# =============================================================================

set -e

DOCKER_ROOT="/volume1/docker"
DATA_ROOT="/volume1/mediarr"
PUID=1026
PGID=100

echo ">>> [1/4] 도커 컨테이너 설정 디렉토리 생성 중 ($DOCKER_ROOT)..."
mkdir -p "$DOCKER_ROOT"/{gluetun,qbittorrent,plexhw,seerr,prowlarr,flaresolverr,sonarr,radarr,bazarr,smi2srt,smi2srt/log,smi2srt/smi_backup,recyclarr,unpackerr,tautulli,kometa,maintainerr,_backups/mediarr-stack}

echo ">>> [2/4] TRaSH Guides 표준 단일 볼륨 하드링크 폴더 트리 생성 중 ($DATA_ROOT)..."
mkdir -p "$DATA_ROOT"/torrents/{movies,tv,anime,music}
mkdir -p "$DATA_ROOT"/media/{movies,tv,anime,music}

echo ">>> [3/4] 좀비 Plex PID 파일 점검 및 정리 중..."
rm -f "$DOCKER_ROOT/plexhw/Library/Application Support/Plex Media Server/plexmediaserver.pid" 2>/dev/null || true

echo ">>> [4/4] 시놀로지 파일 시스템 소유권($PUID:$PGID) 및 권한(775) 최적화 중..."
chown -R $PUID:$PGID "$DOCKER_ROOT"/{gluetun,qbittorrent,plexhw,seerr,prowlarr,flaresolverr,sonarr,radarr,bazarr,smi2srt,recyclarr,unpackerr,tautulli,kometa,maintainerr,_backups}
chown -R $PUID:$PGID "$DATA_ROOT"
chmod -R 775 "$DATA_ROOT"

echo "✅ MEDIARR-STACK 시놀로지 폴더 및 하드링크 권한 세팅이 100% 완료되었습니다!"
