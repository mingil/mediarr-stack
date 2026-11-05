"""Automated Unit & Integration Tests for the Unified Mediarr Stack Control Center (mediarr-stack)."""

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from app.auto_wirer import (
    TRASH_RADARR_NAMING,
    TRASH_SONARR_NAMING,
    configure_prowlarr_via_api,
    configure_radarr_via_api,
    configure_sonarr_via_api,
    provision_bazarr_config,
    provision_qbittorrent_categories_and_conf,
    provision_seerr_settings,
)
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
    assert data["watchtower_service_duplicated"] is False
    assert data["watchtower_labels_enabled"] is True
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
    assert "smi2srt" in service_ids
    assert len(service_ids) == 16

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

    assert "marius" not in compose_str.lower()

    parsed = yaml.safe_load(compose_str)
    assert "mediarr_net" in parsed["networks"]
    services = parsed["services"]
    assert "watchtower" not in services
    assert len(services) == 16
    assert "mediarr-control-center" in services
    assert "smi2srt" in services
    assert services["smi2srt"]["image"] == "cpm0722/smi2srt:latest"
    assert services["seerr"]["image"] == "ghcr.io/seerr-team/seerr:latest"

    # Verify Watchtower labels on all services and depends-on=mediarr-gluetun on VPN-routed services
    for svc_name, svc_def in services.items():
        assert "com.centurylinklabs.watchtower.enable=true" in svc_def.get("labels", []), f"Missing watchtower label on {svc_name}"
        if svc_name != "mediarr-control-center":
            assert "mediarr-control-center" in svc_def.get("depends_on", {}), f"Missing boot dependency on {svc_name}"

    for vpn_svc in ["qbittorrent", "prowlarr", "flaresolverr"]:
        assert "com.centurylinklabs.watchtower.depends-on=mediarr-gluetun" in services[vpn_svc]["labels"]
        assert "gluetun" in services[vpn_svc]["depends_on"]

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


def test_runtime_bootstrap_auto_apikey_bridge_and_sqlite_maintenance(tmp_path: Path):
    docker_root = tmp_path / "docker"
    data_root = tmp_path / "mediarr"
    docker_root.mkdir()
    data_root.mkdir()

    # Simulate relocated plexhw/Library inside mediarr-stack/plexhw/Library
    relocated_lib = docker_root / "mediarr-stack/plexhw/Library/Application Support/Plex Media Server"
    relocated_lib.mkdir(parents=True)
    stale_pid = relocated_lib / "plexmediaserver.pid"
    stale_pid.write_text("12345", encoding="utf-8")
    (relocated_lib / "Preferences.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?><Preferences PlexOnlineToken="TEST_PLEX_TOKEN_123"/>',
        encoding="utf-8",
    )

    # Simulate Sonarr & Radarr config.xml with auto-generated API keys
    (docker_root / "sonarr").mkdir(parents=True)
    (docker_root / "sonarr/config.xml").write_text("<Config><ApiKey>SONARR_AUTO_KEY_999</ApiKey></Config>", encoding="utf-8")
    (docker_root / "radarr").mkdir(parents=True)
    (docker_root / "radarr/config.xml").write_text("<Config><ApiKey>RADARR_AUTO_KEY_888</ApiKey></Config>", encoding="utf-8")

    # Run bootstrap
    boot_res = bootstrap_host_environment(docker_root=docker_root, data_root=data_root)
    assert boot_res["executed"] is True

    # Verify Library was auto-restored to docker_root / "plexhw/Library" and stale PID removed
    restored_pms = docker_root / "plexhw/Library/Application Support/Plex Media Server"
    assert restored_pms.is_dir()
    assert not (restored_pms / "plexmediaserver.pid").exists()

    # Verify auto-bridged API keys in recyclarr.yml, unpackerr.conf, and kometa/config.yml
    recyclarr_txt = (docker_root / "recyclarr/recyclarr.yml").read_text(encoding="utf-8")
    assert "SONARR_AUTO_KEY_999" in recyclarr_txt
    assert "RADARR_AUTO_KEY_888" in recyclarr_txt

    unpackerr_txt = (docker_root / "unpackerr/unpackerr.conf").read_text(encoding="utf-8")
    assert "SONARR_AUTO_KEY_999" in unpackerr_txt
    assert "RADARR_AUTO_KEY_888" in unpackerr_txt

    kometa_txt = (docker_root / "kometa/config.yml").read_text(encoding="utf-8")
    assert "TEST_PLEX_TOKEN_123" in kometa_txt

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
    assert "unpackerr/unpackerr.conf" in names
    assert "kometa/config.yml" in names
    assert "synology-mediarr-init.sh" in names
    assert "mediarr-maintenance-doctor.sh" in names


