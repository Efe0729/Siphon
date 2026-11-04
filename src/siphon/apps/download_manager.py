"""The download queue: what each download is, and how many run at once.

No window code lives here, so it can be tested and reasoned about alone."""

import collections
import csv
import io
import os
import re
import threading
import time
import uuid

from siphon import sites as M3U8Sites
from siphon.apps.downloads import (
    ACTIVE_STATES,
    DONE_STATES,
    PAUSED_STATES,
    QUEUED_STATES,
    classify_download_problem,
    format_eta,
    site_name)
from siphon.core import config, dl_history, secretstore
from siphon.core.secretstore import SecretError
from siphon.core.storage import StorageWriteError
from siphon.i18n.locales import T
from siphon.sites.base import MirrorsBlockedError
from siphon.apps.app_basics import (
    DEFAULT_CONCURRENT,
    ERR_BLOCKED,
    HARD_LOAD_LIMIT,
    MAX_CONCURRENT,
    MAX_PERSIST_ROWS,
    SLOW_REQUEUE_GRACE_SECONDS,
    SLOW_REQUEUE_MAX_ATTEMPTS,
    _KEEP_PROGRESS_STATES,
    _download_size_text,
    _fallback_name,
    _select_persist)

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
        # Downloads the user resumed while the paused worker was still
        # winding down: url -> destination.  The new one starts the moment the
        # old worker lets go of the files, not never.
        self._resume_when_free: dict[str, str] = {}
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
                # even though the current result has a useful title.
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
            self._resume_when_free.pop(url, None)
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
            old = self._active.get(url)
            if old is not None and old.cancelled.is_set():
                # Paused a moment ago, and the old worker has not finished
                # stopping.  Asking for a new one now was answered with
                # "already running" and silence.
                self._resume_when_free[url] = dest or item_dest
                self._set_state(url, '等待中', progress=0, error='')
                return True
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
            self._resume_when_free.clear()
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
            print(f'[Download failed] {url}\n  {exc}', flush=True)
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
            elif (task.url in self._resume_when_free
                  and task.epoch == self._cancel_epoch
                  and task.url in self._items):
                again = self._resume_when_free.pop(task.url)
                item = self._items[task.url]
                item.dest = again or item.dest
                item.auto_requeues = 0
                item.retry_count = 0
                self._pending.insert(0, _DownloadTask(
                    task.url, item.dest, self._cancel_epoch,
                    resolution=item.resolution,
                    filename_template=item.filename_template))
                self._set_state(task.url, '等待中', progress=0, error='')
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
        from siphon.core import eta
        # What is really arriving, not the ceiling the limit sets.  Each
        # download's figure is already averaged over a few seconds and is the
        # very number its row shows, so the total here agrees with the rows
        # instead of lagging behind them.
        speed, limited = eta.pick(speed, speed_limiter.limit_bps)
        return {'bytes': remaining, 'estimated': estimated,
                'videos': len(active) + pending, 'unknown': unknown,
                'speed': speed, 'limited': limited}

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)
