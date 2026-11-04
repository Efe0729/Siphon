import json
from types import SimpleNamespace

import pytest

from siphon.apps.downloads import (
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
from siphon.apps import browse
from siphon.apps.browse import DownloadManager, _DownloadTask
from siphon.core import config


def test_extract_urls_deduplicates_and_strips_message_punctuation():
    text = (
        'one https://example.test/en/mdhg0020, '
        'again https://example.test/en/mdhg0020 and '
        'https://example.test/videos/abc-123/).'
    )

    assert extract_urls(text) == [
        'https://example.test/en/mdhg0020',
        'https://example.test/videos/abc-123/',
    ]


def test_load_url_file_supports_text_csv_and_json(tmp_path):
    text_path = tmp_path / 'urls.txt'
    text_path.write_text('https://example.test/en/mdhg0020\n', encoding='utf-8')
    csv_path = tmp_path / 'urls.csv'
    csv_path.write_text(
        'name,url\nOne,https://example.test/videos/abc-123/\n',
        encoding='utf-8')
    json_path = tmp_path / 'urls.json'
    json_path.write_text(json.dumps({
        'items': [{'url': 'https://other.test/12345.html'}],
    }), encoding='utf-8')

    assert load_url_file(str(text_path)) == [
        'https://example.test/en/mdhg0020']
    assert load_url_file(str(csv_path)) == [
        'https://example.test/videos/abc-123/']
    assert load_url_file(str(json_path)) == [
        'https://other.test/12345.html']


def test_load_url_file_csv_honours_limit(tmp_path):
    csv_path = tmp_path / 'urls.csv'
    csv_path.write_text(
        'url\nhttps://third.test/a\nhttps://third.test/b\n'
        'https://third.test/c\n',
        encoding='utf-8',
    )

    assert load_url_file(str(csv_path), max_urls=2) == [
        'https://third.test/a', 'https://third.test/b',
    ]


def test_filters_cover_active_queue_failure_history_and_paused():
    items = [SimpleNamespace(state=state) for state in (
        '下載中', '等待中', '未完成', '已下載', '已暫停')]

    assert [item.state for item in filter_items(items, 'active')] == ['下載中']
    assert [item.state for item in filter_items(items, 'queued')] == ['等待中']
    assert [item.state for item in filter_items(items, 'failed')] == ['未完成']
    assert [item.state for item in filter_items(items, 'done')] == ['已下載']
    assert [item.state for item in filter_items(items, 'paused')] == ['已暫停']
    # "All" keeps every row but groups them: running, waiting, stopped, done
    assert sorted(filter_items(items, 'all'), key=id) == sorted(items, key=id)


def test_ordering_does_not_need_every_field_to_be_there():
    """The order is worked out for whatever the list holds; a row without a
    finish time or an address must not stop the list from drawing."""
    items = [SimpleNamespace(state=state) for state in (
        '已下載', '等待中', '下載中')]
    assert [i.state for i in filter_items(items, 'all')] == [
        '下載中', '等待中', '已下載']


@pytest.mark.parametrize(
    ('error', 'state', 'code', 'retryable'),
    [
        ('No space left on device', '未完成', 'disk_full', False),
        ('Cloudflare 403', '封鎖/解析失敗', 'blocked', True),
        ('connection timed out', '未完成', 'network', True),
        ('HTTP 404 video not found', '未完成', 'video_missing', False),
        ('ffmpeg not found', '未完成', 'ffmpeg_missing', False),
    ],
)
def test_problem_classification(error, state, code, retryable):
    problem = classify_download_problem(error, state)
    assert (problem.code, problem.retryable) == (code, retryable)


def test_storage_preflight_creates_and_checks_writable_destination(tmp_path):
    result = storage_preflight(str(tmp_path / 'downloads'), minimum_free_bytes=0)
    assert result.ok
    assert result.free_bytes > 0
    assert not list((tmp_path / 'downloads').glob('.siphon-write-test-*'))


def test_schedule_and_eta_helpers_are_deterministic():
    now = 1_767_225_600.0
    scheduled = next_schedule_epoch('23:59', now=now)
    assert scheduled > now
    assert next_schedule_epoch('', now=now) == 0
    with pytest.raises(ValueError):
        next_schedule_epoch('25:00', now=now)
    assert format_eta(65) == '1m 5s'
    assert format_eta(3660) == '1h 1m'


def test_site_code_and_export_include_diagnostics(tmp_path):
    item = SimpleNamespace(
        job_id='job-1', state='未完成', name='MDHG0020 Full title',
        progress=42, speed='1 MB/s', eta='2m',
        url='https://example.test/en/mdhg0020', dest='downloads',
        resolution='720', filename_template='{code} {title}',
        error_code='network', error='timeout', created_at=1, updated_at=2,
        site='Example',
    )
    target = tmp_path / 'queue.json'

    export_items([item], str(target))
    record = json.loads(target.read_text(encoding='utf-8'))['items'][0]

    # Siphon has no site names of its own: a site is called whatever the
    # user named it, and its host until they do.
    assert site_name(item.url) == 'example.test'
    assert video_code(item.url, item.name) == 'MDHG0020'
    assert record['job_id'] == 'job-1'
    assert record['error_code'] == 'network'
    assert QueueAddSummary(requested=1, added=1).added == 1


def test_new_preferences_normalize_and_round_trip(tmp_path, monkeypatch):
    path = tmp_path / 'ui_prefs.json'
    monkeypatch.setattr(config, '_ui_prefs_path', lambda: str(path))

    assert config.set_filename_template('{site} {code} {title}') == (
        '{site} {code} {title}')
    assert config.set_download_schedule('7:05') == '07:05'
    assert config.set_minimum_free_gb('1.25') == 1.25
    assert config.set_auto_retry_count(99) == 10
    assert config.set_notify_on_complete(False) is False
    assert config.set_speed_limit_mbps('12.5') == 12.5
    assert config.set_download_directory(str(tmp_path / 'downloads')) == (
        str(tmp_path / 'downloads'))

    assert config.get_filename_template() == '{site} {code} {title}'
    assert config.get_download_schedule() == '07:05'
    assert config.get_minimum_free_gb() == 1.25
    assert config.get_auto_retry_count() == 10
    assert config.get_notify_on_complete() is False
    assert config.get_speed_limit_mbps() == 12.5
    assert config.get_download_directory() == str(tmp_path / 'downloads')


def test_notification_preference_parses_string_booleans(tmp_path, monkeypatch):
    path = tmp_path / 'ui_prefs.json'
    monkeypatch.setattr(config, '_ui_prefs_path', lambda: str(path))

    assert config.set_notify_on_complete('false') is False
    assert config.get_notify_on_complete() is False
    assert config.set_notify_on_complete('yes') is True
    assert config.get_notify_on_complete() is True


def test_pause_and_resume_a_pending_download(monkeypatch):
    manager = DownloadManager(max_concurrent=1)
    started = []
    monkeypatch.setattr(manager, '_start_download_thread', started.append)
    manager.add_item('first', dest='download')
    manager.enqueue('first', 'download')
    paused = manager.add_item('second', dest='download')
    manager.enqueue('second', 'download')

    assert manager.pause('second')
    assert paused.state == '已暫停'
    assert manager.pending_count == 0
    assert manager.resume('second')
    assert manager.pending_count == 1


def test_pause_active_preserves_chunks_and_finishes_as_paused(monkeypatch):
    manager = DownloadManager(max_concurrent=1)
    item = manager.add_item('active', state='下載中', dest='download')
    task = _DownloadTask('active', 'download', manager._cancel_epoch)
    cleanup_values = []
    task.job = SimpleNamespace(
        cancel_download=lambda cleanup=True: cleanup_values.append(cleanup))
    manager._active['active'] = task
    monkeypatch.setattr(manager, '_start_download_thread', lambda _task: None)

    assert manager.pause('active')
    manager._complete_download(task, '已取消')

    assert cleanup_values == [False]
    assert item.state == '已暫停'
    assert manager.active_count == 0


def test_future_schedule_waits_until_due(monkeypatch):
    now = [1000.0]
    manager = DownloadManager(max_concurrent=1)
    started = []
    monkeypatch.setattr(browse.time, 'time', lambda: now[0])
    monkeypatch.setattr(manager, '_arm_schedule_locked', lambda: None)
    monkeypatch.setattr(manager, '_start_download_thread', started.append)
    item = manager.add_item('scheduled', dest='download')

    assert manager.enqueue('scheduled', 'download', not_before=1100)
    assert item.state == '已排程'
    assert manager.pending_count == 1
    assert started == []

    now[0] = 1100
    manager._try_next()
    assert len(started) == 1
    assert manager.active_count == 1


def test_transient_failure_uses_bounded_backoff(monkeypatch):
    now = [1000.0]
    manager = DownloadManager(auto_retry_count_getter=lambda: 2)
    monkeypatch.setattr(browse.time, 'time', lambda: now[0])
    monkeypatch.setattr(manager, '_arm_schedule_locked', lambda: None)
    item = manager.add_item('retry', state='下載中', dest='download')
    task = _DownloadTask('retry', 'download', manager._cancel_epoch)
    manager._active['retry'] = task

    assert manager._schedule_transient_retry(task, 'connection timed out')
    assert item.state == '等待重試'
    assert item.retry_count == 1
    assert item.next_retry_at == 1002
    assert manager.pending_count == 1
    assert manager.active_count == 0


def test_url_file_is_read_whatever_encoding_notepad_used(tmp_path):
    """A Turkish Windows saves plain text as cp1254 by default."""
    path = tmp_path / 'linkler.txt'
    path.write_bytes(
        'https://site.com/videos/1/şahane-klip/\nsite.com/videos/2/\n'
        .encode('cp1254'))

    assert load_url_file(str(path)) == [
        'https://site.com/videos/1/şahane-klip/',
        'https://site.com/videos/2/',
    ]


def _paused_manager():
    """A manager holding one paused download and nothing running."""
    mgr = DownloadManager()
    mgr._items['https://example.com/v/1/'] = browse.DownloadItem(
        'https://example.com/v/1/', dest='/tmp')
    mgr._set_state('https://example.com/v/1/', '已暫停')
    return mgr


def test_cancel_all_reaches_a_paused_download():
    """A paused download holds no task, and used to survive Cancel All."""
    mgr = _paused_manager()
    assert mgr.active_count == 0 and mgr.pending_count == 0
    mgr.cancel_all()
    assert [i.state for i in mgr.get_items()] == ['已取消']


def test_resume_all_puts_paused_downloads_back_in_the_queue(monkeypatch):
    mgr = _paused_manager()
    started = []
    monkeypatch.setattr(mgr, 'enqueue',
                        lambda url, dest, **kw: started.append(url) or True)
    assert mgr.resume_all() == 1
    assert started == ['https://example.com/v/1/']


def test_all_shows_what_is_running_first_and_the_finished_ones_last():
    """A finished download sitting between the running ones made the user
    scroll to find what was actually happening."""
    from siphon.apps.downloads import filter_items
    from siphon.apps.browse import DownloadItem

    def row(url, state, finished=0):
        item = DownloadItem(url, dest='/tmp')
        item.state = state
        # Set by hand: the Windows clock ticks about every 15 ms, so two rows
        # made one after the other can share a time and tie.
        item.completed_at = finished
        return item

    # added in the worst possible order
    items = [row('a', '已下載', 100), row('b', '等待中'), row('c', '下載中'),
             row('d', '已下載', 200), row('e', '已暫停'), row('f', '等待中'),
             row('g', '未完成')]

    order = [item.url for item in filter_items(items, 'all')]
    assert order == ['c',              # running
                     'b', 'f',         # waiting, in the order they were added
                     'e',              # paused
                     'g',              # failed
                     'd', 'a']         # finished, the latest one first
    # the same ordering inside a single tab, not only in All
    assert [i.url for i in filter_items(items, 'done')] == ['d', 'a']


def test_the_waiting_rows_sit_in_the_order_the_queue_will_run_them():
    """Moving a download to the front of the queue used to change what ran
    next while its row stayed where it was, so the list disagreed with
    itself and the move looked like it had failed."""
    from siphon.apps.downloads import filter_items
    from siphon.apps.browse import DownloadItem

    def row(url):
        item = DownloadItem(url, dest='/tmp')
        item.state = '等待中'
        return item

    items = [row('a'), row('b'), row('c')]
    moved_to_the_front = {'c': 1, 'a': 2, 'b': 3}

    assert [i.url for i in filter_items(items, 'all', moved_to_the_front)] == [
        'c', 'a', 'b']
    assert [i.url for i in filter_items(items, 'queued', moved_to_the_front)] == [
        'c', 'a', 'b']
    # Without the queue's order, the rows keep the order they were added in.
    assert [i.url for i in filter_items(items, 'all')] == ['a', 'b', 'c']


def test_a_download_not_in_the_queue_yet_sits_after_those_that_are():
    from siphon.apps.downloads import filter_items
    from siphon.apps.browse import DownloadItem

    def row(url):
        item = DownloadItem(url, dest='/tmp')
        item.state = '等待中'
        return item

    items = [row('not-queued'), row('queued')]
    assert [i.url for i in filter_items(items, 'all', {'queued': 1})] == [
        'queued', 'not-queued']


def _sortable():
    from siphon.apps.browse import DownloadItem

    def row(url, name, state, size, when):
        item = DownloadItem(url, dest='/tmp')
        item.name = name
        item.state = state
        item.size_text = size
        item.completed_at = when
        return item

    return [
        row('a', 'Zebra', '已下載', '120.5 MB / 300.0 MB', 100),
        row('b', 'apple', '下載中', '1.0 GB / 2.0 GB', 300),
        row('c', 'Mango', '已下載', '', 200),
    ]


def test_sorting_by_name_ignores_capital_letters():
    from siphon.apps.downloads import filter_items
    assert [i.name for i in filter_items(_sortable(), 'all', None, 'name')] == [
        'apple', 'Mango', 'Zebra']


def test_sorting_by_size_reads_the_whole_size_off_the_row():
    """The row shows "120.5 MB / 300.0 MB"; the file is the second number."""
    from siphon.apps.downloads import filter_items, item_size
    order = [i.url for i in filter_items(_sortable(), 'all', None, 'size')]
    assert order[0] == 'b'          # 2 GB
    assert order[-1] == 'c'         # no size yet: sorts last, not as zero
    assert item_size(_sortable()[0]) == 300.0 * (1 << 20)


def test_sorting_by_time_runs_both_ways():
    from siphon.apps.downloads import filter_items
    assert [i.url for i in filter_items(_sortable(), 'all', None, 'newest')] == [
        'b', 'c', 'a']
    assert [i.url for i in filter_items(_sortable(), 'all', None, 'oldest')] == [
        'a', 'c', 'b']


def test_a_chosen_order_replaces_the_grouping_rather_than_sorting_inside_it():
    """Asking for the biggest file means the biggest file, even if it is one
    that has already finished."""
    from siphon.apps.downloads import filter_items
    biggest = filter_items(_sortable(), 'all', None, 'size')[0]
    assert biggest.state == '下載中'
    first_by_name = filter_items(_sortable(), 'all', None, 'name')[0]
    assert first_by_name.name == 'apple'


def test_sorting_still_happens_inside_one_tab():
    from siphon.apps.downloads import filter_items
    done = filter_items(_sortable(), 'done', None, 'name')
    assert [i.name for i in done] == ['Mango', 'Zebra']


def test_an_unknown_order_falls_back_to_the_default_grouping():
    from siphon.apps.downloads import filter_items
    assert [i.url for i in filter_items(_sortable(), 'all', None, 'nonsense')] == [
        i.url for i in filter_items(_sortable(), 'all')]


def test_resume_straight_after_pause_is_not_swallowed(monkeypatch):
    """The bug: pause left the old worker registered while it wound down, and
    Resume was answered with "already running" and nothing happened."""
    manager = DownloadManager(max_concurrent=1)
    item = manager.add_item('active', state='下載中', dest='download')
    task = _DownloadTask('active', 'download', manager._cancel_epoch)
    task.job = SimpleNamespace(cancel_download=lambda cleanup=True: None)
    manager._active['active'] = task
    started = []
    monkeypatch.setattr(manager, '_start_download_thread', started.append)

    assert manager.pause('active')
    assert manager.resume('active')            # old worker has not finished yet
    assert item.state == '等待中'

    manager._complete_download(task, '已取消')  # ...and now it lets go

    assert [t.url for t in started] == ['active']
    assert started[0] is not task
    assert item.state in ('等待中', '下載中')
    assert manager.active_count == 1


def test_pausing_again_cancels_the_waiting_resume(monkeypatch):
    manager = DownloadManager(max_concurrent=1)
    item = manager.add_item('active', state='下載中', dest='download')
    task = _DownloadTask('active', 'download', manager._cancel_epoch)
    task.job = SimpleNamespace(cancel_download=lambda cleanup=True: None)
    manager._active['active'] = task
    started = []
    monkeypatch.setattr(manager, '_start_download_thread', started.append)

    manager.pause('active')
    manager.resume('active')
    manager.pause('active')
    manager._complete_download(task, '已取消')

    assert started == []
    assert item.state == '已暫停'


def test_a_front_page_with_no_videos_opens_its_first_section_once():
    """Some sites show only a list of sections on the front page."""
    from types import SimpleNamespace
    opened = []
    chosen = ['Home']
    me = SimpleNamespace(
        _categories=[{'name': 'Home'}, {'name': 'Best'}, {'name': 'New'}],
        _cat_var=SimpleNamespace(get=lambda: chosen[0],
                                 set=lambda v: chosen.__setitem__(0, v)),
        _site_key='s.test',
        _on_cat_change=opened.append)
    step = browse.ModernApp._open_first_section_instead
    assert step(me, [], 1, False) is True
    assert opened == ['Best'] and chosen[0] == 'Best'
    # Back on Home by choice: left alone.
    chosen[0] = 'Home'
    assert step(me, [], 1, False) is False
    # Videos present, or a later page, or a block: nothing to do.
    me2 = SimpleNamespace(**{**vars(me), '_site_key': 'other.test'})
    assert step(me2, [{'url': 'x'}], 1, False) is False
    assert step(me2, [], 2, False) is False
    assert step(me2, [], 1, True) is False
