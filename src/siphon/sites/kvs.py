"""Shared support for sites built on KVS (Kernel Video Sharing).

KVS sites look alike: video pages at <root>/videos/<id>/<slug>/ embed a
``flashvars`` object whose ``video_url`` / ``video_alt_url`` … point to plain
MP4 files under /get_file/; listings are paged as <listing>/<n>/, search is
<root>/search/<query>/ and categories live at <root>/categories/<slug>/.

To add a KVS site, subclass KvsSite and KvsBrowser and set ROOT/NAME (see
sites built on it).
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote, urlsplit

import cloudscraper

try:
    from curl_cffi import requests as cffi_requests
    _use_cffi = True
except ImportError:  # pragma: no cover - optional dependency
    cffi_requests = None
    _use_cffi = False

from siphon.core import browser as real_browser
from siphon.core import config
from siphon.sites.base import MirrorsBlockedError, request_headers
from siphon.sites.downloader import MediaSite

_FLASHVARS_RE = re.compile(r'flashvars\s*=\s*\{(.*?)\}\s*;', re.S)
_PAIR_RE = re.compile(r"(\w+)\s*:\s*'((?:\\.|[^'\\])*)'")


def make_scraper():
    if _use_cffi:
        return cffi_requests.Session(impersonate='chrome')
    return cloudscraper.create_scraper(browser=request_headers, delay=10)


# Embed players may give the settings object a random name
# (``var tf835f9b2cd = {… video_url: …};``) and pass it to kt_player().
_ANY_VARS_RE = re.compile(r'var\s+(\w+)\s*=\s*\{(.*?)\}\s*;', re.S)


def parse_flashvars(text):
    """Return the KVS flashvars object as a dict of strings (empty if missing)."""
    match = _FLASHVARS_RE.search(text or '')
    if not match:
        player = re.search(r'kt_player\([^)]*?,\s*(\w+)\s*\)', text or '')
        wanted = player.group(1) if player else None
        for candidate in _ANY_VARS_RE.finditer(text or ''):
            if (wanted and candidate.group(1) == wanted) or (
                    not wanted and re.search(r'\bvideo_url\s*:', candidate.group(2))):
                match = candidate
                break
        if not match:
            return {}
        result = {}
        for key, value in _PAIR_RE.findall(match.group(2)):
            result[key] = html.unescape(value.replace("\\'", "'").replace('\\/', '/'))
        return result
    result = {}
    for key, value in _PAIR_RE.findall(match.group(1)):
        result[key] = html.unescape(value.replace("\\'", "'").replace('\\/', '/'))
    return result


def fetch_text(scraper, url, referer='', name='Site'):
    """Page text, whatever it takes.

    A site that answers with a Cloudflare check is opened in a real browser
    instead (see core/browser.py), which also stores the pass so the quick
    way works again afterwards.
    """
    status, text = 0, ''
    try:
        response = scraper.get(url, headers={'Referer': referer or url}, timeout=30,
                               allow_redirects=True, **config.proxy_request_kwargs())
        status = int(getattr(response, 'status_code', 0) or 0)
        text = getattr(response, 'text', '') or ''
    except Exception as exc:
        if not real_browser.available():
            raise
        print(f'[{name}] {url}: {exc}; trying the browser', flush=True)
    if status == 200 and not real_browser.looks_blocked(status, text):
        return text
    if status and status != 200 and not real_browser.looks_blocked(status, text):
        raise Exception(f'{name} page request failed (HTTP {status})')
    if not real_browser.available():
        raise MirrorsBlockedError(url)
    print(f'[{name}] {url} is behind a check; opening it in the browser', flush=True)
    text, _media = real_browser.fetch(url, referer=referer or url)
    if not text or real_browser.looks_blocked(0, text):
        raise MirrorsBlockedError(url)
    real_browser.remember_pass(urlsplit(url).hostname or '')
    return text


def clean_title(value):
    """Unescape and drop any HTML a site leaked into the title."""
    text = str(value or '')
    for _ in range(2):
        text = html.unescape(text)
    text = text.split('<', 1)[0]           # e.g. '… </a> <a href="#" …>'
    return re.sub(r'\s+', ' ', text).strip().rstrip('.').strip()


def _height_from(label, url):
    for value in (label or '', url or ''):
        found = re.search(r'(\d{3,4})\s*p', value, re.I)
        if found:
            return int(found.group(1))
    return None


def _kvs_license_token(license_code):
    digits = str(license_code or '').replace('$', '')
    if not digits.isdigit() or len(digits) < 2:
        return None
    values = [int(c) for c in digits]
    modified = digits.replace('0', '1')
    center = len(modified) // 2
    front, back = int(modified[:center + 1]), int(modified[center:])
    modified = str(4 * abs(front - back))[:center + 1]
    try:
        return [(values[index + offset] + current) % 10
                for index, current in enumerate(map(int, modified))
                for offset in range(4)]
    except IndexError:
        return None


def decode_kvs_url(video_url, license_code):
    """Undo the KVS player's 'function/0/…' link obfuscation (hash shuffle
    keyed by the page's license_code).  '' if it cannot be decoded."""
    if not video_url.startswith('function/0/'):
        return video_url if video_url.startswith('http') else ''
    token = _kvs_license_token(license_code)
    if not token:
        return ''
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(video_url[len('function/0/'):])
    parts = parsed.path.split('/')
    if len(parts) < 4 or len(parts[3]) < 32:
        return ''
    digest = parts[3][:32]
    indices = list(range(32))
    accum = 0
    for src in reversed(range(32)):
        accum += token[src % len(token)]
        dest = (src + accum) % 32
        indices[src], indices[dest] = indices[dest], indices[src]
    parts[3] = ''.join(digest[i] for i in indices) + parts[3][32:]
    return urlunparse(parsed._replace(path='/'.join(parts)))


