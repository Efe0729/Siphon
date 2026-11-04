"""Loading and caching the small preview pictures."""

import io
import threading
import requests

from PIL import Image
from typing import Optional
from urllib.parse import urlsplit
from siphon.core import config
from siphon.core.config import headers
from siphon.core.ssl import SharedSSLAdapter

# ── Thumbnail loader ────────────────────────────────────────────────
_thumb_session: Optional[requests.Session] = None


_thumb_lock = threading.Lock()


_thumb_cache: dict = {}   # url -> PIL.Image (raw, not CTkImage; Tk root needed)


_thumb_cache_lock = threading.Lock()   # guards _thumb_cache mutation across the 4 worker threads


_THUMB_SIZE = (300, 169)  # readable 16:9 cards at the default three-column layout


# Pages the quick read cannot name are handed to the site's own adapter at a
# few seconds each; what does not fit in one sweep waits for the next.
_ADAPTER_TITLE_LIMIT = 24


# How many sweeps a page gets before the row keeps its number: a site that is
# busy or shows a bot check often answers on the second or third try.
_TITLE_ATTEMPTS = 3


def _get_thumb_session() -> requests.Session:
    global _thumb_session
    if _thumb_session is None:
        with _thumb_lock:
            if _thumb_session is None:
                s = requests.Session()
                s.mount('http://', requests.adapters.HTTPAdapter(pool_connections=8,
                                                                 pool_maxsize=32))
                s.mount('https://', SharedSSLAdapter(pool_connections=8,
                                                     pool_maxsize=32))
                _thumb_session = s
    return _thumb_session


def _thumbnail_request_context(url: str, site_key: str = ''):
    """Headers for a thumbnail, and the clearance cookie when one is set.

    A site behind a bot check serves its pictures from behind it too.  The
    clearance the user saved is only ever sent to the exact host it was saved
    for, over https: it is theirs, and it must not leak to a CDN or tracker
    that happens to host an image.
    """
    request_headers = dict(headers)
    cookies = None
    try:
        parsed = urlsplit(str(url or ''))
        host = (parsed.hostname or '').lower().rstrip('.')
    except (TypeError, ValueError):
        return request_headers, cookies
    if parsed.scheme.lower() != 'https' or not host:
        return request_headers, cookies

    # A site usually serves its pictures from a subdomain (img.example.com),
    # so the clearance saved for example.com covers those too — and nothing
    # outside that domain.
    override, zone = {}, ''
    labels = host.split('.')
    for cut in range(len(labels) - 1):
        candidate = '.'.join(labels[cut:])
        found = config.get_cf_override(candidate) or {}
        if found:
            override, zone = found, candidate
            break
    if not override:
        return request_headers, cookies

    request_headers['Referer'] = f'https://{zone}/'
    if override.get('ua'):
        request_headers['User-Agent'] = override['ua']
    if override.get('cookie'):
        cookies = requests.cookies.RequestsCookieJar()
        cookies.set('cf_clearance', override['cookie'],
                    domain='.' + zone, path='/', secure=True)
    return request_headers, cookies


def _clear_thumb(label):
    """Take the picture off a pooled row.

    CustomTkinter keeps its own reference to the image, so dropping ours is
    not enough: the label is told to show nothing and that reference is let
    go, or the row carries the last video's picture onto the next one.
    """
    try:
        label.configure(image=None, text='')
    except Exception:
        return
    for attribute in ('_ctk_img_ref', '_image'):
        try:
            setattr(label, attribute, None)
        except Exception:
            pass


def _fetch_thumbnail(url: str, site_key: str = '') -> Optional[Image.Image]:
    """Download and decode a thumbnail; cached per-URL."""
    if not url:
        return None
    cached = _thumb_cache.get(url)
    if cached is not None:
        return cached
    request_headers, cookies = _thumbnail_request_context(url, site_key)
    attempts = [(request_headers, cookies)]
    if request_headers != headers or cookies is not None:
        # A saved browser context can expire.  Match the listing fetcher's
        # behavior by trying one ordinary request before declaring failure.
        attempts.append((dict(headers), None))

    for attempt_headers, attempt_cookies in attempts:
        request_kwargs = {
            'headers': attempt_headers,
            'timeout': 12,
            **config.proxy_request_kwargs(),
        }
        if attempt_cookies is not None:
            request_kwargs['cookies'] = attempt_cookies
        response = None
        try:
            response = _get_thumb_session().get(url, **request_kwargs)
            if response.status_code != 200:
                continue
            img = Image.open(io.BytesIO(response.content)).convert('RGB')
            img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
        except Exception:
            continue
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
        with _thumb_cache_lock:
            _thumb_cache[url] = img
            # Limit cache growth — under the lock so a concurrent insert can't resize the
            # dict mid-iteration (RuntimeError: dictionary changed size during iteration).
            if len(_thumb_cache) > 200:
                for k in list(_thumb_cache.keys())[:40]:
                    _thumb_cache.pop(k, None)
        return img
    return None
