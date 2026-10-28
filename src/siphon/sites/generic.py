"""Generic ("add your own site") support.

Most video sites put the video file in the page in one of a handful of
well-known shapes: a KVS ``flashvars`` object, a ``<video><source>`` tag, an
``og:video`` meta tag, a player's JSON (``"file": "…"``) or an HLS playlist
address.  This module tries all of them on any page, so a site can be added
by the user from Settings without new code: the host is remembered and every
link from it is handled here afterwards.

``probe(url)`` does the same work and reports what it found; Settings uses it
to test a site before saving it.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlsplit

from siphon.core import browser as real_browser
from siphon.core import config
from siphon.sites import kvs
from siphon.sites.base import MirrorsBlockedError
from siphon.sites.site import Sitesite

# Addresses that look like a video file or an HLS playlist, in plain HTML,
# in JSON and in JavaScript (where "/" is often written "\/").
_MEDIA_RE = re.compile(
    r"""["'=(]\s*((?:https?:)?(?:\\?/){2}[^\s"'<>()]+?\.(?:m3u8|mp4|webm)"""
    r"""(?:\?[^\s"'<>()]*)?)""", re.I)
_REL_MEDIA_RE = re.compile(
    r"""["'](\\?/[^\s"'<>()]+?\.(?:m3u8|mp4|webm)(?:\?[^\s"'<>()]*)?)["']""", re.I)
_IFRAME_RE = re.compile(r'<iframe\b[^>]*\bsrc=["\']([^"\']+)["\']', re.I)
_SOURCE_RE = re.compile(r'<source\b[^>]*>', re.I)
_VIDEO_SRC_RE = re.compile(r'<video\b[^>]*\bsrc=["\']([^"\']+)["\']', re.I)
# Thumbnails and trailers that are not the video itself.
_JUNK_RE = re.compile(
    r'(?:videos?_screenshots|/screenshots?/|'
    r'(?:^|[/_.-])(?:preview|trailer|teaser|sample|sprite|thumb)s?(?:[/_.-]|$))', re.I)


# The engines tube sites are built on.  Each leaves a mark in the page, and
# knowing which one is in use says where the video and the listings are.
ENGINES = (
    # (name, what to look for, a short note for the log)
    ('kvs', re.compile(r'kt_player\.(?:js|swf)\?v=|<!--\s*KVS|/get_file/\d+/', re.I),
     'Kernel Video Sharing'),
    ('jwplayer', re.compile(r'jwplayer\s*\(|jwplayer\.js|data-video-jw-id', re.I),
     'JW Player'),
    ('videojs', re.compile(r'\bvideojs\s*\(|video-js\.(?:min\.)?js|class="[^"]*video-js',
                           re.I), 'video.js'),
    ('flowplayer', re.compile(r'flowplayer\s*\(|flowplayer\.(?:min\.)?js', re.I),
     'Flowplayer'),
    ('mechbunny', re.compile(r'mechbunny|mb_player', re.I), 'MechBunny'),
    ('clipbucket', re.compile(r'clipbucket|cb_player', re.I), 'ClipBucket'),
    ('phpmelody', re.compile(r'php\s*melody|/melody/', re.I), 'PHP Melody'),
    ('wordpress', re.compile(r'/wp-content/|/wp-includes/', re.I), 'WordPress'),
)


def detect_engine(text):
    """('kvs', 'Kernel Video Sharing') for a page, or ('', '') if unknown."""
    head = text or ''
    for name, pattern, label in ENGINES:
        if pattern.search(head):
            return name, label
    return '', ''


_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', re.I)
_SCRIPT_SRC_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.I)


def page_address(text):
    """The address a saved page says it came from (canonical link / og:url)."""
    for pattern in (r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
                    r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)',
                    r'<base[^>]+href=["\']([^"\']+)'):
        found = re.search(pattern, text or '', re.I)
        if found:
            url = html.unescape(found.group(1)).strip()
            if url.startswith('http'):
                return url
    return ''


