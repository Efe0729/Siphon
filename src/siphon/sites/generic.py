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
from urllib.parse import urljoin, urlsplit, urlunsplit

from siphon.core import browser as real_browser
from siphon.core import config
from siphon.sites import kvs
from siphon.sites.base import MirrorsBlockedError
from siphon.sites.downloader import MediaSite

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


def _tag_values(text, tag, key_attr, keys, value_attr):
    """The ``value_attr`` of every ``<tag>`` whose ``key_attr`` is one of
    ``keys``, whichever order the attributes come in."""
    found = []
    for match in re.finditer(rf'<{tag}\b[^>]*>', text or '', re.I):
        piece = match.group(0)
        key = re.search(rf'\b{key_attr}\s*=\s*["\']?([^"\'\s>]+)', piece, re.I)
        value = re.search(rf'\b{value_attr}\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))',
                          piece, re.I)
        if key and value and key.group(1).lower() in keys:
            found.append(html.unescape(
                next(g for g in value.groups() if g is not None)).strip())
    return found


def page_address(text):
    """The address a saved page says it came from (canonical link, og:url,
    twitter:url), whichever order the tag spells its attributes in."""
    candidates = (
        _tag_values(text, 'link', 'rel', ('canonical',), 'href')
        + _tag_values(text, 'meta', 'property', ('og:url',), 'content')
        + _tag_values(text, 'meta', 'name', ('twitter:url',), 'content')
        + _tag_values(text, 'meta', 'property', ('twitter:url',), 'content')
        + _tag_values(text, 'base', 'href', (), 'href'))
    base = re.search(r'<base\b[^>]*\bhref\s*=\s*["\']([^"\']+)', text or '', re.I)
    if base:
        candidates.append(html.unescape(base.group(1)).strip())
    for url in candidates:
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


class SiteUnreachableError(Exception):
    """The site was never reached: the network blocked or redirected us.

    Worth a name of its own because what comes back in this case is not the
    site's page, so looking for a video in it finds none — and reporting
    "no video on this page" sends the user looking at the site and at Siphon
    when the fault is in neither.
    """


_INTERCEPTED = re.compile(
    # A certificate for some name other than the one asked for, or the site's
    # name resolving to the machine itself: something on the way answered in
    # the site's place.  Blocked DNS and filters both look like this.
    r'localhost\.localdomain|certificate|hostname mismatch|'
    r'ssl|tls|handshake|wrong_version|'
    # Or nothing answered at all.
    r'name or service not known|could not resolve|getaddrinfo|'
    r'name resolution|nodename nor servname|'
    r'connection refused|network is unreachable|no route to host',
    re.I)


def _network_lied(exc):
    """Whether this failure means the site itself was never reached."""
    return bool(_INTERCEPTED.search(str(exc)))


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
            if _network_lied(exc):
                # The browser sits on this same network and would be told the
                # same thing, slowly.  Say it now rather than opening it.
                host = urlsplit(url).hostname or url
                raise SiteUnreachableError(
                    f'{host} could not be reached from this connection — it '
                    f'looks blocked by the network or by DNS ({exc})') from exc
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


def _note_site_trouble(url, reason):
    """Tell the health watch that a video of this site could not be read.

    Imported here rather than at the top because health reads this module
    back when it relearns a site.
    """
    try:
        from siphon.sites import health
        if health.note_failure(url, reason):
            health.heal_in_background(url)
    except Exception as exc:      # never let watching break a download
        print(f'[health] could not be noted: {exc}', flush=True)


def _note_site_well(url):
    try:
        from siphon.sites import health
        health.note_success(url)
    except Exception:
        pass


def _is_connect_error(exc):
    """A failure to reach the site at all, rather than a page that said no."""
    if isinstance(exc, SiteUnreachableError):
        # Still worth retrying on http: a site that answers only there also
        # fails its https handshake, which reads as interception.
        return True
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


