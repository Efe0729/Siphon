"""Local storage failures must not enter network retry/fallback loops (#54)."""
import errno
import types
import pytest

from siphon.core.storage import StorageWriteError, storage_open
from siphon.sites import base, downloader as dl
from siphon.cli import headless


def test_storage_open_classifies_open_failure(monkeypatch, tmp_path):
    def broken(*args, **kwargs):
        raise OSError(errno.EIO, 'device unavailable')
    monkeypatch.setattr('builtins.open', broken)
    with pytest.raises(StorageWriteError, match='device unavailable'):
        with storage_open(tmp_path / 'video.part', 'wb'):
            pass


@pytest.mark.parametrize(('code', 'hint'), [
    (errno.ENOENT, 'path is missing or unavailable'),
    (errno.ENOSPC, 'Free space'),
    (errno.EACCES, 'permission'),
    (errno.ENOTDIR, 'not a directory'),
    (errno.EIO, 'device health'),
])
def test_storage_error_explains_errno_and_keeps_path_and_cause(code, hint):
    path = r'D:\Downloads\video.mp4.part'
    cause = OSError(code, 'underlying failure', path)
    error = StorageWriteError(path, cause, operation='open for writing')
    message = str(error)
    assert hint in message
    assert message.index('open for writing') < message.index(path)
    assert message.index(path) < message.index('underlying failure')
    assert error.path == path
    assert error.filename == path
    assert error.cause is cause
    assert error.errno == code


def test_missing_download_directory_is_storage_error_with_actionable_hint(tmp_path):
    missing = tmp_path / 'removed-download-directory' / 'video.mp4.part'
    with pytest.raises(StorageWriteError) as caught:
        with storage_open(missing, 'wb'):
            pytest.fail('missing destination must not open')
    assert caught.value.operation == 'open for writing'
    assert 'path is missing or unavailable' in str(caught.value)
    assert 'choose an existing writable download folder' in str(caught.value)
    assert not missing.parent.exists()  # Do not silently recreate an offline mount.


def test_storage_write_failure_identifies_operation(monkeypatch, tmp_path):
    def fail_write(data):
        raise OSError(errno.EIO, 'device offline')
    fake = types.SimpleNamespace(write=fail_write, close=lambda: None)
    monkeypatch.setattr('builtins.open', lambda *a, **kw: fake)
    with pytest.raises(StorageWriteError) as caught:
        with storage_open(tmp_path / 'video.part', 'wb') as target:
            target.write(b'video')
    assert caught.value.operation == 'write'
    assert 'device offline' in str(caught.value)


def test_storage_open_does_not_classify_network_errors(tmp_path):
    with pytest.raises(ConnectionError) as caught:
        with storage_open(tmp_path / 'video.part', 'wb'):
            raise ConnectionError('network reset')
    assert not isinstance(caught.value, StorageWriteError)


def test_storage_open_rejects_short_write(monkeypatch, tmp_path):
    fake = types.SimpleNamespace(write=lambda data: len(data) - 1, close=lambda: None)
    monkeypatch.setattr('builtins.open', lambda *a, **kw: fake)
    with pytest.raises(StorageWriteError, match='short write'):
        with storage_open(tmp_path / 'video.part', 'wb') as target:
            target.write(b'video')


def test_hls_write_error_is_fatal_not_pending_retry(monkeypatch, tmp_path):
    job = base.M3U8Crawler.__new__(base.M3U8Crawler)
    job._cancel_job = False
    job._storage_error = None
    job._seg_savename = lambda index: str(tmp_path / 'segment.ts')
    job._m3u8_headers = lambda: {}
    job._key_content = None
    job._transform_segment = lambda data: data
    monkeypatch.setattr(base, '_http_get', lambda *a, **kw: types.SimpleNamespace(
        status_code=200, content=b'\x47' + b'\0' * 187))
    monkeypatch.setattr(base, '_is_valid_ts_segment', lambda data: True)
    def broken(*args, **kwargs):
        raise StorageWriteError(str(tmp_path), OSError(errno.EINVAL, 'device offline'))
    monkeypatch.setattr(base, 'storage_open', broken)
    with pytest.raises(StorageWriteError):
        job._scrape((0, 'https://example.test/segment.ts'))
    assert isinstance(job._storage_error, StorageWriteError)


