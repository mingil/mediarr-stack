"""Runtime Auto-Bootstrapper, Self-Healing PID Cleaner, SQLite Optimizer & Backup Engine for mediarr-control-center."""

import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from app.mediarr_generator import (
    MediarrStackConfigRequest,
    generate_kometa_config,
    generate_recyclarr_config,
)

BASE_PROJECT_DIR = Path(__file__).resolve().parent.parent


def get_mount_paths() -> Dict[str, Path]:
    docker_mount = Path(os.environ.get("HOST_DOCKER_MOUNT", "/host-docker"))
    data_mount = Path(os.environ.get("HOST_DATA_MOUNT", "/host-data"))
    return {"docker": docker_mount, "data": data_mount}


def clean_stale_pid_files(search_roots: List[Path]) -> List[str]:
    """Remove stale plexmediaserver.pid or lock files that prevent container startup."""
    removed: List[str] = []
    rel_candidates = [
        "plexhw/Library/Application Support/Plex Media Server/plexmediaserver.pid",
        "Library/Application Support/Plex Media Server/plexmediaserver.pid",
    ]
    for root in search_roots:
        if not root or not root.exists():
            continue
        for rel in rel_candidates:
            candidate = root / rel
            if candidate.exists() and candidate.is_file():
                try:
                    candidate.unlink()
                    removed.append(str(candidate))
                except Exception:
                    pass
    return removed


def bootstrap_host_environment(
    docker_root: Path | None = None,
    data_root: Path | None = None,
) -> Dict[str, Any]:
    """Automatically provision folders, clean stale Plex PID files, and write recyclarr.yml & kometa/config.yml."""
    mounts = get_mount_paths()
    d_root = docker_root or mounts["docker"]
    m_root = data_root or mounts["data"]

    actions: List[str] = []

    # Always check local uploaded plexhw folder for stale PID files as well
    local_plexhw = BASE_PROJECT_DIR / "plexhw"
    pid_removed = clean_stale_pid_files([d_root, BASE_PROJECT_DIR, local_plexhw])
    if pid_removed:
        actions.append(f"비정상 종료 잔여 Plex PID 파일 {len(pid_removed)}개 자동 감지 및 제거 완료")

    if not d_root.exists() and not m_root.exists():
        return {
            "executed": bool(pid_removed),
            "mode": "preview_standalone",
            "message": "호스트 마운트(/host-docker, /host-data) 미감지: 스튜디오 프리뷰 및 로컬 진단 모드로 동작합니다.",
            "actions": actions,
        }

    # 1. Create config directories
    config_subdirs = [
        "gluetun",
        "qbittorrent",
        "plexhw",
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
        "_backups/mediarr-stack",
    ]
    if d_root.exists():
        for sub in config_subdirs:
            (d_root / sub).mkdir(parents=True, exist_ok=True)
        actions.append(f"도커 설정 폴더 {len(config_subdirs)}개 확인 및 자동 생성 완료 ({d_root})")

        # 2. Auto-generate recyclarr.yml if missing
        recyclarr_yml_path = d_root / "recyclarr/recyclarr.yml"
        if not recyclarr_yml_path.exists():
            recyclarr_yml_path.write_text(generate_recyclarr_config(), encoding="utf-8")
            actions.append("TRaSH Guides 화질 자동화 설정 파일(recyclarr/recyclarr.yml) 자동 생성 완료")

        # 3. Auto-generate Kometa config.yml if missing
        kometa_yml_path = d_root / "kometa/config.yml"
        if not kometa_yml_path.exists():
            cfg = MediarrStackConfigRequest(
                nas_ip=os.environ.get("NAS_IP", "192.168.0.100"),
            )
            kometa_yml_path.write_text(generate_kometa_config(cfg), encoding="utf-8")
            actions.append("Kometa 포스터 4K·HDR·평점 배지 설정 템플릿(kometa/config.yml) 자동 생성 완료")

    # 4. Create TRaSH Guides unified hardlink directory tree (/data/torrents & /data/media)
    media_subdirs = [
        "torrents/movies",
        "torrents/tv",
        "torrents/anime",
        "torrents/music",
        "media/movies",
        "media/tv",
        "media/anime",
        "media/music",
    ]
    if m_root.exists():
        for sub in media_subdirs:
            (m_root / sub).mkdir(parents=True, exist_ok=True)
        actions.append(f"TRaSH Guides 단일 볼륨 하드링크 폴더 트리 {len(media_subdirs)}개 자동 생성 완료 ({m_root})")

    return {
        "executed": True,
        "mode": "active_container_management",
        "message": "통합 관제 엔진이 폴더 구조·PID 정리·TRaSH 설정 파일을 완벽히 초기화했습니다.",
        "actions": actions,
    }


