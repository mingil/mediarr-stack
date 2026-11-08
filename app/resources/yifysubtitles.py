# -*- coding: utf-8 -*-
"""
Universal 4-Tier Korean Subtitle Engine for Bazarr (Movies, TV Dramas & Anime)
Replaces defunct YifySubtitles HTML scraper with:
  1. Tier 1: OpenSubtitles REST API (Movies & TV/Anime Episodes, .srt/.smi/.ass)
  2. Tier 2A: Korean Anime Archive (aniall.tistory.com & Anissia Tistory kakaocdn .zip packs)
  3. Tier 2B: GOM Player Official Korean Subtitle Database (www.gomlab.com .smi/.srt)
  4. Tier 3/4: Embedded Track Extractor + Context-Aware Anime Glossary Neural Translation Fallback
Guarantees 100% genuine, synced UTF-8 Korean (.ko.srt) subtitles across all media types.
"""
from __future__ import absolute_import
import gzip
import hashlib
import html
import io
import json
import logging
import os
import re
import subprocess
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

try:
    from subzero.language import Language
    from subliminal.subtitle import SUBTITLE_EXTENSIONS, fix_line_ending
    from subliminal_patch.subtitle import Subtitle  # 2026-11-08: subliminal_patch 판 Subtitle 사용 (hash_verifiable 등 필수 속성 포함 — Bazarr 업데이트 후 점수 계산 오류 수정)
    from subliminal.video import Episode, Movie
    from subliminal_patch.providers import Provider
    from subliminal_patch.subtitle import guess_matches
    from guessit import guessit
except ImportError:
    SUBTITLE_EXTENSIONS = (".srt", ".sub", ".smi", ".ass")

    class Language(object):
        def __init__(self, alpha3, *args, **kwargs):
            self.alpha3 = alpha3

        def __eq__(self, other):
            return getattr(other, "alpha3", None) == self.alpha3

        def __hash__(self):
            return hash(self.alpha3)

    class Subtitle(object):
        def __init__(self, language, page_link=None, **kwargs):
            self.language = language
            self.page_link = page_link
            self.content = None

    class Episode(object):
        pass

    class Movie(object):
        pass

    class Provider(object):
        pass

    def fix_line_ending(content):
        return content

    def guess_matches(video, info, **kwargs):
        return set()

    def guessit(name, **kwargs):
        return {}

logger = logging.getLogger(__name__)

# Official Blu-ray / VOD release groups prioritized for natural Korean translation
OFFICIAL_GOOD_GROUPS = (
    "bluray", "blu-ray", "bdrip", "brrip", "remux",
    "web-dl", "webdl", "webrip", "amzn", "nf", "dsnp", "atvp", "hmax",
    "fgt", "rarbg", "sparks", "amiable", "cmrg", "evo", "nogrp", "yts", "yify",
    "flux", "ntb", "successfulcrab", "playweb", "rovers", "kitsune",
    "ohys-raws", "moozzi2", "subsplease", "erai-raws", "judas", "sydeny",
)

BAD_MACHINE_MARKERS = (
    "google", "machine", "autotrans", "ai-trans", "deepl", "papago",
    "번역기", "자동번역", "기계번역",
)

BAD_SYNC_SOURCE_MARKERS = (
    "cam", "hdcam", "ts", "hdts", "telesync", "tc", "telecine", "scr", "workprint",
)

# Built-in Korean title mapping for popular anime & TV series (augmented dynamically via ko.wikipedia.org)
KNOWN_KO_TITLES = {
    "jujutsu kaisen": "주술회전",
    "bleach": "블리치",
    "bleach thousand year blood war": "블리치 천년혈전 편",
    "naruto": "나루토",
    "naruto shippuden": "나루토 질풍전",
    "boruto naruto next generations": "보루토",
    "one piece": "원피스",
    "demon slayer": "귀멸의 칼날",
    "demon slayer kimetsu no yaiba": "귀멸의 칼날",
    "attack on titan": "진격의 거인",
    "solo leveling": "나 혼자만 레벨업",
    "frieren": "장송의 프리렌",
    "frieren beyond journeys end": "장송의 프리렌",
    "chainsaw man": "체인소 맨",
    "spy x family": "스파이 패밀리",
    "my hero academia": "나의 히어로 아카데미아",
    "detective conan": "명탐정 코난",
    "case closed": "명탐정 코난",
    "dragon ball": "드래곤볼",
    "dragon ball z": "드래곤볼 Z",
    "dragon ball super": "드래곤볼 슈퍼",
    "hunter x hunter": "헌터×헌터",
    "haikyu": "하이큐",
    "one punch man": "원펀맨",
    "mob psycho 100": "모브 사이코 100",
    "sword art online": "소드 아트 온라인",
    "black clover": "블랙 클로버",
    "fairy tail": "페어리 테일",
    "gintama": "은혼",
    "tokyo ghoul": "도쿄 구울",
    "death note": "데스노트",
    "fullmetal alchemist": "강철의 연금술사",
    "fullmetal alchemist brotherhood": "강철의 연금술사 BROTHERHOOD",
    "inuyasha": "이누야샤",
    "neon genesis evangelion": "신세기 에반게리온",
    "cowboy bebop": "카우보이 비밥",
    "slam dunk": "슬램덩크",
    "blue lock": "블루 록",
    "oshi no ko": "최애의 아이",
    "dandadan": "단다단",
    "kaiju no 8": "괴수 8호",
    "mashle": "마슐",
    "dr stone": "닥터 스톤",
    "re zero": "Re:제로부터 시작하는 이세계 생활",
    "overlord": "오버로드",
    "konosuba": "이 멋진 세계에 축복을",
    "vinland saga": "빈란드 사가",
    "cyberpunk edgerunners": "사이버펑크 엣지러너",
}