def page_site(text):
    """Which site a saved page belongs to, read from the page itself.

    Its own address if it says one, otherwise the host its links point at
    most often — a page saved from the browser keeps those absolute.
    """
    address = page_address(text)
    if address:
        return '{0.scheme}://{0.netloc}'.format(urlsplit(address))
    counts = {}
    for match in re.finditer(r'(?:href|src)=["\'](https?://([^/"\'?#]+))', text or ''):
        host = match.group(2).lower()
        if host and '.' in host:
            counts[match.group(1).rsplit(host, 1)[0] + host] = counts.get(
                match.group(1).rsplit(host, 1)[0] + host, 0) + 1
    if not counts:
        return ''
    return max(counts.items(), key=lambda item: item[1])[0]


def page_markers(text):
    """Fingerprints that say which builder a page came from.

    A site builder ships the same player script and the same "generator" note
    on every site it makes, so these are what recognises the next site built
    the same way.
    """
    markers = []
    generator = _GENERATOR_RE.search(text or '')
    if generator:
        markers.append('generator:' + generator.group(1).strip()[:60])
    for src in _SCRIPT_SRC_RE.findall(text or '')[:60]:
        name = re.sub(r'[?#].*$', '', src).rsplit('/', 1)[-1].lower()
        if re.search(r'player|kt_|tube|engine', name) and name.endswith('.js'):
            marker = 'script:' + name
            if marker not in markers:
                markers.append(marker)
    engine, _label = detect_engine(text)
    if engine:
        markers.append('engine:' + engine)
    return markers[:8]


def match_template(text, templates):
    """The learned layout whose markers this page carries (None if new)."""
    markers = set(page_markers(text))
    if not markers:
        return None
    best, score = None, 0
    for template in templates or ():
        hits = len(markers & set(template.get('markers') or ()))
        # 'engine:kvs' alone is weak; a shared player script is strong.
        strong = any(m.startswith(('script:', 'generator:'))
                     for m in markers & set(template.get('markers') or ()))
        if hits > score and (strong or hits > 1):
            best, score = template, hits
    return best


def _jsonld_sources(text):
    """Video addresses a page declares in its schema.org data."""
    found = []
    for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            text or '', re.S | re.I):
        for match in re.finditer(r'"(?:contentUrl|embedUrl)"\s*:\s*"([^"]+)"', block):
            found.append(match.group(1))
    return found


def _attr(tag, name):
    found = re.search(rf'\b{name}=["\']([^"\']*)["\']', tag, re.I)
    return html.unescape(found.group(1)) if found else ''


def _clean(url, page_url):
    """Absolute address from whatever spelling the page used."""
    text = html.unescape(str(url or '')).replace('\\/', '/').replace('\\u002F', '/').strip()
    if not text or text.startswith('data:'):
        return ''
    if text.startswith('//'):
        text = urlsplit(page_url).scheme + ':' + text
    elif not text.startswith('http'):
        text = urljoin(page_url, text)
    return text if text.startswith('http') else ''


def _add(found, url, label, page_url, tier):
    """Keep one playable address.

    ``tier`` says how trustworthy the find is (0 = the page's own player
    settings, higher = a looser match).  Sources are ranked so that, between
    two of the same quality, the most trustworthy and earliest one wins —
    pages also list the files of their "related videos".
    """
    url = _clean(url, page_url)
    if not url or url in {s['url'] for s in found} or _JUNK_RE.search(url):
        return
    if len(found) >= 60:
        return
    kind = 'hls' if '.m3u8' in url.lower() else 'direct'
    found.append({'url': url, 'label': label or '', 'kind': kind,
                  'height': kvs._height_from(label, url),
                  'rank': -(tier * 1000 + len(found))})


