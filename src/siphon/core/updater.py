#!/usr/bin/env python
# coding: utf-8
"""Updater logic for the frozen Windows GUI app."""

import os
import re
import subprocess
import sys
import tempfile

import requests
from siphon.core import config
from siphon import metadata


REPO = metadata.GITHUB_REPOSITORY
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
API_CANDIDATES = (API_LATEST,) + tuple(
    f"https://api.github.com/repos/{repo}/releases/latest"
    for repo in metadata.LEGACY_GITHUB_REPOSITORIES
)


def _session():
    """requests session that reuses the ONE shared SSLContext (ssl_util) so the
    updater's background HTTPS can't race a fresh SSLContext construction with the
    site scrapers — that race is the concurrent-SSLContext native crash (issue #25)."""
    s = requests.Session()
    try:
        from siphon.core import ssl as ssl_util
        s.mount('https://', ssl_util.SharedSSLAdapter())
    except Exception:
        pass
    return s


def parse_version(s):
    text = str(s or '').strip()
    if text.lower().startswith('v'):
        text = text[1:]
    parts = re.split(r'[.\-_\s+]+', text)
    nums = []
    for part in parts:
        if not part:
            continue
        m = re.match(r'\d+', part)
        nums.append(int(m.group(0)) if m else 0)
        if len(nums) >= 3:
            break
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def is_newer(latest, current):
    return parse_version(latest) > parse_version(current)


# Updates come only from the repository this app was published from, named in
# metadata.GITHUB_REPOSITORY.  While that is empty there is nowhere safe to
# look: the updater downloads and runs the build it finds, so it must never
# fall back to another project's releases.
UPDATES_DISABLED = not REPO
PERSONAL_FORK = UPDATES_DISABLED      # old name, kept for existing callers


def check_latest(timeout=10):
    if PERSONAL_FORK:
        return {'version': '0', 'tag': '', 'html_url': ''}
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{metadata.PRODUCT_NAME}-Updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with _session() as s:
            response = None
            for api_url in API_CANDIDATES:
                candidate = s.get(
                    api_url,
                    headers=headers,
                    timeout=timeout,
                    **config.proxy_request_kwargs(),
                )
                if candidate.status_code == 200:
                    response = candidate
                    break
        if response is None:
            return None
        data = response.json()
        tag = str(data.get('tag_name') or '').strip()
        if not tag:
            return None
        version = tag[1:] if tag.lower().startswith('v') else tag
        assets = {}
        for asset in data.get('assets') or []:
            name = asset.get('name')
            url = asset.get('browser_download_url')
            if name and url:
                assets[str(name)] = str(url)
        return {
            "tag": tag,
            "version": version,
            "html_url": data.get('html_url') or '',
            "notes": str(data.get('body') or '')[:4000],
            "assets": assets,
        }
    except Exception:
        return None


def current_exe_name():
    if is_frozen():
        return os.path.basename(sys.executable)
    return metadata.release_asset_candidates('browse')[0]


def find_asset_url(release_info, channel='browse'):
    """Find a canonical or v2-compatible asset for a logical application."""
    assets = (release_info or {}).get('assets') or {}
    for name in metadata.release_asset_candidates(channel):
        url = assets.get(name)
        if url:
            return str(url)
    return ''


def find_checksum_url(release_info):
    assets = (release_info or {}).get('assets') or {}
    for key in ('Siphon_SHA256SUMS.txt',):
        if assets.get(key):
            return str(assets[key])
    return ''


def fetch_expected_sha256(release_info, asset_name, timeout=10):
    """Return the expected lowercase SHA-256 hex digest for ``asset_name``, or ''."""
    url = find_checksum_url(release_info)
    if not url or not asset_name:
        return ''
    try:
        with _session() as s:
            resp = s.get(url, timeout=timeout, **config.proxy_request_kwargs())
        if getattr(resp, 'status_code', 0) != 200:
            return ''
        for raw_line in str(resp.text or '').splitlines():
            parts = raw_line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            digest, filename = parts[0].strip().lower(), parts[1].strip().lstrip('*')
            if (len(digest) == 64
                    and all(c in '0123456789abcdef' for c in digest)
                    and os.path.basename(filename) == asset_name):
                return digest
    except Exception:
        pass
    return ''


def is_frozen():
    return bool(getattr(sys, 'frozen', False))