def test_direct_storage_error_never_falls_back_to_serial(monkeypatch, tmp_path):
    job = dl.MediaSite.__new__(dl.MediaSite)
    job._cancel_job = False
    job._direct_referer = 'https://example.test/'
    job._create_dest_folder = lambda: None
    job.is_target_video_exist = lambda: False
    job._get_video_savename = lambda: str(tmp_path / 'video.mp4')
    def broken(*args):
        raise StorageWriteError(str(tmp_path), OSError(errno.ENOSPC, 'full'))
    job._download_direct_ranges = broken
    job._download_direct_serial = lambda *args: pytest.fail('must not retry disk failure')
    with pytest.raises(StorageWriteError):
        job._download_direct()


def test_cli_stops_batch_on_storage_error(monkeypatch, tmp_path):
    calls = []
    class Site:
        def is_url_vaildate(self):
            return True
        def start_download(self):
            raise StorageWriteError(str(tmp_path), OSError(errno.EIO, 'offline'))
    def create(*args, **kwargs):
        calls.append(args)
        return Site()
    monkeypatch.setattr(
        headless, 'gather_urls', lambda *_args: ['one', 'two'])
    monkeypatch.setattr(headless.M3U8Sites, 'CreateSite', create)
    monkeypatch.setenv('DOWNLOAD_DIR', str(tmp_path))
    assert headless.main([]) == 1
    assert len(calls) == 1


def test_direct_serial_storage_failure_is_not_retried(monkeypatch, tmp_path):
    calls = []
    class Response:
        status_code = 200
        headers = {'content-length': '5'}
        def iter_content(self, **kwargs):
            yield b'video'
        def close(self):
            pass
    def get(*args, **kwargs):
        calls.append(1)
        return Response()
    monkeypatch.setattr(dl, '_get_session', lambda: types.SimpleNamespace(get=get))
    def broken(*args, **kwargs):
        raise StorageWriteError(str(tmp_path), OSError(errno.EIO, 'offline'))
    monkeypatch.setattr(dl, 'storage_open', broken)
    job = dl.MediaSite.__new__(dl.MediaSite)
    job._cancel_job = False
    job._direct_url = 'https://example.test/video'
    with pytest.raises(StorageWriteError):
        job._download_direct_serial(str(tmp_path / 'video.part'), '', 0)
    assert len(calls) == 1


def test_browser_storage_failure_stops_remaining_queue(monkeypatch, tmp_path):
    from siphon.apps import browse
    manager = browse.DownloadManager(max_concurrent=1)
    started = []
    monkeypatch.setattr(manager, '_start_download_thread', started.append)
    cancelled = []
    class Site:
        _cancel_job = False
        def is_url_vaildate(self):
            return True
        def target_name(self):
            return 'video'
        def start_download(self):
            raise StorageWriteError(str(tmp_path), OSError(errno.EIO, 'offline'))
        def cancel_download(self, cleanup=True):
            cancelled.append(cleanup)
            self._cancel_job = True
    monkeypatch.setattr(browse.M3U8Sites, 'CreateSite', lambda *a: Site())
    for url in ('first', 'second'):
        manager.add_item(url, dest=str(tmp_path))
        manager.enqueue(url, str(tmp_path))
    assert len(started) == 1
    manager._run_download(started[0])
    assert len(started) == 1
    items = {item.url: item for item in manager.get_items()}
    assert items['first'].state == '未完成'
    assert 'storage I/O failed' in items['first'].error
    assert items['second'].state == '已取消'
    assert cancelled == [False]


def test_remux_disk_full_does_not_start_raw_fallback(monkeypatch, tmp_path):
    class Process:
        returncode = 1
        def wait(self, **kwargs):
            return 1
    monkeypatch.setattr(base, 'locate_ffmpeg', lambda: 'ffmpeg')
    monkeypatch.setattr(base, '_ffmpeg_safe_dir', lambda path: path)
    def run(*args, **kwargs):
        kwargs['stderr'].write(b'Error writing trailer: No space left on device\n')
        return Process()
    monkeypatch.setattr(base.subprocess, 'Popen', run)
    job = base.M3U8Crawler.__new__(base.M3U8Crawler)
    job._cancel_job = False
    with pytest.raises(StorageWriteError, match='No space left'):
        job._remux_to_mp4(str(tmp_path / 'in.ts'), str(tmp_path / 'out.mp4'), str(tmp_path))


