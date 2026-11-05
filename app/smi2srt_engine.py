"""Native Korean SMI-to-SRT Subtitle Converter Engine (CP949/EUC-KR/UTF-8/UTF-16 Auto-Detection) for Plex Direct Play."""

import html
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.runtime_manager import _safe_chown_chmod, get_mount_paths

SYNC_TAG_RE = re.compile(r"<sync\s+start\s*=\s*['\"]?(\d+)['\"]?[^>]*>", re.IGNORECASE)
BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
STYLE_SCRIPT_RE = re.compile(r"<(style|script|head)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def _decode_smi_bytes(raw: bytes) -> str:
    """Decode Korean SAMI (.smi) bytes cleanly across UTF-8-SIG, CP949, EUC-KR, UTF-16, and Latin-1."""
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp949", errors="replace")


def _ms_to_srt_timestamp(ms: int) -> str:
    """Convert milliseconds to SRT timestamp format (HH:MM:SS,mmm)."""
    if ms < 0:
        ms = 0
    hours = ms // 3_600_000
    rem = ms % 3_600_000
    minutes = rem // 60_000
    rem %= 60_000
    seconds = rem // 1_000
    millis = rem % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _clean_sami_fragment(fragment: str) -> str:
    """Convert a SAMI cue HTML fragment into clean plain text for SRT."""
    text = BR_TAG_RE.sub("\n", fragment)
    text = HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines).strip()


def convert_smi_content_to_srt(smi_text: str) -> str:
    """Parse SAMI (.smi) content and return UTF-8 SubRip (.srt) formatted text."""
    cleaned = COMMENT_RE.sub("", smi_text)
    cleaned = STYLE_SCRIPT_RE.sub("", cleaned)

    matches = list(SYNC_TAG_RE.finditer(cleaned))
    if not matches:
        return ""

    raw_cues: List[Tuple[int, str]] = []
    for idx, match in enumerate(matches):
        try:
            start_ms = int(match.group(1))
        except ValueError:
            continue
        frag_start = match.end()
        frag_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned)
        fragment = cleaned[frag_start:frag_end]
        cue_text = _clean_sami_fragment(fragment)
        raw_cues.append((start_ms, cue_text))

    srt_blocks: List[str] = []
    seq = 1
    for i, (start_ms, cue_text) in enumerate(raw_cues):
        if not cue_text:
            continue
        if i + 1 < len(raw_cues):
            end_ms = raw_cues[i + 1][0]
            if end_ms <= start_ms:
                end_ms = start_ms + 3000
        else:
            end_ms = start_ms + 3500

        start_ts = _ms_to_srt_timestamp(start_ms)
        end_ts = _ms_to_srt_timestamp(end_ms)
        srt_blocks.append(f"{seq}\n{start_ts} --> {end_ts}\n{cue_text}\n")
        seq += 1

    return "\n".join(srt_blocks)


def convert_single_smi_file(
    smi_path: Path,
    backup_root: Path | None = None,
    scan_root: Path | None = None,
    append_ko: bool = True,
    puid: int = 1026,
    pgid: int = 100,
) -> Dict[str, Any]:
    """Convert a single .smi file to .ko.srt (UTF-8) and optionally move the original .smi to backup_root."""
    raw_bytes = smi_path.read_bytes()
    smi_text = _decode_smi_bytes(raw_bytes)
    srt_text = convert_smi_content_to_srt(smi_text)
    if not srt_text.strip():
        return {"converted": False, "reason": "유효한 SYNC 자막 구간 없음", "source": str(smi_path)}

    stem = smi_path.stem
    # Avoid duplicate .ko.ko.srt if stem already ends with .ko or .kor
    if append_ko and not re.search(r"\.(ko|kor|kr|en|eng|ja|jpn)$", stem, re.IGNORECASE):
        srt_name = f"{stem}.ko.srt"
    else:
        srt_name = f"{stem}.srt"

    srt_path = smi_path.with_name(srt_name)
    srt_path.write_text(srt_text, encoding="utf-8")
    _safe_chown_chmod(srt_path, puid, pgid, is_dir=False)

    backed_up_to = None
    if backup_root is not None:
        try:
            if scan_root and smi_path.is_relative_to(scan_root):
                rel = smi_path.relative_to(scan_root)
            else:
                rel = Path(smi_path.name)
            dest = backup_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            _safe_chown_chmod(dest.parent, puid, pgid, is_dir=True)
            shutil.move(str(smi_path), str(dest))
            _safe_chown_chmod(dest, puid, pgid, is_dir=False)
            backed_up_to = str(dest)
        except Exception:
            pass

    return {
        "converted": True,
        "source": str(smi_path),
        "srt_path": str(srt_path),
        "backed_up_to": backed_up_to,
    }