def _remove_quiet(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def download_asset(url, dest_path, progress_cb=None, timeout=60,
                   expected_sha256=''):
    import hashlib
    part_path = dest_path + '.part'
    _remove_quiet(part_path)
    expected = str(expected_sha256 or '').strip().lower()
    hasher = hashlib.sha256() if expected else None
    try:
        with _session() as s, s.get(
                url, stream=True, timeout=timeout,
                **config.proxy_request_kwargs()) as r:
            if r.status_code != 200:
                return False
            total = int(r.headers.get('content-length') or 0)
            downloaded = 0
            with open(part_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    if hasher is not None:
                        hasher.update(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(downloaded, total)
                        except Exception:
                            pass

        if os.path.getsize(part_path) <= 3_000_000:
            _remove_quiet(part_path)
            return False
        with open(part_path, 'rb') as f:
            if f.read(2) != b'MZ':
                _remove_quiet(part_path)
                return False
        if hasher is not None and hasher.hexdigest().lower() != expected:
            _remove_quiet(part_path)
            return False
        os.replace(part_path, dest_path)
        return True
    except Exception:
        _remove_quiet(part_path)
        return False


def _bat_quote(path):
    return '"' + str(path).replace('"', '""').replace('%', '%%') + '"'


def _clean_restart_env(env=None):
    """Strip PyInstaller bootloader variables so a restarted exe extracts fresh.

    Without this, the helper batch script inherits ``_PYI_PARENT_PROCESS_LEVEL``
    and ``_PYI_APPLICATION_HOME_DIR`` (or ``_MEIPASS2``) and passes them to the
    updated executable, so its bootloader skips extraction and fails trying to
    load ``python*.dll`` from the exiting process's deleted ``_MEI*`` temp folder.
    """
    cleaned = dict(os.environ if env is None else env)
    mei_dirs = []
    meipass = getattr(sys, '_MEIPASS', '')
    if meipass:
        mei_dirs.append(os.path.normcase(os.path.normpath(meipass)))
    for key in list(cleaned):
        upper = key.upper()
        if upper.startswith('_PYI_') or upper in ('_MEIPASS', '_MEIPASS2'):
            val = cleaned.pop(key, '')
            if val and ('_MEI' in val.upper() or upper in ('_PYI_APPLICATION_HOME_DIR', '_MEIPASS', '_MEIPASS2')):
                mei_dirs.append(os.path.normcase(os.path.normpath(val)))
    if mei_dirs:
        for tk_key in ('TCL_LIBRARY', 'TK_LIBRARY'):
            val = cleaned.get(tk_key, '')
            norm = os.path.normcase(os.path.normpath(val)) if val else ''
            if norm and any(norm == d or norm.startswith(d + os.sep) for d in mei_dirs):
                cleaned.pop(tk_key, None)
        path_key = 'PATH' if 'PATH' in cleaned else ('Path' if 'Path' in cleaned else '')
        if path_key:
            kept = [
                part for part in cleaned[path_key].split(os.pathsep)
                if not any(
                    os.path.normcase(os.path.normpath(part)) == d
                    or os.path.normcase(os.path.normpath(part)).startswith(d + os.sep)
                    for d in mei_dirs if part
                )
            ]
            cleaned[path_key] = os.pathsep.join(kept)
    return cleaned


def apply_update_and_restart(new_exe_path):
    if PERSONAL_FORK or not is_frozen():
        return False
    try:
        cur = sys.executable
        pid = os.getpid()
        bat = os.path.join(tempfile.gettempdir(), f'siphon_update_{pid}.bat')
        body = f"""@echo off
setlocal
set "_PYI_PARENT_PROCESS_LEVEL="
set "_PYI_APPLICATION_HOME_DIR="
set "_PYI_ARCHIVE_FILE="
set "_PYI_SPLASH_IPC="
set "_MEIPASS="
set "_MEIPASS2="
set /a n=0
:retry
move /Y {_bat_quote(new_exe_path)} {_bat_quote(cur)} >nul 2>&1
if not errorlevel 1 goto done
set /a n+=1
if %n% GEQ 120 goto giveup
ping -n 2 127.0.0.1 >nul
goto retry
:giveup
del {_bat_quote(new_exe_path)} >nul 2>&1
:done
ping -n 2 127.0.0.1 >nul
start "" {_bat_quote(cur)}
del "%~f0" >nul 2>&1
"""
        encoding = 'mbcs' if os.name == 'nt' else 'utf-8'
        with open(bat, 'w', encoding=encoding, errors='replace') as f:
            f.write(body)
        flags = (
            getattr(subprocess, 'CREATE_NO_WINDOW', 0) |
            getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        )
        subprocess.Popen(['cmd', '/c', bat], creationflags=flags,
                         env=_clean_restart_env(), close_fds=True)
        return True
    except Exception:
        return False