def find_sources(text, page_url):
    """Every playable address the page offers, best quality last."""
    text = text or ''
    found = []

    flashvars = kvs.parse_flashvars(text)
    if flashvars:
        root = '{0.scheme}://{0.netloc}'.format(urlsplit(page_url))
        try:
            for source in kvs.extract_sources(flashvars, root, 'Site'):
                _add(found, source['url'], source.get('label'), page_url, 0)
        except Exception as exc:                      # encrypted and undecodable
            print(f'[Site] KVS sources unusable: {exc}', flush=True)

    for index, tag in enumerate(_SOURCE_RE.findall(text)):
        _add(found, _attr(tag, 'src'), _attr(tag, 'title') or _attr(tag, 'label') or
             _attr(tag, 'res') or _attr(tag, 'size'), page_url, 1)
    for src in _VIDEO_SRC_RE.findall(text):
        _add(found, src, '', page_url, 1)

    for index, url in enumerate(_jsonld_sources(text)):
        _add(found, url, '', page_url, 2 + index * 0)

    for prop in ('video:secure_url', 'video:url', 'video'):
        meta = re.search(rf'<meta[^>]+(?:property|name)=["\']og:{re.escape(prop)}["\']'
                         rf'[^>]+content=["\']([^"\']+)["\']', text, re.I)
        if meta:
            _add(found, meta.group(1), '', page_url, 2)

    # Player settings: "file": "…", sources:[{src:"…"}], contentUrl, videoUrl…
    for match in _MEDIA_RE.finditer(text):
        _add(found, match.group(1), '', page_url, 3)
    for match in _REL_MEDIA_RE.finditer(text):
        _add(found, match.group(1), '', page_url, 4)

    # A page that lists other videos too: the file whose address carries this
    # page's own video number is certainly the right one.
    page_ids = set(re.findall(r'\d{4,}', urlsplit(page_url).path))
    if page_ids:
        for source in found:
            if page_ids & set(re.findall(r'\d{4,}', urlsplit(source['url']).path)):
                source['rank'] += 100000

    # Best last, matching kvs.select_source.
    found.sort(key=lambda s: (s['height'] or 0, s['rank']))
    return found


def iframe_urls(text, page_url):
    """Embedded players worth following when the page itself has no video."""
    urls = []
    for src in _IFRAME_RE.findall(text or ''):
        url = _clean(src, page_url)
        if not url or url in urls:
            continue
        if re.search(r'(?:youtube|facebook|twitter|google|doubleclick|disqus|'
                     r'recaptcha|adserver|exoclick|juicyads)', url, re.I):
            continue
        urls.append(url)
    return urls[:3]


def add_media(found, media, page_url):
    """Addresses the player itself asked for while the page loaded: the most
    reliable find there is, so they outrank anything read out of the HTML."""
    for url in media or ():
        if not _JUNK_RE.search(url):
            _add(found, url, '', page_url, -1)
    found.sort(key=lambda s: (s['height'] or 0, s['rank']))
    return found


def _fetch(scraper, url, referer, allow_browser=True, want_media=False):
    """(page text, addresses its player asked for).

    The quick way first; when the site answers with a Cloudflare check — or
    when the page needs JavaScript to show its video — the page is opened in a
    real browser instead.
    """
    status, text = 0, ''
    if not want_media:
        try:
            response = scraper.get(url, headers={'Referer': referer}, timeout=30,
                                   allow_redirects=True, **config.proxy_request_kwargs())
            status = int(getattr(response, 'status_code', 0) or 0)
            text = getattr(response, 'text', '') or ''
        except Exception as exc:
            if not allow_browser or not real_browser.available():
                raise
            print(f'[Site] {url}: {exc}; trying the browser', flush=True)
        if status == 200 and not real_browser.looks_blocked(status, text):
            return text, []
    if not allow_browser or not real_browser.available():
        if real_browser.looks_blocked(status, text):
            raise MirrorsBlockedError(url)
        raise Exception(f'Page request failed (HTTP {status})')
    if status:
        print(f'[Site] {url}: HTTP {status} / blocked; opening it in the browser',
              flush=True)
    text, media = real_browser.fetch(url, referer=referer)
    if real_browser.looks_blocked(0, text) or not text:
        raise MirrorsBlockedError(url)
    real_browser.remember_pass(urlsplit(url).hostname or '')
    return text, media