def learn_from_html(text, page_url, listing_text='', listing_url='',
                    page_known=True):
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
    # The shape of a real video page's own address is the one thing about
    # the site that is certain, so it is marked as proved: Browse then keeps
    # it instead of re-guessing from a home page of category tiles.
    if page_url and page_known and sources:
        shape = genericbrowse._shape(urlsplit(page_url).path)
        # The last part of a video's address is its own name.  A short, plain
        # one ("/video-abc/my_clip") is read as a fixed word and would match
        # no other video, so it is generalised.
        parts = shape.strip('/').split('/')
        if len(parts) > 1 and parts[-1] not in ('#', '*'):
            parts[-1] = '*'
            shape = '/' + '/'.join(parts)
        profile['video_shape'] = shape
        profile['video_shape_ok'] = '1'
    listing = listing_text or text
    listing_at = listing_url or page_url or (root + '/')
    search = genericbrowse.detect_search(listing, root)
    if search:
        profile['search'] = search
    form = genericbrowse.detect_page_form(listing, listing_at)
    if form:
        profile['page_form'] = form
    if listing_text and not profile.get('video_shape_ok'):
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
            'videos_listed': len(genericbrowse.parse_videos(
                listing, root, profile.get('video_shape', ''),
                bool(profile.get('video_shape_ok')))),
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


# Every place a video's name can sit on a page, best-looking first.  Naming
# them lets a site be asked which one actually works there, instead of this
# order being a guess re-made on every page.
def _rule_player_heading(text):
    found = _PLAYER_HEADING.search(text)
    return re.sub(r'<[^>]+>', ' ', found.group(1)) if found else ''


def _rule_og_title(text):
    return kvs._meta(text, 'title')


def _rule_twitter_title(text):
    found = re.search(
        r'<meta\s+(?:name|property)="twitter:title"\s+content="([^"]+)"', text)
    return found.group(1) if found else ''


def _rule_first_h1(text):
    found = re.search(r'<h1[^>]*>(.*?)</h1>', text, re.S | re.I)
    return re.sub(r'<[^>]+>', ' ', found.group(1)) if found else ''


def _rule_title_tag(text):
    found = re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I)
    return found.group(1) if found else ''


TITLE_RULES = {
    'player_heading': _rule_player_heading,
    'og_title': _rule_og_title,
    'twitter_title': _rule_twitter_title,
    'first_h1': _rule_first_h1,
    'title_tag': _rule_title_tag,
}
TITLE_RULE_ORDER = ('player_heading', 'og_title', 'twitter_title',
                    'first_h1', 'title_tag')


def rule_order():
    """The title rules, most-often-right first.

    Each site's own answer is kept against that site and never copied to
    another.  What is shared is only this ordering: a rule confirmed on seven
    sites is tried before one confirmed on three.  So one site's experience
    makes the next site quicker to read without ever deciding for it — a
    wrong guess here costs nothing, because every candidate is still checked
    against the site's own listing before it is believed.

    The built-in order breaks ties, so a fresh install behaves as before.
    """
    try:
        wins = config.rule_wins()
    except Exception:
        wins = {}
    if not wins:
        return TITLE_RULE_ORDER
    return tuple(sorted(TITLE_RULE_ORDER,
                        key=lambda name: (-int(wins.get(name, 0)),
                                          TITLE_RULE_ORDER.index(name))))


def title_candidates(text, url):
    """{rule name: the title that rule finds here}, cleaned, blanks dropped."""
    host = (urlsplit(url).hostname or '').replace('www.', '')
    suffix = kvs._site_suffix_re(host, f'https://{host}')
    found = {}
    for name in TITLE_RULE_ORDER:
        value = kvs.clean_title(TITLE_RULES[name](text) or '')
        if suffix is not None:
            value = suffix.sub('', value).strip()
        if value and not kvs._looks_like_slug(value, url):
            found[name] = value
    return found


def _same_title(left, right):
    """Two titles that differ only in spacing, case or punctuation."""
    squash = lambda value: re.sub(r'[^a-z0-9]+', '', str(value or '').lower())
    left, right = squash(left), squash(right)
    if not left or not right:
        return False
    return left == right or left.startswith(right) or right.startswith(left)


def learn_title_rule(pages, listed_titles=()):
    """Which of the title rules actually names a video on this site.

    ``pages`` are (page_text, page_url) for a few of the site's videos and
    ``listed_titles`` the names its own listing gave those same videos.  The
    listing already knows the answer, so the rules are not ranked by taste:
    the one that reproduces it wins.

    A rule that returns the same text for every video is reading something
    the site prints on every page — a backup-domain notice, the site's own
    name — and is refused however good it looks.

    Returns (rule name, reason) with an empty name when none can be trusted.
    """
    pages = [(text, url) for text, url in pages if text]
    if not pages:
        return '', 'no page could be read'
    seen = [title_candidates(text, url) for text, url in pages]
    titles = list(listed_titles) + [''] * len(pages)

    order = rule_order()
    repeated = set()
    if len(pages) > 1:
        for name in order:
            values = [found.get(name, '') for found in seen]
            if all(values) and all(_same_title(values[0], v) for v in values[1:]):
                repeated.add(name)

    for name in order:
        if name in repeated:
            continue
        agree = sum(1 for found, listed in zip(seen, titles)
                    if listed and _same_title(found.get(name, ''), listed))
        if agree:
            return name, f'matches the listing on {agree} of {len(pages)}'
    for name in order:
        if name not in repeated and any(found.get(name) for found in seen):
            return name, 'the first rule that gives a different name per video'
    if repeated:
        return '', 'every heading is the same on all of them'
    return '', 'no heading found'


