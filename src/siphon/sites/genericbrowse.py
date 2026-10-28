"""Browsing a site nobody wrote code for.

Tube sites differ in their HTML but agree on the shape: a listing page holds
many links that carry a thumbnail and all look alike, pagination is a number
in the address, search is a form, and categories sit under /categories/ or
/tags/.  This module works that out from the site's own pages, remembers what
it learned (per host, in the app's settings) and then behaves like the
hand-written site adapters: the Browse tab cannot tell the difference.
"""

from __future__ import annotations

import re
import threading
from urllib.parse import quote, urljoin, urlsplit

from siphon.core import config
from siphon.sites import kvs

# Where sites keep their category lists.
_CATEGORY_WORDS = ('categories', 'category', 'tags', 'tag', 'niches', 'niche',
                   'channels', 'genres', 'genre', 'c')
# Path words that mean "this link is a video".
_VIDEO_WORDS = ('video', 'videos', 'watch', 'v', 'movie', 'movies', 'clip',
                'clips', 'play', 'embed', 'gallery')
_SEARCH_NAMES = ('q', 's', 'search', 'query', 'k', 'keyword', 'keywords',
                 'text', 'term', 'w')
_PAGE_WORDS = ('page', 'p', 'pg', 'from')


def _soup(text):
    from bs4 import BeautifulSoup
    return BeautifulSoup(text or '', 'html.parser')


def _same_site(url, root):
    host = (urlsplit(url).hostname or '').lower().replace('www.', '')
    return host and host == (urlsplit(root).hostname or '').lower().replace('www.', '')


def _shape(path):
    """'/videos/1234/big-title/' -> '/videos/#/*/' — the family a link belongs to."""
    parts = []
    for segment in path.strip('/').split('/'):
        if not segment:
            continue
        if segment.isdigit():
            parts.append('#')
        elif re.fullmatch(r'[\w-]{3,}', segment) and (
                '-' in segment or re.search(r'\d', segment) or len(segment) > 14):
            parts.append('*')
        else:
            parts.append(segment.lower())
    # '/videos/7/x/': once a number is in the address, what follows it is the
    # video's own name, however short.
    if '#' in parts[:-1] and len(parts) > 1 and parts[-1] not in ('#', '*'):
        parts[-1] = '*'
    return '/' + '/'.join(parts)


def _shape_regex(shape):
    pattern = []
    for segment in shape.strip('/').split('/'):
        if segment == '#':
            pattern.append(r'\d+')
        elif segment == '*':
            pattern.append(r'[^/?#]+')
        elif segment:
            pattern.append(re.escape(segment))
    return '/' + '/'.join(pattern) + '/?'


def _text_of(node):
    return re.sub(r'\s+', ' ', node.get_text(' ', strip=True)) if node else ''


_BACKGROUND_RE = re.compile(r'url\(["\']?([^"\')]+)', re.I)


def _image_of(link):
    """(the picture element, its address) for a card, however it is built.

    Sites load thumbnails in several ways: a plain <img>, a lazy <img> whose
    address hides in a data- attribute, a <source srcset>, or a <div> with a
    background image.  All of them count as "this link is a video card".
    """
    img = link.select_one('img')
    if img is not None:
        for attr in ('data-original', 'data-src', 'data-lazy', 'data-thumb',
                     'data-webp', 'data-poster', 'data-image', 'src'):
            value = (img.get(attr) or '').strip()
            if value and not value.startswith('data:'):
                return img, value
        return img, ''
    source = link.select_one('source[srcset], img[srcset]')
    if source is not None:
        value = (source.get('srcset') or '').split(',')[0].strip().split(' ')[0]
        if value:
            return source, value
    for node in [link] + link.select('[style*=background]'):
        found = _BACKGROUND_RE.search(node.get('style') or '')
        if found:
            return node, found.group(1).strip()
    return None, ''


_DURATION_RE = re.compile(r'^\d{1,2}:\d{2}(?::\d{2})?$')


def _duration_near(link):
    """The card's own running time, never a neighbour's."""
    boxes = [link]
    parent = link.parent
    if parent is not None and len(parent.select('a img')) <= 1:
        boxes.append(parent)        # the card around a single thumbnail link
    for box in boxes:
        for node in box.select('[class*=duration], [class*=time], .length'):
            value = _text_of(node)
            if _DURATION_RE.match(value):
                return value
    return ''


