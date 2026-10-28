#!/usr/bin/env python
# coding: utf-8
"""Siphon: interactive site, site, site, and site GUI."""

import os
import sys
import re
import io
import csv
import json
import time
import shutil
import webbrowser
import threading
import queue
import concurrent.futures
import collections
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional
from urllib.parse import urlsplit

import customtkinter as ctk
import requests
from PIL import Image

from siphon.core import config
from siphon.core.storage import StorageWriteError
from siphon import sites as M3U8Sites
from siphon.i18n import sites as site_i18n
from siphon.core import updater
from siphon.core import dl_history
from siphon.core.ssl import SharedSSLAdapter, get_shared_ssl_context
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import (
    site_FILTER_TAG_GROUPS,
    siteBrowser,
    Sitesite,
)
from siphon.sites.base import (
    MirrorsBlockedError, is_unreachable_error, last_mirror_failure)
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.trannyone import TrannyoneBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.sites.site import siteBrowser
from siphon.core import secretstore
from siphon.core.secretstore import SecretError
from siphon.core.config import headers
from siphon.i18n.locales import T, set_lang, get_lang, ui_font, LANGUAGES, state_label
from siphon.ui.preview import open_video_preview
from siphon.ui import speed_limit
from siphon.ui import scroll as ui_scroll

ui_scroll.install()
from siphon.apps.upload_tab import UploadTab
from siphon.upload.manager import UploadManager
from siphon.ui.theme import (
    ACCENT, ACCENT_HOVER, ACCENT_DIM,
    SUCCESS, SUCCESS_DIM, WARNING, WARNING_DIM, ERROR_C, ERROR_DIM,
    BG_DARK, BG_CARD, BG_CARD_HOVER, BG_INPUT, BG_HEADER, BG_SECTION,
    BG_SIDEBAR, BG_BADGE, TEXT_PRI, TEXT_SEC, TEXT_DIM, TEXT_LINK,
    BORDER, BORDER_HOVER, BORDER_CARD, WHITE, CARD_RADIUS, CONTROL_RADIUS,
    color_for_mode,
    browse_columns_for_width,
)
from siphon.metadata import APP_DISPLAY_NAMES, PRODUCT_NAME, VERSION
from siphon.apps.downloads import (
    ACTIVE_STATES,
    DONE_STATES,
    FAILED_STATES,
    PAUSED_STATES,
    QUEUED_STATES,
    QueueAddSummary,
    classify_download_problem,
    export_items,
    extract_urls,
    filter_items,
    format_eta,
    load_url_file,
    next_schedule_epoch,
    site_name,
    storage_preflight,
    video_code,
)

APP_VERSION = VERSION

# issue #24: startup breadcrumbs — no-op if crashlog unavailable
try:
    from siphon.core.crashlog import breadcrumb as _crumb
except Exception:
    def _crumb(msg):
        pass

DEFAULT_CONCURRENT = 2
MAX_CONCURRENT = 32
SLOW_REQUEUE_GRACE_SECONDS = 60
SLOW_REQUEUE_MAX_ATTEMPTS = 3
SETTINGS_INLINE_HELP_WRAP = 620
MAX_VISIBLE_ROWS = 200
ROW_BUILD_BUDGET = 40
MAX_PERSIST_ROWS = 1000
HARD_LOAD_LIMIT = 5000
CSV_PATH = config.queue_csv_path()
# Downloads that were running or queued when the app was closed, in order,
# so they continue automatically on the next start.
RESUME_PATH = os.path.join(os.path.dirname(CSV_PATH), 'resume_on_start.json')
_RUNNING_STATES = ('準備中', '下載中')
_QUEUED_STATES = ('等待中', '等待重試', '已排程')
ERR_BLOCKED = '__cf_blocked__'

# Sites shown in the Browse tab's site picker (in menu order).  site,
# site and site are still downloadable by pasting a link; they are only
# hidden from Browse.  Add new browsable sites here.
SITES = {
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
    'Tranny.one': {'browser': TrannyoneBrowser},
    'site': {'browser': siteBrowser},
    'site': {'browser': siteBrowser},
}


BUILTIN_SITES = tuple(SITES)
BUILTIN_SITE_ENTRIES = dict(SITES)
# Nothing is listed until the user adds a site.
SITES.clear()

_VIDEO_EXTS = ('.mp4', '.mkv', '.ts', '.webm', '.mov', '.m4v')


def _find_item_file(item, known_path=None, default_dest='download'):
    """The downloaded file of a row: the remembered path, else <dest>/<name>.mp4,
    else the newest video in <dest> whose name starts with the row's name."""
    if getattr(item, 'local', False) and os.path.isfile(str(item.url)):
        return os.path.abspath(item.url)
    if known_path and os.path.isfile(known_path):
        return os.path.abspath(known_path)
    folder = os.path.abspath(item.dest or default_dest)
    name = str(item.name or '').strip()
    if not name or not os.path.isdir(folder):
        return None
    for ext in _VIDEO_EXTS:
        candidate = os.path.join(folder, name + ext)
        if os.path.isfile(candidate):
            return candidate
    key = name.casefold()
    matches = []
    try:
        for entry in os.scandir(folder):
            stem, ext = os.path.splitext(entry.name)
            if (entry.is_file() and ext.lower() in _VIDEO_EXTS
                    and stem.casefold().startswith(key)):
                matches.append(entry.path)
    except OSError:
        return None
    return max(matches, key=os.path.getmtime) if matches else None


def _reveal_in_explorer(path):
    """Open the file's folder with the file selected.  False if that failed."""
    import platform
    import subprocess
    path = os.path.abspath(path)
    try:
        system = platform.system()
        if system == 'Windows':
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        elif system == 'Darwin':
            subprocess.Popen(['open', '-R', path])
        else:
            return False   # most Linux file managers can't select a file
        return True
    except OSError:
        return False


_SLUG_TITLE_HOSTS = ('site', 'site', 'site', 'site', 'site',
                     'site', 'site', 'site', 'tranny.one', 'example.com', 'site', 'porn-xp', 'site')


def _section_label(name):
    """A site's section/sort name in the current language (Turkish only;
    tag and category names from the sites stay as they are)."""
    if get_lang() == 'tr':
        from siphon.i18n.tr import SECTION_TR
        return SECTION_TR.get(name, name)
    return name


def _fallback_name(url):
    """Row label before the real title is known: 'big-ass-anal' -> 'Big Ass Anal'
    on the newer sites; the last URL part (e.g. a JAV code) elsewhere."""
    last = str(url or '').rstrip('/').split('/')[-1]
    try:
        host = (urlsplit(str(url)).hostname or '').lower()
    except ValueError:
        return last
    if any(h in host for h in _SLUG_TITLE_HOSTS):
        from siphon.sites import kvs as _kvs
        return _kvs.slug_to_title(last) or last
    return last


def builtin_browser_for_host(host):
    """(name, browser) when this app has code written for that site.

    The app ships with no sites in it; these are recipes, used only once the
    user adds a site they happen to cover, because they browse and download it
    better than the general-purpose reader can.
    """
    host = str(host or '').lower().replace('www.', '')
    for name, entry in BUILTIN_SITE_ENTRIES.items():
        browser = entry['browser']
        root_host = (urlsplit(getattr(browser, 'ROOT', '') or '').hostname or '')
        root_host = root_host.lower().replace('www.', '')
        if root_host and (host == root_host or host.endswith('.' + root_host)
                          or root_host.endswith('.' + host)):
            return name, browser
    for name, entry in BUILTIN_SITE_ENTRIES.items():
        for mirror in getattr(entry['browser'], 'MIRRORS', ()) or ():
            mirror_host = (urlsplit(str(mirror)).hostname or str(mirror)).lower()
            if mirror_host.replace('www.', '') == host:
                return name, entry['browser']
    return '', None


def site_catalog():
    """The sites the user added: [{'name','browser','builtin','hidden'}].

    ``builtin`` means this app has its own code for that site and is using it
    instead of the general-purpose reader.
    """
    from siphon.sites.genericbrowse import browser_for
    entries = {}
    for entry in config.get_custom_sites():
        host = entry['host']
        name = entry.get('name') or host
        known_name, known = builtin_browser_for_host(host)
        if known is not None:
            entries[known_name] = {'name': known_name, 'browser': known,
                                   'builtin': True}
        else:
            entries[name] = {'name': name, 'browser': browser_for(host, name),
                             'builtin': False}
    order = [name for name in config.get_site_order() if name in entries]
    order += [name for name in entries if name not in order]
    hidden = set(config.get_hidden_sites())
    return [dict(entries[name], hidden=name in hidden) for name in order]


def register_user_sites():
    """Rebuild the Browse tab's site list from the catalog (order kept, sites
    switched off left out)."""
    visible = [entry for entry in site_catalog() if not entry['hidden']]
    SITES.clear()
    for entry in visible:
        SITES[entry['name']] = {'browser': entry['browser']}
    return list(SITES)


def _kvs_browser_for_url(url):
    """(site name, browser) for a pasted link on a KVS-based site, else (None, None)."""
    host = (urlsplit(url).hostname or '').lower()
    for name, entry in SITES.items():
        browser = entry['browser']
        root = getattr(browser, 'ROOT', '')
        root_host = (urlsplit(root).hostname or '').lower() if root else ''
        if root_host and (host == root_host or host == root_host.replace('www.', '', 1)
                          or 'www.' + host == root_host):
            if hasattr(browser, 'page_url') and hasattr(browser, 'fetch_page'):
                return name, browser
    return None, None
DEFAULT_SITE_KEY = ''      # no site until the user adds one
SITES_LOADING_HINT = ''


# Stopped-but-resumable states that keep showing their progress bar, % and
# size, so paused items at 50% and at 0% can be told apart.
_KEEP_PROGRESS_STATES = frozenset({'已暫停', '未完成', '封鎖/解析失敗', '等待重試'})

_STATE_PRIORITY = {
    '下載中': 0,
    '準備中': 4,
    '等待中': 5,
    '等待重試': 5,
    '已排程': 5,
    '已暫停': 6,
    '未完成': 6,
    '封鎖/解析失敗': 7,
    '網址錯誤': 8,
    '已下載': 9,
    '已存在': 9,
    '已取消': 10,
}


def _visible_window(items, cap, positions=None):
    positions = positions or {}

    def finished_first(item):
        # Finished downloads: most recently completed at the top.
        if item.state in DONE_STATES:
            return -(getattr(item, 'completed_at', 0) or item.updated_at or 0)
        return 0

    ordered = sorted(
        enumerate(items),
        key=lambda pair: (_STATE_PRIORITY.get(pair[1].state, 8),
                          positions.get(pair[1].url, 10 ** 9),
                          finished_first(pair[1]), pair[0]))
    return [item for _, item in ordered[:cap]]


def _select_persist(items, cap):
    terminal = {'已下載', '已取消', '網址錯誤', '已存在'}
    resumable = [i for i in items if i.state not in terminal]
    terminal_items = [i for i in items if i.state in terminal]
    budget = max(0, cap - len(resumable))
    kept_terminal = terminal_items[-budget:] if budget > 0 else []
    keep_ids = {id(i) for i in resumable} | {id(i) for i in kept_terminal}
    return [i for i in items if id(i) in keep_ids]


def _download_row_action(item):
    """Return the primary action exposed by a download-row button."""
    if item.state in ACTIVE_STATES or item.state in QUEUED_STATES:
        return 'pause'
    if item.state == '已暫停':
        return 'resume'
    if (item.state in {'未完成', '封鎖/解析失敗', '已取消'} or
            (item.state == '已下載' and bool(item.error))):
        return 'retry'
    if item.state == '已存在':
        return 'force'
    return ''


# ── Download Manager ────────────────────────────────────────────────
class DownloadItem:
    __slots__ = (
        'url', 'name', 'state', 'progress', 'speed', 'error', 'dest',
        'local', 'auto_requeues',
        'job_id', 'site', 'resolution', 'filename_template', 'thumbnail',
        'eta', 'error_code', 'retry_count', 'next_retry_at',
        'not_before', 'created_at', 'updated_at', 'size_text', 'completed_at',
    )

    def __init__(
            self, url: str, name: str = '', state: str = '', dest: str = '',
            local: bool = False,
            job_id: str = '', site: str = '', resolution: str = '',
            filename_template: str = '', thumbnail: str = '',
            not_before: float = 0, created_at: float = 0):
        self.url = url
        self.name = name or _fallback_name(url)
        self.state = state
        self.progress = 0
        self.speed = ''
        self.error = ''
        self.dest = dest or ''
        self.auto_requeues = 0
        candidate_job_id = str(job_id or '').strip()
        self.job_id = (
            candidate_job_id
            if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', candidate_job_id)
            else uuid.uuid4().hex)
        self.site = str(site or site_name(url))[:80]
        candidate_resolution = str(
            resolution or config.get_resolution_pref()).strip().lower()
        self.resolution = (
            candidate_resolution
            if candidate_resolution in config.VALID_RESOLUTION_PREFS
            else config.get_resolution_pref())
        self.filename_template = config.normalize_filename_template(
            filename_template or config.get_filename_template())
        self.thumbnail = str(thumbnail or '')[:2048]
        self.eta = ''
        self.size_text = ''   # "120.5 MB / 300.0 MB" while downloading
        self.completed_at = 0.0   # when it finished (for History, newest first)
        self.error_code = ''
        self.retry_count = 0
        self.next_retry_at = 0.0
        self.not_before = max(0.0, float(not_before or 0))
        self.created_at = float(created_at or time.time())
        self.updated_at = self.created_at
        # A local file row: never
        # downloaded, requeued or persisted.
        self.local = local


class _DownloadTask:
    """One URL moving through the download queue."""

    __slots__ = (
        'url', 'dest', 'epoch', 'job', 'cancelled',
        'download_started', 'slow_requeue_checked', 'prev_total',
        'transfer_complete', 'transferred_bytes', 'window_bytes',
        'window_started', 'last_done', 'monitor_stop', 'monitor_thread',
        'monitor_unit', 'speed_samples',
        'resolution', 'filename_template', 'retry_count', 'not_before',
        'pause_requested', 'force', 'est_total', 'est_done', 'cur_bps',
    )

    def __init__(
            self, url: str, dest: str, epoch: int,
            resolution: str = '',
            filename_template: str = '', retry_count: int = 0,
            not_before: float = 0):
        self.url = url
        self.dest = dest
        self.epoch = epoch
        self.job = None
        self.cancelled = threading.Event()
        self.download_started = None
        self.slow_requeue_checked = False
        self.prev_total = None
        self.transfer_complete = False
        self.transferred_bytes = 0.0
        # Recent (time, bytes) samples for the speed shown in the row: the
        # last few seconds, not an average since the download started.
        self.speed_samples = collections.deque()
        self.window_bytes = 0.0
        self.window_started = None
        self.last_done = 0
        self.monitor_stop = threading.Event()
        self.monitor_thread = None
        self.monitor_unit = None
        self.force = False            # download even if it was downloaded before
        self.est_total = 0.0          # (estimated) size of the video in bytes
        self.est_done = 0.0           # bytes downloaded so far
        self.cur_bps = 0.0            # current speed
        self.resolution = str(resolution or '')
        self.filename_template = str(filename_template or '')
        self.retry_count = max(0, int(retry_count or 0))
        self.not_before = max(0.0, float(not_before or 0))
        self.pause_requested = False


