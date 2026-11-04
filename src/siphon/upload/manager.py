"""Upload queue: runs one rclone transfer at a time in a background thread."""

from __future__ import annotations

import os
import threading
import time
import uuid

from siphon.core import config
from siphon.upload import rclone

WAITING, UPLOADING, DONE, FAILED, CANCELLED, PAUSED, SKIPPED = (
    'waiting', 'uploading', 'done', 'failed', 'cancelled', 'paused', 'skipped')
FINISHED = frozenset({DONE, FAILED, CANCELLED, SKIPPED})


# ── Settings (stored in the app's ui_prefs.json) ─────────────────────────
_prefs_cache = {'at': 0.0, 'data': {}}


def _get(key, default):
    # Settings are read often (every worker, every second); re-reading the
    # file each time stalls the window, so keep them for a few seconds.
    now = time.monotonic()
    if now - _prefs_cache['at'] > 3.0:
        _prefs_cache['data'] = config._load_prefs()
        _prefs_cache['at'] = now
    return _prefs_cache['data'].get(key, default)


def _set(key, value):
    with config._prefs_lock:
        prefs = config._load_prefs()
        prefs[key] = value
        config._save_prefs(prefs)
    _prefs_cache['at'] = 0.0
    return value


def get_remote():
    return str(_get('upload_remote', '') or '')


def set_remote(name):
    return _set('upload_remote', str(name or ''))


def get_folder():
    return str(_get('upload_folder', 'Siphon') or '').strip('/')


def set_folder(folder):
    return _set('upload_folder', str(folder or '').replace('\\', '/').strip('/'))


def get_auto_upload():
    return bool(_get('auto_upload', False))


def set_auto_upload(value):
    return _set('auto_upload', bool(value))


EXISTING_MODES = ('skip', 'replace')


def get_existing_mode():
    """'skip': a file already in the cloud folder (same name) is not uploaded.
    'replace': same file is skipped, a different one with that name is replaced."""
    mode = str(_get('upload_existing', 'skip'))
    return mode if mode in EXISTING_MODES else 'skip'


def set_existing_mode(mode):
    return _set('upload_existing', mode if mode in EXISTING_MODES else 'skip')


MAX_PARALLEL = 4


def get_parallel():
    """How many files upload at the same time (1–4)."""
    try:
        return max(1, min(MAX_PARALLEL, int(_get('upload_parallel', 1))))
    except (TypeError, ValueError):
        return 1


def set_parallel(value):
    return _set('upload_parallel', max(1, min(MAX_PARALLEL, int(value or 1))))


def get_last_pick():
    """Cloud folder chosen for the last manual upload (picker start point)."""
    return str(_get('upload_last_pick', get_folder()) or '')


def set_last_pick(folder):
    return _set('upload_last_pick', str(folder or '').replace('\\', '/').strip('/'))


def get_bwlimit_bps():
    try:
        return max(0, int(_get('upload_bwlimit_bps', 0) or 0))
    except (TypeError, ValueError):
        return 0


def set_bwlimit_bps(value):
    return _set('upload_bwlimit_bps', max(0, int(value or 0)))


def get_delete_after():
    return bool(_get('upload_delete_after', False))


def set_delete_after(value):
    return _set('upload_delete_after', bool(value))


# ── Jobs ─────────────────────────────────────────────────────────────────
class UploadJob:
    def __init__(self, name, source_dir, files, destination, move, auto=False):
        self.id = uuid.uuid4().hex
        self.name = name
        self.source_dir = source_dir
        self.files = list(files or [])
        self.destination = destination
        self.move = move
        self.auto = auto
        self.state = WAITING
        self.progress = 0
        self.done_bytes = 0
        self.total_bytes = 0
        # rclone re-sends the whole file when an attempt fails and keeps
        # adding to its byte counters; these track the current attempt only.
        self.attempt = 1
        self.max_attempts = rclone.RETRIES
        self.retry_reason = ''
        self._base_bytes = 0
        self._last_total = 0
        self._rebase = False
        self._samples = []   # (time, bytes) of the last few seconds
        self.speed = 0.0
        self.eta = None
        self.error = ''
        self.created_at = time.time()
        self.batch = 0   # set by the manager: jobs added in one request
        self.seq = 0
        self.size_bytes = _local_size(source_dir, self.files)
        self.file_count = len(self.files) if self.files else _count_files(source_dir)
        self.started_at = None
        self.finished_at = None
        self.paused_total = 0.0      # seconds spent paused while uploading
        self._paused_since = None
        self.restart_note = 0        # % reached before an app restart
        self.resent_bytes = 0        # sent again after dropped connections
        self.done_bytes_shown = 0
        self._proc = None
        self._cancel = False


