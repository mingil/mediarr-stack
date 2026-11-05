# -*- coding: utf-8 -*-
from __future__ import absolute_import
import base64
import html
import io
import json
import logging
import re
from random import randint
from urllib.parse import urljoin
from zipfile import ZipFile, is_zipfile

from bs4 import BeautifulSoup
from guessit import guessit
from requests import Session
from subliminal import Movie
from subliminal.subtitle import fix_line_ending
from subliminal_patch.providers import Provider
from subliminal_patch.subtitle import Subtitle, guess_matches
from subzero.language import Language
from .utils import FIRST_THOUSAND_OR_SO_USER_AGENTS as AGENT_LIST

logger = logging.getLogger(__name__)


def score_korean_sub_candidate(meta, content_sample=""):
    score = 100
    rel = (meta.get("MovieReleaseName", "") + " " + meta.get("SubFileName", "")).lower()
    if any(bad in rel for bad in ("hdcam", "cam", "hdtc", ".tc.", "telesync", "캠버전", "김코난")):
        score -= 500
    if any(good in rel for good in ("bluray", "blu-ray", "remux", "web-dl", "webrip", "1080p", "2160p")):
        score += 100
    if any(grp in rel for grp in ("sparks", "rarbg", "fgt", "amiable", "tigole")):
        score += 150
    if meta.get("SubFormat", "").lower() == "srt":
        score += 80

    if content_sample:
        if any(spam in content_sample for spam in ("자막넷", "jamack.net", "첫 자막입니다", "설명충", "OpenSubtitles.org")):
            score -= 600
        for bad_kr in ("맞칠건가", "옴겨", "됬지", "예아.", "음-흠", "자, 걱정하자", "볼 수 있니?"):
            if bad_kr in content_sample:
                score -= 200
        for good_kr in ("쏘지 마", "됐지?", "잠깐만", "괜찮아", "안 돼", "할 수"):
            if good_kr in content_sample:
                score += 60
    return score


def normalize_korean_subtitle_bytes(raw_bytes, is_smi=False):
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            text = raw_bytes.decode(enc)
            break
        except Exception:
            continue
    else:
        text = raw_bytes.decode("cp949", errors="replace")

    if not is_smi or ("-->" in text and "<sync" not in text.lower()):
        return text.encode("utf-8")

    cleaned = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<(style|script|head)[^>]*>.*?</\1>", "", cleaned, flags=re.I | re.DOTALL)
    matches = list(re.finditer(r"<sync\s+start\s*=\s*['\"]?(\d+)['\"]?[^>]*>", cleaned, flags=re.I))
    cues = []
    for idx, m in enumerate(matches):
        start_ms = int(m.group(1))
        frag = cleaned[m.end():(matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned))]
        frag = re.sub(r"<br\s*/?>", "\n", frag, flags=re.I)
        frag = re.sub(r"<[^>]+>", "", frag)
        frag = html.unescape(frag).replace("\xa0", " ")
        lines = [ln.strip() for ln in frag.splitlines() if ln.strip()]
        cues.append((start_ms, "\n".join(lines).strip()))

    blocks = []
    seq = 1
    for i, (s_ms, c_txt) in enumerate(cues):
        if not c_txt:
            continue
        e_ms = cues[i + 1][0] if i + 1 < len(cues) else s_ms + 3500
        if e_ms <= s_ms:
            e_ms = s_ms + 3000
        elif e_ms - s_ms > 8000:
            e_ms = s_ms + 5000

        def fmt(ms):
            h, r = divmod(max(0, ms), 3600000)
            m, r = divmod(r, 60000)
            s, ml = divmod(r, 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ml:03d}"

        blocks.append(f"{seq}\n{fmt(s_ms)} --> {fmt(e_ms)}\n{c_txt}\n")
        seq += 1
    return "\n".join(blocks).encode("utf-8")


