#!/usr/bin/env python
# coding: utf-8

import re
import html
import os
import time
import concurrent.futures
import base64
import codecs
import json
import ipaddress
import cloudscraper
try:
    from curl_cffi import requests as cffi_requests
    _use_cffi = True
except ImportError:
    _use_cffi = False
import threading as _threading
from urllib.parse import quote, urlsplit, urljoin, parse_qsl, urlencode
from siphon.sites.base import *
from siphon.sites.base import _get_session
from bs4 import BeautifulSoup
from siphon.core import config


_EMBED_GATEWAY = 'https://embed.example.invalid/resolve?c={}'
_BLOCKED_MSG = "All mirrors are blocked by Cloudflare (network/IP reputation; try a VPN or another network)"
_DIRECT_RANGE_WORKERS = 4
_DIRECT_RANGE_RETRIES = 4
_DIRECT_RETRY_BASE_DELAY = 1.0

_browser_scraper = None
_browser_scraper_lock = _threading.Lock()

def _unpack_js_eval(script_text):
    """Decode Dean Edwards p,a,c,k,e,d packer."""
    match = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{.*?\}\('(.*?)',\s*(\d+),\s*(\d+),\s*'([^']*)'\s*\.split\('\|'\)",
        script_text, re.DOTALL
    )
    if not match:
        return None
    packed, a, c, keys_str = match.group(1), int(match.group(2)), int(match.group(3)), match.group(4).split('|')
    # Guard against malformed packer params: base<=1 makes to_base loop forever;
    # an absurd `c` would allocate an unbounded lookup dict. Bail on either.
    if a <= 1 or c < 0 or c > 200000:
        return None

    def to_base(n, base):
        digits = '0123456789abcdefghijklmnopqrstuvwxyz'
        if n == 0: return '0'
        s = ''
        while n:
            s = digits[n % base] + s
            n //= base
        return s

    lookup = {to_base(i, a): (keys_str[i] if i < len(keys_str) and keys_str[i] else to_base(i, a))
              for i in range(c)}
    return re.sub(r'\b(\w+)\b', lambda m: lookup.get(m.group(0), m.group(0)), packed)


def _make_scraper():
    """Fresh scraper: curl_cffi (Cloudflare-capable) if available, else cloudscraper."""
    if _use_cffi:
        return cffi_requests.Session(impersonate='chrome')
    return cloudscraper.create_scraper(browser=request_headers, delay=10)


def _extract_tv_link(html_text):
    soup = BeautifulSoup(html_text, 'html.parser')
    for a in soup.select('a[data-link]'):
        if a.get_text(strip=True) == 'TV':
            return a.get('data-link', '')
    return None


def _extract_m3u8(body):
    body = body.replace('\\/', '/')
    m = re.search(r'urlPlay[\s=:\'"]+(?P<u>https?://[^\s\'"\\]+\.m3u8[^\s\'"\\]*)', body)
    if m:
        return m.group('u')
    m = re.search(r'https?://[^\s\'"\\]+\.m3u8[^\s\'"\\]*', body)
    return m.group(0) if m else None


def _extract_title(soup):
    h1 = soup.find('h1')
    return h1.get_text(strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else '')


def _strip_fake_header(data):
    """Some servers hide MPEG-TS segments behind a fake PNG header. Return the stream
    from the first valid MPEG-TS sync (0x47 on a 188-byte stride). Plain TS is returned unchanged."""
    if data[:1] == b'\x47':
        return data
    limit = min(len(data) - 188 * 4 - 1, 8000)
    i = 0
    while 0 <= i <= limit:
        j = data.find(b'\x47', i)
        if j < 0 or j > limit:
            break
        if all(data[j + 188 * n] == 0x47 for n in range(5)):
            return data[j:]
        i = j + 1
    return b''


def _server_links(html_text):
    """Return {SERVER_NAME: data_link} for every .btn-server anchor on a
    video page, including EVS, VAS and LUC added in 2026."""
    soup = BeautifulSoup(html_text, 'html.parser')
    out = {}
    for a in soup.select('a.btn-server[data-link]'):
        name = a.get_text(strip=True).upper()
        link = a.get('data-link', '')
        if name and link and name not in out:
            out[name] = link
    return out


