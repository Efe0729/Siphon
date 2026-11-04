"""Constants, the site list and small helpers the app's modules share.

Nothing here opens a window: it can be imported by any part of the app
without pulling in the rest of it."""

import os

from urllib.parse import urlsplit
from siphon.apps.downloads import ACTIVE_STATES, DONE_STATES, QUEUED_STATES
from siphon.core import config
from siphon.i18n.locales import T, get_lang
from siphon.metadata import VERSION
from siphon.sites.base import MirrorsBlockedError

APP_VERSION = VERSION


# issue #24: startup breadcrumbs — no-op if crashlog unavailable
try:
    from siphon.core.crashlog import breadcrumb as _crumb
except Exception:
    def _crumb(msg):
        pass


DEFAULT_CONCURRENT = 2


MAX_CONCURRENT = 32


SLOW_REQUEUE_GRACE_SECONDS = 60


SLOW_REQUEUE_MAX_ATTEMPTS = 3


SETTINGS_INLINE_HELP_WRAP = 620


MAX_VISIBLE_ROWS = 200


ROW_BUILD_BUDGET = 40


MAX_PERSIST_ROWS = 1000


HARD_LOAD_LIMIT = 5000


CSV_PATH = config.queue_csv_path()


# Downloads that were running or queued when the app was closed, in order,
# so they continue automatically on the next start.
RESUME_PATH = os.path.join(os.path.dirname(CSV_PATH), 'resume_on_start.json')


_RUNNING_STATES = ('準備中', '下載中')


_QUEUED_STATES = ('等待中', '等待重試', '已排程')


ERR_BLOCKED = '__cf_blocked__'


# The Browse tab's site picker, in menu order.  Siphon ships with none:
# register_user_sites() fills this from the sites the user added.
SITES = {}


BUILTIN_SITES = ()


# Siphon ships with no sites: every entry here is one the user added.
BUILTIN_SITE_ENTRIES = {}


_VIDEO_EXTS = ('.mp4', '.mkv', '.ts', '.webm', '.mov', '.m4v')


def _section_label(name):
    """A site's section/sort name in the current language (Turkish only;
    tag and category names from the sites stay as they are)."""
    if get_lang() == 'tr':
        from siphon.i18n.tr import SECTION_TR
        return SECTION_TR.get(name, name)
    return name


def _learned_report(result):
    """What the check worked out, in one readable line per thing.

    The user should be able to tell at the moment of adding whether the site
    was understood, instead of finding out days later from an empty search
    or a row named after a notice.
    """
    tick, cross = '\u2713', '\u2717'
    listed = int(result.get('listed') or 0)
    thumbs = int(result.get('thumbs') or 0)
    qualities = [q for q in (result.get('qualities') or []) if q]
    titles = result.get('sample_titles') or []
    lines = [
        f"{tick if listed else cross} " + T('learned_listing', n=listed),
        f"{tick if titles else cross} " + (
            T('learned_titles', example=titles[0]) if titles
            else T('learned_titles_none')),
        f"{tick if qualities else cross} " + (
            T('learned_qualities', list=', '.join(qualities)) if qualities
            else T('learned_qualities_none')),
        f"{tick if thumbs else cross} " + T('learned_thumbs', n=thumbs),
        f"{tick if result.get('search') else cross} " + (
            T('learned_search') if result.get('search')
            else T('learned_search_none')),
    ]
    return '\n'.join(lines)


def _fallback_name(url):
    """Row label before the real title is known.

    The last part of the address is usually the video's own name with dashes
    for spaces ('big-ass-anal'), so it is read back as words; a part that is
    only a number stays as it is.
    """
    last = str(url or '').rstrip('/').split('/')[-1]
    if not last or last.isdigit() or '-' not in last:
        return last
    from siphon.sites import kvs as _kvs
    return _kvs.slug_to_title(last) or last


def builtin_browser_for_host(host):
    """(name, browser) when this app has code written for that site.

    The app ships with no sites in it; these are recipes, used only once the
    user adds a site they happen to cover, because they browse and download it
    better than the general-purpose reader can.
    """
    host = str(host or '').lower().replace('www.', '')
    for name, entry in BUILTIN_SITE_ENTRIES.items():
        browser = entry['browser']
        root_host = (urlsplit(getattr(browser, 'ROOT', '') or '').hostname or '')
        root_host = root_host.lower().replace('www.', '')
        if root_host and (host == root_host or host.endswith('.' + root_host)
                          or root_host.endswith('.' + host)):
            return name, browser
    for name, entry in BUILTIN_SITE_ENTRIES.items():
        for mirror in getattr(entry['browser'], 'MIRRORS', ()) or ():
            mirror_host = (urlsplit(str(mirror)).hostname or str(mirror)).lower()
            if mirror_host.replace('www.', '') == host:
                return name, entry['browser']
    return '', None


def site_catalog():
    """The sites the user added: [{'name','browser','builtin','hidden','host'}].

    ``builtin`` means this app has its own code for that site and is using it
    instead of the general-purpose reader.
    """
    from siphon.sites.genericbrowse import browser_for
    entries = {}
    for entry in config.get_custom_sites():
        host = entry['host']
        name = entry.get('name') or host
        known_name, known = builtin_browser_for_host(host)
        if known is not None:
            entries[known_name] = {'name': known_name, 'browser': known,
                                   'builtin': True, 'host': host}
        else:
            entries[name] = {'name': name, 'browser': browser_for(host, name),
                             'builtin': False, 'host': host}
    order = [name for name in config.get_site_order() if name in entries]
    order += [name for name in entries if name not in order]
    hidden = set(config.get_hidden_sites())
    return [dict(entries[name], hidden=name in hidden) for name in order]


