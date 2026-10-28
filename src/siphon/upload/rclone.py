"""Thin wrapper around the rclone command-line tool.

rclone handles cloud sign-in (OAuth), retries and chunked uploads for
Google Drive and many other services, so the app never stores cloud
passwords itself.  Everything here runs rclone as a child process.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_EXE = 'rclone.exe' if os.name == 'nt' else 'rclone'
RETRIES = 3


class RcloneError(Exception):
    pass


def _no_window():
    if os.name == 'nt':
        return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    return {}


def _candidates():
    override = os.environ.get('SIPHON_RCLONE', '').strip()
    if override:
        yield Path(override)
    # Next to the project checkout (…/Siphon/rclone.exe or tools/rclone/)
    here = Path(__file__).resolve()
    for root in (here.parents[3], Path(sys.executable).resolve().parent):
        yield root / _EXE
        yield root / 'tools' / 'rclone' / _EXE
        yield root / 'rclone' / _EXE
    found = shutil.which('rclone')
    if found:
        yield Path(found)
    if os.name == 'nt':
        local = os.environ.get('LOCALAPPDATA', '')
        if local:
            # winget installs land here; PATH may not be refreshed yet
            yield Path(local) / 'Microsoft' / 'WinGet' / 'Links' / _EXE
            packages = Path(local) / 'Microsoft' / 'WinGet' / 'Packages'
            if packages.is_dir():
                for pkg in packages.glob('Rclone.Rclone*'):
                    for exe in pkg.glob('rclone-*/' + _EXE):
                        yield exe
        yield Path(r'C:\Program Files\rclone') / _EXE


def find_rclone():
    """Return the path to rclone, or None when it is not installed."""
    for path in _candidates():
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return None


def _run(args, timeout=60):
    exe = find_rclone()
    if not exe:
        raise RcloneError('rclone not found')
    try:
        proc = subprocess.run(
            [exe, *args], capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
            stdin=subprocess.DEVNULL, **_no_window())
    except subprocess.TimeoutExpired as exc:
        raise RcloneError('rclone timed out') from exc
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or '').strip().splitlines()
        raise RcloneError(message[-1] if message else f'rclone exit {proc.returncode}')
    return proc.stdout


def list_remotes():
    """Return [(name, type)] for every configured rclone remote, e.g. [('gdrive', 'drive')]."""
    remotes = []
    for line in _run(['listremotes', '--long']).splitlines():
        if ':' not in line:
            continue
        name, _, kind = line.partition(':')
        name = name.strip()
        if name:
            remotes.append((name, kind.strip()))
    return remotes


def remote_path(remote, folder=''):
    folder = (folder or '').replace('\\', '/').strip('/')
    return f'{remote}:{folder}'


def list_folders(remote, folder=''):
    """Sub-folder names directly under remote:folder."""
    out = _run(['lsf', '--dirs-only', remote_path(remote, folder)], timeout=90)
    return sorted((line.rstrip('/') for line in out.splitlines() if line.strip()),
                  key=str.casefold)


def make_folder(remote, folder):
    _run(['mkdir', remote_path(remote, folder)], timeout=90)


def free_remote_name(base='gdrive'):
    names = {name for name, _ in list_remotes()}
    if base not in names:
        return base
    index = 2
    while f'{base}{index}' in names:
        index += 1
    return f'{base}{index}'


_auth_proc = None


def _run_sign_in(args, timeout=600):
    """Run an rclone command that signs in through the browser.  A sign-in
    still waiting from an earlier try is stopped first (it would keep the
    local sign-in port busy)."""
    global _auth_proc
    exe = find_rclone()
    if not exe:
        raise RcloneError('rclone not found')
    old = _auth_proc
    if old is not None and old.poll() is None:
        try:
            old.kill()
            old.wait(timeout=5)
        except Exception:
            pass
    proc = subprocess.Popen(
        [exe, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
        **_no_window())
    _auth_proc = proc
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise RcloneError('Google sign-in timed out') from exc
    finally:
        if _auth_proc is proc:
            _auth_proc = None
    if proc.returncode != 0:
        lines = (err or out or '').strip().splitlines()
        if proc.returncode < 0 or (proc.returncode == 1 and not lines):
            raise RcloneError('sign-in was stopped')
        raise RcloneError(lines[-1] if lines else f'rclone exit {proc.returncode}')
    return out


def connect_google_drive(name, client_id='', client_secret=''):
    """Create a Google Drive remote.  rclone opens the browser for sign-in
    and blocks until the user approves (or closes) the consent page."""
    args = ['config', 'create', name, 'drive', 'scope=drive']
    if client_id and client_secret:
        args += [f'client_id={client_id}', f'client_secret={client_secret}']
    _run_sign_in(args)


def remote_settings(name):
    """The remote's config section as a dict (empty if unknown)."""
    try:
        data = json.loads(_run(['config', 'dump']) or '{}')
    except (RcloneError, ValueError):
        return {}
    section = data.get(name) or {}
    return section if isinstance(section, dict) else {}


def uses_own_client(name):
    settings = remote_settings(name)
    return bool(settings.get('client_id') and settings.get('client_secret'))


def set_drive_client(name, client_id, client_secret):
    """Store your own Google client ID/secret on a Drive remote and sign in
    again with it (rclone opens the browser and waits for the approval)."""
    _run_sign_in(['config', 'update', name, f'client_id={client_id.strip()}',
                  f'client_secret={client_secret.strip()}', 'config_refresh_token=true'])


