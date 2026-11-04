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

# How sites spell "page 2" in an address.  Tried in this order when the
# site's own page links spell nothing — which is common, because many sites
# draw their pager with JavaScript while still answering these addresses.
PAGE_SHAPES = ('query:page', 'path', 'path_word:page', 'query:p', 'query:pg')

# The pager whose links go to '#' and keep the real address in a data-
# attribute.  Kernel Video Sharing, the most common tube engine, builds its
# pager this way, so this is how most added sites turn a page.
INPAGE_FORM = 'inpage'


def _inpage_pager(listing_text):
    """(block id, parameters) of a data-attribute pager, or None."""
    if not listing_text or 'data-parameters' not in listing_text:
        return None
    try:
        from siphon.sites.kvs import parse_ajax_pagination
        return parse_ajax_pagination(listing_text)
    except Exception:
        return None


def inpage_page_url(listing_text, listing_url, page):
    """The address a data-attribute pager would ask for, for ``page``.

    The pager's own link carries which block of the page to re-render and
    which parameter counts the pages; both go into an ordinary address, so
    no browser and no JavaScript is needed to turn the page.
    """
    pager = _inpage_pager(listing_text)
    if not pager:
        return ''
    block_id, params = pager
    query = {'mode': 'async', 'function': 'get_block', 'block_id': block_id}
    for key, value in params:
        for name in str(key).split('+'):
            query[name] = str(page) if value == '{page}' else value
    # A sort chosen in the address is the one the person is looking at, so it
    # replaces whatever the pager's own link happened to carry.
    sort = re.search(r'[?&]sort_by=([^&]+)', listing_url)
    if sort:
        query['sort_by'] = sort.group(1)
    from urllib.parse import urlencode
    return f"{listing_url.split('?', 1)[0]}?{urlencode(query)}"


