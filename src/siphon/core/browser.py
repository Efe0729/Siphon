"""A real browser, used only when a plain request is not enough.

Some sites answer Python requests with a Cloudflare check, and some build
their player with JavaScript, so the video address is nowhere in the HTML the
server sends.  Both are solved the same way: open the page in the browser that
is already installed (Edge or Chrome), off-screen and in the app's own
profile, and take the finished page from it — plus the addresses the player
asked for while it loaded, and the site's cookies.

The window is kept open between pages (opening one costs a few seconds) and
closed by itself once unused for a while.  Only the standard library is used:
the browser is driven over its DevTools protocol, as ``cfpass`` already does.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time

from siphon.core import config
from siphon.core.cfpass import (CfPassError, _WebSocket, _free_port,
                                        _http_json, _profile_dir, find_browser)

IDLE_SHUTDOWN = 8.0              # close the browser this long after its last page
MEDIA_RE = re.compile(r'\.(?:m3u8|mp4|webm)(?:[?#]|$)', re.I)
_CHALLENGE_RE = re.compile(
    r'just a moment|checking your browser|cf-chl-|__cf_chl|enable javascript and cookies',
    re.I)


class BrowserError(Exception):
    pass


def available():
    """True when a browser this module can drive is installed."""
    return find_browser() is not None


def _hide_windows_of(pid, seconds=15.0):
    """Keep this browser's windows out of the taskbar and the Alt-Tab list.

    Windows only.  The window is already off-screen; what still showed was its
    taskbar button.  Making it a "tool window" removes that without hiding or
    minimising it, which would make the browser stop drawing and so stop
    loading the pages it is there for.  Runs for a few seconds in the
    background because the window does not exist yet when the process starts.
    """
    if os.name != 'nt':
        return None

    def _work():
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            GWL_EXSTYLE, TOOL, APP = -20, 0x00000080, 0x00040000
            seen = set()

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def visit(hwnd, _lparam):
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value == pid and hwnd not in seen:
                    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    if not style & TOOL:
                        shown = bool(user32.IsWindowVisible(hwnd))
                        # The window has to be hidden while its style
                        # changes, or the taskbar keeps the old button.
                        user32.ShowWindow(hwnd, 0)
                        user32.SetWindowLongW(
                            hwnd, GWL_EXSTYLE, (style | TOOL) & ~APP)
                        # Only a window that was showing is shown again.  The
                        # browser also owns helper windows that are never
                        # meant to be seen; showing those, before they have
                        # drawn anything, is the black "not responding" box.
                        if shown:
                            user32.ShowWindow(hwnd, 8)  # shown, not activated
                    seen.add(hwnd)
                return True

            end = time.time() + seconds
            while time.time() < end:
                user32.EnumWindows(visit, 0)
                time.sleep(0.1)
        except Exception as exc:
            print(f'[browser] could not keep its window out of the taskbar: {exc}',
                  flush=True)

    thread = threading.Thread(target=_work, name='hide-browser-window', daemon=True)
    thread.start()
    return thread


class _EventSocket(_WebSocket):
    """DevTools connection that keeps the events it sees (instead of dropping
    them), so a page's network requests can be read after it loads."""

    def __init__(self, url, timeout=20):
        super().__init__(url, timeout=timeout)
        self.events = []

    def call(self, method, params=None):
        self._next_id += 1
        msg_id = self._next_id
        self.send_text(json.dumps({'id': msg_id, 'method': method, 'params': params or {}}))
        while True:
            reply = json.loads(self.recv_text())
            if reply.get('id') == msg_id:
                if 'error' in reply:
                    raise BrowserError(str(reply['error']))
                return reply.get('result', {})
            if reply.get('method'):
                self.events.append(reply)
                del self.events[:-4000]

    def drain(self, seconds=0.0):
        """Read whatever has already arrived (optionally waiting a little)."""
        deadline = time.time() + seconds
        self.sock.settimeout(0.2)
        try:
            while True:
                try:
                    reply = json.loads(self.recv_text())
                except (OSError, ValueError):
                    if time.time() >= deadline:
                        return
                    continue
                if reply.get('method'):
                    self.events.append(reply)
                if time.time() >= deadline:
                    return
        finally:
            try:
                self.sock.settimeout(20)
            except OSError:
                pass


