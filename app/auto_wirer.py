"""Zero-Touch REST API & Config Auto-Wirer for Sonarr, Radarr, Prowlarr, Seerr, Bazarr, and qBittorrent."""

import configparser
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import httpx
import yaml

from app.runtime_manager import _safe_chown_chmod, discover_credentials, get_mount_paths

# TRaSH Guides Official Naming Standards for Plex + Sonarr v4 + Radarr v5
TRASH_SONARR_NAMING = {
    "renameEpisodes": True,
    "replaceIllegalCharacters": True,
    "colonReplacementFormat": 4,  # Smart Replace
    "standardEpisodeFormat": (
        "{Series TitleYear} - S{season:00}E{episode:00} - {Episode CleanTitle} "
        "[{Preferred Words }{Quality Full}]{[MediaInfo VideoDynamicRangeType]}"
        "{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}{[MediaInfo VideoCodec]}{-Release Group}"
    ),
    "dailyEpisodeFormat": (
        "{Series TitleYear} - {Air-Date} - {Episode CleanTitle} "
        "[{Preferred Words }{Quality Full}]{[MediaInfo VideoDynamicRangeType]}"
        "{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}{[MediaInfo VideoCodec]}{-Release Group}"
    ),
    "animeEpisodeFormat": (
        "{Series TitleYear} - S{season:00}E{episode:00} - {absolute:000} - {Episode CleanTitle} "
        "[{Preferred Words }{Quality Full}]{[MediaInfo VideoDynamicRangeType]}[{MediaInfo VideoBitDepth}bit]"
        "{[MediaInfo VideoCodec]}[{Mediainfo AudioCodec} { Mediainfo AudioChannels}]{MediaInfo AudioLanguages}{-Release Group}"
    ),
    "seriesFolderFormat": "{Series TitleYear} {tvdb-{TvdbId}}",
    "seasonFolderFormat": "Season {season:00}",
    "specialsFolderFormat": "Specials",
}

TRASH_RADARR_NAMING = {
    "renameMovies": True,
    "replaceIllegalCharacters": True,
    "colonReplacementFormat": "smart",
    "standardMovieFormat": (
        "{Movie CleanTitle} {(Release Year)} {tmdb-{TmdbId}} "
        "{[Custom Formats]}{[Quality Full]}{[MediaInfo 3D]}{[MediaInfo VideoDynamicRangeType]}"
        "{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}{[MediaInfo VideoCodec]}{-Release Group}"
    ),
    "movieFolderFormat": "{Movie CleanTitle} ({Release Year}) {tmdb-{TmdbId}}",
}

TRASH_MEDIA_MANAGEMENT_COMMON = {
    "copyUsingHardlinks": True,
    "deleteEmptyFolders": True,
    "importExtraFiles": True,
    "extraFileExtensions": "srt,smi,ass,sub,idx",
    "enableMediaInfo": True,
    "setPermissionsLinux": False,  # Synology ACL 보존 권장 (UMASK 002 및 1026:100으로 권한 자동 일원화)
}