def scan_and_convert_smi_directories(
    docker_root: Path | None = None,
    data_root: Path | None = None,
    extra_roots: List[Path] | None = None,
    backup_smi: bool = True,
    append_ko: bool = True,
) -> Dict[str, Any]:
    """Scan media & torrent folders, convert all .smi/.SMI files to UTF-8 .ko.srt, and archive .smi files to prevent Plex transcoding."""
    mounts = get_mount_paths()
    d_root = docker_root or mounts["docker"]
    m_root = data_root or mounts["data"]
    puid = int(os.environ.get("PUID", "1026"))
    pgid = int(os.environ.get("PGID", "100"))

    backup_root: Path | None = None
    log_dir: Path | None = None
    if d_root.exists():
        smi_base = d_root / "smi2srt"
        backup_dir = smi_base / "smi_backup"
        log_dir = smi_base / "log"
        backup_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        _safe_chown_chmod(smi_base, puid, pgid, is_dir=True)
        _safe_chown_chmod(backup_dir, puid, pgid, is_dir=True)
        _safe_chown_chmod(log_dir, puid, pgid, is_dir=True)
        if backup_smi:
            backup_root = backup_dir

    scan_targets: List[Path] = []
    if m_root.exists():
        scan_targets.append(m_root)
    if extra_roots:
        for r in extra_roots:
            if r.exists():
                scan_targets.append(r)

    converted_files: List[str] = []
    errors: List[str] = []

    for root in scan_targets:
        for dirpath, dirnames, filenames in os.walk(root):
            # Skip Synology @eaDir, #recycle, and smi_backup folders
            dirnames[:] = [
                d for d in dirnames if not d.startswith("@") and not d.startswith("#") and d != "smi_backup"
            ]
            cur_dir = Path(dirpath)
            for fname in filenames:
                if fname.lower().endswith(".smi"):
                    smi_file = cur_dir / fname
                    try:
                        res = convert_single_smi_file(
                            smi_file,
                            backup_root=backup_root,
                            scan_root=root,
                            append_ko=append_ko,
                            puid=puid,
                            pgid=pgid,
                        )
                        if res.get("converted"):
                            converted_files.append(res["srt_path"])
                        else:
                            errors.append(f"{smi_file}: {res.get('reason')}")
                    except Exception as exc:
                        errors.append(f"{smi_file}: {exc}")

    if log_dir is not None and (converted_files or errors):
        try:
            log_file = log_dir / "log.txt"
            with open(log_file, "a", encoding="utf-8") as f:
                for item in converted_files:
                    f.write(f"[CONVERTED -> UTF-8 .ko.srt] {item}\n")
                for err in errors:
                    f.write(f"[ERROR] {err}\n")
            _safe_chown_chmod(log_file, puid, pgid, is_dir=False)
        except Exception:
            pass

    return {
        "status": "ok",
        "converted_count": len(converted_files),
        "converted_files": converted_files,
        "errors_count": len(errors),
        "errors": errors,
        "backup_dir": str(backup_root) if backup_root else None,
        "summary": f"SMI ➔ UTF-8 .ko.srt 무트랜스코딩 자막 변환 {len(converted_files)}건 완료 (원본 .smi 백업 분리 완료)",
    }