def _title_from(text, url, rule=''):
    """The video's name; ``rule`` is the one this site was found to use."""
    found = title_candidates(text, url)
    if rule and found.get(rule):
        return found[rule]
    for name in rule_order():
        if found.get(name):
            return found[name]
    return ''


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
    return _title_from(text, url, _learned_rule(url))


def _learned_rule(url):
    """The title rule this site was found to use when it was added."""
    host = (urlsplit(url).hostname or '').lower()
    return config.custom_site_rules(host).get('title_rule', '')


def _plain_page(url, scraper):
    """A page's HTML, without hunting for a video in it.

    collect() is for video pages: when it finds none it opens the off-screen
    browser to watch the player build itself.  Looking for a search address
    or a listing wants none of that — the browser would be started once per
    address tried, which turned adding a site into minutes of waiting.
    """
    text, _media = _fetch(scraper, url, '{0.scheme}://{0.netloc}/'.format(
        urlsplit(url)), allow_browser=False)
    return text


def _same_videos(left, right):
    """Two listings showing the same videos, whatever order they are in."""
    first = {video['url'] for video in left}
    second = {video['url'] for video in right}
    if not first or not second:
        return False
    overlap = len(first & second) / max(len(first), len(second))
    return overlap >= 0.8


# The address shapes sites actually use for searching.  The one in the
# site's own search box is tried first; these are what is tried when it has
# none, or when the one it has turns out not to search.
_SEARCH_SHAPES = (
    '{root}/search/{query}/',
    '{root}/search?q={query}',
    '{root}/search/video?q={query}',
    '{root}/search/all?q={query}',
    '{root}/?s={query}',
    '{root}/search/?q={query}',
    '{root}/video/search?search={query}',
    '{root}/tags/{query}/',
    '{root}/?q={query}',
)


def search_template_from(url):
    """Turn a search address the user pasted into a reusable one.

    They searched for a word on the site and copied the address, so that
    word is somewhere in it.  Whichever part is the word becomes {query} and
    the rest is kept exactly as the site wrote it, which is safer than
    guessing the shape from the site's markup.
    """
    from urllib.parse import parse_qsl, unquote, urlencode
    parts = urlsplit(str(url or '').strip())
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        return ''
    # the word in a query parameter: ?q=word, ?s=word, ?search=word
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    for index, (name, value) in enumerate(pairs):
        if value and not value.isdigit() and len(value) >= 2:
            spelled = list(pairs)
            spelled[index] = (name, '{query}')
            query = urlencode(spelled, safe='{}')
            return urlunsplit((parts.scheme, parts.netloc, parts.path,
                               query, ''))
    # the word as the last part of the path: /search/word/
    pieces = [piece for piece in parts.path.split('/') if piece]
    for index in range(len(pieces) - 1, -1, -1):
        word = unquote(pieces[index])
        if len(word) >= 2 and not word.isdigit() and '.' not in word:
            pieces[index] = '{query}'
            path = '/' + '/'.join(pieces) + ('/' if parts.path.endswith('/') else '')
            return urlunsplit((parts.scheme, parts.netloc, path, '', ''))
    return ''