def test_failed_segment_write_never_publishes_truncated_chunk(monkeypatch, tmp_path):
    job = base.M3U8Crawler.__new__(base.M3U8Crawler)
    job._cancel_job = False
    job._storage_error = None
    final = tmp_path / 'segment.ts'
    job._seg_savename = lambda index: str(final)
    job._m3u8_headers = lambda: {}
    job._key_content = None
    job._transform_segment = lambda data: data
    monkeypatch.setattr(base, '_http_get', lambda *a, **kw: types.SimpleNamespace(
        status_code=200, content=b'video'))
    monkeypatch.setattr(base, '_is_valid_ts_segment', lambda data: True)
    class Broken:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def write(self, data):
            (tmp_path / 'segment.ts.part').write_bytes(data[:1])
            raise StorageWriteError(str(final), OSError(errno.EIO, 'offline'))
    monkeypatch.setattr(base, 'storage_open', lambda *a, **kw: Broken())
    with pytest.raises(StorageWriteError):
        job._scrape((0, 'https://example.test/seg.ts'))
    assert not final.exists()
    assert (tmp_path / 'segment.ts.part').exists()





def test_the_log_file_does_not_remember_what_was_downloaded():
    """The queue and history are stored scrambled; a plain-text log next to
    them must not hand the same thing back."""
    from siphon.core.applog import redact

    assert redact('[Example] title: A Real Video Name') == '[Example] title: <hidden>'
    assert redact('File name: Anal Classic') == 'File name: <hidden>'
    assert redact(r'Save location: C:\Users\Someone\Downloads\31') == 'Save location: <hidden>'
    assert redact('Thumbnail: https://example.com/92486562962775.jpg') == 'Thumbnail: <hidden>'
    # the address of a video is private; which site answered is what a
    # problem report needs
    assert redact('Download error: 403 for https://example.com/videos/42/some-clip/') == (
        'Download error: 403 for https://example.com/<hidden>')
    # ordinary diagnosis survives untouched
    for line in ('[browser] msedge.exe ready',
                 'Resuming from 47% (397.6 MB already downloaded).',
                 'Cancelling download...'):
        assert redact(line) == line


def test_hiding_a_part_file_never_breaks_a_download(tmp_path, monkeypatch):
    """Hiding is cosmetic: on anything but Windows it does nothing, and a
    refusal from Windows must not stop the download."""
    from siphon.core.storage import hide_while_working
    target = tmp_path / 'clip.mp4.part'
    target.write_bytes(b'x')

    hide_while_working(str(target))        # not Windows here: a quiet no-op
    assert target.exists()

    monkeypatch.setattr('os.name', 'nt')
    hide_while_working(str(target))        # no ctypes windll here: swallowed
    assert target.exists()


def test_a_finished_download_is_not_left_hidden(tmp_path, monkeypatch):
    """Renaming carries a file's attributes on Windows, so the .part file's
    hidden mark would land on the video and a download that worked would look
    like it had vanished."""
    from siphon.core import storage

    marks = {}
    monkeypatch.setattr(storage, '_hidden', lambda p: marks.get(str(p), False))
    monkeypatch.setattr(storage, 'hide_while_working',
                        lambda p: marks.__setitem__(str(p), True))
    monkeypatch.setattr(storage, 'show_when_finished',
                        lambda p: marks.__setitem__(str(p), False))

    part = tmp_path / 'video.mp4.part'
    part.write_bytes(b'data')
    storage.hide_while_working(part)
    assert marks[str(part)] is True

    done = tmp_path / 'video.mp4'
    part.rename(done)
    marks[str(done)] = marks.pop(str(part))      # what Windows does
    storage.show_when_finished(done)

    assert marks[str(done)] is False


def test_old_hidden_videos_are_brought_back_but_part_files_are_left_alone(
        tmp_path, monkeypatch):
    """The repair pass only touches whole videos: a .part or state file
    belongs to a download that may still be running."""
    from siphon.core import storage

    video = tmp_path / 'already-downloaded.mp4'
    part = tmp_path / 'still-going.mp4.part'
    state = tmp_path / 'still-going.mp4.part.state.json'
    for item in (video, part, state):
        item.write_bytes(b'x')

    hidden = {str(video): True, str(part): True, str(state): True}
    monkeypatch.setattr(storage, '_on_windows', lambda: True)
    monkeypatch.setattr(storage, '_hidden', lambda p: hidden.get(str(p), False))
    monkeypatch.setattr(storage, 'show_when_finished',
                        lambda p: hidden.__setitem__(str(p), False))

    assert storage.unhide_finished_downloads(tmp_path) == 1
    assert hidden[str(video)] is False
    assert hidden[str(part)] is True
    assert hidden[str(state)] is True


def test_the_repair_survives_a_folder_it_cannot_read(tmp_path, monkeypatch):
    """A folder that has been moved or unplugged is not a crash at startup."""
    from siphon.core import storage
    monkeypatch.setattr(storage, '_on_windows', lambda: True)
    assert storage.unhide_finished_downloads(tmp_path / 'not-here') == 0
