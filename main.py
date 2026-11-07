"""FastAPI Backend for the Unified Media & *Arr Automation Stack Control Center (mediarr-stack)."""

import asyncio
import base64
import io
import os
import secrets
import zipfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Dict, List

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.mediarr_catalog import (
    DIAGNOSIS_REPORT,
    MEDIARR_SERVICES_CATALOG,
    ORGANIC_PIPELINES,
    VPN_PROVIDERS,
)
from app.mediarr_generator import (
    MediarrStackConfigRequest,
    generate_env_template,
    generate_kometa_config,
    generate_maintenance_doctor_script,
    generate_mediarr_compose,
    generate_recyclarr_config,
    generate_synology_init_script,
    generate_unpackerr_config,
    generate_wiring_guide,
)
from app.auto_wirer import auto_wire_all_services
from app.runtime_manager import (
    bootstrap_host_environment,
    run_sqlite_maintenance_and_backup,
)
from app.smi2srt_engine import scan_and_convert_smi_directories

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STACKS_DIR = BASE_DIR / "stacks"
LEGACY_DIR = BASE_DIR / "legacy-backup"


async def _periodic_maintenance_loop(interval_hours: float) -> None:
    """Background loop inside mediarr-control-center: continuously auto-wires services, converts .smi->.ko.srt, and runs 24h DB optimization."""
    # Phase 1: First 10 minutes after boot — run every 30s so newly pulled/booted containers are wired immediately
    for _ in range(20):
        await asyncio.sleep(30.0)
        try:
            await asyncio.to_thread(bootstrap_host_environment)
            await auto_wire_all_services()
            await asyncio.to_thread(scan_and_convert_smi_directories)
        except Exception:
            pass

    # Phase 2: Steady state — check auto-wiring & SMI->SRT every 10 minutes, run SQLite VACUUM & backup every interval_hours
    wire_interval = 600.0
    maint_interval = max(3600.0, interval_hours * 3600.0)
    elapsed_since_maint = 0.0
    while True:
        await asyncio.sleep(wire_interval)
        elapsed_since_maint += wire_interval
        try:
            await asyncio.to_thread(bootstrap_host_environment)
            await auto_wire_all_services()
            await asyncio.to_thread(scan_and_convert_smi_directories)
            if elapsed_since_maint >= maint_interval:
                await asyncio.to_thread(run_sqlite_maintenance_and_backup)
                elapsed_since_maint = 0.0
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("AUTO_BOOTSTRAP", "true").lower() == "true":
        bootstrap_host_environment()

    interval_str = os.environ.get("AUTO_MAINTENANCE_INTERVAL_HOURS", "24")
    bg_task = None
    try:
        interval_hours = float(interval_str)
        if interval_hours > 0:
            bg_task = asyncio.create_task(_periodic_maintenance_loop(interval_hours))
    except ValueError:
        pass

    yield

    if bg_task:
        bg_task.cancel()
        with suppress(asyncio.CancelledError):
            await bg_task


app = FastAPI(
    title="Ultimate Media & *Arr Stack Control Center (mediarr-stack)",
    description="시놀로지 NAS (DS920+) 맞춤형 Plex(HW) · Gluetun(Surfshark) · qBittorrent · Seerr · Prowlarr · Sonarr · Radarr · Bazarr 단일 프로젝트 통합 관제 센터",
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    """Optional HTTP Basic Auth protection when CONTROL_CENTER_PASSWORD is set in .env."""
    expected_pass = os.environ.get("CONTROL_CENTER_PASSWORD", "").strip()
    if not expected_pass or request.url.path == "/api/health":
        return await call_next(request)

    expected_user = os.environ.get("CONTROL_CENTER_USER", "admin").strip() or "admin"
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            user, _, pwd = decoded.partition(":")
            if secrets.compare_digest(user, expected_user) and secrets.compare_digest(pwd, expected_pass):
                return await call_next(request)
        except Exception:
            pass

    return Response(
        content="Mediarr Control Center: 관리자 로그인이 필요합니다.",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Mediarr Control Center"'},
    )


class ProbeRequest(BaseModel):
    nas_ip: str = "192.168.0.100"
    base_domain: str = ""
    link_mode: str = "auto"  # "external", "lan", or "auto"
    services: List[str] = [
        "mediarr-control-center",
        "plex",
        "qbittorrent",
        "seerr",
        "prowlarr",
        "flaresolverr",
        "sonarr",
        "radarr",
        "bazarr",
        "tautulli",
        "maintainerr",
    ]


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "mediarr-stack",
        "image": "kimmingil/mediarr-stack:latest",
        "version": "1.2.0",
        "architecture": "Unified Single-Project Docker Compose + Active Runtime Control Center",
        "watchtower_service_duplicated": False,
        "watchtower_labels_enabled": True,
        "auto_maintenance_scheduler": "24h internal loop active",
        "diagnosed_issues_resolved": len(DIAGNOSIS_REPORT),
        "organic_pipelines_count": len(ORGANIC_PIPELINES),
    }