def extract_sources(flashvars, root, site_name='KVS'):
    """Every MP4 source KVS exposes: video_url, video_alt_url, video_alt_url2…"""
    sources = []
    for key in sorted(flashvars):
        if not re.fullmatch(r'video_(?:alt_)?url\d*', key):
            continue
        url = flashvars[key].strip()
        if not url:
            continue
        if url.startswith('function/'):
            url = decode_kvs_url(url, flashvars.get('license_code', ''))
            if not url:
                raise Exception(f'{site_name} video URL is encrypted and could not be decoded')
        if url.startswith('/'):
            url = root + url
        if not url.startswith('http'):
            continue
        label = flashvars.get(key + '_text', '')
        rank = 0 if key == 'video_url' else int(re.sub(r'\D', '', key) or 1) + 1
        sources.append({'url': url, 'label': label,
                        'height': _height_from(label, url), 'rank': rank})
    return sources


def select_source(sources, preference):
    if not sources:
        return None
    ordered = sorted(sources, key=lambda s: (s['height'] or 0, s['rank']))
    pref = str(preference or 'highest').lower()
    if pref == 'lowest':
        return ordered[0]
    if pref.isdigit():
        fitting = [s for s in ordered if s['height'] and s['height'] <= int(pref)]
        if fitting:
            return fitting[-1]
    return ordered[-1]


def _meta(text, prop):
    found = re.search(rf'<meta\s+property="og:{prop}"\s+content="([^"]+)"', text or '')
    return html.unescape(found.group(1)) if found else ''


def session_cookies(session):
    """{name: value} of a requests / curl_cffi session's cookies."""
    try:
        jar = getattr(session.cookies, 'jar', session.cookies)
        return {cookie.name: cookie.value for cookie in jar}
    except Exception:
        try:
            return dict(session.cookies)
        except Exception:
            return {}


def _url_slug(url):
    path = urlsplit(str(url or '')).path.rstrip('/')
    return path.rsplit('/', 1)[-1] if path else ''


def _looks_like_slug(value, url=''):
    """True for 'big-ass-anal' style values (URL slugs, not real titles)."""
    text = str(value or '').strip()
    if not text:
        return True
    slug = _url_slug(url)
    if slug and text.casefold() == slug.casefold():
        return True
    return ' ' not in text and bool(re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)+', text))


def slug_to_title(slug):
    """'big-ass-anal' -> 'Big Ass Anal'."""
    words = [w for w in re.split(r'[-_]+', str(slug or '')) if w]
    return ' '.join(w if w.isdigit() else w[:1].upper() + w[1:] for w in words)