def register_user_sites():
    """Rebuild the Browse tab's site list from the catalog (order kept, sites
    switched off left out)."""
    visible = [entry for entry in site_catalog() if not entry['hidden']]
    SITES.clear()
    for entry in visible:
        SITES[entry['name']] = {'browser': entry['browser']}
    return list(SITES)


def _kvs_browser_for_url(url):
    """(site name, browser) for a pasted link on a KVS-based site, else (None, None)."""
    host = (urlsplit(url).hostname or '').lower()
    for name, entry in SITES.items():
        browser = entry['browser']
        root = getattr(browser, 'ROOT', '')
        root_host = (urlsplit(root).hostname or '').lower() if root else ''
        if root_host and (host == root_host or host == root_host.replace('www.', '', 1)
                          or 'www.' + host == root_host):
            if hasattr(browser, 'page_url') and hasattr(browser, 'fetch_page'):
                return name, browser
    return None, None


DEFAULT_SITE_KEY = ''      # no site until the user adds one


SITES_LOADING_HINT = ''


# Stopped-but-resumable states that keep showing their progress bar, % and
# size, so paused items at 50% and at 0% can be told apart.
_KEEP_PROGRESS_STATES = frozenset({'已暫停', '未完成', '封鎖/解析失敗', '等待重試'})


_STATE_PRIORITY = {
    '下載中': 0,
    '準備中': 4,
    '等待中': 5,
    '等待重試': 5,
    '已排程': 5,
    '已暫停': 6,
    '未完成': 6,
    '封鎖/解析失敗': 7,
    '網址錯誤': 8,
    '已下載': 9,
    '已存在': 9,
    '已取消': 10,
}


def _visible_window(items, cap, positions=None):
    positions = positions or {}

    def finished_first(item):
        # Finished downloads: most recently completed at the top.
        if item.state in DONE_STATES:
            return -(getattr(item, 'completed_at', 0) or item.updated_at or 0)
        return 0

    ordered = sorted(
        enumerate(items),
        key=lambda pair: (_STATE_PRIORITY.get(pair[1].state, 8),
                          positions.get(pair[1].url, 10 ** 9),
                          finished_first(pair[1]), pair[0]))
    return [item for _, item in ordered[:cap]]


def _select_persist(items, cap):
    terminal = {'已下載', '已取消', '網址錯誤', '已存在'}
    resumable = [i for i in items if i.state not in terminal]
    terminal_items = [i for i in items if i.state in terminal]
    budget = max(0, cap - len(resumable))
    kept_terminal = terminal_items[-budget:] if budget > 0 else []
    keep_ids = {id(i) for i in resumable} | {id(i) for i in kept_terminal}
    return [i for i in items if id(i) in keep_ids]


def _download_row_action(item):
    """Return the primary action exposed by a download-row button."""
    if item.state in ACTIVE_STATES or item.state in QUEUED_STATES:
        return 'pause'
    if item.state == '已暫停':
        return 'resume'
    if (item.state in {'未完成', '封鎖/解析失敗', '已取消'} or
            (item.state == '已下載' and bool(item.error))):
        return 'retry'
    if item.state == '已存在':
        return 'force'
    return ''


# ── Browse helper ────────────────────────────────────────────────────
def _fmt_size(value: float) -> str:
    value = float(value or 0)
    if value >= 1024 ** 3:
        return f'{value / 1024 ** 3:.2f} GB'
    return f'{value / 1024 ** 2:.1f} MB'


def _fmt_duration(seconds):
    """'3h 25m', '12m', '45s' (rounded up to the minute above one minute)."""
    seconds = max(0, int(seconds + 0.5))
    if seconds < 60:
        return f'{seconds}s'
    minutes = -(-seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f'{days}d {hours}h'
    return f'{hours}h {minutes:02d}m' if hours else f'{minutes}m'


def _download_size_text(job, done: int, total: int) -> str:
    """'120.5 MB / 300.0 MB' for direct MP4s; for HLS (counted in segments)
    the downloaded bytes plus an estimate of the final size."""
    unit = getattr(job, '_progress_unit', None)
    if unit == 'bytes':
        if total > 0:
            return f'{_fmt_size(done)} / {_fmt_size(total)}'
        return _fmt_size(done) if done else ''
    got = getattr(job, '_bytes_downloaded', 0) or 0
    if not got:
        return ''
    if unit == 'segments' and done > 0 and total > done:
        return f'{_fmt_size(got)} / ~{_fmt_size(got * total / done)}'
    return _fmt_size(got)


def fetch_page_data(browser_cls, url: str) -> dict:
    """Fetch video list from a category/search URL. Returns dict with videos list."""
    try:
        videos = browser_cls.fetch_page(url)
        print(f'[Browse] {url} -> {len(videos)} videos', flush=True)
        return {'videos': videos}
    except MirrorsBlockedError:
        print(f'[Browse] {url} -> blocked (Cloudflare / all mirrors failed)', flush=True)
        raise
    except Exception as e:
        print(f'[Browse error] {url}: {e}', flush=True)
        return {'videos': [], 'error': str(e)}