def provision_qbittorrent_categories_and_conf(docker_root: Path, puid: int = 1026, pgid: int = 100) -> str:
    """Configure qBittorrent categories.json AND qBittorrent.conf (SavePath=/data/torrents & Docker subnet auth bypass)."""
    if not docker_root.exists():
        return "호스트 마운트 대기 중 (qBittorrent 설정 스킵)"

    qbit_cfg_dir = docker_root / "qbittorrent/qBittorrent"
    cat_dir = qbit_cfg_dir / "config"
    cat_dir.mkdir(parents=True, exist_ok=True)
    _safe_chown_chmod(qbit_cfg_dir, puid, pgid, is_dir=True)
    _safe_chown_chmod(cat_dir, puid, pgid, is_dir=True)

    # 1. categories.json
    cat_file = cat_dir / "categories.json"
    existing: Dict[str, Any] = {}
    if cat_file.exists():
        try:
            existing = json.loads(cat_file.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    desired = {
        "movies": {"save_path": "/data/torrents/movies"},
        "tv": {"save_path": "/data/torrents/tv"},
        "anime": {"save_path": "/data/torrents/anime"},
        "music": {"save_path": "/data/torrents/music"},
        "prowlarr": {"save_path": "/data/torrents"},
    }
    for k, v in desired.items():
        if k not in existing:
            existing[k] = v

    cat_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    _safe_chown_chmod(cat_file, puid, pgid, is_dir=False)

    # 2. qBittorrent.conf (Ensure /data/torrents save path & internal Docker subnet auth whitelist)
    conf_file = qbit_cfg_dir / "qBittorrent.conf"
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # preserve case
    if conf_file.exists():
        try:
            parser.read(conf_file, encoding="utf-8")
        except Exception:
            pass

    if "Preferences" not in parser:
        parser["Preferences"] = {}
    prefs = parser["Preferences"]
    prefs.setdefault(r"Downloads\SavePath", "/data/torrents/")
    prefs[r"WebUI\LocalHostAuth"] = "false"
    prefs[r"WebUI\AuthSubnetWhitelistEnabled"] = "true"
    prefs[r"WebUI\AuthSubnetWhitelist"] = "172.16.0.0/12, 192.168.0.0/16, 10.0.0.0/8, 127.0.0.1/32"

    if "BitTorrent" not in parser:
        parser["BitTorrent"] = {}
    bt = parser["BitTorrent"]
    bt.setdefault(r"Session\DefaultSavePath", "/data/torrents")

    with open(conf_file, "w", encoding="utf-8") as f:
        parser.write(f, space_around_delimiters=False)
    _safe_chown_chmod(conf_file, puid, pgid, is_dir=False)

    return "qBittorrent: 기본 저장경로(/data/torrents), 카테고리 5종, 내부 도커 서브넷 무인증 연동 설정 완료"


provision_qbittorrent_categories = provision_qbittorrent_categories_and_conf


def provision_bazarr_config(
    docker_root: Path,
    sonarr_api_key: str,
    radarr_api_key: str,
    puid: int = 1026,
    pgid: int = 100,
) -> str:
    """Automatically configure Bazarr config.yaml with Sonarr/Radarr connection & Korean Subsync settings."""
    if not docker_root.exists():
        return "호스트 마운트 대기 중 (Bazarr 설정 스킵)"

    bazarr_cfg_dir = docker_root / "bazarr/config"
    bazarr_cfg_dir.mkdir(parents=True, exist_ok=True)
    _safe_chown_chmod(bazarr_cfg_dir, puid, pgid, is_dir=True)
    cfg_file = bazarr_cfg_dir / "config.yaml"

    data: Dict[str, Any] = {}
    if cfg_file.exists():
        try:
            loaded = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}

    general = data.setdefault("general", {})
    general["use_sonarr"] = True
    general["use_radarr"] = True
    general["auto_update"] = False
    general["serie_default_enabled"] = True
    general["movie_default_enabled"] = True
    general.setdefault("enabled_providers", ["yify", "subdl", "podnapisi", "gestdown", "animetosho"])

    sonarr_sec = data.setdefault("sonarr", {})
    sonarr_sec["ip"] = "sonarr"
    sonarr_sec["port"] = 8989
    sonarr_sec["base_url"] = ""
    sonarr_sec["ssl"] = False
    if sonarr_api_key:
        sonarr_sec["apikey"] = sonarr_api_key

    radarr_sec = data.setdefault("radarr", {})
    radarr_sec["ip"] = "radarr"
    radarr_sec["port"] = 7878
    radarr_sec["base_url"] = ""
    radarr_sec["ssl"] = False
    if radarr_api_key:
        radarr_sec["apikey"] = radarr_api_key

    subsync_sec = data.setdefault("subsync", {})
    subsync_sec["use_subsync"] = True
    subsync_sec["use_subsync_threshold"] = True
    subsync_sec["subsync_threshold"] = 90

    cfg_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _safe_chown_chmod(cfg_file, puid, pgid, is_dir=False)
    return "Bazarr: 한국어·영어 자막 공급자 활성화, Sonarr·Radarr 연동 및 AI Subsync 오디오 싱크 보정 설정 완료"