def _local_size(folder, files):
    total = 0
    try:
        if files:
            for name in files:
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    total += os.path.getsize(path)
        elif folder and os.path.isdir(folder):
            for root, _dirs, names in os.walk(folder):
                for name in names:
                    try:
                        total += os.path.getsize(os.path.join(root, name))
                    except OSError:
                        pass
    except OSError:
        pass
    return total


def _count_files(folder):
    try:
        return sum(len(names) for _r, _d, names in os.walk(folder)) if folder else 0
    except OSError:
        return 0


def elapsed_seconds(job):
    """Active upload time (pauses excluded)."""
    if not job.started_at:
        return 0.0
    end = job.finished_at or time.time()
    paused = job.paused_total
    if job._paused_since:
        paused += time.time() - job._paused_since
    return max(0.0, end - job.started_at - paused)


def _sidecar_files(video_path):
    """The video plus files that share its name: subtitles (.ja.srt …) and thumbnail."""
    folder, base = os.path.split(os.path.abspath(video_path))
    stem = os.path.splitext(base)[0]
    names = []
    try:
        for entry in os.listdir(folder):
            if entry == base:
                continue
            if entry.endswith('.part') or entry.endswith('.tmp'):
                continue
            if entry.startswith(stem + '.') and os.path.isfile(os.path.join(folder, entry)):
                names.append(entry)
    except OSError:
        pass
    return folder, [base] + sorted(names)


class UploadManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._jobs: list[UploadJob] = []
        self._wake = threading.Event()
        self._worker = None
        self._workers = []
        self._closed = False
        self.version = 0  # bumps on every change so the UI knows to redraw
        self._seq = 0
        self._batch = 0
        self._persist_path = None
        self._saved_version = -1

    # saving the queue between app runs -------------------------------------
    _FIELDS = ('id', 'name', 'source_dir', 'files', 'destination', 'move', 'auto',
               'state', 'progress', 'done_bytes', 'total_bytes', 'size_bytes',
               'file_count', 'started_at', 'finished_at', 'paused_total', 'error',
               'batch', 'seq', 'created_at', 'restart_note')
    HISTORY_KEEP = 200

    def restore(self, path):
        """Load the upload list saved by the last run and keep saving it.
        Unfinished uploads go back into the queue (in their old order) and
        start automatically; finished ones are shown as history."""
        import json
        self._persist_path = path
        try:
            from siphon.core import secretstore
            text = secretstore.read_text(path)
            data = json.loads(text) if text.strip() else {}
        except Exception:
            data = {}
        restored = 0
        with self._lock:
            for entry in data.get('jobs', []) if isinstance(data, dict) else []:
                try:
                    job = UploadJob.__new__(UploadJob)
                    UploadJob.__init__(job, entry['name'], entry['source_dir'],
                                       entry.get('files') or None, entry['destination'],
                                       bool(entry.get('move')), bool(entry.get('auto')))
                    for key in self._FIELDS:
                        if key in entry and key not in ('files',):
                            setattr(job, key, entry[key])
                except (KeyError, TypeError):
                    continue
                if job.state in (UPLOADING, WAITING):
                    missing = [n for n in (job.files or []) if not os.path.isfile(
                        os.path.join(job.source_dir, n))] if job.files else (
                        [] if os.path.isdir(job.source_dir) else [job.source_dir])
                    if missing:
                        job.state, job.error = FAILED, 'local file not found: ' + missing[0]
                    else:
                        if entry.get('state') == UPLOADING and job.progress:
                            job.restart_note = job.progress
                        job.state = WAITING
                        restored += 1
                    job.progress, job.done_bytes = 0, 0
                    job.started_at = job.finished_at = None
                    job.paused_total = 0.0
                elif job.state == PAUSED:
                    # A frozen transfer did not survive the restart: it waits
                    # (paused) for Resume and then starts that file again.
                    if job.started_at and job.progress:
                        job.restart_note = job.progress
                    job.progress, job.done_bytes = 0, 0
                    job.started_at = job.finished_at = None
                    job.paused_total = 0.0
                self._jobs.append(job)
                self._seq = max(self._seq, int(job.seq or 0))
                self._batch = max(self._batch, int(job.batch or 0))
            self._touch()
            if restored:
                self._ensure_worker()
        if restored:
            print(f'[Upload] {restored} upload(s) from the last session continue', flush=True)
            self._wake.set()
        threading.Thread(target=self._save_loop, daemon=True).start()
        return restored

    def _snapshot(self, closing=False):
        with self._lock:
            jobs = list(self._jobs)
        live = [j for j in jobs if j.state not in FINISHED]
        done = sorted((j for j in jobs if j.state in FINISHED),
                      key=lambda j: j.finished_at or 0)[-self.HISTORY_KEEP:]
        out = []
        for job in live + done:
            entry = {k: getattr(job, k, None) for k in self._FIELDS}
            if closing and job.state == UPLOADING:
                entry['state'] = UPLOADING   # restored as "restart this file"
            out.append(entry)
        return {'version': 1, 'jobs': out}

    def save(self, closing=False):
        path = self._persist_path
        if not path:
            return
        import json
        data = self._snapshot(closing)
        tmp = f'{path}.{uuid.uuid4().hex[:6]}.tmp'
        try:
            from siphon.core import secretstore
            secretstore.write_text(path, json.dumps(data, ensure_ascii=False))
        except OSError as exc:
            print(f'[Upload] could not save the upload list: {exc}', flush=True)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _save_loop(self):
        while not self._closed:
            time.sleep(2)
            if self._closed:
                break
            if self.version != self._saved_version:
                self._saved_version = self.version
                self.save()

    # public API -----------------------------------------------------------
    def jobs(self):
        with self._lock:
            return list(self._jobs)

    def destination(self, remote=None, folder=None):
        remote = remote if remote is not None else get_remote()
        folder = folder if folder is not None else get_folder()
        if not remote:
            raise rclone.RcloneError('no cloud account selected')
        return remote, folder

    def add_folder(self, local_folder, remote=None, folder=None, move=None,
                   keep_folder_name=False):
        """Upload what is inside local_folder (files and sub-folders) straight
        into the cloud folder.  keep_folder_name=True would instead create a
        cloud folder with the same name and put the contents in it."""
        self._new_batch()
        remote, folder = self.destination(remote, folder)
        local_folder = os.path.abspath(local_folder)
        name = os.path.basename(local_folder.rstrip('\\/')) or local_folder
        if keep_folder_name:
            folder = f'{folder}/{name}' if folder else name
        target = rclone.remote_path(remote, folder)
        return self._add(UploadJob(
            name, local_folder, None, target,
            get_delete_after() if move is None else move))

    def add_folder_files(self, local_folder, remote=None, folder=None, move=None):
        """One upload row per file inside local_folder (sub-folders included;
        their structure is kept under the cloud folder)."""
        self._new_batch()
        remote, folder = self.destination(remote, folder)
        local_folder = os.path.abspath(local_folder)
        move = get_delete_after() if move is None else move
        jobs = []
        for root, dirs, files in os.walk(local_folder):
            dirs.sort(key=str.casefold)
            rel = os.path.relpath(root, local_folder).replace('\\', '/')
            sub = '' if rel in ('.', '') else rel
            cloud = '/'.join(p for p in (folder.strip('/'), sub) if p)
            target = rclone.remote_path(remote, cloud)
            for name in sorted(files, key=str.casefold):
                if name.endswith(('.part', '.tmp')) or name.endswith('.state.json'):
                    continue
                label = f'{sub}/{name}' if sub else name
                jobs.append(self._add(UploadJob(label, root, [name], target, move)))
        return jobs

    def add_files(self, paths, remote=None, folder=None, move=None, auto=False):
        """One upload row per selected file, so each shows its own progress."""
        self._new_batch()
        remote, folder = self.destination(remote, folder)
        target = rclone.remote_path(remote, folder)
        move = get_delete_after() if move is None else move
        jobs = []
        for path in paths:
            path = os.path.abspath(path)
            name = os.path.basename(path)
            jobs.append(self._add(UploadJob(
                name, os.path.dirname(path), [name], target, move, auto=auto)))
        return jobs

    def add_downloaded_video(self, video_path):
        """Called when a download finishes; honours the auto-upload switch."""
        self._new_batch()
        if not get_auto_upload() or not get_remote():
            return None
        if not os.path.isfile(video_path):
            return None
        src_dir, names = _sidecar_files(video_path)
        remote, folder = self.destination()
        label = names[0]
        return self._add(UploadJob(
            label, src_dir, names, rclone.remote_path(remote, folder),
            get_delete_after(), auto=True))

    def cancel(self, job_id):
        with self._lock:
            for job in self._jobs:
                if job.id == job_id and job.state not in FINISHED:
                    job._cancel = True
                    if job.state == WAITING or (job.state == PAUSED and job._proc is None):
                        job.state = CANCELLED
                        job.finished_at = time.time()
                    proc = job._proc
                    break
            else:
                return
            self._touch()
        if proc is not None:
            _terminate(proc)

    def pause(self, job_id):
        """Pause: a waiting upload is skipped until resumed; a running one is
        frozen in place (its progress is kept)."""
        with self._lock:
            job = next((j for j in self._jobs if j.id == job_id), None)
            if job is None:
                return False
            if job.state == WAITING:
                job.state = PAUSED
                self._touch()
                return True
            if job.state != UPLOADING or job._proc is None:
                return False
            proc = job._proc
        if not rclone.suspend_process(proc):
            return False
        with self._lock:
            job.state = PAUSED
            job._paused_since = time.time()
            job.speed, job.eta = 0.0, None
            job._samples.clear()
            self._touch()
        self._wake.set()          # a paused upload frees its slot for the next one
        self._apply_limits()
        print(f'[Upload] Paused: {job.name} at {job.progress}%', flush=True)
        return True

    def resume(self, job_id):
        with self._lock:
            job = next((j for j in self._jobs if j.id == job_id), None)
            if job is None or job.state != PAUSED:
                return False
            proc = job._proc
            if proc is None:
                job.state = WAITING
                self._touch()
                self._ensure_worker()
                self._wake.set()
                return True
        if not rclone.resume_process(proc):
            return False
        with self._lock:
            if job._paused_since:
                job.paused_total += time.time() - job._paused_since
            job._paused_since = None
            job.state = UPLOADING
            self._touch()
        # A limit changed while frozen could not reach rclone; share it now.
        self._apply_limits()
        print(f'[Upload] Resumed: {job.name}', flush=True)
        return True

    def queue_ids(self):
        """Ids of uploads waiting to start, in the order they will run."""
        with self._lock:
            return [j.id for j in self._jobs if j.state == WAITING]

    def move_in_queue(self, job_id, position):
        """Move a waiting upload to 1-based ``position`` among the waiting ones."""
        with self._lock:
            waiting = [j for j in self._jobs if j.state == WAITING]
            job = next((j for j in waiting if j.id == job_id), None)
            if job is None:
                return False
            position = max(1, min(int(position), len(waiting)))
            waiting.remove(job)
            waiting.insert(position - 1, job)
            # Rebuild the job list: waiting jobs take the new order in the
            # slots waiting jobs occupied before; everything else stays put.
            it = iter(waiting)
            self._jobs = [next(it) if j.state == WAITING else j for j in self._jobs]
            self._touch()
            return True

    def set_parallel(self, value):
        set_parallel(value)
        with self._lock:
            self._ensure_worker()
        self._wake.set()
        self._apply_limits()

    def queue_position(self, job_id):
        """1-based position among uploads waiting to start (0 if not waiting)."""
        with self._lock:
            waiting = [j.id for j in self._jobs if j.state == WAITING]
        return waiting.index(job_id) + 1 if job_id in waiting else 0

    def cancel_all(self):
        """Cancel every unfinished upload at once (no new one can start
        while the waiting ones are being cancelled)."""
        procs = []
        now = time.time()
        with self._lock:
            for job in self._jobs:
                if job.state in FINISHED:
                    continue
                job._cancel = True
                if job._proc is not None:
                    procs.append(job._proc)
                elif job.state in (WAITING, PAUSED):
                    job.state = CANCELLED
                    job.finished_at = now
            self._touch()
        for proc in procs:
            _terminate(proc)

    def retry_all(self):
        """Put every failed or cancelled upload back in the queue (in order)."""
        count = 0
        with self._lock:
            for job in self._jobs:
                if job.state in (FAILED, CANCELLED):
                    job.state, job.error, job.progress, job.done_bytes = WAITING, '', 0, 0
                    job._cancel = False
                    job.finished_at = None
                    count += 1
            if count:
                self._touch()
                self._ensure_worker()
        if count:
            self._wake.set()
        return count

    def clear_cancelled(self):
        """Remove failed and cancelled uploads from the list."""
        with self._lock:
            self._jobs = [j for j in self._jobs if j.state not in (FAILED, CANCELLED)]
            self._touch()

    def retry(self, job_id):
        with self._lock:
            for job in self._jobs:
                if job.id == job_id and job.state in (FAILED, CANCELLED):
                    job.state, job.error, job.progress = WAITING, '', 0
                    job.done_bytes = 0
                    job.finished_at = None
                    job._cancel = False
                    self._touch()
                    self._ensure_worker()
                    self._wake.set()

    def clear_finished(self):
        with self._lock:
            # Only successful ones: failed/cancelled stay so they can be retried.
            self._jobs = [j for j in self._jobs if j.state not in (DONE, SKIPPED)]
            self._touch()

    def set_speed_limit(self, bps):
        """Save the upload limit and apply it to the transfer in progress."""
        set_bwlimit_bps(bps)
        self._apply_limits()

    def active_count(self):
        with self._lock:
            return sum(1 for j in self._jobs if j.state in (WAITING, UPLOADING, PAUSED))

    def close(self):
        self._closed = True
        self.save(closing=True)      # before cancelling, so nothing is lost
        self.cancel_all()
        self._wake.set()

    # internals --------------------------------------------------------------
    def _touch(self):
        self.version += 1

    def _new_batch(self):
        with self._lock:
            self._batch += 1

    def _add(self, job):
        with self._lock:
            self._seq += 1
            job.batch, job.seq = self._batch, self._seq
            self._jobs.append(job)
            self._touch()
            self._ensure_worker()
        self._wake.set()
        return job

    def _ensure_worker(self):
        self._workers = [t for t in self._workers if t.is_alive()]
        while len(self._workers) < MAX_PARALLEL:
            worker = threading.Thread(target=self._loop, daemon=True)
            worker.start()
            self._workers.append(worker)
        self._worker = self._workers[0]

    def _running(self):
        return [j for j in self._jobs if j.state == UPLOADING]

    def _apply_limits(self):
        """Share the upload limit between the uploads running right now."""
        limit = get_bwlimit_bps()
        with self._lock:
            procs = [j._proc for j in self._running() if j._proc is not None]
        if not procs:
            return
        share = max(16 * 1024, limit // len(procs)) if limit else 0
        for proc in procs:
            threading.Thread(target=rclone.set_live_bwlimit, args=(proc, share),
                             daemon=True).start()

    def _next(self):
        parallel = get_parallel()          # read outside the lock
        with self._lock:
            if len(self._running()) >= parallel:
                return None
            for job in self._jobs:
                if job.state == WAITING:
                    job.state = UPLOADING
                    job.started_at = time.time()
                    job.finished_at = None
                    job.paused_total, job._paused_since = 0.0, None
                    job.resent_bytes = job.done_bytes_shown = 0
                    self._touch()
                    return job
        return None

    def _loop(self):
        while not self._closed:
            job = self._next()
            if job is None:
                self._wake.wait(1)
                self._wake.clear()
                continue
            self._run(job)

    def _run(self, job):
        limit = get_bwlimit_bps()
        with self._lock:
            running = max(1, len(self._running()))
        share = max(16 * 1024, limit // running) if limit else 0
        # Upload pieces sized for the slowest this upload may get (when all
        # parallel slots are busy), so Google never times a piece out.
        slowest = max(16 * 1024, limit // max(running, get_parallel())) if limit else 0
        try:
            proc = rclone.start_transfer(
                job.source_dir, job.destination, files=job.files or None,
                move=job.move, bwlimit_bps=share, chunk_bps=slowest,
                skip_existing=get_existing_mode() == 'skip')
        except Exception as exc:
            with self._lock:
                job.state, job.error = FAILED, str(exc)
                self._touch()
            print(f'[Upload] Failed to start: {job.name}: {exc}', flush=True)
            return
        with self._lock:
            job._proc = proc
            cancel_now = job._cancel
        if cancel_now:
            _terminate(proc)
        else:
            threading.Timer(1.0, self._apply_limits).start()
        last_error = ''
        totals = {'transfers': 0, 'checks': 0}
        try:
            for line in proc.stderr:
                kind, value = rclone.parse_stats_line(line)
                if kind == 'stats':
                    totals['transfers'] = int(value.get('totalTransfers') or 0)
                    totals['checks'] = int(value.get('checks') or 0)
                    with self._lock:
                        raw_done = int(value.get('bytes') or 0)
                        raw_total = int(value.get('totalBytes') or 0)
                        if job._rebase and raw_total > job._last_total:
                            job._base_bytes = job._last_total
                            job._rebase = False
                        job._last_total = raw_total
                        sent = max(0, raw_done - job._base_bytes)
                        job.done_bytes = sent
                        job.total_bytes = max(0, raw_total - job._base_bytes)
                        # rclone counts every byte it sends, including parts it
                        # had to send again after a dropped connection, so its
                        # totals can grow past the file size.  Use the per-file
                        # progress (bytes of the file / its size) instead.
                        files = value.get('transferring') or []
                        if job.size_bytes and (files or job.file_count <= 1):
                            current = sum(min(int(f.get('bytes') or 0), int(f.get('size') or 0))
                                          for f in files)
                            if job.file_count <= 1:
                                done_now = current if files else min(sent, job.size_bytes)
                            else:
                                done_now = min(sent, job.size_bytes)
                            if done_now < job.done_bytes_shown - 1024 * 1024:
                                job._samples.clear()      # the file restarted
                            job.done_bytes = min(done_now, job.size_bytes)
                            job.total_bytes = job.size_bytes
                            job.resent_bytes = max(job.resent_bytes, sent - job.done_bytes)
                        job.done_bytes_shown = job.done_bytes
                        # Speed over the last ~5 s (rclone's own figure is a
                        # slow average that lags behind limit changes).
                        now = time.monotonic()
                        job._samples.append((now, job.done_bytes))
                        while (len(job._samples) > 2
                               and now - job._samples[0][0] > 5.0):
                            job._samples.pop(0)
                        t0, b0 = job._samples[0]
                        if now - t0 >= 1.0 and job.done_bytes >= b0:
                            job.speed = (job.done_bytes - b0) / (now - t0)
                        else:
                            job.speed = float(value.get('speed') or 0)
                        remaining = job.total_bytes - job.done_bytes
                        job.eta = (remaining / job.speed
                                   if job.speed > 0 and remaining > 0 else None)
                        if job.total_bytes:
                            job.progress = min(100, int(job.done_bytes * 100 / job.total_bytes))
                        self._touch()
                elif kind == 'error' and value:
                    print(f'[Upload] {job.name}: rclone: {value}', flush=True)
                    retry = rclone.parse_attempt_failed(value)
                    if retry:
                        with self._lock:
                            job.attempt = min(retry[0] + 1, retry[1])
                            job.max_attempts = retry[1]
                            job.retry_reason = retry[2]
                            job._rebase = True
                            job._samples.clear()
                            job.progress = 0
                            self._touch()
                    elif not value.startswith('Attempt '):
                        last_error = value
            code = proc.wait()
        finally:
            list_file = getattr(proc, 'siphon_list_file', None)
            if list_file:
                try:
                    os.remove(list_file)
                except OSError:
                    pass
        with self._lock:
            job._proc = None
            if job._paused_since:
                job.paused_total += time.time() - job._paused_since
                job._paused_since = None
            job.finished_at = time.time()
            if job._cancel:
                job.state = CANCELLED
            elif code == 0 and totals['transfers'] == 0 and totals['checks'] > 0:
                # Nothing was sent: the file is already in the cloud folder.
                job.state, job.progress, job.error = SKIPPED, 100, ''
                job.restart_note = 0
            elif code == 0:
                job.state, job.progress, job.error = DONE, 100, ''
                job.restart_note = 0
            else:
                job.state = FAILED
                job.error = last_error or f'rclone exit code {code}'
                if _sign_in_expired(job.error):
                    job.error = 'SIGN_IN_EXPIRED'
            job.speed, job.eta = 0.0, None
            self._touch()
        self._wake.set()
        self._apply_limits()
        if job.state == SKIPPED:
            print(f'[Upload] Already there, skipped: {job.name} -> {job.destination}', flush=True)
        if job.state == DONE:
            print(f'[Upload] Done: {job.name} -> {job.destination}', flush=True)
        elif job.state == FAILED:
            print(f'[Upload] Failed: {job.name} -> {job.destination}: {job.error}', flush=True)
        elif job.state == CANCELLED:
            print(f'[Upload] Cancelled: {job.name}', flush=True)


def _sign_in_expired(message):
    """Google refused the saved sign-in (e.g. a 'Testing' app's 7-day limit)."""
    text = str(message or '').lower()
    return any(hint in text for hint in (
        'invalid_grant', 'token has been expired or revoked',
        "couldn't fetch token", 'oauth2: cannot fetch token', 'unauthorized_client'))


def _terminate(proc):
    rclone.resume_process(proc)   # a frozen process must run to exit cleanly
    try:
        proc.terminate()
    except Exception:
        pass