def run_sqlite_maintenance_and_backup(
    docker_root: Path | None = None,
    data_root: Path | None = None,
) -> Dict[str, Any]:
    """Run Python-native SQLite VACUUM/ANALYZE optimization across Plex & *Arr DBs and create config backups."""
    mounts = get_mount_paths()
    d_root = docker_root or mounts["docker"]
    _ = data_root or mounts["data"]

    optimized_dbs: List[str] = []
    backups_created: List[str] = []

    pid_removed = clean_stale_pid_files([d_root, BASE_PROJECT_DIR])

    db_candidates = [
        d_root / "plexhw/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db",
        d_root / "plexhw/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.dlna.db",
        d_root / "sonarr/sonarr.db",
        d_root / "sonarr/logs.db",
        d_root / "radarr/radarr.db",
        d_root / "radarr/logs.db",
        d_root / "prowlarr/prowlarr.db",
        d_root / "prowlarr/logs.db",
        d_root / "bazarr/db/bazarr.db",
        d_root / "tautulli/tautulli.db",
        d_root / "seerr/db/db.sqlite3",
    ]
    if docker_root is None:
        db_candidates.extend([
            BASE_PROJECT_DIR / "plexhw/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.dlna.db",
            BASE_PROJECT_DIR / "plexhw/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db",
        ])

    seen_paths = set()
    for db_path in db_candidates:
        resolved_str = str(db_path)
        if resolved_str in seen_paths:
            continue
        seen_paths.add(resolved_str)
        if db_path.exists() and db_path.is_file():
            try:
                conn = sqlite3.connect(str(db_path), timeout=15.0)
                if "com.plexapp.plugins.library" in db_path.name:
                    # Plex library.db uses custom 'icu_root' collation; use safe WAL checkpoint & optimize
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    conn.execute("PRAGMA optimize;")
                else:
                    conn.execute("PRAGMA optimize;")
                    conn.execute("VACUUM;")
                    conn.execute("ANALYZE;")
                conn.close()
                optimized_dbs.append(str(db_path))
            except Exception as exc:
                optimized_dbs.append(f"{db_path} (스킵: {exc})")

    if d_root.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = d_root / "_backups/mediarr-stack" / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        for svc in ["gluetun", "qbittorrent", "seerr", "prowlarr", "sonarr", "radarr", "bazarr", "recyclarr", "unpackerr", "tautulli", "kometa"]:
            cfg_dir = d_root / svc
            if cfg_dir.exists() and any(cfg_dir.iterdir()):
                archive_path = backup_dir / f"{svc}_config_{timestamp}.tar.gz"
                with tarfile.open(archive_path, "w:gz") as tar:
                    tar.add(cfg_dir, arcname=svc)
                backups_created.append(str(archive_path))

        # Prune backups older than 30 days
        cutoff = datetime.now() - timedelta(days=30)
        parent_backup = d_root / "_backups/mediarr-stack"
        if parent_backup.exists():
            for child in parent_backup.iterdir():
                if child.is_dir():
                    mtime = datetime.fromtimestamp(child.stat().st_mtime)
                    if mtime < cutoff:
                        shutil.rmtree(child, ignore_errors=True)

    return {
        "status": "ok",
        "stale_pids_removed": pid_removed,
        "optimized_databases": optimized_dbs,
        "backups_created": backups_created,
        "summary": f"SQLite DB 최적화 {len(optimized_dbs)}건, 잔여 PID 제거 {len(pid_removed)}건, 설정 백업 {len(backups_created)}건 완료",
    }
