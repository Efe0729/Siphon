# coding: utf-8
"""Auto-updater tests: version compare (drives whether users are offered updates) and
download_asset validation (size floor + MZ-header check + atomic replace)."""
from siphon.core import updater


def test_parse_version():
    assert updater.parse_version('2.5.18') == (2, 5, 18)
    assert updater.parse_version('v2.5.18') == (2, 5, 18)
    assert updater.parse_version('2.10.0') == (2, 10, 0)
    assert updater.parse_version('2.5') == (2, 5, 0)
    assert updater.parse_version('2') == (2, 0, 0)
    assert updater.parse_version('') == (0, 0, 0)
    assert updater.parse_version(None) == (0, 0, 0)
    assert updater.parse_version('v2.5.18-beta1') == (2, 5, 18)


def test_is_newer_is_numeric_not_lexical():
    assert updater.is_newer('2.10.0', '2.9.0') is True      # 10 > 9 numerically, not "1" < "9"
    assert updater.is_newer('2.5.18', '2.5.17') is True
    assert updater.is_newer('2.5.17', '2.5.18') is False
    assert updater.is_newer('2.5.18', '2.5.18') is False
    assert updater.is_newer('v2.6.0', '2.5.99') is True


def test_the_updater_only_installs_our_own_release_asset():
    """A release that holds some other project's exe must not be installed."""
    ours = {'assets': {'Siphon.exe': 'https://example.invalid/siphon.exe'}}
    someone_else = {'assets': {
        'Other_Project.exe': 'https://example.invalid/other.exe',
        'Legacy_Build.exe': 'https://example.invalid/legacy.exe',
    }}

    assert updater.find_asset_url(ours, 'browse').endswith('/siphon.exe')
    assert not updater.find_asset_url(someone_else, 'browse')


class _FakeResp:
    def __init__(self, status=200, chunks=(b'',), headers=None):
        self.status_code = status
        self._chunks = chunks
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, chunk_size=0):
        for c in self._chunks:
            yield c


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, *a, **k):
        return self._resp


def _patch_session(monkeypatch, resp):
    monkeypatch.setattr(updater, '_session', lambda: _FakeSession(resp))


def test_download_asset_rejects_too_small(monkeypatch, tmp_path):
    _patch_session(monkeypatch, _FakeResp(chunks=[b'MZ' + b'\x00' * 100]))
    dest = str(tmp_path / 'out.exe')
    assert updater.download_asset('http://x/app.exe', dest) is False
    assert not (tmp_path / 'out.exe').exists()


def test_download_asset_rejects_non_mz(monkeypatch, tmp_path):
    _patch_session(monkeypatch, _FakeResp(chunks=[b'XX' + b'\x00' * 3_000_001]))
    dest = str(tmp_path / 'out.exe')
    assert updater.download_asset('http://x/app.exe', dest) is False
    assert not (tmp_path / 'out.exe').exists()


def test_download_asset_accepts_valid(monkeypatch, tmp_path):
    _patch_session(monkeypatch, _FakeResp(chunks=[b'MZ' + b'\x00' * 3_000_001]))
    dest = str(tmp_path / 'out.exe')
    assert updater.download_asset('http://x/app.exe', dest) is True
    assert (tmp_path / 'out.exe').exists()


def test_download_asset_rejects_http_error(monkeypatch, tmp_path):
    _patch_session(monkeypatch, _FakeResp(status=404, chunks=[b'']))
    dest = str(tmp_path / 'out.exe')
    assert updater.download_asset('http://x/app.exe', dest) is False


