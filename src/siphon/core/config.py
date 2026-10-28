import json
import os
import re
import threading
from string import Formatter
from urllib.parse import urlsplit

from siphon.core.paths import product_data_dir


headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}

MIRRORS = {
    'site': ['example.com', 'site.ai', 'example.com', 'example.com'],
    'site':  ['example.com', 'fs1.app'],
    'site': ['example.com'],
}

# Cloudflare answers bursts of example.com searches with an HTTP 429 challenge
# (measured: about ten searches within ten seconds from one IP; video and
# listing pages were not limited) that lifts after a few quiet seconds. Wait
# these seconds and retry the same host instead of reporting a block.
RATE_LIMIT_WAITS = {
    'site': (10, 20),
}

_cf_lock = threading.Lock()
_prefs_lock = threading.Lock()
_proxy_lock = threading.Lock()
_PROXY_UNSET = object()
_proxy_url_cache = _PROXY_UNSET
_proxy_mode_cache = _PROXY_UNSET
_system_proxy_cache = _PROXY_UNSET
CF_OVERRIDES = {}
VALID_RESOLUTION_PREFS = {'highest', 'lowest', '1080', '720', '480', '360'}
VALID_SUBTITLE_PREFS = {'none', 'ja', 'en', 'zh', 'all'}
VALID_FILENAME_MODES = {'full-title', 'code-only'}
DEFAULT_FILENAME_TEMPLATE = '{title}'
FILENAME_TEMPLATE_FIELDS = frozenset({'title', 'code', 'site'})
VALID_RECOGNITION_QUALITIES = {'auto', 'quality', 'balanced', 'fast'}
DEFAULT_DOWNLOAD_CONCURRENCY = 2
MIN_DOWNLOAD_CONCURRENCY = 1
MAX_DOWNLOAD_CONCURRENCY = 32
DEFAULT_MAX_WORKERS_PER_VIDEO = (
    min(os.cpu_count() * 2, 16) if os.cpu_count() else 8)
MIN_WORKERS_PER_VIDEO = 1
MAX_WORKERS_PER_VIDEO = 16
DEFAULT_SLOW_REQUEUE_KBPS = 0
MIN_SLOW_REQUEUE_KBPS = 0
MAX_SLOW_REQUEUE_KBPS = 100000
DEFAULT_MINIMUM_FREE_GB = 0.5
MAX_MINIMUM_FREE_GB = 1024.0
DEFAULT_AUTO_RETRY_COUNT = 2
MAX_AUTO_RETRY_COUNT = 10
MAX_SPEED_LIMIT_MBPS = 10000.0
VALID_PROXY_SCHEMES = {
    'http', 'https', 'socks4', 'socks4a', 'socks5', 'socks5h',
}
VALID_PROXY_MODES = {'manual', 'system', 'direct'}


def _cf_store_path():
    return str(product_data_dir() / 'cf_overrides.json')


def _ui_prefs_path():
    return os.path.join(os.path.dirname(_cf_store_path()), 'ui_prefs.json')


def queue_csv_path():
    return os.path.join(os.path.dirname(_ui_prefs_path()), 'download_queue.csv')


# Settings are read constantly (every queued row asks for the quality, the
# template, the limits...), and reading means unscrambling the file, so the
# last read is kept until the file changes.
_prefs_cache = {'key': None, 'data': {}}


def _load_prefs():
    path = _ui_prefs_path()
    try:
        stamp = os.stat(path)
        key = (path, stamp.st_mtime_ns, stamp.st_size)
    except OSError:
        key = (path, 0, 0)
    if _prefs_cache['key'] == key:
        return dict(_prefs_cache['data'])
    try:
        from siphon.core import secretstore
        text = secretstore.read_text(path)
        raw = json.loads(text) if text.strip() else {}
    except Exception:
        return {}
    if isinstance(raw, str):
        raw = {'theme': raw}
    if not isinstance(raw, dict):
        return {}
    _prefs_cache['key'], _prefs_cache['data'] = key, dict(raw)
    return dict(raw)