def _site_suffix_re(site_name, root):
    names = {re.escape(n) for n in (site_name, (urlsplit(root).hostname or '').replace('www.', ''))
             if n}
    if not names:
        return None
    return re.compile(r'\s*[-|–—:]\s*(?:' + '|'.join(names) + r')(?:\.com)?\s*$', re.I)


def pick_title(text, url, candidates=(), site_name='', root=''):
    """The video's real title: the first non-slug candidate, else a tidied slug.

    ``candidates`` come first (e.g. flashvars video_title), then og:title,
    twitter:title, the <h1> and the <title> (minus a "- SiteName" suffix).
    """
    text = text or ''
    pool = list(candidates)
    pool.append(_meta(text, 'title'))
    found = re.search(r'<meta\s+(?:name|property)="twitter:title"\s+content="([^"]+)"', text)
    pool.append(found.group(1) if found else '')
    found = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.S | re.I)
    pool.append(re.sub(r'<[^>]+>', ' ', found.group(1)) if found else '')
    found = re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I)
    pool.append(found.group(1) if found else '')
    suffix = _site_suffix_re(site_name, root)
    for value in pool:
        title = clean_title(value)
        if suffix is not None:
            title = suffix.sub('', title).strip()
        if title and not _looks_like_slug(title, url):
            return title
    for value in pool:
        title = clean_title(value)
        if title:
            return slug_to_title(title) if _looks_like_slug(title, url) else title
    return slug_to_title(_url_slug(url))


class KvsSite(MediaSite):
    """URL download for a KVS site.  Subclasses set ROOT and NAME."""

    ROOT = ''
    NAME = 'KVS'
    # These sites throttle each connection separately, so several ranged
    # connections per video help; dropped ones are resumed, not restarted.
    direct_range_workers_max = 8
    # Video servers (get_file) of some KVS sites refuse plain Python
    # requests; download with a browser-like connection and page cookies.
    direct_browser_session = True

    def get_url_infos(self):
        self._direct_url = None
        self._direct_referer = None
        self._m3u8url = None
        home = self.ROOT + '/'
        with make_scraper() as scraper:
            text = fetch_text(scraper, self._url, home, self.NAME)
            cookies = session_cookies(scraper)
        cookies.update(real_browser.cookies_for(self._url))
        self._direct_cookies = cookies
        flashvars = parse_flashvars(text)
        if not flashvars:
            raise Exception(f'{self.NAME} player data not found (site may have changed)')
        selected = select_source(extract_sources(flashvars, self.ROOT, self.NAME),
                                 self._resolution_pref)
        if not selected:
            raise Exception(f'No MP4 source for this {self.NAME} video')
        title = pick_title(text, self._url, [flashvars.get('video_title', '')],
                           self.NAME, self.ROOT)
        if not title:
            raise Exception(f'{self.NAME} title not found')
        print(f'[{self.NAME}] title: {title}', flush=True)
        self._targetName = title
        self._imageUrl = flashvars.get('preview_url', '').strip() or _meta(text, 'image') or None
        self._direct_url = selected['url']
        self._direct_referer = self._url
        self._extra_headers = {'Referer': self._url}


