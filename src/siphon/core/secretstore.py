"""Keeping the app's own files unreadable to anyone but this account.

Settings, the download queue and the history say which sites you added and
what you downloaded.  They are stored scrambled so that opening them in a text
editor shows nothing, and on Windows they can only be unscrambled by the
account that wrote them.

Windows does the work through DPAPI, which ties the data to the signed-in
Windows user without any password to remember.  Elsewhere a key file beside
the data is used instead (same idea, weaker: whoever can read the key file can
read the data).

A file written by an older version is plain text; it is read as it is and
written back scrambled the next time it is saved, so nothing is lost.
"""

from __future__ import annotations

import base64
import os

MAGIC = b'SIPHON1\n'            # marks a scrambled file


class SecretError(Exception):
    pass


# ── Windows: DPAPI, tied to the signed-in account ───────────────────────────
def _dpapi(data: bytes, unprotect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD),
                    ('pbData', ctypes.POINTER(ctypes.c_char))]

    source = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data),
                                         ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    function = (ctypes.windll.crypt32.CryptUnprotectData if unprotect
                else ctypes.windll.crypt32.CryptProtectData)
    args = ([ctypes.byref(source), None, None, None, None, 0x01,
             ctypes.byref(result)] if unprotect else
            [ctypes.byref(source), 'Siphon', None, None, None, 0x01,
             ctypes.byref(result)])
    if not function(*args):
        raise SecretError('Windows refused to unlock this file'
                          if unprotect else 'Windows refused to lock this file')
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


# ── Elsewhere: a key file next to the data ──────────────────────────────────
def _key_path() -> str:
    from siphon.core.paths import product_data_dir
    return str(product_data_dir() / 'key.bin')


def _key() -> bytes:
    path = _key_path()
    try:
        with open(path, 'rb') as handle:
            key = handle.read()
        if len(key) == 32:
            return key
    except OSError:
        pass
    key = os.urandom(32)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, 'wb') as fh:
        fh.write(key)
    return key


def _aes(data: bytes, decrypt: bool) -> bytes:
    from Crypto.Cipher import AES
    key = _key()
    if decrypt:
        nonce, tag, body = data[:16], data[16:32], data[32:]
        return AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(body, tag)
    cipher = AES.new(key, AES.MODE_GCM, nonce=os.urandom(16))
    body, tag = cipher.encrypt_and_digest(data)
    return cipher.nonce + tag + body


def lock(text: str) -> bytes:
    """Scramble text for storage (plain bytes if that is not possible)."""
    raw = text.encode('utf-8')
    try:
        sealed = _dpapi(raw, False) if os.name == 'nt' else _aes(raw, False)
    except Exception as exc:
        print(f'[store] saved without scrambling: {exc}', flush=True)
        return raw
    return MAGIC + base64.b64encode(sealed)


def unlock(data: bytes) -> str:
    """Read back a file written by lock(); plain files are returned as they are."""
    if not data.startswith(MAGIC):
        # Written by an older version: plain text, and real text or nothing.
        return data.decode('utf-8')
    sealed = base64.b64decode(data[len(MAGIC):])
    raw = _dpapi(sealed, True) if os.name == 'nt' else _aes(sealed, True)
    return raw.decode('utf-8')


def read_text(path: str) -> str:
    """'' when the file is missing; raises SecretError when it cannot be read."""
    try:
        with open(path, 'rb') as handle:
            data = handle.read()
    except OSError:
        return ''
    if not data:
        return ''
    try:
        return unlock(data)
    except Exception as exc:
        raise SecretError(f'{os.path.basename(path)} could not be read: {exc}') from exc


def write_text(path: str, text: str) -> None:
    """Replace a file with the scrambled text, atomically."""
    import time
    import uuid
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = f'{path}.{uuid.uuid4().hex[:8]}.tmp'
    try:
        with open(tmp, 'wb') as handle:
            handle.write(lock(text))
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