class _Session:
    """One running browser with one re-used tab."""

    def __init__(self):
        self.proc = None
        self.port = 0
        self.ws = None
        self.last_used = time.time()

    # ── lifetime ────────────────────────────────────────────────────
    def start(self, timeout=40):
        browser = find_browser()
        if not browser:
            raise BrowserError('Microsoft Edge or Google Chrome was not found')
        self.port = _free_port()
        args = [browser, f'--remote-debugging-port={self.port}',
                f'--user-data-dir={_profile_dir()}',
                '--no-first-run', '--no-default-browser-check',
                '--disable-popup-blocking', '--mute-audio',
                # Off-screen rather than headless: a headless browser is
                # recognised and shown the check again on every page.
                '--window-position=-32000,-32000', '--window-size=1280,900',
                '--new-window', 'about:blank']
        if os.name != 'nt' and hasattr(os, 'geteuid') and os.geteuid() == 0:
            args.insert(1, '--no-sandbox')     # Chrome refuses to run as root
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, **kwargs)
        _hide_windows_of(self.proc.pid)
        deadline = time.time() + timeout
        target = None
        while time.time() < deadline and target is None:
            try:
                pages = [t for t in _http_json(f'http://127.0.0.1:{self.port}/json/list')
                         if t.get('type') == 'page' and t.get('webSocketDebuggerUrl')]
                target = pages[0] if pages else None
            except (OSError, ValueError, IndexError):
                time.sleep(0.4)
        if target is None:
            self.stop()
            raise BrowserError('the browser did not start')
        self.ws = _EventSocket(target['webSocketDebuggerUrl'])
        self.ws.call('Page.enable')
        self.ws.call('Network.enable')
        print(f'[browser] {os.path.basename(browser)} ready', flush=True)

    def alive(self):
        return (self.proc is not None and self.proc.poll() is None
                and self.ws is not None)

    def stop(self):
        if self.ws is not None:
            try:
                self.ws.call('Browser.close')
            except Exception:
                pass
            self.ws.close()
            self.ws = None
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.proc = None

    # ── work ────────────────────────────────────────────────────────
    def _html(self):
        result = self.ws.call('Runtime.evaluate', {
            'expression': 'document.documentElement ? '
                          'document.documentElement.outerHTML : ""',
            'returnByValue': True})
        return str(result.get('result', {}).get('value') or '')

    def fetch(self, url, referer='', timeout=45, settle=1.5):
        """Load ``url`` and return (html, media addresses the page requested)."""
        self.last_used = time.time()
        self.ws.events.clear()
        headers = {'Referer': referer} if referer else {}
        try:
            self.ws.call('Network.setExtraHTTPHeaders', {'headers': headers})
        except BrowserError:
            pass
        self.ws.call('Page.navigate', {'url': url})
        deadline = time.time() + timeout
        html_text = ''
        while time.time() < deadline:
            self.ws.drain(0.5)
            try:
                state = self.ws.call('Runtime.evaluate', {
                    'expression': 'document.readyState', 'returnByValue': True})
            except BrowserError:
                break
            if str(state.get('result', {}).get('value')) == 'complete':
                html_text = self._html()
                # A Cloudflare check replaces itself with the real page a few
                # seconds later; keep waiting for that.
                if not _CHALLENGE_RE.search(html_text[:4000]):
                    break
            time.sleep(0.5)
        if not html_text:
            html_text = self._html()
        self.ws.drain(settle)                  # catch the player's own requests
        # A page that builds its list with JavaScript (or loads it as you
        # scroll) has no cards yet at "complete".  Scroll once, let it fill,
        # and read the page again so the cards are in what is returned.
        if html_text:
            try:
                self.ws.call('Runtime.evaluate', {
                    'expression': 'window.scrollTo(0, document.body.scrollHeight)',
                    'returnByValue': True})
                self.ws.drain(1.0)
                later = self._html()
                if later and len(later) >= len(html_text) * 0.5:
                    html_text = later
            except BrowserError:
                pass
        media = []
        for event in self.ws.events:
            if event.get('method') not in ('Network.requestWillBeSent',
                                           'Network.responseReceived'):
                continue
            params = event.get('params', {})
            found = (params.get('request') or params.get('response') or {}).get('url', '')
            if found and MEDIA_RE.search(found) and found not in media:
                media.append(found)
        self.last_used = time.time()
        return html_text, media

    def cookies(self, url=''):
        try:
            result = self.ws.call('Network.getCookies', {'urls': [url]} if url else {})
        except BrowserError:
            return {}
        return {c.get('name'): c.get('value') for c in result.get('cookies', [])
                if c.get('name')}

    def user_agent(self):
        try:
            version = _http_json(f'http://127.0.0.1:{self.port}/json/version')
            return version.get('User-Agent', '')
        except OSError:
            return ''