_prefs_save_lock = __import__('threading').Lock()


def _save_prefs(prefs):
    """Atomic save.  Serialised between threads, a unique temp file per
    write, and a few retries: on Windows another save, an antivirus scan or
    a sync tool can briefly lock the file (WinError 32)."""
    import time as _time
    import uuid as _uuid
    path = _ui_prefs_path()
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    from siphon.core import secretstore
    with _prefs_save_lock:
        secretstore.write_text(
            path, json.dumps(prefs, ensure_ascii=False, indent=2, sort_keys=True))
        try:
            stamp = os.stat(path)
            _prefs_cache['key'] = (path, stamp.st_mtime_ns, stamp.st_size)
            _prefs_cache['data'] = dict(prefs)
        except OSError:
            _prefs_cache['key'] = None


def get_theme():
    mode = _load_prefs().get('theme')
    if isinstance(mode, str):
        mode = mode.strip().lower()
        if mode in {'system', 'light', 'dark'}:
            return mode
    return 'system'


def set_theme(mode):
    mode = (mode or '').strip().lower()
    if mode not in {'system', 'light', 'dark'}:
        mode = 'system'
    try:
        with _prefs_lock:
            prefs = _load_prefs()
            prefs['theme'] = mode
            _save_prefs(prefs)
    except Exception:
        pass


def get_ui_lang():
    code = _load_prefs().get('lang')
    if isinstance(code, str):
        code = code.strip()
        if code in {'en', 'tr', 'zh', 'zh-Hans', 'ja', 'th'}:
            return code
    return None


def set_ui_lang(code):
    code = (code or '').strip()
    if code not in {'en', 'tr', 'zh', 'zh-Hans', 'ja', 'th'}:
        code = 'en'
    try:
        with _prefs_lock:
            prefs = _load_prefs()
            prefs['lang'] = code
            _save_prefs(prefs)
    except Exception:
        pass


def get_resolution_pref():
    pref = _load_prefs().get('resolution')
    if isinstance(pref, str):
        pref = pref.strip().lower()
        if pref in VALID_RESOLUTION_PREFS:
            return pref
    return 'highest'


def set_resolution_pref(pref):
    pref = str(pref or '').strip().lower()
    if pref not in VALID_RESOLUTION_PREFS:
        pref = 'highest'
    try:
        with _prefs_lock:
            prefs = _load_prefs()
            prefs['resolution'] = pref
            _save_prefs(prefs)
    except Exception:
        pass


def normalize_filename_mode(value):
    """Return the shared output filename mode, preserving the v3 default."""
    mode = str(value or '').strip().lower().replace('_', '-')
    aliases = {
        '': 'full-title',
        'full': 'full-title',
        'title': 'full-title',
        'complete': 'full-title',
        'code': 'code-only',
        'jav-code': 'code-only',
        'number': 'code-only',
    }
    mode = aliases.get(mode, mode)
    if mode in VALID_FILENAME_MODES:
        return mode
    return 'full-title'

def _normalize_download_concurrency(value):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = DEFAULT_DOWNLOAD_CONCURRENCY
    return max(MIN_DOWNLOAD_CONCURRENCY,
               min(parsed, MAX_DOWNLOAD_CONCURRENCY))

def get_filename_mode():
    """Return full-title (default) or code-only for every downloader UI."""
    return normalize_filename_mode(_load_prefs().get('filename_mode'))


def set_filename_mode(value):
    """Persist the shared filename mode without disturbing other preferences."""
    mode = normalize_filename_mode(value)
    try:
        with _prefs_lock:
            prefs = _load_prefs()
            prefs['filename_mode'] = mode
            _save_prefs(prefs)
    except Exception:
        pass
    return mode