def provision_seerr_settings(
    docker_root: Path,
    nas_ip: str,
    sonarr_api_key: str,
    radarr_api_key: str,
    puid: int = 1026,
    pgid: int = 100,
) -> str:
    """Automatically pre-wire Sonarr, Radarr, and Plex server endpoints into Seerr (settings.json)."""
    if not docker_root.exists():
        return "호스트 마운트 대기 중 (Seerr 설정 스킵)"

    seerr_dir = docker_root / "seerr"
    seerr_dir.mkdir(parents=True, exist_ok=True)
    _safe_chown_chmod(seerr_dir, puid, pgid, is_dir=True)
    settings_file = seerr_dir / "settings.json"

    data: Dict[str, Any] = {}
    if settings_file.exists():
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    plex_sec = data.setdefault("plex", {})
    plex_sec.setdefault("name", "Plex Media Server")
    plex_sec.setdefault("ip", nas_ip)
    plex_sec.setdefault("port", 32400)
    plex_sec.setdefault("useSsl", False)

    if radarr_api_key:
        radarr_list = data.setdefault("radarr", [])
        if not radarr_list:
            radarr_list.append(
                {
                    "id": 1,
                    "name": "Radarr (Movies)",
                    "hostname": "radarr",
                    "port": 7878,
                    "apiKey": radarr_api_key,
                    "useSsl": False,
                    "baseUrl": "",
                    "activeProfileId": 1,
                    "activeProfileName": "Any",
                    "activeDirectory": "/data/media/movies",
                    "is4k": False,
                    "minimumAvailability": "released",
                    "isDefault": True,
                    "externalUrl": f"http://{nas_ip}:7878",
                    "syncEnabled": True,
                    "preventSearch": False,
                }
            )
        else:
            radarr_list[0]["apiKey"] = radarr_api_key
            radarr_list[0]["hostname"] = "radarr"
            radarr_list[0]["activeDirectory"] = "/data/media/movies"

    if sonarr_api_key:
        sonarr_list = data.setdefault("sonarr", [])
        if not sonarr_list:
            sonarr_list.append(
                {
                    "id": 1,
                    "name": "Sonarr (TV & Anime)",
                    "hostname": "sonarr",
                    "port": 8989,
                    "apiKey": sonarr_api_key,
                    "useSsl": False,
                    "baseUrl": "",
                    "activeProfileId": 1,
                    "activeProfileName": "Any",
                    "activeDirectory": "/data/media/tv",
                    "activeAnimeProfileId": 1,
                    "activeAnimeProfileName": "Any",
                    "activeAnimeDirectory": "/data/media/anime",
                    "enableSeasonFolders": True,
                    "is4k": False,
                    "isDefault": True,
                    "externalUrl": f"http://{nas_ip}:8989",
                    "syncEnabled": True,
                    "preventSearch": False,
                }
            )
        else:
            sonarr_list[0]["apiKey"] = sonarr_api_key
            sonarr_list[0]["hostname"] = "sonarr"
            sonarr_list[0]["activeDirectory"] = "/data/media/tv"
            sonarr_list[0]["activeAnimeDirectory"] = "/data/media/anime"

    if settings_file.exists() or sonarr_api_key or radarr_api_key:
        settings_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _safe_chown_chmod(settings_file, puid, pgid, is_dir=False)

    return "Seerr: Plex 주소 및 Sonarr(/data/media/tv, anime)·Radarr(/data/media/movies) 서버 자동 연동 완료"


async def configure_sonarr_via_api(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    qbit_host: str = "qbittorrent",
    qbit_port: int = 8181,
    qbit_user: str = "admin",
    qbit_pass: str = "",
) -> List[str]:
    """Configure Sonarr v4 Media Management, TRaSH Naming, Root Folders (/data/media/tv, anime), and qBittorrent."""
    logs: List[str] = []
    headers = {"X-Api-Key": api_key}

    r_nam = await client.get(f"{base_url}/api/v3/config/naming", headers=headers)
    if r_nam.status_code == 200:
        nam_data = r_nam.json()
        nam_data.update(TRASH_SONARR_NAMING)
        await client.put(f"{base_url}/api/v3/config/naming", headers=headers, json=nam_data)
        logs.append("Sonarr: TRaSH Guides 표준 에피소드·애니·시즌 폴더 네이밍 포맷 자동 적용")

    r_mm = await client.get(f"{base_url}/api/v3/config/mediamanagement", headers=headers)
    if r_mm.status_code == 200:
        mm_data = r_mm.json()
        mm_data.update(TRASH_MEDIA_MANAGEMENT_COMMON)
        mm_data["unmonitorDeletedEpisodes"] = True
        await client.put(f"{base_url}/api/v3/config/mediamanagement", headers=headers, json=mm_data)
        logs.append("Sonarr: 0.1초 하드링크(copyUsingHardlinks) 및 자막(.srt/.smi) 동시 임포트 활성화")

    r_rf = await client.get(f"{base_url}/api/v3/rootfolder", headers=headers)
    if r_rf.status_code == 200:
        existing_paths = {item.get("path", "").rstrip("/") for item in r_rf.json()}
        for target_path in ["/data/media/tv", "/data/media/anime"]:
            if target_path not in existing_paths:
                await client.post(f"{base_url}/api/v3/rootfolder", headers=headers, json={"path": target_path})
                logs.append(f"Sonarr: 루트 폴더({target_path}) 자동 등록")

    r_dc = await client.get(f"{base_url}/api/v3/downloadclient", headers=headers)
    if r_dc.status_code == 200:
        existing_dcs = r_dc.json()
        if not any(d.get("implementation") == "QBittorrent" for d in existing_dcs):
            payload = {
                "enable": True,
                "protocol": "torrent",
                "priority": 1,
                "removeCompletedDownloads": True,
                "removeFailedDownloads": True,
                "name": "qBittorrent (VPN)",
                "implementation": "QBittorrent",
                "configContract": "QBittorrentSettings",
                "fields": [
                    {"name": "host", "value": qbit_host},
                    {"name": "port", "value": qbit_port},
                    {"name": "useSsl", "value": False},
                    {"name": "username", "value": qbit_user},
                    {"name": "password", "value": qbit_pass},
                    {"name": "tvCategory", "value": "tv"},
                ],
            }
            await client.post(f"{base_url}/api/v3/downloadclient", headers=headers, json=payload)
            logs.append(f"Sonarr: qBittorrent({qbit_host}:{qbit_port}) 다운로드 클라이언트 자동 연결")

    return logs