def video_groups(text, root):
    """{shape: [links]} for every family of thumbnail links on the page."""
    groups = {}
    for link in _soup(text).select('a[href]'):
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            continue
        url = urljoin(root + '/', href)
        if not _same_site(url, root):
            continue
        img, _src = _image_of(link)
        if img is None:
            continue
        path = urlsplit(url).path
        shape = _shape(path)
        if shape.count('/') < 1 or shape == '/':
            continue
        groups.setdefault(shape, []).append((url, link))
    return groups


def _score(shape, links):
    """How much a family looks like "the videos on this page"."""
    score = min(len(links), 60)
    words = shape.strip('/').split('/')
    if any(word in _VIDEO_WORDS for word in words):
        score += 40
    if '#' in words:
        score += 20
    if any(word in _CATEGORY_WORDS for word in words):
        score -= 60
    if len(words) == 1 and words[0] == '*':
        score -= 15          # bare /slug/ links are often categories
    return score


def detect_video_shape(text, root):
    """The address shape of this site's video pages ('' if unclear)."""
    groups = video_groups(text, root)
    if not groups:
        return ''
    best = max(groups.items(), key=lambda item: _score(*item))
    return best[0] if len(best[1]) >= 3 else ''


def parse_videos(text, root, shape=''):
    """[{'url','title','thumbnail','duration'}] from any listing page."""
    groups = video_groups(text, root)
    if not groups:
        return []
    if shape and shape in groups:
        links = groups[shape]
    else:
        links = max(groups.items(), key=lambda item: _score(*item))[1]
    videos, seen = [], set()
    for url, link in links:
        if url in seen:
            continue
        seen.add(url)
        img, thumb = _image_of(link)
        title = (link.get('title') or (img.get('alt') if img else '') or '').strip()
        if not title or len(title) < 3:
            for node in (link.select_one('[class*=title]'), link):
                title = _text_of(node)
                if title:
                    break
        if thumb:
            thumb = urljoin(root + '/', thumb)
        videos.append({'url': url, 'title': kvs.clean_title(title) or url,
                       'thumbnail': thumb, 'duration': _duration_near(link)})
    return videos


def detect_page_form(text, page_url):
    """How this site spells "page 2", applied to ``page_url``.

    Only two spellings are accepted, because they are the two that sites
    actually use and the only two that can be told apart safely: the number as
    the last part of the address (…/popular/2/) and a page number in the query
    (…?page=2).  The form is taken from the site's own page links; the address
    is then built from the listing being viewed.
    """
    base = page_url.split('#', 1)[0]
    votes = {}
    for link in _soup(text).select('a[href]'):
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'javascript:')):
            continue
        label = _text_of(link)
        rel = ' '.join(link.get('rel') or []).lower()
        wanted = label if label.isdigit() else ''
        if not wanted and 'next' not in rel and not re.fullmatch(
                r'(?:next|»|>>?|sonraki)', label.lower()):
            continue
        url = urljoin(base, href)
        parts = urlsplit(url)
        query = dict(re.findall(r'([^?&=]+)=([^&]*)', parts.query))
        for key, value in query.items():
            if value.isdigit() and 2 <= int(value) <= 500 and (
                    key.lower() in _PAGE_WORDS or 'page' in key.lower()):
                if not wanted or value == wanted:
                    votes[f'query:{key}'] = votes.get(f'query:{key}', 0) + 2
        tail = parts.path.rstrip('/').rsplit('/', 1)[-1]
        if tail.isdigit() and 2 <= int(tail) <= 500 and (not wanted or tail == wanted):
            votes['path'] = votes.get('path', 0) + 2
        folder = parts.path.rstrip('/').rsplit('/', 2)
        if len(folder) == 3 and folder[1].lower() in _PAGE_WORDS and folder[2].isdigit():
            votes['path_word:' + folder[1].lower()] = votes.get(
                'path_word:' + folder[1].lower(), 0) + 3
    if not votes:
        return ''
    return max(votes.items(), key=lambda item: item[1])[0]


def apply_page_form(form, base_url):
    """'query:page' + a listing address -> that listing's page-2 address."""
    if not form:
        return ''
    head, _, rest = base_url.partition('?')
    rest = f'?{rest}' if rest else ''
    if form == 'path':
        return head.rstrip('/') + '/{page}/' + rest
    if form.startswith('path_word:'):
        return head.rstrip('/') + f'/{form.split(":", 1)[1]}/{{page}}/' + rest
    key = form.split(':', 1)[1]
    key = re.sub(r'[^\w-]', '', key) or 'page'
    joiner = '&' if rest else '?'
    return f'{head}{rest}{joiner}{key}={{page}}'


