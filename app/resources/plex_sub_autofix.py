#!/usr/bin/env python3
"""Bazarr Post-Processing Hook: Ensure UTF-8 encoding, clean .ko.srt copy, Plex metadata refresh, and auto-select Korean subtitle."""
import os
import shutil
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

PLEX_URL = os.environ.get("PLEX_URL", "http://172.17.0.1:32400")


def _load_plex_token() -> str:
    env_tok = os.environ.get("PLEX_TOKEN", "").strip()
    if env_tok:
        return env_tok
    tok_file = "/config/.plex_token"
    if os.path.exists(tok_file):
        try:
            return open(tok_file, "r", encoding="utf-8").read().strip()
        except Exception:
            pass
    return ""


PLEX_TOKEN = _load_plex_token()

# Self-heal yifysubtitles.py and Bazarr SQLite WAL concurrency settings if container was recreated
try:
    src_yify = "/config/yifysubtitles.py"
    dst_yify = "/app/bazarr/bin/custom_libs/subliminal_patch/providers/yifysubtitles.py"
    if os.path.exists(src_yify) and os.path.exists(dst_yify):
        if os.path.getsize(src_yify) != os.path.getsize(dst_yify):
            shutil.copy2(src_yify, dst_yify)
    db_py = "/app/bazarr/bin/bazarr/app/database.py"
    if os.path.exists(db_py):
        db_txt = open(db_py, "r", encoding="utf-8", errors="ignore").read()
        if "timeout': 5" in db_txt:
            db_txt = db_txt.replace("'timeout': 5", "'timeout': 60")
            open(db_py, "w", encoding="utf-8").write(db_txt)
except Exception:
    pass


def ensure_utf8_and_clean_ko(sub_path: str) -> None:
    if not sub_path or not os.path.exists(sub_path):
        return
    try:
        raw = open(sub_path, "rb").read()
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16"):
            try:
                txt = raw.decode(enc)
                break
            except Exception:
                continue
        else:
            txt = raw.decode("cp949", errors="replace")
        with open(sub_path, "w", encoding="utf-8") as f:
            f.write(txt)
        if sub_path.endswith(".ko.hi.srt"):
            clean_path = sub_path[:-len(".ko.hi.srt")] + ".ko.srt"
            shutil.copy2(sub_path, clean_path)
    except Exception as e:
        print(f"[plex_sub_autofix] encoding fix error: {e}")


def refresh_and_select_korean_in_plex(directory: str) -> None:
    try:
        sections_xml = urllib.request.urlopen(f"{PLEX_URL}/library/sections?X-Plex-Token={PLEX_TOKEN}", timeout=10).read()
        sroot = ET.fromstring(sections_xml)
        target_sections = []
        for sec in sroot.findall(".//Directory"):
            sec_key = sec.attrib.get("key")
            sec_type = sec.attrib.get("type")
            locs = [loc.attrib.get("path", "") for loc in sec.findall(".//Location")]
            if sec_type in ("movie", "show") and any("/data/media" in p for p in locs):
                target_sections.append((sec_key, sec_type))
                urllib.request.urlopen(f"{PLEX_URL}/library/sections/{sec_key}/refresh?X-Plex-Token={PLEX_TOKEN}", timeout=10)

        time.sleep(2)
        clean_dir = directory.rstrip("/") if directory else ""
        for sec_key, sec_type in target_sections:
            qtype = "1" if sec_type == "movie" else "4"
            all_xml = urllib.request.urlopen(f"{PLEX_URL}/library/sections/{sec_key}/all?type={qtype}&X-Plex-Token={PLEX_TOKEN}", timeout=10).read()
            aroot = ET.fromstring(all_xml)
            matched_rkeys = []
            for video in aroot.findall(".//Video"):
                rkey = video.attrib.get("ratingKey")
                m_xml = urllib.request.urlopen(f"{PLEX_URL}/library/metadata/{rkey}?X-Plex-Token={PLEX_TOKEN}", timeout=10).read()
                mroot = ET.fromstring(m_xml)
                part = mroot.find(".//Part")
                if part is None:
                    continue
                file_path = part.attrib.get("file", "")
                if not clean_dir or clean_dir in file_path:
                    req = urllib.request.Request(f"{PLEX_URL}/library/metadata/{rkey}/refresh?X-Plex-Token={PLEX_TOKEN}", method="PUT")
                    urllib.request.urlopen(req, timeout=10)
                    matched_rkeys.append(rkey)
            if matched_rkeys:
                time.sleep(2)
            for rkey in matched_rkeys:
                m_xml2 = urllib.request.urlopen(f"{PLEX_URL}/library/metadata/{rkey}?X-Plex-Token={PLEX_TOKEN}", timeout=10).read()
                mroot2 = ET.fromstring(m_xml2)
                part2 = mroot2.find(".//Part")
                part_id = part2.attrib.get("id") if part2 is not None else None
                ko_stream_id = None
                for st in mroot2.findall(".//Stream"):
                    if st.attrib.get("streamType") == "3" and st.attrib.get("languageCode") in ("kor", "ko"):
                        ko_stream_id = st.attrib.get("id")
                        if st.attrib.get("codec") == "srt":
                            break
                if part_id and ko_stream_id:
                    put_url = f"{PLEX_URL}/library/parts/{part_id}?subtitleStreamID={ko_stream_id}&allParts=1&X-Plex-Token={PLEX_TOKEN}"
                    urllib.request.urlopen(urllib.request.Request(put_url, method="PUT"), timeout=10)
                    print(f"[plex_sub_autofix] Selected Korean subtitle stream {ko_stream_id} for ratingKey={rkey}")
    except Exception as e:
        print(f"[plex_sub_autofix] Plex sync error: {e}")


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else ""
    subtitles = sys.argv[2] if len(sys.argv) > 2 else ""
    ensure_utf8_and_clean_ko(subtitles)
    refresh_and_select_korean_in_plex(directory)