class DownloadManager:
    """Thread-safe manager for the download queue."""

    def __init__(self, on_update=None, max_concurrent: int = DEFAULT_CONCURRENT,
                 slow_requeue_kbps_getter=None,
                 auto_retry_count_getter=None, on_finished=None):
        self._on_update = on_update
        # Called with the saved video path once a download has finished
        # successfully, e.g. for auto-upload.
        self._on_finished = on_finished
        self._slow_requeue_kbps_getter = (
            slow_requeue_kbps_getter or config.get_slow_requeue_kbps)
        self._auto_retry_count_getter = (
            auto_retry_count_getter or config.get_auto_retry_count)
        self._pending: list[_DownloadTask] = []
        self._active: dict[str, _DownloadTask] = {}
        self._items: dict[str, DownloadItem] = {}
        # Active tasks requested for restart stay registered until their old
        # worker reaches _complete_download().  Only then is the replacement
        # inserted at the front of the queue, preventing two workers from
        # touching the same temporary files at once.
        self._restart_pending: dict[
            str, tuple[_DownloadTask, str, threading.Event]] = {}
        # RLock: enqueue() and cancel_all() call _set_state() while holding
        # the lock — a plain Lock would deadlock the caller (often the main
        # GUI thread, freezing the app).
        self._lock = threading.RLock()
        self._max_concurrent = max(
            1, min(int(max_concurrent), MAX_CONCURRENT))
        self._prep_sem = threading.Semaphore(1)
        self._cancel_epoch = 0
        self._schedule_timer = None
        self._schedule_deadline = 0.0

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @max_concurrent.setter
    def max_concurrent(self, value: int):
        self._max_concurrent = max(1, min(value, MAX_CONCURRENT))
        for _ in range(self._max_concurrent):
            self._try_next()

    def add_item(
            self, url: str, name: str = '', state: str = '', dest: str = '',
            *, resolution: str = '',
            filename_template: str = '', thumbnail: str = '',
            not_before: float = 0, job_id: str = '', site: str = '',
            created_at: float = 0):
        with self._lock:
            if url not in self._items:
                self._items[url] = DownloadItem(
                    url, name, state, dest, job_id=job_id, site=site, resolution=resolution,
                    filename_template=filename_template,
                    thumbnail=thumbnail, not_before=not_before,
                    created_at=created_at)
            else:
                item = self._items[url]
                # Refresh stale/persisted labels from the card the user just
                # selected.  Older queue entries often contained only a code,
                # even though the current site result has a useful title.
                if name:
                    item.name = name
                if dest:
                    item.dest = dest
                if resolution:
                    candidate = str(resolution).strip().lower()
                    if candidate in config.VALID_RESOLUTION_PREFS:
                        item.resolution = candidate
                if filename_template:
                    item.filename_template = config.normalize_filename_template(
                        filename_template)
                if thumbnail:
                    item.thumbnail = str(thumbnail)
                if not_before:
                    item.not_before = max(0.0, float(not_before))
                item.updated_at = time.time()
            return self._items[url]

    def contains(self, url: str) -> bool:
        with self._lock:
            return url in self._items

    def get_items(self) -> list[DownloadItem]:
        with self._lock:
            return list(self._items.values())

    # ── waiting-queue order ──────────────────────────────────────────────
    def queue_positions(self) -> dict:
        """{url: 1-based position} of downloads waiting to start."""
        with self._lock:
            return {task.url: index + 1
                    for index, task in enumerate(self._pending)}

    def move_in_queue(self, url: str, position: int) -> bool:
        """Move a waiting download to 1-based ``position`` (clamped)."""
        with self._lock:
            index = next((i for i, task in enumerate(self._pending)
                          if task.url == url), None)
            if index is None:
                return False
            task = self._pending.pop(index)
            position = max(1, min(int(position), len(self._pending) + 1))
            self._pending.insert(position - 1, task)
        return True

    def remove_item(self, url: str):
        with self._lock:
            self._items.pop(url, None)
            restart = self._restart_pending.pop(url, None)
            if restart is not None:
                restart[2].set()
            removed = [task for task in self._pending if task.url == url]
            self._pending = [task for task in self._pending if task.url != url]
            active = self._active.get(url)
            contexts = list(removed)
            if active is not None:
                contexts.append(active)
            for task in contexts:
                task.cancelled.set()
            self._arm_schedule_locked()
        self._cancel_contexts(contexts)

    def restart(self, url: str, dest: str, automatic: bool = False,
                expected_task: _DownloadTask | None = None) -> bool:
        """Cancel one active video and safely put a fresh task first in line.

        `automatic` marks a self-triggered slow-download requeue; manual
        requeues (the default) reset the item's automatic-retry counter.
        """
        with self._lock:
            item = self._items.get(url)
            task = self._active.get(url)
            if item is None or task is None:
                return False

            if automatic:
                from siphon.sites.base import speed_limiter
                # An asynchronous decision must never apply to a replacement
                # sharing the URL, nor to a transfer that has entered remux.
                if (task is not expected_task or
                        self._context_cancelled_locked(task) or
                        task.transfer_complete or task.monitor_stop.is_set() or
                        getattr(task.job, '_progress_unit', None) in (
                            'preparing', 'postprocess') or
                        item.state != '下載中' or
                        bool(getattr(task.job, '_storage_error', None)) or
                        speed_limiter.limit_bps > 0 or
                        not self._slow_requeue_kbps_getter()):
                    return False
                if url in self._restart_pending:
                    return False
                if item.auto_requeues >= SLOW_REQUEUE_MAX_ATTEMPTS:
                    return False
                item.auto_requeues += 1

            if not automatic:
                item.auto_requeues = 0

            restart_dest = dest or task.dest or item.dest
            existing = self._restart_pending.get(url)
            if existing is not None and existing[0] is task:
                self._restart_pending[url] = (
                    task, restart_dest, existing[2])
                return True

            item.dest = restart_dest
            cleanup_done = threading.Event()
            self._restart_pending[url] = (
                task, restart_dest, cleanup_done)
            task.cancelled.set()
            task.monitor_stop.set()
            self._set_state(url, '等待中', progress=0, error='')

        # Keep cleanup outside the manager lock.  The replacement is created
        # by _complete_download only after start_download() has returned.
        try:
            self._cancel_contexts([task], cleanup=True)
        finally:
            # The old worker can finish as soon as its cancel flag changes.
            # This gate also waits for temporary-file cleanup to finish before
            # a replacement is allowed to touch the same destination.
            cleanup_done.set()
        return True

    def enqueue(self, url: str, dest: str, not_before: float | None = None,
                force: bool = False):
        start_task = None
        history = getattr(self, 'history', None)
        seen = None if (force or history is None) else history.match_url(url)
        if seen is not None:
            with self._lock:
                if self._url_inflight_locked(url):
                    return False
                item = self._items.get(url)
                if item is None:
                    self._items[url] = item = DownloadItem(url, dest=dest)
                if not item.name or item.name == _fallback_name(url):
                    item.name = seen.get('name') or item.name
                self._set_state(url, '已存在', progress=100,
                                error=T('already_downloaded_detail',
                                        info=dl_history.when(seen)))
            self._report_already(url, seen)
            return False
        with self._lock:
            if self._url_inflight_locked(url):
                return False
            item = self._items.get(url)
            if item:
                item.dest = dest or item.dest
            else:
                self._items[url] = DownloadItem(url, dest=dest)
                item = self._items[url]
            item.auto_requeues = 0  # a fresh enqueue starts a new session
            item.retry_count = 0
            due = (
                item.not_before if not_before is None
                else max(0.0, float(not_before or 0)))
            if due <= time.time():
                due = 0.0
            item.not_before = due
            item.next_retry_at = 0.0
            task = _DownloadTask(
                url, dest, self._cancel_epoch,
                resolution=item.resolution,
                filename_template=item.filename_template,
                not_before=due)
            task.force = bool(force)
            if due:
                self._pending.append(task)
                self._set_state(url, '已排程', progress=0, error='')
                self._arm_schedule_locked()
            elif len(self._active) < self._max_concurrent:
                self._active[url] = task
                start_task = task
            else:
                self._pending.append(task)
                self._set_state(url, '等待中')
        if start_task is not None:
            self._start_download_thread(start_task)
        return True

    def pause(self, url: str) -> bool:
        """Pause one queued/active item while preserving resumable chunks."""
        contexts = []
        with self._lock:
            item = self._items.get(url)
            if item is None:
                return False
            pending = [task for task in self._pending if task.url == url]
            if pending:
                self._pending = [
                    task for task in self._pending if task.url != url]
                for task in pending:
                    task.pause_requested = True
                    task.cancelled.set()
                contexts.extend(pending)
            active = self._active.get(url)
            if active is not None:
                active.pause_requested = True
                active.cancelled.set()
                active.monitor_stop.set()
                contexts.append(active)
            if not contexts:
                if item.state == '已下載':
                    return False
                self._set_state(url, '已暫停', error='')
                return True
            self._set_state(url, '已暫停', error='')
            self._arm_schedule_locked()
        self._cancel_contexts(contexts, cleanup=False)
        self._try_next()
        return True

    def _report_already(self, url, entry):
        callback = getattr(self, 'on_already_downloaded', None)
        if callback is not None:
            try:
                callback(url, entry)
            except Exception:
                pass

    def resume(self, url: str, dest: str = '') -> bool:
        with self._lock:
            item = self._items.get(url)
            if item is None or item.state not in {'已暫停', '已取消'}:
                return False
            item.not_before = 0.0
            item_dest = item.dest
        return bool(self.enqueue(url, dest or item_dest, force=True))

    def pause_all(self) -> int:
        with self._lock:
            urls = [
                item.url for item in self._items.values()
                if item.state in ACTIVE_STATES or item.state in QUEUED_STATES
            ]
        return sum(1 for url in urls if self.pause(url))

    def _arm_schedule_locked(self):
        deadlines = [
            task.not_before for task in self._pending
            if task.not_before > time.time() and not task.cancelled.is_set()
        ]
        deadline = min(deadlines) if deadlines else 0.0
        if self._schedule_timer is not None:
            if deadline and abs(deadline - self._schedule_deadline) < 0.5:
                return
            self._schedule_timer.cancel()
            self._schedule_timer = None
            self._schedule_deadline = 0.0
        if not deadline:
            return

        def _wake():
            with self._lock:
                self._schedule_timer = None
                self._schedule_deadline = 0.0
            for _ in range(self._max_concurrent):
                self._try_next()

        self._schedule_deadline = deadline
        self._schedule_timer = threading.Timer(
            max(0.05, deadline - time.time()), _wake)
        self._schedule_timer.daemon = True
        self._schedule_timer.start()

    def cancel_all(self, cleanup: bool = True):
        with self._lock:
            self._cancel_epoch += 1
            if self._schedule_timer is not None:
                self._schedule_timer.cancel()
                self._schedule_timer = None
                self._schedule_deadline = 0.0
            for _task, _dest, cleanup_done in self._restart_pending.values():
                cleanup_done.set()
            self._restart_pending.clear()
            pending = list(self._pending)
            self._pending.clear()
            active = list(self._active.values())
            contexts = pending + active
            for task in contexts:
                task.cancelled.set()
                self._set_state(task.url, '已取消')
            # A paused download holds no task of its own, so cancelling only
            # the running and waiting ones left it paused for ever.
            for item in self._items.values():
                if item.state == '已暫停':
                    self._set_state(item.url, '已取消')
        self._cancel_contexts(contexts, cleanup=cleanup)

    def resume_all(self) -> int:
        """Put every paused or cancelled download back in the queue."""
        with self._lock:
            urls = [item.url for item in self._items.values()
                    if item.state in PAUSED_STATES]
        return sum(1 for url in urls if self.resume(url))

    def clear_all(self):
        self.cancel_all()
        with self._lock:
            self._items.clear()

    def _run(self, url: str, dest: str, epoch: int | None = None):
        """Compatibility entry point used by focused tests and older callers."""
        with self._lock:
            task = self._active.get(url)
            if task is None:
                task = _DownloadTask(
                    url, dest, self._cancel_epoch if epoch is None else epoch)
                self._active[url] = task
        self._run_download(task)

    def _run_download(self, task: _DownloadTask):
        url = task.url
        self._set_context_state(task, '準備中')
        try:
            self._prep_sem.acquire()
            try:
                if self._context_cancelled(task):
                    self._complete_download(task, '已取消')
                    return
                try:
                    job = M3U8Sites.CreateSite(
                        url, task.dest,
                        resolution=task.resolution,
                        filename_template=task.filename_template)
                except TypeError as exc:
                    # Preserve compatibility with third-party site factories
                    # that still implement the v2 positional signature.
                    if 'unexpected keyword argument' not in str(exc):
                        raise
                    job = M3U8Sites.CreateSite(url, task.dest)
                with self._lock:
                    if self._active.get(url) is task:
                        task.job = job
            finally:
                self._prep_sem.release()
            if self._context_cancelled(task):
                if job is not None:
                    try:
                        job._cancel_job = True
                    except Exception:
                        pass
                self._complete_download(task, '已取消')
                return
            if not job:
                self._complete_download(task, '網址錯誤')
                return
            if not job.is_url_vaildate():
                err = getattr(job, '_last_error', None)
                if isinstance(err, StorageWriteError):
                    raise err  # Preserve the storage-halt path, never retry I/O.
                if isinstance(err, MirrorsBlockedError):
                    error = ERR_BLOCKED
                else:
                    error = str(err) if err else T('parse_failed_short')
                if err is not None and self._schedule_transient_retry(task, error):
                    return
                self._complete_download(
                    task, '封鎖/解析失敗', error=error)
                return
            if self._context_cancelled(task):
                try:
                    job._cancel_job = True
                except Exception:
                    pass
                self._complete_download(task, '已取消')
                return
            name = job.target_name() or ''
            history = getattr(self, 'history', None)
            seen = (None if task.force or history is None
                    else history.match_name(name, url))
            if seen is not None:
                self._set_context_state(task, '準備中', name=name)
                self._complete_download(
                    task, '已存在', progress=100,
                    error=T('already_downloaded_detail',
                            info=dl_history.when(seen)))
                self._report_already(url, seen)
                return
            self._set_context_state(task, '下載中', name=name)
            job._progress_callback = (
                lambda d, t, s: self._on_context_progress(task, d, t, s))
            if self._context_cancelled(task):
                try:
                    job._cancel_job = True
                except Exception:
                    pass
                self._complete_download(task, '已取消')
                return
            self._start_slow_monitor(task)
            ok = job.start_download()
            task.monitor_stop.set()
            if ok is False and not job._cancel_job:
                raise Exception(T('parse_failed_short'))
            if job._cancel_job or self._context_cancelled(task):
                self._complete_download(task, '已取消')
                return
            self._complete_download(task, '已下載', progress=100)
        except Exception as exc:
            print(f'[下載失敗] {url}\n  {exc}', flush=True)
            if isinstance(exc, StorageWriteError):
                # No automatic queue advance or cleanup writes on a device
                # that has just failed. The user must explicitly retry.
                self.cancel_all(cleanup=False)
                self._complete_download(task, '已取消')
                with self._lock:
                    self._set_state(url, '未完成', error=str(exc))
                return
            if self._context_cancelled(task):
                self._complete_download(task, '已取消')
            elif isinstance(exc, MirrorsBlockedError):
                if not self._schedule_transient_retry(task, ERR_BLOCKED):
                    self._complete_download(
                        task, '封鎖/解析失敗', error=ERR_BLOCKED)
            else:
                if not self._schedule_transient_retry(task, str(exc)):
                    self._complete_download(task, '未完成', error=str(exc))
        finally:
            task.monitor_stop.set()

    def _try_next(self):
        task = None
        with self._lock:
            candidates = len(self._pending)
            while (candidates > 0 and self._pending and
                   len(self._active) < self._max_concurrent):
                candidates -= 1
                candidate = self._pending.pop(0)
                if (candidate.cancelled.is_set() or
                        candidate.epoch != self._cancel_epoch):
                    candidate.cancelled.set()
                    self._set_state(candidate.url, '已取消')
                    continue
                if candidate.not_before > time.time():
                    self._pending.append(candidate)
                    continue
                self._active[candidate.url] = candidate
                candidate.not_before = 0.0
                item = self._items.get(candidate.url)
                if item is not None:
                    item.not_before = 0.0
                    item.next_retry_at = 0.0
                task = candidate
                break
            self._arm_schedule_locked()
        if task is not None:
            self._start_download_thread(task)

    def _schedule_transient_retry(self, task: _DownloadTask, error: str) -> bool:
        problem = classify_download_problem(error, '未完成')
        with self._lock:
            item = self._items.get(task.url)
            retry_limit = max(0, int(self._auto_retry_count_getter()))
            if (not problem.retryable or item is None or
                    self._active.get(task.url) is not task or
                    task.retry_count >= retry_limit or
                    self._context_cancelled_locked(task)):
                return False
            self._active.pop(task.url, None)
            retry_count = task.retry_count + 1
            delay = min(60.0, float(2 ** retry_count))
            due = time.time() + delay
            item.retry_count = retry_count
            item.next_retry_at = due
            item.not_before = due
            replacement = _DownloadTask(
                task.url, task.dest, self._cancel_epoch,
                resolution=item.resolution,
                filename_template=item.filename_template,
                retry_count=retry_count, not_before=due)
            self._pending.append(replacement)
            self._set_state(
                task.url, '等待重試', progress=0, error=error)
            self._arm_schedule_locked()
        self._try_next()
        return True

    def _start_download_thread(self, task: _DownloadTask):
        threading.Thread(
            target=self._run_download, args=(task,), daemon=True).start()

    def _url_inflight_locked(self, url: str) -> bool:
        return (
            url in self._active
            or any(task.url == url for task in self._pending)
        )

    def _context_inflight_locked(self, task: _DownloadTask) -> bool:
        return (
            self._active.get(task.url) is task
            or any(candidate is task for candidate in self._pending)
        )

    def _context_cancelled_locked(self, task: _DownloadTask) -> bool:
        return (
            task.cancelled.is_set()
            or task.epoch != self._cancel_epoch
            or not self._context_inflight_locked(task)
        )

    def _context_cancelled(self, task: _DownloadTask) -> bool:
        with self._lock:
            return self._context_cancelled_locked(task)

    def _set_context_state(self, task: _DownloadTask, state: str,
                           name: str = '', progress: int = -1, error=None):
        with self._lock:
            if self._context_cancelled_locked(task):
                return
            self._set_state(
                task.url, state, name=name, progress=progress, error=error)

    def _complete_download(self, task: _DownloadTask, state: str,
                           progress: int = -1, error=None):
        task.monitor_stop.set()
        with self._lock:
            restart = self._restart_pending.get(task.url)
            cleanup_done = (
                restart[2]
                if restart is not None and restart[0] is task
                else None)
        if cleanup_done is not None:
            cleanup_done.wait()

        with self._lock:
            if self._active.get(task.url) is not task:
                return
            restart = self._restart_pending.get(task.url)
            restart_requested = (
                restart is not None
                and restart[0] is task
                and task.epoch == self._cancel_epoch
                and task.url in self._items)
            context_cancelled = self._context_cancelled_locked(task)
            self._active.pop(task.url, None)
            finished_ok = False
            if restart_requested:
                self._restart_pending.pop(task.url, None)
                item = self._items[task.url]
                replacement = _DownloadTask(
                    task.url, restart[1], self._cancel_epoch,
                    resolution=item.resolution,
                    filename_template=item.filename_template)
                self._pending.insert(0, replacement)
                self._set_state(
                    task.url, '等待中', progress=0, error='')
            else:
                self._restart_pending.pop(task.url, None)
                if task.pause_requested:
                    state, progress, error = '已暫停', -1, ''
                if context_cancelled and state != '已取消':
                    if not task.pause_requested:
                        state, progress, error = '已取消', -1, None
                self._set_state(
                    task.url, state, progress=progress, error=error)
                finished_ok = state in DONE_STATES and state != '已存在'
        if not restart_requested and finished_ok:
            self._notify_finished(task)
        self._try_next()

    def _notify_finished(self, task: _DownloadTask):
        hook = self._on_finished
        job = task.job
        if job is None:
            return
        try:
            path = job._get_video_savename()
        except Exception:
            return
        # Remember the exact file so "open location" can select it.
        if not hasattr(self, 'finished_paths'):
            self.finished_paths = {}
        self.finished_paths[task.url] = path
        history = getattr(self, 'history', None)
        if history is not None:
            try:
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                history.add(task.url, job.target_name() or os.path.basename(path), path,
                            size=size)
            except Exception as exc:
                print(f'[history] {exc}', flush=True)
        if hook is None:
            return
        try:
            hook(path)
        except Exception as exc:
            print(f'[upload] auto-upload skipped: {exc}', flush=True)

    @staticmethod
    def _cancel_contexts(contexts, cleanup: bool = True):
        seen = set()
        for task in contexts:
            if id(task) in seen:
                continue
            seen.add(id(task))
            task.cancelled.set()
            task.monitor_stop.set()
            job = task.job
            if not job or not hasattr(job, 'cancel_download'):
                continue
            try:
                job.cancel_download(cleanup=cleanup)
            except TypeError:
                try:
                    job.cancel_download()
                except Exception:
                    pass
            except Exception:
                pass
            if cleanup and hasattr(job, 'cleanup_temp'):
                try:
                    job.cleanup_temp()
                except Exception:
                    pass

    def _set_state(self, url: str, state: str, name: str = '', progress: int = -1, error=None):
        with self._lock:
            item = self._items.get(url)
            if item:
                item.state = state
                if name:
                    item.name = name
                if progress >= 0:
                    item.progress = progress
                if error is not None:
                    item.error = error
                    item.error_code = classify_download_problem(
                        error, state).code
                elif state not in ('未完成', '封鎖/解析失敗'):
                    item.error = ''
                    item.error_code = ''
                if state != '下載中':
                    item.speed = ''
                    item.eta = ''
                if state not in _KEEP_PROGRESS_STATES and state != '下載中':
                    item.size_text = ''
                if state in DONE_STATES:
                    item.retry_count = 0
                    item.next_retry_at = 0.0
                    if not item.completed_at:
                        item.completed_at = time.time()
                elif state not in ('已下載',):
                    item.completed_at = 0.0
                item.updated_at = time.time()

    def _on_progress(self, url: str, done: int, total: int, speed_bps: float):
        if total <= 0:
            return
        pct = int(done * 100 / total)
        spd = (f'{speed_bps / 1024:.0f} KB/s' if speed_bps < 1024 * 1024
               else f'{speed_bps / 1024 / 1024:.1f} MB/s')
        with self._lock:
            item = self._items.get(url)
            if item:
                item.progress = pct
                item.speed = spd

    def _on_context_progress(self, task: _DownloadTask, done: int,
                             total: int, speed_bps: float):
        with self._lock:
            if (self._active.get(task.url) is not task or
                    self._context_cancelled_locked(task)):
                return
            self._on_progress(task.url, done, total, speed_bps)
            now = time.monotonic()
            if task.download_started is None:
                task.download_started = now
                task.window_started = now
            source_changed = task.prev_total is not None and (
                    total != task.prev_total or done < task.last_done)
            if source_changed:
                # HLS -> direct MP4/source fallback starts a fresh byte window.
                task.download_started = now
                task.window_started = now
                task.window_bytes = 0.0
                task.transferred_bytes = 0.0
                task.slow_requeue_checked = False
            task.prev_total = total
            task.last_done = done
            task.transfer_complete = total > 0 and done >= total
            item = self._items.get(task.url)
            if (item is not None and done > 0 and total > done and
                    task.download_started is not None):
                elapsed = max(0.0, now - task.download_started)
                item.eta = format_eta(elapsed * (total - done) / done)
            elif item is not None and total > 0 and done >= total:
                item.eta = ''
            job = task.job
            if item is not None:
                item.size_text = _download_size_text(job, done, total)
            unit = getattr(job, '_progress_unit', None)
            if unit == 'bytes':
                task.est_done, task.est_total = float(done), float(total or 0)
            else:
                got = float(getattr(job, '_bytes_downloaded', 0) or 0)
                task.est_done = got
                task.est_total = (got * total / done) if (unit == 'segments'
                                                          and done > 0 and total > 0) else 0.0
            if getattr(job, '_progress_unit', None) == 'bytes':
                task.transferred_bytes = float(done)
            elif hasattr(job, '_bytes_downloaded'):
                task.transferred_bytes = float(job._bytes_downloaded)
            else:
                # Compatibility for custom download jobs with only an average
                # speed callback. Production HLS/direct jobs use exact bytes.
                task.transferred_bytes = max(
                    task.transferred_bytes,
                    speed_bps * max(0.0, now - task.download_started))
            if source_changed:
                task.window_bytes = task.transferred_bytes
                task.speed_samples.clear()
            if item is not None:
                self._update_live_speed_locked(task, item, now, done, total)
            should_restart = self._check_slow_requeue_locked(task, now)
        if should_restart:
            # Never restart/cancel synchronously here: this callback runs
            # inside the crawler's own worker pool (for HLS, its segment
            # ThreadPoolExecutor), and restart() waits on that same pool's
            # cleanup — a synchronous call would deadlock it.
            threading.Thread(
                target=self._restart_slow_download, args=(task,),
                daemon=True).start()

    _SPEED_WINDOW = 5.0   # seconds of history used for the displayed speed

    def _update_live_speed_locked(self, task, item, now, done, total):
        samples = task.speed_samples
        current = task.transferred_bytes
        samples.append((now, current))
        while len(samples) > 2 and now - samples[0][0] > self._SPEED_WINDOW:
            samples.popleft()
        span = now - samples[0][0]
        if span < 1.0:
            return                     # keep the job's own figure until warmed up
        bps = max(0.0, (current - samples[0][1]) / span)
        task.cur_bps = bps
        item.speed = (f'{bps / 1024:.0f} KB/s' if bps < 1024 * 1024
                      else f'{bps / 1024 / 1024:.1f} MB/s')
        if (getattr(task.job, '_progress_unit', None) == 'bytes'
                and total > done > 0):
            item.eta = format_eta((total - done) / bps) if bps > 0 else ''

    def _restart_slow_download(self, task: _DownloadTask) -> bool:
        accepted = self.restart(task.url, task.dest, automatic=True,
                                expected_task=task)
        if not accepted:
            with self._lock:
                # A user may switch the option off or apply a speed cap
                # between decision and cancellation. Keep monitoring this
                # transfer if that decision was superseded.
                if not self._context_cancelled_locked(task):
                    task.slow_requeue_checked = False
        return accepted

    def _start_slow_monitor(self, task: _DownloadTask):
        with self._lock:
            if self._context_cancelled_locked(task):
                return
            now = time.monotonic()
            task.download_started = task.window_started = now
            task.monitor_unit = getattr(task.job, '_progress_unit', None)
            task.monitor_thread = threading.Thread(
                target=self._monitor_slow_download, args=(task,),
                name='siphon-slow-download-monitor', daemon=True)
            task.monitor_thread.start()

    def _monitor_slow_download(self, task: _DownloadTask):
        # One bounded watcher per active transfer; no manager-wide thread that
        # could keep a discarded manager alive. Completion/cancel wakes it.
        while not task.monitor_stop.wait(1.0):
            with self._lock:
                if (self._active.get(task.url) is not task or
                        self._context_cancelled_locked(task)):
                    return
                should_restart = self._check_slow_requeue_locked(
                    task, time.monotonic())
            if should_restart:
                if self._restart_slow_download(task):
                    return

    def _check_slow_requeue_locked(self, task: _DownloadTask,
                                   now: float) -> bool:
        """Evaluate successive 60-second byte windows, including no progress.

        Called under the manager lock. Callers restart outside it. The
        decision is advisory; restart rechecks identity and completion.
        """
        item = self._items.get(task.url)
        if (self._active.get(task.url) is not task or
                self._context_cancelled_locked(task) or item is None or
                item.state != '下載中' or task.transfer_complete or
                task.monitor_stop.is_set() or task.slow_requeue_checked or
                bool(getattr(task.job, '_storage_error', None))):
            return False
        unit = getattr(task.job, '_progress_unit', None)
        if unit in ('preparing', 'postprocess'):
            task.monitor_unit = unit
            task.window_started = task.download_started = None
            return False
        if unit in ('segments', 'bytes') and unit != task.monitor_unit:
            task.monitor_unit = unit
            task.window_started = task.download_started = now
            task.window_bytes = task.transferred_bytes
            return False
        if task.window_started is None:
            task.window_started = task.download_started
        if task.window_started is None:
            return False
        elapsed = now - task.window_started
        if elapsed < SLOW_REQUEUE_GRACE_SECONDS:
            return False
        speed_bps = max(
            0.0, task.transferred_bytes - task.window_bytes) / elapsed
        task.window_started = now
        task.window_bytes = task.transferred_bytes
        threshold_kbps = self._slow_requeue_kbps_getter()
        if not threshold_kbps:
            return False
        from siphon.sites.base import speed_limiter
        if speed_limiter.limit_bps > 0:
            return False
        if speed_bps >= threshold_kbps * 1024:
            return False

        if item.auto_requeues < SLOW_REQUEUE_MAX_ATTEMPTS:
            task.slow_requeue_checked = True
            print(
                f'[慢速自動重排] {task.url} 速度 {speed_bps / 1024:.0f} KB/s '
                f'低於門檻 {threshold_kbps} KB/s，第 {item.auto_requeues + 1}/'
                f'{SLOW_REQUEUE_MAX_ATTEMPTS} 次自動重新排隊', flush=True)
            return True
        print(
            f'[慢速自動重排] {task.url} 已自動重試 {SLOW_REQUEUE_MAX_ATTEMPTS} '
            '次仍低速，停止自動重試並繼續下載', flush=True)
        item.error = T('slow_requeue_exhausted', n=SLOW_REQUEUE_MAX_ATTEMPTS)
        return False

    def save_csv(self, path: str):
        with self._lock:
            items = list(self._items.values())
        # Local file rows hold file paths, not URLs: never reload them
        # as downloads.
        items = [item for item in items if not item.local]
        # Python 3.7+ dict insertion order is used as the recency proxy for
        # capped terminal history; resumable items are never dropped.
        items = _select_persist(items, MAX_PERSIST_ROWS)
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        buffer = io.StringIO()
        if True:
            f = buffer
            w = csv.writer(f)
            w.writerow([
                '狀態', '名稱', '進度', '速度', '網址', '目標',
                '字幕來源證據', '工作 ID', '網站', '解析度',
                '檔名範本', '縮圖', '錯誤', '錯誤代碼',
                '重試次數', '排程時間', '建立時間', '更新時間', '大小', '完成時間',
            ])
            for item in items:
                w.writerow([item.state, item.name, f'{item.progress}%',
                            item.speed, item.url, item.dest,
                            '',
                            item.job_id, item.site, item.resolution,
                            item.filename_template, item.thumbnail,
                            item.error, item.error_code, item.retry_count,
                            item.not_before, item.created_at,
                            item.updated_at, item.size_text, item.completed_at])
        secretstore.write_text(path, buffer.getvalue())

    def load_csv(self, path: str):
        try:
            if not os.path.exists(path):
                return
            text = secretstore.read_text(path)
            if True:
                for idx, row in enumerate(csv.DictReader(io.StringIO(text))):
                    if idx >= HARD_LOAD_LIMIT:
                        break
                    url = row.get('網址', '')
                    if url:
                        state = row.get('狀態', '')
                        if state in (
                                '下載中', '準備中', '等待中',
                                '等待重試', '已排程'):
                            state = '未完成'
                        def _number(name, default=0.0):
                            try:
                                return float(row.get(name, default) or default)
                            except (TypeError, ValueError):
                                return float(default)
                        item = self.add_item(
                            url, row.get('名稱', ''), state,
                            row.get('目標', ''),
                            resolution=row.get('解析度', ''),
                            filename_template=row.get('檔名範本', ''),
                            thumbnail=row.get('縮圖', ''),
                            job_id=row.get('工作 ID', ''),
                            site=row.get('網站', ''),
                            created_at=_number('建立時間'))
                        progress = (row.get('進度', '') or '').rstrip('%')
                        try:
                            item.progress = int(float(progress))
                        except (TypeError, ValueError):
                            pass
                        item.speed = row.get('速度', '') or ''
                        item.size_text = row.get('大小', '') or ''
                        try:
                            item.completed_at = float(row.get('完成時間', 0) or 0)
                        except ValueError:
                            item.completed_at = 0.0
                        if not item.completed_at and state in DONE_STATES:
                            # Older queue files: use the last update time.
                            try:
                                item.completed_at = float(row.get('更新時間', 0) or 0)
                            except ValueError:
                                item.completed_at = 0.0
                        item.error = row.get('錯誤', '') or ''
                        item.error_code = (
                            row.get('錯誤代碼', '') or
                            classify_download_problem(
                                item.error, item.state).code)
                        try:
                            item.retry_count = max(
                                0, int(row.get('重試次數', 0) or 0))
                        except (TypeError, ValueError):
                            item.retry_count = 0
                        item.updated_at = _number(
                            '更新時間', item.created_at)
            # Keep load memory bounded after the safety read limit. Python 3.7+
            # dict insertion order is the recency proxy for terminal items.
            kept = _select_persist(self.get_items(), MAX_PERSIST_ROWS)
            keep_urls = {item.url for item in kept}
            with self._lock:
                for url in list(self._items.keys()):
                    if url not in keep_urls:
                        self._items.pop(url, None)
        except (OSError, UnicodeDecodeError, csv.Error, SecretError):
            try:
                os.replace(path, path + '.bak')
            except Exception:
                pass

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def queue_estimate(self):
        """Remaining work of running + queued downloads.

        Returns dict(bytes, estimated, videos, unknown, speed, limited):
        queued videos (size not known before they start) count with the
        average size of earlier downloads."""
        from siphon.sites.base import speed_limiter
        with self._lock:
            active = list(self._active.values())
            pending = len(self._pending)
        remaining = 0.0
        unknown = 0
        speed = 0.0
        for task in active:
            speed += task.cur_bps or 0.0
            if task.est_total > 0:
                remaining += max(0.0, task.est_total - task.est_done)
            else:
                unknown += 1
        history = getattr(self, 'history', None)
        average = history.average_size() if history is not None else 0
        estimated = False
        if average:
            remaining += average * (pending + unknown)
            estimated = bool(pending + unknown)
            unknown = 0
        else:
            unknown += pending
        limit = speed_limiter.limit_bps
        return {'bytes': remaining, 'estimated': estimated,
                'videos': len(active) + pending, 'unknown': unknown,
                'speed': float(limit) if limit else speed, 'limited': bool(limit)}

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)



# ── Browse helper ────────────────────────────────────────────────────
def _fmt_size(value: float) -> str:
    value = float(value or 0)
    if value >= 1024 ** 3:
        return f'{value / 1024 ** 3:.2f} GB'
    return f'{value / 1024 ** 2:.1f} MB'