def collect(url, scraper):
    """(sources, page text, address they were found on) for a video page.

    The page is searched first; when it holds no video, embedded players are
    opened and searched the same way (one level), and finally the page is
    watched in a real browser to see what its player loads.
    """
    home = '{0.scheme}://{0.netloc}/'.format(urlsplit(url))
    text, media = _fetch(scraper, url, home)
    sources = add_media(find_sources(text, url), media, url)
    if sources:
        return sources, text, url
    for frame in iframe_urls(text, url):
        try:
            frame_text, frame_media = _fetch(scraper, frame, url)
        except Exception as exc:
            print(f'[Site] embed {frame} failed: {exc}', flush=True)
            continue
        frame_sources = add_media(find_sources(frame_text, frame), frame_media, frame)
        if frame_sources:
            print(f'[Site] source found in embed: {frame}', flush=True)
            return frame_sources, text, frame
        for inner in iframe_urls(frame_text, frame):
            try:
                inner_text, inner_media = _fetch(scraper, inner, frame)
            except Exception:
                continue
            inner_sources = add_media(find_sources(inner_text, inner), inner_media, inner)
            if inner_sources:
                return inner_sources, text, inner
    if real_browser.available():
        # Players that build themselves with JavaScript: watch what the page
        # actually loads.
        print('[Site] nothing in the page; watching it play in the browser',
              flush=True)
        try:
            watched, media = _fetch(scraper, url, home, want_media=True)
        except Exception as exc:
            print(f'[Site] browser attempt failed: {exc}', flush=True)
            return [], text, url
        sources = add_media(find_sources(watched, url), media, url)
        if sources:
            return sources, watched or text, url
    return [], text, url


def _is_connect_error(exc):
    """A failure to reach the site at all, rather than a page that said no."""
    return bool(re.search(r'ssl|tls|connect|timed out|timeout|resolve|refused|'
                          r'unreachable|handshake|wrong_version',
                          str(exc), re.I))


def normalize_site_url(text):
    """What the user typed, as an address: 'example.com' -> 'https://example.com/'."""
    value = str(text or '').strip().strip('"\'')
    if not value:
        return ''
    if not re.match(r'^[a-z][a-z0-9+.-]*://', value, re.I):
        value = 'https://' + value.lstrip('/')
    parts = urlsplit(value)
    if not parts.hostname or '.' not in parts.hostname:
        return ''
    return value if parts.path or parts.query else value.rstrip('/') + '/'


def learn_from_html(text, page_url, listing_text='', listing_url=''):
    """What a saved page teaches about a site.

    Used when a site cannot be opened from here (sign-in, region block, a
    check the browser must pass): the user saves the page from their own
    browser and this reads the same things out of the file.
    """
    from siphon.sites import genericbrowse
    engine, label = detect_engine(text)
    sources = find_sources(text, page_url)
    root = '{0.scheme}://{0.netloc}'.format(urlsplit(page_url or listing_url or ''))
    profile = {'engine': engine, 'root': root}
    if page_url:
        profile['video_shape'] = genericbrowse._shape(urlsplit(page_url).path)
    listing = listing_text or text
    listing_at = listing_url or page_url or (root + '/')
    search = genericbrowse.detect_search(listing, root)
    if search:
        profile['search'] = search
    form = genericbrowse.detect_page_form(listing, listing_at)
    if form:
        profile['page_form'] = form
    if listing_text:
        shape = genericbrowse.detect_video_shape(listing_text, root)
        if shape:
            profile['video_shape'] = shape
    # The same layout on another site: its own address, not this one's.
    template = {key: value for key, value in profile.items()
                if key in ('video_shape', 'page_form', 'search')}
    if template.get('search') and root:
        template['search'] = template['search'].replace(root.rstrip('/'), '{root}')
    return {'engine': engine, 'engine_label': label,
            'markers': page_markers(text),
            'template': template,
            'sources': len(sources),
            'kind': ('HLS' if sources[-1]['kind'] == 'hls' else 'MP4') if sources else '',
            'title': kvs.pick_title(text, page_url, (), '', ''),
            'categories': len(genericbrowse.detect_categories(listing, root)),
            'videos_listed': len(genericbrowse.parse_videos(listing, root)),
            'profile': {k: v for k, v in profile.items() if v}}