class KvsBrowser:
    """Browse support for a KVS site.  Subclasses set ROOT, NAME, SECTIONS."""

    ROOT = ''
    NAME = 'KVS'
    VIDEO_PATH = r'/videos/\d+/[^/?#]+/?'   # regex for a video page path
    SECTIONS = []                 # [(label, absolute url)]
    FALLBACK_CATEGORIES = []      # slugs used if /categories/ can't be read
    _scraper = None
    _scraper_lock = None

    @classmethod
    def _get_scraper(cls):
        if cls.__dict__.get('_scraper_lock') is None:
            cls._scraper_lock = __import__('threading').Lock()
        with cls._scraper_lock:
            if cls.__dict__.get('_scraper') is None:
                cls._scraper = make_scraper()
            return cls._scraper

    @classmethod
    def _get(cls, url):
        response = cls._get_scraper().get(
            url, headers={'Referer': cls.ROOT + '/'}, timeout=30,
            allow_redirects=True, **config.proxy_request_kwargs())
        status = int(getattr(response, 'status_code', 0) or 0)
        text = getattr(response, 'text', '') or ''
        final = str(getattr(response, 'url', url))
        print(f'[{cls.NAME}] GET {url} -> HTTP {status}'
              + (f' (redirected to {final})' if final.rstrip('/') != url.rstrip('/') else ''),
              flush=True)
        if status == 404:
            return ''          # past the last page
        if status != 200 or real_browser.looks_blocked(status, text):
            # Blocked, or an error the browser may get through: let it try.
            text = fetch_text(cls._get_scraper(), url, cls.ROOT + '/', cls.NAME)
            final = url
        if cls.__dict__.get('_final_urls') is None:
            cls._final_urls = {}
        cls._final_urls[url] = final
        return text

    _final_urls = None

    @classmethod
    def _final_url(cls, url):
        return (cls.__dict__.get('_final_urls') or {}).get(url, url)

    @classmethod
    def fetch_categories(cls):
        cats = [{'name': name, 'url': url, 'count': 0} for name, url in cls.SECTIONS]
        found = []
        try:
            found = parse_categories(cls._get(cls.ROOT + '/categories/'), cls.ROOT)
        except MirrorsBlockedError:
            raise
        except Exception as exc:
            print(f'[{cls.NAME}] category list unavailable: {exc}', flush=True)
        if not found:
            found = [{'name': slug.rstrip('0123456789').replace('-', ' ').title(),
                      'url': f'{cls.ROOT}/categories/{slug}/', 'count': 0}
                     for slug in cls.FALLBACK_CATEGORIES]
        return cats + found

    @classmethod
    def fetch_page(cls, url):
        match = re.search(r'[?&]siphon_page=(\d+)', url)
        if not match:
            return parse_videos(cls._get(url), cls.ROOT, cls.VIDEO_PATH)
        base = re.sub(r'[?&]siphon_page=\d+', '', url)
        page = int(match.group(1))
        if '/search/' not in base:
            # Most listings have real /<n>/ page links; try that first.
            path_url = f'{base.split("?", 1)[0].rstrip("/")}/{page}/'
            videos = parse_videos(cls._get(path_url), cls.ROOT, cls.VIDEO_PATH)
            if videos:
                return videos
        # Search results, model pages, tags…: in-page (AJAX) pagination.
        return cls._fetch_ajax_page(base, page)

    @classmethod
    def is_video_url(cls, url):
        return bool(re.match('^' + _host_pattern(cls.ROOT) + cls.VIDEO_PATH + r'(?:[?#].*)?$',
                             url or '', re.I))

    @staticmethod
    def page_url(base_url, page):
        if page <= 1:
            return base_url
        # fetch_page() resolves this marker: /<n>/ link first, else the
        # site's in-page (AJAX) request (search results, model pages …).
        sep = '&' if '?' in base_url else '?'
        return f'{base_url}{sep}siphon_page={int(page)}'

    _ajax_cache = None

    @classmethod
    def _fetch_ajax_page(cls, base_url, page):
        """Page N of a listing whose pagination links are '#…' + data-parameters."""
        if cls.__dict__.get('_ajax_cache') is None:
            cls._ajax_cache = {}
        block = cls._ajax_cache.get(base_url)
        if block is None:
            block = parse_ajax_pagination(cls._get(base_url))
            cls._ajax_cache[base_url] = block
        if not block:
            print(f'[{cls.NAME}] no in-page pagination found on {base_url}', flush=True)
            return []
        block_id, params = block
        sort = re.search(r'[?&]sort_by=([^&]+)', base_url)
        # The block lives on the page the URL redirected to (e.g. a search
        # for a name lands on /channels/<name>/): ask that page for it.
        base_url = cls._final_url(base_url) or base_url
        query = {'mode': 'async', 'function': 'get_block', 'block_id': block_id}
        for key, value in params:
            for name in key.split('+'):
                query[name] = str(page) if value == '{page}' else value
        if sort:
            query['sort_by'] = sort.group(1)
        from urllib.parse import urlencode
        path = base_url.split('?', 1)[0]
        return parse_videos(cls._get(f'{path}?{urlencode(query)}'), cls.ROOT,
                            cls.VIDEO_PATH)

    # Sort choices for search results: (label, KVS sort_by value).
    SEARCH_SORTS = [
        ('Relevance', ''), ('Latest', 'post_date'), ('Most viewed', 'video_viewed'),
        ('Top rated', 'rating'), ('Longest', 'duration'),
    ]

    @classmethod
    def search_url(cls, query, sort=''):
        # Same form the site's own search box builds: words joined by '-'.
        words = '-'.join((query or '').split())
        url = f'{cls.ROOT}/search/{quote(words, safe="-")}/'
        if sort:
            url += f'?sort_by={quote(sort)}'
        return url

    @classmethod
    def search(cls, query, sort=''):
        return cls.fetch_page(cls.search_url(query, sort))