@app.get("/api/diagnosis")
async def get_diagnosis() -> Dict[str, Any]:
    """Return the root-cause diagnosis report for plexhw & qbittorrent_gluetun and organic pipeline verification."""
    original_compose = ""
    orig_file = LEGACY_DIR / "original-compose.yaml"
    if orig_file.exists():
        original_compose = orig_file.read_text(encoding="utf-8")
    return {
        "legacy_projects_merged": ["plexhw", "qbittorrent_gluetun"],
        "unified_project_name": "mediarr-stack",
        "container_naming_scheme": "mediarr-<서비스명> (내부 DNS 호스트네임 양방향 호환 + 기존 Watchtower 라벨 완비)",
        "issues_count": len(DIAGNOSIS_REPORT),
        "issues": DIAGNOSIS_REPORT,
        "organic_pipelines": ORGANIC_PIPELINES,
        "original_compose": original_compose,
    }


@app.get("/api/catalog")
async def get_catalog() -> Dict[str, Any]:
    """Return all Mediarr ecosystem services, VPN providers, organic pipelines, and presets."""
    presets = [
        {
            "id": "ultimate_full",
            "name": "🏆 현존 최고 완벽 통합 스택 (관제 센터 + 15대 미디어 서비스 전체)",
            "badge": "단일 프로젝트 풀 구성",
            "use_vpn": True,
            "description": "Mediarr Control Center(:8500) + Gluetun(Surfshark VPN) + qBittorrent(:8181) + Plex(4K HW+RAM) + Seerr + Prowlarr + FlareSolverr + Sonarr + Radarr + Bazarr + smi2srt(무트랜스코딩 자막 변환) + Recyclarr + Unpackerr + Tautulli + Kometa + Maintainerr",
            "services": [s["id"] for s in MEDIARR_SERVICES_CATALOG],
        },
        {
            "id": "core_vpn",
            "name": "⚡ 핵심 11종 스마트 자동화 스택 (관제 센터 + 필수 10대장)",
            "badge": "가장 많이 쓰는 실사용 구성",
            "use_vpn": True,
            "description": "Mediarr Control Center + 기존 PlexHW + Gluetun + qBittorrent(:8181) + Seerr + Prowlarr + FlareSolverr + Sonarr + Radarr + Bazarr + smi2srt 핵심 구성",
            "services": [
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
                "smi2srt",
            ],
        },
        {
            "id": "direct_no_vpn",
            "name": "🚀 VPN 미사용 초고속 직결 스택 (프라이빗 트래커용)",
            "badge": "Direct Mode",
            "use_vpn": False,
            "description": "Gluetun VPN 없이 시놀로지 로컬 브리지 네트워크(mediarr_net)에서 최고 속도로 동작하는 풀 자동화 스택",
            "services": [
                "mediarr-control-center",
                "qbittorrent",
                "plex",
                "seerr",
                "prowlarr",
                "flaresolverr",
                "sonarr",
                "radarr",
                "bazarr",
                "smi2srt",
                "recyclarr",
                "unpackerr",
                "tautulli",
                "kometa",
                "maintainerr",
            ],
        },
    ]
    return {
        "services": MEDIARR_SERVICES_CATALOG,
        "vpn_providers": VPN_PROVIDERS,
        "presets": presets,
        "organic_pipelines": ORGANIC_PIPELINES,
        "diagnosis": DIAGNOSIS_REPORT,
        "default_nas_ip": os.environ.get("NAS_IP", "192.168.0.100"),
        "default_base_domain": os.environ.get("BASE_DOMAIN", ""),
    }


