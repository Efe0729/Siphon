"""Tranny.one: URL download (direct MP4) and Browse.

Video pages: https://www.tranny.one/view/<id>/  (listing links add ?l=<token>)
The player block ``#videoContainer`` carries ``data-high`` / ``data-low``
MP4 addresses on stream.tranny.one (signed with key/end, per-connection
speed cap, so several ranged connections help).

Listings load more videos while scrolling; the same pages are reachable as
``<listing>?extended=1&p=<n>`` (26 videos per page).  Search is
``/search/<query>/`` with optional sort suffixes (recent/, rating/, viewed/).
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote_plus, urlsplit

from siphon.core import config
from siphon.sites import kvs
from siphon.sites.base import MirrorsBlockedError
from siphon.sites.site import Sitesite

TRANNYONE_ROOT = 'https://www.tranny.one'
_HOST = r'https://(?:www|[a-z]{2})\.tranny\.one'
_DATA_RE = re.compile(r'data-(high|low)="(https?://[^"]+)"')
_POSTER_RE = re.compile(r"poster\s*=\s*[^;]*?'(https?://[^']+/thumbs/original/[^']+)'")


def parse_streams(text):
    """{'high': url, 'low': url} from a video page (empty if missing)."""
    found = {}
    for quality, url in _DATA_RE.findall(text or ''):
        found.setdefault(quality, html.unescape(url))
    return found


class SiteTrannyone(Sitesite):
    website_pattern = _HOST + r'/view/\d+/?(?:[?#].*)?$'
    website_dirname_pattern = _HOST + r'/view/(\d+)'
    direct_site_name = 'Tranny.one'
    direct_default_referer = TRANNYONE_ROOT + '/'
    direct_range_workers_max = 8
    direct_browser_session = True

    def get_url_infos(self):
        self._direct_url = None
        self._direct_referer = None
        self._m3u8url = None
        with kvs.make_scraper() as scraper:
            page = scraper.get(self._url, headers={'Referer': TRANNYONE_ROOT + '/'},
                               timeout=30, allow_redirects=True,
                               **config.proxy_request_kwargs())
            self._direct_cookies = kvs.session_cookies(scraper)
        status = int(getattr(page, 'status_code', 0) or 0)
        text = getattr(page, 'text', '') or ''
        if status in (403, 429, 503) and 'just a moment' in text.lower():
            raise MirrorsBlockedError(self._url)
        if status != 200:
            raise Exception(f'Tranny.one page request failed (HTTP {status})')
        streams = parse_streams(text)
        if not streams:
            raise Exception('Tranny.one player data not found (site may have changed)')
        pref = str(self._resolution_pref or 'highest').lower()
        if pref == 'lowest' or (pref.isdigit() and int(pref) < 720 and 'low' in streams):
            chosen = streams.get('low') or streams.get('high')
        else:
            chosen = streams.get('high') or streams.get('low')
        title_tag = re.search(r'class="movie-title-text"[^>]*>(.*?)</span>', text, re.S)
        candidates = [re.sub(r'<[^>]+>', ' ', title_tag.group(1))] if title_tag else []
        title = kvs.pick_title(text, self._url, candidates, 'Tranny.one', TRANNYONE_ROOT)
        print(f'[Tranny.one] title: {title} ({"high" if chosen == streams.get("high") else "low"})',
              flush=True)
        poster = _POSTER_RE.search(text)
        self._targetName = title
        self._imageUrl = poster.group(1).replace('.webp', '.jpg') if poster else None
        self._direct_url = chosen
        self._direct_referer = self._url
        self._extra_headers = {'Referer': self._url}


# ── Browse ──────────────────────────────────────────────────────────────────
_VIDEO_HREF = re.compile(_HOST + r'/view/(\d+)/')
_CAT_HREF = re.compile(r'^' + _HOST + r'/c\d+/[a-z0-9-]+/$')


class TrannyoneBrowser(kvs.KvsBrowser):
    ROOT = TRANNYONE_ROOT
    NAME = 'Tranny.one'
    VIDEO_PATH = r'/view/\d+/?'
    SECTIONS = [
        ('Featured', TRANNYONE_ROOT + '/'),
        ('Recent', TRANNYONE_ROOT + '/recent/'),
        ('Most viewed', TRANNYONE_ROOT + '/viewed/'),
        ('Top rated', TRANNYONE_ROOT + '/rating/'),
        ('HD', TRANNYONE_ROOT + '/hd/'),
    ]
    FALLBACK_CATS = [
        ('Shemales with Guys', '/c2042/shemales-fuck-guys/'), ('Anal', '/c2096/shemale-anal/'),
        ('Amateur', '/c2106/amateur-trans/'), ('Masturbation', '/c2063/masturbation/'),
        ('Big Tits', '/c2052/big-tits/'), ('Shemales with Girls', '/c2048/shemales-fuck-girls/'),
        ('Shemale with Shemale', '/c2049/shemales-fuck-shemales/'),
        ('Hardcore', '/c2100/hardcore/'), ('Asian Ladyboys', '/c2047/asian-ladyboys/'),
        ('Big Cock', '/c2081/big-cock/'), ('Threesome', '/c2062/threesome/'),
        ('Interracial', '/c2060/interracial/'), ('Sissy', '/c2381/sissy-femboy-porn/'),
        ('Babes', '/c2300/babes/'), ('Asian', '/c2061/asian/'), ('Webcams', '/c2053/webcams/'),
    ]
    SEARCH_SORTS = [('Relevance', ''), ('Recent', 'recent'), ('Most viewed', 'viewed'),
                    ('Top rated', 'rating')]

    @classmethod
    def is_video_url(cls, url):
        return bool(re.match(_HOST + r'/view/\d+', str(url or '')))

    @classmethod
    def fetch_categories(cls):
        cats = [{'name': name, 'url': url, 'count': 0} for name, url in cls.SECTIONS]
        found = []
        try:
            found = parse_categories(cls._get(TRANNYONE_ROOT + '/'))
        except MirrorsBlockedError:
            raise
        except Exception as exc:
            print(f'[Tranny.one] category list unavailable: {exc}', flush=True)
        if not found:
            found = [{'name': n, 'url': TRANNYONE_ROOT + p, 'count': 0}
                     for n, p in cls.FALLBACK_CATS]
        return cats + found

    @classmethod
    def fetch_page(cls, url):
        return parse_videos(cls._get(url))

    @staticmethod
    def page_url(base_url, page):
        base = re.sub(r'[?&](?:extended|p)=[^&]*', '', base_url).rstrip('?&')
        if page <= 1:
            return base
        sep = '&' if '?' in base else '?'
        return f'{base}{sep}extended=1&p={int(page)}'

    @classmethod
    def search_url(cls, query, sort=''):
        words = re.sub(r'\s+', ' ', (query or '').strip())
        url = f'{TRANNYONE_ROOT}/search/{quote_plus(words)}/'
        return url + (f'{sort}/' if sort else '')


def parse_videos(text):
    if not text:
        return []
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, 'html.parser')
    videos, seen = [], set()
    for box in soup.select('div.th[data-id]'):
        link = box.select_one('a.pp[href]')
        if link is None:
            continue
        match = _VIDEO_HREF.match(link['href'])
        if not match or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        img = box.select_one('img')
        title_el = box.select_one('.video-title')
        title = (title_el.get_text(' ', strip=True) if title_el else '') or (
            re.sub(r'\s*(?:Shemale|Trans) Porn$', '', img.get('alt', '')) if img else '')
        thumb = ''
        if img is not None:
            thumb = (img.get('data-src') or img.get('src') or '').strip()
            if thumb.endswith('px_4_3.png'):
                thumb = ''
        dur = box.select_one('.btime')
        videos.append({'url': link['href'], 'title': html.unescape(title) or link['href'],
                       'thumbnail': thumb, 'duration': dur.get_text(strip=True) if dur else ''})
    return videos


def parse_categories(text):
    if not text:
        return []
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, 'html.parser')
    cats, seen = [], set()
    for link in soup.select('a[href]'):
        href = link['href'].strip()
        if not _CAT_HREF.match(href):
            continue
        path = urlsplit(href).path
        if path in seen:
            continue
        name = re.sub(r'\s+', ' ', link.get_text(' ', strip=True))
        if not name or len(name) > 40:
            continue
        seen.add(path)
        cats.append({'name': name, 'url': TRANNYONE_ROOT + path, 'count': 0})
    return cats