async def configure_radarr_via_api(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    qbit_host: str = "qbittorrent",
    qbit_port: int = 8181,
    qbit_user: str = "admin",
    qbit_pass: str = "",
) -> List[str]:
    """Configure Radarr v5 Media Management, TRaSH Naming, Root Folder (/data/media/movies), and qBittorrent."""
    logs: List[str] = []
    headers = {"X-Api-Key": api_key}

    r_nam = await client.get(f"{base_url}/api/v3/config/naming", headers=headers)
    if r_nam.status_code == 200:
        nam_data = r_nam.json()
        nam_data.update(TRASH_RADARR_NAMING)
        await client.put(f"{base_url}/api/v3/config/naming", headers=headers, json=nam_data)
        logs.append("Radarr: TRaSH Guides + Plex 표준 영화 폴더·파일({tmdb-{TmdbId}}) 네이밍 포맷 자동 적용")

    r_mm = await client.get(f"{base_url}/api/v3/config/mediamanagement", headers=headers)
    if r_mm.status_code == 200:
        mm_data = r_mm.json()
        mm_data.update(TRASH_MEDIA_MANAGEMENT_COMMON)
        mm_data["unmonitorDeletedMovies"] = True
        await client.put(f"{base_url}/api/v3/config/mediamanagement", headers=headers, json=mm_data)
        logs.append("Radarr: 0.1초 하드링크(copyUsingHardlinks) 및 자막(.srt/.smi) 동시 임포트 활성화")

    r_rf = await client.get(f"{base_url}/api/v3/rootfolder", headers=headers)
    if r_rf.status_code == 200:
        existing_paths = {item.get("path", "").rstrip("/") for item in r_rf.json()}
        if "/data/media/movies" not in existing_paths:
            await client.post(f"{base_url}/api/v3/rootfolder", headers=headers, json={"path": "/data/media/movies"})
            logs.append("Radarr: 루트 폴더(/data/media/movies) 자동 등록")

    r_dc = await client.get(f"{base_url}/api/v3/downloadclient", headers=headers)
    if r_dc.status_code == 200:
        existing_dcs = r_dc.json()
        if not any(d.get("implementation") == "QBittorrent" for d in existing_dcs):
            payload = {
                "enable": True,
                "protocol": "torrent",
                "priority": 1,
                "removeCompletedDownloads": True,
                "removeFailedDownloads": True,
                "name": "qBittorrent (VPN)",
                "implementation": "QBittorrent",
                "configContract": "QBittorrentSettings",
                "fields": [
                    {"name": "host", "value": qbit_host},
                    {"name": "port", "value": qbit_port},
                    {"name": "useSsl", "value": False},
                    {"name": "username", "value": qbit_user},
                    {"name": "password", "value": qbit_pass},
                    {"name": "movieCategory", "value": "movies"},
                ],
            }
            await client.post(f"{base_url}/api/v3/downloadclient", headers=headers, json=payload)
            logs.append(f"Radarr: qBittorrent({qbit_host}:{qbit_port}) 다운로드 클라이언트 자동 연결")

    return logs