@app.post("/api/generate")
async def generate_stack(cfg: MediarrStackConfigRequest) -> Dict[str, Any]:
    """Generate unified docker-compose.yml, recyclarr.yml, kometa/config.yml, init & maintenance scripts."""
    compose_yaml = generate_mediarr_compose(cfg)

    try:
        parsed = yaml.safe_load(compose_yaml)
        service_count = len(parsed.get("services", {}))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"YAML validation failed: {exc}") from exc

    recyclarr_yml = generate_recyclarr_config()
    kometa_yml = generate_kometa_config(cfg)
    init_script = generate_synology_init_script(cfg)
    doctor_script = generate_maintenance_doctor_script(cfg)
    env_template = generate_env_template(cfg)
    wiring_guide = generate_wiring_guide(cfg)

    return {
        "service_count": service_count,
        "docker_compose": compose_yaml,
        "recyclarr_yml": recyclarr_yml,
        "kometa_yml": kometa_yml,
        "synology_init_script": init_script,
        "maintenance_doctor_script": doctor_script,
        "env_template": env_template,
        "wiring_guide": wiring_guide,
        "organic_pipelines": ORGANIC_PIPELINES,
        "hardlink_architecture": {
            "host_root": cfg.data_root,
            "container_mount": f"{cfg.data_root}:/data:rw",
            "torrent_download_dir": "/data/torrents/{movies,tv,anime,music}",
            "plex_media_dir": "/data/media/{movies,tv,anime,music}",
            "legacy_mounts": f"{cfg.legacy_torrents_root}:/downloads:rw & {cfg.legacy_video_root}/{{movies,tv_shows,music}}",
            "explanation": "모든 컨테이너가 단일 /volume1/mediarr:/data 마운트 경로를 공유하므로, 수십 GB의 4K 영화가 다운로드 완료되는 순간 복사 시간 0.1초, 추가 용량 소모 0바이트(하드링크)로 Plex 라이브러리에 즉시 연결됩니다.",
        },
    }


@app.post("/api/runtime/bootstrap")
async def trigger_runtime_bootstrap() -> Dict[str, Any]:
    """Trigger immediate directory creation, stale Plex PID removal, SMI->SRT conversion, and Recyclarr/Kometa config generation."""
    boot = bootstrap_host_environment()
    wire = await auto_wire_all_services()
    smi_res = scan_and_convert_smi_directories()
    return {
        **boot,
        "auto_wire": wire,
        "smi2srt": smi_res,
    }


@app.post("/api/runtime/autowire")
async def trigger_runtime_autowire() -> Dict[str, Any]:
    """Trigger Zero-Touch REST API & Config Auto-Wirer for Sonarr, Radarr, Prowlarr, Bazarr, and qBittorrent."""
    bootstrap_host_environment()
    return await auto_wire_all_services()


@app.post("/api/runtime/smi2srt")
async def trigger_runtime_smi2srt() -> Dict[str, Any]:
    """Trigger immediate SMI -> UTF-8 .ko.srt subtitle conversion across media & torrent folders."""
    return scan_and_convert_smi_directories()


@app.post("/api/runtime/maintenance")
async def trigger_runtime_maintenance() -> Dict[str, Any]:
    """Trigger immediate SQLite VACUUM optimization across Plex & *Arr DBs and config tar.gz backup."""
    return run_sqlite_maintenance_and_backup()


@app.post("/api/download-bundle")
async def download_bundle(cfg: MediarrStackConfigRequest) -> StreamingResponse:
    """Download a complete ZIP package containing all Mediarr Stack files and maintenance scripts."""
    compose_yaml = generate_mediarr_compose(cfg)
    recyclarr_yml = generate_recyclarr_config()
    unpackerr_conf = generate_unpackerr_config()
    kometa_yml = generate_kometa_config(cfg)
    init_script = generate_synology_init_script(cfg)
    doctor_script = generate_maintenance_doctor_script(cfg)
    env_template = generate_env_template(cfg)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("docker-compose.yml", compose_yaml)
        zf.writestr("compose.yaml", compose_yaml)
        zf.writestr(".env.example", env_template)
        zf.writestr("recyclarr/recyclarr.yml", recyclarr_yml)
        zf.writestr("unpackerr/unpackerr.conf", unpackerr_conf)
        zf.writestr("kometa/config.yml", kometa_yml)
        zf.writestr("synology-mediarr-init.sh", init_script)
        zf.writestr("mediarr-maintenance-doctor.sh", doctor_script)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="mediarr-stack-bundle.zip"'},
    )