class YifySubtitle(Subtitle):
    """YIFY + OpenSubtitles Official Blu-ray Quality Korean Subtitle"""
    provider_name = 'yifysubtitles'
    hearing_impaired_verifiable = True

    def __init__(self, language, page_link, release, uploader, rating, hi, direct_srt_bytes=None):
        super(YifySubtitle, self).__init__(language)
        self.page_link = page_link
        self.hearing_impaired = hi
        self.release_info = release.replace('\n', ', ')
        self.uploader = uploader
        self.rating = rating
        self.direct_srt_bytes = direct_srt_bytes

    @property
    def id(self):
        return self.page_link

    def make_picklable(self):
        self.content = None
        self._is_valid = False
        return self

    def get_matches(self, video):
        self.matches.add('imdb_id')
        self.matches |= guess_matches(video, guessit(self.release_info, video.hints))
        return self.matches


class YifySubtitlesProvider(Provider):
    """Hybrid OpenSubtitles REST (Quality-Scored Official Blu-ray/VOD) + YIFY Provider."""

    YifyLanguages = [
        ('Albanian', 'sqi', None),
        ('Arabic', 'ara', None),
        ('Bengali', 'ben', None),
        ('Brazilian Portuguese', 'por', 'BR'),
        ('Bulgarian', 'bul', None),
        ('Chinese', 'zho', None),
        ('Croatian', 'hrv', None),
        ('Czech', 'ces', None),
        ('Danish', 'dan', None),
        ('Dutch', 'nld', None),
        ('English', 'eng', None),
        ('Farsi/Persian', 'fas', None),
        ('Finnish', 'fin', None),
        ('French', 'fra', None),
        ('German', 'deu', None),
        ('Greek', 'ell', None),
        ('Hebrew', 'heb', None),
        ('Hungarian', 'hun', None),
        ('Indonesian', 'ind', None),
        ('Italian', 'ita', None),
        ('Japanese', 'jpn', None),
        ('Korean', 'kor', None),
        ('Lithuanian', 'lit', None),
        ('Macedonian', 'mkd', None),
        ('Malay', 'msa', None),
        ('Norwegian', 'nor', None),
        ('Polish', 'pol', None),
        ('Portuguese', 'por', None),
        ('Romanian', 'ron', None),
        ('Russian', 'rus', None),
        ('Serbian', 'srp', None),
        ('Slovenian', 'slv', None),
        ('Spanish', 'spa', None),
        ('Swedish', 'swe', None),
        ('Thai', 'tha', None),
        ('Turkish', 'tur', None),
        ('Urdu', 'urd', None),
        ('Vietnamese', 'vie', None)
    ]

    languages = {Language(l, c) for (_, l, c) in YifyLanguages}
    languages.update(set(Language.rebuild(l, hi=True) for l in languages))
    server_url = 'https://yts-subs.com'
    video_types = (Movie,)

    def initialize(self):
        self.session = Session()
        self.session.headers['User-Agent'] = AGENT_LIST[randint(0, len(AGENT_LIST) - 1)]
        self.session.headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        self.session.headers["Accept-Language"] = "en-US,en;q=0.5"

    def terminate(self):
        self.session.close()

    def _query_opensubtitles_rest_korean(self, imdb_id):
        results = []
        try:
            imdb_num = imdb_id.lstrip('t')
            os_url = f"https://rest.opensubtitles.org/search/imdbid-{imdb_num}/sublanguageid-kor"
            resp = self.session.get(os_url, headers={"User-Agent": "TemporaryUserAgent"}, timeout=10)
            if resp.status_code != 200:
                return results
            items = resp.json()
            if not isinstance(items, list):
                return results
            items.sort(key=lambda x: score_korean_sub_candidate(x), reverse=True)
            best_candidates = []
            for it in items[:5]:
                fid = it.get("IDSubtitleFile")
                if not fid:
                    continue
                strem_url = f"https://subs5.strem.io/en/download/subencoding-stremio-utf8/src-api/file/{fid}"
                try:
                    dl = self.session.get(strem_url, timeout=8)
                    if dl.status_code != 200 or not dl.content:
                        continue
                    is_smi = it.get("SubFormat", "").lower() == "smi" or b"<sync" in dl.content[:2000].lower()
                    norm_bytes = normalize_korean_subtitle_bytes(dl.content, is_smi=is_smi)
                    sample_txt = norm_bytes.decode("utf-8", errors="ignore")[:3000]
                    q_score = score_korean_sub_candidate(it, sample_txt)
                    if q_score >= 150:
                        rel_name = it.get("MovieReleaseName") or it.get("SubFileName") or "BluRay.1080p.x264"
                        best_candidates.append(
                            YifySubtitle(
                                Language("kor"),
                                strem_url,
                                rel_name,
                                "opensubtitles-official",
                                q_score,
                                False,
                                direct_srt_bytes=norm_bytes,
                            )
                        )
                except Exception:
                    continue
            best_candidates.sort(key=lambda x: x.rating, reverse=True)
            return best_candidates
        except Exception as e:
            logger.debug("OpenSubtitles REST Korean check error: %s", e)
            return results

    def _parse_row(self, row, languages, server_url):
        td = row.findAll('td')
        rating = int(td[0].text.strip())
        sub_lang = td[1].text.strip()
        release = re.sub(r'^\s*subtitle\s*', '', td[2].text.strip())
        page_link = urljoin(server_url, td[2].find('a').get('href'))
        hi = False
        uploader = td[4].text.strip()

        _, l, c = next(x for x in self.YifyLanguages if x[0] == sub_lang)
        lang = Language(l, c)

        if languages & {lang}:
            return [YifySubtitle(lang, page_link, release, uploader, rating, hi)]

        return []

    def query(self, languages, imdb_id):
        subtitles = []
        if any(l.alpha3 == 'kor' for l in languages):
            os_subs = self._query_opensubtitles_rest_korean(imdb_id)
            if os_subs:
                subtitles.extend(os_subs)

        logger.info('Searching subtitle %r on %s', imdb_id, self.server_url)
        response = self.session.get(
            urljoin(self.server_url, f'/movie-imdb/{imdb_id}'),
            allow_redirects=True,
            timeout=15,
            headers={'Referer': self.server_url},
        )

        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'lxml')
            tbl = soup.find('table', {'class': 'other-subs'})
            tbl_body = tbl.find('tbody') if tbl else None
            rows = tbl_body.findAll('tr') if tbl_body else []
            for row in rows:
                try:
                    subtitles = subtitles + self._parse_row(row, languages, self.server_url)
                except Exception:
                    pass

        subtitles.sort(key=lambda x: x.rating, reverse=True)
        return subtitles

    def list_subtitles(self, video, languages):
        return self.query(languages, video.imdb_id) if isinstance(video, Movie) and video.imdb_id else []

    def download_subtitle(self, subtitle):
        if getattr(subtitle, "direct_srt_bytes", None):
            subtitle.content = fix_line_ending(subtitle.direct_srt_bytes)
            return

        logger.info('Downloading subtitle %r', subtitle.page_link)
        request = self.session.get(
            urljoin(self.server_url, subtitle.page_link),
            headers={'Referer': self.server_url},
            timeout=15,
        )
        request.raise_for_status()

        soup = BeautifulSoup(request.content, 'lxml')
        download_button = soup.find('a', {'class': 'download-subtitle'}) or soup.find('a', attrs={'data-link': True})
        if download_button:
            data_link = download_button.get('data-link')
            if data_link:
                dl_url = base64.b64decode(data_link).decode('utf-8')
            else:
                dl_url = urljoin(self.server_url, download_button['href'])

            dl_req = self.session.get(dl_url, headers={'Referer': subtitle.page_link}, timeout=20)
            dl_req.raise_for_status()

            archive_stream = io.BytesIO(dl_req.content)
            if is_zipfile(archive_stream):
                self._process_archive(ZipFile(archive_stream), subtitle)
            else:
                logger.error('Ignore unsupported archive %r', dl_req.headers)
        else:
            logger.error('Cannot find download link on this page: %r', subtitle.page_link)

    def _process_archive(self, archive_stream, subtitle):
        for file_name in archive_stream.namelist():
            if file_name.lower().endswith(('.srt', '.sub')):
                raw = archive_stream.read(file_name)
                subtitle.content = fix_line_ending(normalize_korean_subtitle_bytes(raw, is_smi=False))
                if subtitle.is_valid():
                    return
            elif file_name.lower().endswith('.smi'):
                raw = archive_stream.read(file_name)
                subtitle.content = fix_line_ending(normalize_korean_subtitle_bytes(raw, is_smi=True))
                if subtitle.is_valid():
                    return