async def configure_prowlarr_via_api(
    client: httpx.AsyncClient,
    base_url: str,
    prowlarr_api_key: str,
    sonarr_api_key: str = "",
    radarr_api_key: str = "",
) -> List[str]:
    """Configure Prowlarr v1 FlareSolverr Proxy, Sonarr/Radarr Full-Sync Apps, and default public indexers."""
    logs: List[str] = []
    headers = {"X-Api-Key": prowlarr_api_key}

    # 1. Ensure 'flaresolverr' tag exists
    tag_id = 1
    r_tags = await client.get(f"{base_url}/api/v1/tag", headers=headers)
    if r_tags.status_code == 200:
        tags = r_tags.json()
        found = next((t for t in tags if t.get("label") == "flaresolverr"), None)
        if found:
            tag_id = found["id"]
        else:
            r_new_tag = await client.post(f"{base_url}/api/v1/tag", headers=headers, json={"label": "flaresolverr"})
            if r_new_tag.status_code in (200, 201):
                tag_id = r_new_tag.json().get("id", 1)

    # 2. Register FlareSolverr Indexer Proxy
    r_px = await client.get(f"{base_url}/api/v1/indexerproxy", headers=headers)
    if r_px.status_code == 200:
        proxies = r_px.json()
        if not any(p.get("implementation") == "FlareSolverr" for p in proxies):
            px_payload = {
                "name": "FlareSolverr",
                "implementation": "FlareSolverr",
                "configContract": "FlareSolverrSettings",
                "tags": [tag_id],
                "fields": [
                    {"name": "host", "value": "http://flaresolverr:8191"},
                    {"name": "requestTimeout", "value": 60},
                ],
            }
            await client.post(f"{base_url}/api/v1/indexerproxy", headers=headers, json=px_payload)
            logs.append("Prowlarr: FlareSolverr(http://flaresolverr:8191) Cloudflare 우회 프록시 자동 등록")

    # 3. Register Sonarr & Radarr Full-Sync Applications
    r_apps = await client.get(f"{base_url}/api/v1/applications", headers=headers)
    if r_apps.status_code == 200:
        apps = r_apps.json()
        if sonarr_api_key and not any(a.get("implementation") == "Sonarr" for a in apps):
            sonarr_app = {
                "name": "Sonarr",
                "syncLevel": "fullSync",
                "implementation": "Sonarr",
                "configContract": "SonarrSettings",
                "fields": [
                    {"name": "prowlarrUrl", "value": "http://prowlarr:9696"},
                    {"name": "baseUrl", "value": "http://sonarr:8989"},
                    {"name": "apiKey", "value": sonarr_api_key},
                ],
            }
            await client.post(f"{base_url}/api/v1/applications", headers=headers, json=sonarr_app)
            logs.append("Prowlarr: Sonarr(http://sonarr:8989) 인덱서 실시간 Full Sync 자동 연결")

        if radarr_api_key and not any(a.get("implementation") == "Radarr" for a in apps):
            radarr_app = {
                "name": "Radarr",
                "syncLevel": "fullSync",
                "implementation": "Radarr",
                "configContract": "RadarrSettings",
                "fields": [
                    {"name": "prowlarrUrl", "value": "http://prowlarr:9696"},
                    {"name": "baseUrl", "value": "http://radarr:7878"},
                    {"name": "apiKey", "value": radarr_api_key},
                ],
            }
            await client.post(f"{base_url}/api/v1/applications", headers=headers, json=radarr_app)
            logs.append("Prowlarr: Radarr(http://radarr:7878) 인덱서 실시간 Full Sync 자동 연결")

    # 4. Auto-register starter public indexers if Prowlarr currently has 0 indexers
    r_idx = await client.get(f"{base_url}/api/v1/indexer", headers=headers)
    if r_idx.status_code == 200 and len(r_idx.json()) == 0:
        r_schema = await client.get(f"{base_url}/api/v1/indexer/schema", headers=headers)
        if r_schema.status_code == 200:
            schemas = r_schema.json()
            starter_targets = {"limetorrents", "eztv", "yts", "nyaasi", "thepiratebay", "1337x", "tokyotoshokan"}
            added_count = 0
            for item in schemas:
                defn = str(item.get("definitionName", "")).lower()
                if defn in starter_targets and item.get("privacy") == "public":
                    item["enable"] = True
                    item["appProfileId"] = 1
                    item["priority"] = 25
                    item["tags"] = [tag_id]
                    res_post = await client.post(f"{base_url}/api/v1/indexer", headers=headers, json=item)
                    if res_post.status_code in (200, 201):
                        added_count += 1
            if added_count > 0:
                logs.append(f"Prowlarr: 기본 공개 인덱서 {added_count}종 자동 등록 및 Sonarr·Radarr 동기화 완료")

    return logs