# A title sits near the top of a page, so the rest is never downloaded: 43
# queued rows then cost a fraction of a full page each.  Reading used to stop
# at the first </h1>, which on a site whose first heading is a notice ("New
# Backup Domain: ...") named every video after the notice; it now reads on to
# the heading the player itself carries.
_TITLE_STOP = re.compile(rb'</(?:body|html)>', re.I)
_TITLE_CAP = 256 * 1024

# The heading next to the player: an <h1> inside a box whose class or id says
# it belongs to the video, rather than the first <h1> on the page.
_PLAYER_HEADING = re.compile(
    r'''<[^>]+\b(?:class|id)="[^"]*\b\w*(?:title|player|detail|video)\w*\b[^"]*"'''
    r'''[^>]*>\s*(?:<[^/h][^>]*>\s*)*<h1[^>]*>(.*?)</h1>''', re.S | re.I)


def _title_from(text, url):
    host = (urlsplit(url).hostname or '').replace('www.', '')
    found = _PLAYER_HEADING.search(text)
    candidates = ([re.sub(r'<[^>]+>', ' ', found.group(1))] if found else [])
    title = kvs.pick_title(text, url, candidates, host, f'https://{host}')
    return title if title and not kvs._looks_like_slug(title, url) else ''


def page_title(url, timeout=12):
    """The video's title, read from its page ('' if it cannot be read).

    Deliberately quick and cheap: this only labels a row in the queue, so it
    re-uses one connection per thread, stops reading as soon as the title has
    arrived, and never opens the browser.
    """
    try:
        from siphon.sites.base import _get_cffi_session, _use_cffi as _cffi_ok
        session = _get_cffi_session() if _cffi_ok else kvs.make_scraper()
        response = session.get(
            url, headers={'Referer': '{0.scheme}://{0.netloc}/'.format(urlsplit(url))},
            timeout=timeout, allow_redirects=True, stream=True,
            **config.proxy_request_kwargs())
        if int(getattr(response, 'status_code', 0) or 0) != 200:
            return ''
        head = b''
        try:
            for chunk in response.iter_content(chunk_size=16384):
                head += chunk
                if _TITLE_STOP.search(head) or len(head) >= _TITLE_CAP:
                    break
        finally:
            try:
                response.close()
            except Exception:
                pass
        text = head.decode('utf-8', 'replace')
    except Exception:
        return ''
    if real_browser.looks_blocked(200, text):
        return ''
    return _title_from(text, url)