def detect_search(text, root):
    """A search address with {query} in it ('' if the site has no search box)."""
    for form in _soup(text).select('form'):
        if (form.get('method') or 'get').lower() != 'get':
            continue
        field = None
        for candidate in form.select('input'):
            name = (candidate.get('name') or '').lower()
            kind = (candidate.get('type') or 'text').lower()
            if kind in ('text', 'search', '') and (
                    name in _SEARCH_NAMES or 'search' in name or 'query' in name):
                field = candidate
                break
        if field is None:
            continue
        action = urljoin(root + '/', (form.get('action') or '').strip() or '/')
        extra = []
        for other in form.select('input[type=hidden]'):
            if other.get('name'):
                extra.append(f"{other['name']}={quote(str(other.get('value') or ''))}")
        joiner = '&' if '?' in action else '?'
        query = f"{field.get('name')}={{query}}"
        return action + joiner + '&'.join([query] + extra)
    return ''


def detect_categories(text, root):
    """[{'name','url','count'}] from the links a site keeps to its categories."""
    found, seen = [], set()
    for link in _soup(text).select('a[href]'):
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'javascript:')):
            continue
        url = urljoin(root + '/', href)
        if not _same_site(url, root):
            continue
        parts = [p for p in urlsplit(url).path.strip('/').split('/') if p]
        if len(parts) < 2 or parts[0].lower() not in _CATEGORY_WORDS:
            continue
        if url in seen:
            continue
        seen.add(url)
        name = _text_of(link) or parts[1].replace('-', ' ').title()
        if len(name) > 40:
            name = parts[1].replace('-', ' ').title()
        found.append({'name': name, 'url': url, 'count': 0})
    return found[:60]


# Sites built on Kernel Video Sharing all use the same addresses, so a site
# recognised as KVS starts from these instead of being worked out page by page.
ENGINE_PROFILES = {
    'kvs': {'video_shape': '/videos/#/*', 'page_form': 'path',
            'search': '{root}/search/{query}/'},
}


def engine_profile(engine, root, page_text=''):
    """The layout to start from: one the user taught us, else a known engine."""
    profile = {}
    if page_text:
        from siphon.sites.generic import match_template
        learned = match_template(page_text, config.get_site_templates())
        if learned:
            print(f'[site] same layout as "{learned["name"]}"', flush=True)
            profile = {k: v for k, v in learned.items()
                       if k in ('video_shape', 'page_form', 'search')}
    for key, value in ENGINE_PROFILES.get(engine or '', {}).items():
        profile.setdefault(key, value)
    if profile.get('search'):
        profile['search'] = profile['search'].replace('{root}', root.rstrip('/'))
    return profile


