"""Automated Unit & Integration Tests for the Unified Mediarr Stack Control Center (mediarr-stack)."""

import io
import sqlite3
import zipfile
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.runtime_manager import (
    bootstrap_host_environment,
    run_sqlite_maintenance_and_backup,
)
from main import app

client = TestClient(app)


def test_health_check():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["service"] == "mediarr-stack"
    assert data["image"] == "kimmingil/mediarr-stack:latest"
    assert data["watchtower_included"] is False
    assert data["diagnosed_issues_resolved"] == 8
    assert data["organic_pipelines_count"] == 5


def test_diagnosis_and_catalog_no_marius_no_watchtower():
    diag_res = client.get("/api/diagnosis")
    assert diag_res.status_code == 200
    diag = diag_res.json()
    assert diag["unified_project_name"] == "mediarr-stack"
    assert len(diag["issues"]) == 8

    cat_res = client.get("/api/catalog")
    assert cat_res.status_code == 200
    cat = cat_res.json()
    service_ids = [s["id"] for s in cat["services"]]
    assert "watchtower" not in service_ids
    assert "mediarr-control-center" in service_ids
    assert len(service_ids) == 15

    for svc in cat["services"]:
        assert "marius" not in svc["container_name"].lower()
        assert "watchtower" not in svc["container_name"].lower()


def test_generate_full_compose_organic_integration():
    res = client.post(
        "/api/generate",
        json={
            "nas_ip": "192.168.0.100",
            "qbit_webui_port": 8181,
            "use_vpn": True,
            "vpn_provider": "surfshark",
            "route_prowlarr_vpn": True,
            "enable_hw_transcoding": True,
        },
    )
    assert res.status_code == 200
    payload = res.json()
    compose_str = payload["docker_compose"]

    # Ensure no marius or watchtower anywhere in generated compose
    assert "marius" not in compose_str.lower()
    assert "watchtower" not in compose_str.lower()

    parsed = yaml.safe_load(compose_str)
    assert "mediarr_net" in parsed["networks"]
    services = parsed["services"]
    assert len(services) == 15
    assert "mediarr-control-center" in services

    # Verify Gluetun firewall subnets, healthcheck, and aliases
    gluetun = services["gluetun"]
    assert gluetun["container_name"] == "mediarr-gluetun"
    assert "FIREWALL_OUTBOUND_SUBNETS" in gluetun["environment"]
    assert "healthcheck" in gluetun
    aliases = gluetun["networks"]["mediarr_net"]["aliases"]
    assert "qbittorrent" in aliases
    assert "prowlarr" in aliases
    assert "flaresolverr" in aliases

    # Verify qBittorrent legacy compatibility (port 8181, /downloads, /data)
    qbit = services["qbittorrent"]
    assert qbit["container_name"] == "mediarr-qbittorrent"
    assert qbit["environment"]["WEBUI_PORT"] == 8181
    assert any("/volume1/mediarr:/data:rw" in v for v in qbit["volumes"])
    assert any("/volume1/torrents:/downloads:rw" in v for v in qbit["volumes"])

    # Verify Plex HW transcoding + RAM transcode + legacy /volume1/docker/plexhw
    plex = services["plex"]
    assert plex["container_name"] == "mediarr-plex"
    assert any("/volume1/docker/plexhw:/config:rw" in v for v in plex["volumes"])
    assert any("/transcode:size=2G" in t for t in plex["tmpfs"])


def test_runtime_bootstrap_and_sqlite_maintenance(tmp_path: Path):
    docker_root = tmp_path / "docker"
    data_root = tmp_path / "mediarr"
    docker_root.mkdir()
    data_root.mkdir()

    # Create a fake stale Plex PID file
    pid_dir = docker_root / "plexhw/Library/Application Support/Plex Media Server"
    pid_dir.mkdir(parents=True)
    stale_pid = pid_dir / "plexmediaserver.pid"
    stale_pid.write_text("12345", encoding="utf-8")

    # Run bootstrap
    boot_res = bootstrap_host_environment(docker_root=docker_root, data_root=data_root)
    assert boot_res["executed"] is True
    assert not stale_pid.exists()
    assert (docker_root / "recyclarr/recyclarr.yml").exists()
    assert (docker_root / "kometa/config.yml").exists()
    assert (data_root / "torrents/movies").is_dir()
    assert (data_root / "media/anime").is_dir()

    # Create sample SQLite DBs to test VACUUM & WAL checkpoint
    sonarr_db = docker_root / "sonarr/sonarr.db"
    conn = sqlite3.connect(str(sonarr_db))
    conn.execute("CREATE TABLE series (id INTEGER PRIMARY KEY, title TEXT);")
    conn.execute("INSERT INTO series (title) VALUES ('Moving');")
    conn.commit()
    conn.close()

    maint_res = run_sqlite_maintenance_and_backup(docker_root=docker_root, data_root=data_root)
    assert maint_res["status"] == "ok"
    assert any("sonarr.db" in p for p in maint_res["optimized_databases"])
    assert len(maint_res["backups_created"]) >= 2


def test_download_bundle_zip():
    res = client.post("/api/download-bundle", json={})
    assert res.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = zf.namelist()
    assert "docker-compose.yml" in names
    assert "compose.yaml" in names
    assert ".env.example" in names
    assert "recyclarr/recyclarr.yml" in names
    assert "kometa/config.yml" in names
    assert "synology-mediarr-init.sh" in names
    assert "mediarr-maintenance-doctor.sh" in names
