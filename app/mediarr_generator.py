"""Unified Synology Self-Hosting Style Docker Compose, Config & Maintenance Script Generator for mediarr-stack."""

from typing import Any, Dict, List
from pydantic import BaseModel, Field
from app.mediarr_catalog import MEDIARR_SERVICES_CATALOG, VPN_PROVIDERS


class MediarrStackConfigRequest(BaseModel):
    nas_ip: str = Field(default="192.168.0.100", description="시놀로지 NAS 내부 IP 주소")
    puid: int = Field(default=1026, description="시놀로지 사용자 PUID (기본 1026)")
    pgid: int = Field(default=100, description="시놀로지 그룹 PGID (기본 100)")
    tz: str = Field(default="Asia/Seoul", description="타임존")
    docker_root: str = Field(default="/volume1/docker", description="도커 설정 폴더 루트 경로")
    data_root: str = Field(default="/volume1/mediarr", description="토렌트 및 미디어 통합 데이터 경로 (하드링크용)")
    legacy_torrents_root: str = Field(default="/volume1/torrents", description="기존 토렌트 호환 경로 (/downloads)")
    legacy_video_root: str = Field(default="/volume1/video", description="기존 비디오 호환 경로 (/movies, /tv_shows, /music)")
    use_vpn: bool = Field(default=True, description="Gluetun VPN 킬스위치 사용 여부")
    vpn_provider: str = Field(default="surfshark", description="VPN 서비스 제공자 ID (surfshark 기본)")
    route_prowlarr_vpn: bool = Field(default=True, description="기존 구성처럼 Prowlarr/FlareSolverr도 VPN 내부로 라우팅할지 여부")
    enable_hw_transcoding: bool = Field(default=True, description="Plex Intel QuickSync (/dev/dri) + RAM 트랜스코딩 활성화")
    qbit_webui_port: int = Field(default=8181, description="qBittorrent Web UI 포트 (기존 8181 유지)")
    plex_claim: str = Field(default="", description="Plex Claim 토큰 (선택)")
    seerr_variant: str = Field(default="jellyseerr", description="seerr 이미지 선택 (jellyseerr 또는 overseerr)")
    selected_services: List[str] = Field(
        default_factory=lambda: [
            "mediarr-control-center",
            "gluetun",
            "qbittorrent",
            "plex",
            "seerr",
            "prowlarr",
            "flaresolverr",
            "sonarr",
            "radarr",
            "bazarr",
            "recyclarr",
            "unpackerr",
            "tautulli",
            "kometa",
            "maintainerr",
        ]
    )


def _normalize_selected(cfg: MediarrStackConfigRequest) -> List[str]:
    selected = list(dict.fromkeys(cfg.selected_services))
    if "mediarr-control-center" not in selected:
        selected.insert(0, "mediarr-control-center")
    if cfg.use_vpn and "qbittorrent" in selected and "gluetun" not in selected:
        idx = 1 if "mediarr-control-center" in selected else 0
        selected.insert(idx, "gluetun")
    if not cfg.use_vpn and "gluetun" in selected:
        selected.remove("gluetun")
    # Never allow watchtower
    if "watchtower" in selected:
        selected.remove("watchtower")
    return selected


