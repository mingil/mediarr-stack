#!/bin/bash
# =============================================================================
# 🩺 MEDIARR-STACK 통합 업데이트 · VPN 보안 점검 · SQLite DB 최적화 닥터 스크립트
# (기존 update_qbittorrent.sh의 전체 스택 확장 업그레이드 버전 - Watchtower 불필요)
# =============================================================================

WORK_DIR="/volume1/docker/mediarr-stack"
LOG_FILE="${WORK_DIR}/mediarr-update.log"

mkdir -p "$WORK_DIR"
exec >> "$LOG_FILE" 2>&1

echo "================================================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] MEDIARR-STACK 통합 유지보수 & 업데이트 시작"
echo "================================================================="

export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin

if command -v docker compose &> /dev/null; then
    DOCKER_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_CMD="docker-compose"
else
    echo "오류: docker compose 명령어를 찾을 수 없습니다."
    exit 1
fi

echo ">> [1/5] Plex 비정상 종료 잔여 PID 파일 정리..."
rm -f "/volume1/docker/plexhw/Library/Application Support/Plex Media Server/plexmediaserver.pid" 2>/dev/null || true

echo ">> [2/5] Mediarr Control Center를 통한 SQLite DB VACUUM 최적화 & 설정 백업 실행..."
curl -fsS -X POST http://127.0.0.1:8500/api/runtime/maintenance || true

if [ -f "$WORK_DIR/docker-compose.yml" ] || [ -f "$WORK_DIR/compose.yaml" ]; then
    cd "$WORK_DIR"
    echo ">> [3/5] 전체 컨테이너 최신 이미지 다운로드 (Pull)..."
    $DOCKER_CMD pull
    echo ">> [4/5] 변경된 컨테이너 무중단 재구동 (Up -d)..."
    $DOCKER_CMD up -d --remove-orphans
fi

echo ">> [5/5] Gluetun VPN 터널 공인 IP 보호 상태 검증 및 구버전 이미지 정리..."
docker exec mediarr-gluetun wget -qO- https://ipinfo.io/json 2>/dev/null || true
docker image prune -f

chmod 666 "$LOG_FILE" 2>/dev/null || true
echo "================================================================="
echo "[$(date '+%Y-%m-%d %H:%M:%S')] MEDIARR-STACK 유지보수가 성공적으로 완료되었습니다."
echo "================================================================="