class GenericBrowser:
    """Browse support for a site the user added.  One subclass per host."""

    ROOT = ''
    NAME = ''
    SEARCH_SORTS = []
    _scraper = None
    _lock = None
    _learned = None

    # ── fetching ────────────────────────────────────────────────────
    @classmethod
    def _get_scraper(cls):
        if cls.__dict__.get('_lock') is None:
            cls._lock = threading.Lock()
        with cls._lock:
            if cls.__dict__.get('_scraper') is None:
                cls._scraper = kvs.make_scraper()
            return cls._scraper

    @classmethod
    def _get(cls, url, render=None):
        """The page's HTML.

        ``render`` opens it in a real browser instead, which is what a site
        whose list is built by JavaScript needs; once that has been necessary
        the site is remembered, so later pages go straight there.
        """
        from siphon.core import browser as real_browser
        if render is None:
            render = cls.profile().get('needs_browser') == '1'
        if render and real_browser.available():
            text, _media = real_browser.fetch(url, referer=cls.ROOT + '/')
            print(f'[{cls.NAME}] read {url} in the browser ({len(text)} bytes)',
                  flush=True)
            return text
        text = kvs.fetch_text(cls._get_scraper(), url, cls.ROOT + '/', cls.NAME)
        print(f'[{cls.NAME}] read {url} ({len(text)} bytes)', flush=True)
        return text

    @classmethod
    def _get_with_videos(cls, url, shape=''):
        """(page text, videos).  Falls back to the browser when the quick read
        finds no videos: the list was probably built by JavaScript."""
        from siphon.core import browser as real_browser
        text = cls._get(url)
        videos = parse_videos(text, cls.ROOT, shape)
        if videos or cls.profile().get('needs_browser') == '1':
            return text, videos
        if not real_browser.available():
            return text, videos
        print(f'[{cls.NAME}] nothing in the page source; opening it in the browser',
              flush=True)
        rendered = cls._get(url, render=True)
        found = parse_videos(rendered, cls.ROOT, shape)
        if found:
            cls._remember(needs_browser='1')
            return rendered, found
        return text, videos

    # ── what we worked out about this site ──────────────────────────
    @classmethod
    def profile(cls):
        if cls.__dict__.get('_learned') is None:
            cls._learned = dict(config.get_site_profile(cls.host()) or {})
        return cls._learned

    @classmethod
    def _remember(cls, **values):
        profile = dict(cls.profile())
        profile.update({k: v for k, v in values.items() if v})
        cls._learned = profile
        config.set_site_profile(cls.host(), profile)

    @classmethod
    def host(cls):
        return (urlsplit(cls.ROOT).hostname or '').replace('www.', '')

    @classmethod
    def _home(cls):
        return cls._get(cls.ROOT + '/')

    # ── the interface the Browse tab uses ───────────────────────────
    @classmethod
    def fetch_categories(cls):
        home, _videos = cls._get_with_videos(cls.ROOT + '/')
        from siphon.sites.generic import detect_engine
        engine, label = detect_engine(home)
        if engine:
            print(f'[{cls.NAME}] built on {label}', flush=True)
        known = engine_profile(engine, cls.ROOT, home)
        shape = detect_video_shape(home, cls.ROOT) or known.get('video_shape', '')
        search = detect_search(home, cls.ROOT) or known.get('search', '')
        cls._remember(engine=engine, video_shape=shape, search=search,
                      page_form=cls.profile().get('page_form') or known.get('page_form', ''))
        sections = [{'name': 'Home', 'url': cls.ROOT + '/', 'count': 0}]
        return sections + detect_categories(home, cls.ROOT)

    @classmethod
    def fetch_page(cls, url):
        page = 1
        match = re.search(r'[?&]siphon_page=(\d+)', url)
        if match:
            page = int(match.group(1))
            url = re.sub(r'[?&]siphon_page=\d+', '', url) or cls.ROOT + '/'
        text, found = cls._get_with_videos(url)
        shape = cls.profile().get('video_shape') or detect_video_shape(text, cls.ROOT)
        form = detect_page_form(text, url) or cls.profile().get('page_form', '')
        cls._remember(video_shape=shape, page_form=form)
        if page > 1:
            # '?page=N' is the spelling nearly every site understands, so it
            # is the first guess when the listing showed no page links; the
            # other spelling is tried when that returns nothing.
            forms = [form] if form else ['query:page', 'path']
            videos = []
            for index, candidate in enumerate(forms):
                next_url = apply_page_form(candidate, url).replace('{page}', str(page))
                try:
                    _text, videos = cls._get_with_videos(next_url, shape)
                except Exception as exc:
                    print(f'[{cls.NAME}] page {page} ({candidate}): {exc}', flush=True)
                    continue
                if videos:
                    if index:
                        cls._remember(page_form=candidate)
                    return videos
            return videos
        return found or parse_videos(text, cls.ROOT, shape)

    @staticmethod
    def page_url(base_url, page):
        if page <= 1:
            return base_url
        sep = '&' if '?' in base_url else '?'
        return f'{base_url}{sep}siphon_page={int(page)}'

    @classmethod
    def is_video_url(cls, url):
        if not _same_site(str(url or ''), cls.ROOT):
            return False
        shape = cls.profile().get('video_shape')
        if not shape:
            return True          # unknown yet: let the download side decide
        return bool(re.fullmatch(_shape_regex(shape), urlsplit(url).path or '/'))

    @classmethod
    def search_url(cls, query, sort=''):
        template = cls.profile().get('search')
        if not template:
            try:
                template = detect_search(cls._home(), cls.ROOT)
                cls._remember(search=template)
            except Exception as exc:
                print(f'[{cls.NAME}] search box not found: {exc}', flush=True)
        words = (query or '').strip()
        if template:
            return template.replace('{query}', quote(words))
        return f'{cls.ROOT}/search/{quote(words)}/'

    @classmethod
    def search(cls, query, sort=''):
        return cls.fetch_page(cls.search_url(query, sort))


_classes = {}


def browser_for(host, name=''):
    """The browse adapter for a user-added site (one per host, re-used)."""
    host = str(host or '').lower().replace('www.', '')
    if host not in _classes:
        # The address this site actually answered on (probe() stores it);
        # https for one we have not met yet.
        root = (config.get_site_profile(host) or {}).get('root') or f'https://{host}'
        _classes[host] = type(
            'Browser_' + re.sub(r'\W', '_', host),
            (GenericBrowser,),
            {'ROOT': root.rstrip('/'), 'NAME': name or host,
             '_scraper': None, '_lock': None, '_learned': None})
    return _classes[host]