def chunk_size_for(bps, seconds=20):
    """Drive upload piece size that finishes in about ``seconds`` at ``bps``.

    Google drops (HTTP 408 "Request Timeout") an upload piece that takes too
    long to arrive, which happens with big pieces under a low speed limit.
    Power of two between 1M and 32M; no limit → 32M."""
    if not bps or bps <= 0:
        return '32M'
    mb = 1
    while mb < 32 and (mb * 2) * 1024 * 1024 <= bps * seconds:
        mb *= 2
    return f'{mb}M'


def start_transfer(sources_dir, destination, *, files=None, move=False, bwlimit_bps=0,
                   skip_existing=False, chunk_bps=None):
    """Start ``rclone copy|move`` and return the Popen object.

    ``files`` is an optional list of file names relative to ``sources_dir``;
    when given only those files are transferred (via --files-from-raw).
    Progress is reported as JSON lines on stderr (see parse_stats_line).
    """
    exe = find_rclone()
    if not exe:
        raise RcloneError('rclone not found')
    args = [exe, 'move' if move else 'copy', sources_dir, destination,
            '--use-json-log', '--stats', '1s', '--stats-log-level', 'NOTICE',
            '--log-level', 'NOTICE', '--retries', str(RETRIES),
            # Google Drive allows only so many requests per minute (and the
            # shared rclone app often hits that quota).  Fewer, slower
            # requests, bigger upload chunks, and a pause before a whole-file
            # retry so the per-minute quota has time to recover.
            '--tpslimit', '4', '--tpslimit-burst', '4',
            '--drive-chunk-size',
            chunk_size_for(bwlimit_bps if chunk_bps is None else chunk_bps),
            '--low-level-retries', '20',
            # A stalled piece is given up on (and retried) after 2 minutes
            # instead of waiting 5.
            '--timeout', '2m',
            '--retries-sleep', '30s']
    if skip_existing:
        # A file whose name already exists in the cloud folder is left alone
        # (not uploaded, not replaced; with "move" the local copy is kept).
        args.append('--ignore-existing')
    list_file = None
    if files:
        import tempfile
        handle, list_file = tempfile.mkstemp(prefix='siphon_upload_', suffix='.txt')
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write('\n'.join(files) + '\n')
        # --no-traverse: look up just these files instead of listing the
        # whole cloud folder (hundreds of requests saved in big folders).
        args += ['--files-from-raw', list_file, '--no-traverse']
    # Upload speed limit, changeable while running through rclone's
    # localhost-only remote control (random port and password per transfer).
    import secrets
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    rc_user, rc_pass = 'siphon', secrets.token_urlsafe(16)
    args += ['--bwlimit', _bwlimit_arg(bwlimit_bps),
             '--rc', '--rc-addr', f'127.0.0.1:{port}',
             '--rc-user', rc_user, '--rc-pass', rc_pass]
    proc = subprocess.Popen(
        args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
        errors='replace', bufsize=1, **_no_window())
    proc.siphon_list_file = list_file
    proc.siphon_rc = (f'http://127.0.0.1:{port}', rc_user, rc_pass)
    return proc


def suspend_process(proc):
    """Freeze a running rclone (Pause).  Its progress stays where it is."""
    if proc is None or proc.poll() is not None:
        return False
    try:
        if os.name == 'nt':
            import ctypes
            handle = getattr(proc, '_handle', None)
            return bool(handle) and ctypes.windll.ntdll.NtSuspendProcess(int(handle)) == 0
        import signal
        os.kill(proc.pid, signal.SIGSTOP)
        return True
    except Exception:
        return False


def resume_process(proc):
    """Continue a frozen rclone (Resume)."""
    if proc is None or proc.poll() is not None:
        return False
    try:
        if os.name == 'nt':
            import ctypes
            handle = getattr(proc, '_handle', None)
            return bool(handle) and ctypes.windll.ntdll.NtResumeProcess(int(handle)) == 0
        import signal
        os.kill(proc.pid, signal.SIGCONT)
        return True
    except Exception:
        return False


def _bwlimit_arg(bps):
    bps = int(bps or 0)
    return f'{max(1, bps // 1024)}k' if bps > 0 else 'off'


def set_live_bwlimit(proc, bps):
    """Change the speed limit of a running transfer; returns True on success."""
    rc = getattr(proc, 'siphon_rc', None)
    if not rc or proc.poll() is not None:
        return False
    import base64
    import urllib.request
    url, user, password = rc
    body = json.dumps({'rate': _bwlimit_arg(bps)}).encode()
    request = urllib.request.Request(url + '/core/bwlimit', data=body, method='POST')
    request.add_header('Content-Type', 'application/json')
    token = base64.b64encode(f'{user}:{password}'.encode()).decode()
    request.add_header('Authorization', f'Basic {token}')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def parse_stats_line(line):
    """Return ('stats', dict) / ('error', message) / (None, None) for one stderr line."""
    line = (line or '').strip()
    if not line.startswith('{'):
        return ('error', line) if line else (None, None)
    try:
        data = json.loads(line)
    except ValueError:
        return (None, None)
    if isinstance(data.get('stats'), dict):
        return ('stats', data['stats'])
    if str(data.get('level', '')).lower() in ('error', 'critical'):
        return ('error', str(data.get('msg', '')).strip())
    return (None, None)


_ATTEMPT_RE = __import__('re').compile(r'Attempt (\d+)/(\d+) failed with \d+ errors? and: (.*)', __import__('re').S)


def parse_attempt_failed(message):
    """'Attempt 1/3 failed with 1 errors and: <reason>' -> (1, 3, reason) or None."""
    match = _ATTEMPT_RE.search(message or '')
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), match.group(3).strip()