def _streamtape_direct_url(html_text):
    """Extract the direct progressive-MP4 URL from a Streamtape embed page.
    Streamtape overwrites #robotlink via JS:  'PREFIX' + ('SUFFIX').substring(a)[.substring(b)]
    — the static div text is a decoy; only the JS-computed value carries the live token."""
    m = re.search(
        r"getElementById\(\s*['\"]robotlink['\"]\s*\)\.innerHTML\s*=\s*"
        r"['\"]([^'\"]*)['\"]\s*\+\s*(?:['\"]{2}\s*\+\s*)?"
        r"\(\s*['\"]([^'\"]*)['\"]\s*\)((?:\.substring\(\s*\d+\s*\))+)",
        html_text)
    if not m:
        return None
    prefix, suffix, subs = m.group(1), m.group(2), m.group(3)
    s = suffix
    for off in re.findall(r'substring\(\s*(\d+)\s*\)', subs):
        s = s[int(off):]
    link = (prefix + s).lstrip('/')
    if 'get_video' not in link:
        return None
    return 'https://' + link


def _extract_packed_m3u8(html_text):
    """Read FST/EVS/LUC packed player data without executing remote JavaScript."""
    for script in re.findall(r'<script[^>]*>(.*?)</script>', html_text, re.DOTALL):
        if 'eval(function' not in script or 'm3u8' not in script:
            continue
        unpacked = _unpack_js_eval(script)
        if not unpacked:
            continue
        match = re.search(
            r"https?://[^'\"\\;\s]+\.m3u8[^'\"\\;\s]*",
            unpacked,
        )
        if match:
            return match.group(0)
    return None


def _public_https_url(value):
    """Reject credentials and explicit local destinations in provider data.

    This is a URL-level guard; it does not replace a deployment's DNS/network
    policy. Provider CDN names can change without an application update.
    """
    if not isinstance(value, str):
        return None
    value = html.unescape(value.replace('\\/', '/')).strip()
    try:
        parts = urlsplit(value)
        hostname = (parts.hostname or '').lower().rstrip('.')
        hostname = hostname.encode('idna').decode('ascii')
        parts.port  # Reject malformed ports before handing the URL to HTTP.
        if (parts.scheme != 'https' or not hostname
                or parts.username is not None or parts.password is not None
                or '\\' in parts.netloc or '%' in hostname):
            return None
        if hostname == 'localhost' or hostname.endswith(('.localhost', '.local', '.internal')):
            return None
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            if '.' not in hostname or all(
                    re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', label)
                    for label in hostname.split('.')):
                return None
        else:
            if not address.is_global or address.is_multicast:
                return None
        return value
    except (ValueError, UnicodeError):
        return None


def _valid_hls_url(value):
    value = _public_https_url(value)
    return value if value and urlsplit(value).path.lower().endswith('.m3u8') else None


def _fetch_embed(scraper, url, referer):
    """Validate each HTTP redirect before fetching it; cap provider hops."""
    for _ in range(6):
        if not _public_https_url(url):
            raise ValueError('Unsafe playback source URL')
        response = scraper.get(
            url, headers={'Referer': referer}, timeout=25,
            allow_redirects=False, **config.proxy_request_kwargs())
        if not _public_https_url(str(response.url)):
            raise ValueError('Unsafe playback source response URL')
        if response.status_code not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get('Location') or response.headers.get('location')
        if not location:
            return response
        referer = str(response.url)
        url = urljoin(referer, location)
        close = getattr(response, 'close', None)
        if callable(close):
            close()
    raise ValueError('Too many playback source redirects')


def _extract_voe_m3u8(html_text):
    """Decode VOE's JSON player config; ignore the deliberately unrelated source.

    The provider's loader performs ROT13, removes noise pairs, Base64-decodes,
    subtracts three, reverses, then decodes JSON. No remote code is evaluated.
    """
    soup = BeautifulSoup(html_text, 'html.parser')
    for script in soup.select('script[type="application/json"]'):
        try:
            payload = json.loads(script.get_text())
            if not isinstance(payload, list) or not payload or not isinstance(payload[0], str):
                continue
            encoded = codecs.decode(payload[0], 'rot13')
            for noise in ('@$', '^^', '~@', '%?', '*~', '!!', '#&', '_'):
                encoded = encoded.replace(noise, '')
            shifted = base64.b64decode(encoded, validate=True).decode('ascii')
            reversed_payload = ''.join(chr(ord(char) - 3) for char in shifted)[::-1]
            data = json.loads(base64.b64decode(reversed_payload, validate=True))
            if isinstance(data, dict):
                result = _valid_hls_url(data.get('source'))
                if result:
                    return result
        except (ValueError, TypeError, UnicodeError):
            continue
    return None