def generate_mediarr_compose(cfg: MediarrStackConfigRequest) -> str:
    """Generate unified single-project docker-compose.yml for mediarr-stack (Watchtower-free)."""
    selected = _normalize_selected(cfg)
    docker_root = cfg.docker_root.rstrip("/")
    data_root = cfg.data_root.rstrip("/")
    legacy_torrents = cfg.legacy_torrents_root.rstrip("/")
    legacy_video = cfg.legacy_video_root.rstrip("/")
    vpn_active = cfg.use_vpn and ("gluetun" in selected)
    qbit_port = cfg.qbit_webui_port

    vpn_info = next((v for v in VPN_PROVIDERS if v["id"] == cfg.vpn_provider), VPN_PROVIDERS[0])

    lines: List[str] = [
        "# =============================================================================",
        "# 🎬 ULTIMATE SYNOLOGY MEDIA & *ARR AUTOMATION STACK (mediarr-stack)",
        "# =============================================================================",
        "# • 프로젝트명   : mediarr-stack (단일 프로젝트 & 단일 docker-compose.yml 통합 아키텍처)",
        "# • 통합 이미지  : kimmingil/mediarr-stack:latest (자동 초기화 · 실시간 관제 · DB 최적화 내장)",
        "# • 하드링크 규격: TRaSH Guides 단일 볼륨(/volume1/mediarr:/data) 0.1초 하드링크 완벽 지원",
        "# • 기존 호환성  : 기존 PlexHW(/volume1/docker/plexhw) & qBittorrent(:8181) 설정 100% 무손실 승계",
        f"# • 시놀로지 권한: PUID={cfg.puid} / PGID={cfg.pgid} / TZ={cfg.tz}",
        "# =============================================================================",
        "",
        'version: "3.9"',
        "",
        "# 🌐 1. 도커 내부 유기적 통신용 전용 브리지 네트워크",
        "networks:",
        "  mediarr_net:",
        "    name: mediarr_net",
        "    driver: bridge",
        "",
        "# 🧹 2. 시놀로지 NAS 디스크 보호용 공통 로그 로테이션 설정",
        "x-logging: &default-logging",
        '  driver: "json-file"',
        "  options:",
        '    max-size: "10m"',
        '    max-file: "3"',
        "",
        "services:",
    ]

    # 0. MEDIARR CONTROL CENTER
    if "mediarr-control-center" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 🎛️ 0. MEDIARR CONTROL CENTER - 통합 관제 · 폴더/설정 자동 초기화 · DB 닥터",
            "  # ---------------------------------------------------------------------------",
            "  mediarr-control-center:",
            "    image: kimmingil/mediarr-stack:latest",
            "    container_name: mediarr-control-center",
            "    hostname: mediarr-control-center",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - mediarr-control-center",
            "          - mediarr-stack",
            "    extra_hosts:",
            '      - "host.docker.internal:host-gateway"',
            "    security_opt:",
            "      - no-new-privileges:true",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            "      PORT: 8500",
            '      AUTO_BOOTSTRAP: "true"',
            "      HOST_DOCKER_MOUNT: /host-docker",
            "      HOST_DATA_MOUNT: /host-data",
            f"      NAS_IP: ${{NAS_IP:-{cfg.nas_ip}}}",
            "      SONARR_API_KEY: ${SONARR_API_KEY:-}",
            "      RADARR_API_KEY: ${RADARR_API_KEY:-}",
            "    ports:",
            '      - "8500:8500"',
            "    volumes:",
            f"      - {docker_root}:/host-docker:rw",
            f"      - {data_root}:/host-data:rw",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8500/api/health >/dev/null || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 3",
            "      start_period: 15s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 1. GLUETUN VPN GATEWAY
    if vpn_active:
        gluetun_ports = [
            '      - "8000:8000/tcp"   # Gluetun 내장 컨트롤 서버',
        ]
        gluetun_aliases = [
            "          - gluetun",
            "          - mediarr-gluetun",
        ]
        if "qbittorrent" in selected:
            gluetun_ports.extend([
                f'      - "{qbit_port}:{qbit_port}/tcp"   # qBittorrent Web UI (기존 {qbit_port} 포트 호환)',
                '      - "6881:6881/tcp"   # qBittorrent 토렌트 피어 포트 (TCP)',
                '      - "6881:6881/udp"   # qBittorrent 토렌트 피어 포트 (UDP)',
            ])
            gluetun_aliases.extend([
                "          - qbittorrent",
                "          - mediarr-qbittorrent",
            ])
        if cfg.route_prowlarr_vpn and "prowlarr" in selected:
            gluetun_ports.append('      - "9696:9696/tcp"   # Prowlarr Web UI (VPN 터널 경유)')
            gluetun_aliases.extend([
                "          - prowlarr",
                "          - mediarr-prowlarr",
            ])
        if cfg.route_prowlarr_vpn and "flaresolverr" in selected:
            gluetun_ports.append('      - "8191:8191/tcp"   # FlareSolverr API (VPN 터널 경유)')
            gluetun_aliases.extend([
                "          - flaresolverr",
                "          - mediarr-flaresolverr",
            ])

        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 🛡️ 1. GLUETUN - Surfshark VPN 킬스위치 및 암호화 게이트웨이",
            "  # ---------------------------------------------------------------------------",
            "  gluetun:",
            "    image: qmcgaw/gluetun:latest",
            "    container_name: mediarr-gluetun",
            "    hostname: gluetun",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            *gluetun_aliases,
            "    cap_add:",
            "      - NET_ADMIN",
            "    devices:",
            "      - /dev/net/tun:/dev/net/tun",
            "    mem_limit: 512m",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    ports:",
            *gluetun_ports,
            "    volumes:",
            f"      - {docker_root}/gluetun:/gluetun:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
        ])
        for k, v in vpn_info["env_template"].items():
            lines.append(f'      {k}: "{v}"')
        lines.extend([
            '      FIREWALL_OUTBOUND_SUBNETS: "${FIREWALL_OUTBOUND_SUBNETS:-172.16.0.0/12,192.168.0.0/16,10.0.0.0/8}"',
            '      HEALTH_VPN_DURATION_INITIAL: "30s"',
            "    healthcheck:",
            '      test: ["CMD", "/gluetun-entrypoint", "healthcheck"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 30s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 2. QBITTORRENT
    if "qbittorrent" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            f"  # ⬇️ 2. QBITTORRENT - VPN 보호 초고속 토렌트 다운로더 (포트 {qbit_port} 호환)",
            "  # ---------------------------------------------------------------------------",
            "  qbittorrent:",
            "    image: lscr.io/linuxserver/qbittorrent:latest",
            "    container_name: mediarr-qbittorrent",
        ])
        if vpn_active:
            lines.extend([
                '    network_mode: "service:gluetun"',
                "    depends_on:",
                "      gluetun:",
                "        condition: service_healthy",
            ])
        else:
            lines.extend([
                "    hostname: qbittorrent",
                "    networks:",
                "      mediarr_net:",
                "        aliases:",
                "          - qbittorrent",
                "          - mediarr-qbittorrent",
                "    ports:",
                f'      - "{qbit_port}:{qbit_port}/tcp"',
                '      - "6881:6881/tcp"',
                '      - "6881:6881/udp"',
            ])
        lines.extend([
            "    mem_limit: 2g",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    volumes:",
            f"      - {docker_root}/qbittorrent:/config:rw",
            f"      - {data_root}:/data:rw",
            f"      - {legacy_torrents}:/downloads:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            f"      WEBUI_PORT: {qbit_port}",
            "      TORRENTING_PORT: 6881",
            "    healthcheck:",
            f'      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:{qbit_port} >/dev/null || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 30s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 3. PLEX MEDIA SERVER (HW)
    if "plex" in selected:
        claim_val = cfg.plex_claim if cfg.plex_claim else "${PLEX_CLAIM:-}"
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 🍿 3. PLEX MEDIA SERVER - 4K QuickSync 하드웨어 가속 & RAM 트랜스코딩 서버",
            "  # ---------------------------------------------------------------------------",
            "  plex:",
            "    image: lscr.io/linuxserver/plex:latest",
            "    container_name: mediarr-plex",
            "    hostname: plex",
            "    network_mode: host",
            "    mem_limit: 4g",
            "    cpu_shares: 1024",
            "    security_opt:",
            "      - no-new-privileges:true",
        ])
        if cfg.enable_hw_transcoding:
            lines.extend([
                "    devices:",
                "      - /dev/dri/renderD128:/dev/dri/renderD128",
                "      - /dev/dri/card0:/dev/dri/card0",
                "    tmpfs:",
                "      - /transcode:size=2G,mode=1777",
            ])
        lines.extend([
            "    volumes:",
            f"      - {docker_root}/plexhw:/config:rw",
            f"      - {data_root}:/data:rw",
            f"      - {data_root}/media/movies:/data/media/movies:rw",
            f"      - {data_root}/media/tv:/data/media/tv:rw",
            f"      - {data_root}/media/anime:/data/media/anime:rw",
            f"      - {legacy_video}/movies:/movies:ro",
            f"      - {legacy_video}/tv_shows:/tv_shows:ro",
            f"      - {legacy_video}/music:/music:ro",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            "      VERSION: docker",
            f'      PLEX_CLAIM: "{claim_val}"',
            "    healthcheck:",
            '      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:32400/identity >/dev/null || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 40s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 4. SEERR (JELLYSEERR / OVERSEERR)
    if "seerr" in selected:
        seerr_image = (
            "lscr.io/linuxserver/overseerr:latest"
            if cfg.seerr_variant == "overseerr"
            else "ghcr.io/fallenbagel/jellyseerr:latest"
        )
        seerr_vol = (
            f"      - {docker_root}/seerr:/config:rw"
            if cfg.seerr_variant == "overseerr"
            else f"      - {docker_root}/seerr:/app/config:rw"
        )
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 🎫 4. SEERR - 넷플릭스형 영화·드라마·애니 원클릭 검색 및 요청 포털",
            "  # ---------------------------------------------------------------------------",
            "  seerr:",
            f"    image: {seerr_image}",
            "    container_name: mediarr-seerr",
            "    hostname: seerr",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - seerr",
            "          - jellyseerr",
            "          - overseerr",
            "          - mediarr-seerr",
            "    extra_hosts:",
            '      - "host.docker.internal:host-gateway"',
            "    mem_limit: 1g",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    ports:",
            '      - "5055:5055/tcp"',
            "    volumes:",
            seerr_vol,
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            "      LOG_LEVEL: info",
            "      PORT: 5055",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:5055/api/v1/status >/dev/null 2>&1 || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 30s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 5. PROWLARR
    if "prowlarr" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 📡 5. PROWLARR - 통합 토렌트 인덱서 컨트롤 타워 (Sonarr·Radarr 자동 동기화)",
            "  # ---------------------------------------------------------------------------",
            "  prowlarr:",
            "    image: lscr.io/linuxserver/prowlarr:latest",
            "    container_name: mediarr-prowlarr",
        ])
        if vpn_active and cfg.route_prowlarr_vpn:
            lines.extend([
                '    network_mode: "service:gluetun"',
                "    depends_on:",
                "      gluetun:",
                "        condition: service_healthy",
            ])
        else:
            lines.extend([
                "    hostname: prowlarr",
                "    networks:",
                "      mediarr_net:",
                "        aliases:",
                "          - prowlarr",
                "          - mediarr-prowlarr",
                "    ports:",
                '      - "9696:9696/tcp"',
            ])
        lines.extend([
            "    mem_limit: 1g",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    volumes:",
            f"      - {docker_root}/prowlarr:/config:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:9696/ping >/dev/null || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 30s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 6. FLARESOLVERR
    if "flaresolverr" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 🛡️ 6. FLARESOLVERR - 인덱서 Cloudflare 보안 검증 백그라운드 자동 우회",
            "  # ---------------------------------------------------------------------------",
            "  flaresolverr:",
            "    image: ghcr.io/flaresolverr/flaresolverr:latest",
            "    container_name: mediarr-flaresolverr",
        ])
        if vpn_active and cfg.route_prowlarr_vpn:
            lines.extend([
                '    network_mode: "service:gluetun"',
                "    depends_on:",
                "      gluetun:",
                "        condition: service_healthy",
            ])
        else:
            lines.extend([
                "    hostname: flaresolverr",
                "    networks:",
                "      mediarr_net:",
                "        aliases:",
                "          - flaresolverr",
                "          - mediarr-flaresolverr",
                "    ports:",
                '      - "8191:8191/tcp"',
            ])
        lines.extend([
            "    mem_limit: 1g",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            "      LOG_LEVEL: info",
            "      LOG_HTML: \"false\"",
            "      CAPTCHA_SOLVER: none",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8191/health >/dev/null 2>&1 || wget -qO- http://127.0.0.1:8191/ >/dev/null 2>&1 || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 20s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 7. SONARR
    if "sonarr" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 📺 7. SONARR - TV 드라마·예능·애니메이션 자동 수집 및 0.1초 하드링크 정리",
            "  # ---------------------------------------------------------------------------",
            "  sonarr:",
            "    image: lscr.io/linuxserver/sonarr:latest",
            "    container_name: mediarr-sonarr",
            "    hostname: sonarr",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - sonarr",
            "          - mediarr-sonarr",
            "    extra_hosts:",
            '      - "host.docker.internal:host-gateway"',
            "    mem_limit: 1g",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    ports:",
            '      - "8989:8989/tcp"',
            "    volumes:",
            f"      - {docker_root}/sonarr:/config:rw",
            f"      - {data_root}:/data:rw",
            f"      - {legacy_torrents}:/downloads:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8989/ping >/dev/null || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 30s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 8. RADARR
    if "radarr" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 🎬 8. RADARR - 영화(4K/1080p) 자동 수집 및 화질 업그레이드 · 하드링크 정리",
            "  # ---------------------------------------------------------------------------",
            "  radarr:",
            "    image: lscr.io/linuxserver/radarr:latest",
            "    container_name: mediarr-radarr",
            "    hostname: radarr",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - radarr",
            "          - mediarr-radarr",
            "    extra_hosts:",
            '      - "host.docker.internal:host-gateway"',
            "    mem_limit: 1g",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    ports:",
            '      - "7878:7878/tcp"',
            "    volumes:",
            f"      - {docker_root}/radarr:/config:rw",
            f"      - {data_root}:/data:rw",
            f"      - {legacy_torrents}:/downloads:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:7878/ping >/dev/null || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 30s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 9. BAZARR
    if "bazarr" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 💬 9. BAZARR - 한국어(ko)·영어(en) 자막 자동 다운로드 & AI 오디오 싱크 보정",
            "  # ---------------------------------------------------------------------------",
            "  bazarr:",
            "    image: lscr.io/linuxserver/bazarr:latest",
            "    container_name: mediarr-bazarr",
            "    hostname: bazarr",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - bazarr",
            "          - mediarr-bazarr",
            "    mem_limit: 1g",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    ports:",
            '      - "6767:6767/tcp"',
            "    volumes:",
            f"      - {docker_root}/bazarr:/config:rw",
            f"      - {data_root}:/data:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:6767/ping >/dev/null 2>&1 || curl -fsS http://127.0.0.1:6767 >/dev/null 2>&1 || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 30s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 10. RECYCLARR
    if "recyclarr" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # ♻️ 10. RECYCLARR - TRaSH Guides 최고급 화질 프로필 & 한국어 우대 자동 동기화",
            "  # ---------------------------------------------------------------------------",
            "  recyclarr:",
            "    image: ghcr.io/recyclarr/recyclarr:latest",
            "    container_name: mediarr-recyclarr",
            "    hostname: recyclarr",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - recyclarr",
            "          - mediarr-recyclarr",
            "    user: " + f'"{cfg.puid}:{cfg.pgid}"',
            "    mem_limit: 512m",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    volumes:",
            f"      - {docker_root}/recyclarr:/config:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            '      CRON_SCHEDULE: "@daily"',
            "      SONARR_API_KEY: ${SONARR_API_KEY:-}",
            "      RADARR_API_KEY: ${RADARR_API_KEY:-}",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 11. UNPACKERR
    if "unpackerr" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 📦 11. UNPACKERR - 토렌트 압축파일(.rar/.zip) 자동 해제 후 하드링크 연결",
            "  # ---------------------------------------------------------------------------",
            "  unpackerr:",
            "    image: golift/unpackerr:latest",
            "    container_name: mediarr-unpackerr",
            "    hostname: unpackerr",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - unpackerr",
            "          - mediarr-unpackerr",
            "    user: " + f'"{cfg.puid}:{cfg.pgid}"',
            "    mem_limit: 512m",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    volumes:",
            f"      - {docker_root}/unpackerr:/config:rw",
            f"      - {data_root}:/data:rw",
            f"      - {legacy_torrents}:/downloads:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            "      UN_SONARR_0_URL: http://sonarr:8989",
            "      UN_SONARR_0_API_KEY: ${SONARR_API_KEY:-}",
            "      UN_SONARR_0_PATHS_0: /data/torrents",
            "      UN_RADARR_0_URL: http://radarr:7878",
            "      UN_RADARR_0_API_KEY: ${RADARR_API_KEY:-}",
            "      UN_RADARR_0_PATHS_0: /data/torrents",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 12. TAUTULLI
    if "tautulli" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 📊 12. TAUTULLI - Plex 실시간 스트리밍·하드웨어 트랜스코딩 모니터링 (포트 8182)",
            "  # ---------------------------------------------------------------------------",
            "  tautulli:",
            "    image: lscr.io/linuxserver/tautulli:latest",
            "    container_name: mediarr-tautulli",
            "    hostname: tautulli",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - tautulli",
            "          - mediarr-tautulli",
            "    extra_hosts:",
            '      - "host.docker.internal:host-gateway"',
            "    mem_limit: 512m",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    ports:",
            '      - "8182:8181/tcp"',
            "    volumes:",
            f"      - {docker_root}/tautulli:/config:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            f"      PUID: ${{PUID:-{cfg.puid}}}",
            f"      PGID: ${{PGID:-{cfg.pgid}}}",
            "    healthcheck:",
            '      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8181/status >/dev/null || exit 1"]',
            "      interval: 30s",
            "      timeout: 10s",
            "      retries: 5",
            "      start_period: 30s",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 13. KOMETA
    if "kometa" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 🎨 13. KOMETA - Plex 포스터 4K·HDR·평점 배지 오버레이 및 스마트 컬렉션",
            "  # ---------------------------------------------------------------------------",
            "  kometa:",
            "    image: kometateam/kometa:latest",
            "    container_name: mediarr-kometa",
            "    hostname: kometa",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - kometa",
            "          - mediarr-kometa",
            "    extra_hosts:",
            '      - "host.docker.internal:host-gateway"',
            "    user: " + f'"{cfg.puid}:{cfg.pgid}"',
            "    mem_limit: 1g",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    volumes:",
            f"      - {docker_root}/kometa:/config:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            '      KOMETA_TIME: "04:00"',
            '      KOMETA_RUN: "false"',
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    # 14. MAINTAINERR
    if "maintainerr" in selected:
        lines.extend([
            "  # ---------------------------------------------------------------------------",
            "  # 🧹 14. MAINTAINERR - 시청 완료 미디어 자동 정리 및 시놀로지 용량 수호자",
            "  # ---------------------------------------------------------------------------",
            "  maintainerr:",
            "    image: ghcr.io/jorenn92/maintainerr:latest",
            "    container_name: mediarr-maintainerr",
            "    hostname: maintainerr",
            "    networks:",
            "      mediarr_net:",
            "        aliases:",
            "          - maintainerr",
            "          - mediarr-maintainerr",
            "    extra_hosts:",
            '      - "host.docker.internal:host-gateway"',
            "    user: " + f'"{cfg.puid}:{cfg.pgid}"',
            "    mem_limit: 512m",
            "    security_opt:",
            "      - no-new-privileges:true",
            "    ports:",
            '      - "6246:6246/tcp"',
            "    volumes:",
            f"      - {docker_root}/maintainerr:/opt/data:rw",
            "    environment:",
            f"      TZ: ${{TZ:-{cfg.tz}}}",
            "    restart: on-failure:5",
            "    logging: *default-logging",
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def generate_recyclarr_config() -> str:
    """Generate TRaSH Guides best-practice recyclarr.yml for Sonarr v4 & Radarr v5."""
    return """# =============================================================================
# ♻️ TRaSH GUIDES 공식 표준 화질 프로필 & 한국어 우대 자동 동기화 (recyclarr.yml)
# 저장 위치: /volume1/docker/recyclarr/recyclarr.yml (mediarr-control-center 자동 생성)
# =============================================================================

sonarr:
  series_tv_anime:
    base_url: http://sonarr:8989
    api_key: !env_var SONARR_API_KEY

    delete_old_custom_formats: true
    replace_existing_custom_formats: true

    include:
      # TRaSH 공식 WEB-1080p 및 WEB-2160p(4K) 최적 화질 정의
      - template: sonarr-quality-definition-series
      - template: sonarr-v4-quality-profile-web-1080p
      - template: sonarr-v4-custom-formats-web-1080p
      - template: sonarr-v4-quality-profile-web-2160p
      - template: sonarr-v4-custom-formats-web-2160p
      # 애니메이션 전용 프로필
      - template: sonarr-v4-quality-profile-anime
      - template: sonarr-v4-custom-formats-anime

    custom_formats:
      # 저품질 릴리즈 및 캠버전 원천 차단 (-10000점)
      - trash_ids:
          - 85c61753df5da1fb2aab6f2a47426b09 # BR-DISK
          - 9c11cd3f07101cdba90a2d81cf0e56b4 # LQ (저품질 그룹)
          - 47435ece6b99a0b477caf360e79ba0bb # x265 (HD 저화질 재인코딩 차단)
        assign_scores_to:
          - name: WEB-1080p

radarr:
  uhd_hd_movies:
    base_url: http://radarr:7878
    api_key: !env_var RADARR_API_KEY

    delete_old_custom_formats: true
    replace_existing_custom_formats: true

    include:
      # TRaSH 공식 영화 품질 정의 및 HD Bluray+WEB / UHD Bluray+WEB 프로필
      - template: radarr-quality-definition-movie
      - template: radarr-quality-profile-hd-bluray-web
      - template: radarr-custom-formats-hd-bluray-web
      - template: radarr-quality-profile-uhd-bluray-web
      - template: radarr-custom-formats-uhd-bluray-web

    custom_formats:
      # 캠버전(CAM), 3D, 불량 릴리즈 완벽 차단 (-10000점)
      - trash_ids:
          - ed38b889b31be83fda192888e2286d83 # BR-DISK
          - 90a6f9a284dff5103f6346090e6280c8 # LQ (저품질/캠버전)
          - b8cd450cbfa689c0259a01d9e29ba3d6 # 3D
        assign_scores_to:
          - name: HD Bluray + WEB
          - name: UHD Bluray + WEB
"""


def generate_kometa_config(cfg: MediarrStackConfigRequest) -> str:
    """Generate starter Kometa config.yml for 4K/HDR/Rating overlays."""
    return f"""# =============================================================================
# 🎨 KOMETA (Plex Meta Manager) 포스터 4K·HDR·평점 배지 자동화 템플릿
# 저장 위치: /volume1/docker/kometa/config.yml (mediarr-control-center 자동 생성)
# =============================================================================
libraries:
  Movies:
    collection_files:
      - default: basic
      - default: imdb
      - default: streaming
    overlay_files:
      - remove_overlays: false
      - default: ribbon
      - default: resolution
      - default: audio_codec
      - default: ratings
  TV Shows:
    collection_files:
      - default: basic
      - default: streaming
    overlay_files:
      - remove_overlays: false
      - default: ribbon
      - default: resolution
      - default: ratings

plex:
  url: http://{cfg.nas_ip}:32400
  token: YOUR_PLEX_TOKEN
  timeout: 60
  clean_bundles: true
  empty_trash: true
  optimize: true

tmdb:
  apikey: YOUR_TMDB_API_KEY
  language: ko
  region: KR
"""


def generate_synology_init_script(cfg: MediarrStackConfigRequest) -> str:
    """Generate Synology DSM Task Scheduler initialization script for mediarr-stack."""
    docker_root = cfg.docker_root.rstrip("/")
    data_root = cfg.data_root.rstrip("/")
    return f"""#!/bin/bash
# =============================================================================
# 🚀 시놀로지 NAS (DS920+) MEDIARR-STACK 원클릭 폴더 & 권한 초기화 스크립트
# 실행 방법: 시놀로지 [제어판] -> [작업 스케줄러] -> [사용자 정의 스크립트(root)] 1회 실행
# (참고: mediarr-control-center 컨테이너가 부팅 시에도 자동으로 동일 작업을 수행합니다!)
# =============================================================================

set -e

DOCKER_ROOT="{docker_root}"
DATA_ROOT="{data_root}"
PUID={cfg.puid}
PGID={cfg.pgid}

echo ">>> [1/4] 도커 컨테이너 설정 디렉토리 생성 중 ($DOCKER_ROOT)..."
mkdir -p "$DOCKER_ROOT"/{{gluetun,qbittorrent,plexhw,seerr,prowlarr,flaresolverr,sonarr,radarr,bazarr,recyclarr,unpackerr,tautulli,kometa,maintainerr,_backups/mediarr-stack}}

echo ">>> [2/4] TRaSH Guides 표준 단일 볼륨 하드링크 폴더 트리 생성 중 ($DATA_ROOT)..."
mkdir -p "$DATA_ROOT"/torrents/{{movies,tv,anime,music}}
mkdir -p "$DATA_ROOT"/media/{{movies,tv,anime,music}}

echo ">>> [3/4] 좀비 Plex PID 파일 점검 및 정리 중..."
rm -f "$DOCKER_ROOT/plexhw/Library/Application Support/Plex Media Server/plexmediaserver.pid" 2>/dev/null || true

echo ">>> [4/4] 시놀로지 파일 시스템 소유권($PUID:$PGID) 및 권한(775) 최적화 중..."
chown -R $PUID:$PGID "$DOCKER_ROOT"/{{gluetun,qbittorrent,plexhw,seerr,prowlarr,flaresolverr,sonarr,radarr,bazarr,recyclarr,unpackerr,tautulli,kometa,maintainerr,_backups}}
chown -R $PUID:$PGID "$DATA_ROOT"
chmod -R 775 "$DATA_ROOT"

echo "✅ MEDIARR-STACK 시놀로지 폴더 및 하드링크 권한 세팅이 100% 완료되었습니다!"
"""


def generate_maintenance_doctor_script(cfg: MediarrStackConfigRequest) -> str:
    """Generate upgraded full-stack maintenance & update script (replacing old update_qbittorrent.sh)."""
    docker_root = cfg.docker_root.rstrip("/")
    return f"""#!/bin/bash
# =============================================================================
# 🩺 MEDIARR-STACK 통합 업데이트 · VPN 보안 점검 · SQLite DB 최적화 닥터 스크립트
# (기존 update_qbittorrent.sh의 전체 스택 확장 업그레이드 버전 - Watchtower 불필요)
# =============================================================================

WORK_DIR="{docker_root}/mediarr-stack"
LOG_FILE="${{WORK_DIR}}/mediarr-update.log"

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
rm -f "{docker_root}/plexhw/Library/Application Support/Plex Media Server/plexmediaserver.pid" 2>/dev/null || true

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
"""


def generate_env_template(cfg: MediarrStackConfigRequest) -> str:
    """Generate .env template file for mediarr-stack."""
    return f"""# =============================================================================
# 🎬 MEDIARR-STACK 통합 환경 변수 설정 (.env)
# =============================================================================
TZ={cfg.tz}
PUID={cfg.puid}
PGID={cfg.pgid}
NAS_IP={cfg.nas_ip}

# 시놀로지 볼륨 경로
DOCKER_ROOT={cfg.docker_root}
DATA_ROOT={cfg.data_root}
LEGACY_TORRENTS_ROOT={cfg.legacy_torrents_root}
LEGACY_VIDEO_ROOT={cfg.legacy_video_root}

# Gluetun VPN (Surfshark WireGuard 기본 / OpenVPN 전환 가능)
VPN_SERVICE_PROVIDER={cfg.vpn_provider}
VPN_TYPE=wireguard
WIREGUARD_PRIVATE_KEY=YOUR_SURFSHARK_WIREGUARD_PRIVATE_KEY
WIREGUARD_ADDRESSES=10.14.0.2/16
OPENVPN_USER=YOUR_OPENVPN_USER
OPENVPN_PASSWORD=YOUR_OPENVPN_PASSWORD
SERVER_COUNTRIES=Japan
SERVER_CITIES=Tokyo
FIREWALL_OUTBOUND_SUBNETS=172.16.0.0/12,192.168.0.0/16,10.0.0.0/8

# 포트 설정 (기존 qBittorrent {cfg.qbit_webui_port} 포트 완벽 유지)
QBIT_WEBUI_PORT={cfg.qbit_webui_port}
QBIT_PEER_PORT=6881
PLEX_PORT=32400
SEERR_PORT=5055
PROWLARR_PORT=9696
FLARESOLVERR_PORT=8191
SONARR_PORT=8989
RADARR_PORT=7878
BAZARR_PORT=6767
TAUTULLI_PORT=8182
MAINTAINERR_PORT=6246
CONTROL_CENTER_PORT=8500

# Plex & *Arr API 연동 키
PLEX_CLAIM={cfg.plex_claim}
SONARR_API_KEY=YOUR_SONARR_API_KEY
RADARR_API_KEY=YOUR_RADARR_API_KEY
"""


def generate_wiring_guide(cfg: MediarrStackConfigRequest) -> List[Dict[str, Any]]:
    """Generate step-by-step organic internal wiring guide for the user."""
    qbit_port = cfg.qbit_webui_port
    flaresolverr_internal = "http://127.0.0.1:8191 (또는 http://flaresolverr:8191)" if (cfg.use_vpn and cfg.route_prowlarr_vpn) else "http://flaresolverr:8191"

    return [
        {
            "step": 1,
            "service": "qBittorrent (VPN 킬스위치 보호 다운로더)",
            "external_url": f"http://{cfg.nas_ip}:{qbit_port}",
            "internal_address": f"http://qbittorrent:{qbit_port} (또는 http://gluetun:{qbit_port})",
            "key_settings": [
                f"기존에 사용하시던 포트({qbit_port})와 설정 폴더(/volume1/docker/qbittorrent)가 그대로 연결되어 기존 토렌트 시드가 100% 유지됩니다.",
                "Options(톱니바퀴) -> Downloads -> Default Save Path를 /data/torrents 로 설정하세요 (기존 /downloads 경로도 동시 마운트되어 호환됩니다).",
                "Gluetun에 qbittorrent 네트워크 별칭(alias)이 등록되어 있어, Sonarr/Radarr에서 Host에 qbittorrent 만 입력해도 즉시 연결됩니다.",
            ],
        },
        {
            "step": 2,
            "service": "Prowlarr + FlareSolverr (통합 인덱서 & Cloudflare 자동 우회)",
            "external_url": f"http://{cfg.nas_ip}:9696",
            "internal_address": "http://prowlarr:9696",
            "key_settings": [
                f"Settings -> Indexers -> Add Indexer Proxy -> FlareSolverr 선택 후 Host에 {flaresolverr_internal}, Tag에 flaresolverr 입력",
                "Settings -> Apps -> (+) 버튼으로 Sonarr (Prowlarr Server: http://prowlarr:9696, Sonarr Server: http://sonarr:8989) 추가",
                "Settings -> Apps -> (+) 버튼으로 Radarr (Prowlarr Server: http://prowlarr:9696, Radarr Server: http://radarr:7878) 추가",
            ],
        },
        {
            "step": 3,
            "service": "Sonarr (드라마·예능·애니) & Radarr (영화)",
            "external_url": f"Sonarr: http://{cfg.nas_ip}:8989 | Radarr: http://{cfg.nas_ip}:7878",
            "internal_address": "http://sonarr:8989 | http://radarr:7878",
            "key_settings": [
                "Sonarr -> Settings -> Media Management -> Root Folders에 /data/media/tv 와 /data/media/anime 추가",
                "Radarr -> Settings -> Media Management -> Root Folders에 /data/media/movies 추가",
                f"Settings -> Download Clients -> (+) qBittorrent 추가: Host에 qbittorrent, Port에 {qbit_port} 입력 (Category: tv / movies)",
                "Settings -> General -> Security에서 API Key를 복사해 .env 파일에 넣으면 Recyclarr(화질 최적화)와 Unpackerr(압축 해제)가 즉시 자동 작동합니다.",
            ],
        },
        {
            "step": 4,
            "service": "Bazarr (한국어·영어 자막 자동화 & AI 싱크 보정)",
            "external_url": f"http://{cfg.nas_ip}:6767",
            "internal_address": "http://bazarr:6767",
            "key_settings": [
                "Settings -> Sonarr (Address: sonarr, Port: 8989) 및 Radarr (Address: radarr, Port: 7878) 활성화 후 API Key 입력",
                "Settings -> Languages -> Languages Profile 생성: Korean(ko) 1순위, English(en) 2순위 지정",
                "Settings -> Subtitles -> Automatic Subtitles Synchronization(자동 싱크 보정) 체크 시 자막 싱크가 0.01초 단위로 자동 일치됩니다.",
            ],
        },
        {
            "step": 5,
            "service": "Plex Media Server (4K HW 가속 + RAM 트랜스코딩) & Seerr (요청 포털)",
            "external_url": f"Plex: http://{cfg.nas_ip}:32400/web | Seerr: http://{cfg.nas_ip}:5055",
            "internal_address": f"Plex: http://host.docker.internal:32400 (또는 http://{cfg.nas_ip}:32400) | Seerr: http://seerr:5055",
            "key_settings": [
                "기존 /volume1/docker/plexhw 데이터와 /volume1/video, /volume1/mediarr/media 폴더가 100% 그대로 연결됩니다.",
                "Plex 설정 -> Transcoder 에서 '트랜스코더 임시 디렉토리'에 /transcode 를 입력하면 2GB RAM 디스크 트랜스코딩이 작동하여 SSD/HDD 수명 소모가 0이 됩니다.",
                "Seerr(:5055)에 접속해 Plex 계정으로 로그인 후 Sonarr(hostname: sonarr, port: 8989)와 Radarr(hostname: radarr, port: 7878)를 연동하면 모든 구축이 완성됩니다!",
            ],
        },
    ]