_session = None
_lock = threading.RLock()
_reaper = None


def _reap():
    while True:
        time.sleep(1)
        with _lock:
            session = _session
            if session is None:
                return
            if not session.alive() or time.time() - session.last_used > IDLE_SHUTDOWN:
                _close_locked()
                return


def _close_locked():
    global _session, _reaper
    if _session is not None:
        print('[browser] closing (unused)', flush=True)
        _session.stop()
    _session = None
    _reaper = None


def shutdown():
    with _lock:
        _close_locked()


def fetch(url, referer='', timeout=45, settle=1.5):
    """(html, media addresses) for ``url``, loaded in a real browser.

    Starts the browser on first use and keeps it for the next pages.
    """
    global _session, _reaper
    with _lock:
        if _session is not None and not _session.alive():
            _close_locked()
        if _session is None:
            session = _Session()
            session.start()
            _session = session
            _reaper = threading.Thread(target=_reap, daemon=True)
            _reaper.start()
        try:
            return _session.fetch(url, referer=referer, timeout=timeout, settle=settle)
        except (BrowserError, CfPassError, OSError) as exc:
            # The window was closed or crashed: start over once.
            print(f'[browser] retrying after: {exc}', flush=True)
            _close_locked()
            session = _Session()
            session.start()
            _session = session
            _reaper = threading.Thread(target=_reap, daemon=True)
            _reaper.start()
            return _session.fetch(url, referer=referer, timeout=timeout, settle=settle)


def cookies_for(url):
    """The browser's cookies for ``url`` (empty when it is not running)."""
    with _lock:
        if _session is None or not _session.alive():
            return {}
        return _session.cookies(url)


def user_agent():
    with _lock:
        return _session.user_agent() if (_session and _session.alive()) else ''


def looks_blocked(status, text):
    """True for a Cloudflare / bot check instead of the page itself."""
    if int(status or 0) in (401, 403, 429, 503) and not text:
        return True
    head = (text or '')[:4000]
    if _CHALLENGE_RE.search(head):
        return True
    return int(status or 0) in (403, 429, 503) and bool(
        re.search(r'cloudflare|attention required|access denied', head, re.I))


def remember_pass(host):
    """Store the browser's Cloudflare cookie for ``host`` so plain requests
    work again too (same place Settings → Cloudflare keeps it)."""
    with _lock:
        if _session is None or not _session.alive():
            return False
        cookies = _session.cookies(f'https://{host}/')
        clearance = cookies.get('cf_clearance')
        agent = _session.user_agent()
    if clearance and agent:
        config.set_cf_override(host, clearance, agent)
        print(f'[browser] saved Cloudflare pass for {host}', flush=True)
        return True
    return False