def _safe(url):
    """An address Siphon worked out itself: kept whole in the log file.

    The log hides the path of an address by default, so that which videos a
    person opened is not written down.  The addresses here are different:
    they are how the site spells a listing or a page, which is the whole
    content of a site report and tells nobody what anyone watched.
    """
    try:
        from siphon.core import applog
        return applog.keep(str(url))
    except Exception:
        return str(url)


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
        # A page ending such as .html belongs to the site's plumbing, not to
        # the video's name: '/v6abc-a-title.html' is the same family as
        # '/v6def-another.html'.  Without this every such address was a
        # family of one and no family ever reached the three links needed to
        # count as a listing, which is why Rumble read as empty.
        bare = re.sub(r'\.(?:html?|php|aspx?|jsp)$', '', segment, flags=re.I)
        if segment.isdigit():
            parts.append('#')
        elif bare.isdigit():
            parts.append('#')
        elif re.fullmatch(r'[\w-]{3,}', bare) and (
                '-' in bare or re.search(r'\d', bare) or len(bare) > 14):
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

    The picture does not have to be inside the link.  Plenty of sites build
    a card as a box holding a picture and, beside it, a link — Rumble does,
    and every one of its links was passed over for having no picture of its
    own, so its listing read as empty.  When the link holds none, the box
    around it is searched, under one condition: see _image_beside().
    """
    found = _image_inside(link)
    if found[0] is not None:
        return found
    return _image_beside(link)


def _image_inside(link):
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


# How far up to look for a card's picture.  A card is a small box; going
# further reaches the row, then the whole page, where any picture at all
# would be claimed by any link at all.
_CARD_LEVELS = 3


def _image_beside(link):
    """A picture in the box around ``link``, when that box holds only it.

    The condition is the whole safety of this: a box with two links in it
    gives no way to know which one the picture belongs to, and guessing
    brings back the bug where a row showed another video's thumbnail.  So
    the search stops at the first box that holds a second link, and a card
    whose picture cannot be told apart simply has none.
    """
    box = link.parent
    for _level in range(_CARD_LEVELS):
        if box is None or getattr(box, 'name', '') in ('body', 'html', '[document]'):
            break
        if len(box.select('a[href]')) > 1:
            break               # more than one link: no telling whose it is
        found = _image_inside(box)
        if found[0] is not None:
            return found
        box = box.parent
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


def video_groups(text, root, explain=False):
    """{shape: [links]} for every family of thumbnail links on the page.

    With ``explain``, the reasons links were passed over are written to the
    log.  An empty listing used to be reported as "0 videos", which says
    where the reading stopped and nothing about why, so every such site had
    to be opened by hand to find out.  Now the page says it itself.
    """
    groups = {}
    passed = {'off site': 0, 'no picture in the link': 0,
              'address too short to be a video page': 0, 'not a link': 0}
    links = _soup(text).select('a[href]')
    for link in links:
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            passed['not a link'] += 1
            continue
        url = urljoin(root + '/', href)
        if not _same_site(url, root):
            passed['off site'] += 1
            continue
        img, _src = _image_of(link)
        if img is None:
            passed['no picture in the link'] += 1
            continue
        path = urlsplit(url).path
        shape = _shape(path)
        if shape.count('/') < 1 or shape == '/':
            passed['address too short to be a video page'] += 1
            continue
        groups.setdefault(shape, []).append((url, link))
    if explain:
        _explain_groups(links, groups, passed)
    return groups


def _explain_groups(links, groups, passed):
    """Say what the page held and why it gave no videos.

    Printed to the log and returned as one line for the site report, so the
    cause travels even when the log does not.
    """
    print(f'[Site] the page has {len(links)} links; a video card is a link '
          'to this site with a picture inside it', flush=True)
    for reason, count in sorted(passed.items(), key=lambda kv: -kv[1]):
        if count:
            print(f'[Site]   {count} passed over: {reason}', flush=True)
    if groups:
        for shape, found in sorted(groups.items(), key=lambda kv: -_score(*kv)):
            print(f'[Site]   {len(found)} links shaped "{shape}" '
                  f'(score {_score(shape, found)})', flush=True)
        return ''

    biggest = max(passed.items(), key=lambda kv: kv[1])[0] if any(
        passed.values()) else 'nothing to pass over'
    summary = (f'{len(links)} links on the page, no video cards; '
               f'most were passed over: {biggest}')
    print(f'[Site]   {summary}', flush=True)
    if biggest == 'no picture in the link':
        print('[Site]   that means this site keeps its thumbnails outside '
              'the link, which this reader cannot follow yet', flush=True)
        summary += (' — the site keeps its thumbnails outside the link, '
                    'which this reader cannot follow yet')
    return summary


def _where(node, levels=4):
    """'div.videostream > div.thumb > a.link' for a node and its boxes."""
    chain = []
    at = node
    for _level in range(levels + 1):
        if at is None or getattr(at, 'name', None) in (None, '[document]'):
            break
        classes = [c for c in (at.get('class') or []) if c][:2]
        chain.append(at.name + ''.join('.' + c for c in classes))
        at = at.parent
    return ' > '.join(reversed(chain))


def _picture_near(link, levels=5):
    """Where the closest picture to ``link`` is, in words ('' if none)."""
    box = link.parent
    for level in range(1, levels + 1):
        if box is None or getattr(box, 'name', '') in ('body', 'html', '[document]'):
            break
        img = box.select_one('img, source[srcset], picture')
        if img is not None:
            return (f'{level} level(s) up, in {_where(box, 1)}, '
                    f'as <{img.name}>')
        box = box.parent
    return ''


# Where a site keeps its own furniture.  A link in here is a menu item, not
# a video, and describing three of those says nothing about the listing —
# which is exactly what the first sample of Rumble did.
_FURNITURE = ('header', 'nav', 'footer', 'aside')


def _in_furniture(node):
    at = node.parent
    while at is not None and getattr(at, 'name', None):
        name = at.name.lower()
        if name in _FURNITURE:
            return True
        hint = ' '.join(at.get('class') or []) + ' ' + (at.get('id') or '')
        if re.search(r'\b(header|navbar|nav|footer|sidebar|menu)\b', hint, re.I):
            return True
        at = at.parent
    return False


def _link_families(text, root):
    """{shape: [links]} for every on-site link, picture or not.

    video_groups() keeps only links that have a picture, which is the very
    judgement under suspicion when a listing cannot be read.  This keeps
    them all, so the report can say what the page actually holds.
    """
    families = {}
    for link in _soup(text).select('a[href]'):
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            continue
        url = urljoin(root + '/', href)
        if not _same_site(url, root) or _in_furniture(link):
            continue
        families.setdefault(_shape(urlsplit(url).path), []).append(link)
    return families


def page_shape_sample(text, root, families_wanted=4):
    """How this page is built around its links, for a site report.

    When a listing cannot be read there is no way to fix it without seeing
    how the page is put together — and asking someone to save the page and
    send it is both work for them and a thing they should not have to do.
    The page is already open here, so it describes its own shape.

    It describes the largest families of links rather than the first few on
    the page: a listing is many links of one shape, while the first links on
    any page are its menu.  Only shape — tag names, class names, where the
    nearest picture sits, how many links share a box — so it says nothing
    about what anyone watched.
    """
    families = _link_families(text, root)
    if not families:
        return ''
    ranked = sorted(families.items(), key=lambda kv: -len(kv[1]))
    lines = []
    for shape, links in ranked[:families_wanted]:
        with_picture = sum(1 for link in links
                           if _image_inside(link)[0] is not None)
        example = links[0]
        box = example.parent
        shared = len(box.select('a[href]')) if box is not None else 1
        lines.append(
            f'{len(links)} links shaped "{shape}" '
            f'(score {_score(shape, links)}), '
            f'{with_picture} of them with a picture inside\n'
            f'    one of them: {_where(example)}\n'
            f'    nearest picture: '
            f'{_picture_near(example) or "none within 5 levels"}\n'
            f'    links sharing its box: {shared}')
    return '\n'.join(lines)


def why_no_listing(text, root):
    """One line saying why this page gave no videos ('' when it gave some)."""
    links = _soup(text).select('a[href]')
    groups = video_groups(text, root)
    if groups:
        return ''
    passed = {'off site': 0, 'no picture in the link': 0,
              'address too short to be a video page': 0, 'not a link': 0}
    for link in links:
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            passed['not a link'] += 1
        elif not _same_site(urljoin(root + '/', href), root):
            passed['off site'] += 1
        elif _image_of(link)[0] is None:
            passed['no picture in the link'] += 1
        else:
            passed['address too short to be a video page'] += 1
    return _explain_groups(links, {}, passed)


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


def _titles_by_url(text, root):
    """{video address: the best name any link on the page gives it}.

    A card very often links to the same video twice: once around the
    picture, once around the title.  Only the picture link counts as a card,
    so the one carrying the name is dropped before it is ever looked at, and
    the row ends up named after the address — which is what rows reading
    "www.example.com/sdkbfwef" were.  The name is on the page; it just
    belongs to the other link.
    """
    names = {}
    for link in _soup(text).select('a[href]'):
        href = (link.get('href') or '').strip()
        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
            continue
        url = urljoin(root + '/', href)
        found = (link.get('title') or '').strip() or _text_of(link)
        found = kvs.clean_title(found or '')
        # The longest name wins: a card's title link says more than an
        # "x comments" or "watch later" link to the same video.
        if found and len(found) > len(names.get(url, '')):
            names[url] = found
    return names


def parse_videos(text, root, shape='', strict=False):
    """[{'url','title','thumbnail','duration'}] from any listing page.

    ``strict`` is for a shape somebody proved (taught from a real video page):
    if this page has no links of that shape the answer is none, not whichever
    other family of links scores highest.  On a home page made of category
    tiles that other family is the tiles, shown as if they were videos.
    """
    groups = video_groups(text, root)
    if not groups:
        return []
    if shape and shape in groups:
        links = groups[shape]
    elif shape and strict:
        return []
    else:
        links = max(groups.items(), key=lambda item: _score(*item))[1]
    elsewhere = _titles_by_url(text, root)
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
        title = kvs.clean_title(title or '')
        # Whatever the rest of the card calls it, if this link said nothing
        # useful.  Falling back to the address makes a row unreadable.
        if len(title) < 3 or title in url:
            title = elsewhere.get(url) or title
        if thumb:
            thumb = urljoin(root + '/', thumb)
        videos.append({'url': url, 'title': title or url,
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


def detect_search_all(text, root):
    """Every search address the page's forms offer, the likeliest first.

    A page can hold several small forms (a mobile menu, a newsletter box, the
    real search), so the first one is not always the right one.  Forms whose
    address says "search" and fields called "q" come first.
    """
    found = []
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
        template = action + joiner + '&'.join([query] + extra)
        rank = (0 if 'search' in urlsplit(action).path.lower() else 1,
                0 if (field.get('name') or '').lower() == 'q' else 1)
        if template not in [t for _r, t in found]:
            found.append((rank, template))
    return [template for _rank, template in sorted(found, key=lambda x: x[0])]


def detect_search(text, root):
    """A search address with {query} in it ('' if the site has no search box)."""
    found = detect_search_all(text, root)
    return found[0] if found else ''


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

    _home_videos = None      # what the front page lists, read once per run

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
            text, _media = real_browser.fetch(url, referer=cls.ROOT + '/',
                                              settle=2.5)
            print(f'[{cls.NAME}] read {_safe(url)} in the browser ({len(text)} bytes)',
                  flush=True)
            return text
        text = kvs.fetch_text(cls._get_scraper(), url, cls.ROOT + '/', cls.NAME)
        print(f'[{cls.NAME}] read {_safe(url)} ({len(text)} bytes)', flush=True)
        return text

    front_page_empty = False

    @classmethod
    def _saved_shape(cls):
        """(shape, proved): the video shape kept for this site."""
        kept = cls.profile()
        shape = kept.get('video_shape') or ''
        return shape, bool(shape and kept.get('video_shape_ok'))

    @classmethod
    def _get_with_videos(cls, url, shape=None):
        """(page text, videos).  Falls back to the browser when the quick read
        finds no videos: the list was probably built by JavaScript.

        With no shape given, the one saved for the site is used: reading with
        a fresh guess every time threw away what the site had been taught."""
        from siphon.core import browser as real_browser
        proved = False
        if shape is None:
            shape, proved = cls._saved_shape()
        text = cls._get(url)
        videos = parse_videos(text, cls.ROOT, shape or '', proved)
        if videos or cls.profile().get('needs_browser') == '1':
            return text, videos
        if not real_browser.available():
            return text, videos
        print(f'[{cls.NAME}] nothing in the page source; opening it in the browser',
              flush=True)
        try:
            rendered = cls._get(url, render=True)
        except Exception as exc:
            # The browser is only a second try.  When it cannot start or the
            # site turns it away, the page already read is still the answer:
            # failing here took the section list down with it ("Failed to
            # load categories") although that page had been read fine.
            print(f'[{cls.NAME}] the browser could not read {_safe(url)} '
                  f'either ({exc}); keeping the page read without it',
                  flush=True)
            return text, videos
        found = parse_videos(rendered, cls.ROOT, shape or '', proved)
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
        home, home_videos = cls._get_with_videos(cls.ROOT + '/')
        from siphon.sites.generic import detect_engine
        engine, label = detect_engine(home)
        if engine:
            print(f'[{cls.NAME}] built on {label}', flush=True)
        known = engine_profile(engine, cls.ROOT, home)
        shape, proved = cls._saved_shape()
        if not proved:
            shape = detect_video_shape(home, cls.ROOT) or known.get('video_shape', '')
        # The search address is NOT touched here.  Adding the site tried it
        # once and kept it only if it really searched; re-guessing it on every
        # visit put the unverified guess straight back.
        # Nor is the page spelling re-guessed once one has been proved on
        # this site: the proof came from fetching page two and seeing
        # different videos, which a guess from the engine cannot match.
        kept = cls.profile()
        page_form = (kept.get('page_form') if kept.get('page_form_ok')
                     else kept.get('page_form') or known.get('page_form', ''))
        cls._remember(engine=engine, video_shape=shape, page_form=page_form)
        categories = detect_categories(home, cls.ROOT)
        # Some sites' front page is only a door: tiles for categories and no
        # videos at all.  Opening on it shows an empty page, so the first
        # category opens instead and the front page is not offered.
        if categories and not home_videos:
            print(f'[{cls.NAME}] the front page lists no videos, only '
                  f'{len(categories)} categories, so it opens on "'
                  f'{categories[0]["name"]}"', flush=True)
            return categories
        return [{'name': 'Home', 'url': cls.ROOT + '/', 'count': 0}] + categories

    @classmethod
    def _describe_empty_page(cls, url, text):
        """Write down what a page with no videos is, so the log answers it.

        A page that yields nothing is one of a few things: a listing built
        some other way, a door made of categories, or not the site at all (an
        age check, a block notice).  What the page calls itself and how its
        links are built tells which, without anyone saving anything.
        """
        try:
            soup = _soup(text)
            title = _text_of(soup.title)[:100] if soup.title else ''
            words = _text_of(soup.body)[:200] if soup.body else ''
            links = soup.select('a[href]')
            print(f'[{cls.NAME}] this page has no videos. It calls itself '
                  f'"{title}", has {len(links)} links, '
                  f'{len(detect_categories(text, cls.ROOT))} of them to '
                  f'categories. It starts: "{words}"', flush=True)
            sample = page_shape_sample(text, cls.ROOT, 6)
            for line in (sample or 'no link family worth describing').splitlines():
                print(f'[{cls.NAME}]     {line}', flush=True)
        except Exception as exc:
            print(f'[{cls.NAME}] could not describe the empty page: {exc}',
                  flush=True)

    @classmethod
    def _is_the_front_page_again(cls, url, videos):
        """True when a category or search gave back the front page.

        A site that does not recognise an address often answers with its home
        page rather than an error, which makes every category look like it
        worked and show the same videos.
        """
        home = (cls.ROOT + '/').rstrip('/')
        if url.split('?')[0].rstrip('/') == home or not videos:
            return False
        from siphon.sites.generic import _same_videos
        if cls._home_videos is None:
            try:
                _text, found = cls._get_with_videos(cls.ROOT + '/')
                cls._home_videos = found
            except Exception:
                cls._home_videos = []
        return _same_videos(videos, cls._home_videos or [])

    @classmethod
    def fetch_page(cls, url):
        page = 1
        match = re.search(r'[?&]siphon_page=(\d+)', url)
        if match:
            page = int(match.group(1))
            url = re.sub(r'[?&]siphon_page=\d+', '', url) or cls.ROOT + '/'
        text, found = cls._get_with_videos(url)
        shape, proved = cls._saved_shape()
        shape = shape or detect_video_shape(text, cls.ROOT)
        cls._remember(video_shape=shape)
        if page > 1:
            here = found or parse_videos(text, cls.ROOT, shape, proved)
            return cls._videos_on_page(url, page, here, shape, text)
        videos = found or parse_videos(text, cls.ROOT, shape, proved)
        print(f"[{cls.NAME}] video shape {shape or '-'} "
              f"({'taught' if proved else 'guessed'}): {len(videos)} read",
              flush=True)
        if proved and not videos:
            print(f'[{cls.NAME}] no links shaped like {shape} on this page, so '
                  'nothing is shown as a video here', flush=True)
        is_front = url.split('?')[0].rstrip('/') == cls.ROOT.rstrip('/')
        # Remembered for the Browse tab, which can then say why it is empty.
        cls.front_page_empty = bool(not videos and page <= 1 and is_front)
        if not videos and page <= 1:
            cls._describe_empty_page(url, text)
        if cls._is_the_front_page_again(url, videos):
            print(f'[{cls.NAME}] this address gives back the front page, so it '
                  'is not a listing of its own', flush=True)
            return []
        if not videos and page <= 1:
            videos = cls._search_elsewhere(url)
        elif videos and page <= 1 and cls._is_saved_search(url):
            cls._remember(search_ok='1')
        return videos

    @classmethod
    def _is_saved_search(cls, url):
        template = cls.profile().get('search') or ''
        return '{query}' in template and url.startswith(template.split('{query}')[0])

    @classmethod
    def _search_elsewhere(cls, url):
        """A search that found nothing may just have used the wrong address.

        When ``url`` is this site's saved search address filled in with a
        word, the page's other search boxes and the usual addresses are tried
        for the same word.  The first one that returns videos is kept.
        """
        template = cls.profile().get('search') or ''
        if '{query}' not in template or cls.profile().get('search_ok') == '1':
            return []           # this address has searched before: no results
        prefix = template.split('{query}')[0]
        if not url.startswith(prefix):
            return []
        word = url[len(prefix):].split('&')[0]
        if not word:
            return []
        from siphon.sites.generic import _SEARCH_SHAPES
        options = []
        try:
            options += detect_search_all(cls._home(), cls.ROOT)
        except Exception:
            pass
        options += [shape.replace('{root}', cls.ROOT) for shape in _SEARCH_SHAPES]
        tried = {template}
        for option in options:
            if option in tried:
                continue
            tried.add(option)
            try_url = option.replace('{query}', word)
            try:
                text, found = cls._get_with_videos(try_url)
            except Exception as exc:
                print(f'[{cls.NAME}] search at {_safe(try_url)} failed: {exc}',
                      flush=True)
                continue
            if found and not cls._is_the_front_page_again(try_url, found):
                print(f'[{cls.NAME}] the saved search address found nothing; '
                      f'{_safe(option)} works, so that is kept', flush=True)
                cls._remember(search=option, search_ok='1')
                return found
            print(f'[{cls.NAME}] search at {_safe(option)} found nothing',
                  flush=True)
        return []

    @classmethod
    def _page_candidates(cls, listing_text, listing_url):
        """The page-2 spellings to try, best first, without repeats.

        A spelling already proved on this site comes first and is the only
        one needed.  Next is whatever the site's own page links spell, then
        the spellings sites actually use — because plenty of sites paginate
        by address while showing no page links at all in their HTML.
        """
        order = []
        profile = cls.profile()
        if profile.get('page_form') and profile.get('page_form_ok'):
            order.append(profile['page_form'])
        from_links = detect_page_form(listing_text, listing_url)
        if from_links:
            order.append(from_links)
        order.extend(PAGE_SHAPES)
        # Some sites write the pager as links that go nowhere — href="#" —
        # and keep the real page address in a data- attribute for their own
        # JavaScript to use.  Nothing is hidden from us there: the address
        # exists, it is just not in the href, so it is worth asking for.
        if INPAGE_FORM not in order and _inpage_pager(listing_text):
            order.append(INPAGE_FORM)
        seen, unique = set(), []
        for form in order:
            if form and form not in seen:
                seen.add(form)
                unique.append(form)
        return unique

    @classmethod
    def _videos_on_page(cls, listing_url, page, on_page_one, shape,
                        listing_text=''):
        """Page ``page`` of ``listing_url``, or [] when the site has no such page.

        The address for page two is a guess until it is checked, and the
        check that matters is not "did videos come back".  A site that does
        not understand ?page=2 usually answers with the listing again, so
        videos always come back: every spelling looks right and the reader
        stays on page one for ever.  A page is only a page when it shows
        something page one did not.
        """
        for form in cls._page_candidates(listing_text, listing_url):
            if form == INPAGE_FORM:
                next_url = inpage_page_url(listing_text, listing_url, page)
                if not next_url:
                    print(f'[{cls.NAME}] page {page}: the pager on this page '
                          'carries no page number this reader can use',
                          flush=True)
                    continue
            else:
                next_url = apply_page_form(form, listing_url).replace(
                    '{page}', str(page))
            try:
                _text, videos = cls._get_with_videos(next_url)
            except Exception as exc:
                print(f'[{cls.NAME}] page {page}: tried {_safe(next_url)} — '
                      f'could not be read ({exc})', flush=True)
                continue
            if not videos:
                print(f'[{cls.NAME}] page {page}: tried {_safe(next_url)} — '
                      'no videos on it', flush=True)
                continue
            from siphon.sites.generic import _same_videos
            if _same_videos(videos, on_page_one):
                print(f'[{cls.NAME}] page {page}: tried {_safe(next_url)} — '
                      f'gave back the same {len(videos)} videos as the page '
                      'before, so the site ignored it', flush=True)
                continue
            if cls._is_the_front_page_again(next_url, videos):
                print(f'[{cls.NAME}] page {page}: tried {_safe(next_url)} — '
                      'gave back the front page, so the site ignored it',
                      flush=True)
                continue
            print(f'[{cls.NAME}] page {page}: {_safe(next_url)} — {len(videos)} '
                  f'different videos, so "{form}" is how this site spells '
                  'pages', flush=True)
            cls._remember(page_form=form, page_form_ok='1')
            return videos
        print(f'[{cls.NAME}] page {page}: none of the usual page addresses '
              'worked on this site. Its paging may be built by JavaScript, '
              'which has no address to ask for.', flush=True)
        return []

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
        """The address this site searches at, or '' when it has none.

        Never a guess: an invented address usually answers with the front
        page, so every search would look like it worked and show the same
        videos.  '' tells the Browse tab to say searching is off here.
        """
        template = cls.profile().get('search')
        if not template:
            try:
                template = detect_search(cls._home(), cls.ROOT)
                if template:
                    cls._remember(search=template)
            except Exception as exc:
                print(f'[{cls.NAME}] search box not found: {exc}', flush=True)
        if not template:
            return ''
        return template.replace('{query}', quote((query or '').strip()))

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