def normalize_filename_template(value):
    """Validate a conservative filename template used by new jobs."""
    template = str(value or '').strip() or DEFAULT_FILENAME_TEMPLATE
    if (len(template) > 160 or re.search(r'[\x00-\x1f\x7f]', template) or
            any(char in template for char in '\\/<>:"|?*')):
        return DEFAULT_FILENAME_TEMPLATE
    try:
        fields = []
        for _literal, field, specification, conversion in Formatter().parse(template):
            if field is None:
                continue
            # Formatting can resolve attributes/indices even without eval.
            # Accept only the complete, literal field names documented here.
            if (field not in FILENAME_TEMPLATE_FIELDS or specification or
                    conversion is not None):
                return DEFAULT_FILENAME_TEMPLATE
            fields.append(field)
        rendered = template.format(title='title', code='code', site='site')
    except (KeyError, ValueError, IndexError, AttributeError):
        return DEFAULT_FILENAME_TEMPLATE
    if not rendered.strip() or not ({'title', 'code'} & set(fields)):
        return DEFAULT_FILENAME_TEMPLATE
    return template


def get_filename_template():
    return normalize_filename_template(
        _load_prefs().get('filename_template'))


def set_filename_template(value):
    template = normalize_filename_template(value)
    try:
        with _prefs_lock:
            prefs = _load_prefs()
            prefs['filename_template'] = template
            _save_prefs(prefs)
    except Exception:
        pass
    return template


def normalize_download_schedule(value):
    schedule = str(value or '').strip()
    if not schedule:
        return ''
    if not re.fullmatch(r'(?:[01]?\d|2[0-3]):[0-5]\d', schedule):
        return ''
    hour, minute = schedule.split(':', 1)
    return f'{int(hour):02d}:{minute}'


def get_download_schedule():
    return normalize_download_schedule(
        _load_prefs().get('download_schedule'))


def set_download_schedule(value):
    raw = str(value or '').strip()
    schedule = normalize_download_schedule(raw)
    if raw and not schedule:
        raise ValueError('Schedule must use HH:MM')
    with _prefs_lock:
        prefs = _load_prefs()
        prefs['download_schedule'] = schedule
        _save_prefs(prefs)
    return schedule


def normalize_minimum_free_gb(value):
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        parsed = DEFAULT_MINIMUM_FREE_GB
    return max(0.0, min(parsed, MAX_MINIMUM_FREE_GB))


def get_minimum_free_gb():
    return normalize_minimum_free_gb(
        _load_prefs().get('minimum_free_gb'))


def set_minimum_free_gb(value):
    normalized = normalize_minimum_free_gb(value)
    with _prefs_lock:
        prefs = _load_prefs()
        prefs['minimum_free_gb'] = normalized
        _save_prefs(prefs)
    return normalized


def normalize_auto_retry_count(value):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = DEFAULT_AUTO_RETRY_COUNT
    return max(0, min(parsed, MAX_AUTO_RETRY_COUNT))


def get_auto_retry_count():
    return normalize_auto_retry_count(
        _load_prefs().get('auto_retry_count'))


def set_auto_retry_count(value):
    normalized = normalize_auto_retry_count(value)
    with _prefs_lock:
        prefs = _load_prefs()
        prefs['auto_retry_count'] = normalized
        _save_prefs(prefs)
    return normalized


def get_notify_on_complete():
    value = _load_prefs().get('notify_on_complete', True)
    if isinstance(value, str):
        return value.strip().lower() not in {'0', 'false', 'no', 'off', ''}
    return bool(value)


def set_notify_on_complete(value):
    if isinstance(value, str):
        normalized = value.strip().lower() not in {
            '0', 'false', 'no', 'off', '',
        }
    else:
        normalized = bool(value)
    with _prefs_lock:
        prefs = _load_prefs()
        prefs['notify_on_complete'] = normalized
        _save_prefs(prefs)
    return normalized


def browser_notice_seen():
    """True once the user has been told that Siphon drives a real browser."""
    return bool(_load_prefs().get('browser_notice_seen', False))


def set_browser_notice_seen(value=True):
    with _prefs_lock:
        prefs = _load_prefs()
        prefs['browser_notice_seen'] = bool(value)
        _save_prefs(prefs)


def normalize_speed_limit_mbps(value):
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        parsed = 0.0
    return max(0.0, min(parsed, MAX_SPEED_LIMIT_MBPS))


