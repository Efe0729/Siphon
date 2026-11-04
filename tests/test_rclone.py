"""The cloud-upload helper: what it asks rclone to do and how it reads back."""

import json

import pytest

from siphon.upload import rclone


def test_a_remote_path_is_remote_colon_folder_with_forward_slashes():
    assert rclone.remote_path('gdrive') == 'gdrive:'
    assert rclone.remote_path('gdrive', '/Videos\\2026/') == 'gdrive:Videos/2026'
    assert rclone.remote_path('gdrive', None) == 'gdrive:'


def test_remotes_are_read_from_the_long_listing(monkeypatch):
    monkeypatch.setattr(rclone, '_run', lambda args, timeout=60:
                        'gdrive: drive\nwork: onedrive\n\nnot a remote line\n')
    assert rclone.list_remotes() == [('gdrive', 'drive'), ('work', 'onedrive')]


def test_a_new_remote_never_reuses_a_name(monkeypatch):
    monkeypatch.setattr(rclone, 'list_remotes',
                        lambda: [('gdrive', 'drive'), ('gdrive2', 'drive')])
    assert rclone.free_remote_name() == 'gdrive3'
    monkeypatch.setattr(rclone, 'list_remotes', lambda: [])
    assert rclone.free_remote_name() == 'gdrive'


def test_folders_come_back_sorted_without_slashes(monkeypatch):
    monkeypatch.setattr(rclone, '_run', lambda args, timeout=60:
                        'zeta/\nalpha/\nBeta/\n\n')
    assert rclone.list_folders('gdrive') == ['alpha', 'Beta', 'zeta']


@pytest.mark.parametrize('bps, expected', [
    (0, '32M'), (None, '32M'),                 # no limit: biggest pieces
    (10 * 1024 * 1024, '32M'),                  # fast: capped at 32M
    (50 * 1024, '1M'),                          # slow: smallest, so a piece
                                                # never outlasts Google's timeout
])
def test_the_upload_piece_size_follows_the_speed_limit(bps, expected):
    assert rclone.chunk_size_for(bps) == expected


def test_the_piece_size_is_a_power_of_two_between_1m_and_32m():
    for bps in (10_000, 100_000, 500_000, 2_000_000, 50_000_000):
        size = int(rclone.chunk_size_for(bps).rstrip('M'))
        assert 1 <= size <= 32 and size & (size - 1) == 0


def test_the_speed_limit_is_given_in_kilobytes_or_switched_off():
    assert rclone._bwlimit_arg(0) == 'off'
    assert rclone._bwlimit_arg(None) == 'off'
    assert rclone._bwlimit_arg(1_500_000) == '1464k'
    assert rclone._bwlimit_arg(10) == '1k'      # never rounds down to nothing


def test_stats_lines_are_told_from_errors_and_noise():
    stats = json.dumps({'stats': {'bytes': 5, 'speed': 2.5}})
    assert rclone.parse_stats_line(stats) == ('stats', {'bytes': 5, 'speed': 2.5})
    error = json.dumps({'level': 'error', 'msg': ' quota exceeded '})
    assert rclone.parse_stats_line(error) == ('error', 'quota exceeded')
    assert rclone.parse_stats_line(json.dumps({'level': 'info', 'msg': 'x'})) == (None, None)
    assert rclone.parse_stats_line('{not json') == (None, None)
    assert rclone.parse_stats_line('') == (None, None)
    assert rclone.parse_stats_line('plain text from rclone') == (
        'error', 'plain text from rclone')


def test_a_failed_attempt_message_is_split_into_its_parts():
    message = 'Attempt 2/3 failed with 1 errors and: googleapi: Error 403: rate limit'
    assert rclone.parse_attempt_failed(message) == (
        2, 3, 'googleapi: Error 403: rate limit')
    assert rclone.parse_attempt_failed('something else') is None
    assert rclone.parse_attempt_failed(None) is None


class _Recorder:
    """Stands in for Popen so no program is started."""
    def __init__(self, args, **_kwargs):
        _Recorder.args = args

    def poll(self):
        return None


@pytest.fixture
def fake_rclone(monkeypatch):
    monkeypatch.setattr(rclone, 'find_rclone', lambda: 'rclone-test')
    monkeypatch.setattr(rclone.subprocess, 'Popen', _Recorder)
    return _Recorder


def test_copy_is_the_default_and_move_is_asked_for(fake_rclone, tmp_path):
    rclone.start_transfer(str(tmp_path), 'gdrive:')
    assert fake_rclone.args[1] == 'copy'
    rclone.start_transfer(str(tmp_path), 'gdrive:', move=True)
    assert fake_rclone.args[1] == 'move'


def test_existing_files_are_only_skipped_when_asked(fake_rclone, tmp_path):
    rclone.start_transfer(str(tmp_path), 'gdrive:')
    assert '--ignore-existing' not in fake_rclone.args
    rclone.start_transfer(str(tmp_path), 'gdrive:', skip_existing=True)
    assert '--ignore-existing' in fake_rclone.args


def test_the_speed_limit_goes_to_rclone_and_a_live_control_is_opened(fake_rclone, tmp_path):
    proc = rclone.start_transfer(str(tmp_path), 'gdrive:', bwlimit_bps=1_048_576)
    args = fake_rclone.args
    assert args[args.index('--bwlimit') + 1] == '1024k'
    url, user, password = proc.siphon_rc
    # The control channel is this computer only, behind a password.
    assert url.startswith('http://127.0.0.1:') and password
    assert args[args.index('--rc-addr') + 1].startswith('127.0.0.1:')


def test_no_limit_means_off(fake_rclone, tmp_path):
    rclone.start_transfer(str(tmp_path), 'gdrive:')
    assert fake_rclone.args[fake_rclone.args.index('--bwlimit') + 1] == 'off'


def test_only_the_named_files_are_sent_and_their_list_is_kept(fake_rclone, tmp_path):
    proc = rclone.start_transfer(str(tmp_path), 'gdrive:',
                                 files=['a.mp4', 'sub/b.mp4'])
    args = fake_rclone.args
    assert '--no-traverse' in args
    listing = args[args.index('--files-from-raw') + 1]
    with open(listing, encoding='utf-8') as handle:
        assert handle.read().splitlines() == ['a.mp4', 'sub/b.mp4']
    assert proc.siphon_list_file == listing
    import os
    os.unlink(listing)


def test_without_rclone_the_error_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(rclone, 'find_rclone', lambda: None)
    with pytest.raises(rclone.RcloneError):
        rclone.start_transfer(str(tmp_path), 'gdrive:')


def test_a_finished_or_unreachable_transfer_cannot_be_re_limited():
    class Done:
        siphon_rc = ('http://127.0.0.1:1', 'u', 'p')

        def poll(self):
            return 0

    assert rclone.set_live_bwlimit(Done(), 1000) is False
    assert rclone.set_live_bwlimit(object(), 1000) is False

    class Running(Done):
        def poll(self):
            return None

    # Nothing is listening on that port: it must say no, not raise.
    assert rclone.set_live_bwlimit(Running(), 1000) is False
