#!/bin/bash
# =============================================================================
# 🩺 MEDIARR-STACK 수동 점검용 보조 스크립트 (선택 사항)
# • 평소 이미지 업데이트: 기존 운영 중인 Watchtower가 라벨(enable=true & depends-on)을 인식해 100% 자동 수행합니다.
# • 평소 DB 최적화·백업: mediarr-control-center 컨테이너 내장 스케줄러가 24시간마다 자동 수행합니다.
# =============================================================================

echo ">> [1/2] Plex 잔여 PID 정리 및 Mediarr Control Center 즉시 DB 최적화 트리거..."
rm -f "/volume1/docker/plexhw/Library/Application Support/Plex Media Server/plexmediaserver.pid" 2>/dev/null || true
curl -fsS -X POST http://127.0.0.1:8500/api/runtime/maintenance || true

echo ">> [2/2] Gluetun VPN 공인 IP 보호 상태 확인..."
docker exec mediarr-gluetun wget -qO- https://ipinfo.io/json 2>/dev/null || true
echo ""
echo "✅ 점검 완료!"