def _fmt_duration(seconds):
    """'3h 25m', '12m', '45s' (rounded up to the minute above one minute)."""
    seconds = max(0, int(seconds + 0.5))
    if seconds < 60:
        return f'{seconds}s'
    minutes = -(-seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f'{days}d {hours}h'
    return f'{hours}h {minutes:02d}m' if hours else f'{minutes}m'


def _download_size_text(job, done: int, total: int) -> str:
    """'120.5 MB / 300.0 MB' for direct MP4s; for HLS (counted in segments)
    the downloaded bytes plus an estimate of the final size."""
    unit = getattr(job, '_progress_unit', None)
    if unit == 'bytes':
        if total > 0:
            return f'{_fmt_size(done)} / {_fmt_size(total)}'
        return _fmt_size(done) if done else ''
    got = getattr(job, '_bytes_downloaded', 0) or 0
    if not got:
        return ''
    if unit == 'segments' and done > 0 and total > done:
        return f'{_fmt_size(got)} / ~{_fmt_size(got * total / done)}'
    return _fmt_size(got)


def fetch_page_data(browser_cls, url: str) -> dict:
    """Fetch video list from a category/search URL. Returns dict with videos list."""
    try:
        videos = browser_cls.fetch_page(url)
        print(f'[Browse] {url} -> {len(videos)} videos', flush=True)
        return {'videos': videos}
    except MirrorsBlockedError:
        print(f'[Browse] {url} -> blocked (Cloudflare / all mirrors failed)', flush=True)
        raise
    except Exception as e:
        print(f'[瀏覽錯誤] {url}: {e}', flush=True)
        return {'videos': [], 'error': str(e)}


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
    """Build thumbnail headers and a domain-scoped site clearance jar."""
    request_headers = dict(headers)
    cookies = None
    try:
        parsed = urlsplit(str(url or ''))
        host = (parsed.hostname or '').lower().rstrip('.')
    except (TypeError, ValueError):
        return request_headers, cookies

    trusted_site = (
        str(site_key or '').lower() == 'site'
        and parsed.scheme.lower() == 'https'
        and host in {'example.com', 'example.com', 'img.example.com'}
    )
    if not trusted_site:
        return request_headers, cookies

    request_headers['Referer'] = 'https://example.com/'
    override = config.get_cf_override('example.com') or {}
    if override.get('ua'):
        request_headers['User-Agent'] = override['ua']
    if override.get('cookie'):
        cookies = requests.cookies.RequestsCookieJar()
        cookies.set(
            'cf_clearance', override['cookie'], domain='.example.com',
            path='/', secure=True)
    return request_headers, cookies


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


# ── Main App ─────────────────────────────────────────────────────────
class ModernApp(ctk.CTk):
    def __init__(self, url: str = '', dest: str = 'download', lang: str = 'en'):
        super().__init__()
        self._is_closing = False
        self._startup_complete = False
        self._close_requested = False
        self._ui_callbacks = queue.SimpleQueue()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

        get_shared_ssl_context()

        config.load_cf_overrides()
        self._lang_code_by_name = {name: code for code, name in LANGUAGES}
        self._lang_name_by_code = {code: name for code, name in LANGUAGES}
        self._theme_mode = config.get_theme()
        ctk.set_appearance_mode(self._theme_mode)
        ctk.set_default_color_theme('blue')

        stored = config.get_ui_lang()
        if stored and stored not in self._lang_name_by_code:
            stored = 'en'          # a language that is no longer offered
        set_lang(stored or 'en')
        self._needs_lang_prompt = (stored is None)

        self.title(APP_DISPLAY_NAMES['browse'])
        self.geometry('1280x820')
        self.minsize(980, 680)
        self.configure(fg_color=BG_DARK)

        self._dest = (
            config.get_download_directory()
            if dest == 'download' and config.get_download_directory()
            else dest)
        self._url_input = url
        self._rebuilding = False

        # Rows whose page was already read for a title (once each).
        self._titles_tried: dict[str, int] = {}   # url -> sweeps spent on it
        self._title_worker_busy = False

        # Browse state
        register_user_sites()
        self._site_key = (list(SITES) or [DEFAULT_SITE_KEY])[0]
        self._categories: list[dict] = []
        self._current_base_url = ''
        self._page = 1
        self._has_next = True
        self._videos: list[dict] = []
        self._selected_urls: set = set()
        # Keep the complete card metadata in insertion order.  A set alone
        # loses both the displayed title and the order in which pages were
        # selected, which made site queues look unrelated to the grid.
        self._selected_videos: dict[str, dict] = {}
        self._select_all_running = False
        self._sidebar_expanded: dict[str, bool] = {}
        self._site_filter_state = {
            'query': '', 'genre': '', 'sort': '', 'date': '',
            'duration': '', 'tags': (),
        }
        self._site_filter_popup = None
        self._grid_gen: int = 0  # bumps on each page refresh so stale thumbs are dropped
        self._grid_columns = browse_columns_for_width(1280)
        self._resize_after_id = None
        self._page_req: int = 0
        self._build_gen: int = 0
        self._active_tab_idx: int = 0
        self._last_loaded_page: int = 1
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._card_widgets: dict = {}  # url -> {card, sel_btn}
        self._dl_rows: dict = {}   # url -> {row, state_lbl, name_lbl, pb, pct, spd, remove}
        self._dl_filter = 'all'
        self._batch_was_busy = False
        self._batch_notified = True
        self._dl_empty_lbl = None
        self._dl_pool = []
        self._dl_first = 0
        self._dl_view_items = []
        self._dl_gen = 0
        self._thumb_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        self._speed_mbps = config.get_speed_limit_mbps()
        self._download_autosave_ticks = 0
        self._last_download_save_sig = None
        self._update_info = None
        self._update_checking = False
        self._update_installing = False
        self._update_prompt_shown = False
        self._update_status_text = ''
        self._update_status_color = TEXT_DIM
        self._update_badge = None
        self._update_status_lbl = None
        self._update_note_lbl = None
        self._update_check_btn = None
        self._update_now_btn = None

        # Download manager
        self._upmgr = UploadManager()
        try:
            self._upmgr.restore(os.path.join(
                os.path.dirname(config.queue_csv_path()), 'upload_queue.json'))
        except Exception as exc:
            print(f'[Upload] could not restore the upload list: {exc}', flush=True)
        self._dlmgr = DownloadManager(
            max_concurrent=config.get_download_concurrency(),
            on_finished=self._upmgr.add_downloaded_video)
        if not os.path.exists(CSV_PATH):
            old_csv = os.path.join(os.getcwd(), 'site.csv')
            if (os.path.exists(old_csv) and
                    os.path.abspath(old_csv) != os.path.abspath(CSV_PATH)):
                try:
                    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
                    shutil.copy2(old_csv, CSV_PATH)
                except Exception:
                    pass
        self._dlmgr.load_csv(CSV_PATH)

        from siphon.sites.base import set_resolution_pref
        set_resolution_pref(config.get_resolution_pref())
        from siphon.sites.base import speed_limiter
        speed_limiter.set_limit(self._speed_mbps)

        self._build_ui()
        self.bind('<Configure>', self._on_root_resize, add='+')
        # Windows sometimes leaves parts of the window black after it was in
        # the background (alt-tab); repaint everything when it comes back.
        self.bind('<FocusIn>', self._on_window_focus, add='+')
        self.bind('<Map>', self._on_window_focus, add='+')
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self._startup_complete = True
        if self._close_requested:
            self._on_close()
            return
        self.after(30, self._drain_ui_callbacks)
        # Start periodic refresh for downloads
        self._refresh_downloads()
        # Continue what was running / queued when the app was last closed.
        self._setup_download_history()
        self.after(800, self._restore_resume_list)
        # Start clipboard monitor (main-thread safe)
        self._clp_text = ''
        self._clipboard_poll()

        # Tk rejects worker-thread ``after`` calls before mainloop starts.  Defer
        # every worker that can complete quickly until the event loop is active.
        self.after_idle(self._start_initial_background_tasks)
        if self._needs_lang_prompt:
            self.after(250, self._first_run_language_prompt)
        self.after(1500 if self._needs_lang_prompt else 700,
                   self._browser_first_run_notice)

    def _browser_first_run_notice(self):
        """Say, once, that Siphon will drive a real browser on this computer.

        It happens out of sight, so it should not be a surprise discovered in
        Task Manager.
        """
        if self._is_closing or config.browser_notice_seen():
            return
        config.set_browser_notice_seen()
        try:
            messagebox.showinfo(T('browser_notice_title'), T('browser_notice_body'))
        except tk.TclError:
            pass

    def _start_initial_background_tasks(self):
        if self._is_closing:
            return
        self._load_categories()

    def _ask_language_first_run(self):
        popup = None
        try:
            idx = 0 if ctk.get_appearance_mode() == 'Light' else 1
            def C(tok):                      # resolve a (light,dark) token to a single hex string
                return tok[idx] if isinstance(tok, (tuple, list)) else tok
            bg, card, fg, border, accent, cardh = (
                C(BG_DARK), C(BG_CARD), C(TEXT_PRI), C(BORDER_HOVER), C(ACCENT), C(BG_CARD_HOVER))

            popup = tk.Toplevel(self)
            popup.title(T('lang_picker_title'))
            popup.configure(bg=bg)
            popup.resizable(False, False)
            popup.transient(self)

            picker_font = 'Microsoft JhengHei'   # renders all 4 native scripts
            tk.Label(popup, text=T('lang_picker_title'), bg=bg, fg=fg,
                     font=(picker_font, 15, 'bold')).pack(padx=32, pady=(24, 14))

            def _choose(code='en'):
                config.set_ui_lang(code)
                if code != get_lang():
                    self._apply_language(code)
                try:
                    popup.destroy()
                except tk.TclError:
                    pass

            for code, name in LANGUAGES:
                tk.Button(popup, text=name, width=22,
                          bg=card, fg=fg, activebackground=accent, activeforeground='#ffffff',
                          relief='flat', bd=1, highlightbackground=border, highlightthickness=1,
                          padx=12, pady=9, font=(picker_font, 12), cursor='hand2',
                          command=lambda c=code: _choose(c)).pack(padx=32, pady=5)

            popup.protocol('WM_DELETE_WINDOW', lambda: _choose(get_lang() or 'en'))
            popup.update_idletasks()
            w = max(popup.winfo_reqwidth(), 320)
            h = max(popup.winfo_reqheight(), 280)
            x = max((self.winfo_screenwidth() - w) // 2, 0)
            y = max((self.winfo_screenheight() - h) // 3, 0)
            popup.geometry(f'{w}x{h}+{x}+{y}')
            # Force the picker visible (plain tk.Toplevel shows reliably in frozen builds)
            popup.deiconify()
            popup.lift()
            try:
                popup.attributes('-topmost', True)
                popup.after(300, lambda: popup.winfo_exists() and popup.attributes('-topmost', False))
            except tk.TclError:
                pass
            popup.update_idletasks()
            popup.focus_force()
        except Exception:
            if popup is not None:
                try:
                    popup.destroy()
                except tk.TclError:
                    pass
            try:
                config.set_ui_lang('en')
            except Exception:
                pass

    def _first_run_language_prompt(self):
        if self._is_closing:
            return
        try:
            self.deiconify()
            self.update_idletasks()
        except tk.TclError:
            pass
        self._ask_language_first_run()

    def _ui(self, fn, gen: int | None = None):
        if self._is_closing:
            return
        if gen is not None and gen != self._build_gen:
            return

        # No Tk calls from worker threads, even before mainloop or while
        # CustomTkinter processes a close event during its startup update.
        self._ui_callbacks.put((gen, fn))

    def _drain_ui_callbacks(self):
        for _ in range(64):
            if self._is_closing:
                return
            try:
                gen, fn = self._ui_callbacks.get_nowait()
            except queue.Empty:
                break
            if gen is not None and gen != self._build_gen:
                continue
            try:
                fn()
            except tk.TclError:
                pass
        try:
            if not self._is_closing:
                self.after(30, self._drain_ui_callbacks)
        except tk.TclError:
            pass

    def _short_update_note(self, info):
        notes = (info or {}).get('notes') or ''
        for line in notes.splitlines():
            line = line.strip()
            if line:
                return line[:180]
        return ''

    def _show_update_prompt(self, info):
        if self._is_closing or self._update_prompt_shown:
            return
        self._update_prompt_shown = True
        prompt = None
        try:
            prompt = ctk.CTkToplevel(self)
            prompt.title(T('update_prompt_title'))
            prompt.configure(fg_color=BG_CARD)
            prompt.resizable(False, False)
            prompt.transient(self)

            pos_width, pos_height = 420, 220
            self.update_idletasks()
            x = self.winfo_rootx() + max((self.winfo_width() - pos_width) // 2, 0)
            y = self.winfo_rooty() + 80
            x = max(min(x, self.winfo_screenwidth() - pos_width), 0)
            y = max(min(y, self.winfo_screenheight() - pos_height), 0)

            body = ctk.CTkFrame(prompt, fg_color=BG_CARD, corner_radius=0)
            body.pack(fill='both', expand=True, padx=22, pady=20)

            ctk.CTkLabel(
                body, text=T('update_prompt_title'),
                font=(ui_font(), 16, 'bold'), text_color=TEXT_PRI
            ).pack(anchor='w')

            tag = (info or {}).get('tag') or (info or {}).get('version')
            ctk.CTkLabel(
                body, text=T('update_available', version=tag),
                font=(ui_font(), 12), text_color=TEXT_SEC,
                wraplength=360, justify='left'
            ).pack(anchor='w', pady=(12, 0))

            note = self._short_update_note(info)
            if note:
                ctk.CTkLabel(
                    body, text=note, font=(ui_font(), 10),
                    text_color=TEXT_DIM, wraplength=360, justify='left'
                ).pack(anchor='w', pady=(8, 0))

            row = ctk.CTkFrame(body, fg_color='transparent')
            row.pack(fill='x', pady=(18, 0))

            def _close():
                try:
                    prompt.destroy()
                except tk.TclError:
                    pass

            def _install():
                _close()
                self._start_update_install()

            later_btn = ctk.CTkButton(
                row, text=T('update_prompt_later'), width=118, height=34,
                corner_radius=8, fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, command=_close)

            update_btn = ctk.CTkButton(
                row, text=T('update_now_btn'), width=118, height=34,
                corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                text_color=('#FFFFFF', '#FFFFFF'), command=_install
            )
            update_btn.pack(side='right')
            later_btn.pack(side='right', padx=(0, 8))

            prompt.protocol('WM_DELETE_WINDOW', _close)
            prompt.bind('<Escape>', lambda _event: _close())
            prompt.update_idletasks()
            prompt.geometry(f'+{x}+{y}')
            prompt.deiconify()
            prompt.lift()
            prompt.focus_force()
            later_btn.focus_force()
        except Exception:
            if prompt is not None:
                try:
                    prompt.destroy()
                except tk.TclError:
                    pass

    def _set_update_status(self, text, color=None):
        self._update_status_text = text
        self._update_status_color = color or TEXT_DIM
        self._refresh_update_ui()

    def _refresh_update_ui(self):
        available = bool(self._update_info)
        status = self._update_status_text or T('update_idle')
        if self._update_status_lbl is not None:
            try:
                self._update_status_lbl.configure(
                    text=status, text_color=self._update_status_color)
            except tk.TclError:
                pass
        if self._update_note_lbl is not None:
            try:
                if available:
                    note = self._short_update_note(self._update_info)
                    tag = self._update_info.get('tag') or self._update_info.get('version')
                    text = T('update_available', version=tag)
                    if note:
                        text = f'{text}  {note}'
                    self._update_note_lbl.configure(text=text)
                else:
                    self._update_note_lbl.configure(text='')
            except tk.TclError:
                pass
        if self._update_check_btn is not None:
            try:
                self._update_check_btn.configure(
                    state='disabled' if self._update_checking else 'normal')
            except tk.TclError:
                pass
        if self._update_now_btn is not None:
            try:
                if available:
                    if not self._update_now_btn.winfo_manager():
                        self._update_now_btn.pack(side='left', padx=(8, 0))
                    self._update_now_btn.configure(
                        state='disabled' if self._update_installing else 'normal')
                else:
                    self._update_now_btn.configure(state='disabled')
                    self._update_now_btn.pack_forget()
            except tk.TclError:
                pass
        if self._update_badge is not None:
            try:
                if available:
                    if not self._update_badge.winfo_manager():
                        self._update_badge.pack(side='left', padx=(8, 0))
                else:
                    self._update_badge.pack_forget()
            except tk.TclError:
                pass

    def _check_updates_clicked(self):
        """Update checking waits until this app has a release of its own."""
        if updater.PERSONAL_FORK:
            self._set_update_status(T('update_not_published'), TEXT_SEC)
            return
        self._start_update_check(manual=True)

    def _start_update_check(self, manual=False):
        if self._is_closing or self._update_checking:
            return
        self._update_checking = True
        if manual:
            self._set_update_status(T('update_checking'), TEXT_SEC)
        else:
            self._refresh_update_ui()

        def _worker():
            info = None
            newer = False
            try:
                info = updater.check_latest()
                newer = bool(info and updater.is_newer(
                    info.get('version', ''), APP_VERSION))
            except Exception:
                info = None
                newer = False

            def _apply():
                self._update_checking = False
                if newer:
                    self._update_info = info
                    tag = info.get('tag') or info.get('version')
                    self._set_update_status(
                        T('update_available', version=tag), SUCCESS)
                    if not manual and not self._update_prompt_shown:
                        self._show_update_prompt(info)
                elif manual:
                    self._update_info = None
                    self._set_update_status(T('update_uptodate'), TEXT_SEC)
                elif info is not None:
                    self._update_info = None
                    self._refresh_update_ui()
                else:
                    if manual:
                        self._set_update_status(T('update_failed'), ERROR_C)
                    else:
                        self._refresh_update_ui()

            self._ui(_apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _start_update_install(self):
        info = self._update_info
        if self._is_closing or self._update_installing or not info:
            return
        if not updater.is_frozen():
            try:
                webbrowser.open(info.get('html_url') or updater.API_LATEST)
            except Exception:
                pass
            self._set_update_status(T('update_from_source'), WARNING)
            return

        name = updater.current_exe_name()
        url = updater.find_asset_url(info, 'browse')
        if not url:
            self._set_update_status(T('update_failed'), ERROR_C)
            return

        self._update_installing = True
        self._set_update_status(T('update_downloading', pct=0), TEXT_SEC)

        def _worker():
            exe_dir = os.path.dirname(sys.executable)
            new_path = os.path.join(exe_dir, name + '.new')

            def _progress(downloaded, total):
                pct = int(downloaded * 100 / total) if total else 0
                self._ui(lambda p=pct: self._set_update_status(
                    T('update_downloading', pct=p), TEXT_SEC))

            ok = updater.download_asset(url, new_path, progress_cb=_progress)
            if ok and updater.apply_update_and_restart(new_path):
                self._ui(lambda: self._set_update_status(
                    T('update_restarting'), SUCCESS))
                self._ui(self._on_close)
                return

            def _failed():
                self._update_installing = False
                self._set_update_status(T('update_failed'), ERROR_C)

            self._ui(_failed)

        threading.Thread(target=_worker, daemon=True).start()

    def _show_update_settings(self, event=None):
        self._select_tab('settings')

    # ── Build UI ─────────────────────────────────────────────────────
    def _theme_glyph(self):
        return {'system': '◐', 'light': '☀', 'dark': '☾'}.get(self._theme_mode, '◐')

    def _cycle_theme(self):
        modes = ('system', 'light', 'dark')
        try:
            idx = modes.index(self._theme_mode)
        except ValueError:
            idx = 0
        self._theme_mode = modes[(idx + 1) % len(modes)]
        ctk.set_appearance_mode(self._theme_mode)
        config.set_theme(self._theme_mode)
        self._theme_btn.configure(text=self._theme_glyph())

    def _on_root_resize(self, event):
        if event.widget is not self or self._is_closing:
            return
        try:
            logical_width = event.width / max(self._get_window_scaling(), 1.0)
        except Exception:
            logical_width = event.width
        columns = browse_columns_for_width(logical_width)
        if columns == self._grid_columns:
            return
        self._grid_columns = columns
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        try:
            self._resize_after_id = self.after(180, self._apply_responsive_grid)
        except tk.TclError:
            self._resize_after_id = None

    def _apply_responsive_grid(self):
        self._resize_after_id = None
        if (self._is_closing or not self._videos or
                getattr(self, '_grid_scroll', None) is None):
            return
        self._refresh_grid()

    def _current_tab_index(self):
        return self._active_tab_idx

    def _set_tab_index(self, idx: int):
        idx = max(0, min(int(idx), len(self._tab_keys) - 1))
        self._select_tab(self._tab_keys[idx])

    def _select_tab(self, key):
        if key not in getattr(self, '_tab_frames', {}):
            return
        for f in self._tab_frames.values():
            f.pack_forget()
        self._tab_frames[key].pack(fill='both', expand=True)
        for k, w in self._tab_buttons.items():
            active = (k == key)
            try:
                w['lbl'].configure(
                    text_color=(TEXT_PRI if active else TEXT_SEC),
                    font=(ui_font(), 13, 'bold') if active else (ui_font(), 13))
                w['underline'].configure(fg_color=(ACCENT if active else 'transparent'))
            except tk.TclError:
                pass
        self._active_tab_idx = self._tab_keys.index(key)

    def _speed_values(self):
        return speed_limit.menu_values(
            T('unlimited'), T('speed_custom'),
            int(self._speed_mbps * 1024 * 1024))

    def _speed_label(self):
        return speed_limit.format_speed(
            int(self._speed_mbps * 1024 * 1024), T('unlimited'))

    def _resolution_values(self):
        return [T('resolution_highest'), '1080p', '720p', '480p', '360p',
                T('resolution_lowest')]

    def _resolution_pref_from_label(self, label):
        label = str(label or '').strip()
        if label == T('resolution_lowest'):
            return 'lowest'
        if label in {'1080p', '720p', '480p', '360p'}:
            return label[:-1]
        return 'highest'

    def _resolution_label(self):
        from siphon.sites.base import get_resolution_pref
        pref = get_resolution_pref()
        if pref == 'lowest':
            return T('resolution_lowest')
        if pref in {'1080', '720', '480', '360'}:
            return f'{pref}p'
        return T('resolution_highest')

    def _filename_mode_values(self):
        return [T('filename_mode_full'), T('filename_mode_code')]

    def _filename_mode_from_label(self, label):
        if str(label or '') == T('filename_mode_code'):
            return 'code-only'
        return 'full-title'

    def _filename_mode_label(self, mode=None):
        if mode is None:
            mode = config.get_filename_mode()
        mode = config.normalize_filename_mode(mode)
        if mode == 'code-only':
            return T('filename_mode_code')
        return T('filename_mode_full')

    def _on_lang_change(self, display_name):
        code = self._lang_code_by_name.get(display_name)
        if not code or code == get_lang():
            return
        self._apply_language(code)

    def _var_get(self, name, default=''):
        var = getattr(self, name, None)
        if var is None:
            return default
        try:
            return var.get()
        except (AttributeError, tk.TclError):
            return default

    def _apply_language(self, code):
        self._rebuilding = True
        from siphon.sites.base import get_resolution_pref, set_resolution_pref

        try:
            snapshot = {
                'tab_idx': self._current_tab_index(),
                'dest': self._var_get('_dest_var', self._dest),
                'dl_url': self._var_get('_dl_url_var', self._url_input),
                'cf_host': self._var_get('_cf_host_var'),
                'cf_cookie': self._var_get('_cf_cookie_var'),
                'cf_ua': self._var_get('_cf_ua_var'),
                'page_jump': self._var_get('_page_jump_var'),
                'concurrency': self._dlmgr.max_concurrent,
                'max_workers_per_video': self._commit_workers_preference(),
                'slow_requeue_kbps': self._commit_slow_requeue_preference(),
                'speed_mbps': self._speed_mbps,
                'resolution_pref': get_resolution_pref(),
                'site_key': self._site_key,
            }

            set_lang(code)
            config.set_ui_lang(code)
            self._build_gen += 1
            self._page_req += 1
            self._grid_gen += 1

            for child in self.winfo_children():
                try:
                    child.destroy()
                except tk.TclError:
                    pass

            self._card_widgets = {}
            self._dl_rows = {}
            self._dl_pool = []
            self._dl_first = 0
            self._dl_view_items = []
            self._dl_gen += 1
            self._categories = []
            self._selected_urls.clear()
            self._selected_videos.clear()
            self._videos = []
            self._browse_blocked = False
            self._browse_empty_message = ''
            self._cf_status_lbl = None
            self._site_menu = None
            self._cat_menu = None
            self._grid_scroll = None
            self._dl_scroll = None
            self._sidebar = None
            self._status_lbl = None

            self._dest = snapshot['dest']
            self._url_input = snapshot['dl_url']
            self._site_key = snapshot['site_key']
            self._speed_mbps = snapshot['speed_mbps']
            set_resolution_pref(snapshot['resolution_pref'])

            self._build_ui()

            self._site_key = snapshot['site_key']
            self._site_var.set(snapshot['site_key'])
            self._dest_var.set(snapshot['dest'])
            self._dl_url_var.set(snapshot['dl_url'])
            self._page_jump_var.set(snapshot['page_jump'])
            self._conc_var.set(str(snapshot['concurrency']))
            self._workers_var.set(str(snapshot['max_workers_per_video']))
            self._slow_requeue_var.set(str(snapshot['slow_requeue_kbps']))
            self._speed_var.set(self._speed_label())
            self._res_var.set(self._resolution_label())
            if snapshot['cf_host']:
                self._cf_host_var.set(snapshot['cf_host'])
            self._cf_cookie_var.set(snapshot['cf_cookie'])
            self._cf_ua_var.set(snapshot['cf_ua'])
            self._refresh_cf_status()
            self._set_tab_index(snapshot['tab_idx'])
            self._update_selection_count()
            self._rebuild_sidebar()
            self._load_categories()
        finally:
            self._rebuilding = False
        self._refresh_downloads(schedule=False)

    def _build_ui(self):
        # ── Header bar ──────────────────────────────────────────────
        header = ctk.CTkFrame(self, height=64, fg_color=BG_HEADER, corner_radius=0)
        header.pack(fill='x')
        header.pack_propagate(False)

        # Brand — stacked to keep the product name readable at compact widths.
        brand = ctk.CTkFrame(header, fg_color='transparent')
        brand.pack(side='left', padx=24, fill='y')
        ctk.CTkLabel(brand, text=APP_DISPLAY_NAMES['browse'],
                     font=(ui_font(), 17, 'bold'),
                     text_color=TEXT_PRI).pack(anchor='w', pady=(9, 0))
        ctk.CTkLabel(brand, text='DOWNLOAD  /  UPLOAD',
                     font=('Consolas', 9, 'bold'),
                     text_color=ACCENT).pack(anchor='w', pady=(0, 9))

        # Right info
        right_info = ctk.CTkFrame(header, fg_color='transparent')
        right_info.pack(side='right', padx=24, fill='y')
        version_box = ctk.CTkFrame(
            right_info, fg_color=BG_BADGE, corner_radius=6,
            border_width=1, border_color=BORDER)
        version_box.pack(side='right', padx=(10, 0), pady=14)
        ctk.CTkLabel(version_box, text=f'v{APP_VERSION}',
                     font=('Consolas', 10, 'bold'),
                     text_color=TEXT_SEC).pack(side='left', padx=10, pady=4)
        self._update_badge = ctk.CTkLabel(
            version_box, text=T('update_new_badge'),
            font=(ui_font(), 10, 'bold'), text_color=ACCENT)
        try:
            self._update_badge.configure(cursor='hand2')
        except Exception:
            pass
        self._update_badge.bind('<Button-1>', self._show_update_settings)
        self._theme_btn = ctk.CTkButton(
            right_info, text=self._theme_glyph(), width=36, height=36,
            corner_radius=CONTROL_RADIUS, fg_color=BG_CARD, border_width=1,
            border_color=BORDER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 14),
            command=self._cycle_theme)
        self._theme_btn.pack(side='right', padx=(8, 0), pady=14)
        self._lang_var = ctk.StringVar(value=self._lang_name_by_code.get(get_lang(), 'English'))
        self._lang_menu = ctk.CTkOptionMenu(
            right_info, values=[name for _, name in LANGUAGES],
            variable=self._lang_var, command=self._on_lang_change,
            width=126, height=36, corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT, button_color=BORDER_HOVER,
            button_hover_color=ACCENT, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 11), dropdown_font=(ui_font(), 11))
        self._lang_menu.pack(side='right', pady=14)

        # Header separator
        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')

        # ── Custom underline tab bar (Studio Noir) ──────────────────
        self._tab_keys = ['browse', 'download', 'upload', 'settings']
        tab_labels = {'browse': T('tab_browse'), 'download': T('tab_download'),
                      'upload': T('tab_upload'), 'settings': T('tab_settings')}

        tabbar = ctk.CTkFrame(self, height=48, fg_color=BG_HEADER, corner_radius=0)
        tabbar.pack(fill='x')
        tabbar.pack_propagate(False)
        tabbar_inner = ctk.CTkFrame(tabbar, fg_color='transparent')
        tabbar_inner.pack(side='left', padx=18, fill='y')

        self._tab_buttons = {}   # key -> {'lbl': CTkLabel, 'underline': CTkFrame}
        for key in self._tab_keys:
            holder = ctk.CTkFrame(tabbar_inner, fg_color='transparent')
            holder.pack(side='left', padx=(0, 6), fill='y')
            # underline FIRST at the bottom so it is never clipped
            underline = ctk.CTkFrame(holder, height=3, fg_color='transparent', corner_radius=2)
            underline.pack(side='bottom', fill='x', padx=4, pady=(0, 0))
            lbl = ctk.CTkLabel(holder, text=tab_labels[key],
                               font=(ui_font(), 13), text_color=TEXT_SEC, cursor='hand2')
            lbl.pack(side='top', fill='both', expand=True, padx=14)
            lbl.bind('<Button-1>', lambda e, k=key: self._select_tab(k))
            self._tab_buttons[key] = {'lbl': lbl, 'underline': underline}

        # Header separator already drawn above; add one below the tab bar
        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')

        # Content container holding the 3 tab frames
        self._tab_container = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        self._tab_container.pack(fill='both', expand=True)
        self._tab_frames = {}
        for key in self._tab_keys:
            self._tab_frames[key] = ctk.CTkFrame(
                self._tab_container, fg_color=BG_DARK, corner_radius=0)

        self._build_browse_tab()
        self._build_download_tab()
        self._upload_tab = UploadTab(self, self._tab_frames['upload'], self._upmgr)
        self._build_settings_tab()

        self._select_tab(self._tab_keys[self._active_tab_idx])

        # ── Status bar ──────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')
        status_bar = ctk.CTkFrame(self, height=30, fg_color=BG_HEADER, corner_radius=0)
        status_bar.pack(fill='x')
        status_bar.pack_propagate(False)
        self._status_lbl = ctk.CTkLabel(status_bar, text=T('status_ready'),
                                         font=('Consolas', 10),
                                         text_color=TEXT_SEC)
        self._status_lbl.pack(side='left', padx=16)
        ctk.CTkButton(status_bar, text=T('open_log'), width=80, height=22,
                      corner_radius=CONTROL_RADIUS, fg_color='transparent',
                      border_width=1, border_color=BORDER, hover_color=BG_CARD_HOVER,
                      text_color=TEXT_SEC, font=(ui_font(), 10),
                      command=self._open_log_file).pack(side='right', padx=12)

    # ── continue downloads after a restart ───────────────────────────────
    def _save_resume_list(self):
        mgr = self._dlmgr
        with mgr._lock:
            running = [url for url in mgr._active
                       if mgr._items.get(url) is not None
                       and mgr._items[url].state in _RUNNING_STATES]
            queued = [task.url for task in mgr._pending]
            # Items waiting in the list without a task (e.g. scheduled ones).
            queued += [url for url, item in mgr._items.items()
                       if item.state in _QUEUED_STATES and not item.local]
        order = list(dict.fromkeys(running + queued))
        secretstore.write_text(RESUME_PATH, json.dumps(
            {'urls': order, 'running': len(set(running))}))
        print(f'[resume] {len(set(running))} running + '
              f'{len(order) - len(set(running))} queued download(s) will '
              'continue on next start', flush=True)

    def _setup_download_history(self):
        """Permanent history of finished downloads; seeded once from the list."""
        try:
            self._dlmgr.history = dl_history.DownloadHistory(os.path.join(
                os.path.dirname(CSV_PATH), 'download_history.json'))
            self._seed_history_sizes()
            seeded = self._dlmgr.history.add_many(
                (i.url, i.name, getattr(i, 'completed_at', 0) or i.updated_at)
                for i in self._dlmgr.get_items()
                if i.state == '已下載' and not i.local)
            if seeded:
                print(f'[history] {seeded} finished download(s) added to the history',
                      flush=True)
        except Exception as exc:
            print(f'[history] unavailable: {exc}', flush=True)
            self._dlmgr.history = None
        self._already_pending = []
        self._dlmgr.on_already_downloaded = (
            lambda url, entry: self._ui(lambda: self._note_already(url, entry)))

    def _seed_history_sizes(self):
        """Give history entries without a size the size shown in the list
        ('300.0 MB / 300.0 MB' → 300 MB), so download-time estimates work
        before any new download finishes."""
        history = self._dlmgr.history
        units = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}
        changed = False
        for item in self._dlmgr.get_items():
            if item.state != '已下載' or not item.size_text:
                continue
            found = re.findall(r'([\d.]+)\s*(TB|GB|MB|KB|B)\b', item.size_text)
            if not found:
                continue
            number, unit = found[-1]
            try:
                size = int(float(number) * units[unit])
            except (ValueError, KeyError):
                continue
            entry = history.match_url(item.url)
            if entry is None:
                history.add(item.url, item.name, '', getattr(item, 'completed_at', 0)
                            or item.updated_at, save=False, size=size)
                changed = True
            elif not entry.get('size'):
                entry['size'] = size
                changed = True
        if changed:
            with history._lock:
                history._save()

    def _note_already(self, url, entry):
        """Collect 'already downloaded' hits for a moment, then show one message."""
        first = not self._already_pending
        self._already_pending.append(entry or {'url': url})
        if first:
            self.after(600, self._show_already)

    def _show_already(self):
        entries, self._already_pending = self._already_pending, []
        if not entries or self._is_closing:
            return
        names = [f'• {e.get("name") or e.get("url")}' for e in entries[:12]]
        if len(entries) > 12:
            names.append(f'… +{len(entries) - 12}')
        text = T('already_downloaded_msg', n=len(entries)) + '\n\n' + '\n'.join(names)
        try:
            self._status_lbl.configure(text=T('already_downloaded_status', n=len(entries)))
        except (AttributeError, tk.TclError):
            pass
        self._refresh_downloads(schedule=False)
        messagebox.showinfo(T('already_downloaded_title'), text, parent=self)

    def _restore_resume_list(self):
        try:
            text = secretstore.read_text(RESUME_PATH)
            urls = list(json.loads(text).get('urls') or []) if text.strip() else []
        except (OSError, ValueError, Exception):
            return
        try:
            os.remove(RESUME_PATH)
        except OSError:
            pass
        started = 0
        for url in urls:
            item = self._dlmgr._items.get(url)
            if item is None or item.state in DONE_STATES or item.state == '已暫停':
                continue
            if self._dlmgr.enqueue(url, item.dest or self._dest):
                started += 1
        if started:
            print(f'[resume] continued {started} download(s) from last session', flush=True)
            try:
                self._status_lbl.configure(text=T('resume_restored', n=started))
            except (AttributeError, tk.TclError):
                pass
            self._refresh_downloads(schedule=False)

    def _on_window_focus(self, event=None):
        if event is not None and event.widget is not self:
            return
        now = time.monotonic()
        if now - getattr(self, '_last_repaint', 0.0) < 1.5:
            return
        self._last_repaint = now
        self.after(60, self._force_repaint)

    def _force_repaint(self):
        if self._is_closing:
            return
        try:
            self.update_idletasks()
            if sys.platform.startswith('win'):
                # Re-composite the whole window (cheap, no visible flicker).
                self.attributes('-alpha', 0.995)
                self.after(40, lambda: self.attributes('-alpha', 1.0))
        except tk.TclError:
            pass

    def _open_log_file(self):
        from siphon.core import applog
        path = applog.log_path()
        if path is None or not os.path.exists(path):
            messagebox.showinfo(T('open_log'), str(path or '-'))
            return
        try:
            if os.name == 'nt':
                os.startfile(str(path))
            else:
                import subprocess
                subprocess.Popen(['xdg-open', str(path)])
        except Exception as exc:
            messagebox.showerror(T('open_log'), f'{path}\n{exc}')

    # ── Browse Tab ───────────────────────────────────────────────────
    def _build_browse_tab(self):
        tab = self._tab_frames['browse']

        # ── Two-level workspace toolbar ─────────────────────────────
        top = ctk.CTkFrame(tab, fg_color=BG_SECTION, corner_radius=0, height=112)
        top.pack(fill='x')
        top.pack_propagate(False)
        self._browse_toolbar = top

        filters = ctk.CTkFrame(top, fg_color='transparent')
        filters.pack(fill='x', padx=20, pady=(10, 6))
        self._site_var = ctk.StringVar(value=self._site_key)
        self._site_menu = ctk.CTkOptionMenu(
            filters, values=list(SITES.keys()), variable=self._site_var,
            command=self._on_site_change, width=170, height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color=ACCENT, button_color=ACCENT_HOVER,
            button_hover_color=ACCENT_HOVER, text_color=WHITE,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 12, 'bold'), dropdown_font=(ui_font(), 12),
            dynamic_resizing=False)
        self._site_menu.pack(side='left')

        self._cat_var = ctk.StringVar(value=T('loading_browse'))
        self._cat_menu = ctk.CTkOptionMenu(
            filters, values=[T('loading_browse')], variable=self._cat_var,
            command=self._on_cat_change, width=190, height=36,
            fg_color=BG_INPUT, button_color=BORDER_HOVER,
            button_hover_color=ACCENT, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI, corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 11), dropdown_font=(ui_font(), 11))
        self._cat_menu.pack(side='left', padx=(10, 0))

        self._site_filter_box = ctk.CTkFrame(
            filters, fg_color='transparent')
        self._site_filter_btn = ctk.CTkButton(
            self._site_filter_box, text=T('site_filter_button'),
            command=self._open_site_filters,
            width=112, height=36, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, font=(ui_font(), 10, 'bold'))
        self._site_filter_btn.pack()

        self._search_var = ctk.StringVar()
        self._search_entry = ctk.CTkEntry(
            filters, textvariable=self._search_var,
            placeholder_text=T('search_placeholder'), height=36,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            corner_radius=CONTROL_RADIUS, text_color=TEXT_PRI,
            font=(ui_font(), 11))
        self._search_entry.pack(
            side='left', fill='x', expand=True, padx=(10, 8))
        self._search_entry.bind('<Return>', lambda e: self._on_search())
        # Sort for the current search only (shown while search results are on screen).
        self._search_sort_var = ctk.StringVar(value='')
        self._search_sort_menu = ctk.CTkOptionMenu(
            filters, values=[''], variable=self._search_sort_var,
            command=self._on_search_sort, width=140, height=36,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER, dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 11), dropdown_font=(ui_font(), 11))
        self._search_sort_visible = False
        self._search_btn = ctk.CTkButton(
            filters, text=T('search_btn'), command=self._on_search,
            width=76, height=36, corner_radius=CONTROL_RADIUS,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE, font=(ui_font(), 11, 'bold'))
        self._search_btn.pack(side='left')
        self._search_query = ''
        self._sync_site_filter_button_visibility()

        actions = ctk.CTkFrame(top, fg_color='transparent')
        actions.pack(fill='x', padx=20, pady=(0, 10))

        self._sel_lbl = ctk.CTkLabel(
            actions, text=f'0 {T("selected")}', text_color=TEXT_SEC,
            font=(ui_font(), 11, 'bold'))
        self._sel_lbl.pack(side='left')
        ctk.CTkButton(actions, text=T('download_selected'),
                      command=lambda: self._review_selected(True),
                      width=128, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=WHITE, font=(ui_font(), 11, 'bold')).pack(
                          side='right', padx=(8, 0))
        ctk.CTkButton(actions, text=T('add_to_queue'),
                      command=lambda: self._review_selected(False),
                      width=104, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER,
                      text_color=TEXT_PRI, font=(ui_font(), 11)).pack(side='right')
        ctk.CTkButton(actions, text=T('select_all_results_btn'),
                      command=self._select_all_results,
                      width=134, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1,
                      border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER,
                      text_color=TEXT_PRI, font=(ui_font(), 10)).pack(
                          side='right', padx=(0, 8))
        ctk.CTkButton(actions, text=T('select_page_btn'), command=self._select_all_on_page,
                      width=92, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER,
                      text_color=TEXT_PRI, font=(ui_font(), 11)).pack(
                          side='right', padx=(0, 8))
        ctk.CTkButton(actions, text=T('clear_selection_btn'),
                      command=self._clear_selection_in_place,
                      width=62, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=0,
                      hover_color=BG_CARD_HOVER,
                      text_color=TEXT_DIM, font=(ui_font(), 10)).pack(
                          side='right', padx=(0, 4))

        # ── Content area: sidebar + grid ────────────────────────────
        content = ctk.CTkFrame(tab, fg_color=BG_DARK, corner_radius=0)
        content.pack(fill='both', expand=True)

        # The tag sidebar was removed; videos use the full width.
        self._sidebar = None

        # Video grid area
        grid_area = ctk.CTkFrame(content, fg_color=BG_DARK, corner_radius=0)
        grid_area.pack(side='left', fill='both', expand=True)

        self._grid_scroll = ctk.CTkScrollableFrame(
            grid_area, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        self._grid_scroll.pack(fill='both', expand=True)

        # ── Navigation bar ──────────────────────────────────────────
        nav = ctk.CTkFrame(tab, fg_color=BG_HEADER, corner_radius=0, height=44)
        nav.pack(fill='x')
        nav.pack_propagate(False)
        self._browse_nav = nav

        nav_inner = ctk.CTkFrame(nav, fg_color='transparent')
        nav_inner.pack(pady=6)

        ctk.CTkButton(nav_inner, text=T('first_page'), width=64, height=30,
                      corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=lambda: self._goto_page(1)).pack(side='left', padx=3)
        ctk.CTkButton(nav_inner, text=T('prev_page'), width=74, height=30,
                      corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=lambda: self._goto_page(self._page - 1)
                      ).pack(side='left', padx=3)
        self._page_lbl = ctk.CTkLabel(nav_inner, text=T('page_n', n=1), text_color=TEXT_PRI,
                                       font=(ui_font(), 12, 'bold'),
                                       width=80)
        self._page_lbl.pack(side='left', padx=10)
        ctk.CTkButton(nav_inner, text=T('next_page'), width=74, height=30,
                      corner_radius=8,
                      fg_color=ACCENT,
                      hover_color=ACCENT_HOVER,
                      text_color=('#FFFFFF', '#FFFFFF'),
                      command=lambda: self._goto_page(self._page + 1)
                      ).pack(side='left', padx=3)

        # Page jump input
        ctk.CTkFrame(nav_inner, width=1, fg_color=BORDER).pack(
            side='left', fill='y', pady=4, padx=10)
        self._page_jump_var = ctk.StringVar(value='')
        page_entry = ctk.CTkEntry(nav_inner, textvariable=self._page_jump_var,
                                   width=50, height=30, corner_radius=8,
                                   fg_color=BG_INPUT, border_color=BORDER,
                                   border_width=1, text_color=TEXT_PRI,
                                   placeholder_text='#',
                                   justify='center')
        page_entry.pack(side='left', padx=3)
        page_entry.bind('<Return>', lambda e: self._jump_to_page())
        ctk.CTkButton(nav_inner, text=T('go_btn'), width=40, height=30,
                      corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._jump_to_page).pack(side='left', padx=3)

        self._rebuild_sidebar()

    # ── Download Tab ─────────────────────────────────────────────────
    def _build_download_tab(self):
        tab = self._tab_frames['download']

        # ── Input section ───────────────────────────────────────────
        input_frame = ctk.CTkFrame(tab, fg_color=BG_SECTION, corner_radius=0)
        input_frame.pack(fill='x')

        # Save location
        row1 = ctk.CTkFrame(input_frame, fg_color='transparent')
        row1.pack(fill='x', padx=20, pady=(14, 5))
        ctk.CTkLabel(row1, text=T('save_location'), text_color=TEXT_SEC, width=86,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        self._dest_var = ctk.StringVar(value=self._dest)
        ctk.CTkEntry(row1, textvariable=self._dest_var,
                     height=38, corner_radius=CONTROL_RADIUS,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI, font=(ui_font(), 11)).pack(side='left', fill='x',
                                               expand=True, padx=10)
        ctk.CTkButton(row1, text=T('browse_folder'), width=72, height=38, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._pick_dest).pack(side='left')
        ctk.CTkButton(row1, text=T('open_btn'), width=60, height=38, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._open_dest_folder).pack(side='left', padx=(6, 0))

        # Download URL
        row2 = ctk.CTkFrame(input_frame, fg_color='transparent')
        row2.pack(fill='x', padx=20, pady=(0, 14))
        ctk.CTkLabel(row2, text=T('url_label'), text_color=TEXT_SEC, width=86,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        self._dl_url_var = ctk.StringVar(value=self._url_input)
        ctk.CTkEntry(row2, textvariable=self._dl_url_var,
                     height=38, corner_radius=CONTROL_RADIUS,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI, font=('Consolas', 10)).pack(side='left', fill='x',
                                               expand=True, padx=10)

        # Separator
        ctk.CTkFrame(tab, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')

        # ── Action bar ──────────────────────────────────────────────
        bar = ctk.CTkFrame(tab, fg_color=BG_HEADER, corner_radius=0, height=106)
        bar.pack(fill='x')
        bar.pack_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        actions_left = ctk.CTkFrame(bar, fg_color='transparent')
        actions_left.grid(row=0, column=0, padx=(16, 8), pady=10, sticky='w')
        ctk.CTkButton(actions_left, text=T('download_btn'), width=112, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=WHITE,
                      font=(ui_font(), 11, 'bold'),
                      command=self._download_url).pack(side='left')
        ctk.CTkButton(actions_left, text=T('download_all_btn'), width=126, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._download_all).pack(side='left', padx=(8, 0))
        local_actions = ctk.CTkFrame(bar, fg_color='transparent')
        local_actions.grid(row=1, column=0, columnspan=3,
                           padx=16, pady=(0, 10), sticky='w')
        ctk.CTkButton(
            local_actions, text=T('import_urls'), width=112, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            command=self._import_urls_file).pack(side='left', padx=(8, 0))
        ctk.CTkButton(
            local_actions, text=T('paste_urls'), width=104, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            command=self._paste_urls).pack(side='left', padx=(8, 0))
        ctk.CTkButton(
            local_actions, text=T('export_queue'), width=92, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            command=self._export_queue).pack(side='left', padx=(8, 0))

        speed = ctk.CTkFrame(bar, fg_color='transparent')
        speed.grid(row=0, column=1, pady=10)
        ctk.CTkLabel(speed, text=T('speed_limit'), text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(side='left', padx=(0, 8))
        self._speed_var = ctk.StringVar(value=self._speed_label())
        self._speed_menus = []
        menu = ctk.CTkOptionMenu(
            speed, values=self._speed_values(), variable=self._speed_var,
            command=self._on_speed_change, width=118, height=38,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER, dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 10), dropdown_font=(ui_font(), 10))
        menu.pack(side='left')
        self._speed_menus.append(menu)

        destructive = ctk.CTkFrame(bar, fg_color='transparent')
        destructive.grid(row=0, column=2, padx=(8, 16), pady=10, sticky='e')
        ctk.CTkButton(destructive, text=T('pause_all'), width=88, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1,
                      border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=WARNING,
                      command=self._dlmgr.pause_all).pack(side='left')
        ctk.CTkButton(destructive, text=T('resume_all'), width=88, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1,
                      border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=SUCCESS,
                      command=self._dlmgr.resume_all).pack(side='left',
                                                           padx=(8, 0))
        ctk.CTkButton(destructive, text=T('cancel_all'), width=88, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=ERROR_C,
                      command=self._cancel_all).pack(side='left', padx=(8, 0))
        ctk.CTkButton(destructive, text=T('clear_list'), width=70, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                      command=self._clear_queue).pack(side='left', padx=(8, 0))

        # Separator under action bar
        ctk.CTkFrame(tab, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')

        filter_bar = ctk.CTkFrame(
            tab, fg_color=BG_SECTION, corner_radius=0, height=48)
        filter_bar.pack(fill='x')
        filter_bar.pack_propagate(False)
        self._dl_filter_labels = {
            'all': T('queue_filter_all'),
            'active': T('queue_filter_active'),
            'queued': T('queue_filter_queued'),
            'failed': T('queue_filter_failed'),
            'done': T('queue_filter_done'),
            'paused': T('queue_filter_paused'),
        }
        self._dl_filter_var = ctk.StringVar(
            value=self._dl_filter_labels[self._dl_filter])
        ctk.CTkSegmentedButton(
            filter_bar, values=list(self._dl_filter_labels.values()),
            variable=self._dl_filter_var,
            command=self._on_download_filter_change,
            height=32, corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            unselected_color=BG_INPUT,
            unselected_hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, font=(ui_font(), 10, 'bold')).pack(
                side='left', padx=16, pady=8)

        # A clear total — counts plus the time left for the whole queue —
        # right above the list, not only in the small bottom bar.
        self._dl_summary_lbl = ctk.CTkLabel(
            filter_bar, text='', text_color=TEXT_SEC, anchor='e',
            font=(ui_font(), 11, 'bold'))
        self._dl_summary_lbl.pack(side='right', padx=16)

        # ── Download list ───────────────────────────────────────────
        # A fixed pool of rows is moved over the list instead of one widget
        # per download: a thousand queued videos then cost the same as ten.
        list_area = ctk.CTkFrame(tab, fg_color=BG_DARK, corner_radius=0)
        list_area.pack(fill='both', expand=True)
        self._dl_scrollbar = ctk.CTkScrollbar(
            list_area, command=self._dl_on_scrollbar,
            button_color=BORDER, button_hover_color=BORDER_HOVER)
        self._dl_scrollbar.pack(side='right', fill='y', padx=(0, 4), pady=4)
        self._dl_scrollbar_shown = True
        self._dl_viewport = tk.Frame(
            list_area, bg=color_for_mode(
                BG_DARK, 'dark' if ctk.get_appearance_mode().lower() == 'dark'
                else 'light'),
            highlightthickness=0, bd=0)
        self._dl_viewport.pack(side='left', fill='both', expand=True)
        self._dl_scroll = self._dl_viewport      # kept: "is the list built?"
        self._dl_pool: list[dict] = []
        self._dl_first = 0
        self._dl_view_items: list[DownloadItem] = []
        self._dl_empty_lbl = ctk.CTkLabel(
            self._dl_viewport, text=T('dl_list_empty'), text_color=TEXT_DIM,
            font=(ui_font(), 13))
        self._dl_viewport.bind(
            '<Configure>', lambda _e: self._dl_on_resize())
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self._dl_viewport.bind(seq, self._dl_on_wheel, add='+')

    def _build_update_card(self, content):
        upd = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                           border_width=1, border_color=BORDER_CARD)
        upd.pack(fill='x', pady=(0, 16))

        upd_hdr = ctk.CTkFrame(upd, fg_color='transparent')
        upd_hdr.pack(fill='x', padx=20, pady=(16, 12))
        ctk.CTkLabel(upd_hdr, text=PRODUCT_NAME,
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')

        ctk.CTkFrame(upd, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        row_info = ctk.CTkFrame(upd, fg_color='transparent')
        row_info.pack(fill='x', padx=20, pady=(14, 16))

        row_actions = ctk.CTkFrame(row_info, fg_color='transparent')
        row_actions.pack(side='right', anchor='e')

        left_info = ctk.CTkFrame(row_info, fg_color='transparent')
        left_info.pack(side='left', fill='x', expand=True, padx=(0, 16))
        ctk.CTkLabel(left_info, text=T('update_current', version=APP_VERSION),
                     font=(ui_font(), 12, 'bold'),
                     text_color=TEXT_PRI).pack(anchor='w')
        ctk.CTkLabel(left_info, text=T('app_brand_2'),
                     font=(ui_font(), 10),
                     text_color=TEXT_DIM).pack(anchor='w', pady=(2, 0))

        self._update_status_lbl = ctk.CTkLabel(
            left_info, text='', text_color=TEXT_DIM, font=(ui_font(), 11))
        self._update_status_lbl.pack(anchor='w', pady=(3, 0))

        self._update_note_lbl = ctk.CTkLabel(
            left_info, text='', text_color=TEXT_DIM, font=(ui_font(), 10),
            wraplength=620, justify='left')
        self._update_note_lbl.pack(anchor='w', pady=(1, 0))

        self._update_check_btn = ctk.CTkButton(
            row_actions, text=T('update_check_btn'), width=138, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=self._check_updates_clicked)
        self._update_check_btn.pack(side='left')
        self._update_now_btn = ctk.CTkButton(
            row_actions, text=T('update_now_btn'), width=118, height=38,
            corner_radius=CONTROL_RADIUS, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE,
            command=self._start_update_install)
        self._refresh_update_ui()

    # ── Settings Tab ─────────────────────────────────────────────────
    def _build_settings_tab(self):
        tab = self._tab_frames['settings']

        outer = ctk.CTkScrollableFrame(
            tab, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        outer.pack(fill='both', expand=True)

        # Content container
        content = ctk.CTkFrame(outer, fg_color='transparent')
        content.pack(fill='x', padx=64, pady=28)

        # ── Page title ──────────────────────────────────────────────
        title_row = ctk.CTkFrame(content, fg_color='transparent')
        title_row.pack(fill='x', pady=(0, 22))
        ctk.CTkLabel(title_row, text=T('settings_title'),
                     font=(ui_font(), 22, 'bold'),
                     text_color=TEXT_PRI).pack(anchor='w')
        ctk.CTkLabel(title_row, text=T('settings_desc'),
                     font=(ui_font(), 11),
                     text_color=TEXT_DIM).pack(anchor='w', pady=(4, 0))

        # ── Download Settings Card ──────────────────────────────────
        grp = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                            border_width=1, border_color=BORDER_CARD)
        grp.pack(fill='x', pady=(0, 16))

        # Card header
        grp_hdr = ctk.CTkFrame(grp, fg_color='transparent')
        grp_hdr.pack(fill='x', padx=20, pady=(16, 12))
        ctk.CTkLabel(grp_hdr, text=T('download_settings'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')

        ctk.CTkFrame(grp, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        # Save location
        row_dest = ctk.CTkFrame(grp, fg_color='transparent')
        row_dest.pack(fill='x', padx=20, pady=(16, 2))
        ctk.CTkLabel(row_dest, text=T('save_location_setting'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkEntry(row_dest, textvariable=self._dest_var,
                     height=38, corner_radius=CONTROL_RADIUS,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI).pack(side='left', fill='x',
                                               expand=True, padx=10)
        ctk.CTkButton(row_dest, text=T('browse_folder'), width=60, height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._pick_dest).pack(side='left')
        ctk.CTkLabel(grp, text=T('save_location_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 0), pady=(0, 10))

        # Speed limit
        row_speed = ctk.CTkFrame(grp, fg_color='transparent')
        row_speed.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_speed, text=T('speed_limit_setting'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        menu = ctk.CTkOptionMenu(row_speed, values=self._speed_values(),
                          variable=self._speed_var,
                          command=self._on_speed_change, width=130, height=34,
                          corner_radius=8,
                          fg_color=BG_INPUT, button_color=BORDER_HOVER,
                          button_hover_color=ACCENT, text_color=TEXT_PRI,
                          dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                          dropdown_text_color=TEXT_PRI)
        menu.pack(side='left', padx=10)
        self._speed_menus = getattr(self, '_speed_menus', []) + [menu]
        ctk.CTkLabel(grp, text=T('speed_limit_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 0), pady=(0, 10))

        # Concurrent downloads
        row_conc = ctk.CTkFrame(grp, fg_color='transparent')
        row_conc.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_conc, text=T('concurrent_setting'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        self._conc_var = ctk.StringVar(value=str(self._dlmgr.max_concurrent))
        self._conc_entry = ctk.CTkEntry(
            row_conc, textvariable=self._conc_var, width=80, height=34,
            corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, border_width=1,
            text_color=TEXT_PRI, justify='center')
        self._conc_entry.pack(side='left', padx=10)
        self._conc_entry.bind('<Return>', self._on_conc_change)
        self._conc_entry.bind('<FocusOut>', self._on_conc_change)
        ctk.CTkLabel(row_conc, text=T('max_n', n=MAX_CONCURRENT),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(side='left')
        ctk.CTkLabel(grp, text=T('concurrent_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 0), pady=(0, 10))

        # Segment workers used inside each individual video download
        row_workers = ctk.CTkFrame(grp, fg_color='transparent')
        row_workers.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_workers, text=T('max_workers_per_video_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        # Global default (kept for language-rebuild snapshots) + per-site picker.
        self._workers_var = ctk.StringVar(
            value=str(config.get_max_workers_per_video()))
        all_label = T('workers_all_sites')
        self._workers_site_var = ctk.StringVar(value=all_label)
        ctk.CTkOptionMenu(
            row_workers, values=[all_label] + list(config.WORKER_SITES),
            variable=self._workers_site_var,
            command=lambda _v: self._show_site_workers(),
            width=150, height=34, corner_radius=CONTROL_RADIUS,
            fg_color=ACCENT, button_color=ACCENT_HOVER,
            button_hover_color=ACCENT_HOVER, text_color=WHITE,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI, font=(ui_font(), 11, 'bold'),
            dropdown_font=(ui_font(), 11), dynamic_resizing=False,
        ).pack(side='left', padx=(10, 10))
        self._workers_slider = ctk.CTkSlider(
            row_workers, from_=1, to=config.MAX_WORKERS_PER_VIDEO,
            number_of_steps=config.MAX_WORKERS_PER_VIDEO - 1, width=220,
            progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            command=self._on_workers_slide)
        self._workers_slider.pack(side='left')
        self._workers_value_lbl = ctk.CTkLabel(
            row_workers, text='', width=34, text_color=TEXT_PRI,
            font=('Consolas', 13, 'bold'))
        self._workers_value_lbl.pack(side='left', padx=(8, 4))
        self._workers_range_lbl = ctk.CTkLabel(
            row_workers, text='', text_color=TEXT_DIM, font=(ui_font(), 10))
        self._workers_range_lbl.pack(side='left', padx=(0, 8))
        self._workers_reset_btn = ctk.CTkButton(
            row_workers, text=T('workers_use_default'), width=110, height=30,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, font=(ui_font(), 10),
            command=self._reset_site_workers)
        self._show_site_workers()
        ctk.CTkLabel(
            grp,
            text=T(
                'max_workers_per_video_desc',
                n=config.MAX_WORKERS_PER_VIDEO),
            text_color=TEXT_DIM, font=(ui_font(), 10),
            wraplength=SETTINGS_INLINE_HELP_WRAP,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        # Automatic requeue of downloads stuck below a speed threshold
        row_slow_requeue = ctk.CTkFrame(grp, fg_color='transparent')
        row_slow_requeue.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_slow_requeue, text=T('slow_requeue_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._slow_requeue_var = ctk.StringVar(
            value=str(config.get_slow_requeue_kbps()))
        self._slow_requeue_entry = ctk.CTkEntry(
            row_slow_requeue, textvariable=self._slow_requeue_var, width=80,
            height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, border_width=1,
            text_color=TEXT_PRI, justify='center')
        self._slow_requeue_entry.pack(side='left', padx=10)
        self._slow_requeue_entry.bind('<Return>', self._on_slow_requeue_change)
        self._slow_requeue_entry.bind('<FocusOut>', self._on_slow_requeue_change)
        ctk.CTkLabel(
            row_slow_requeue, text=T('slow_requeue_unit'),
            text_color=TEXT_DIM, font=(ui_font(), 10)).pack(side='left')
        ctk.CTkLabel(
            grp,
            text=T(
                'slow_requeue_desc',
                grace=SLOW_REQUEUE_GRACE_SECONDS,
                n=SLOW_REQUEUE_MAX_ATTEMPTS),
            text_color=TEXT_DIM, font=(ui_font(), 10),
            wraplength=SETTINGS_INLINE_HELP_WRAP,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        # Resolution preference
        row_res = ctk.CTkFrame(grp, fg_color='transparent')
        row_res.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_res, text=T('resolution_setting'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        self._res_var = ctk.StringVar(value=self._resolution_label())
        ctk.CTkOptionMenu(row_res,
                          values=self._resolution_values(),
                          variable=self._res_var,
                          command=self._on_res_change, width=180, height=34,
                          corner_radius=8,
                          fg_color=BG_INPUT, button_color=BORDER_HOVER,
                          button_hover_color=ACCENT, text_color=TEXT_PRI,
                          dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                          dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)
        ctk.CTkLabel(grp, text=T('resolution_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 0), pady=(0, 10))

        # Shared output filename policy (Browser and Watcher).
        row_filename = ctk.CTkFrame(grp, fg_color='transparent')
        row_filename.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_filename, text=T('filename_mode_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._filename_mode_var = ctk.StringVar(
            value=self._filename_mode_label())
        ctk.CTkOptionMenu(
            row_filename, values=self._filename_mode_values(),
            variable=self._filename_mode_var,
            command=self._on_filename_mode_change, width=230, height=34,
            corner_radius=8, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)
        ctk.CTkLabel(
            grp, text=T('filename_mode_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_template = ctk.CTkFrame(grp, fg_color='transparent')
        row_template.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_template, text=T('filename_template_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._filename_template_var = ctk.StringVar(
            value=config.get_filename_template())
        template_entry = ctk.CTkEntry(
            row_template, textvariable=self._filename_template_var,
            height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, text_color=TEXT_PRI)
        template_entry.pack(side='left', fill='x', expand=True, padx=10)
        template_entry.bind('<Return>', self._on_filename_template_change)
        template_entry.bind('<FocusOut>', self._on_filename_template_change)
        ctk.CTkLabel(
            grp, text=T('filename_template_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_schedule = ctk.CTkFrame(grp, fg_color='transparent')
        row_schedule.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_schedule, text=T('download_schedule_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._download_schedule_var = ctk.StringVar(
            value=config.get_download_schedule())
        schedule_entry = ctk.CTkEntry(
            row_schedule, textvariable=self._download_schedule_var,
            width=100, height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, text_color=TEXT_PRI,
            placeholder_text='HH:MM', justify='center')
        schedule_entry.pack(side='left', padx=10)
        schedule_entry.bind('<Return>', self._on_download_schedule_change)
        schedule_entry.bind('<FocusOut>', self._on_download_schedule_change)
        ctk.CTkLabel(
            grp, text=T('download_schedule_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_safety = ctk.CTkFrame(grp, fg_color='transparent')
        row_safety.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_safety, text=T('minimum_free_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._minimum_free_var = ctk.StringVar(
            value=str(config.get_minimum_free_gb()))
        minimum_entry = ctk.CTkEntry(
            row_safety, textvariable=self._minimum_free_var,
            width=80, height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, text_color=TEXT_PRI, justify='center')
        minimum_entry.pack(side='left', padx=10)
        minimum_entry.bind('<Return>', self._on_minimum_free_change)
        minimum_entry.bind('<FocusOut>', self._on_minimum_free_change)
        ctk.CTkLabel(
            row_safety, text='GB', text_color=TEXT_DIM,
            font=(ui_font(), 10)).pack(side='left')
        ctk.CTkLabel(
            grp, text=T('minimum_free_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_retry = ctk.CTkFrame(grp, fg_color='transparent')
        row_retry.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_retry, text=T('auto_retry_setting'), text_color=TEXT_PRI,
            font=(ui_font(), 12, 'bold'), width=116,
            anchor='w').pack(side='left')
        self._auto_retry_var = ctk.StringVar(
            value=str(config.get_auto_retry_count()))
        retry_entry = ctk.CTkEntry(
            row_retry, textvariable=self._auto_retry_var,
            width=80, height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, text_color=TEXT_PRI, justify='center')
        retry_entry.pack(side='left', padx=10)
        retry_entry.bind('<Return>', self._on_auto_retry_change)
        retry_entry.bind('<FocusOut>', self._on_auto_retry_change)
        ctk.CTkLabel(
            grp, text=T('auto_retry_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        # Mouse-wheel scroll speed for every list in the app
        row_scroll = ctk.CTkFrame(grp, fg_color='transparent')
        row_scroll.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_scroll, text=T('scroll_speed_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        steps = ui_scroll.MAX_SPEED - ui_scroll.MIN_SPEED
        self._scroll_speed_lbl = ctk.CTkLabel(
            row_scroll, text=f'{ui_scroll.get_speed()}x', width=36,
            text_color=TEXT_PRI, font=('Consolas', 13, 'bold'))
        scroll_slider = ctk.CTkSlider(
            row_scroll, from_=ui_scroll.MIN_SPEED, to=ui_scroll.MAX_SPEED,
            number_of_steps=steps, width=220, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            command=self._on_scroll_speed)
        scroll_slider.set(ui_scroll.get_speed())
        scroll_slider.pack(side='left', padx=10)
        self._scroll_speed_lbl.pack(side='left')
        ctk.CTkLabel(
            grp, text=T('scroll_speed_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=SETTINGS_INLINE_HELP_WRAP,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_notify = ctk.CTkFrame(grp, fg_color='transparent')
        row_notify.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_notify, text=T('notify_complete_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._notify_complete_var = ctk.BooleanVar(
            value=config.get_notify_on_complete())
        ctk.CTkSwitch(
            row_notify, text='', variable=self._notify_complete_var,
            command=self._on_notify_complete_change,
            progress_color=ACCENT).pack(side='left', padx=10)
        ctk.CTkLabel(
            grp, text=T('notify_complete_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=SETTINGS_INLINE_HELP_WRAP,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        # App-scoped network proxy
        proxy = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                             border_width=1, border_color=BORDER_CARD)
        proxy.pack(fill='x', pady=(0, 16))

        proxy_hdr = ctk.CTkFrame(proxy, fg_color='transparent')
        proxy_hdr.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(proxy_hdr, text=T('proxy_card_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')
        ctk.CTkLabel(proxy, text=T('proxy_card_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=20, pady=(0, 12))

        ctk.CTkFrame(proxy, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        self._proxy_var = ctk.StringVar(value=config.get_proxy_url())
        row_proxy = ctk.CTkFrame(proxy, fg_color='transparent')
        row_proxy.pack(fill='x', padx=20, pady=(16, 2))
        ctk.CTkLabel(row_proxy, text=T('proxy_url_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkEntry(
            row_proxy, textvariable=self._proxy_var,
            placeholder_text=T('proxy_url_placeholder'),
            height=34, corner_radius=8,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            text_color=TEXT_PRI).pack(side='left', fill='x', expand=True, padx=10)

        proxy_actions = ctk.CTkFrame(proxy, fg_color='transparent')
        proxy_actions.pack(fill='x', padx=20, pady=(10, 2))
        ctk.CTkButton(
            proxy_actions, text=T('proxy_save'), width=70, height=34,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE, command=self._on_proxy_save).pack(
                side='left', padx=(126, 6))
        ctk.CTkButton(
            proxy_actions, text=T('proxy_windows'), width=86, height=34,
            corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=self._on_proxy_windows).pack(side='left', padx=(0, 6))
        ctk.CTkButton(
            proxy_actions, text=T('proxy_clear'), width=70, height=34,
            corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, command=self._on_proxy_clear).pack(side='left')
        self._proxy_status_lbl = ctk.CTkLabel(
            proxy_actions, text='', text_color=TEXT_SEC, font=(ui_font(), 10))
        self._proxy_status_lbl.pack(side='left', padx=12)
        self._refresh_proxy_status()

        ctk.CTkLabel(proxy, text=T('proxy_help'),
                     text_color=TEXT_DIM, font=(ui_font(), 9),
                     wraplength=720, justify='left').pack(
                         anchor='w', padx=20, pady=(6, 18))

        # Cloudflare bypass
        cf = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                          border_width=1, border_color=BORDER_CARD)
        cf.pack(fill='x', pady=(0, 16))

        cf_hdr = ctk.CTkFrame(cf, fg_color='transparent')
        cf_hdr.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(cf_hdr, text=T('cf_card_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')
        ctk.CTkLabel(cf, text=T('cf_card_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=20, pady=(0, 12))

        ctk.CTkFrame(cf, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        hosts = sorted({h for mirrors in config.MIRRORS.values() for h in mirrors})
        default_host = hosts[0] if hosts else ''
        self._cf_host_var = ctk.StringVar(value=default_host)
        self._cf_cookie_var = ctk.StringVar()
        self._cf_ua_var = ctk.StringVar()

        row_host = ctk.CTkFrame(cf, fg_color='transparent')
        row_host.pack(fill='x', padx=20, pady=(16, 2))
        ctk.CTkLabel(row_host, text=T('cf_host_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkOptionMenu(row_host, values=hosts,
                          variable=self._cf_host_var,
                          command=self._on_cf_host_change, width=220, height=34,
                          corner_radius=8,
                          fg_color=BG_INPUT, button_color=BORDER_HOVER,
                          button_hover_color=ACCENT, text_color=TEXT_PRI,
                          dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                          dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)

        row_cookie = ctk.CTkFrame(cf, fg_color='transparent')
        row_cookie.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_cookie, text=T('cf_cookie_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkEntry(row_cookie, textvariable=self._cf_cookie_var,
                     height=34, corner_radius=8,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI).pack(side='left', fill='x',
                                               expand=True, padx=10)

        row_ua = ctk.CTkFrame(cf, fg_color='transparent')
        row_ua.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_ua, text=T('cf_ua_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkEntry(row_ua, textvariable=self._cf_ua_var,
                     height=34, corner_radius=8,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI).pack(side='left', fill='x',
                                               expand=True, padx=10)

        row_actions = ctk.CTkFrame(cf, fg_color='transparent')
        row_actions.pack(fill='x', padx=20, pady=(10, 2))
        ctk.CTkButton(row_actions, text=T('cf_save'), width=70, height=34, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=WHITE,
                      command=self._on_cf_save).pack(side='left', padx=(126, 6))
        ctk.CTkButton(row_actions, text=T('cf_clear'), width=70, height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._on_cf_clear).pack(side='left')
        ctk.CTkButton(row_actions, text=T('cfpass_auto'), height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=ACCENT,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._on_cf_auto).pack(side='left', padx=(6, 0))

        self._cf_status_lbl = ctk.CTkLabel(cf, text='', text_color=TEXT_SEC,
                                           font=(ui_font(), 10))
        self._cf_status_lbl.pack(anchor='w', padx=(146, 20), pady=(6, 4))

        ctk.CTkLabel(cf, text=T('cf_help'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 9),
                     wraplength=720,
                     justify='left').pack(anchor='w', padx=20, pady=(4, 18))

        self._on_cf_host_change(default_host)
        self._refresh_cf_status()

        # ── My own sites ────────────────────────────────────────────
        mine = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                            border_width=1, border_color=BORDER_CARD)
        mine.pack(fill='x', pady=(0, 16))

        mine_hdr = ctk.CTkFrame(mine, fg_color='transparent')
        mine_hdr.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(mine_hdr, text=T('mysites_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')
        ctk.CTkLabel(mine, text=T('mysites_desc'), text_color=TEXT_DIM,
                     font=(ui_font(), 10), wraplength=720,
                     justify='left').pack(anchor='w', padx=20, pady=(0, 12))

        ctk.CTkFrame(mine, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        # Picker: "+ add new" on top, then every site, in the user's order.
        row_pick = ctk.CTkFrame(mine, fg_color='transparent')
        row_pick.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(row_pick, text=T('mysites_pick_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        self._site_pick_var = ctk.StringVar(value=T('mysites_new'))
        self._site_pick = ctk.CTkOptionMenu(
            row_pick, values=[T('mysites_new')], variable=self._site_pick_var,
            command=self._on_site_pick, width=230, height=36,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER, dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 12), dropdown_font=(ui_font(), 12),
            dynamic_resizing=False)
        self._site_pick.pack(side='left', padx=10)

        def _tool(text, command, color=TEXT_PRI, width=42):
            return ctk.CTkButton(
                row_pick, text=text, width=width, height=36, corner_radius=8,
                fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER, text_color=color,
                font=(ui_font(), 12, 'bold'), command=command)

        self._site_up_btn = _tool('▲', lambda: self._move_site(-1))
        self._site_up_btn.pack(side='left', padx=(0, 4))
        self._site_down_btn = _tool('▼', lambda: self._move_site(1))
        self._site_down_btn.pack(side='left', padx=(0, 10))
        self._site_toggle_btn = _tool(T('mysites_hide'), self._toggle_site, width=96)
        self._site_toggle_btn.pack(side='left', padx=(0, 4))
        self._site_del_btn = _tool(T('mysites_remove'), self._remove_picked_site,
                                   ERROR_C, width=84)
        self._site_del_btn.pack(side='left')

        # Shown for "+ add new": the address box.
        self._mysite_add_row = ctk.CTkFrame(mine, fg_color='transparent')
        self._mysite_add_row.pack(fill='x', padx=20, pady=(10, 2))
        ctk.CTkLabel(self._mysite_add_row, text=T('mysites_url_label'),
                     text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
                     width=116, anchor='w').pack(side='left')
        self._mysite_var = ctk.StringVar()
        mysite_entry = ctk.CTkEntry(
            self._mysite_add_row, textvariable=self._mysite_var, height=38,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT, border_color=BORDER,
            border_width=1, text_color=TEXT_PRI,
            placeholder_text=T('mysites_url_hint'))
        mysite_entry.pack(side='left', fill='x', expand=True, padx=10)
        self._mysite_entry = mysite_entry
        mysite_entry.bind('<Return>', lambda _e: self._test_custom_site())
        self._mysite_btn = ctk.CTkButton(
            self._mysite_add_row, text=T('mysites_test'), width=120, height=34,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color='#ffffff', command=self._test_custom_site)
        self._mysite_btn.pack(side='left')
        self._mysite_html_btn = ctk.CTkButton(
            self._mysite_add_row, text=T('mysites_teach'), width=150, height=34,
            corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, command=self._teach_from_html)
        self._mysite_html_btn.pack(side='left', padx=(6, 0))

        self._mysite_status = ctk.CTkLabel(mine, text='', text_color=TEXT_DIM,
                                           font=(ui_font(), 10), wraplength=720,
                                           justify='left')
        self._mysite_status.pack(anchor='w', padx=(136, 20), pady=(6, 18))
        self._refresh_site_picker()

        # Saved download queue
        queue = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                             border_width=1, border_color=BORDER_CARD)
        queue.pack(fill='x', pady=(0, 16))

        queue_hdr = ctk.CTkFrame(queue, fg_color='transparent')
        queue_hdr.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(queue_hdr, text=T('queue_card_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')
        ctk.CTkLabel(queue, text=T('queue_card_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=20, pady=(0, 12))

        ctk.CTkFrame(queue, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        row_queue_path = ctk.CTkFrame(queue, fg_color='transparent')
        row_queue_path.pack(fill='x', padx=20, pady=(16, 2))
        ctk.CTkLabel(row_queue_path, text=T('queue_path_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        queue_path_entry = ctk.CTkEntry(
            row_queue_path, height=34, corner_radius=8,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            text_color=TEXT_PRI)
        queue_path_entry.pack(side='left', fill='x', expand=True, padx=10)
        queue_path_entry.insert(0, config.queue_csv_path())
        queue_path_entry.configure(state='readonly')

        row_queue_actions = ctk.CTkFrame(queue, fg_color='transparent')
        row_queue_actions.pack(fill='x', padx=20, pady=(10, 18))
        ctk.CTkButton(row_queue_actions, text=T('open_queue_folder'),
                      width=110, height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._open_queue_folder).pack(side='left', padx=(126, 6))
        ctk.CTkButton(row_queue_actions, text=T('clear_saved_queue'),
                      width=140, height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=ERROR_C,
                      command=self._clear_saved_queue).pack(side='left')

        # ── About, at the very bottom ───────────────────────────────
        self._build_update_card(content)

    # ── Browse logic ─────────────────────────────────────────────────
    def _load_categories(self):
        if self._is_closing:
            return
        if not SITES:
            self._show_no_sites()
            return
        self._show_browse_chrome(True)
        _crumb("load_categories: site=%s" % self._site_key)
        self._page_req += 1
        my_req = self._page_req
        my_gen = self._build_gen
        site_key = self._site_key
        browser = SITES[site_key]['browser']
        self._show_grid_loading(T('browse_loading_site', site=site_key))
        site_lang = T('site_lang')
        site_lang = T('site_lang')

        def _fetch():
            failed = False
            try:
                if site_key == 'site':
                    cats = browser.fetch_categories(lang=site_lang)
                elif site_key == 'site':
                    cats = browser.fetch_categories(lang=site_lang)
                else:
                    cats = browser.fetch_categories()
            except Exception:
                failed = True
                cats = []
            if not cats and hasattr(browser, 'HOMEPAGE_SECTIONS'):
                cats = [{'name': site_i18n.loc(site_i18n.CATEGORY_I18N, url, name),
                         'url': url, 'count': 0, 'section': True}
                        for name, url in browser.HOMEPAGE_SECTIONS]

            def _apply():
                nonlocal cats
                if self._is_closing or my_req != self._page_req or my_gen != self._build_gen:
                    return
                cats = [dict(c, name=_section_label(c['name'])) for c in (cats or [])]
                self._categories = cats
                if cats and not failed:
                    self._current_base_url = cats[0]['url']
                    self._page = 1
                    self._last_loaded_page = 1
                    self._has_next = True
                    self._browse_blocked = False
                    self._browse_empty_message = ''
                    self._update_cat_menu([c['name'] for c in cats])
                    self._load_page()
                    return
                if cats:
                    self._current_base_url = cats[0]['url']
                    self._update_cat_menu([c['name'] for c in cats])
                else:
                    self._current_base_url = ''
                    self._cat_menu.configure(values=[])
                    self._cat_var.set('')
                self._videos = []
                self._has_next = False
                self._browse_blocked = False
                self._browse_empty_message = T('category_load_failed')
                self._status_lbl.configure(text=T('category_load_failed'))
                self._refresh_grid()

            self._ui(_apply, gen=my_gen)

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_cat_menu(self, names: list[str]):
        self._cat_menu.configure(values=names)
        if names:
            self._cat_var.set(names[0])

    def _show_grid_loading(self, text):
        """Replace the grid with a clear 'loading' message right away."""
        self._grid_gen += 1          # stops any card building still in progress
        try:
            for w in self._grid_scroll.winfo_children():
                w.destroy()
            self._card_widgets = {}
            ctk.CTkLabel(self._grid_scroll, text=text, text_color=TEXT_SEC,
                         font=(ui_font(), 15, 'bold')).pack(pady=(60, 6))
            ctk.CTkLabel(self._grid_scroll, text=SITES_LOADING_HINT,
                         text_color=TEXT_DIM, font=(ui_font(), 10)).pack()
            self._grid_scroll._parent_canvas.yview_moveto(0)
        except (AttributeError, tk.TclError):
            pass

    def _show_browse_chrome(self, visible):
        """Hide the site picker, search and page buttons while there is no site."""
        for name, side in (('_browse_toolbar', 'top'), ('_browse_nav', 'bottom')):
            widget = getattr(self, name, None)
            if widget is None or not widget.winfo_exists():
                continue
            try:
                if visible and not widget.winfo_manager():
                    widget.pack(fill='x', side=side)
                elif not visible and widget.winfo_manager():
                    widget.pack_forget()
            except tk.TclError:
                pass

    def _show_no_sites(self):
        """Browse with nothing in it yet: say what to do and go there."""
        self._show_browse_chrome(False)
        self._grid_gen += 1
        try:
            for widget in self._grid_scroll.winfo_children():
                widget.destroy()
            self._card_widgets = {}
            ctk.CTkLabel(self._grid_scroll, text=T('nosites_title'),
                         text_color=TEXT_PRI,
                         font=(ui_font(), 16, 'bold')).pack(pady=(80, 8))
            ctk.CTkLabel(self._grid_scroll, text=T('nosites_desc'),
                         text_color=TEXT_DIM, font=(ui_font(), 11),
                         wraplength=560, justify='center').pack()
            ctk.CTkButton(self._grid_scroll, text=T('nosites_button'),
                          width=200, height=42, corner_radius=CONTROL_RADIUS,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          text_color=WHITE, font=(ui_font(), 13, 'bold'),
                          command=self._go_add_site).pack(pady=(18, 0))
            self._grid_scroll._parent_canvas.yview_moveto(0)
        except (AttributeError, tk.TclError):
            pass

    def _go_add_site(self):
        """Open Settings with the cursor already in the "add a site" box."""
        self._select_tab('settings')
        picker = getattr(self, '_site_pick', None)
        if picker is not None and picker.winfo_exists():
            self._site_pick_var.set(T('mysites_new'))
            self._on_site_pick(T('mysites_new'))
        entry = getattr(self, '_mysite_entry', None)
        if entry is not None and entry.winfo_exists():
            try:
                entry.master.master._parent_canvas.yview_moveto(1.0)
            except (AttributeError, tk.TclError):
                pass
            entry.focus_set()

    def _load_page(self):
        if not self._current_base_url:
            return
        self._show_grid_loading(
            T('browse_loading_page', site=self._site_key, n=self._page))
        if getattr(self, '_status_lbl', None) is not None:
            self._status_lbl.configure(text=T('loading_browse'))
        self._page_req += 1
        my_req = self._page_req
        my_gen = self._build_gen
        site_key = self._site_key
        browser = SITES[site_key]['browser']
        base = self._current_base_url
        page_snapshot = self._page
        if site_key == 'site':
            if '?' in base:
                url = f'{base}&from={page_snapshot}'
            else:
                url = f'{base.rstrip("/")}/?from={page_snapshot}'
        else:
            url = browser.page_url(base, page_snapshot)

        def _fetch():
            blocked = False
            try:
                data = fetch_page_data(browser, url)
                videos = data.get('videos', [])
                error = data.get('error', '')
            except MirrorsBlockedError:
                blocked = True
                videos = []
                error = ''
            self._ui(
                lambda: self._apply_page(
                    my_req, videos, page_snapshot, blocked, my_gen, error),
                gen=my_gen)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_page(self, req: int, videos: list[dict], page_snapshot: int,
                    blocked: bool = False, gen: int | None = None,
                    error: str = ''):
        if self._is_closing or req != self._page_req:
            return
        if gen is not None and gen != self._build_gen:
            return
        if error:
            self._page = self._last_loaded_page
            self._has_next = False
            if is_unreachable_error(error):
                self._browse_empty_message = T('site_unreachable', site=self._site_key)
            else:
                self._browse_empty_message = f'{T("fetch_error")} · {error[:160]}'
            if page_snapshot <= 1:
                self._videos = []    # new site/category failed: show the error, not old cards
            self._page_lbl.configure(text=T('page_n', n=self._page))
            self._status_lbl.configure(text=self._browse_empty_message)
            self._refresh_grid()     # previous page back (paging) or the error message
            return
        if (videos and page_snapshot > 1 and self._videos
                and [v.get('url') for v in videos] == [v.get('url') for v in self._videos]):
            # The site answered with the same list again: there is no next page
            # (or this site's paging isn't understood) — don't show duplicates.
            print(f'[Browse] page {page_snapshot} repeated page {self._last_loaded_page}; '
                  'treating it as the last page', flush=True)
            videos = []
        if not videos and page_snapshot > 1 and not blocked:
            self._page = self._last_loaded_page
            self._has_next = False
            self._page_lbl.configure(text=T('page_n', n=self._page))
            self._status_lbl.configure(text=T('browse_last_page'))
            self._refresh_grid()     # no more pages: show the last one again
            return
        self._videos = videos
        self._browse_blocked = blocked
        self._browse_empty_message = (
            f'{T("fetch_error")} · {error[:160]}' if error
            else '')
        self._has_next = bool(videos)
        if videos:
            self._last_loaded_page = page_snapshot
            self._page = page_snapshot
        _crumb("apply_page: %d videos -> refresh_grid" % len(videos))
        self._refresh_grid()
        _crumb("apply_page: grid refreshed")
        self._page_lbl.configure(text=T('page_n', n=self._page))
        self._status_lbl.configure(
            text=(self._blocked_message() if blocked else
                  self._browse_empty_message or T('status_ready')))

    def _video_version_badge(self, url: str, title: str):
        url_l = (url or '').lower()
        title_l = (title or '').lower()
        path = url_l.split('?', 1)[0].rstrip('/')
        if ('uncensored-leak' in url_l or '無碼' in title_l or
                '无码' in title_l or 'uncensored' in title_l):
            return '無碼', '#C2410C'
        if ('chinese-subtitle' in url_l or path.endswith('-c') or
                '-c/' in url_l or '中文字幕' in title_l or '中字' in title_l):
            return '中字', '#0E7490'
        return None

    def _refresh_grid(self):
        try:
            for w in self._grid_scroll.winfo_children():
                w.destroy()
        except (AttributeError, tk.TclError):
            return
        self._card_widgets = {}
        self._grid_gen += 1
        gen = self._grid_gen
        build_gen = self._build_gen

        if not self._videos:
            if self._browse_blocked:
                msg = self._blocked_message()
            else:
                msg = self._browse_empty_message or T('no_results')
            ctk.CTkLabel(self._grid_scroll, text=msg,
                         text_color=TEXT_DIM,
                         font=(ui_font(), 14)).pack(pady=(40, 12))
            host = self._cf_pass_host()
            if (self._browse_blocked and host
                    and self._blocked_kind() == 'cloudflare'):
                ctk.CTkButton(
                    self._grid_scroll, text=T('cfpass_button', host=host),
                    height=40, corner_radius=CONTROL_RADIUS, fg_color=ACCENT,
                    hover_color=ACCENT_HOVER, text_color=WHITE,
                    font=(ui_font(), 12, 'bold'),
                    command=lambda h=host: self._start_cf_pass(h, reload=True)).pack()
                ctk.CTkLabel(self._grid_scroll, text=T('cfpass_hint'),
                             text_color=TEXT_DIM, font=(ui_font(), 10),
                             wraplength=560, justify='center').pack(pady=(8, 0))
            return

        # Responsive card density: 2 compact / 3 default / 4 wide.
        columns = max(2, self._grid_columns)
        try:
            logical_width = self.winfo_width() / max(self._get_window_scaling(), 1.0)
        except Exception:
            logical_width = self.winfo_width()
        estimated_card_width = max(
            240, int((max(logical_width, 980) - 240) / columns) - 24)
        title_wrap = max(180, min(330, estimated_card_width - 34))
        # Cards are built a few rows at a time so the window stays responsive
        # (building ~50 cards in one go froze the app for ~2 seconds).
        videos = list(self._videos)
        row_holder = [None]
        chunk = max(columns, 2)   # one row at a time

        def _build_card(i, v):
            if i % columns == 0:
                row_holder[0] = ctk.CTkFrame(self._grid_scroll, fg_color='transparent')
                row_holder[0].pack(fill='x', padx=14, pady=7)
            row_frame = row_holder[0]

            url = v.get('url', '')
            title = v.get('title', '')
            dur = v.get('duration', '')
            thumb_url = v.get('thumbnail', '')
            is_sel = url in self._selected_urls

            card = ctk.CTkFrame(row_frame, fg_color=ACCENT_DIM if is_sel else BG_CARD,
                                corner_radius=CARD_RADIUS,
                                border_width=2 if is_sel else 1,
                                border_color=ACCENT if is_sel else BORDER_CARD)
            card.pack(side='left', padx=7, pady=7, fill='x', expand=True)

            # Thumbnail placeholder (16:9)
            thumb_holder = ctk.CTkFrame(card, fg_color=BG_SIDEBAR,
                                         height=_THUMB_SIZE[1], corner_radius=6)
            thumb_holder.pack(fill='x', padx=10, pady=(10, 0))
            thumb_holder.pack_propagate(False)
            thumb_lbl = ctk.CTkLabel(thumb_holder, text=T('loading_browse'),
                                      text_color=TEXT_DIM,
                                      fg_color='transparent',
                                      font=(ui_font(), 11))
            thumb_lbl.pack(expand=True)

            # Duration badge
            if dur:
                dur_lbl = ctk.CTkLabel(thumb_holder, text=f' {dur} ',
                                        text_color='#FFFFFF',
                                        fg_color='#000000',
                                        corner_radius=4,
                                        font=('Consolas', 9, 'bold'))
                dur_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-6, y=-6)

            # Title
            title_text = title[:72] + '...' if len(title) > 72 else title
            title_row = ctk.CTkFrame(card, fg_color='transparent')
            title_row.pack(fill='x', padx=12, pady=(10, 5))
            version_badge = self._video_version_badge(url, title)
            wrap = title_wrap - 44 if version_badge else title_wrap
            if version_badge:
                badge_text, badge_color = version_badge
                ctk.CTkLabel(title_row, text=badge_text,
                             text_color='#FFFFFF', fg_color=badge_color,
                             corner_radius=4, width=34, height=18,
                             font=(ui_font(), 9, 'bold')).pack(
                    side='left', padx=(0, 6), anchor='n')
            ctk.CTkLabel(title_row, text=title_text, text_color=TEXT_PRI,
                         font=(ui_font(), 11),
                         wraplength=wrap, justify='left').pack(
                side='left', fill='x', expand=True, anchor='w')

            # Bottom row
            bottom = ctk.CTkFrame(card, fg_color='transparent')
            bottom.pack(fill='x', padx=12, pady=(0, 12))

            sel_text = ('✓ ' + T('selected')) if is_sel else T('select')
            sel_btn = ctk.CTkButton(
                bottom, text=sel_text, width=76, height=30,
                corner_radius=CONTROL_RADIUS,
                fg_color=ACCENT if is_sel else 'transparent',
                border_width=0 if is_sel else 1,
                border_color=BORDER_HOVER,
                hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                text_color=('#FFFFFF', '#FFFFFF') if is_sel else TEXT_PRI,
                font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10),
                command=lambda u=url: self._toggle_select(u)
            )
            sel_btn.pack(side='right')

            ctk.CTkButton(
                bottom, text=T('preview_browser'), width=112, height=30,
                corner_radius=CONTROL_RADIUS, fg_color='transparent',
                border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                font=(ui_font(), 10),
                command=lambda u=url: self._preview_video(u),
            ).pack(side='right', padx=(0, 6))

            self._card_widgets[url] = {'card': card, 'sel_btn': sel_btn}

            # Clickable card
            def _bind_click(widget, video_url=url):
                widget.bind('<Button-1>', lambda e, u=video_url: self._toggle_select(u))
                widget.configure(cursor='hand2')
            _bind_click(card)
            _bind_click(thumb_holder)
            _bind_click(thumb_lbl)

            # Background thumbnail load
            if thumb_url:
                self._load_thumb_async(
                    thumb_url, thumb_lbl, gen, build_gen, self._site_key)
            else:
                thumb_lbl.configure(text=T('no_thumbnail'))

        def _build_chunk(start):
            if (self._is_closing or gen != self._grid_gen
                    or build_gen != self._build_gen):
                return
            try:
                for index in range(start, min(start + chunk, len(videos))):
                    _build_card(index, videos[index])
                # Lay out these cards now; otherwise all the layout work piles
                # up and runs in one long freeze after the last card.
                self.update_idletasks()
            except tk.TclError:
                return
            if start + chunk < len(videos):
                self.after(15, lambda: _build_chunk(start + chunk))

        _build_chunk(0)

    def _load_thumb_async(self, thumb_url: str, label: ctk.CTkLabel,
                          gen: int, build_gen: int, site_key: str = ''):
        """Fetch thumbnail in a background thread; marshal result back to the
        main thread via .after() so Tk widget updates stay thread-safe.
        The gen counter prevents stale thumbs from polluting a newer page."""
        def _worker():
            if self._is_closing or gen != self._grid_gen or build_gen != self._build_gen:
                return
            img = _fetch_thumbnail(thumb_url, site_key)
            if img is None:
                def _apply_missing():
                    if (self._is_closing or gen != self._grid_gen or
                            build_gen != self._build_gen):
                        return
                    try:
                        if label.winfo_exists():
                            label.configure(text=T('no_thumbnail'), image=None)
                    except Exception:
                        pass
                self._ui(_apply_missing, gen=build_gen)
                return
            # Only apply if this label is still part of the current page.
            def _apply():
                if self._is_closing or gen != self._grid_gen or build_gen != self._build_gen:
                    return
                try:
                    if not label.winfo_exists():
                        return
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                            size=img.size)
                    label.configure(image=ctk_img, text='')
                    # Keep a reference on the widget so GC doesn't reclaim it
                    label._ctk_img_ref = ctk_img
                except Exception:
                    pass
            self._ui(_apply, gen=build_gen)
        try:
            self._thumb_executor.submit(_worker)
        except RuntimeError:
            pass

    def _preview_video(self, url: str):
        """Preview through the source site's browser player, without queuing."""
        try:
            opened = open_video_preview(url)
        except Exception:
            opened = False
        self._status_lbl.configure(
            text=T('preview_opened' if opened else 'preview_failed'))

    def _toggle_select(self, url: str):
        if url in self._selected_urls:
            self._selected_urls.discard(url)
            self._selected_videos.pop(url, None)
        else:
            self._selected_urls.add(url)
            video = next(
                (item for item in self._videos
                if item.get('url', '') == url),
                {'url': url},
            )
            self._selected_videos[url] = dict(video)
        # Update the specific card in-place (no full grid rebuild)
        w = self._card_widgets.get(url)
        if w:
            is_sel = url in self._selected_urls
            try:
                w['card'].configure(
                    fg_color=ACCENT_DIM if is_sel else BG_CARD,
                    border_width=2 if is_sel else 1,
                    border_color=ACCENT if is_sel else BORDER_CARD)
                w['sel_btn'].configure(
                    text=('✓ ' + T('selected')) if is_sel else T('select'),
                    fg_color=ACCENT if is_sel else 'transparent',
                    border_width=0 if is_sel else 1,
                    hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                    text_color=WHITE if is_sel else TEXT_PRI,
                    font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10))
            except Exception:
                pass
        self._update_selection_count()

    def _update_selection_count(self):
        n = len(self._selected_urls)
        page_selected = sum(
            1 for video in self._videos
            if video.get('url', '') in self._selected_urls)
        self._sel_lbl.configure(
            text=T('selection_count', selected=n, page=page_selected),
            text_color=ACCENT if n else TEXT_SEC)

    def _set_card_selected(self, url: str, is_sel: bool):
        w = self._card_widgets.get(url)
        if not w:
            return
        try:
            w['card'].configure(
                fg_color=ACCENT_DIM if is_sel else BG_CARD,
                border_width=2 if is_sel else 1,
                border_color=ACCENT if is_sel else BORDER_CARD)
            w['sel_btn'].configure(
                text=('✓ ' + T('selected')) if is_sel else T('select'),
                fg_color=ACCENT if is_sel else 'transparent',
                border_width=0 if is_sel else 1,
                hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                text_color=WHITE if is_sel else TEXT_PRI,
                font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10))
        except Exception:
            pass

    def _clear_selection_in_place(self):
        scan = getattr(self, '_selection_scan_cancel', None)
        if scan is not None:
            scan.set()
        selected = list(self._selected_urls)
        self._selected_urls.clear()
        self._selected_videos.clear()
        for url in selected:
            self._set_card_selected(url, False)
        self._update_selection_count()

    def _goto_page(self, p: int):
        if p < 1:
            return
        if p > self._page and not self._has_next:
            return
        self._page = p
        self._load_page()

    def _jump_to_page(self):
        """Jump to page number entered in the page-jump field."""
        try:
            p = int(self._page_jump_var.get().strip())
            if p >= 1 and not (p > self._page and not self._has_next):
                self._goto_page(p)
        except (ValueError, TypeError):
            pass
        self._page_jump_var.set('')

    def _select_all_on_page(self):
        """Select all videos currently displayed on the page."""
        for v in self._videos:
            url = v.get('url', '')
            if url:
                self._selected_urls.add(url)
                # Assignment refreshes metadata without changing the original
                # insertion order when a selected card is visited again.
                self._selected_videos[url] = dict(v)
                self._set_card_selected(url, True)
        self._update_selection_count()

    def _select_all_results(self):
        """Fetch and select every unique result from the current listing."""
        if self._select_all_running or not self._current_base_url:
            return
        self._select_all_running = True
        site_key = self._site_key
        browser = SITES[site_key]['browser']
        base_url = self._current_base_url
        build_gen = self._build_gen
        cancel = threading.Event()
        self._selection_scan_cancel = cancel

        def _cancelled():
            return (cancel.is_set() or self._is_closing or
                    build_gen != self._build_gen or
                    self._site_key != site_key or
                    self._current_base_url != base_url)

        def _page_url(page):
            if site_key == 'site':
                if page <= 1:
                    return base_url
                if '?' in base_url:
                    return f'{base_url}&from={page}'
                return f'{base_url.rstrip("/")}/?from={page}'
            return browser.page_url(base_url, page)

        def _worker():
            selected: dict[str, dict] = {}
            page = 1
            reason = ''
            fingerprints = set()
            while not _cancelled():
                try:
                    videos = browser.fetch_page(_page_url(page))
                except MirrorsBlockedError:
                    reason = T('mirrors_blocked')
                    break
                except Exception as exc:
                    print(f'[select all results] page {page}: {exc}', flush=True)
                    reason = T('fetch_error')
                    break
                if not videos:
                    break
                fingerprint = frozenset(
                    str(video.get('url', '')) for video in videos)
                if fingerprint in fingerprints:
                    reason = T('selection_scan_repeated')
                    break
                fingerprints.add(fingerprint)
                before = len(selected)
                for video in videos:
                    url = video.get('url', '')
                    if not url or not M3U8Sites.VaildateUrl(url):
                        continue
                    selected.setdefault(url, dict(video))
                count = len(selected)
                self._ui(lambda p=page, n=count: self._status_lbl.configure(
                    text=T('selecting_all_results', page=p, count=n)),
                    gen=build_gen)
                if len(selected) == before:
                    reason = T('selection_scan_repeated')
                    break
                page += 1
                # Small, cancelable listing pacing; no arbitrary page ceiling.
                for _ in range(3):
                    if _cancelled():
                        break
                    time.sleep(0.1)

            if _cancelled():
                reason = T('selection_scan_cancelled')
            self._select_all_running = False

            def _apply():
                if (self._is_closing or build_gen != self._build_gen or
                        getattr(self, '_selection_scan_cancel', None) is not cancel or
                        self._site_key != site_key or
                        self._current_base_url != base_url):
                    return
                # Clear selection cancels the scan, not merely its display.
                for url, video in (() if cancel.is_set() else selected.items()):
                    self._selected_urls.add(url)
                    self._selected_videos[url] = video
                    self._set_card_selected(url, True)
                self._update_selection_count()
                self._status_lbl.configure(
                    text=(T('selection_all_partial', count=len(selected), reason=reason)
                          if reason else
                          T('selection_all_done', count=len(selected))))

            self._ui(_apply, gen=build_gen)

        threading.Thread(target=_worker, daemon=True).start()

    def _site_filters_active(self) -> bool:
        return any(
            self._site_filter_state.get(key)
            for key in ('query', 'genre', 'sort', 'date', 'duration', 'tags')
        )

    def _refresh_site_filter_button(self):
        button = getattr(self, '_site_filter_btn', None)
        if button is None:
            return
        active = self._site_filters_active()
        try:
            button.configure(
                text=(T('site_filter_active') if active else
                      T('site_filter_button')),
                fg_color=ACCENT_DIM if active else 'transparent',
                border_color=ACCENT if active else BORDER_HOVER,
                text_color=ACCENT if active else TEXT_PRI,
            )
        except tk.TclError:
            pass

    def _sync_site_filter_button_visibility(self):
        box = getattr(self, '_site_filter_box', None)
        search_entry = getattr(self, '_search_entry', None)
        if box is None or search_entry is None:
            return
        try:
            if self._site_key == 'site':
                if not box.winfo_manager():
                    box.pack(
                        side='left', padx=(10, 0), before=search_entry)
                self._refresh_site_filter_button()
            else:
                box.pack_forget()
        except tk.TclError:
            pass

    def _reset_site_filter_state(self):
        self._site_filter_state = {
            'query': '', 'genre': '', 'sort': '', 'date': '',
            'duration': '', 'tags': (),
        }
        self._refresh_site_filter_button()

    def _apply_site_filter_state(self):
        state = self._site_filter_state
        self._current_base_url = siteBrowser.filter_url(
            query=state.get('query', ''),
            genre=state.get('genre', ''),
            sort=state.get('sort', ''),
            date=state.get('date', ''),
            duration=state.get('duration', ''),
            tags=state.get('tags', ()),
        )
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._search_var.set(state.get('query', ''))
        self._cat_var.set(T('site_filter_result'))
        self._refresh_site_filter_button()
        self._load_page()

    def _open_site_filters(self):
        if self._site_key != 'site':
            return
        existing = self._site_filter_popup
        try:
            if existing is not None and existing.winfo_exists():
                existing.focus_force()
                return
        except tk.TclError:
            pass

        catalog = siteBrowser.filter_catalog()
        popup = ctk.CTkToplevel(self)
        self._site_filter_popup = popup
        popup.title(T('site_filter_title'))
        popup.geometry('900x720')
        popup.minsize(760, 560)
        popup.transient(self)
        popup.configure(fg_color=BG_DARK)
        popup.grid_columnconfigure(0, weight=1)
        popup.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(popup, fg_color=BG_CARD, corner_radius=0)
        header.grid(row=0, column=0, sticky='ew')
        ctk.CTkLabel(
            header, text=T('site_filter_title'), text_color=TEXT_PRI,
            font=(ui_font(), 18, 'bold')).pack(
                anchor='w', padx=22, pady=(18, 4))
        ctk.CTkLabel(
            header, text=T('site_filter_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), justify='left', wraplength=840).pack(
                anchor='w', padx=22, pady=(0, 16))

        fields = ctk.CTkFrame(
            popup, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD)
        fields.grid(row=1, column=0, padx=18, pady=(16, 6), sticky='ew')
        for column in (1, 3):
            fields.grid_columnconfigure(column, weight=1)

        any_value = T('site_filter_any')
        state = self._site_filter_state
        query_var = tk.StringVar(
            value=state.get('query') or self._search_var.get().strip())
        genre_var = tk.StringVar(value=state.get('genre') or any_value)
        sort_var = tk.StringVar(value=state.get('sort') or any_value)
        date_var = tk.StringVar(value=state.get('date') or any_value)
        duration_var = tk.StringVar(value=state.get('duration') or any_value)

        def add_entry(row, column, label_key, variable):
            ctk.CTkLabel(
                fields, text=T(label_key), text_color=TEXT_SEC,
                font=(ui_font(), 10, 'bold'), anchor='w').grid(
                    row=row, column=column, padx=(14, 8), pady=7,
                    sticky='w')
            entry = ctk.CTkEntry(
                fields, textvariable=variable, height=34,
                corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
                border_color=BORDER, border_width=1,
                text_color=TEXT_PRI, font=(ui_font(), 10))
            entry.grid(
                row=row, column=column + 1, padx=(0, 14), pady=7,
                sticky='ew')
            return entry

        def add_menu(row, column, label_key, variable, values):
            ctk.CTkLabel(
                fields, text=T(label_key), text_color=TEXT_SEC,
                font=(ui_font(), 10, 'bold'), anchor='w').grid(
                    row=row, column=column, padx=(14, 8), pady=7,
                    sticky='w')
            menu = ctk.CTkOptionMenu(
                fields, variable=variable, values=[any_value, *values],
                height=34, corner_radius=CONTROL_RADIUS,
                fg_color=BG_INPUT, button_color=BORDER_HOVER,
                button_hover_color=ACCENT, text_color=TEXT_PRI,
                dropdown_fg_color=BG_CARD,
                dropdown_hover_color=BG_CARD_HOVER,
                dropdown_text_color=TEXT_PRI,
                font=(ui_font(), 9), dropdown_font=(ui_font(), 9))
            menu.grid(
                row=row, column=column + 1, padx=(0, 14), pady=7,
                sticky='ew')
            return menu

        query_entry = add_entry(
            0, 0, 'site_filter_query', query_var)
        add_menu(0, 2, 'site_filter_genre', genre_var,
                 list(catalog['genres']))
        add_menu(1, 0, 'site_filter_sort', sort_var,
                 list(catalog['sorts']))
        add_menu(1, 2, 'site_filter_date', date_var,
                 list(catalog['dates']))
        add_menu(2, 0, 'site_filter_duration', duration_var,
                 list(catalog['durations']))

        tags_card = ctk.CTkFrame(
            popup, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD)
        tags_card.grid(row=2, column=0, padx=18, pady=6, sticky='nsew')
        tags_card.grid_columnconfigure(0, weight=1)
        tags_card.grid_rowconfigure(1, weight=1)

        tags_header = ctk.CTkFrame(tags_card, fg_color='transparent')
        tags_header.grid(row=0, column=0, padx=12, pady=(10, 6), sticky='ew')
        ctk.CTkLabel(
            tags_header, text=T('site_filter_tags'), text_color=TEXT_PRI,
            font=(ui_font(), 12, 'bold')).pack(side='left')
        selected_count = ctk.CTkLabel(
            tags_header, text='', text_color=ACCENT,
            font=(ui_font(), 9, 'bold'))
        selected_count.pack(side='left', padx=(10, 0))
        tag_search_var = tk.StringVar()
        ctk.CTkEntry(
            tags_header, textvariable=tag_search_var,
            placeholder_text=T('site_filter_tag_search'), width=260,
            height=32, corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            border_color=BORDER, border_width=1, text_color=TEXT_PRI,
            font=(ui_font(), 10)).pack(side='right')

        tag_scroll = ctk.CTkScrollableFrame(
            tags_card, fg_color='transparent', corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        tag_scroll.grid(row=1, column=0, padx=8, pady=(0, 8), sticky='nsew')

        selected_tags = set(state.get('tags') or ())
        tag_vars = {
            tag: tk.BooleanVar(value=tag in selected_tags)
            for tag in catalog['tags']
        }
        group_key = {
            'features': 'st_site_tags_features',
            'relationships': 'st_site_tags_relationships',
            'roles': 'st_site_tags_roles',
            'characters': 'st_site_tags_characters',
            'appearance': 'st_site_tags_appearance',
            'clothing': 'st_site_tags_clothing',
            'locations': 'st_site_tags_locations',
            'themes': 'st_site_tags_themes',
            'acts': 'st_site_tags_acts',
        }
        grouped_names = {
            tag for _group, tags in site_FILTER_TAG_GROUPS for tag in tags
        }
        tag_groups = list(site_FILTER_TAG_GROUPS)
        extra_tags = tuple(
            tag for tag in catalog['tags'] if tag not in grouped_names)
        if extra_tags:
            tag_groups.append(('other', extra_tags))
        render_after = [None]

        def update_selected_count():
            count = sum(var.get() for var in tag_vars.values())
            selected_count.configure(
                text=T('site_filter_selected_tags', count=count))

        def render_tags(*_args):
            render_after[0] = None
            needle = tag_search_var.get().strip().casefold()
            for child in tag_scroll.winfo_children():
                child.destroy()
            for group_id, tags in tag_groups:
                visible = [
                    tag for tag in tags
                    if tag in tag_vars and
                    (not needle or needle in tag.casefold())
                ]
                if not visible:
                    continue
                group = ctk.CTkFrame(
                    tag_scroll, fg_color=BG_SECTION, corner_radius=8,
                    border_width=1, border_color=BORDER_CARD)
                group.pack(fill='x', padx=3, pady=4)
                ctk.CTkLabel(
                    group,
                    text=(T(group_key[group_id]) if group_id in group_key
                          else T('site_filter_other_tags')),
                    text_color=TEXT_SEC,
                    font=(ui_font(), 10, 'bold')).pack(
                        anchor='w', padx=10, pady=(8, 4))
                grid = ctk.CTkFrame(group, fg_color='transparent')
                grid.pack(fill='x', padx=8, pady=(0, 8))
                for column in range(3):
                    grid.grid_columnconfigure(column, weight=1)
                for index, tag in enumerate(visible):
                    ctk.CTkCheckBox(
                        grid, text=tag, variable=tag_vars[tag],
                        height=26, checkbox_width=17, checkbox_height=17,
                        corner_radius=4, border_width=1,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER,
                        border_color=BORDER_HOVER, checkmark_color=WHITE,
                        text_color=TEXT_SEC, font=(ui_font(), 9),
                        command=update_selected_count).grid(
                            row=index // 3, column=index % 3, sticky='w',
                            padx=6, pady=2)

        def schedule_render(*_args):
            if render_after[0] is not None:
                try:
                    popup.after_cancel(render_after[0])
                except tk.TclError:
                    pass
            render_after[0] = popup.after(120, render_tags)

        tag_search_var.trace_add('write', schedule_render)
        render_tags()
        update_selected_count()

        footer = ctk.CTkFrame(popup, fg_color=BG_CARD, corner_radius=0)
        footer.grid(row=3, column=0, sticky='ew')

        def close_popup():
            try:
                popup.destroy()
            except tk.TclError:
                pass
            self._site_filter_popup = None

        def clear_form():
            query_var.set('')
            genre_var.set(any_value)
            sort_var.set(any_value)
            date_var.set(any_value)
            duration_var.set(any_value)
            tag_search_var.set('')
            for variable in tag_vars.values():
                variable.set(False)
            update_selected_count()

        def selected_value(variable):
            value = variable.get().strip()
            return '' if value == any_value else value

        def apply_filter():
            self._site_filter_state = {
                'query': query_var.get().strip(),
                'genre': selected_value(genre_var),
                'sort': selected_value(sort_var),
                'date': selected_value(date_var),
                'duration': selected_value(duration_var),
                'tags': tuple(
                    tag for tag, variable in tag_vars.items()
                    if variable.get()),
            }
            close_popup()
            self._apply_site_filter_state()

        ctk.CTkButton(
            footer, text=T('site_filter_apply'), width=116, height=38,
            corner_radius=CONTROL_RADIUS, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, text_color=WHITE,
            font=(ui_font(), 10, 'bold'), command=apply_filter).pack(
                side='right', padx=(8, 18), pady=12)
        ctk.CTkButton(
            footer, text=T('site_filter_reset'), width=92, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            font=(ui_font(), 10), command=clear_form).pack(
                side='right', pady=12)
        ctk.CTkButton(
            footer, text=T('st_calendar_cancel'), width=92, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=(ui_font(), 10), command=close_popup).pack(
                side='right', padx=(0, 8), pady=12)

        popup.protocol('WM_DELETE_WINDOW', close_popup)
        query_entry.focus_set()
        popup.update_idletasks()
        x = self.winfo_rootx() + max(
            0, (self.winfo_width() - popup.winfo_width()) // 2)
        y = self.winfo_rooty() + max(
            0, (self.winfo_height() - popup.winfo_height()) // 3)
        popup.geometry(f'+{x}+{y}')

    def _on_site_change(self, val):
        self._site_key = val
        self._search_query = ''
        self._show_search_sort(False)
        self._reset_site_filter_state()
        self._sync_site_filter_button_visibility()
        self._categories.clear()
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._rebuild_sidebar()
        self._load_categories()

    def _on_cat_change(self, val):
        idx = next((i for i, c in enumerate(self._categories)
                    if c['name'] == val), -1)
        if idx < 0:
            return
        self._search_query = ''
        self._show_search_sort(False)
        if self._site_key == 'site':
            self._reset_site_filter_state()
        self._current_base_url = self._categories[idx]['url']
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._load_page()

    def _search_sorts(self):
        browser = SITES.get(self._site_key, {}).get('browser')
        return [(_section_label(label), value)
                for label, value in (getattr(browser, 'SEARCH_SORTS', []) or [])]

    def _show_search_sort(self, show):
        sorts = self._search_sorts() if show else []
        try:
            if sorts:
                labels = [label for label, _value in sorts]
                self._search_sort_menu.configure(values=labels)
                if self._search_sort_var.get() not in labels:
                    self._search_sort_var.set(labels[0])
                if not self._search_sort_visible:
                    self._search_sort_menu.pack(side='left', padx=(0, 8),
                                                before=self._search_btn)
                    self._search_sort_visible = True
            elif self._search_sort_visible:
                self._search_sort_menu.pack_forget()
                self._search_sort_visible = False
        except (AttributeError, tk.TclError):
            pass

    def _on_search_sort(self, _label):
        if self._search_query:
            self._on_search(query=self._search_query)

    def _on_search(self, query=None):
        q = (query if query is not None else self._search_var.get()).strip()
        if not q:
            return
        if query is None and q != self._search_query:
            # A new search starts with the site's default order.
            self._search_sort_var.set('')
        self._search_query = q
        self._show_search_sort(True)
        sort_value = dict(self._search_sorts()).get(self._search_sort_var.get(), '')
        from urllib.parse import quote
        if self._site_key == 'site':
            # site does not expose language-specific listing/search variants.
            self._current_base_url = f'https://example.com/search/?q={quote(q, safe="")}'
        elif self._site_key == 'site':
            self._current_base_url = siteBrowser.search_url(q, lang=T('site_lang'))
        elif self._site_key == 'site':
            self._site_filter_state['query'] = q
            self._apply_site_filter_state()
            return
        elif self._site_key in SITES and hasattr(
                SITES[self._site_key]['browser'], 'search_url'):
            # site, site, KVS sites…: each browser builds its own URL.
            self._current_base_url = SITES[self._site_key]['browser'].search_url(
                q, sort_value)
        else:
            lang = T('site_lang')
            eq = quote(q, safe='')
            if lang:
                self._current_base_url = f'https://{config.MIRRORS["site"][0]}/{lang}/search/{eq}'
            else:
                self._current_base_url = f'https://{config.MIRRORS["site"][0]}/search/{eq}'
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._load_page()

    def _on_tag_click(self, url: str, name: str):
        self._current_base_url = url
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._cat_var.set(f'🏷 {name}')
        self._load_page()

    # ── Sidebar ──────────────────────────────────────────────────────
    def _rebuild_sidebar(self):
        if self._sidebar is None:   # tag sidebar removed from Browse
            return
        for w in self._sidebar.winfo_children():
            w.destroy()

        ctk.CTkLabel(self._sidebar, text=T('sidebar_title'),
                     text_color=ACCENT,
                     font=(ui_font(), 14, 'bold')).pack(
            anchor='w', padx=14, pady=(14, 10))

        # Subtle divider
        ctk.CTkFrame(self._sidebar, height=1,
                     fg_color=BORDER).pack(fill='x', padx=8, pady=(0, 6))

        if self._site_key != 'site':
            ctk.CTkLabel(self._sidebar, text=T('tags_site_only'),
                         text_color=TEXT_DIM,
                         font=(ui_font(), 10)).pack(pady=20)
            return

        tags = siteBrowser.SIDEBAR_TAGS
        for group_name, tag_list in tags.items():
            expanded = self._sidebar_expanded.get(group_name, False)
            display_group_name = site_i18n.loc(site_i18n.TAG_GROUPS, group_name, group_name)

            # Group header button
            arrow = '▾' if expanded else '▸'
            hdr = ctk.CTkButton(
                self._sidebar,
                text=f'{arrow} {display_group_name} ({len(tag_list)})',
                fg_color='transparent', hover_color=BG_CARD_HOVER,
                text_color=TEXT_SEC, anchor='w',
                font=(ui_font(), 10, 'bold'),
                height=30, corner_radius=8,
                command=lambda g=group_name: self._toggle_group(g))
            hdr.pack(fill='x', padx=6, pady=1)

            if expanded:
                for name, slug in tag_list:
                    tag_url = siteBrowser.tag_url(slug)
                    display_name = site_i18n.loc(site_i18n.TAGS, slug, name)
                    btn = ctk.CTkButton(
                        self._sidebar, text=display_name,
                        fg_color='transparent', hover_color=BG_CARD_HOVER,
                        text_color=TEXT_SEC, anchor='w',
                        font=(ui_font(), 10),
                        height=26, corner_radius=8,
                        command=lambda u=tag_url, n=display_name: self._on_tag_click(u, n))
                    btn.pack(fill='x', padx=(18, 6), pady=0)

    def _toggle_group(self, group: str):
        self._sidebar_expanded[group] = not self._sidebar_expanded.get(group, False)
        self._rebuild_sidebar()

    # ── Download actions ─────────────────────────────────────────────
    def _review_selected(self, start_download: bool = False):
        ordered = list(self._selected_videos) or list(self._selected_urls)
        if not ordered:
            self._status_lbl.configure(text=T('selection_preview_empty'))
            return
        popup = ctk.CTkToplevel(self)
        popup.title(T('selection_preview_title'))
        popup.geometry('760x620')
        popup.minsize(620, 460)
        popup.transient(self)
        popup.configure(fg_color=BG_DARK)

        header = ctk.CTkFrame(popup, fg_color=BG_SECTION, corner_radius=0)
        header.pack(fill='x')
        ctk.CTkLabel(
            header, text=T('selection_preview_title'), text_color=TEXT_PRI,
            font=(ui_font(), 17, 'bold')).pack(
                anchor='w', padx=20, pady=(16, 2))
        ctk.CTkLabel(
            header, text=T('selection_preview_desc', count=len(ordered)),
            text_color=TEXT_DIM, font=(ui_font(), 10)).pack(
                anchor='w', padx=20, pady=(0, 14))

        options = ctk.CTkFrame(popup, fg_color=BG_CARD)
        options.pack(fill='x', padx=16, pady=12)
        resolution_var = ctk.StringVar(value=self._resolution_label())
        template_var = ctk.StringVar(value=config.get_filename_template())
        ctk.CTkLabel(
            options, text=T('selection_preview_resolution'),
            text_color=TEXT_SEC, font=(ui_font(), 10, 'bold')).grid(
                row=0, column=0, padx=(14, 8), pady=12, sticky='w')
        ctk.CTkOptionMenu(
            options, values=self._resolution_values(),
            variable=resolution_var, width=140, height=32,
            fg_color=BG_INPUT, button_color=BORDER_HOVER,
            button_hover_color=ACCENT,
            dropdown_fg_color=BG_CARD).grid(
                row=0, column=1, padx=(0, 18), pady=12, sticky='w')
        ctk.CTkLabel(
            options, text=T('selection_preview_template'),
            text_color=TEXT_SEC, font=(ui_font(), 10, 'bold')).grid(
                row=0, column=2, padx=(0, 8), pady=12, sticky='w')
        template_entry = ctk.CTkEntry(
            options, textvariable=template_var, height=32,
            fg_color=BG_INPUT, border_color=BORDER,
            text_color=TEXT_PRI)
        template_entry.grid(
            row=0, column=3, padx=(0, 14), pady=12, sticky='ew')
        options.grid_columnconfigure(3, weight=1)

        listing = ctk.CTkScrollableFrame(
            popup, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER)
        listing.pack(fill='both', expand=True, padx=16)
        choices = {
            url: ctk.BooleanVar(value=True) for url in ordered
        }
        for url in ordered[:200]:
            video = self._selected_videos.get(url, {})
            enabled = choices[url]
            row = ctk.CTkFrame(
                listing, fg_color=BG_CARD, corner_radius=8,
                border_width=1, border_color=BORDER_CARD)
            row.pack(fill='x', pady=4)
            ctk.CTkCheckBox(
                row, text='', variable=enabled, width=24,
                fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(
                    side='left', padx=(12, 6), pady=10)
            labels = ctk.CTkFrame(row, fg_color='transparent')
            labels.pack(side='left', fill='x', expand=True, pady=8)
            title = str(video.get('title') or url.rstrip('/').split('/')[-1])
            ctk.CTkLabel(
                labels, text=title, text_color=TEXT_PRI,
                font=(ui_font(), 10, 'bold'), anchor='w').pack(fill='x')
            ctk.CTkLabel(
                labels,
                text=f'{site_name(url)} · {video_code(url, title)} · {url}',
                text_color=TEXT_DIM, font=('Consolas', 8),
                anchor='w').pack(fill='x', pady=(2, 0))
        if len(ordered) > 200:
            ctk.CTkLabel(
                listing,
                text=T('selection_preview_more', count=len(ordered) - 200),
                text_color=TEXT_DIM, font=(ui_font(), 10)).pack(
                    anchor='w', padx=12, pady=10)

        footer = ctk.CTkFrame(popup, fg_color=BG_HEADER, corner_radius=0)
        footer.pack(fill='x', pady=(12, 0))

        def _commit(download):
            keep = {url for url, variable in choices.items() if variable.get()}
            for url in list(self._selected_urls):
                if url not in keep:
                    self._selected_urls.discard(url)
                    self._selected_videos.pop(url, None)
            if not keep:
                popup.destroy()
                self._update_selection_count()
                return
            if download and not self._preflight_download_destination():
                return
            resolution = self._resolution_pref_from_label(
                resolution_var.get())
            template = config.normalize_filename_template(
                template_var.get())
            due = next_schedule_epoch(config.get_download_schedule())
            if download:
                self._download_selected(
                    resolution, template, not_before=due)
            else:
                self._add_selected_to_queue(resolution, template)
            popup.destroy()

        ctk.CTkButton(
            footer, text=T('selection_preview_cancel'), width=96,
            height=36, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, command=popup.destroy).pack(
                side='left', padx=16, pady=12)
        secondary_text = (
            T('selection_preview_add') if start_download
            else T('selection_preview_download'))
        secondary_action = (False if start_download else True)
        ctk.CTkButton(
            footer, text=secondary_text, width=132, height=36,
            fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=lambda: _commit(secondary_action)).pack(
                side='right', padx=(0, 8), pady=12)
        primary_text = (
            T('selection_preview_download') if start_download
            else T('selection_preview_add'))
        ctk.CTkButton(
            footer, text=primary_text, width=142, height=36,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE,
            command=lambda: _commit(start_download)).pack(
                side='right', padx=(0, 8), pady=12)
        popup.grab_set()
        popup.focus_force()

    def _preflight_download_destination(self) -> bool:
        minimum = config.get_minimum_free_gb()
        result = storage_preflight(
            self._dest_var.get() or 'download',
            minimum_free_bytes=int(minimum * 1024 ** 3))
        if result.ok:
            config.set_download_directory(result.path)
            return True
        if result.error == 'low_space':
            message = T(
                'disk_low_space', free=f'{result.free_bytes / 1024 ** 3:.2f}',
                minimum=f'{minimum:.2f}')
        else:
            message = T('disk_preflight_failed', error=result.error)
        self._status_lbl.configure(text=message)
        messagebox.showerror(T('open_folder_failed_title'), message)
        return False

    def _queue_selected(
            self, *, start_download: bool, resolution: str = '',
            filename_template: str = '', not_before: float = 0):
        dest = self._dest_var.get() or 'download'
        requested = added = duplicates = unsupported = started = 0
        ordered = list(self._selected_videos) or list(self._selected_urls)
        for url in ordered:
            requested += 1
            if M3U8Sites.VaildateUrl(url):
                video = self._selected_videos.get(url, {})
                contains = getattr(self._dlmgr, 'contains', None)
                existed = bool(contains(url)) if callable(contains) else False
                self._dlmgr.add_item(
                    url, name=str(video.get('title') or ''),
                    state='等待中', dest=dest, resolution=resolution,
                    filename_template=filename_template,
                    thumbnail=str(video.get('thumbnail') or ''),
                    site=self._site_key)
                if existed:
                    duplicates += 1
                else:
                    added += 1
                if start_download:
                    try:
                        accepted = self._dlmgr.enqueue(
                            url, dest, not_before=not_before)
                    except TypeError:
                        accepted = self._dlmgr.enqueue(url, dest)
                    if accepted is not False:
                        started += 1
            else:
                unsupported += 1
                print(f'[queue] unsupported selected URL: {url}')
        self._clear_selection_in_place()
        return QueueAddSummary(
            requested=requested, added=added, duplicates=duplicates,
            unsupported=unsupported, started=started)

    def _show_queue_summary(self, summary: QueueAddSummary, started=False):
        key = 'queue_started_summary' if started else 'queue_summary'
        text = T(
            key, added=summary.added, started=summary.started,
            duplicates=summary.duplicates,
            unsupported=summary.unsupported)
        label = getattr(self, '_status_lbl', None)
        if label is not None:
            try:
                label.configure(text=text)
            except Exception:
                pass
        print(text, flush=True)

    def _add_selected_to_queue(
            self, resolution: str = '', filename_template: str = ''):
        # "Add to Queue" puts the videos in the real download queue (in
        # order, with a ▲ n ▼ position); they start as slots free up.
        due = next_schedule_epoch(config.get_download_schedule())
        summary = ModernApp._queue_selected(
            self, start_download=True, resolution=resolution,
            filename_template=filename_template, not_before=due)
        ModernApp._show_queue_summary(self, summary, started=True)
        return summary

    def _download_selected(
            self, resolution: str = '', filename_template: str = '',
            not_before: float = 0):
        summary = ModernApp._queue_selected(
            self, start_download=True, resolution=resolution,
            filename_template=filename_template, not_before=not_before)
        ModernApp._show_queue_summary(self, summary, started=True)
        return summary

    def _download_url(self):
        url = self._dl_url_var.get().strip()
        if not url:
            return
        if not self._preflight_download_destination():
            return
        resolution = config.get_resolution_pref()
        filename_template = config.get_filename_template()
        due = next_schedule_epoch(config.get_download_schedule())
        # Direct video URL
        if M3U8Sites.VaildateUrl(url):
            dest = self._dest_var.get() or 'download'
            self._dlmgr.add_item(
                url, state='等待中', dest=dest, resolution=resolution,
                filename_template=filename_template)
            self._dlmgr.enqueue(url, dest, not_before=due)
            self._dl_url_var.set('')
            return
        # Listing / actress / category URL — crawl all videos
        if self._is_listing_url(url):
            self._dl_url_var.set('')
            self._status_lbl.configure(text=T('crawling_url'))
            dest = self._dest_var.get() or 'download'
            threading.Thread(
                target=self._crawl_listing,
                args=(url, dest, resolution, filename_template, due),
                daemon=True).start()
            return
        self._status_lbl.configure(text=T('url_not_supported'))
        print(T('url_not_supported') + f': {url}')

    def _is_listing_url(self, url: str) -> bool:
        """Check if URL is a supported listing/category/actress page."""
        if re.match(r'https://(?:www\.)?site\.com/(?:(?:zh|ja)/)?\d+\.html$', url):
            return False
        if Sitesite.validate_url(url):
            return False
        kvs_name, kvs_browser = _kvs_browser_for_url(url)
        if kvs_name and kvs_name != 'site':
            if hasattr(kvs_browser, 'is_video_url'):
                return not kvs_browser.is_video_url(url)
            return '/videos/' not in urlsplit(url).path
        return (bool(re.match(r'https://(?:www\.)?(?:site\.tv|fs1\.app)/', url)) or
                bool(re.match(r'https://(?:www\.)?(?:site\.(?:ai|ws|live)|site123\.com)/', url)) or
                bool(re.match(r'https://(?:www\.)?site\.com/', url)) or
                bool(re.match(r'https://(?:www\.)?site\.me/', url)))

    def _crawl_listing(
            self, url: str, dest: str, resolution: str = '',
            filename_template: str = '', not_before: float = 0):
        """Crawl a listing URL across all pages; add every video to the queue."""
        gen = self._build_gen
        seen: set[str] = set()
        is_site = bool(re.match(r'https://(?:www\.)?(?:site\.tv|fs1\.app)/', url))
        is_site = bool(re.match(r'https://(?:www\.)?site\.com/', url))
        is_site = bool(re.match(r'https://(?:www\.)?site\.me/', url))
        kvs_name, kvs_browser = _kvs_browser_for_url(url)
        epoch = self._dlmgr._cancel_epoch
        fingerprints = set()
        reason = ''
        page = 1

        def _cancelled():
            return (self._is_closing or gen != self._build_gen or
                    epoch != self._dlmgr._cancel_epoch)

        while not _cancelled():
            try:
                if is_site:
                    if page == 1:
                        page_url = url
                    elif '?' in url:
                        page_url = f'{url}&from={page}'
                    else:
                        page_url = f'{url.rstrip("/")}/?from={page}'
                    videos = siteBrowser.fetch_page(page_url)
                elif is_site:
                    page_url = siteBrowser.page_url(url, page)
                    videos = siteBrowser.fetch_page(page_url)
                elif is_site:
                    page_url = siteBrowser.page_url(url, page)
                    videos = siteBrowser.fetch_page(page_url)
                elif kvs_browser is not None:
                    page_url = kvs_browser.page_url(url, page)
                    videos = kvs_browser.fetch_page(page_url)
                else:
                    page_url = siteBrowser.page_url(url, page)
                    videos = siteBrowser.fetch_page(page_url)
            except MirrorsBlockedError as e:
                print(f'[crawl] page {page} blocked: {e}')
                reason = T('mirrors_blocked')
                break
            except Exception as e:
                print(f'[crawl] page {page} error: {e}')
                reason = T('fetch_error')
                break

            if _cancelled():
                break
            if not videos:
                if page == 1:
                    print(f'[crawl] No videos found on first page: {url}')
                break
            fingerprint = frozenset(str(v.get('url', '')) for v in videos)
            if fingerprint in fingerprints:
                reason = T('selection_scan_repeated')
                break
            fingerprints.add(fingerprint)

            new_count = 0
            for v in videos:
                if _cancelled():
                    break
                video_url = v.get('url', '')
                if video_url and video_url not in seen and M3U8Sites.VaildateUrl(video_url):
                    seen.add(video_url)
                    new_count += 1
                    name = v.get('title', '')
                    candidate = dict(v)
                    candidate['_site'] = (
                        'site' if is_site
                        else 'site' if is_site
                        else 'site' if is_site
                        else kvs_name if kvs_browser is not None
                        else 'site')
                    candidate['_source_listing_url'] = url
                    self._dlmgr.add_item(
                        video_url, name=name, state='等待中', dest=dest,
                        resolution=resolution,
                        filename_template=filename_template,
                        thumbnail=str(v.get('thumbnail') or ''),
                        site=candidate['_site'])
                    self._dlmgr.enqueue(
                        video_url, dest, not_before=not_before)

            if new_count == 0:
                reason = T('selection_scan_repeated')
                break  # No new videos on this page, stop

            self._ui(lambda n=len(seen): self._status_lbl.configure(
                text=T('crawling_url') + f' ({n})'), gen=gen)
            page += 1
            for _ in range(3):
                if _cancelled():
                    break
                time.sleep(0.1)

        n = len(seen)
        if _cancelled():
            reason = T('selection_scan_cancelled')
        self._ui(lambda: self._status_lbl.configure(
            text=(T('selection_all_partial', count=n, reason=reason)
                  if reason else T('crawl_added', n=n))), gen=gen)

    def _download_all(self):
        if not self._preflight_download_destination():
            return
        resolution = config.get_resolution_pref()
        filename_template = config.get_filename_template()
        due = next_schedule_epoch(config.get_download_schedule())
        # If the URL field has a listing URL, crawl it first
        url = self._dl_url_var.get().strip()
        if url:
            if M3U8Sites.VaildateUrl(url):
                dest = self._dest_var.get() or 'download'
                self._dlmgr.add_item(
                    url, state='等待中', dest=dest, resolution=resolution,
                    filename_template=filename_template)
                self._dlmgr.enqueue(url, dest, not_before=due)
                self._dl_url_var.set('')
            elif self._is_listing_url(url):
                self._dl_url_var.set('')
                self._status_lbl.configure(text=T('crawling_url'))
                dest = self._dest_var.get() or 'download'
                threading.Thread(
                    target=self._crawl_listing,
                    args=(url, dest, resolution, filename_template, due),
                    daemon=True).start()
                return
        dest = self._dest_var.get() or 'download'
        count = 0
        for item in self._dlmgr.get_items():
            # Local file rows are not downloads.
            if item.local:
                continue
            # Skip items that are already active or completed; queued ('等待中')
            # items still need enqueue() to (re)start them.
            if item.state in ('已下載', '下載中', '準備中', '已存在'):
                continue
            if self._dlmgr.enqueue(
                    item.url, item.dest or dest, not_before=due):
                count += 1
        if count:
            print(f'已加入 {count} 個下載任務')

    def _import_urls(self, urls) -> QueueAddSummary:
        """Put a list of addresses into the queue, and say what happened.

        An address already in the list is not simply ignored: one that
        stopped (paused, cancelled, failed) is started again, which is what
        importing the same list twice is usually meant to do.  Nothing ever
        happens silently — the result is always shown.
        """
        dest = self._dest_var.get() or 'download'
        due = next_schedule_epoch(config.get_download_schedule())
        requested = added = requeued = waiting = finished = unsupported = 0
        skipped = []
        for url in urls:
            requested += 1
            if not M3U8Sites.VaildateUrl(url):
                unsupported += 1
                skipped.append(url)
                continue
            existing = next((item for item in self._dlmgr.get_items()
                             if item.url == url), None)
            if existing is not None:
                if existing.state in DONE_STATES:
                    finished += 1
                    continue
                if existing.state in ACTIVE_STATES or existing.state in QUEUED_STATES:
                    waiting += 1
                    continue
                # Paused, cancelled or failed: start it again.
                if self._dlmgr.enqueue(url, existing.dest or dest, not_before=due):
                    requeued += 1
                else:
                    waiting += 1
                continue
            self._dlmgr.add_item(
                url, state='等待中', dest=dest,
                resolution=config.get_resolution_pref(),
                filename_template=config.get_filename_template(),
                site=site_name(url))
            # Put it in the real queue straight away so it gets a queue
            # position (▲ n ▼) and starts when a slot is free.
            self._dlmgr.enqueue(url, dest, not_before=due)
            added += 1
        summary = QueueAddSummary(
            requested=requested, added=added,
            duplicates=waiting + finished, unsupported=unsupported)
        report = T('import_report', requested=requested, added=added,
                   requeued=requeued, waiting=waiting, finished=finished,
                   unsupported=unsupported)
        if skipped:
            hosts = sorted({(urlsplit(u).hostname or u).replace('www.', '')
                            for u in skipped})
            print('[import] not added as a site yet: ' + ', '.join(hosts[:10]),
                  flush=True)
            report += '\n\n' + T('import_unsupported_hint',
                                  hosts=', '.join(hosts[:6]))
        self._status_lbl.configure(text=T(
            'import_complete', added=added + requeued,
            duplicates=waiting + finished, unsupported=unsupported))
        self._refresh_downloads(schedule=False)
        messagebox.showinfo(T('import_urls'), report)
        return summary

    def _import_urls_file(self):
        path = filedialog.askopenfilename(filetypes=[
            ('URL files', '*.txt *.csv *.json *.text *.log'),
            ('All files', '*.*'),
        ])
        if not path:
            return
        try:
            urls = load_url_file(path)
        except Exception as exc:
            print(f'[import] {path}: {exc}', flush=True)
            messagebox.showerror(T('import_failed'), f'{exc}')
            return
        if not urls:
            messagebox.showinfo(T('import_failed'), T('import_no_urls'))
            return
        self._import_urls(urls)

    def _paste_urls(self):
        try:
            text = self.clipboard_get()
        except tk.TclError as exc:
            messagebox.showerror(T('import_failed'), str(exc))
            return
        self._import_urls(extract_urls(text))

    def _export_queue(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            filetypes=[('CSV', '*.csv'), ('JSON', '*.json')],
            initialfile='siphon-downloads.csv')
        if not path:
            return
        try:
            export_items(self._dlmgr.get_items(), path)
            self._status_lbl.configure(text=T('export_complete'))
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror(T('export_failed'), str(exc))

    def _retry_download(self, url: str):
        item = next((i for i in self._dlmgr.get_items() if i.url == url), None)
        if item is None:
            return
        dest = item.dest or self._dest_var.get() or 'download'
        restart = getattr(self._dlmgr, 'restart', None)
        if callable(restart) and restart(url, dest):
            return
        item.progress = 0
        item.speed = ''
        item.error = ''
        item.auto_requeues = 0
        item.retry_count = 0
        self._dlmgr.enqueue(url, dest)

    def _handle_download_action(self, url: str):
        item = next((i for i in self._dlmgr.get_items() if i.url == url), None)
        if item is None:
            return
        action = _download_row_action(item)
        if action == 'pause':
            self._dlmgr.pause(url)
        elif action == 'resume':
            self._dlmgr.resume(url, item.dest or self._dest_var.get())
        elif action == 'retry':
            self._retry_download(url)
        elif action == 'force':
            item.error = ''
            self._dlmgr.enqueue(url, item.dest or self._dest_var.get() or 'download',
                                force=True)
            self._refresh_downloads(schedule=False)

    def _on_download_filter_change(self, label):
        reverse = {value: key for key, value in self._dl_filter_labels.items()}
        self._dl_filter = reverse.get(label, 'all')
        self._dl_gen += 1
        # The rows belong to the pool and are reused for whatever the filter
        # now shows.  Destroying them here emptied the list for good: the pool
        # kept handing out widgets that no longer existed.
        self._dl_rows.clear()
        self._dl_first = 0
        self._refresh_downloads(schedule=False)

    def _filtered_download_items(self, items):
        return filter_items(items, self._dl_filter)

    def _notify_batch_complete(self):
        if not config.get_notify_on_complete() or self._is_closing:
            return
        try:
            self._status_lbl.configure(text=T('batch_complete'))
        except (AttributeError, tk.TclError):
            pass
        try:
            if os.name == 'nt':
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                self.bell()
        except Exception:
            pass

    def _cancel_all(self):
        if ((self._dlmgr.active_count or self._dlmgr.pending_count) and
                not messagebox.askyesno(
                    T('cancel_all'), T('cancel_all_confirm'))):
            return
        self._dlmgr.cancel_all()

    def _clear_queue(self):
        if self._dlmgr.get_items() and not messagebox.askyesno(
                T('clear_list'), T('clear_queue_confirm')):
            return
        self._dlmgr.clear_all()
        self._dl_gen += 1
        self._last_download_save_sig = None
        try:
            self._dlmgr.save_csv(CSV_PATH)
        except Exception as e:
            print(f'[clear queue save failed] {e}', flush=True)
        self._refresh_downloads(schedule=False)

    def _on_cf_host_change(self, host):
        ov = config.get_cf_override(host) or {}
        self._cf_cookie_var.set(ov.get('cookie', ''))
        self._cf_ua_var.set(ov.get('ua', ''))

    def _refresh_proxy_status(self, saved=False):
        mode = config.get_proxy_mode()
        if mode == 'manual' and config.get_proxy_url():
            text, color = T('proxy_enabled'), SUCCESS
        elif mode == 'system':
            _display_url, status = config.refresh_system_proxy()
            if status == 'detected':
                text, color = T('proxy_windows_enabled'), SUCCESS
            elif status == 'pac':
                text, color = T('proxy_windows_pac'), WARNING
            elif status == 'invalid':
                text, color = T('proxy_windows_invalid'), ERROR_C
            else:
                text, color = T('proxy_windows_missing'), WARNING
        else:
            text, color = T('proxy_disabled'), TEXT_DIM
        if saved:
            text = f"{T('proxy_saved')} · {text}"
        self._proxy_status_lbl.configure(text=text, text_color=color)

    def _on_proxy_save(self):
        try:
            value = config.set_proxy_url(self._proxy_var.get())
        except (OSError, ValueError):
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._proxy_var.set(value)
        self._refresh_proxy_status(saved=True)

    def _on_proxy_windows(self):
        try:
            config.set_proxy_mode('system')
        except OSError:
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._refresh_proxy_status(saved=True)

    def _on_proxy_clear(self):
        try:
            config.set_proxy_url('')
        except OSError:
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._proxy_var.set('')
        self._refresh_proxy_status()

    def _on_cf_save(self):
        host = self._cf_host_var.get()
        config.set_cf_override(host, self._cf_cookie_var.get(), self._cf_ua_var.get())
        self._refresh_cf_status()
        current = self._cf_status_lbl.cget('text')
        self._cf_status_lbl.configure(text=f"{T('cf_saved')} | {current}")

    def _blocked_kind(self):
        if self._site_key == 'site':
            return last_mirror_failure.get('site', 'cloudflare')
        return 'cloudflare'

    def _blocked_message(self):
        if self._blocked_kind() == 'unreachable':
            return T('site_unreachable', site=self._site_key)
        return T('mirrors_blocked')

    # ── one-click Cloudflare pass ───────────────────────────────────────
    def _cf_pass_host(self):
        if self._site_key == 'site':
            return config.MIRRORS['site'][0]
        browser = SITES.get(self._site_key, {}).get('browser')
        root = getattr(browser, 'ROOT', '')
        return urlsplit(root).hostname if root else ''

    def _start_cf_pass(self, host, reload=False):
        if getattr(self, '_cf_pass_running', False):
            return
        self._cf_pass_running = True
        from siphon.core import cfpass
        gen = self._build_gen
        try:
            self._status_lbl.configure(text=T('cfpass_waiting', host=host))
        except (AttributeError, tk.TclError):
            pass

        def work():
            try:
                cfpass.obtain(host)
                error = ''
            except Exception as exc:
                error = str(exc)
                print(f'[CF pass] {host}: {error}', flush=True)

            def done():
                self._cf_pass_running = False
                if error:
                    messagebox.showerror(T('cf_card_title'), T('cfpass_failed', error=error))
                    return
                try:
                    self._status_lbl.configure(text=T('cfpass_done', host=host))
                    self._refresh_cf_status()
                except (AttributeError, tk.TclError):
                    pass
                if reload:
                    self._load_categories()
            self._ui(done, gen=gen)
        threading.Thread(target=work, daemon=True).start()

    def _on_cf_auto(self):
        host = self._cf_host_var.get()
        if host:
            self._start_cf_pass(host)

    def _on_cf_clear(self):
        host = self._cf_host_var.get()
        config.clear_cf_override(host)
        self._cf_cookie_var.set('')
        self._cf_ua_var.set('')
        self._refresh_cf_status()

    def _refresh_cf_status(self):
        hosts = config.cf_override_hosts()
        if hosts:
            self._cf_status_lbl.configure(text=T('cf_status', hosts=', '.join(hosts)))
        else:
            self._cf_status_lbl.configure(text=T('cf_status_none'))

    def _on_speed_change(self, val):
        from siphon.sites.base import speed_limiter
        val = str(val)
        if val == T('speed_custom'):
            bps = speed_limit.ask_custom(
                T('speed_limit_setting'), T('speed_custom_prompt'),
                current_bps=int(self._speed_mbps * 1024 * 1024), master=self)
            if bps is None:          # cancelled or invalid: keep the old value
                self._speed_var.set(self._speed_label())
                return
        else:
            bps = speed_limit.parse_speed(
                '0' if val == T('unlimited') else val) or 0
        mbps = bps / (1024 * 1024)
        self._speed_mbps = mbps
        speed_limiter.set_limit(mbps)
        config.set_speed_limit_mbps(mbps)
        self._refresh_speed_menus()

    def _refresh_speed_menus(self):
        values = self._speed_values()
        for menu in getattr(self, '_speed_menus', []):
            try:
                menu.configure(values=values)
            except tk.TclError:
                pass
        self._speed_var.set(self._speed_label())

    def _on_res_change(self, val):
        from siphon.sites.base import set_resolution_pref
        pref = self._resolution_pref_from_label(val)
        set_resolution_pref(pref)
        config.set_resolution_pref(pref)

    def _on_filename_mode_change(self, val):
        mode = config.set_filename_mode(
            self._filename_mode_from_label(val))
        self._filename_mode_var.set(self._filename_mode_label(mode))

    def _on_filename_template_change(self, _event=None):
        value = config.set_filename_template(
            self._filename_template_var.get())
        self._filename_template_var.set(value)

    def _on_download_schedule_change(self, _event=None):
        try:
            value = config.set_download_schedule(
                self._download_schedule_var.get())
        except ValueError:
            value = config.get_download_schedule()
        self._download_schedule_var.set(value)

    def _on_minimum_free_change(self, _event=None):
        value = config.set_minimum_free_gb(
            self._minimum_free_var.get())
        self._minimum_free_var.set(str(value))

    def _on_auto_retry_change(self, _event=None):
        value = config.set_auto_retry_count(
            self._auto_retry_var.get())
        self._auto_retry_var.set(str(value))

    def _on_scroll_speed(self, raw):
        value = ui_scroll.set_speed(int(round(float(raw))))
        self._scroll_speed_lbl.configure(text=f'{value}x')

    def _on_notify_complete_change(self):
        config.set_notify_on_complete(
            self._notify_complete_var.get())

    def _on_conc_change(self, _event=None):
        try:
            requested = int(self._conc_var.get().strip())
        except (AttributeError, TypeError, ValueError):
            self._conc_var.set(str(self._dlmgr.max_concurrent))
            return
        value = config.set_download_concurrency(requested)
        self._dlmgr.max_concurrent = value
        self._conc_var.set(str(value))

    def _commit_workers_preference(self):
        current = config.get_max_workers_per_video()
        var = self.__dict__.get('_workers_var')
        if var is None:
            return current
        try:
            requested = int(var.get().strip())
        except (AttributeError, TypeError, ValueError):
            value = current
        else:
            value = config.set_max_workers_per_video(requested)
        var.set(str(value))
        return value

    def _on_workers_change(self, _event=None):
        self._commit_workers_preference()

    # ── per-site connections per video ──────────────────────────────────
    def _workers_site(self):
        site = self._workers_site_var.get()
        return site if site in config.WORKER_SITES else ''

    def _show_site_workers(self):
        site = self._workers_site()
        cap = config.site_worker_cap(site) if site else config.MAX_WORKERS_PER_VIDEO
        if site:
            value = config.get_max_workers_for_site(site)
            custom = site in config.get_site_workers_overrides()
        else:
            value = config.get_max_workers_per_video()
            custom = False
        self._workers_slider.configure(to=max(cap, 2), number_of_steps=max(cap - 1, 1))
        self._workers_slider.set(min(value, cap))
        self._workers_value_lbl.configure(text=str(min(value, cap)))
        note = T('workers_range', n=cap)
        if site and not custom:
            note += ' · ' + T('workers_inherits')
        self._workers_range_lbl.configure(text=note)
        if site and custom:
            if not self._workers_reset_btn.winfo_ismapped():
                self._workers_reset_btn.pack(side='left')
        else:
            self._workers_reset_btn.pack_forget()

    def _on_workers_slide(self, raw):
        value = int(round(float(raw)))
        site = self._workers_site()
        if site:
            config.set_site_workers(site, value)
        else:
            value = config.set_max_workers_per_video(value)
            self._workers_var.set(str(value))
        self._show_site_workers()

    def _reset_site_workers(self):
        site = self._workers_site()
        if site:
            config.set_site_workers(site, None)
        self._show_site_workers()

    def _commit_slow_requeue_preference(self):
        current = config.get_slow_requeue_kbps()
        var = self.__dict__.get('_slow_requeue_var')
        if var is None:
            return current
        try:
            requested = int(var.get().strip())
        except (AttributeError, TypeError, ValueError):
            value = current
        else:
            value = config.set_slow_requeue_kbps(requested)
        var.set(str(value))
        return value

    def _on_slow_requeue_change(self, _event=None):
        self._commit_slow_requeue_preference()

    def _pick_dest(self):
        d = filedialog.askdirectory()
        if d:
            self._dest_var.set(d)
            config.set_download_directory(d)

    def _open_dest_folder(self):
        import subprocess, platform
        dest = self._dest_var.get() or 'download'
        folder = os.path.abspath(dest)
        if not os.path.isdir(folder):
            messagebox.showerror(T('open_folder_failed_title'), folder)
            return
        system = platform.system()
        try:
            if system == 'Windows':
                os.startfile(folder)
            elif system == 'Darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except OSError as e:
            messagebox.showerror(T('open_folder_failed_title'), str(e))

    def _open_queue_folder(self):
        import subprocess, platform
        folder = os.path.dirname(config.queue_csv_path())
        system = platform.system()
        try:
            os.makedirs(folder, exist_ok=True)
            if system == 'Windows':
                os.startfile(folder)
            elif system == 'Darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except OSError as e:
            messagebox.showerror(T('open_folder_failed_title'), str(e))

    # ── My own sites ────────────────────────────────────────────────
    def _site_entries(self):
        return site_catalog()

    def _picked_site(self):
        """The site chosen in the picker, or None for "+ add new"."""
        name = self._site_pick_var.get()
        if name == T('mysites_new'):
            return None
        for entry in self._site_entries():
            if entry['name'] == name:
                return entry
        return None

    def _refresh_site_picker(self, keep=''):
        """Redraw the picker and the buttons beside it."""
        if getattr(self, '_site_pick', None) is None or not self._site_pick.winfo_exists():
            return
        entries = self._site_entries()
        labels = [T('mysites_new')] + [
            (entry['name'] if not entry['hidden']
             else T('mysites_off_item', name=entry['name']))
            for entry in entries]
        self._site_pick.configure(values=labels)
        wanted = keep or self._site_pick_var.get()
        if wanted not in labels:
            wanted = T('mysites_new')
        self._site_pick_var.set(wanted)
        self._on_site_pick(wanted)

    def _on_site_pick(self, choice):
        """Show either the address box or the buttons for the chosen site."""
        adding = choice == T('mysites_new')
        name = '' if adding else re.sub(r'\s*\(.*\)$', '', choice)
        entry = None
        for candidate in self._site_entries():
            if candidate['name'] == name:
                entry = candidate
                break
        row = getattr(self, '_mysite_add_row', None)
        if row is not None and row.winfo_exists():
            if adding and not row.winfo_manager():
                row.pack(fill='x', padx=20, pady=(10, 2), before=self._mysite_status)
            elif not adding and row.winfo_manager():
                row.pack_forget()
        for button in (self._site_up_btn, self._site_down_btn,
                       self._site_toggle_btn, self._site_del_btn):
            if button.winfo_exists():
                button.configure(state='disabled' if entry is None else 'normal')
        if entry is None:
            self._set_mysite_status('')
            return
        self._site_toggle_btn.configure(
            text=T('mysites_show') if entry['hidden'] else T('mysites_hide'))
        where = T('mysites_site_known') if entry['builtin'] else T('mysites_site_general')
        state = T('mysites_state_off') if entry['hidden'] else T('mysites_state_on')
        self._set_mysite_status(f"{where} · {state}")

    def _move_site(self, step):
        """Move the chosen site up or down in the Browse list."""
        entry = self._picked_site()
        if entry is None:
            return
        names = [item['name'] for item in self._site_entries()]
        index = names.index(entry['name'])
        target = index + step
        if not 0 <= target < len(names):
            return
        names[index], names[target] = names[target], names[index]
        config.set_site_order(names)
        self._refresh_site_menu()
        self._refresh_site_picker(keep=self._site_pick_var.get())
        self._set_mysite_status(T('mysites_moved', name=entry['name'],
                                  place=target + 1), SUCCESS)

    def _toggle_site(self):
        """Switch a site off (hidden from Browse) or back on."""
        entry = self._picked_site()
        if entry is None:
            return
        config.set_site_hidden(entry['name'], not entry['hidden'])
        self._refresh_site_menu()
        label = (entry['name'] if entry['hidden']
                 else T('mysites_off_item', name=entry['name']))
        self._refresh_site_picker(keep=label)
        self._set_mysite_status(
            T('mysites_turned_on' if entry['hidden'] else 'mysites_turned_off',
              name=entry['name']), SUCCESS)

    def _remove_picked_site(self):
        """Remove a site the user added; a built-in one is only switched off."""
        entry = self._picked_site()
        if entry is None:
            return
        if not messagebox.askyesno(T('mysites_remove'),
                                   T('mysites_remove_confirm', name=entry['name'])):
            return
        for site in config.get_custom_sites():
            known_name, _known = builtin_browser_for_host(site['host'])
            if entry['name'] in ((site.get('name') or site['host']), known_name):
                config.remove_custom_site(site['host'])
        config.set_site_hidden(entry['name'], False)
        self._refresh_site_menu()
        self._refresh_site_picker(keep=T('mysites_new'))
        self._set_mysite_status(T('mysites_removed', name=entry['name']), SUCCESS)

    def _refresh_site_menu(self):
        """Keep the Browse tab's site list in step with Settings."""
        names = register_user_sites()
        menu = getattr(self, '_site_menu', None)
        if menu is None or not menu.winfo_exists():
            return
        if not names:
            self._show_no_sites()
            return
        self._show_browse_chrome(True)
        menu.configure(values=names)
        if self._site_key not in names:
            self._on_site_change(names[0])

    def _set_mysite_status(self, text, color=None):
        label = getattr(self, '_mysite_status', None)
        if label is not None and label.winfo_exists():
            label.configure(text=text, text_color=color or TEXT_DIM)

    def _test_custom_site(self):
        """Add every address in the box: one, or a whole list at once."""
        from siphon.sites.generic import normalize_site_url
        raw = self._mysite_var.get() or ''
        wanted = [part for part in re.split(r'[\s,;]+', raw.strip()) if part]
        wanted = [part for part in wanted if normalize_site_url(part)]
        if not wanted:
            self._set_mysite_status(T('mysites_bad_url'), ERROR_C)
            return
        self._add_queue = wanted[1:]
        self._add_done, self._add_failed = [], []
        self._add_one(wanted[0])

    def _add_one(self, url):
        """Add a single address: instantly when this app knows the site,
        otherwise by opening it and looking for a video."""
        from siphon.sites.generic import normalize_site_url
        self._adding_url = url
        host = (urlsplit(normalize_site_url(url)).hostname or '').lower()
        known_name, known = builtin_browser_for_host(host)
        if known is not None:
            self._custom_site_done({'host': re.sub(r'^www\.', '', host),
                                    'title': '', 'kind': '', 'count': 0,
                                    'engine': '', 'engine_label': '',
                                    'root': f'https://{host}'}, '')
            return
        button = getattr(self, '_mysite_btn', None)
        if button is not None and button.winfo_exists():
            button.configure(state='disabled')
        left = len(getattr(self, '_add_queue', []) or [])
        self._set_mysite_status(
            T('mysites_testing_one', host=host, left=left) if left
            else T('mysites_testing'))

        def work():
            try:
                from siphon.sites import generic
                result = generic.probe(url)
            except Exception as exc:
                self._ui(lambda e=exc: self._custom_site_done(None, str(e)))
                return
            self._ui(lambda r=result: self._custom_site_done(r, ''))

        threading.Thread(target=work, daemon=True).start()

    def _teach_from_html(self):
        """Learn a site from pages saved in the user's own browser.

        For a site this app cannot open by itself (members only, region
        blocked, a check it will not pass): the user saves a video page — and
        if possible a listing page — with Ctrl+S, and the layout is read from
        those files instead.
        """
        from siphon.sites import generic
        typed = (self._mysite_var.get() or '').strip()
        files = filedialog.askopenfilenames(
            title=T('mysites_teach_pick'),
            filetypes=[(T('mysites_teach_files'), '*.html *.htm *.txt'),
                       ('All files', '*.*')])
        if not files:
            return
        pages = []
        for path in list(files)[:4]:
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as handle:
                    pages.append((path, handle.read()))
            except OSError as exc:
                self._set_mysite_status(T('mysites_teach_unreadable', error=str(exc)),
                                        ERROR_C)
                return
        # The page with a video in it is the video page; the one listing many
        # videos is the listing.
        video_page = listing_page = None
        for path, text in pages:
            address = generic.page_address(text) or ''
            if generic.find_sources(text, address or 'https://site/v/1/'):
                video_page = video_page or (path, text, address)
            else:
                listing_page = listing_page or (path, text, address)
        if video_page is None:
            self._set_mysite_status(T('mysites_teach_novideo'), ERROR_C)
            return
        _path, text, address = video_page
        # The saved file knows which site it came from; what the user typed is
        # only the fallback.
        root = generic.page_site(text) or generic.normalize_site_url(typed).rstrip('/')
        address = address or (root + '/video/')
        host = (urlsplit(root).hostname or '').lower()
        if not host:
            self._set_mysite_status(T('mysites_teach_noaddress'), ERROR_C)
            return
        listing_text = listing_page[1] if listing_page else ''
        listing_url = ((listing_page[2] if listing_page else '')
                       or (generic.page_site(listing_text) if listing_text else '')
                       or root) + '/'
        learned = generic.learn_from_html(text, address,
                                          listing_text=listing_text,
                                          listing_url=listing_url.replace('//', '/', 0))
        host = re.sub(r'^www\.', '', host)
        profile = config.get_site_profile(host)
        profile.update(learned['profile'])
        profile.setdefault('root', f'https://{host}')
        config.set_site_profile(host, profile)
        config.add_custom_site(host, host)
        name = learned['engine_label'] or host
        config.save_site_template(name, learned['markers'], learned['template'])
        self._mysite_var.set('')
        self._refresh_site_menu()
        self._refresh_site_picker(keep=host)
        self._set_mysite_status(
            T('mysites_teach_done', host=host, kind=learned['kind'] or '?',
              listed=learned['videos_listed'], name=name), SUCCESS)

    def _custom_site_done(self, result, error):
        """One address finished: record it, then move on to the next."""
        button = getattr(self, '_mysite_btn', None)
        if button is not None and button.winfo_exists():
            button.configure(state='normal')
        done = getattr(self, '_add_done', None)
        failed = getattr(self, '_add_failed', None)
        if done is None:
            done, failed = [], []
            self._add_done, self._add_failed = done, failed
        note = ''
        if not result:
            failed.append((getattr(self, '_adding_url', ''), error))
            note = T('mysites_failed', error=error)
            colour = ERROR_C
        else:
            profile = config.get_site_profile(result['host'])
            profile['root'] = result.get('root') or f"https://{result['host']}"
            if result.get('engine'):
                profile['engine'] = result['engine']
            config.set_site_profile(result['host'], profile)
            config.add_custom_site(result['host'], result['host'])
            self._refresh_site_menu()
            known_name, known = builtin_browser_for_host(result['host'])
            done.append(known_name or result['host'])
            self._refresh_site_picker(keep=known_name or result['host'])
            colour = SUCCESS
            if known is not None:
                note = T('mysites_added_known', host=result['host'], name=known_name)
            else:
                note = T('mysites_added', host=result['host'], title=result['title'],
                         kind=result['kind'])
                if result.get('engine_label'):
                    note += ' ' + T('mysites_engine', engine=result['engine_label'])
        queue = getattr(self, '_add_queue', None) or []
        if queue:
            self._add_queue = queue[1:]
            self._add_one(queue[0])
            return
        self._mysite_var.set('')
        if len(done) + len(failed) > 1:
            summary = T('mysites_batch_done', added=len(done), failed=len(failed))
            if failed:
                summary += ' ' + T('mysites_batch_failed',
                                   hosts=', '.join(url for url, _e in failed))
            self._set_mysite_status(summary, SUCCESS if done else ERROR_C)
        else:
            self._set_mysite_status(note, colour)
        self._add_done, self._add_failed = [], []

    def _clear_saved_queue(self):
        if not messagebox.askyesno(T('clear_saved_queue'),
                                   T('clear_saved_queue_confirm')):
            return
        self._dlmgr.clear_all()
        self._dl_gen += 1
        self._last_download_save_sig = None
        try:
            self._dlmgr.save_csv(CSV_PATH)
            if getattr(self, '_status_lbl', None) is not None:
                self._status_lbl.configure(text=T('clear_saved_queue_done'))
            messagebox.showinfo(T('clear_saved_queue'), T('clear_saved_queue_done'))
        except Exception as e:
            messagebox.showerror(T('clear_saved_queue_failed'), str(e))
        finally:
            self._refresh_downloads(schedule=False)

    # ── Download list refresh (incremental — no destroy/rebuild storm) ──
    _STATE_COLORS = {
        '下載中': ACCENT, '準備中': WARNING, '等待中': WARNING,
        '已下載': SUCCESS,
        '未完成': WARNING, '已取消': TEXT_DIM,
        '網址錯誤': ERROR_C, '封鎖/解析失敗': ERROR_C,
        '等待重試': WARNING, '已排程': ACCENT, '已暫停': TEXT_DIM,
        '已存在': SUCCESS,
    }
    _STATE_BACKGROUNDS = {
        '下載中': ACCENT_DIM, '準備中': WARNING_DIM, '等待中': WARNING_DIM,
        '已下載': SUCCESS_DIM,
        '未完成': WARNING_DIM, '已取消': BG_BADGE,
        '網址錯誤': ERROR_DIM, '封鎖/解析失敗': ERROR_DIM,
        '等待重試': WARNING_DIM, '已排程': ACCENT_DIM,
        '已暫停': BG_BADGE,
        '已存在': SUCCESS_DIM,
    }

    def _queue_step(self, url, delta):
        pos = (getattr(self, '_queue_pos', {}) or {}).get(url)
        if pos is None:
            return
        if self._dlmgr.move_in_queue(url, pos + delta):
            self._refresh_downloads(schedule=False)

    def _queue_edit_position(self, url):
        """Turn the number into a small entry; Enter moves the item there."""
        w = self._dl_rows.get(url)
        pos = (getattr(self, '_queue_pos', {}) or {}).get(url)
        if w is None or pos is None or w.get('q_editor') is not None:
            return
        var = ctk.StringVar(value=str(pos))
        editor = ctk.CTkEntry(
            w['queue_box'], textvariable=var, width=34, height=22,
            corner_radius=4, border_width=1, border_color=ACCENT,
            fg_color=BG_INPUT, text_color=TEXT_PRI, justify='center',
            font=('Consolas', 11, 'bold'))
        w['q_num'].pack_forget()
        editor.pack(side='top', pady=1, after=w['q_up'])
        w['q_editor'] = editor
        editor.focus_set()
        editor.select_range(0, 'end')

        def finish(apply):
            if w.get('q_editor') is not editor:
                return
            w['q_editor'] = None
            value = var.get().strip()
            try:
                editor.destroy()
                w['q_num'].pack(side='top', pady=1, after=w['q_up'])
            except tk.TclError:
                pass
            w['last_q'] = None
            if apply and value.isdigit():
                self._dlmgr.move_in_queue(url, int(value))
            self._refresh_downloads(schedule=False)

        editor.bind('<Return>', lambda _e: finish(True))
        editor.bind('<KP_Enter>', lambda _e: finish(True))
        editor.bind('<Escape>', lambda _e: finish(False))
        editor.bind('<FocusOut>', lambda _e: finish(True))

    def _resolve_missing_titles(self, items):
        """Give queued rows their real names.

        A pasted link only carries the site's own video number, so the row
        would read "924865622775" until the download starts.  Each waiting
        row's page is read in the background, just for its title.

        A page that cannot be named right now — the site is busy, or it
        answered with a bot check — is tried again on a later sweep rather
        than left as a number for good, up to _TITLE_ATTEMPTS times.
        """
        if getattr(self, '_title_worker_busy', False):
            return
        waiting = [item.url for item in items
                   if not item.local and item.state in QUEUED_STATES
                   and (not item.name or item.name == _fallback_name(item.url))
                   and self._titles_tried.get(item.url, 0) < _TITLE_ATTEMPTS]
        if not waiting:
            return
        waiting = waiting[:120]
        self._title_worker_busy = True

        def work():
            try:
                from concurrent.futures import ThreadPoolExecutor
                import siphon.sites as sites
                from siphon.sites import generic
                seen: dict = {}
                missed = []

                def take(url, title, trusted=False):
                    """True when the title was used, False when refused.

                    ``trusted`` marks the site adapter's answer, which is the
                    name the file will be saved under: two videos really can
                    share a name, so it is never second-guessed.
                    """
                    if not title:
                        return False
                    if not trusted:
                        # The same text on three different videos is a notice
                        # the site puts on every page, not a title.
                        seen.setdefault(title, []).append(url)
                        if len(seen[title]) == 3:
                            for stale in seen[title]:
                                self._ui(lambda u=stale, t=title:
                                         self._clear_title(u, t))
                                missed.append(stale)
                        if len(seen[title]) >= 3:
                            return False
                    self._ui(lambda u=url, t=title: self._apply_title(u, t))
                    return True

                # First pass: read the top of each page.  Cheap and parallel,
                # so most rows are named within a second or two.
                with ThreadPoolExecutor(max_workers=8) as pool:
                    for url, title in zip(waiting,
                                          pool.map(generic.page_title, waiting)):
                        if not take(url, title):
                            missed.append(url)

                # Second pass, for the rest: ask the site's own adapter, which
                # is the code that will name the file when the download runs.
                # It knows where that site keeps its heading and opens the
                # off-screen browser when the site insists on one, so it costs
                # seconds a page; what does not fit in this sweep is picked up
                # by the next one.
                tried = self._titles_tried
                # Least-tried first, so a long list works its way through
                # instead of the same few pages being retried every sweep.
                rest = sorted(dict.fromkeys(missed),
                              key=lambda u: tried.get(u, 0))[:_ADAPTER_TITLE_LIMIT]
                for url in rest:
                    tried[url] = tried.get(url, 0) + 1
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for url, title in zip(rest, pool.map(sites.title_for, rest)):
                        if self._is_closing:
                            break
                        take(url, title, trusted=True)
            except Exception as exc:
                print(f'[title] {exc}', flush=True)
            finally:
                self._title_worker_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _clear_title(self, url, title):
        """Take back a name that turned out to be the site's own banner."""
        for item in self._dlmgr.get_items():
            if item.url == url and item.name == title:
                item.name = _fallback_name(url)
                break

    def _apply_title(self, url, title):
        for item in self._dlmgr.get_items():
            if item.url == url and (not item.name
                                    or item.name == _fallback_name(url)):
                item.name = title
                break

    def _refresh_downloads(self, schedule: bool = True):
        if self._is_closing:
            return
        if (self._rebuilding or getattr(self, '_status_lbl', None) is None
                or getattr(self, '_dl_scroll', None) is None):
            # Names are filled in even while another tab is open.
            try:
                self._resolve_missing_titles(self._dlmgr.get_items())
            except Exception:
                pass
            if schedule:
                try:
                    self.after(1000, self._refresh_downloads)
                except tk.TclError:
                    pass
            return
        try:
            all_items = self._dlmgr.get_items()
            self._resolve_missing_titles(all_items)
            items = self._filtered_download_items(all_items)
            self._queue_pos = self._dlmgr.queue_positions()
            if not self._dl_pool:
                self._dl_on_resize()
            self._render_downloads(items)

            # Update status bar
            a = self._dlmgr.active_count
            p = self._dlmgr.pending_count
            parts = []
            if a:
                parts.append(f'{state_label("下載中")} {a}/{self._dlmgr.max_concurrent}')
            if p:
                parts.append(f'{state_label("等待中")} {p}')
            done = sum(1 for i in all_items if i.state == '已下載')
            if done:
                parts.append(f'{state_label("已下載")} {done}')
            eta_text = self._download_eta_text() if (a or p) else ''
            if eta_text:
                parts.append(eta_text)
            self._status_lbl.configure(text='  |  '.join(parts) if parts else T('status_ready'))
            self._update_download_summary(a, p, done, eta_text)
            self._autosave_downloads(all_items)
            busy = bool(a or p)
            if busy:
                self._batch_was_busy = True
                self._batch_notified = False
            elif self._batch_was_busy and not self._batch_notified:
                self._batch_notified = True
                self._notify_batch_complete()
        except Exception as e:
            print(f'[download refresh failed] {e}', flush=True)
        finally:
            if schedule and not self._is_closing:
                try:
                    self.after(1000, self._refresh_downloads)
                except tk.TclError:
                    pass

    def _update_download_summary(self, active, pending, done, eta_text):
        """The bold line above the list: what is running, and how long the
        whole queue should take."""
        label = getattr(self, '_dl_summary_lbl', None)
        if label is None or not label.winfo_exists():
            return
        parts = []
        if active:
            parts.append(T('dl_sum_active', n=active))
        if pending:
            parts.append(T('dl_sum_queued', n=pending))
        if done:
            parts.append(T('dl_sum_done', n=done))
        # The total time left, built straight from the estimate so it reads the
        # same in every language.
        try:
            est = self._dlmgr.queue_estimate() if (active or pending) else None
        except Exception:
            est = None
        if est and est.get('videos'):
            size = _fmt_size(est['bytes']) if est['bytes'] else ''
            prefix = '≈ ' if est['estimated'] else ''
            if est['speed'] > 0 and est['bytes']:
                parts.append(T('dl_sum_left',
                               size=prefix + size,
                               time=_fmt_duration(est['bytes'] / est['speed'])))
            elif size:
                parts.append(prefix + size)
        try:
            label.configure(text='   ·   '.join(parts))
        except tk.TclError:
            pass

    def _download_eta_text(self):
        """'≈ 5.4 GB left · about 1h 30m at 1 MB/s (limit)' for the status bar."""
        try:
            est = self._dlmgr.queue_estimate()
        except Exception:
            return ''
        if not est['videos']:
            return ''
        size = _fmt_size(est['bytes']) if est['bytes'] else ''
        if est['unknown'] and not est['bytes']:
            return T('eta_size_unknown', n=est['videos'])
        prefix = '≈ ' if est['estimated'] else ''
        speed = est['speed']
        if speed <= 0:
            return T('eta_left_no_speed', size=prefix + size)
        speed_text = (f'{speed / 1024:.0f} KB/s' if speed < 1024 * 1024
                      else f'{speed / 1024 / 1024:.1f} MB/s')
        text = T('eta_left', size=prefix + size, time=_fmt_duration(est['bytes'] / speed),
                 speed=speed_text,
                 how=T('eta_at_limit') if est['limited'] else T('eta_at_current'))
        if est['unknown']:
            text += ' ' + T('eta_plus_unknown', n=est['unknown'])
        return text

    def _autosave_downloads(self, items: list[DownloadItem]):
        self._download_autosave_ticks += 1
        if self._download_autosave_ticks < 10:
            return
        self._download_autosave_ticks = 0
        sig = tuple((
            i.url, i.name, i.state, i.progress, i.dest,
            i.resolution,
            i.filename_template, i.error, i.error_code,
            i.retry_count, i.not_before,
        ) for i in items)
        if sig == self._last_download_save_sig:
            return
        try:
            self._dlmgr.save_csv(CSV_PATH)
            self._last_download_save_sig = sig
        except Exception:
            pass

    DL_ROW_HEIGHT = 92          # one row plus the gap under it

    def _make_dl_row(self) -> dict:
        """Build one empty row for the pool.

        The row is not tied to a download: every button asks the row which
        address it is showing right now, so the same widgets can be moved to
        whatever is on screen.
        """
        w: dict = {'url': ''}
        row = ctk.CTkFrame(
            self._dl_viewport, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD, height=self.DL_ROW_HEIGHT - 16)
        row.pack_propagate(False)

        # Waiting-queue position: ▲ / number (click to type) / ▼
        queue_box = ctk.CTkFrame(row, fg_color='transparent', width=40)
        queue_box.pack(side='left', fill='y', padx=(8, 0), pady=4)
        queue_box.pack_propagate(False)
        q_up = ctk.CTkButton(
            queue_box, text='▲', width=30, height=18, corner_radius=4,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 9),
            command=lambda: self._queue_step(w['url'], -1))
        q_num = ctk.CTkLabel(
            queue_box, text='', width=30, height=22, corner_radius=4,
            fg_color=BG_BADGE, text_color=TEXT_PRI, cursor='hand2',
            font=('Consolas', 11, 'bold'))
        q_num.bind('<Button-1>', lambda _e: self._queue_edit_position(w['url']))
        q_down = ctk.CTkButton(
            queue_box, text='▼', width=30, height=18, corner_radius=4,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 9),
            command=lambda: self._queue_step(w['url'], +1))

        state_holder = ctk.CTkFrame(
            row, width=92, height=32, corner_radius=6, fg_color=BG_BADGE)
        state_holder.pack(side='left', padx=(14, 10))
        state_holder.pack_propagate(False)
        state_lbl = ctk.CTkLabel(
            state_holder, text='—', text_color=TEXT_SEC,
            font=(ui_font(), 10, 'bold'))
        state_lbl.pack(fill='both', expand=True, padx=6)

        thumb_holder = ctk.CTkFrame(
            row, width=88, height=50, corner_radius=6, fg_color=BG_SIDEBAR)
        thumb_holder.pack(side='left', padx=(0, 10), pady=10)
        thumb_holder.pack_propagate(False)
        thumb_lbl = ctk.CTkLabel(
            thumb_holder, text='', text_color=TEXT_DIM, font=(ui_font(), 8))
        thumb_lbl.pack(fill='both', expand=True)

        remove_btn = ctk.CTkButton(
            row, text='✕', width=32, height=32, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_DIM,
            font=('Consolas', 12),
            command=lambda: self._dlmgr.remove_item(w['url']))
        remove_btn.pack(side='right', padx=(6, 14))

        link_btn = ctk.CTkButton(
            row, text='🔗', width=32, height=32, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=(ui_font(), 11),
            command=lambda: self._open_item_page(w['url']))
        link_btn.pack(side='right', padx=(2, 0))

        folder_btn = ctk.CTkButton(
            row, text='▣', width=32, height=32, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=('Consolas', 11),
            command=lambda: self._open_item_folder(w['url']))
        folder_btn.pack(side='right', padx=(2, 0))

        retry_btn = ctk.CTkButton(
            row, text='', width=82, height=32, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=ACCENT,
            font=(ui_font(), 10, 'bold'),
            command=lambda: self._handle_download_action(w['url']))

        metrics = ctk.CTkFrame(row, fg_color='transparent')
        metrics.pack(side='right', padx=(6, 2))
        pb = ctk.CTkProgressBar(metrics, width=150, height=8, corner_radius=5,
                                fg_color=BG_INPUT, progress_color=ACCENT)
        pb.set(0)
        pct_lbl = ctk.CTkLabel(metrics, text='', text_color=TEXT_SEC,
                               font=('Consolas', 10, 'bold'), width=46)
        spd_lbl = ctk.CTkLabel(metrics, text='', text_color=TEXT_SEC,
                               font=('Consolas', 9), width=76)

        text_stack = ctk.CTkFrame(row, fg_color='transparent')
        text_stack.pack(side='left', fill='both', expand=True,
                        padx=(0, 10), pady=10)
        name_lbl = ctk.CTkLabel(text_stack, text='', text_color=TEXT_PRI,
                                font=(ui_font(), 11, 'bold'), anchor='w')
        name_lbl.pack(fill='x', anchor='w')
        detail_lbl = ctk.CTkLabel(text_stack, text='', text_color=TEXT_DIM,
                                  font=('Consolas', 9), anchor='w',
                                  cursor='hand2')
        detail_lbl.pack(fill='x', anchor='w', pady=(3, 0))
        detail_lbl.bind('<Button-1>',
                        lambda _e: self._copy_job_diagnostics(w['url']))

        w.update({
            'row': row, 'state_holder': state_holder, 'state_lbl': state_lbl,
            'name_lbl': name_lbl, 'detail_lbl': detail_lbl, 'metrics': metrics,
            'pb': pb, 'pct_lbl': pct_lbl, 'spd_lbl': spd_lbl,
            'retry_btn': retry_btn, '_before_remove': remove_btn,
            'folder_btn': folder_btn, 'thumb_lbl': thumb_lbl,
            'pb_visible': False, 'pct_visible': False, 'spd_visible': False,
            'retry_visible': False, 'last_retry_action': None,
            'last_state': None, 'last_name': None, 'last_detail': None,
            'last_progress': -1, 'last_speed': None, 'last_thumbnail': None,
            'queue_box': queue_box, 'q_up': q_up, 'q_num': q_num,
            'q_down': q_down, 'q_visible': False, 'last_q': None,
            'q_editor': None, '_placed': None, '_width': None,
        })
        self._dl_bind_wheel(row)
        return w

    def _dl_bind_wheel(self, widget):
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            tk.Misc.bind(widget, seq, self._dl_on_wheel, add='+')
        for child in widget.winfo_children():
            self._dl_bind_wheel(child)

    def _bind_dl_row(self, w: dict, item: DownloadItem):
        """Show ``item`` in a pooled row, forgetting whatever was there."""
        if w['url'] != item.url:
            w.update({'url': item.url, 'last_state': None, 'last_name': None,
                      'last_detail': None, 'last_progress': -1,
                      'last_speed': None, 'last_thumbnail': None,
                      'last_q': None, 'last_retry_action': None})
            if w.get('q_editor') is not None:
                try:
                    w['q_editor'].destroy()
                    w['q_num'].pack(side='top', pady=1, after=w['q_up'])
                except tk.TclError:
                    pass
                w['q_editor'] = None
            try:
                w['thumb_lbl'].configure(image=None, text='')
            except tk.TclError:
                pass
        self._update_dl_row(w, item)

    # ── scrolling ───────────────────────────────────────────────────
    def _dl_visible_count(self):
        height = max(1, self._dl_viewport.winfo_height())
        return max(1, height // self.DL_ROW_HEIGHT)

    def _dl_on_resize(self):
        needed = max(1, -(-max(1, self._dl_viewport.winfo_height())
                          // self.DL_ROW_HEIGHT)) + 1
        while len(self._dl_pool) < needed:
            try:
                self._dl_pool.append(self._make_dl_row())
            except Exception as exc:
                print(f'[download row build failed] {exc}', flush=True)
                break
        self._render_downloads()

    def _dl_on_wheel(self, event):
        if getattr(event, 'num', None) == 4:
            step = -1
        elif getattr(event, 'num', None) == 5:
            step = 1
        else:
            delta = getattr(event, 'delta', 0)
            if not delta:
                return 'break'
            step = -1 if delta > 0 else 1
            if abs(delta) >= 240:
                step *= max(1, abs(delta) // 120)
        from siphon.ui import scroll as _scroll
        speed = _scroll._cache.get('speed')
        if speed is None:
            speed = _scroll._cache['speed'] = _scroll.get_speed()
        rows = max(1, round(speed / 4))
        self._dl_scroll_to(self._dl_first + step * rows)
        return 'break'

    def _dl_on_scrollbar(self, *args):
        total = len(self._dl_view_items)
        if not total or not args:
            return
        if args[0] == 'moveto':
            self._dl_scroll_to(int(round(float(args[1]) * total)))
        elif args[0] == 'scroll':
            amount = int(args[1])
            unit = (self._dl_visible_count()
                    if len(args) > 2 and args[2] == 'pages' else 1)
            self._dl_scroll_to(self._dl_first + amount * unit)

    def _dl_scroll_to(self, first):
        limit = max(0, len(self._dl_view_items) - self._dl_visible_count())
        first = max(0, min(int(first), limit))
        if first != self._dl_first:
            self._dl_first = first
            self._render_downloads(self._dl_view_items)

    def _render_downloads(self, items=None):
        """Place the pooled rows over the visible slice of the list."""
        if getattr(self, '_dl_viewport', None) is None:
            return
        if items is not None:
            self._dl_view_items = items
        items = self._dl_view_items
        total = len(items)
        visible = self._dl_visible_count()
        self._dl_first = max(0, min(self._dl_first, max(0, total - visible)))
        try:
            if total:
                self._dl_empty_lbl.place_forget()
            else:
                self._dl_empty_lbl.configure(
                    text=(T('queue_filter_empty')
                          if self._dlmgr.get_items() else T('dl_list_empty')))
                self._dl_empty_lbl.place(relx=0.5, y=40, anchor='n')
            width = max(1, self._dl_viewport.winfo_width())
            placed = {}
            for slot, w in enumerate(self._dl_pool):
                index = self._dl_first + slot
                if index < total:
                    item = items[index]
                    self._bind_dl_row(w, item)
                    placed[item.url] = w
                    if w['_width'] != width:
                        w['row'].configure(width=width - 24,
                                           height=self.DL_ROW_HEIGHT - 16)
                        w['_width'] = width
                    if w['_placed'] != slot:
                        w['row'].place(x=12, y=slot * self.DL_ROW_HEIGHT + 8)
                        w['_placed'] = slot
                elif w['_placed'] is not None:
                    w['row'].place_forget()
                    w['_placed'] = None
                    w['url'] = ''
            self._dl_rows = placed
            if total:
                self._dl_scrollbar.set(
                    self._dl_first / total,
                    min(1.0, (self._dl_first + visible) / total))
            else:
                self._dl_scrollbar.set(0, 1)
            # No bar at all while everything fits: a full-height track next to
            # three downloads only suggests there is more to scroll to.
            self._dl_show_scrollbar(total > visible)
        except tk.TclError:
            pass

    def _dl_show_scrollbar(self, wanted: bool):
        if bool(getattr(self, '_dl_scrollbar_shown', True)) == bool(wanted):
            return
        self._dl_scrollbar_shown = bool(wanted)
        try:
            if wanted:
                self._dl_scrollbar.pack(side='right', fill='y',
                                        padx=(0, 4), pady=4,
                                        before=self._dl_viewport)
            else:
                self._dl_scrollbar.pack_forget()
        except tk.TclError:
            pass

    def _update_queue_box(self, w: dict, item: DownloadItem):
        """The ▲ n ▼ box: only a row waiting its turn has a position."""
        pos = (getattr(self, '_queue_pos', {}) or {}).get(item.url)
        show = pos is not None
        if show != w['q_visible']:
            try:
                if show:
                    w['q_up'].pack(side='top', pady=1)
                    w['q_num'].pack(side='top', pady=1, after=w['q_up'])
                    w['q_down'].pack(side='top', pady=1)
                else:
                    for key in ('q_up', 'q_num', 'q_down'):
                        w[key].pack_forget()
            except tk.TclError:
                return
            w['q_visible'] = show
        if show and w['last_q'] != pos and w.get('q_editor') is None:
            try:
                w['q_num'].configure(text=str(pos))
            except tk.TclError:
                return
            w['last_q'] = pos

    def _update_dl_row(self, w: dict, item: DownloadItem):
        """Update an existing row's fields in place without rebuilding widgets."""
        self._update_queue_box(w, item)
        if item.thumbnail and w['last_thumbnail'] != item.thumbnail:
            w['last_thumbnail'] = item.thumbnail
            self._load_download_thumb_async(
                item.thumbnail, w, item.url, self._build_gen, item.site)
        # State text + color
        if w['last_state'] != item.state:
            color = self._STATE_COLORS.get(item.state, TEXT_SEC)
            try:
                w['state_holder'].configure(
                    fg_color=self._STATE_BACKGROUNDS.get(item.state, BG_BADGE),
                    width=92)
                w['state_lbl'].configure(
                    text=state_label(item.state) if item.state else '—',
                    text_color=color)
            except Exception:
                return
            w['last_state'] = item.state

        # Name and supporting detail (error or source URL) are separate levels.
        display_name = item.name or item.url
        resolution = item.resolution or config.get_resolution_pref()
        detail = T(
            'job_details', site=item.site or site_name(item.url),
            code=video_code(item.url, display_name), resolution=resolution)
        detail_color = TEXT_DIM
        if item.state == '已存在' and item.error:
            detail, detail_color = item.error, SUCCESS
        elif item.error and item.state in (
                '未完成', '封鎖/解析失敗', '已下載', '下載中'):
            if item.error == ERR_BLOCKED:
                err_text = T('blocked_vpn_hint')
            elif item.error_code:
                err_text = T(f'problem_{item.error_code}')
                if item.error and item.error not in err_text:
                    err_text = f'{err_text} · {item.error}'
            else:
                err_text = item.error
            err = err_text.replace('\n', ' ').strip()
            if len(err) > 110:
                err = err[:107] + '...'
            detail = err
            detail_color = WARNING if item.state in ('已下載', '下載中') else ERROR_C
        if w['last_name'] != display_name:
            try:
                w['name_lbl'].configure(text=display_name)
            except Exception:
                return
            w['last_name'] = display_name
        if w['last_detail'] != detail:
            try:
                w['detail_lbl'].configure(text=detail, text_color=detail_color)
            except Exception:
                return
            w['last_detail'] = detail

        retry_action = _download_row_action(item)
        if w['last_retry_action'] != retry_action:
            if retry_action:
                labels = {
                    'pause': 'pause_short',
                    'resume': 'resume_short',
                    'retry': 'retry_short',
                    'force': 'download_anyway',
                }
                label = T(labels.get(retry_action, 'retry_short'))
                try:
                    w['retry_btn'].configure(text=f'↻ {label}')
                except Exception:
                    return
            w['last_retry_action'] = retry_action
        if retry_action and not w['retry_visible']:
            w['retry_btn'].pack(side='right', padx=(2, 0), before=w['_before_remove'])
            w['retry_visible'] = True
        elif not retry_action and w['retry_visible']:
            try:
                w['retry_btn'].pack_forget()
            except Exception:
                pass
            w['retry_visible'] = False

        # Progress bar: show only while downloading
        # '下載中' keeps the bar visible even at 0% (e.g. a direct MP4 that
        # just restarted on a single connection) so the row never looks idle.
        is_downloading = item.state == '下載中'
        is_stopped_partial = (
            item.state in _KEEP_PROGRESS_STATES and item.progress > 0)
        if is_downloading or is_stopped_partial:
            if not w['pb_visible']:
                w['pb'].pack(side='left', padx=(0, 4))
                w['pb_visible'] = True
            if w['last_progress'] != item.progress:
                w['pb'].set(max(0.0, min(1.0, item.progress / 100)))
                w['last_progress'] = item.progress
            pct_text = f'{item.progress}%'
            if not w['pct_visible']:
                w['pct_lbl'].pack(side='left')
                w['pct_visible'] = True
            if w['pct_lbl'].cget('text') != pct_text:
                w['pct_lbl'].configure(text=pct_text)
        else:
            if w['pb_visible']:
                try: w['pb'].pack_forget()
                except Exception: pass
                w['pb_visible'] = False
            if w['pct_visible']:
                try: w['pct_lbl'].pack_forget()
                except Exception: pass
                w['pct_visible'] = False

        # Speed (or, for a paused/stopped item, just how much is downloaded)
        if (is_downloading and (item.speed or item.eta)) or (
                is_stopped_partial and item.size_text):
            if not w['spd_visible']:
                w['spd_lbl'].pack(side='left', padx=4)
                w['spd_visible'] = True
            if is_downloading:
                metric = ' · '.join(
                    part for part in (item.size_text, item.speed) if part)
            else:
                metric = item.size_text
            if is_downloading and item.eta:
                metric = f'{metric} · {T("eta_label", eta=item.eta)}'.strip(' ·')
            if w['last_speed'] != metric:
                w['spd_lbl'].configure(text=metric, width=300)
                w['last_speed'] = metric
        else:
            if w['spd_visible']:
                try: w['spd_lbl'].pack_forget()
                except Exception: pass
                w['spd_visible'] = False
                w['last_speed'] = None

    def _load_download_thumb_async(
            self, url: str, w: dict, for_url: str, build_gen: int,
            site_key: str = ''):
        def _worker():
            image = _fetch_thumbnail(url, site_key)
            if image is None:
                return

            def _apply():
                if self._is_closing or build_gen != self._build_gen:
                    return
                # The row is shared: while this picture was downloading it may
                # have been scrolled onto a different video.
                if w['url'] != for_url:
                    return
                label = w['thumb_lbl']
                try:
                    if not label.winfo_exists():
                        return
                    ctk_image = ctk.CTkImage(
                        light_image=image, dark_image=image, size=(80, 45))
                    label.configure(image=ctk_image, text='')
                    label._ctk_img_ref = ctk_image
                except Exception:
                    pass

            self._ui(_apply, gen=build_gen)

        try:
            self._thumb_executor.submit(_worker)
        except RuntimeError:
            pass

    def _copy_job_diagnostics(self, url: str):
        item = next((candidate for candidate in self._dlmgr.get_items()
                     if candidate.url == url), None)
        if item is None:
            return
        details = {
            'job_id': item.job_id,
            'site': item.site,
            'code': video_code(item.url, item.name),
            'state': state_label(item.state),
            'progress': item.progress,
            'url': item.url,
            'destination': item.dest,
            'resolution': item.resolution,
            'filename_template': item.filename_template,
            'error_code': item.error_code,
            'error': item.error,
            'retry_count': item.retry_count,
        }
        try:
            self.clipboard_clear()
            self.clipboard_append(json.dumps(
                details, ensure_ascii=False, indent=2))
            self._status_lbl.configure(text=T('copy_diagnostics'))
        except tk.TclError:
            pass

    def _open_item_page(self, url):
        """Open the video's page (where it was downloaded from) in the browser."""
        item = self._dlmgr._items.get(url)
        if item is not None and getattr(item, 'local', False):
            self._open_item_folder(url)      # local files have no web page
            return
        if str(url).startswith(('http://', 'https://')):
            webbrowser.open(url)

    def _open_item_folder(self, url: str):
        item = next((candidate for candidate in self._dlmgr.get_items()
                     if candidate.url == url), None)
        if item is None:
            return
        path = _find_item_file(item, getattr(self._dlmgr, 'finished_paths', {}).get(url),
                               self._dest_var.get() or 'download')
        if path and _reveal_in_explorer(path):
            return
        current = self._dest_var.get()
        try:
            self._dest_var.set(item.dest or current)
            self._open_dest_folder()
        finally:
            self._dest_var.set(current)

    # ── Clipboard monitor (main-thread safe) ─────────────────────────
    def _clipboard_poll(self):
        if self._is_closing:
            return
        if self._rebuilding:
            try:
                self.after(800, self._clipboard_poll)
            except tk.TclError:
                pass
            return
        try:
            clp = self.clipboard_get()
            if clp != self._clp_text:
                self._clp_text = clp
                urls = extract_urls(clp)
                if urls and getattr(self, '_dl_url_var', None) is not None:
                    # Clipboard monitoring is a convenience hint only.  It no
                    # longer mutates the persistent queue without a click.
                    self._dl_url_var.set(urls[0])
        except (tk.TclError, Exception):
            pass
        finally:
            if not self._is_closing:
                try:
                    self.after(800, self._clipboard_poll)
                except tk.TclError:
                    pass

    # ── Close ────────────────────────────────────────────────────────
    def _on_close(self):
        self._is_closing = True
        try:
            self._upmgr.close()
        except Exception:
            pass
        if not getattr(self, '_startup_complete', True):
            self._close_requested = True
            return
        try:
            self._thumb_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self._save_resume_list()
        except Exception as exc:
            print(f'[resume] could not save the running queue: {exc}', flush=True)
        try:
            with self._dlmgr._lock:
                for item in self._dlmgr._items.values():
                    if item.state in (
                            '準備中', '下載中', '等待中', '等待重試',
                            '已排程'):
                        item.state = '未完成'
                        item.speed = ''
                self._dlmgr.save_csv(CSV_PATH)
        except Exception:
            pass
        self._dlmgr.cancel_all(cleanup=False)
        self.destroy()


def gui_modern_main(url: str = '', dest: str = 'download', lang: str = 'en'):
    _crumb("gui_modern_main: constructing ModernApp")
    app = ModernApp(url=url, dest=dest, lang=lang)
    _crumb("gui_modern_main: app constructed, entering mainloop")
    try:
        if not app._is_closing:
            app.mainloop()
    except tk.TclError:
        # CTk.mainloop calls update() while styling the Windows titlebar.
        # A legitimate close handled during that update destroys the root.
        if not app._is_closing:
            raise
    _crumb("gui_modern_main: mainloop returned (normal exit)")