def _content_range(value):
    match = re.fullmatch(r'bytes\s+(\d+)-(\d+)/(\d+)', str(value or '').strip(), re.I)
    if not match:
        return None
    start, end, total = (int(part) for part in match.groups())
    if start > end or end >= total:
        return None
    return start, end, total


# A file is cut into more pieces than there are connections, and the
# connections take the next piece whenever they finish one.
#
# One piece per connection was the obvious arrangement and it has a bad end:
# a connection that finishes sits idle, so the slowest piece is downloaded
# alone and the last part of every file runs at the speed of one connection.
# Smaller pieces make that tail short — the stragglers are whatever is left
# of one piece, not a quarter of the file.
#
# Not too small: each piece is its own HTTP request, and a thousand requests
# for one film is rude to the site and slower overall.
_TARGET_PIECE = 8 * 1024 * 1024
# High enough that a large film is still cut into 8 MB pieces rather than
# into 64 big ones, which would bring the slow tail straight back.  A few
# hundred range requests is ordinary: playlist downloads already ask for
# that many segments.
_MAX_PIECES = 512
# Below this there is nothing worth taking over: a new
# connection costs more than the few seconds it would save.
_MIN_TAIL_TO_SPLIT = 4 * 1024 * 1024


def _split_byte_ranges(total, workers=_DIRECT_RANGE_WORKERS,
                       target_piece=_TARGET_PIECE, max_pieces=_MAX_PIECES):
    """Byte ranges covering ``total``, enough of them to keep every
    connection busy to the end."""
    workers = max(1, int(workers))
    pieces = max(workers, (int(total) + target_piece - 1) // target_piece)
    pieces = min(pieces, int(max_pieces), max(1, int(total)))
    chunk, remainder = divmod(int(total), pieces)
    ranges = []
    start = 0
    for index in range(pieces):
        size = chunk + (1 if index < remainder else 0)
        end = start + size - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def _resplit_unfinished(ranges, written, target_piece=_TARGET_PIECE):
    """Re-cut a resumed download so its unfinished part is in small pieces.

    A paused download carries the layout it was started with.  One begun
    before pieces were made small still has four of them, so it still
    crawls at the end, and the person has no way to know why one file
    behaves differently from the next.

    Every byte already on disk is kept: the finished head of a piece stays
    exactly as it is, and only what is left of it is cut up.
    """
    fresh, done = [], []
    for (start, end), got in zip(ranges, written):
        got = max(0, int(got))
        size = end - start + 1
        if got:                      # what has arrived stays one piece
            fresh.append((start, start + got - 1))
            done.append(got)
        left = size - got
        if left <= 0:
            continue
        at = start + got
        while left > 0:
            take = min(target_piece, left)
            fresh.append((at, at + take - 1))
            done.append(0)
            at += take
            left -= take
    return fresh, done


def _parse_videos(soup):
    videos = []
    seen = set()
    for post in soup.select('div.post'):
        a = post.select_one('a[href*=".html"]')
        if not a:
            continue
        video_url = a['href']
        if video_url in seen:
            continue
        seen.add(video_url)
        title = html.unescape(a.get('title') or a.get_text(strip=True))
        img = post.find('img')
        thumbnail = (img.get('data-original') or img.get('data-src') or '') if img else ''
        if img and not thumbnail:
            src = img.get('src') or ''
            if not src.startswith('data:'):
                thumbnail = src
        meta = post.select_one('div.meta')
        date_match = re.search(
            r'(?<!\d)(20\d{2}/\d{1,2}/\d{1,2})(?!\d)',
            meta.get_text(' ', strip=True) if meta else '',
        )
        videos.append({
            'url': video_url,
            'title': title,
            'thumbnail': thumbnail,
            'duration': '',
            'date': date_match.group(1) if date_match else '',
        })
    return videos


class MediaSite(M3U8Crawler):
    # Never matched: an adapter decides which addresses it handles.
    website_pattern = r'(?!)x'
    website_dirname_pattern = r'(?!)x'
    direct_site_name = 'Site'
    direct_default_referer = 'https://downloader.com/'

    def _transform_segment(self, data):
        return _strip_fake_header(data)

    _direct_url = None
    _direct_referer = None

    def _resolve_server(self, scraper, name, link):
        response = _fetch_embed(
            scraper, _EMBED_GATEWAY.format(quote(link[::-1], safe='')),
            'https://downloader.com/')
        if response.status_code != 200:
            raise RuntimeError(f'{name} returned HTTP {response.status_code}')
        if name == 'VOE':
            # VOE sends a small literal JS redirect page before its player page.
            # Follow only this known redirect shape, with a bounded hop count.
            for _ in range(2):
                if _extract_voe_m3u8(response.text):
                    break
                match = re.search(r"window\.location\.href\s*=\s*['\"](https://[^'\"]+)['\"]", response.text)
                if not match:
                    break
                redirect = match.group(1)
                parts = urlsplit(redirect)
                if not _public_https_url(redirect) or not re.fullmatch(r'/e/[A-Za-z0-9]+/?', parts.path):
                    break
                response = _fetch_embed(scraper, redirect, str(response.url))
                if response.status_code != 200:
                    raise RuntimeError(f'VOE returned HTTP {response.status_code}')
        embed_url = str(response.url)
        parts = urlsplit(embed_url)
        origin = f'{parts.scheme}://{parts.netloc}'
        source_headers = {'Referer': embed_url, 'Origin': origin}
        if name == 'ST':
            return _public_https_url(_streamtape_direct_url(response.text)), source_headers
        if name == 'VAS':
            filecode = parts.path.rstrip('/').rsplit('/', 1)[-1]
            if not re.fullmatch(r'[A-Za-z0-9]+', filecode) or '/api/stream' not in response.text:
                return None, source_headers
            query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != 'filecode'])
            api_url = origin + '/api/stream' + ('?' + query if query else '')
            api_response = scraper.post(
                api_url, headers=source_headers,
                json={'filecode': filecode, 'device': 'web', 'codecs': []},
                timeout=25, allow_redirects=False, **config.proxy_request_kwargs(),
            )
            if api_response.status_code != 200:
                raise RuntimeError(f'VAS returned HTTP {api_response.status_code}')
            data = json.loads(api_response.text)
            return _valid_hls_url(data.get('streaming_url') if isinstance(data, dict) else None), source_headers
        if name == 'VOE':
            return _extract_voe_m3u8(response.text), source_headers
        if name == 'TV':
            return _valid_hls_url(_extract_m3u8(response.text)), {'Referer': 'https://downloader.com/'}
        return _valid_hls_url(_extract_packed_m3u8(response.text)), source_headers

    def get_url_infos(self):
        """Work out this video's media address.

        The base class knows how to download; where a given site keeps
        its video is the adapter's business, so SiteGeneric fills this in
        from what the site taught Siphon when it was added.
        """
        raise NotImplementedError

    def is_url_vaildate(self):
        # The base gate is `True if self._m3u8url` — but a Streamtape source resolves to
        # a direct MP4 (_direct_url) with no m3u8. Without this override the caller would
        # treat the URL as invalid and silently skip it (and __init__ would not sanitize
        # the target filename).
        return bool(self._m3u8url or getattr(self, '_direct_url', None))

    def start_download(self):
        sources = getattr(self, '_hls_sources', None) or (
            [('HLS', self._m3u8url, getattr(self, '_extra_headers', {}))] if self._m3u8url else [])
        last_error = None
        for index, (name, media_url, source_headers) in enumerate(sources):
            self._m3u8url = media_url
            self._extra_headers = source_headers
            try:
                return super().start_download()
            except StorageWriteError:
                raise
            except Exception as exc:
                if self._cancel_job:
                    raise
                last_error = exc
                if index + 1 >= len(sources) and not getattr(self, '_direct_url', None):
                    raise
                print(f'\n[{self.direct_site_name}] {name} failed; '
                      'trying the next playback source.', flush=True)
                self.cleanup_temp()
        if getattr(self, '_direct_url', None):
            return self._download_direct()
        if last_error:
            raise last_error
        return super().start_download()

    @staticmethod
    def _safe_remove(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _download_direct(self):
        """Direct MP4 download.  When the video server refuses the link
        (HTTP 403/410 – expired token, too many connections) wait, fetch a
        fresh link from the video page and continue; progress is kept."""
        attempts = max(1, int(getattr(self, 'direct_refresh_attempts', 3)))
        for attempt in range(attempts):
            try:
                return self._download_direct_once()
            except StorageWriteError:
                raise
            except Exception as exc:
                match = re.search(r'HTTP (\d{3})', str(exc))
                code = int(match.group(1)) if match else 0
                if self._cancel_job or code not in (403, 410, 429) or attempt == attempts - 1:
                    raise
                wait = 10 * (attempt + 1)
                print(f'\n[{self.direct_site_name}] Video server answered HTTP {code}; '
                      f'getting a fresh link in {wait}s (try {attempt + 2}/{attempts}).',
                      flush=True)
                for _ in range(wait * 4):
                    if self._cancel_job:
                        return False
                    time.sleep(0.25)
                try:
                    self.get_url_infos()
                except Exception as refresh_exc:
                    print(f'[{self.direct_site_name}] Fresh link failed: {refresh_exc}', flush=True)
                    raise exc
        return False

    def _direct_get(self, session, url, headers):
        """GET for direct downloads.  Sites with ``direct_browser_session``
        use a browser-like (curl_cffi) connection plus the video page's
        cookies – some video servers refuse plain Python requests."""
        if getattr(self, 'direct_browser_session', False) and _use_cffi:
            from siphon.sites.base import _get_cffi_session
            return _get_cffi_session().get(
                url, headers=headers, cookies=getattr(self, '_direct_cookies', None) or None,
                timeout=60, stream=True, allow_redirects=True,
                **config.proxy_request_kwargs())
        return session.get(url, headers=headers, timeout=60, stream=True,
                           allow_redirects=True, **config.proxy_request_kwargs())

    def _log_refusal(self, resp):
        try:
            status = int(getattr(resp, 'status_code', 0) or 0)
            if status < 400:
                return
            headers = getattr(resp, 'headers', {}) or {}
            final = str(getattr(resp, 'url', '') or self._direct_url)
            print(f'[{self.direct_site_name}] video server HTTP {status} '
                  f'(host {urlsplit(final).hostname}, server '
                  f'{headers.get("server", "?")})', flush=True)
        except Exception:
            pass

    def _download_direct_once(self):
        self._progress_unit = 'bytes'
        if self._cancel_job:
            return False
        self._cancel_job = False
        self._create_dest_folder()
        if self.is_target_video_exist():
            print("File already exists!", flush=True)
            return True
        out = self._get_video_savename()
        part = out + '.part'
        state_path = part + '.state.json'
        if os.path.exists(part) and self._load_direct_state(part) is None:
            # A partial file without valid progress bookkeeping cannot be
            # trusted; start that one over.
            self._safe_remove(part)
            self._safe_remove(state_path)
        ref = self._direct_referer or self.direct_default_referer
        start = time.time()
        try:
            try:
                ranged = self._download_direct_ranges(part, ref, start)
            except StorageWriteError:
                raise
            except Exception as range_exc:
                if (self._cancel_job or self._load_direct_state(part) is not None
                        or re.search(r'HTTP (?:401|403|410|429)', str(range_exc))):
                    # Progress is saved: report the error and let a retry /
                    # Resume continue from it instead of starting over.
                    raise
                print(
                    f'\n[{self.direct_site_name}] Parallel ranges failed; '
                    'retrying with one resumable connection.',
                    flush=True)
                self._safe_remove(part)
                self._safe_remove(state_path)
                ranged = None
            if ranged is None:
                done, total = self._download_direct_serial(part, ref, start)
            else:
                done, total = ranged
        except StorageWriteError:
            # Preserve the partial file; a failing device must not be
            # subjected to a source fallback or another write attempt.
            raise
        except Exception:
            # Keep a resumable partial download (ranges + bookkeeping) so a
            # retry continues where it stopped; anything else starts over.
            if self._load_direct_state(part) is None:
                self._safe_remove(part)
            raise
        if self._cancel_job:
            # Pause keeps the partial file so Resume continues from it;
            # Cancel/remove (cleanup) deletes it.
            if not getattr(self, '_keep_partial_on_cancel', False):
                self._safe_remove(part)
                self._safe_remove(state_path)
            return False
        if total > 0 and done < total:
            raise Exception("Download incomplete (connection dropped? retry)")
        self._safe_remove(state_path)
        self._progress_unit = 'postprocess'
        try:
            os.replace(part, out)
        except OSError as exc:
            raise StorageWriteError(out, exc) from exc
        except Exception:
            self._safe_remove(part)
            raise
        show_when_finished(out)
        print(f"\nDownload complete: {os.path.basename(out)}", flush=True)
        return True

    def _download_direct_ranges(self, part, ref, start_time):
        """Use up to four HTTP Range connections when the host supports ranges.
        The shared requests session mounts SharedSSLAdapter, which is required for every
        concurrent HTTPS path in this project. Return None to keep the serial fallback."""
        session = _get_session()
        probe = None
        refused = 0
        try:
            probe = self._direct_get(
                session, self._direct_url, {'Referer': ref, 'Range': 'bytes=0-0'})
            status = int(getattr(probe, 'status_code', 0) or 0)
            if status in (401, 403, 410, 429):
                self._log_refusal(probe)
                refused = status
            info = _content_range(getattr(probe, 'headers', {}).get('content-range'))
            if not refused and (status != 206 or not info or info[:2] != (0, 0)):
                return None
            total = info[2] if info else 0
        except Exception:
            return None
        finally:
            if probe is not None:
                try:
                    probe.close()
                except Exception:
                    pass
        if refused:
            raise Exception(f"Direct download failed (HTTP {refused})")

        connections = max(1, min(
            getattr(self, 'direct_range_workers_max', _DIRECT_RANGE_WORKERS),
            getattr(self, '_max_workers', _DIRECT_RANGE_WORKERS)))

        saved = self._load_direct_state(part)
        if saved is not None and saved['total'] == total:
            # Resume after Pause / app restart: same file, keep its ranges.
            ranges = [tuple(r) for r in saved['ranges']]
            range_written = list(saved['written'])
            resumed = sum(range_written)
            print(f'\n[{self.direct_site_name}] Resuming from '
                  f'{resumed * 100 // max(total, 1)}% '
                  f'({resumed / 1048576:.1f} MB already downloaded).', flush=True)
            biggest = max((end - start + 1 - got
                           for (start, end), got in zip(ranges, range_written)),
                          default=0)
            if biggest > _TARGET_PIECE * 2:
                ranges, range_written = _resplit_unfinished(
                    ranges, range_written)
                print(f'[{self.direct_site_name}] what is left of it was cut '
                      f'into {len(ranges)} smaller pieces, so the end does '
                      'not crawl along on one connection', flush=True)
        else:
            ranges = _split_byte_ranges(total, connections)
            # Even a single connection is tracked as one "range" so it can
            # be resumed later.
            range_written = [0] * len(ranges)
            resumed = 0
            self._safe_remove(part + '.state.json')
            with storage_open(part, 'wb') as target:
                hide_while_working(part)
                target.truncate(total)

        progress_lock = _threading.Lock()
        # Guards the piece list while a connection takes over the tail of
        # someone else's piece.
        plan_lock = _threading.Lock()
        stop_event = _threading.Event()
        done = resumed
        state_lock = _threading.Lock()
        last_saved = [0.0]
        last_report = [0.0]

        def _save_state(force=False):
            now = time.time()
            if not force and now - last_saved[0] < 1.0:
                return
            last_saved[0] = now
            with state_lock:
                self._save_direct_state(part, total, ranges, range_written)

        self._save_direct_state(part, total, ranges, range_written)

        def _fetch_range(index, max_retries=_DIRECT_RANGE_RETRIES, honor_stop=True):
            nonlocal done
            range_start = ranges[index][0]
            retries = 0

            def _stopped():
                return honor_stop and stop_event.is_set()

            def _room():
                # Read afresh: an idle connection may have taken over the
                # far end of this piece while it was being downloaded.
                with plan_lock:
                    return ranges[index][1] - range_start + 1

            while (range_written[index] < _room() and not self._cancel_job
                   and not _stopped()):
                expected = _room()
                range_end = range_start + expected - 1
                cursor = range_start + range_written[index]
                response = None
                try:
                    response = self._direct_get(
                        session, self._direct_url,
                        {'Referer': ref, 'Range': f'bytes={cursor}-{range_end}'})
                    response_range = _content_range(
                        getattr(response, 'headers', {}).get('content-range'))
                    if (getattr(response, 'status_code', 0) != 206 or
                            response_range != (cursor, range_end, total)):
                        raise Exception("Source did not answer the range request correctly")

                    received = 0
                    with storage_open(part, 'r+b', buffering=0) as target:
                        target.seek(cursor)
                        for chunk in response.iter_content(chunk_size=65536):
                            if self._cancel_job or _stopped():
                                break
                            if not chunk:
                                continue
                            expected = _room()
                            room = expected - range_written[index]
                            if room <= 0:
                                break    # the rest of this piece is someone
                                         # else's now
                            if len(chunk) > room:
                                chunk = chunk[:room]
                            speed_limiter.acquire(len(chunk))
                            if target.write(chunk) != len(chunk):
                                raise Exception("Write to disk failed")
                            range_written[index] += len(chunk)
                            received += len(chunk)
                            if received >= 1024 * 1024:
                                retries = 0   # the connection is healthy again
                            with progress_lock:
                                done += len(chunk)
                                current_done = done
                                now = time.time()
                                # At most ~5 updates a second: every 64 KB
                                # from 4-8 connections would flood the UI.
                                report = (now - last_report[0] >= 0.2
                                          or current_done >= total)
                                if report:
                                    last_report[0] = now
                                elapsed = now - start_time
                                speed = ((current_done - resumed) / elapsed
                                         if elapsed > 0 else 0)
                                if report and self._progress_callback:
                                    self._progress_callback(current_done, total, speed)
                            _save_state()

                    if self._cancel_job or _stopped():
                        break
                    if range_written[index] < _room():
                        detail = "no data received" if received == 0 else "connection closed early"
                        raise Exception(f"Direct download range: {detail}")
                except StorageWriteError:
                    stop_event.set()
                    raise
                except Exception:
                    if self._cancel_job or _stopped():
                        break
                    retries += 1
                    if retries > max_retries:
                        raise
                    time.sleep(_DIRECT_RETRY_BASE_DELAY * min(retries, 5))
                finally:
                    if response is not None:
                        try:
                            response.close()
                        except Exception:
                            pass

            if (not self._cancel_job and not _stopped()
                    and range_written[index] != _room()):
                raise Exception("Direct download range incomplete (connection dropped? retry)")
            return range_written[index]

        def _take_over_a_tail():
            """Halve the longest piece still going and take the far end.

            Small pieces shorten the slow finish but do not end it: the last
            piece is still one connection, and a server that throttles makes
            that the 30 KB/s that a download sits at while it says 99%.
            When there is nothing left to pick up, the connections that have
            finished cut into what is left instead of watching.

            Returns the new piece's index, or None when nothing is worth
            splitting.  The piece's owner reads its own end afresh as it
            goes, so it stops at the new boundary of its own accord.
            """
            with plan_lock:
                longest, biggest = None, 0
                for index, (start, end) in enumerate(ranges):
                    left = end - start + 1 - range_written[index]
                    if left > biggest:
                        longest, biggest = index, left
                # Below this, splitting costs more in new connections than
                # it saves.
                if longest is None or biggest < _MIN_TAIL_TO_SPLIT:
                    return None
                start, end = ranges[longest]
                keep = range_written[longest] + biggest // 2
                ranges[longest] = (start, start + keep - 1)
                ranges.append((start + keep, end))
                range_written.append(0)
                return len(ranges) - 1

        def _fetch_range_then_help(index):
            """Download this piece, then help with whatever is left."""
            with plan_lock:
                not_started[0] -= 1
            got = _fetch_range(index)
            while not self._cancel_job and not stop_event.is_set():
                with plan_lock:
                    queued = not_started[0] > 0
                if queued:
                    break    # pieces nobody has begun: the pool will hand
                             # them out, and starting one is better than
                             # cutting into a piece already going
                spare = _take_over_a_tail()
                if spare is None:
                    break
                print(f'[{self.direct_site_name}] a free connection took over '
                      'the far end of the slowest piece', flush=True)
                _fetch_range(spare)
            return got

        # As many at a time as there are connections; the rest wait their
        # turn and are picked up by whichever connection frees up first.
        at_once = min(len(ranges), max(1, connections))
        # Pieces submitted but not yet begun.  Nothing is taken over while
        # any of these are left.
        not_started = [len(ranges)]
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=at_once)
        self._t2_executor = executor
        futures = [executor.submit(_fetch_range_then_help, index)
                   for index in range(len(ranges))]
        parallel_error = None
        try:
            # Looked at twice a second rather than waited for outright: a
            # connection gone quiet blocks in its read, and waiting for it
            # kept a paused download "running" until that read gave up, so
            # Resume had nothing to start.
            waiting = set(futures)
            while waiting:
                finished, waiting = concurrent.futures.wait(
                    waiting, timeout=0.5,
                    return_when=concurrent.futures.FIRST_COMPLETED)
                for future in finished:
                    future.result()
                if self._cancel_job:
                    stop_event.set()
                    break
        except StorageWriteError:
            stop_event.set()
            raise
        except Exception as exc:
            parallel_error = exc
            stop_event.set()
            for future in futures:
                future.cancel()
        finally:
            # A stuck connection looks at the cancel flag as soon as its read
            # returns and writes nothing more; it is left to end by itself.
            executor.shutdown(wait=not self._cancel_job, cancel_futures=True)
            self._t2_executor = None

        if parallel_error is not None and not self._cancel_job:
            # Keep everything already downloaded and finish the missing parts
            # one connection at a time (more patient retries).
            missing = [index for index, (a, b) in enumerate(ranges)
                       if range_written[index] < b - a + 1]
            print(f'\n[{self.direct_site_name}] A connection dropped '
                  f'({parallel_error}); finishing {len(missing)} remaining '
                  f'part(s) on one connection, keeping progress '
                  f'({done * 100 // max(total, 1)}%).', flush=True)
            for index in missing:
                if self._cancel_job:
                    break
                _fetch_range(index, max_retries=_DIRECT_RANGE_RETRIES * 3,
                             honor_stop=False)

        _save_state(force=True)
        if self._cancel_job:
            return done, total
        if done != total:
            raise Exception("Direct download incomplete (connection dropped? retry)")
        return done, total

    # ── resumable direct downloads ───────────────────────────────────────
    @staticmethod
    def _save_direct_state(part, total, ranges, written):
        path = part + '.state.json'
        tmp = path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump({'version': 1, 'total': int(total),
                           'ranges': [list(r) for r in ranges],
                           'written': [int(w) for w in written]}, fh)
            os.replace(tmp, path)
            hide_while_working(path)
        except OSError:
            pass

    @staticmethod
    def _load_direct_state(part):
        """Saved range progress for a partial file, or None if unusable."""
        path = part + '.state.json'
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            total = int(data['total'])
            ranges = [(int(a), int(b)) for a, b in data['ranges']]
            written = [int(w) for w in data['written']]
            if (data.get('version') != 1 or total <= 0 or not ranges
                    or len(ranges) != len(written)
                    or os.path.getsize(part) != total):
                return None
            for (a, b), w in zip(ranges, written):
                if a < 0 or b < a or b >= total or w < 0 or w > b - a + 1:
                    return None
            return {'total': total, 'ranges': ranges, 'written': written}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _download_direct_serial(self, part, ref, start_time):
        done = os.path.getsize(part) if os.path.exists(part) else 0
        total = 0
        retries = 0
        session = _get_session()
        while not self._cancel_job:
            request_headers = {'Referer': ref}
            if done:
                request_headers['Range'] = f'bytes={done}-'
            resp = None
            try:
                resp = self._direct_get(session, self._direct_url, request_headers)
                status = getattr(resp, 'status_code', 0)
                self._log_refusal(resp)
                response_range = _content_range(
                    getattr(resp, 'headers', {}).get('content-range'))
                if done:
                    if status != 206 or not response_range or response_range[0] != done:
                        raise Exception(f"Resume failed (HTTP {status})")
                    total = response_range[2]
                elif status == 206 and response_range:
                    total = response_range[2]
                elif status == 200:
                    try:
                        total = int(resp.headers.get('content-length') or 0)
                    except Exception:
                        total = 0
                else:
                    raise Exception(f"Direct download failed (HTTP {status})")

                received = 0
                with storage_open(part, 'ab' if done else 'wb') as target:
                    hide_while_working(part)
                    for chunk in resp.iter_content(chunk_size=65536):
                        if self._cancel_job:
                            break
                        if not chunk:
                            continue
                        speed_limiter.acquire(len(chunk))
                        target.write(chunk)
                        done += len(chunk)
                        received += len(chunk)
                        elapsed = time.time() - start_time
                        speed = done / elapsed if elapsed > 0 else 0
                        if self._progress_callback:
                            self._progress_callback(done, total, speed)

                if self._cancel_job:
                    break
                if total > 0 and done >= total:
                    return done, total
                if total == 0 and received > 0:
                    return done, done
                raise Exception("Connection closed early")
            except StorageWriteError:
                raise
            except Exception:
                if self._cancel_job:
                    break
                retries += 1
                if retries > _DIRECT_RANGE_RETRIES:
                    raise
                time.sleep(_DIRECT_RETRY_BASE_DELAY * retries)
            finally:
                if resp is not None:
                    try:
                        resp.close()
                    except Exception:
                        pass
        return done, total