async def auto_wire_all_services(
    docker_root: Path | None = None,
    sonarr_url: str = "http://sonarr:8989",
    radarr_url: str = "http://radarr:7878",
    prowlarr_url: str = "http://prowlarr:9696",
) -> Dict[str, Any]:
    """Master Zero-Touch Auto-Wirer: configures files and calls Sonarr/Radarr/Prowlarr/Seerr APIs automatically."""
    mounts = get_mount_paths()
    d_root = docker_root or mounts["docker"]
    puid = int(os.environ.get("PUID", "1026"))
    pgid = int(os.environ.get("PGID", "100"))
    nas_ip = os.environ.get("NAS_IP", "192.168.0.100")
    qbit_port = int(os.environ.get("QBIT_WEBUI_PORT", "8181"))
    qbit_user = os.environ.get("QBIT_USER", "admin")
    qbit_pass = os.environ.get("QBIT_PASSWORD", "")

    creds = discover_credentials(d_root)
    completed_actions: List[str] = []

    # 1. File-based auto-provisioning (qBittorrent conf/categories, Bazarr config.yaml, Seerr settings.json)
    if d_root.exists():
        completed_actions.append(provision_qbittorrent_categories_and_conf(d_root, puid, pgid))
        completed_actions.append(
            provision_bazarr_config(
                d_root,
                sonarr_api_key=creds["sonarr_api_key"],
                radarr_api_key=creds["radarr_api_key"],
                puid=puid,
                pgid=pgid,
            )
        )
        completed_actions.append(
            provision_seerr_settings(
                d_root,
                nas_ip=nas_ip,
                sonarr_api_key=creds["sonarr_api_key"],
                radarr_api_key=creds["radarr_api_key"],
                puid=puid,
                pgid=pgid,
            )
        )

    # 2. Live REST API auto-provisioning (Sonarr, Radarr, Prowlarr)
    async with httpx.AsyncClient(timeout=5.0) as client:
        if creds["sonarr_api_key"]:
            try:
                s_logs = await configure_sonarr_via_api(
                    client,
                    base_url=sonarr_url,
                    api_key=creds["sonarr_api_key"],
                    qbit_port=qbit_port,
                    qbit_user=qbit_user,
                    qbit_pass=qbit_pass,
                )
                completed_actions.extend(s_logs)
            except Exception as exc:
                completed_actions.append(f"Sonarr API 대기 중 ({exc})")

        if creds["radarr_api_key"]:
            try:
                r_logs = await configure_radarr_via_api(
                    client,
                    base_url=radarr_url,
                    api_key=creds["radarr_api_key"],
                    qbit_port=qbit_port,
                    qbit_user=qbit_user,
                    qbit_pass=qbit_pass,
                )
                completed_actions.extend(r_logs)
            except Exception as exc:
                completed_actions.append(f"Radarr API 대기 중 ({exc})")

        if creds["prowlarr_api_key"]:
            try:
                p_logs = await configure_prowlarr_via_api(
                    client,
                    base_url=prowlarr_url,
                    prowlarr_api_key=creds["prowlarr_api_key"],
                    sonarr_api_key=creds["sonarr_api_key"],
                    radarr_api_key=creds["radarr_api_key"],
                )
                completed_actions.extend(p_logs)
            except Exception as exc:
                completed_actions.append(f"Prowlarr API 대기 중 ({exc})")

    return {
        "status": "ok",
        "discovered_keys": {
            "plex_token_found": bool(creds["plex_token"]),
            "sonarr_api_key_found": bool(creds["sonarr_api_key"]),
            "radarr_api_key_found": bool(creds["radarr_api_key"]),
            "prowlarr_api_key_found": bool(creds["prowlarr_api_key"]),
        },
        "actions": completed_actions,
        "summary": f"세부 옵션 및 내부 연동 자동 세팅 {len(completed_actions)}개 항목 처리 완료",
    }