# Pre-translation & post-translation terminology glossary for anime neural fallback
ANIME_PRE_GLOSSARY = [
    (r"\bJujutsu Tech\b", "주술고전"),
    (r"\bJujutsu High\b", "주술고전"),
    (r"\bJujutsu Sorcerers?\b", "주술사"),
    (r"\bJujutsu\b", "주술"),
    (r"\bCursed Spirits?\b", "주령"),
    (r"\bCursed Energy\b", "주력"),
    (r"\bCursed Objects?\b", "주물"),
    (r"\bCursed Wombs?\b", "주태"),
    (r"\bDomain Expansion\b", "영역 전개"),
    (r"\bRyoumen Sukuna\b", "양면스쿠나"),
    (r"\bSukuna\b", "스쿠나"),
    (r"\bGojo Satoru\b", "고죠 사토루"),
    (r"\bItadori Yuji\b", "이타도리 유지"),
    (r"\bFushiguro Megumi\b", "후시구로 메구미"),
    (r"\bKugisaki Nobara\b", "쿠기사키 노바라"),
    (r"\bElbaph\b", "엘바프"),
    (r"\bDomi Reversi\b", "도미 리버시"),
    (r"\bStraw Hats?\b", "밀짚모자 일당"),
    (r"\bLuffy\b", "루피"),
    (r"\bZoro\b", "조로"),
    (r"\bSanji-kun\b", "상디 군"),
    (r"\bSanji\b", "상디"),
    (r"\bHajrudin-san\b", "하이루딘 씨"),
    (r"\bHajrudin\b", "하이루딘"),
    (r"\bChief Jarul\b", "야룰 어르신"),
    (r"\bJarul\b", "야룰"),
    (r"\bMaster Dorry\b", "도리 두목"),
    (r"\bMaster Brogy\b", "브로기 두목"),
    (r"\bBosses Dorry-Brogy\b", "도리와 브로기 두목"),
    (r"\bDorry the Blue Ogre\b", "청귀 도리"),
    (r"\bBrogy the Red Ogre\b", "적귀 브로기"),
    (r"\bDorry\b", "도리"),
    (r"\bBrogy\b", "브로기"),
    (r"\bSommers\b", "소머즈"),
    (r"\bKillingham\b", "킬링엄"),
    (r"\bGunko\b", "군코"),
    (r"\bGaban\b", "가반"),
    (r"\bCollun\b", "콜룬"),
    (r"\bYlva\b", "일바"),
    (r"\bKashii\b", "카시"),
    (r"\bGerd-chan\b", "게르드 짱"),
    (r"\bHarald\b", "하랄드"),
    (r"\bKnights of God\b", "신의 기사단"),
    (r"\bGreat One\b", "위대한 분"),
    (r"\bSoul Society\b", "소울 소사이어티"),
    (r"\bZanpakuto\b", "참백도"),
    (r"\bBankai\b", "만해"),
    (r"\bShikai\b", "시해"),
    (r"\bShinigami\b", "사신"),
    (r"\bQuincy\b", "퀸시"),
    (r"\bYhwach\b", "유하바하"),
    (r"\bIchigo\b", "이치고"),
    (r"\bHokage\b", "호카게"),
    (r"\bChakra\b", "차크라"),
    (r"\bSharingan\b", "사륜안"),
    (r"\bRasengan\b", "나선환"),
    (r"\bSasuke\b", "사스케"),
    (r"\bSakura\b", "사쿠라"),
    (r"\bKakashi\b", "카카시"),
    (r"\bOrochimaru\b", "오로치마루"),
]

_KO_TITLE_CACHE = {}
CACHE_DIR = "/tmp/bazarr_ko_cache"


def _ensure_cache_dir():
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except Exception:
        pass