def get_speed_limit_mbps():
    return normalize_speed_limit_mbps(
        _load_prefs().get('speed_limit_mbps'))


def set_speed_limit_mbps(value):
    normalized = normalize_speed_limit_mbps(value)
    with _prefs_lock:
        prefs = _load_prefs()
        prefs['speed_limit_mbps'] = normalized
        _save_prefs(prefs)
    return normalized


def get_download_directory():
    value = _load_prefs().get('download_directory')
    if isinstance(value, str):
        value = value.strip()
        if value and len(value) <= 32767 and not re.search(
                r'[\x00-\x1f\x7f]', value):
            return value
    return ''


def set_download_directory(value):
    path = str(value or '').strip()
    if (not path or len(path) > 32767 or
            re.search(r'[\x00-\x1f\x7f]', path)):
        return get_download_directory()
    with _prefs_lock:
        prefs = _load_prefs()
        prefs['download_directory'] = path
        _save_prefs(prefs)
    return path


def get_download_concurrency():
    """Return the persisted number of simultaneous video downloads."""
    return _normalize_download_concurrency(
        _load_prefs().get('download_concurrency'))


def set_download_concurrency(value):
    """Persist a clamped simultaneous-video-download limit."""
    normalized = _normalize_download_concurrency(value)
    try:
        with _prefs_lock:
            prefs = _load_prefs()
            prefs['download_concurrency'] = normalized
            _save_prefs(prefs)
    except Exception:
        pass
    return normalized


def normalize_max_workers_per_video(value):
    """Return a safe per-video segment worker count (1–16)."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = DEFAULT_MAX_WORKERS_PER_VIDEO
    return max(MIN_WORKERS_PER_VIDEO, min(parsed, MAX_WORKERS_PER_VIDEO))


def get_max_workers_per_video():
    """Return the persisted number of segment workers used by each video."""
    return normalize_max_workers_per_video(
        _load_prefs().get('max_workers_per_video'))


def set_max_workers_per_video(value):
    """Persist a clamped per-video segment worker limit for every client."""
    normalized = normalize_max_workers_per_video(value)
    try:
        with _prefs_lock:
            prefs = _load_prefs()
            prefs['max_workers_per_video'] = normalized
            _save_prefs(prefs)
    except Exception:
        pass
    return normalized


# ── Per-site connections per video ─────────────────────────────────────────
# Sites listed in the Settings site picker (menu order) and the most
# connections each can use per video.  Direct-MP4 sites are capped by their
# downloader; HLS sites (site, site) download segments in parallel.
WORKER_SITES = ['site', 'site', 'site', 'site', 'site', 'site',
                'site', 'site', 'site', 'Tranny.one', 'site', 'site', 'site', 'site', 'site']
SITE_WORKER_CAPS = {'site': 4, 'site': 8, 'site': 8, 'site': 8,
                    'site': 8, 'site': 8, 'site': 8, 'site': 8,
                    'site': 8, 'Tranny.one': 8, 'site': 8, 'site': 8,
                    'site': 4, 'site': 4}


def site_key_for_url(url):
    host = (urlsplit(str(url or '')).hostname or '').lower()
    if 'site' in host:
        return 'site'
    if host in {'example.com', 'example.com', 'fs1.app', 'www.fs1.app'}:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    if host.endswith('tranny.one'):
        return 'Tranny.one'
    if 'example.com' in host or 'site' in host or 'porn-xp' in host:
        return 'site'
    if 'site' in host:
        return 'site'
    return ''


def site_worker_cap(site):
    return SITE_WORKER_CAPS.get(site, MAX_WORKERS_PER_VIDEO)


def get_site_workers_overrides():
    raw = _load_prefs().get('site_workers_per_video')
    if not isinstance(raw, dict):
        return {}
    result = {}
    for site, value in raw.items():
        if site in WORKER_SITES:
            result[site] = min(normalize_max_workers_per_video(value),
                               site_worker_cap(site))
    return result


def get_max_workers_for_site(site):
    """The site's own setting if one was saved, otherwise the global default."""
    override = get_site_workers_overrides().get(site)
    if override is not None:
        return override
    return min(get_max_workers_per_video(), site_worker_cap(site)) if site \
        else get_max_workers_per_video()