def test_zero_touch_auto_wirer_files_and_rest_apis(tmp_path: Path):
    import asyncio

    docker_root = tmp_path / "docker"
    docker_root.mkdir()

    # 1. Test qBittorrent categories.json + qBittorrent.conf, Bazarr config.yaml & Seerr settings.json
    qbit_msg = provision_qbittorrent_categories_and_conf(docker_root)
    assert "설정 완료" in qbit_msg
    cats = json.loads((docker_root / "qbittorrent/qBittorrent/config/categories.json").read_text(encoding="utf-8"))
    assert cats["movies"]["save_path"] == "/data/torrents/movies"
    assert cats["tv"]["save_path"] == "/data/torrents/tv"
    assert cats["anime"]["save_path"] == "/data/torrents/anime"
    qbit_conf = (docker_root / "qbittorrent/qBittorrent/qBittorrent.conf").read_text(encoding="utf-8")
    assert "AuthSubnetWhitelistEnabled=true" in qbit_conf
    assert "/data/torrents" in qbit_conf

    baz_msg = provision_bazarr_config(docker_root, sonarr_api_key="S_KEY_1", radarr_api_key="R_KEY_2")
    assert "설정 완료" in baz_msg
    baz_cfg = yaml.safe_load((docker_root / "bazarr/config/config.yaml").read_text(encoding="utf-8"))
    assert baz_cfg["sonarr"]["apikey"] == "S_KEY_1"
    assert baz_cfg["radarr"]["apikey"] == "R_KEY_2"
    assert baz_cfg["subsync"]["use_subsync"] is True

    seerr_msg = provision_seerr_settings(
        docker_root, nas_ip="192.168.0.100", sonarr_api_key="S_KEY_1", radarr_api_key="R_KEY_2"
    )
    assert "자동 연동 완료" in seerr_msg
    seerr_cfg = json.loads((docker_root / "seerr/settings.json").read_text(encoding="utf-8"))
    assert seerr_cfg["plex"]["ip"] == "host.docker.internal"
    assert seerr_cfg["main"]["locale"] == "en"
    assert seerr_cfg["radarr"][0]["apiKey"] == "R_KEY_2"
    assert seerr_cfg["radarr"][0]["activeDirectory"] == "/data/media/movies"
    assert seerr_cfg["sonarr"][0]["apiKey"] == "S_KEY_1"
    assert seerr_cfg["sonarr"][0]["activeDirectory"] == "/data/media/tv"
    assert seerr_cfg["sonarr"][0]["activeAnimeDirectory"] == "/data/media/anime"

    # 2. Test Sonarr, Radarr, Prowlarr REST API auto-configuration via MockTransport
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append((request.method, str(request.url)))
        path = request.url.path
        if request.method == "GET":
            if path.endswith("/config/naming") or path.endswith("/config/mediamanagement"):
                return httpx.Response(200, json={"id": 1})
            if path.endswith("/indexer/schema"):
                return httpx.Response(
                    200,
                    json=[
                        {"definitionName": "yts", "privacy": "public", "name": "YTS"},
                        {"definitionName": "nyaasi", "privacy": "public", "name": "Nyaa.si"},
                        {"definitionName": "eztv", "privacy": "public", "name": "EZTV"},
                    ],
                )
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": 1})

    async def _run_api_tests():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as mock_client:
            s_logs = await configure_sonarr_via_api(mock_client, "http://sonarr:8989", "S_KEY_1")
            r_logs = await configure_radarr_via_api(mock_client, "http://radarr:7878", "R_KEY_2")
            p_logs = await configure_prowlarr_via_api(
                mock_client, "http://prowlarr:9696", "P_KEY_3", "S_KEY_1", "R_KEY_2"
            )
            return s_logs, r_logs, p_logs

    s_logs, r_logs, p_logs = asyncio.run(_run_api_tests())
    assert len(s_logs) == 5  # Naming, MediaManagement, 2 RootFolders (/tv, /anime), qBittorrent
    assert len(r_logs) == 4  # Naming, MediaManagement, 1 RootFolder (/movies), qBittorrent
    assert len(p_logs) == 4  # FlareSolverr Proxy, Sonarr FullSync, Radarr FullSync, Starter Indexers
    assert "{tvdb-{TvdbId}}" in TRASH_SONARR_NAMING["seriesFolderFormat"]
    assert "{tmdb-{TmdbId}}" in TRASH_RADARR_NAMING["movieFolderFormat"]


def test_smi2srt_korean_encoding_and_backup_engine(tmp_path: Path):
    from app.smi2srt_engine import scan_and_convert_smi_directories

    docker_root = tmp_path / "docker"
    data_root = tmp_path / "mediarr"
    movie_dir = data_root / "media/movies/Oldboy (2003)"
    movie_dir.mkdir(parents=True)
    docker_root.mkdir(parents=True)

    sample_smi = (
        "<SAMI>\n<HEAD><TITLE>Oldboy</TITLE></HEAD>\n<BODY>\n"
        "<SYNC Start=1500><P Class=KRCC>누구냐 넌?<br><font color=yellow>15년 동안 감금되었다.</font>\n"
        "<SYNC Start=4200><P Class=KRCC>&nbsp;\n"
        "<SYNC Start=5000><P Class=KRCC>웃어라, 온 세상이 너와 함께 웃을 것이다.\n"
        "<SYNC Start=8500><P Class=KRCC>&nbsp;\n"
        "</BODY>\n</SAMI>\n"
    )
    # Write in legacy Korean CP949 encoding to verify zero-broken-Korean conversion
    smi_file = movie_dir / "Oldboy.2003.1080p.smi"
    smi_file.write_bytes(sample_smi.encode("cp949"))

    res = scan_and_convert_smi_directories(docker_root=docker_root, data_root=data_root)
    assert res["status"] == "ok"
    assert res["converted_count"] == 1

    srt_file = movie_dir / "Oldboy.2003.1080p.ko.srt"
    assert srt_file.exists()
    srt_text = srt_file.read_text(encoding="utf-8")
    assert "00:00:01,500 --> 00:00:04,200" in srt_text
    assert "누구냐 넌?\n15년 동안 감금되었다." in srt_text
    assert "웃어라, 온 세상이 너와 함께 웃을 것이다." in srt_text

    # Original .smi should be moved to smi_backup so Plex never burns in .smi subtitles
    assert not smi_file.exists()
    backed_up_smi = docker_root / "smi2srt/smi_backup/media/movies/Oldboy (2003)/Oldboy.2003.1080p.smi"
    assert backed_up_smi.exists()

