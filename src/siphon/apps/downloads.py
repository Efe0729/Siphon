"""Testable download-workflow helpers shared by the desktop UI.

This module deliberately has no Tk dependency.  Queue import/export, filtering,
error classification and storage checks can therefore be verified without
constructing a window and can later be reused by another UI.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
TERMINAL_STATES = frozenset({'已下載', '已取消', '網址錯誤'})
ACTIVE_STATES = frozenset({'準備中', '下載中'})
QUEUED_STATES = frozenset({'等待中', '等待重試', '已排程'})
FAILED_STATES = frozenset({'未完成', '封鎖/解析失敗', '網址錯誤'})
DONE_STATES = frozenset({'已下載', '已存在'})
PAUSED_STATES = frozenset({'已暫停', '已取消'})


@dataclass(frozen=True)
class QueueAddSummary:
    """Outcome shown after adding or starting a batch."""

    requested: int = 0
    added: int = 0
    duplicates: int = 0
    unsupported: int = 0
    started: int = 0


@dataclass(frozen=True)
class StoragePreflight:
    ok: bool
    path: str
    free_bytes: int = 0
    error: str = ''


@dataclass(frozen=True)
class DownloadProblem:
    code: str
    retryable: bool


# A line that is only 'site.com/videos/12' — no http:// in front of it.
_BARE_URL_RE = re.compile(
    r"^\s*((?:[\w-]+\.)+[a-z]{2,}(?:/[^\s'\"<>]*)?)\s*$", re.I | re.M)


def extract_urls(text: object, *, max_urls: int = 5000) -> list[str]:
    """Every address in the text, in the order a person would read them.

    A line without 'http://' in front is still an address: people paste and
    save them that way, so the prefix is added here instead of the line being
    dropped.
    """
    seen: set[str] = set()
    urls: list[str] = []
    body = str(text or '')
    for match in URL_RE.finditer(body):
        url = match.group(0).rstrip(".,;:!?)]}'\"")
        if len(url) > 2048 or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= max_urls:
            return urls
    for match in _BARE_URL_RE.finditer(body):
        url = 'https://' + match.group(1).rstrip(".,;:!?)]}'\"")
        if len(url) > 2048 or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= max_urls:
            break
    return urls


def _read_text_file(source: Path) -> str:
    """A text file saved by any ordinary editor.

    Notepad on a Turkish Windows still writes ANSI (cp1254) by default, so a
    file that is not UTF-8 must not be refused — the addresses in it are
    plain ASCII either way.
    """
    raw = source.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16', 'replace')
    for encoding in ('utf-8-sig', 'cp1254', 'latin-1'):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', 'replace')


def load_url_file(path: str, *, max_urls: int = 5000) -> list[str]:
    """Read URLs from a text, CSV or JSON file, whatever its encoding."""
    source = Path(path)
    if source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('URL import file is too large')
    suffix = source.suffix.lower()
    if suffix == '.json':
        raw = json.loads(_read_text_file(source))
        if isinstance(raw, dict):
            raw = raw.get('items', raw.get('urls', []))
        values = []
        for item in raw if isinstance(raw, list) else []:
            values.append(item.get('url', '') if isinstance(item, dict) else item)
        return extract_urls('\n'.join(str(value) for value in values),
                            max_urls=max_urls)
    if suffix == '.csv':
        if True:
            handle = io.StringIO(_read_text_file(source))
            values = []
            for row in csv.DictReader(handle):
                lowered = {str(key or '').strip().lower(): value
                           for key, value in row.items()}
                values.append(
                    lowered.get('url') or lowered.get('網址') or
                    lowered.get('source url') or '')
                if len(values) >= max_urls:
                    break
        return extract_urls('\n'.join(str(value) for value in values),
                            max_urls=max_urls)
    return extract_urls(_read_text_file(source), max_urls=max_urls)


def site_name(url: str) -> str:
    """What to call the site a link came from.

    The name the user gave it when they added it, else its host.
    """
    host = (urlsplit(str(url or '')).hostname or '').lower()
    if not host:
        return 'Local'
    from siphon.core import config
    return config.custom_site_name(host) or host


def video_code(url: str, title: str = '') -> str:
    """Return a concise code for secondary row metadata."""
    first = str(title or '').strip().split(maxsplit=1)
    if first and re.search(r'\d', first[0]):
        return first[0]
    path = urlsplit(str(url or '')).path.rstrip('/').rsplit('/', 1)[-1]
    return path or str(url or '')


_GROUPS = {'active': ACTIVE_STATES, 'queued': QUEUED_STATES,
           'failed': FAILED_STATES, 'done': DONE_STATES,
           'paused': PAUSED_STATES}


# How a list can be ordered.  'default' is the one the list is built
# around — what is running, what is waiting, what is done — and the rest are
# for finding one particular row in a long list.
SORTS = ('default', 'name', 'size', 'newest', 'oldest')

_SIZE_UNITS = {'b': 1, 'kb': 1 << 10, 'mb': 1 << 20,
               'gb': 1 << 30, 'tb': 1 << 40}


def item_size(item):
    """How big the file is, in bytes, read off the size shown on the row.

    The row carries text like "120.5 MB / 300.0 MB": the whole size is the
    last number in it, and a row that has not started yet has none, which
    sorts as nothing rather than as zero bytes.
    """
    text = str(getattr(item, 'size_text', '') or '')
    found = re.findall(r'([\d.]+)\s*([KMGT]?B)\b', text, re.I)
    if not found:
        return -1.0
    amount, unit = found[-1]
    try:
        return float(amount) * _SIZE_UNITS.get(unit.lower(), 1)
    except ValueError:
        return -1.0


def item_time(item):
    """When this row last meant something: when it finished, else when it
    was added."""
    return float(getattr(item, 'completed_at', 0)
                 or getattr(item, 'created_at', 0)
                 or getattr(item, 'updated_at', 0) or 0)


def filter_items(items, filter_name: str, queue_positions=None, sort='default'):
    """The rows to show, in the order to show them.

    ``queue_positions`` is {url: place in the waiting queue} — without it the
    waiting rows keep the order they were added in, which is what the list
    used to do and why moving a download to the front of the queue appeared
    to do nothing.

    ``sort`` replaces that grouping entirely when it is not 'default': asking
    for the biggest file means the biggest file, wherever it is in its life.
    """
    key = str(filter_name or 'all').strip().lower()
    states = _GROUPS.get(key)
    chosen = list(items if states is None
                  else (item for item in items if item.state in states))
    mode = str(sort or 'default').strip().lower()
    if mode == 'name':
        return sorted(chosen, key=lambda i: str(getattr(i, 'name', '')).lower())
    if mode == 'size':
        return sorted(chosen, key=item_size, reverse=True)
    if mode == 'newest':
        return sorted(chosen, key=item_time, reverse=True)
    if mode == 'oldest':
        return sorted(chosen, key=item_time)
    return sorted(chosen, key=_row_order(queue_positions))


# What "All" puts at the top: what is running, then what is waiting its turn,
# then what is stopped, and the finished ones last.
_ALL_ORDER = (ACTIVE_STATES, QUEUED_STATES, PAUSED_STATES, FAILED_STATES)


def _all_order(item):
    for rank, states in enumerate(_ALL_ORDER):
        if item.state in states:
            return rank
    return len(_ALL_ORDER)


def _row_order(queue_positions=None):
    """How the rows sort: by state, then by what makes sense inside it.

    A waiting download sorts by its place in the queue, because that place is
    what the person set and what decides which one runs next — a row sitting
    somewhere else is the list disagreeing with itself.  A finished one sorts
    newest first, since the one just finished is the one being looked for.
    Everything else keeps the order it was added in, so the list stays still
    while nothing changes.
    """
    places = dict(queue_positions or {})

    def key(item):
        rank = _all_order(item)
        if item.state in QUEUED_STATES:
            # Anything not in the queue yet goes after what is, in added order.
            return (rank, 0, places.get(getattr(item, 'url', ''), 1 << 30))
        if item.state in DONE_STATES:
            finished = (getattr(item, 'completed_at', 0)
                        or getattr(item, 'updated_at', 0) or 0)
            return (rank, 0, -float(finished))
        return (rank, 0, 0)

    return key


def classify_download_problem(error: object, state: str = '') -> DownloadProblem:
    value = str(error or '').lower()
    if state == '網址錯誤' or 'unsupported' in value or '不支援' in value:
        return DownloadProblem('unsupported_url', False)
    if ('no space' in value or 'disk full' in value or
            'not enough free' in value or 'enospc' in value):
        return DownloadProblem('disk_full', False)
    if ('permission' in value or 'access is denied' in value or
            'permission denied' in value):
        return DownloadProblem('permission', False)
    if ('ffmpeg' in value and ('not found' in value or 'missing' in value)):
        return DownloadProblem('ffmpeg_missing', False)
    if (state == '封鎖/解析失敗' or 'cloudflare' in value or
            'blocked' in value or '429' in value or '403' in value):
        return DownloadProblem('blocked', True)
    if ('timeout' in value or 'timed out' in value or
            'connection' in value or 'reset by peer' in value or
            'temporarily unavailable' in value):
        return DownloadProblem('network', True)
    if ('not found' in value or '404' in value or 'removed' in value):
        return DownloadProblem('video_missing', False)
    if state in FAILED_STATES or value:
        return DownloadProblem('parse_or_unknown', True)
    return DownloadProblem('', False)


def storage_preflight(
        destination: str, *, minimum_free_bytes: int = 512 * 1024 * 1024,
) -> StoragePreflight:
    """Create/check a destination before a batch is allowed to start."""
    path = os.path.abspath(destination or 'download')
    try:
        os.makedirs(path, exist_ok=True)
        if not os.path.isdir(path):
            return StoragePreflight(False, path, error='not_a_directory')
        descriptor, probe = tempfile.mkstemp(
            prefix='.siphon-write-test-', dir=path)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                descriptor = -1
                handle.write(b'siphon')
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.remove(probe)
            except FileNotFoundError:
                pass
        free = int(shutil.disk_usage(path).free)
        if free < max(0, int(minimum_free_bytes)):
            return StoragePreflight(False, path, free, 'low_space')
        return StoragePreflight(True, path, free)
    except OSError as exc:
        return StoragePreflight(False, path, error=str(exc))


def format_eta(seconds: object) -> str:
    try:
        remaining = max(0, int(float(seconds)))
    except (TypeError, ValueError, OverflowError):
        return ''
    if remaining >= 86400:
        return f'{remaining // 86400}d {(remaining % 86400) // 3600}h'
    if remaining >= 3600:
        return f'{remaining // 3600}h {(remaining % 3600) // 60}m'
    if remaining >= 60:
        return f'{remaining // 60}m {remaining % 60}s'
    return f'{remaining}s'


def next_schedule_epoch(value: object, *, now: float | None = None) -> float:
    """Return the next local HH:MM occurrence; blank means immediately."""
    raw = str(value or '').strip()
    current = time.time() if now is None else float(now)
    if not raw:
        return 0.0
    match = re.fullmatch(r'([01]?\d|2[0-3]):([0-5]\d)', raw)
    if not match:
        raise ValueError('Schedule must use HH:MM')
    local = time.localtime(current)
    candidate = time.mktime((
        local.tm_year, local.tm_mon, local.tm_mday,
        int(match.group(1)), int(match.group(2)), 0,
        local.tm_wday, local.tm_yday, local.tm_isdst,
    ))
    if candidate <= current:
        candidate += 86400
    return candidate


def export_items(items, path: str) -> None:
    """Export a user-readable queue/history snapshot to CSV or JSON."""
    fields = (
        'job_id', 'state', 'name', 'site', 'code', 'progress', 'speed',
        'eta', 'url', 'destination', 'resolution', 'filename_template',
        'error_code', 'error', 'created_at', 'updated_at',
    )
    records = []
    for item in items:
        record = {
            'job_id': getattr(item, 'job_id', ''),
            'state': getattr(item, 'state', ''),
            'name': getattr(item, 'name', ''),
            'site': getattr(item, 'site', '') or site_name(item.url),
            'code': video_code(item.url, getattr(item, 'name', '')),
            'progress': getattr(item, 'progress', 0),
            'speed': getattr(item, 'speed', ''),
            'eta': getattr(item, 'eta', ''),
            'url': getattr(item, 'url', ''),
            'destination': getattr(item, 'dest', ''),
            'resolution': getattr(item, 'resolution', ''),
            'filename_template': getattr(item, 'filename_template', ''),
            'error_code': getattr(item, 'error_code', ''),
            'error': getattr(item, 'error', ''),
            'created_at': getattr(item, 'created_at', 0),
            'updated_at': getattr(item, 'updated_at', 0),
        }
        records.append(record)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.tmp')
    if destination.suffix.lower() == '.json':
        temporary.write_text(
            json.dumps({'schema': 1, 'items': records}, ensure_ascii=False,
                       indent=2),
            encoding='utf-8',
        )
    else:
        with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            # Site metadata is untrusted. Excel may evaluate a quoted CSV cell
            # as a formula, so neutralize it in the user-facing CSV export.
            # JSON remains lossless; internal queue persistence is separate.
            writer.writerows({
                key: ("'" + value if isinstance(value, str) and
                      (value[:1] in {'=', '+', '-', '@', '\t', '\r', '\n'} or
                       value.lstrip().startswith(('=', '+', '-', '@')))
                      else value)
                for key, value in record.items()
            } for record in records)
            handle.flush()
            os.fsync(handle.fileno())
    os.replace(temporary, destination)