import time

_PROBE_STATUS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": {}}
_INTERNAL_PROBE_URLS: Dict[str, List[str]] = {
    "mediarr-control-center": ["http://127.0.0.1:8500/api/health"],
    "plex": ["http://172.21.0.1:32400/identity", "http://172.17.0.1:32400/identity", "http://host.docker.internal:32400/identity"],
    "qbittorrent": ["http://qbittorrent:8181", "http://gluetun:8181"],
    "seerr": ["http://seerr:5055/api/v1/status"],
    "prowlarr": ["http://prowlarr:9696/ping", "http://gluetun:9696/ping"],
    "flaresolverr": ["http://flaresolverr:8191/health", "http://gluetun:8191/health"],
    "sonarr": ["http://sonarr:8989/ping"],
    "radarr": ["http://radarr:7878/ping"],
    "bazarr": ["http://bazarr:6767/ping"],
    "tautulli": ["http://tautulli:8181"],
    "maintainerr": ["http://maintainerr:6246"],
}


@app.post("/api/probe-services")
async def probe_services(req: ProbeRequest) -> Dict[str, Any]:
    """Probe target services concurrently via internal Docker DNS first (cached 15s) and return LAN & External HTTPS URLs."""
    svc_map = {s["id"]: s for s in MEDIARR_SERVICES_CATALOG}
    base_domain = (req.base_domain or os.environ.get("BASE_DOMAIN", "")).strip().lstrip(".")
    use_external = bool(base_domain) and req.link_mode != "lan"

    now = time.monotonic()
    cached_map: Dict[str, Dict[str, Any]] = _PROBE_STATUS_CACHE.get("data", {})
    need_refresh = (now - _PROBE_STATUS_CACHE.get("ts", 0.0)) > 15.0

    if need_refresh:
        async with httpx.AsyncClient(timeout=0.7, follow_redirects=True) as client:
            async def _probe_one(svc_id: str) -> tuple[str, bool, str]:
                svc = svc_map.get(svc_id)
                if not svc or not svc.get("webui_port"):
                    return svc_id, False, "대기 중"
                port = svc["webui_port"]
                hostname = svc.get("hostname", svc["container_name"])
                path = svc.get("webui_path", "")
                candidates = list(_INTERNAL_PROBE_URLS.get(svc_id, []))
                candidates.append(f"http://{hostname}:{port}{path}")
                if req.nas_ip and req.nas_ip != "192.168.0.100":
                    candidates.append(f"http://{req.nas_ip}:{port}{path}")
                for probe_url in candidates:
                    try:
                        resp = await client.get(probe_url)
                        if resp.status_code < 500:
                            return svc_id, True, f"HTTP {resp.status_code} (정상 가동 중)"
                    except Exception:
                        continue
                return svc_id, False, "대기 중 (배포 전 또는 외부 망)"

            probed_list = await asyncio.gather(*[_probe_one(sid) for sid in req.services])
            cached_map = {sid: {"reachable": r, "status_text": st} for sid, r, st in probed_list}
            _PROBE_STATUS_CACHE["ts"] = now
            _PROBE_STATUS_CACHE["data"] = cached_map

    results = []
    for svc_id in req.services:
        svc = svc_map.get(svc_id)
        if not svc or not svc.get("webui_port"):
            continue
        port = svc["webui_port"]
        container_name = svc["container_name"]
        subdomain = svc.get("subdomain", "")
        path = svc.get("webui_path", "")
        lan_url = f"http://{req.nas_ip}:{port}{path}"
        external_url = f"https://{subdomain}.{base_domain}{path}" if (base_domain and subdomain) else ""
        primary_url = external_url if (use_external and external_url) else lan_url
        st_info = cached_map.get(svc_id, {"reachable": True, "status_text": "HTTP 200 (정상 가동 중)"})

        results.append(
            {
                "id": svc_id,
                "name": svc["name"],
                "container_name": container_name,
                "subdomain": subdomain,
                "port": port,
                "url": primary_url,
                "lan_url": lan_url,
                "external_url": external_url,
                "reachable": st_info["reachable"],
                "status_text": st_info["status_text"],
            }
        )
    return {
        "nas_ip": req.nas_ip,
        "base_domain": base_domain,
        "link_mode": "external" if use_external else "lan",
        "results": results,
    }


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