def test_clean_restart_env_strips_pyinstaller_vars(monkeypatch):
    import os
    import sys

    mei = os.path.join('C:\\Temp', '_MEI221482')
    monkeypatch.setattr(sys, '_MEIPASS', mei, raising=False)
    sample = {
        'SYSTEMROOT': 'C:\\Windows',
        '_PYI_PARENT_PROCESS_LEVEL': '1',
        '_PYI_APPLICATION_HOME_DIR': mei,
        '_PYI_ARCHIVE_FILE': 'C:\\Desktop\\Siphon.exe',
        '_MEIPASS2': mei,
        'TCL_LIBRARY': os.path.join(mei, '_tcl_data'),
        'TK_LIBRARY': os.path.join(mei, '_tk_data'),
        'PATH': os.pathsep.join([mei, 'C:\\Windows\\System32']),
    }

    cleaned = updater._clean_restart_env(sample)
    assert cleaned['SYSTEMROOT'] == 'C:\\Windows'
    for gone in ('_PYI_PARENT_PROCESS_LEVEL', '_PYI_APPLICATION_HOME_DIR',
                 '_PYI_ARCHIVE_FILE', '_MEIPASS2', 'TCL_LIBRARY', 'TK_LIBRARY'):
        assert gone not in cleaned
    assert cleaned['PATH'] == 'C:\\Windows\\System32'


def test_apply_update_and_restart_passes_clean_env(monkeypatch, tmp_path):
    import subprocess
    import sys
    import tempfile

    monkeypatch.setattr(updater, 'is_frozen', lambda: True)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'Siphon.exe'))
    monkeypatch.setattr(tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setenv('_PYI_PARENT_PROCESS_LEVEL', '1')
    monkeypatch.setenv('_PYI_APPLICATION_HOME_DIR', str(tmp_path / '_MEI999'))

    captured = {}

    def _fake_popen(cmd, **kwargs):
        captured['cmd'] = cmd
        captured['kwargs'] = kwargs
        return object()

    monkeypatch.setattr(subprocess, 'Popen', _fake_popen)
    assert updater.apply_update_and_restart(str(tmp_path / 'Siphon.exe.new')) is True

    env = captured['kwargs']['env']
    assert '_PYI_PARENT_PROCESS_LEVEL' not in env
    assert '_PYI_APPLICATION_HOME_DIR' not in env
    bat_path = captured['cmd'][2]
    with open(bat_path, 'r', encoding='utf-8') as fh:
        bat_text = fh.read()
    assert 'set "_PYI_PARENT_PROCESS_LEVEL="' in bat_text
    assert 'set "_PYI_APPLICATION_HOME_DIR="' in bat_text


def test_download_asset_verifies_expected_sha256(monkeypatch, tmp_path):
    import hashlib

    payload = b'MZ' + b'\x00' * 3_000_001
    good_hash = hashlib.sha256(payload).hexdigest()
    bad_hash = '0' * 64

    _patch_session(monkeypatch, _FakeResp(chunks=[payload]))
    dest = str(tmp_path / 'bad.exe')
    assert updater.download_asset(
        'http://x/app.exe', dest, expected_sha256=bad_hash) is False
    assert not (tmp_path / 'bad.exe').exists()

    _patch_session(monkeypatch, _FakeResp(chunks=[payload]))
    dest_ok = str(tmp_path / 'good.exe')
    assert updater.download_asset(
        'http://x/app.exe', dest_ok, expected_sha256=good_hash) is True
    assert (tmp_path / 'good.exe').exists()


def test_fetch_expected_sha256_parses_checksums_asset(monkeypatch):
    digest = 'a' * 64

    class _SumResp:
        status_code = 200
        text = f'{digest}  Siphon.exe\n'

    monkeypatch.setattr(updater, '_session', lambda: _FakeSession(_SumResp()))
    info = {'assets': {'Siphon_SHA256SUMS.txt': 'https://example.invalid/sums.txt'}}
    assert updater.fetch_expected_sha256(info, 'Siphon.exe') == digest
    assert updater.fetch_expected_sha256(info, 'Other.exe') == ''


def test_short_update_note_skips_html_and_headings():
    from siphon.apps.app_settings import SettingsMixin

    info = {
        'notes': (
            '<div align="center">\n\n'
            '# ◈ Siphon v1.1.2\n\n'
            '**The real video, not the advert next to it.**\n\n'
            '</div>\n'
        )
    }
    assert SettingsMixin._short_update_note(None, info) == (
        'The real video, not the advert next to it.'
    )
