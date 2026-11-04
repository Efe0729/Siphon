"""One-click Cloudflare pass: let a real browser solve the check, keep its cookie.

``obtain(host)`` opens Microsoft Edge (or Chrome) in a separate, app-owned
profile with only the remote-debugging port enabled (no automation flags, so
Cloudflare sees an ordinary browser).  The user passes the "verify you are
human" page; we then read the site's ``cf_clearance`` cookie and the browser's
User-Agent over the DevTools protocol, store them as the host's Cloudflare
override (Settings → Cloudflare) and close the window.

Only a minimal stdlib WebSocket client is used (no extra packages).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import time
import urllib.request

from siphon.core import config


class CfPassError(Exception):
    pass


def find_browser():
    candidates = []
    if os.name == 'nt':
        for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'),
                     os.environ.get('LOCALAPPDATA')):
            if not base:
                continue
            candidates += [
                os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
                os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            ]
    for name in ('msedge', 'google-chrome', 'chrome', 'chromium', 'chromium-browser'):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _profile_dir():
    from siphon.core.paths import product_data_dir
    path = product_data_dir() / 'cf_browser'
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _http_json(url, timeout=2):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


class _WebSocket:
    """Just enough RFC 6455 for DevTools: text frames, client-side masking."""

    def __init__(self, url, timeout=10):
        assert url.startswith('ws://')
        hostport, _, path = url[5:].partition('/')
        host, _, port = hostport.partition(':')
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f'GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n'
                   f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                   'Sec-WebSocket-Version: 13\r\n\r\n')
        self.sock.sendall(request.encode())
        header = b''
        while b'\r\n\r\n' not in header:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise CfPassError('DevTools handshake failed')
            header += chunk
        if b' 101 ' not in header.split(b'\r\n', 1)[0]:
            raise CfPassError('DevTools refused the connection')
        self._buffer = header.split(b'\r\n\r\n', 1)[1]
        self._next_id = 0

    def _recv_exact(self, size):
        while len(self._buffer) < size:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CfPassError('DevTools connection closed')
            self._buffer += chunk
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def send_text(self, text):
        payload = text.encode('utf-8')
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack('>H', length)
        else:
            header.append(0x80 | 127)
            header += struct.pack('>Q', length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_text(self):
        parts = []
        while True:
            first, second = self._recv_exact(2)
            opcode, final = first & 0x0F, first & 0x80
            length = second & 0x7F
            if length == 126:
                length = struct.unpack('>H', self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack('>Q', self._recv_exact(8))[0]
            payload = self._recv_exact(length)
            if opcode == 8:
                raise CfPassError('DevTools connection closed')
            if opcode in (0, 1):
                parts.append(payload)
                if final:
                    return b''.join(parts).decode('utf-8', 'replace')

    def call(self, method, params=None):
        self._next_id += 1
        msg_id = self._next_id
        self.send_text(json.dumps({'id': msg_id, 'method': method, 'params': params or {}}))
        while True:
            reply = json.loads(self.recv_text())
            if reply.get('id') == msg_id:
                if 'error' in reply:
                    raise CfPassError(str(reply['error']))
                return reply.get('result', {})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def _cookie_for(cookies, host):
    bare = host.lower().lstrip('.')
    for cookie in cookies:
        domain = str(cookie.get('domain', '')).lower().lstrip('.')
        if cookie.get('name') == 'cf_clearance' and (
                domain == bare or bare.endswith('.' + domain) or domain.endswith('.' + bare)):
            return cookie.get('value')
    return None


def obtain(host, timeout=240, start_url=None, on_status=None):
    """Open a browser window for ``host``; return True once its pass is saved.

    Raises CfPassError if no browser is found, the window is closed, or the
    check is not passed within ``timeout`` seconds.
    """
    browser = find_browser()
    if not browser:
        raise CfPassError('Microsoft Edge or Google Chrome was not found')
    port = _free_port()
    url = start_url or f'https://{host}/'
    args = [browser, f'--remote-debugging-port={port}', f'--user-data-dir={_profile_dir()}',
            '--no-first-run', '--no-default-browser-check', '--new-window', 'about:blank']
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **kwargs)
    print(f'[CF pass] opened {os.path.basename(browser)} for {host}', flush=True)
    deadline = time.time() + timeout
    ws = None
    try:
        version = None
        while time.time() < deadline and version is None:
            try:
                version = _http_json(f'http://127.0.0.1:{port}/json/version')
            except OSError:
                time.sleep(0.5)
        if version is None:
            raise CfPassError('the browser did not start')
        user_agent = version.get('User-Agent', '')
        ws = _WebSocket(version['webSocketDebuggerUrl'])
        # Start clean: an old (possibly stale) pass in this app-only profile
        # must not be mistaken for a fresh one.  Then open the site.
        ws.call('Storage.clearCookies')
        ws.call('Target.createTarget', {'url': url})
        if on_status:
            on_status('waiting')
        while time.time() < deadline:
            if proc.poll() is not None and not _alive(port):
                raise CfPassError('the browser window was closed before the check was passed')
            try:
                cookies = ws.call('Storage.getCookies').get('cookies', [])
            except CfPassError:
                raise CfPassError('the browser window was closed before the check was passed')
            value = _cookie_for(cookies, host)
            if value:
                config.set_cf_override(host, value, user_agent)
                print(f'[CF pass] saved Cloudflare pass for {host}', flush=True)
                time.sleep(1.5)   # let the page finish loading before closing
                try:
                    ws.call('Browser.close')
                except CfPassError:
                    pass
                return True
            time.sleep(1.0)
        raise CfPassError('timed out waiting for the Cloudflare check')
    finally:
        if ws is not None:
            ws.close()
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass


def _alive(port):
    try:
        _http_json(f'http://127.0.0.1:{port}/json/version', timeout=1)
        return True
    except OSError:
        return False