def _probe_words(listed, want=2):
    """A couple of words taken from the site's own video titles.

    Searching for a word the site itself used is what makes the answer
    checkable: those words must come back in the results.  A made-up word
    would prove nothing, because an empty result and a broken search look
    alike.
    """
    counts = {}
    for video in listed:
        for word in re.findall(r"[A-Za-z]{5,}", str(video.get('title') or '')):
            word = word.lower()
            counts[word] = counts.get(word, 0) + 1
    # a word that is on nearly every card is the site's own furniture
    ceiling = max(2, len(listed) // 2)
    words = [w for w, n in sorted(counts.items(), key=lambda kv: -kv[1])
             if n <= ceiling]
    return words[:want]


# ── what the log says ──────────────────────────────────────────────────
# The log is the only thing a person has when a site is read wrongly, and
# it is read by three sorts of reader: whoever added the site, whoever gets
# the report, and whoever opens this file a year from now.  So each step
# says what it tried, what came back, and why that was enough or not —
# never a bare address with a number after it.

def _say(line, mark=''):
    """One log line.  ``mark`` is '>' for a step, '+' kept, '-' rejected."""
    lead = {'>': '', '+': '   OK   ', '-': '   no   ', '.': '        '}.get(mark, '')
    print(f'[Site] {lead}{line}', flush=True)


def _step(number, total, what):
    _say(f'step {number}/{total}  {what}', '>')


def _safe(url):
    """An address the app worked out itself, kept whole in the log file."""
    try:
        from siphon.core import applog
        return applog.keep(str(url))
    except Exception:
        return str(url)


def _search_answers(url, word, listed, root, scraper):
    """(videos, True) when this address really answered that word."""
    from siphon.sites import genericbrowse
    try:
        videos = genericbrowse.parse_videos(_plain_page(url, scraper), root)
    except Exception as exc:
        _say(f'{_safe(url)} - the site did not answer ({exc})', '-')
        return [], False
    if not videos:
        _say(f'{_safe(url)} - answered, but there are no videos on the page', '-')
        return [], False
    if _same_videos(videos, listed):
        _say(f'{_safe(url)} - gave back the front page, so the site does not '
             'know this address', '-')
        return videos, False
    # Sites search their tags and descriptions too, not only titles, so a
    # real search often shows the word in only a handful of the names it
    # returns.  A page that is not searching at all shows it in none.
    hits = sum(1 for video in videos
               if word in str(video.get('title') or '').lower())
    verdict = '+' if hits >= 2 else '-'
    _say(f'{_safe(url)} - {len(videos)} videos back, {hits} of their names '
         f'contain "{word}"' + ('' if hits >= 2 else
                                ' (too few: a page that is not searching '
                                'looks like this)'), verdict)
    return videos, hits >= 2


def _working_search(listing_text, root, scraper):
    """The site's search address, found by trying and checking.

    Sites answer an address they do not know with their front page, or with
    a page of categories, so "something came back" proves nothing.  Each
    candidate is asked for a word taken from the site's own video titles and
    is believed only when that word comes back in what it returns.

    Every candidate tried is printed, so a site that still cannot be searched
    can be read out of the log rather than guessed at.
    """
    from siphon.sites import genericbrowse
    from urllib.parse import quote
    listed = genericbrowse.parse_videos(listing_text, root)
    words = _probe_words(listed)
    if not words:
        _say('no word on this page is rare enough to search for, so the '
             'search address cannot be checked', '-')
        return ''

    candidates = []
    try:
        found = genericbrowse.detect_search(listing_text, root)
        if found:
            candidates.append(found)
    except Exception as exc:
        _say(f'the page has no search box this reader can use ({exc})', '.')
    base = root.rstrip('/')
    candidates += [shape.replace('{root}', base) for shape in _SEARCH_SHAPES]

    tried = len(list(dict.fromkeys(candidates)))
    _say(f'testing {tried} possible search addresses with the word '
         f'"{words[0]}", taken off this site\'s own listing', '.')
    _say('an address counts only if the word comes back in the names it '
         'returns; a site that does not know the address answers with its '
         'front page instead', '.')
    for template in dict.fromkeys(candidates):
        videos, answered = _search_answers(
            template.replace('{query}', quote(words[0])), words[0],
            listed, root, scraper)
        if not answered:
            continue
        # One word could be luck; a real search gives a different answer to a
        # different word.
        if len(words) > 1:
            other, _ok = _search_answers(
                template.replace('{query}', quote(words[1])), words[1],
                listed, root, scraper)
            if _same_videos(videos, other):
                _say(f'{_safe(template)} - gives the same videos for '
                     f'"{words[0]}" and "{words[1]}", so it is showing a '
                     'fixed page, not searching', '-')
                continue
        _say(f'search works: {_safe(template)}', '+')
        return template
    _say('none of the addresses searched. The search box will stay off for '
         'this site; its search is probably built by JavaScript, which has '
         'no address to ask for.', '-')
    return ''


# A listing that reads as a handful of things is usually not a listing.  On
# some portals the reader picked up three category tiles — "Music", "Gaming",
# and a video count — and called the site added, which is worse
# than failing: the person is told it worked and finds out later.
_FEW_VIDEOS = 5


def listing_looks_wrong(listed, categories=()):
    """A short code for why this listing should not be trusted, or ''.

    A code rather than a sentence: the interface says it in the person's own
    language and the report says it in English, and neither should have to
    unpick prose written by the other.  'too_few:3' carries its number.
    """
    names = [str(v.get('title') or '').strip().lower() for v in listed]
    if not listed:
        return ''                       # already reported as no listing
    if len(listed) < _FEW_VIDEOS:
        return f'too_few:{len(listed)}'
    known = {str(c.get('name') or '').strip().lower()
             for c in (categories or ())}
    shared = [n for n in names if n and n in known]
    if len(shared) >= max(2, len(names) // 2):
        return 'categories'
    numbers = [n for n in names if re.fullmatch(r'[\d.,\s]+', n or '')]
    if len(numbers) >= max(2, len(names) // 2):
        return 'numbers'
    return ''


DOUBT_IN_ENGLISH = {
    'too_few': 'only {n} video(s) on the whole page, too few for a listing: '
               'what was read is probably not the list of videos',
    'categories': "what was read carries the site's own category names, so "
                  'the category tiles were taken for videos',
    'numbers': 'most of the names are only numbers, so what was read is '
               'probably counts or badges, not videos',
}


def doubt_in_english(code):
    """The code spelled out, for a report."""
    name, _, number = str(code or '').partition(':')
    text = DOUBT_IN_ENGLISH.get(name, '')
    return text.replace('{n}', number or '?') if text else ''


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
    print(f'[Site] ===== adding {host} =====', flush=True)
    _say(f'you gave: {_safe(url)}', '.')
    with kvs.make_scraper() as scraper:
        _step(1, 4, 'reading that page and looking for a video on it')
        try:
            sources, text, _found_on = collect(url, scraper)
        except Exception as exc:
            # https was our own guess: a site that only answers on http
            # should still work.
            if re.match(r'^[a-z][a-z0-9+.-]*://', typed, re.I) or not _is_connect_error(exc):
                raise
            url = 'http://' + url.split('://', 1)[1]
            root = '{0.scheme}://{0.netloc}'.format(urlsplit(url))
            _say(f'https did not answer, so trying {_safe(url)} instead', '.')
            sources, text, _found_on = collect(url, scraper)
        tried = url
        samples = []            # (page text, page url, the name the listing gave)
        # The site's own listing is what teaches us: it already knows each
        # video's name, so opening three of them is how a real heading is told
        # from a notice the site prints on every page.  This is done even when
        # the typed page itself held a video — a front page often does, and
        # learning from that one page alone taught us nothing.
        from siphon.sites import genericbrowse
        listing_text, listing_at, listing_why = text, url, ''
        listing_shape = ''
        listed = genericbrowse.parse_videos(text, root)
        if not listed and sources:
            # A video page was given, which is the better thing to be given:
            # it proves the download works.  The listing lives on the front
            # page, so go and fetch that as well instead of asking for a
            # second address.
            _say(f'{len(sources)} video source(s) found, so this is a video '
                 'page. That is the better thing to be given: it proves '
                 'downloading works.', '+')
            _step(2, 4, 'fetching the front page, because its listing is what '
                        'teaches the layout')
            try:
                listing_at = root + '/'
                listing_text = _plain_page(listing_at, scraper)
                listed = genericbrowse.parse_videos(listing_text, root)
            except Exception as exc:
                _say(f'the front page did not answer ({exc}), so the layout '
                     'has to be learned from the one page you gave', '-')
                listing_text, listing_at = text, url
        else:
            _step(2, 4, 'reading the listing on this page')
        if listed:
            _say(f'{len(listed)} videos listed on {_safe(listing_at)}', '+')
            _step(3, 4, f'opening {min(3, len(listed))} of them to learn how '
                        'this site writes a video name')
            _say('the listing already knows each name, so the rule that '
                 'reproduces it is the right one - no guessing', '.')
        else:
            _say(f'no video listing found on {_safe(listing_at)}, so the '
                 'name rule cannot be checked against anything', '-')
            # Why it found none, read off the page already in hand.  Without
            # this the report says "0 videos", which names the step that
            # stopped and nothing about the cause.
            listing_why = genericbrowse.why_no_listing(listing_text, root)
            # How the page is built around its links.  Without this a site
            # that cannot be read can only be guessed at, and guessing has
            # already cost two rounds on one site.
            listing_shape = genericbrowse.page_shape_sample(listing_text, root)
            if listing_shape:
                _say('how this page is built around its links:', '.')
                for line in listing_shape.splitlines():
                    _say(line, '.')
        for video in listed[:3]:
            try:
                found, page, _found_on = collect(video['url'], scraper)
            except Exception as exc:
                _say(f'one of the listed videos could not be read ({exc})', '-')
                continue
            samples.append((page, video['url'], video.get('title', '')))
            if found and not sources:
                sources, text, tried = found, page, video['url']
        _step(4, 4, 'finding the address this site searches with')
        search = _working_search(listing_text, root, scraper)
    if not sources:
        raise Exception(
            'no video found on this page. If this is the front page: many '
            'sites build it for each visitor, so it lists nothing here. '
            'Give the address of one video, or of a search or category page')
    if not samples:
        samples = [(text, tried, '')]
    rule, why = learn_title_rule([(page, at) for page, at, _ in samples],
                                 [name for _, _, name in samples])
    if rule:
        _say(f'names come from "{rule}" ({why})', '+')
    else:
        _say(f'no rule names these videos correctly ({why}). Rows will be '
             'labelled from the address instead.', '-')
    if rule and why.startswith('matches the listing'):
        # Confirmed against this site's own listing, so it is evidence worth
        # sharing.  A rule picked only because nothing better turned up is
        # not: counting a guess would teach the next site the guess.
        try:
            config.note_rule_win(rule, host)
        except Exception as exc:
            print(f'[Site] could not record the rule: {exc}', flush=True)
    # For the report, read off the listing already in hand: no page is
    # fetched to collect them.
    try:
        categories = len(genericbrowse.detect_categories(listing_text, root))
        paging = bool(genericbrowse.detect_page_form(listing_text, listing_at))
    except Exception:
        categories, paging = 0, False
    best = sources[-1]
    engine, engine_label = detect_engine(text)
    titles = [_title_from(page, at, rule) for page, at, _ in samples]
    # The last thing in the log is what was concluded, so a reader does not
    # have to work it out from the steps above.
    _say(f'----- {host} added -----', '>')
    _say(f'built on: {engine_label or "no engine recognised"}', '.')
    _say(f'videos listed: {len(listed)}   with a picture: '
         f'{sum(1 for v in listed if v.get("thumbnail"))}   '
         f'categories: {categories}', '.')
    _say(f'name rule: {rule or "none"}   search: '
         f'{_safe(search) if search else "off"}', '.')
    shown = [t for t in titles if t][:3]
    for name in shown:
        _say(f'example name: {name}', '.')
    if len(shown) > 1 and len(set(shown)) == 1:
        _say('all the example names are the same, so the rule is reading '
             'something this site prints on every page. Press Report.', '-')
    _say('paging is not checked now; it is worked out and logged the first '
         'time you turn a page in Browse', '.')
    return {'engine': engine, 'engine_label': engine_label,
            'title': _title_from(text, tried, rule),
            'title_rule': rule,
            'title_why': why,
            'search': search,
            'sample_titles': [t for t in titles if t],
            'listed': len(listed),
            'listing_doubt': listing_looks_wrong(
                listed, genericbrowse.detect_categories(listing_text, root)),
            'thumbs': sum(1 for v in listed if v.get('thumbnail')),
            'host': re.sub(r'^www\.', '', host),
            'count': len(sources),
            'qualities': [s.get('label') or (f"{s.get('height')}p"
                                             if s.get('height') else '')
                          for s in reversed(sources)][:4],
            'via': tried,
            'root': root,
            'categories': categories,
            'paging': paging,
            'listing_at': listing_at,
            'listing_why': listing_why,
            'listing_shape': listing_shape,
            'kind': 'HLS' if best['kind'] == 'hls' else 'MP4'}


class SiteGeneric(MediaSite):
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
            _note_site_trouble(self._url, 'no video on the page')
            raise Exception(f'{name}: no video found on this page '
                            '(the site may have changed)')
        headers = {'Referer': found_on}
        # Same reading as the queue uses, so the row and the saved file agree
        # and a site-wide notice does not become the name.
        title = _title_from(text, self._url, _learned_rule(self._url)) \
            or kvs.pick_title(text, self._url, (), name, f'https://{host}')
        print(f'[{name}] title: {title}', flush=True)
        if title:
            _note_site_well(self._url)
        else:
            _note_site_trouble(self._url, 'the page gave no title')
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
            _note_site_trouble(self._url, 'nothing playable on the page')
            raise Exception(f'{name}: no playable video source on this page')
