"""Identify destination I/O failures separately from retryable transport errors."""

import errno
import re


def storage_failure_message(message):
    return bool(re.search(
        r'no space left|disk (?:is )?full|input/output error|i/o error|'
        r'device (?:is )?not ready|no such device|device not connected|'
        r'error (?:writing|closing)|failed to (?:write|flush)',
        str(message), re.IGNORECASE))


class StorageWriteError(OSError):
    """Destination storage failed; stop writes and require an explicit retry."""

    def __init__(self, path, cause, operation='access'):
        self.path = str(path)
        self.cause = cause
        self.operation = operation
        code = getattr(cause, 'errno', None) or errno.EIO
        if code == errno.ENOENT:
            hint = ('The path is missing or unavailable; check the drive and '
                    'choose an existing writable download folder')
        elif code == errno.ENOSPC:
            hint = 'Free space on the selected download drive before retrying'
        elif code in (errno.EACCES, errno.EPERM):
            hint = ('Check folder permission and whether another application '
                    'has locked the file')
        elif code == errno.ENOTDIR:
            hint = 'A path component is not a directory; select a download folder'
        elif code == errno.EINVAL:
            hint = 'Check the destination path and drive; try a shorter writable path'
        else:
            hint = 'Check free space, drive availability and device health before retrying'
        detail = getattr(cause, 'strerror', None) or str(cause)
        super().__init__(
            code,
            f"Destination storage I/O failed [{operation}] at '{self.path}': "
            f'{hint}. Details: {detail}. Downloads stopped.', self.path)


class _StorageFile:
    def __init__(self, path, mode, *args, **kwargs):
        self.path = path
        try:
            self.file = open(path, mode, *args, **kwargs)
        except OSError as exc:
            operation = ('open for writing' if any(flag in mode for flag in 'wax+')
                         else 'open for reading')
            raise StorageWriteError(path, exc, operation=operation) from exc

    def _io(self, method, *args, **kwargs):
        try:
            return getattr(self.file, method)(*args, **kwargs)
        except OSError as exc:
            raise StorageWriteError(self.path, exc, operation=method) from exc

    def write(self, data):
        written = self._io('write', data)
        if written != len(data):
            raise StorageWriteError(
                self.path, OSError(errno.EIO, 'short write'), operation='write')
        return written

    def read(self, *args):
        return self._io('read', *args)

    def seek(self, *args):
        return self._io('seek', *args)

    def truncate(self, *args):
        return self._io('truncate', *args)

    def flush(self):
        return self._io('flush')

    def __getattr__(self, name):
        return getattr(self.file, name)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self._io('close')
        except StorageWriteError:
            if kind is None:
                raise


def storage_open(path, mode, *args, **kwargs):
    return _StorageFile(path, mode, *args, **kwargs)


_HIDDEN = 0x02          # FILE_ATTRIBUTE_HIDDEN
_NORMAL = 0x80          # FILE_ATTRIBUTE_NORMAL: what "no attributes" means


def _on_windows():
    """Whether file attributes exist here.

    Its own function so a test can say yes without setting ``os.name``, which
    would make pathlib try to build Windows paths on a Linux machine.
    """
    import os
    return os.name == 'nt'


def hide_while_working(path):
    """Keep a half-finished file out of the user's folder view.

    Downloading leaves a .part beside the video and a small state file next
    to it, so a folder being filled looked like three files per video.  On
    Windows they are marked hidden; elsewhere the name already starts with a
    dot, which file managers hide by themselves.
    """
    if not _on_windows():
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), _HIDDEN)
    except Exception:
        pass        # cosmetic only: never let this stop a download


def show_when_finished(path):
    """Undo hide_while_working, for a file that is now the finished video.

    Renaming a file on Windows carries its attributes along, so the .part
    file's hidden mark lands on the video the moment it takes its real name.
    The download had worked and the file was there; it just could not be
    seen, which is worse than never having hidden anything.  Every rename
    that ends a download therefore clears the mark again.
    """
    if not _on_windows():
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        now = kernel32.GetFileAttributesW(str(path))
        if now == -1 or not now & _HIDDEN:
            return          # never hidden, or gone: nothing to undo
        kernel32.SetFileAttributesW(str(path), now & ~_HIDDEN or _NORMAL)
    except Exception:
        pass        # cosmetic only: the file itself is already complete


def unhide_finished_downloads(folder):
    """Clear the hidden mark left on videos finished before the fix.

    Returns how many files were brought back into view.  Only whole videos
    are touched: a .part or .state.json belongs to a download that may still
    be running, and hiding those is wanted.
    """
    if not _on_windows():
        return 0
    from pathlib import Path
    fixed = 0
    try:
        entries = list(Path(folder).iterdir())
    except OSError:
        return 0
    for item in entries:
        if item.suffix in ('.part', '.json') or item.name.startswith('.'):
            continue
        try:
            if not item.is_file():
                continue
        except OSError:
            continue
        before = _hidden(item)
        show_when_finished(item)
        if before and not _hidden(item):
            fixed += 1
    return fixed


def _hidden(path):
    try:
        import ctypes
        now = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return now != -1 and bool(now & _HIDDEN)
    except Exception:
        return False