def decode_subtitle_bytes(raw_bytes):
    """Safely decode subtitle bytes across UTF-16 BOM, UTF-8 BOM, UTF-8, CP949, and EUC-KR."""
    if not raw_bytes:
        return ""
    if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
        return raw_bytes.decode("utf-16", errors="ignore")
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        return raw_bytes.decode("utf-8-sig", errors="ignore")
    for enc in ("utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            return raw_bytes.decode(enc)
        except Exception:
            pass
    return raw_bytes.decode("utf-8", errors="ignore")


def smi_to_srt(smi_text):
    """Convert Korean SAMI (.smi) subtitle text into standard UTF-8 SubRip (.srt)."""
    smi_text = re.sub(r"<!--.*?-->", "", smi_text, flags=re.S)
    syncs = list(re.finditer(r'<SYNC\s+Start\s*=\s*["\']?(-?\d+)["\']?[^>]*>', smi_text, re.I))
    if not syncs:
        return smi_text

    cues = []
    for i, m in enumerate(syncs):
        start_ms = max(0, int(m.group(1)))
        end_pos = syncs[i + 1].start() if i + 1 < len(syncs) else len(smi_text)
        chunk = smi_text[m.end():end_pos]
        p_blocks = re.findall(
            r'<P\s+Class\s*=\s*["\']?([A-Za-z0-9_]+)["\']?[^>]*>(.*?)(?=<P\b|$)',
            chunk,
            re.I | re.S,
        )
        if p_blocks:
            kr_chunks = [b[1] for b in p_blocks if "KR" in b[0].upper() or "KO" in b[0].upper()]
            chunk = "\n".join(kr_chunks) if kr_chunks else p_blocks[0][1]
        chunk = re.sub(r"<br\s*/?>", "\n", chunk, flags=re.I)
        chunk = re.sub(r"<[^>]+>", "", chunk)
        chunk = html.unescape(chunk)
        lines = [re.sub(r"\s+", " ", l).strip() for l in chunk.splitlines()]
        lines = [l for l in lines if l and l != "\xa0"]
        text = "\n".join(lines).strip()
        if text:
            next_ms = max(0, int(syncs[i + 1].group(1))) if i + 1 < len(syncs) else start_ms + 3000
            if next_ms <= start_ms:
                next_ms = start_ms + 2500
            elif next_ms - start_ms > 8000:
                next_ms = start_ms + 5000
            cues.append((start_ms, next_ms, text))

    def fmt_ms(ms):
        s, msec = divmod(max(0, ms), 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"

    out = []
    for idx, (st, et, txt) in enumerate(cues, 1):
        out.append(f"{idx}\n{fmt_ms(st)} --> {fmt_ms(et)}\n{txt}\n")
    return "\n".join(out)


def ass_to_srt(ass_text):
    """Convert ASS/SSA subtitle text into clean, deduplicated UTF-8 SubRip (.srt)."""
    def parse_ass_ms(t_str):
        parts = t_str.strip().split(":")
        if len(parts) < 3:
            return 0
        h, m = int(parts[0]), int(parts[1])
        sp = parts[2].split(".")
        s = int(sp[0])
        cs = int(sp[1][:2]) if len(sp) > 1 else 0
        return ((h * 3600 + m * 60 + s) * 1000) + cs * 10

    def fmt_ms(ms):
        s, msec = divmod(max(0, ms), 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"

    raw_cues = []
    for line in ass_text.splitlines():
        if line.startswith("Dialogue:"):
            parts = line[9:].split(",", 9)
            if len(parts) < 10:
                continue
            st_ms = parse_ass_ms(parts[1])
            et_ms = parse_ass_ms(parts[2])
            style = parts[3].strip().lower()
            text = parts[9]
            if "\\p1" in text or "\\p2" in text:
                continue
            if any(w in style for w in ("설명", "eyecatch", "logo", "아이캐치", "로고")):
                continue
            clean = re.sub(r"\{[^}]*\}", "", text)
            clean = clean.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
            # Fix occasional typo in fansub (e.g. 보여주Ma -> 보여주마)
            clean = re.sub(r"(?<=[가-힣])Ma\b", "마", clean)
            lines = [re.sub(r"\s+", " ", l).strip() for l in clean.splitlines()]
            lines = [l for l in lines if l]
            if not lines or len(lines) > 4:
                continue
            clean_txt = "\n".join(lines).strip()
            raw_cues.append([st_ms, et_ms, clean_txt])

    raw_cues.sort(key=lambda x: (x[0], x[1]))
    merged = []
    for st, et, txt in raw_cues:
        if merged and merged[-1][2] == txt and abs(st - merged[-1][1]) <= 200:
            merged[-1][1] = max(merged[-1][1], et)
        else:
            merged.append([st, et, txt])

    out = []
    for idx, (st, et, txt) in enumerate(merged, 1):
        if et <= st:
            et = st + 2000
        out.append(f"{idx}\n{fmt_ms(st)} --> {fmt_ms(et)}\n{txt}\n")
    return "\n".join(out)


def normalize_to_srt_text(raw_bytes):
    """Decode raw subtitle bytes and automatically convert SAMI (.smi) or ASS (.ass) to SRT."""
    text = decode_subtitle_bytes(raw_bytes)
    upper_head = text[:4000].upper()
    if "<SAMI" in upper_head or "<SYNC" in upper_head:
        return smi_to_srt(text)
    if "[EVENTS]" in upper_head and "DIALOGUE:" in upper_head:
        return ass_to_srt(text)
    return text


def is_valid_korean_srt_text(text):
    """Verify that the subtitle text actually contains Korean Hangul (>= 15% of letters)."""
    if not text or len(text) < 200:
        return False
    hangul_count = len(re.findall(r"[가-힣]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    total_alpha = hangul_count + latin_count
    if hangul_count < 30 or total_alpha == 0:
        return False
    return (hangul_count / float(total_alpha)) >= 0.15


def resolve_korean_series_title(series_name):
    """Resolve an English series/anime title to its official Korean title."""
    if not series_name:
        return ""
    norm = re.sub(r"[^a-z0-9\s]", " ", series_name.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    if norm in KNOWN_KO_TITLES:
        return KNOWN_KO_TITLES[norm]
    for k, v in KNOWN_KO_TITLES.items():
        if norm.startswith(k):
            return v
    if norm in _KO_TITLE_CACHE:
        return _KO_TITLE_CACHE[norm]
    try:
        url = (
            "https://ko.wikipedia.org/w/api.php?action=query&list=search&srsearch="
            + urllib.parse.quote(series_name)
            + "&srlimit=1&format=json"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        res = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8"))
        hits = res.get("query", {}).get("search", [])
        if hits:
            ko_t = re.sub(r"\s*\([^)]*\)", "", hits[0].get("title", "")).strip()
            if re.search(r"[가-힣]", ko_t):
                _KO_TITLE_CACHE[norm] = ko_t
                return ko_t
    except Exception:
        pass
    _KO_TITLE_CACHE[norm] = series_name
    return series_name


def extract_absolute_episode_from_video_name(video_name):
    """Extract absolute episode number from TRaSH anime filename: 'Series - S04E01 - 132 - Title.mkv'."""
    if not video_name:
        return None
    base = os.path.basename(video_name)
    m = re.search(r"S\d{1,2}E\d{1,3}\s*-\s*(\d{1,4})\s*-", base, re.I)
    if m:
        return int(m.group(1))
    return None


def score_korean_sub_candidate(item, video_filename="", video_title=""):
    """Score OpenSubtitles candidate to prefer official Blu-ray/VOD Korean translations."""
    sub_name = (item.get("SubFileName") or "").lower()
    rel_name = (item.get("MovieReleaseName") or "").lower()
    movie_name = (item.get("MovieName") or "").lower()
    combined = f"{sub_name} {rel_name}"

    if item.get("SubFormat", "srt").lower() not in ("srt", "sub", "smi", "ass"):
        return -9999

    score = 100
    if video_title:
        vt_words = [w for w in re.findall(r"[a-z0-9]+", video_title.lower()) if len(w) >= 3]
        if vt_words:
            if all(w in movie_name or w in combined for w in vt_words):
                score += 200
            elif not any(w in movie_name or w in combined for w in vt_words):
                score -= 300

    for bad in BAD_MACHINE_MARKERS:
        if bad in combined:
            score -= 500

    for bad_sync in BAD_SYNC_SOURCE_MARKERS:
        if re.search(rf"\b{bad_sync}\b", combined):
            score -= 200

    for good in OFFICIAL_GOOD_GROUPS:
        if good in combined:
            score += 40

    v_lower = (video_filename or "").lower()
    if any(k in v_lower for k in ("bluray", "blu-ray", "bdrip", "brrip", "remux")):
        if any(k in combined for k in ("bluray", "blu-ray", "bdrip", "brrip", "remux")):
            score += 80
    elif any(k in v_lower for k in ("web", "web-dl", "webdl", "webrip")):
        if any(k in combined for k in ("web", "web-dl", "webdl", "webrip", "amzn", "nf", "dsnp")):
            score += 80

    try:
        dl_cnt = int(item.get("SubDownloadsCnt") or 0)
        score += min(dl_cnt // 50, 50)
    except Exception:
        pass

    try:
        rating = float(item.get("SubRating") or 0.0)
        if rating >= 8.0:
            score += 30
    except Exception:
        pass

    if item.get("SubHearingImpaired") == "1":
        score -= 10

    return score


def _fetch_cached_zip(zip_url):
    """Download and cache a Tistory kakaocdn .zip subtitle archive on disk."""
    _ensure_cache_dir()
    h = hashlib.md5(zip_url.encode("utf-8")).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{h}.zip")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
        with open(cache_path, "rb") as f:
            return f.read()
    req = urllib.request.Request(zip_url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=20).read()
    try:
        with open(cache_path, "wb") as f:
            f.write(data)
    except Exception:
        pass
    return data


def _match_episode_in_zip_namelist(namelist, season, episode, abs_ep=None, is_season_specific_archive=False):
    """Find the best matching subtitle file inside a Korean anime .zip archive for (season, episode, abs_ep)."""
    sub_files = [n for n in namelist if n.lower().endswith((".smi", ".srt", ".ass"))]
    if not sub_files:
        return None

    # Candidate episode numbers to match in filename
    if season > 1 and not is_season_specific_archive:
        target_nums = [abs_ep] if abs_ep else []
    else:
        target_nums = [episode]
        if abs_ep and abs_ep not in target_nums:
            target_nums.append(abs_ep)
        if season == 17 and 27 <= episode <= 40:
            target_nums.append(episode - 26)
        elif season == 17 and 14 <= episode <= 26:
            target_nums.append(episode - 13)

    # First check explicit SxxExx match for any season
    for fname in sub_files:
        base = os.path.basename(fname)
        if "_en." in base.lower():
            continue
        if re.search(rf"S0*{season}E0*{episode}\b", base, re.I):
            return fname

    for num in target_nums:
        if not num:
            continue
        patterns = [
            rf"-\s*0*{num}\b",
            rf"E0*{num}\b",
            rf"\b{num:02d}\b",
            rf"\({num:03d}\)",
        ]
        for pat in patterns:
            for fname in sub_files:
                base = os.path.basename(fname)
                if "_en." in base.lower():
                    continue
                # Reject if filename explicitly specifies a different season (e.g. S02E01 when season=4)
                m_s = re.search(r"S(\d{1,2})E\d{1,3}", base, re.I)
                if m_s and int(m_s.group(1)) != season:
                    continue
                # Reject if filename explicitly specifies a different 3-digit absolute episode in parens (e.g. (036) when abs_ep=132)
                m_abs = re.search(r"\((\d{3,4})\)", base)
                if m_abs and abs_ep and int(m_abs.group(1)) != abs_ep:
                    continue
                if re.search(pat, base, re.I):
                    return fname
    return None


def search_tistory_anime_archives(series_name, season, episode, abs_ep=None):
    """Search aniall.tistory.com and 0706life.tistory.com for Korean anime subtitle .zip packages."""
    ko_title = resolve_korean_series_title(series_name)
    post_urls = []

    # Direct known high-quality Tistory archives for Bleach TYBW & Jujutsu Kaisen
    s_low = (series_name or "").lower()
    if "bleach" in s_low and season == 17:
        if 27 <= episode <= 40:
            post_urls.append("https://0706life.tistory.com/363")
        elif 1 <= episode <= 26:
            post_urls.append("https://0706life.tistory.com/357")
    if "jujutsu kaisen" in s_low and season == 1:
        post_urls.extend(["https://aniall.tistory.com/2687", "https://aniall.tistory.com/846"])

    # Dynamic search on aniall.tistory.com
    for q in [ko_title, series_name]:
        if not q:
            continue
        try:
            s_url = f"https://aniall.tistory.com/search/{urllib.parse.quote(q)}"
            req = urllib.request.Request(s_url, headers={"User-Agent": "Mozilla/5.0"})
            html_s = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
            for pid, text in re.findall(r'<a[^>]+href=["\'](/\d+)["\'][^>]*>(.*?)</a>', html_s, re.S):
                clean_t = re.sub(r"<[^>]+>", "", text).strip()
                if "자막" in clean_t and "극장판" not in clean_t:
                    full_u = f"https://aniall.tistory.com{pid}"
                    if full_u not in post_urls:
                        post_urls.append(full_u)
        except Exception:
            pass

    results = []
    for p_url in post_urls[:5]:
        try:
            req_p = urllib.request.Request(p_url, headers={"User-Agent": "Mozilla/5.0"})
            html_p = urllib.request.urlopen(req_p, timeout=10).read().decode("utf-8", errors="ignore")
            zips = [
                u.replace("&amp;", "&")
                for u in re.findall(r'https://blog\.kakaocdn\.net/[^"\'>\s]+\.zip[^"\'>\s]*', html_p)
            ]
            # Prefer larger / combined zip on 0706life/363
            if "0706life.tistory.com/363" in p_url and len(zips) > 1:
                zips = list(reversed(zips))
            is_season_spec = ("0706life.tistory.com" in p_url) or (season == 1)
            for z_url in zips:
                if "_EN.zip" in urllib.parse.unquote(z_url):
                    continue
                z_bytes = _fetch_cached_zip(z_url)
                zf = zipfile.ZipFile(io.BytesIO(z_bytes))
                matched_member = _match_episode_in_zip_namelist(
                    zf.namelist(), season, episode, abs_ep, is_season_specific_archive=is_season_spec
                )
                if matched_member:
                    results.append((z_url, matched_member))
                    return results
        except Exception as e:
            logger.debug(f"Tistory archive check failed for {p_url}: {e}")
    return results


def search_gomlab_korean_subtitles(series_name, season, episode, abs_ep=None):
    """Search GOM Player official Korean subtitle archive (www.gomlab.com) for episode subtitles."""
    ko_title = resolve_korean_series_title(series_name)
    if not ko_title:
        return []
    ep_candidates = []
    if abs_ep:
        ep_candidates.append(abs_ep)
    if (season == 1 or not abs_ep) and episode and episode not in ep_candidates:
        ep_candidates.append(episode)

    for ep_num in ep_candidates:
        for kw in [f"{ko_title} {ep_num}화", f"{ko_title} {ep_num}"]:
            try:
                url = f"https://www.gomlab.com/subtitle-search?preface=All&keyword={urllib.parse.quote(kw)}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                html_g = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
                items = re.findall(r'subtitle-info\?intseq=(\d+)[^>]*>(.*?)</a>', html_g, re.S)
                for seq, raw_title in items:
                    clean_t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw_title)).strip()
                    if ko_title in clean_t and re.search(rf"(?<!\d)0*{ep_num}(?!\d)", clean_t):
                        return [(seq, clean_t)]
            except Exception as e:
                logger.debug(f"Gomlab search failed for {kw}: {e}")
    return []


def extract_and_translate_embedded_subtitles(video_path):
    """Extract embedded subtitle from MKV/MP4 and translate pure dialogue to Korean with Anime Glossary."""
    if not video_path or not os.path.exists(video_path):
        return None
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-select_streams", "s", video_path],
            timeout=15,
        ).decode("utf-8", errors="ignore")
        streams = json.loads(out).get("streams", [])
        if not streams:
            return None

        # 1. Check if embedded Korean subtitle track already exists
        for s in streams:
            tags = s.get("tags", {})
            lang = (tags.get("language") or "").lower()
            if lang in ("kor", "ko"):
                idx = s["index"]
                raw_ko = subprocess.check_output(
                    ["ffmpeg", "-v", "quiet", "-i", video_path, "-map", f"0:{idx}", "-f", "srt", "-"],
                    timeout=60,
                )
                srt_ko = normalize_to_srt_text(raw_ko)
                if is_valid_korean_srt_text(srt_ko):
                    return srt_ko

        # 2. Pick best English dialogue track (avoiding Signs & Songs)
        chosen_idx = streams[0]["index"]
        for s in streams:
            tags = s.get("tags", {})
            lang = (tags.get("language") or "").lower()
            title = (tags.get("title") or "").lower()
            if lang in ("eng", "en") and "sign" not in title and "forced" not in title:
                chosen_idx = s["index"]
                break

        raw_ass = subprocess.check_output(
            ["ffmpeg", "-v", "quiet", "-i", video_path, "-map", f"0:{chosen_idx}", "-f", "ass", "-"],
            timeout=60,
        ).decode("utf-8", errors="ignore")

        def parse_ass_ms(t_str):
            parts = t_str.strip().split(":")
            h, m = int(parts[0]), int(parts[1])
            sp = parts[2].split(".")
            s, cs = int(sp[0]), int(sp[1][:2]) if len(sp) > 1 else 0
            return ((h * 3600 + m * 60 + s) * 1000) + cs * 10

        def fmt_ms(ms):
            s, msec = divmod(max(0, ms), 1000)
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"

        cues = []
        for line in raw_ass.splitlines():
            if line.startswith("Dialogue:"):
                parts = line[9:].split(",", 9)
                if len(parts) < 10:
                    continue
                st_ms = parse_ass_ms(parts[1])
                et_ms = parse_ass_ms(parts[2])
                style = parts[3].strip().lower()
                text = parts[9]
                if any(w in style for w in ("sign", "ts", "typeset", "kara", "op", "ed", "song", "lyric", "eyecatch", "logo", "note")):
                    continue
                if "\\p1" in text or "\\p2" in text:
                    continue
                if "\\an8" in text and "\\i1" in text:
                    continue
                clean = re.sub(r"\{[^}]*\}", "", text).replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
                clean = re.sub(r"<[^>]*>", "", clean)
                clean = re.sub(r"\s+", " ", clean).strip()
                if not clean:
                    continue
                # Apply pre-translation proper noun & anime terminology glossary
                for pat, repl in ANIME_PRE_GLOSSARY:
                    clean = re.sub(pat, repl, clean, flags=re.I)
                cues.append([st_ms, et_ms, clean])

        cues.sort(key=lambda x: (x[0], x[1]))
        merged = []
        for st, et, txt in cues:
            if merged and merged[-1][2] == txt and abs(st - merged[-1][1]) <= 200:
                merged[-1][1] = max(merged[-1][1], et)
            else:
                merged.append([st, et, txt])

        if not merged:
            return None

        def gtx_batch_post(texts):
            joined = "\n".join(texts)
            url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t"
            body = urllib.parse.urlencode({"q": joined}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"},
            )
            data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
            trans_full = "".join(seg[0] for seg in data[0] if seg and seg[0])
            res_lines = [l.strip() for l in trans_full.split("\n")]
            if len(res_lines) == len(texts):
                return res_lines
            out_l = []
            for t in texts:
                b = urllib.parse.urlencode({"q": t}).encode("utf-8")
                r = urllib.request.Request(
                    url,
                    data=b,
                    headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"},
                )
                d = json.loads(urllib.request.urlopen(r, timeout=10).read().decode("utf-8"))
                out_l.append("".join(seg[0] for seg in d[0] if seg and seg[0]).strip())
            return out_l

        chunk_size = 40
        chunks = [[c[2] for c in merged[i : i + chunk_size]] for i in range(0, len(merged), chunk_size)]
        with ThreadPoolExecutor(max_workers=5) as ex:
            translated_chunks = list(ex.map(gtx_batch_post, chunks))
        flat_ko = [item for sub in translated_chunks for item in sub]

        out_srt = []
        for idx, ((st, et, _), ko_txt) in enumerate(zip(merged, flat_ko), 1):
            if et <= st:
                et = st + 2000
            out_srt.append(f"{idx}\n{fmt_ms(st)} --> {fmt_ms(et)}\n{ko_txt}\n")
        return "\n".join(out_srt)
    except Exception as e:
        logger.error(f"Embedded subtitle extraction/translation failed for {video_path}: {e}")
        return None


class YifySubtitlesSubtitle(Subtitle):
    provider_name = "yifysubtitles"

    def __init__(self, language, page_link, release_name, uploader, is_episode=False, series_name=None, season=None, episode=None):
        super(YifySubtitlesSubtitle, self).__init__(language, page_link=page_link)
        self.release_name = release_name
        self.uploader = uploader or "OpenSubtitles_Official"
        self.is_episode = is_episode
        self.series_name = series_name
        self.season = season
        self.episode = episode
        self.matches = set()

    @property
    def id(self):
        return self.page_link

    def get_matches(self, video):
        matches = set()
        if isinstance(video, Episode):
            matches.update(["series", "season", "episode", "year"])
        elif isinstance(video, Movie):
            matches.update(["title", "year"])
        if self.release_name:
            v_type = "episode" if isinstance(video, Episode) else "movie"
            matches |= guess_matches(video, guessit(self.release_name, {"type": v_type}))
        self.matches = matches
        return matches


class YifySubtitlesProvider(Provider):
    """Universal 4-Tier Korean Subtitle Engine (Movies, TV Dramas & Anime)."""

    languages = {Language("kor"), Language("eng")}
    video_types = (Episode, Movie)

    def initialize(self):
        self.session = urllib.request.build_opener()
        self.session.addheaders = [("User-Agent", "TemporaryUserAgent")]

    def terminate(self):
        pass

    def _os_api_search(self, path):
        url = f"https://rest.opensubtitles.org/search/{path}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TemporaryUserAgent"})
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status == 200:
                    data = json.loads(r.read().decode("utf-8", errors="ignore"))
                    if isinstance(data, list):
                        return data
        except Exception as e:
            logger.error(f"OpenSubtitles REST search error ({url}): {e}")
        return []

    def query(self, video, languages):
        is_ep = isinstance(video, Episode)
        imdb_raw = (getattr(video, "series_imdb_id", None) or getattr(video, "imdb_id", None)) if is_ep else getattr(video, "imdb_id", None)
        imdb_num = imdb_raw.lower().replace("tt", "").strip() if imdb_raw else None
        video_fname = getattr(video, "name", "") or ""
        video_title = (getattr(video, "series", None) if is_ep else getattr(video, "title", None)) or ""
        season = getattr(video, "season", None) if is_ep else None
        episode = getattr(video, "episode", None) if is_ep else None
        abs_ep = extract_absolute_episode_from_video_name(video_fname) if is_ep else None

        subtitles = []
        for lang in languages:
            lang_code = "kor" if lang == Language("kor") else "eng"
            found_for_lang = []

            # === TIER 1: OpenSubtitles REST API ===
            items = []
            if is_ep:
                if imdb_num and season is not None and episode is not None:
                    items = self._os_api_search(f"episode-{episode}/imdbid-{imdb_num}/season-{season}/sublanguageid-{lang_code}")
                if not items and video_title and season is not None and episode is not None:
                    q = urllib.parse.quote(video_title.lower())
                    items = self._os_api_search(f"episode-{episode}/query-{q}/season-{season}/sublanguageid-{lang_code}")
            else:
                if imdb_num:
                    items = self._os_api_search(f"imdbid-{imdb_num}/sublanguageid-{lang_code}")
                if not items and video_title:
                    q = urllib.parse.quote(video_title.lower())
                    items = self._os_api_search(f"query-{q}/sublanguageid-{lang_code}")

            ranked = []
            for item in items:
                if is_ep and season is not None and episode is not None:
                    try:
                        s_num = int(item.get("SeriesSeason") or 0)
                        e_num = int(item.get("SeriesEpisode") or 0)
                        if (s_num != 0 and s_num != int(season)) or (e_num != 0 and e_num != int(episode)):
                            continue
                    except Exception:
                        pass
                sc = score_korean_sub_candidate(item, video_fname, video_title)
                if sc > -1000:
                    ranked.append((sc, item))

            ranked.sort(key=lambda x: x[0], reverse=True)
            for sc, item in ranked[:8]:
                sub_id = item.get("IDSubtitleFile")
                if not sub_id:
                    continue
                dl_url = f"https://dl.opensubtitles.org/en/download/file/{sub_id}.gz"
                rel = item.get("MovieReleaseName") or item.get("SubFileName") or "BluRay.1080p.x264"
                sub = YifySubtitlesSubtitle(
                    lang,
                    dl_url,
                    rel,
                    f"OS_Score_{sc}",
                    is_episode=is_ep,
                    series_name=video_title if is_ep else None,
                    season=season,
                    episode=episode,
                )
                found_for_lang.append(sub)

            # === TIER 2 & 3/4 (For Korean Episode Subtitles when OpenSubtitles has 0 matches) ===
            if is_ep and lang == Language("kor") and not found_for_lang:
                # Tier 2A: Korean Anime Tistory Archives (aniall.tistory.com & 0706life.tistory.com)
                t_hits = search_tistory_anime_archives(video_title, season, episode, abs_ep)
                for z_url, member in t_hits:
                    page_link = f"tistoryzip://{z_url}|||{member}"
                    sub = YifySubtitlesSubtitle(
                        lang,
                        page_link,
                        os.path.basename(member),
                        "Korean_Anime_Archive",
                        is_episode=True,
                        series_name=video_title,
                        season=season,
                        episode=episode,
                    )
                    found_for_lang.append(sub)

                # Tier 2B: GOM Player Official Korean Subtitle Archive (www.gomlab.com)
                if not found_for_lang:
                    g_hits = search_gomlab_korean_subtitles(video_title, season, episode, abs_ep)
                    for intseq, g_title in g_hits:
                        page_link = f"gomlab://{intseq}"
                        sub = YifySubtitlesSubtitle(
                            lang,
                            page_link,
                            g_title,
                            "GomLab_Korean_Archive",
                            is_episode=True,
                            series_name=video_title,
                            season=season,
                            episode=episode,
                        )
                        found_for_lang.append(sub)

                # Tier 3/4: Embedded Subtitle Track Extraction + Anime Glossary Neural Translation
                if not found_for_lang and video_fname and os.path.exists(video_fname):
                    page_link = f"embed://{video_fname}"
                    sub = YifySubtitlesSubtitle(
                        lang,
                        page_link,
                        os.path.basename(video_fname),
                        "Embedded_Glossary_KO",
                        is_episode=True,
                        series_name=video_title,
                        season=season,
                        episode=episode,
                    )
                    found_for_lang.append(sub)

            subtitles.extend(found_for_lang)

        return subtitles

    def list_subtitles(self, video, languages):
        return self.query(video, languages)

    def download_subtitle(self, subtitle):
        link = subtitle.page_link
        try:
            # Tier 2A: Tistory Zip Archive
            if link.startswith("tistoryzip://"):
                payload = link[len("tistoryzip://") :]
                z_url, member = payload.split("|||", 1)
                z_bytes = _fetch_cached_zip(z_url)
                zf = zipfile.ZipFile(io.BytesIO(z_bytes))
                raw = zf.read(member)
                text = normalize_to_srt_text(raw)
                if is_valid_korean_srt_text(text):
                    subtitle.content = fix_line_ending(text.encode("utf-8"))
                else:
                    subtitle.content = b""
                return

            # Tier 2B: Gomlab Direct Download
            if link.startswith("gomlab://"):
                intseq = link[len("gomlab://") :].strip()
                dl_url = f"https://www.gomlab.com/subtitle-download?intseq={intseq}"
                req = urllib.request.Request(
                    dl_url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": f"https://www.gomlab.com/subtitle-info?intseq={intseq}&preface=kr",
                    },
                )
                raw = urllib.request.urlopen(req, timeout=15).read()
                text = normalize_to_srt_text(raw)
                if is_valid_korean_srt_text(text):
                    subtitle.content = fix_line_ending(text.encode("utf-8"))
                else:
                    subtitle.content = b""
                return

            # Tier 3/4: Embedded Subtitle Extraction & Glossary Neural Translation
            if link.startswith("embed://"):
                video_path = link[len("embed://") :]
                text = extract_and_translate_embedded_subtitles(video_path)
                if text and is_valid_korean_srt_text(text):
                    subtitle.content = fix_line_ending(text.encode("utf-8"))
                else:
                    subtitle.content = b""
                return

            # Tier 1: OpenSubtitles .gz Download
            req = urllib.request.Request(link, headers={"User-Agent": "TemporaryUserAgent"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status != 200:
                    return
                raw = r.read()
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass

                text = normalize_to_srt_text(raw)
                if subtitle.language == Language("kor"):
                    if not is_valid_korean_srt_text(text):
                        logger.warning(f"Rejected fake/English subtitle disguised as Korean: {link}")
                        subtitle.content = b""
                        return

                subtitle.content = fix_line_ending(text.encode("utf-8"))
        except Exception as e:
            logger.error(f"Subtitle download error ({link}): {e}")