def parse_ajax_pagination(text):
    """(block_id, [(key, value|'{page}')]) from a KVS AJAX pagination link."""
    if not text:
        return None
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, 'html.parser')
    links = soup.select('a[data-block-id][data-parameters]')
    # Search pages also paginate models/albums; prefer the video list.
    links.sort(key=lambda a: 'video' not in a.get('data-block-id', ''))
    for link in links:
        params = link.get('data-parameters', '')
        if not re.search(r'from[\w+]*:\s*\d+', params):
            continue
        pairs = []
        for part in params.split(';'):
            if ':' not in part:
                continue
            key, value = part.split(':', 1)
            key, value = key.strip(), value.strip()
            if key.startswith('from') and value.isdigit():
                value = '{page}'
            pairs.append((key, value))
        return link['data-block-id'], pairs
    return None


def _host_pattern(root):
    host = re.sub(r'^https?://(?:www\.)?', '', root).rstrip('/')
    return r'https?://(?:www\.)?' + re.escape(host)


def parse_videos(text, root, video_path=r'/videos/\d+/[^/?#]+/?'):
    """[{'url','title','thumbnail','duration'}] from a KVS listing page."""
    if not text:
        return []
    from bs4 import BeautifulSoup
    video_re = re.compile('^' + _host_pattern(root) + video_path + '$', re.I)
    soup = BeautifulSoup(text, 'html.parser')
    videos, seen = [], set()
    for link in soup.select('a[href]'):
        href = link.get('href', '').strip()
        if href.startswith('/'):
            href = root + href
        if not video_re.match(href):
            continue
        img = link.select_one('img')
        if img is None:
            continue           # text links (breadcrumbs, "next video") are not cards
        url = href if href.endswith('/') else href + '/'
        if url in seen:
            continue
        seen.add(url)
        title = (link.get('title') or img.get('alt') or '').strip()
        if not title:
            strong = link.select_one('.title')
            title = strong.get_text(strip=True) if strong else url
        thumb = ''
        for attr in ('data-original', 'data-src', 'src', 'data-webp'):
            value = (img.get(attr) or '').strip()
            if value and not value.startswith('data:'):
                thumb = value
                break
        if thumb.startswith('//'):
            thumb = 'https:' + thumb
        elif thumb.startswith('/'):
            thumb = root + thumb
        box = link.find_parent(class_='item') or link
        dur = box.select_one('.duration')
        videos.append({'url': url, 'title': clean_title(title) or url,
                       'thumbnail': thumb,
                       'duration': dur.get_text(strip=True) if dur else ''})
    return videos


def parse_categories(text, root):
    if not text:
        return []
    from bs4 import BeautifulSoup
    cat_re = re.compile(
        '^' + _host_pattern(root) + r'/categories/([a-z0-9][a-z0-9_-]*)/?$', re.I)
    soup = BeautifulSoup(text, 'html.parser')
    cats, seen = [], set()
    for link in soup.select('a[href]'):
        href = link.get('href', '').strip()
        if href.startswith('/'):
            href = root + href
        match = cat_re.match(href)
        if not match:
            continue
        slug = match.group(1)
        if slug.isdigit():
            continue           # numeric ids duplicate the named categories
        url = f'{root}/categories/{slug}/'
        if url in seen:
            continue
        name = (link.get('title') or '').strip()
        if not name:
            title_el = link.select_one('.title, strong')
            name = (title_el.get_text(' ', strip=True) if title_el
                    else link.get_text(' ', strip=True))
        name = re.sub(r'\s+', ' ', name).strip()
        if not name or len(name) > 60:
            name = slug.replace('-', ' ').title()
        seen.add(url)
        count = 0
        count_el = link.select_one('.videos, .count')
        if count_el:
            digits = re.sub(r'\D', '', count_el.get_text())
            count = int(digits) if digits else 0
        cats.append({'name': name, 'url': url, 'count': count})
    cats.sort(key=lambda c: c['name'].casefold())
    return cats