def set_site_workers(site, value):
    """Save a per-site value; value None removes it (site uses the default)."""
    if site not in WORKER_SITES:
        raise ValueError(site)
    with _prefs_lock:
        prefs = _load_prefs()
        table = prefs.get('site_workers_per_video')
        table = dict(table) if isinstance(table, dict) else {}
        if value is None:
            table.pop(site, None)
            normalized = None
        else:
            normalized = min(normalize_max_workers_per_video(value),
                             site_worker_cap(site))
            table[site] = normalized
        prefs['site_workers_per_video'] = table
        _save_prefs(prefs)
    return normalized


def normalize_slow_requeue_kbps(value):
    """Return a safe slow-download auto-requeue threshold in KB/s (0 = off)."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = DEFAULT_SLOW_REQUEUE_KBPS
    return max(MIN_SLOW_REQUEUE_KBPS, min(parsed, MAX_SLOW_REQUEUE_KBPS))


def get_slow_requeue_kbps():
    """Return the persisted slow-download auto-requeue threshold (KB/s)."""
    return normalize_slow_requeue_kbps(
        _load_prefs().get('slow_requeue_kbps'))


def set_slow_requeue_kbps(value):
    """Persist a clamped slow-download auto-requeue threshold for every client."""
    normalized = normalize_slow_requeue_kbps(value)
    try:
        with _prefs_lock:
            prefs = _load_prefs()
            prefs['slow_requeue_kbps'] = normalized
            _save_prefs(prefs)
    except Exception:
        pass
    return normalized


def normalize_proxy_url(raw):
    """Validate one app-scoped proxy URL; bare host:port means HTTP."""
    value = str(raw or '').strip()
    if not value:
        return ''
    if re.search(r'[\x00-\x20\x7f]', value):
        raise ValueError('Proxy URL cannot contain whitespace or control characters')
    if '://' not in value:
        value = 'http://' + value
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        parsed.port  # force validation of malformed/out-of-range ports
    except (TypeError, ValueError):
        raise ValueError('Invalid proxy URL') from None
    if scheme not in VALID_PROXY_SCHEMES or not hostname:
        raise ValueError('Unsupported or incomplete proxy URL')
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('Proxy URL must not contain a path, query, or fragment')
    return value


def get_proxy_url():
    global _proxy_url_cache
    if _proxy_url_cache is _PROXY_UNSET:
        with _proxy_lock:
            if _proxy_url_cache is _PROXY_UNSET:
                try:
                    value = normalize_proxy_url(_load_prefs().get('proxy_url'))
                except ValueError:
                    value = ''
                _proxy_url_cache = value
    return _proxy_url_cache


def set_proxy_url(raw):
    global _proxy_mode_cache, _proxy_url_cache
    value = normalize_proxy_url(raw)
    with _prefs_lock:
        prefs = _load_prefs()
        if value:
            prefs['proxy_url'] = value
            prefs['proxy_mode'] = 'manual'
        else:
            prefs.pop('proxy_url', None)
            prefs['proxy_mode'] = 'direct'
        _save_prefs(prefs)
    with _proxy_lock:
        _proxy_url_cache = value
        _proxy_mode_cache = 'manual' if value else 'direct'
    return value


def get_proxy_mode():
    """Return manual/system/direct, migrating legacy preferences in memory."""
    global _proxy_mode_cache
    if _proxy_mode_cache is _PROXY_UNSET:
        with _proxy_lock:
            if _proxy_mode_cache is _PROXY_UNSET:
                prefs = _load_prefs()
                mode = str(prefs.get('proxy_mode') or '').strip().lower()
                if mode not in VALID_PROXY_MODES:
                    try:
                        legacy_url = normalize_proxy_url(
                            prefs.get('proxy_url'))
                    except ValueError:
                        legacy_url = ''
                    mode = 'manual' if legacy_url else 'direct'
                _proxy_mode_cache = mode
    return _proxy_mode_cache


def set_proxy_mode(mode):
    """Persist the routing mode without copying detected system settings."""
    global _proxy_mode_cache, _system_proxy_cache
    value = str(mode or '').strip().lower()
    if value not in VALID_PROXY_MODES:
        raise ValueError('Proxy mode must be manual, system, or direct')
    with _prefs_lock:
        prefs = _load_prefs()
        prefs['proxy_mode'] = value
        _save_prefs(prefs)
    with _proxy_lock:
        _proxy_mode_cache = value
        if value == 'system':
            _system_proxy_cache = _PROXY_UNSET
    return value


def parse_windows_proxy_server(raw):
    """Translate a Windows ProxyServer value into requests-style routes."""
    value = str(raw or '').strip()
    if not value:
        return {}

    if '=' not in value and ';' not in value:
        try:
            proxy = normalize_proxy_url(value)
        except ValueError:
            return {}
        return {'http': proxy, 'https': proxy}

    routes = {}
    socks_proxy = ''
    for item in value.split(';'):
        if '=' not in item:
            continue
        protocol, address = item.split('=', 1)
        protocol = protocol.strip().lower()
        address = address.strip()
        if protocol not in {'http', 'https', 'socks'} or not address:
            continue
        if protocol == 'socks' and '://' not in address:
            address = 'socks4://' + address
        try:
            proxy = normalize_proxy_url(address)
        except ValueError:
            continue
        if protocol == 'socks':
            socks_proxy = proxy
        else:
            routes[protocol] = proxy

    if socks_proxy:
        routes.setdefault('http', socks_proxy)
        routes.setdefault('https', socks_proxy)
    return routes


def _read_windows_proxy_settings():
    """Read the current user's manual WinINet proxy without changing it."""
    settings = {'enabled': False, 'server': '', 'pac_url': ''}
    if os.name != 'nt':
        return settings
    try:
        import winreg
        path = (
            r'Software\Microsoft\Windows\CurrentVersion'
            r'\Internet Settings'
        )
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            try:
                enabled = winreg.QueryValueEx(key, 'ProxyEnable')[0]
                settings['enabled'] = (
                    isinstance(enabled, int) and enabled != 0)
            except OSError:
                pass
            try:
                server = winreg.QueryValueEx(key, 'ProxyServer')[0]
                if isinstance(server, str):
                    settings['server'] = server
            except OSError:
                pass
            try:
                pac_url = winreg.QueryValueEx(key, 'AutoConfigURL')[0]
                if isinstance(pac_url, str):
                    settings['pac_url'] = pac_url.strip()
            except OSError:
                pass
    except (ImportError, OSError, TypeError, ValueError):
        pass
    return settings