def probe(url):
    """Test what the user typed in the Settings "add a site" box.

    A video page is checked directly.  A site's front page works too: the
    first videos listed on it are opened and tried instead.

    Returns {'title', 'host', 'count', 'kind', 'via'}; raises with the reason
    when no video can be found.
    """
    typed = str(url or '').strip()
    url = normalize_site_url(typed)
    host = (urlsplit(url).hostname or '').lower()
    if not url or not host:
        raise ValueError('not a web address')
    root = '{0.scheme}://{0.netloc}'.format(urlsplit(url))
    with kvs.make_scraper() as scraper:
        try:
            sources, text, _found_on = collect(url, scraper)
        except Exception as exc:
            # https was our own guess: a site that only answers on http
            # should still work.
            if re.match(r'^[a-z][a-z0-9+.-]*://', typed, re.I) or not _is_connect_error(exc):
                raise
            url = 'http://' + url.split('://', 1)[1]
            root = '{0.scheme}://{0.netloc}'.format(urlsplit(url))
            print(f'[Site] https did not answer; trying {url}', flush=True)
            sources, text, _found_on = collect(url, scraper)
        tried = url
        if not sources:
            # Not a video page: take the site's own listing and try its videos.
            from siphon.sites import genericbrowse
            listed = genericbrowse.parse_videos(text, root)
            if listed:
                print(f'[Site] {len(listed)} videos listed here; '
                      'trying the first few', flush=True)
            for video in listed[:3]:
                try:
                    sources, text, _found_on = collect(video['url'], scraper)
                except Exception as exc:
                    print(f'[Site] {video["url"]}: {exc}', flush=True)
                    continue
                if sources:
                    tried = video['url']
                    break
    if not sources:
        raise Exception('no video found on this page')
    best = sources[-1]
    engine, engine_label = detect_engine(text)
    return {'engine': engine, 'engine_label': engine_label,
            'title': kvs.pick_title(text, tried, (), '', ''),
            'host': re.sub(r'^www\.', '', host),
            'count': len(sources),
            'via': tried,
            'root': root,
            'kind': 'HLS' if best['kind'] == 'hls' else 'MP4'}


class SiteGeneric(Sitesite):
    """Download from a site the user added themselves."""

    direct_site_name = 'Site'
    direct_range_workers_max = 8
    direct_browser_session = True
    website_pattern = r'(?!)x'            # never matched; validate_url decides
    website_dirname_pattern = r'(?!)x'

    @classmethod
    def validate_url(cls, url):
        host = (urlsplit(str(url or '')).hostname or '').lower()
        if not host or not str(url or '').startswith('http'):
            return None
        return host if config.is_custom_site(host) else None

    def get_url_infos(self):
        self._direct_url = None
        self._direct_referer = None
        self._m3u8url = None
        self._hls_sources = []
        host = re.sub(r'^www\.', '', urlsplit(self._url).hostname or '')
        name = config.custom_site_name(host) or host or 'Site'
        self.direct_site_name = name
        with kvs.make_scraper() as scraper:
            sources, text, found_on = collect(self._url, scraper)
            cookies = kvs.session_cookies(scraper)
        # When the page came from the browser, the video server expects the
        # browser's cookies too (Cloudflare, one-use tokens).
        cookies.update(real_browser.cookies_for(self._url))
        self._direct_cookies = cookies
        if not sources:
            raise Exception(f'{name}: no video found on this page '
                            '(the site may have changed)')
        headers = {'Referer': found_on}
        # Same reading as the queue uses, so the row and the saved file agree
        # and a site-wide notice does not become the name.
        title = _title_from(text, self._url) or kvs.pick_title(
            text, self._url, (), name, f'https://{host}')
        print(f'[{name}] title: {title}', flush=True)
        self._targetName = title
        self._imageUrl = kvs._meta(text, 'image') or None
        self._extra_headers = headers

        selected = kvs.select_source([s for s in sources if s['kind'] == 'direct'],
                                     self._resolution_pref)
        if selected:
            self._direct_url = selected['url']
            self._direct_referer = found_on
        # HLS playlists are tried first (they carry every quality); a plain
        # MP4 found alongside them is the fallback.
        self._hls_sources = [(f'{name} HLS', s['url'], headers)
                             for s in reversed(sources) if s['kind'] == 'hls'][:3]
        if self._hls_sources:
            self._m3u8url = self._hls_sources[0][1]
        if not self._direct_url and not self._hls_sources:
            raise Exception(f'{name}: no playable video source on this page')