def _redact_proxy_url(value):
    """Return a display-safe endpoint with any user information removed."""
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ''
        if ':' in hostname and not hostname.startswith('['):
            hostname = f'[{hostname}]'
        port = f':{parsed.port}' if parsed.port is not None else ''
        return f'{parsed.scheme}://{hostname}{port}'
    except (TypeError, ValueError):
        return ''


def _detect_windows_proxy_state():
    settings = _read_windows_proxy_settings()
    routes = {}
    if settings.get('enabled'):
        routes = parse_windows_proxy_server(settings.get('server'))
    if routes:
        selected = routes.get('https') or routes.get('http') or ''
        return routes, _redact_proxy_url(selected), 'detected'
    if settings.get('pac_url'):
        # A PAC URL points to executable configuration, not a proxy endpoint.
        return {}, '', 'pac'
    if settings.get('enabled'):
        return {}, '', 'invalid'
    return {}, '', 'disabled'


def detect_windows_proxy_url():
    """Detect once and return a credential-free endpoint plus status."""
    _routes, display_url, status = _detect_windows_proxy_state()
    return display_url, status


def refresh_system_proxy():
    """Refresh the in-memory system proxy used by System mode."""
    global _system_proxy_cache
    routes, display_url, status = _detect_windows_proxy_state()
    with _proxy_lock:
        _system_proxy_cache = (dict(routes), status)
    return display_url, status


def refresh_windows_proxy():
    """Compatibility alias for callers that name the Windows source."""
    return refresh_system_proxy()


def _get_cached_system_proxy():
    global _system_proxy_cache
    if _system_proxy_cache is _PROXY_UNSET:
        routes, _display_url, status = _detect_windows_proxy_state()
        with _proxy_lock:
            if _system_proxy_cache is _PROXY_UNSET:
                _system_proxy_cache = (dict(routes), status)
    with _proxy_lock:
        routes, status = _system_proxy_cache
        return dict(routes), status


def proxy_request_kwargs():
    """Return explicit routes for requests and curl_cffi.

    Empty routes are intentional: both clients otherwise inherit proxy
    environment variables, which would make the Direct mode misleading.
    """
    direct_routes = {'http': '', 'https': '', 'all': ''}
    mode = get_proxy_mode()
    if mode == 'direct':
        return {'proxies': direct_routes}
    if mode == 'system':
        routes, _status = _get_cached_system_proxy()
        direct_routes.update(routes)
        return {'proxies': direct_routes}
    value = get_proxy_url()
    if not value:
        return {'proxies': direct_routes}
    direct_routes.update({'http': value, 'https': value})
    return {'proxies': direct_routes}


def _parse_cf_clearance(raw):
    if raw is None:
        return ''
    s = re.sub(r'[\x00-\x1f\x7f]+', '', str(raw).strip())
    if not s:
        return ''
    if 'cf_clearance=' in s:
        m = re.search(r'cf_clearance=([^;,\s]+)', s)
        return m.group(1) if m else ''
    return s.strip('\'"')


def _norm_host(host):
    h = (host or '').strip().lower().rstrip('.')
    if ':' in h:
        h = h.split(':', 1)[0].rstrip('.')
    return h


def get_custom_sites():
    """Sites the user added themselves: [{'host', 'name'}], oldest first."""
    raw = _load_prefs().get('custom_sites')
    result = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict):
            host = _norm_host(entry.get('host'))
            if host and host not in {e['host'] for e in result}:
                result.append({'host': host, 'name': str(entry.get('name') or '').strip()})
    return result


def is_custom_site(host):
    host = _norm_host(host)
    if not host:
        return False
    for entry in get_custom_sites():
        if host == entry['host'] or host.endswith('.' + entry['host']):
            return True
    return False


def custom_site_name(host):
    host = _norm_host(host)
    for entry in get_custom_sites():
        if host == entry['host'] or host.endswith('.' + entry['host']):
            return entry['name'] or entry['host']
    return ''


def add_custom_site(host, name=''):
    host = _norm_host(host)
    if not host:
        return False
    sites = [e for e in get_custom_sites() if e['host'] != host]
    sites.append({'host': host, 'name': str(name or '').strip()})
    prefs = _load_prefs()
    prefs['custom_sites'] = sites
    _save_prefs(prefs)
    return True


def remove_custom_site(host):
    host = _norm_host(host)
    sites = [e for e in get_custom_sites() if e['host'] != host]
    prefs = _load_prefs()
    prefs['custom_sites'] = sites
    _save_prefs(prefs)
    return True


def get_site_templates():
    """Layouts learned from a saved page: [{'name','markers',...}].

    Each one is a site builder's own recipe — once a site has been learned,
    every other site built the same way is recognised from these markers.
    """
    raw = _load_prefs().get('site_templates')
    result = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict) and entry.get('markers'):
            result.append(dict(entry))
    return result


def save_site_template(name, markers, profile):
    name = str(name or '').strip()
    markers = [str(m) for m in (markers or []) if str(m)]
    if not name or not markers:
        return False
    entry = {'name': name, 'markers': markers[:8]}
    entry.update({k: v for k, v in dict(profile or {}).items()
                  if isinstance(v, str) and v})
    templates = [t for t in get_site_templates() if t.get('name') != name]
    templates.append(entry)
    prefs = _load_prefs()
    prefs['site_templates'] = templates[-30:]
    _save_prefs(prefs)
    return True


def remove_site_template(name):
    templates = [t for t in get_site_templates() if t.get('name') != str(name or '')]
    prefs = _load_prefs()
    prefs['site_templates'] = templates
    _save_prefs(prefs)


def get_site_order():
    """The order the user put the Browse sites in (names; may be partial)."""
    raw = _load_prefs().get('site_order')
    return [str(name) for name in raw if str(name)] if isinstance(raw, list) else []


def set_site_order(names):
    prefs = _load_prefs()
    prefs['site_order'] = [str(name) for name in names if str(name)]
    _save_prefs(prefs)


def get_hidden_sites():
    """Sites switched off: still listed in Settings, absent from Browse."""
    raw = _load_prefs().get('hidden_sites')
    return [str(name) for name in raw if str(name)] if isinstance(raw, list) else []


def set_site_hidden(name, hidden):
    name = str(name or '')
    if not name:
        return
    hidden_names = [n for n in get_hidden_sites() if n != name]
    if hidden:
        hidden_names.append(name)
    prefs = _load_prefs()
    prefs['hidden_sites'] = hidden_names
    _save_prefs(prefs)


def is_site_hidden(name):
    return str(name or '') in get_hidden_sites()


def get_site_profile(host):
    """What the app worked out about a user-added site (how its listings,
    paging and search are built)."""
    raw = _load_prefs().get('site_profiles')
    entry = (raw or {}).get(_norm_host(host)) if isinstance(raw, dict) else None
    return dict(entry) if isinstance(entry, dict) else {}


def set_site_profile(host, profile):
    host = _norm_host(host)
    if not host:
        return
    prefs = _load_prefs()
    profiles = prefs.get('site_profiles')
    profiles = dict(profiles) if isinstance(profiles, dict) else {}
    profiles[host] = {k: v for k, v in dict(profile or {}).items()
                      if isinstance(v, str) and v}
    prefs['site_profiles'] = profiles
    _save_prefs(prefs)


def get_cf_override(host):
    with _cf_lock:
        entry = CF_OVERRIDES.get(_norm_host(host))
        return dict(entry) if entry else None


def cf_override_hosts():
    with _cf_lock:
        return sorted(CF_OVERRIDES.keys())


def set_cf_override(host, cookie, ua):
    global CF_OVERRIDES
    h = _norm_host(host)
    if not h:
        return
    entry = {}
    ck = _parse_cf_clearance(cookie)
    if ck:
        entry['cookie'] = ck
    ua = (ua or '').strip()
    if ua:
        entry['ua'] = ua
    with _cf_lock:
        next_overrides = dict(CF_OVERRIDES)
        if entry:
            next_overrides[h] = entry
        else:
            next_overrides.pop(h, None)
        CF_OVERRIDES = next_overrides
    save_cf_overrides()


def clear_cf_override(host):
    set_cf_override(host, '', '')


def load_cf_overrides():
    global CF_OVERRIDES
    path = _cf_store_path()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except FileNotFoundError:
        with _cf_lock:
            CF_OVERRIDES = {}
        return
    except Exception:
        try:
            os.replace(path, path + '.bak')
        except Exception:
            pass
        with _cf_lock:
            CF_OVERRIDES = {}
        return

    parsed = {}
    if isinstance(raw, dict):
        for host, entry in raw.items():
            h = _norm_host(host)
            if not h or not isinstance(entry, dict):
                continue
            clean = {}
            cookie = entry.get('cookie')
            ua = entry.get('ua')
            if isinstance(cookie, str):
                cookie = _parse_cf_clearance(cookie)
                if cookie:
                    clean['cookie'] = cookie
            if isinstance(ua, str) and ua.strip():
                clean['ua'] = ua.strip()
            if clean:
                parsed[h] = clean
    with _cf_lock:
        CF_OVERRIDES = parsed


def save_cf_overrides():
    try:
        path = _cf_store_path()
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        with _cf_lock:
            snapshot = dict(CF_OVERRIDES)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        pass


try:
    load_cf_overrides()
except Exception:
    pass
