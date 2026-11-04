"""Test bootstrap for the repository's src layout."""

from pathlib import Path
import sys

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def never_open_a_real_browser(monkeypatch):
    """No test may launch the off-screen browser.

    A machine with Edge or Chrome installed behaves differently from one
    without: code that falls back to the browser quietly starts a real
    program, waits for its debugging port, and hangs the test run.  That is
    how a suite that passes on one computer times out on another.

    So every test runs as though no browser existed.  ``available()`` says
    no, and ``fetch`` fails the test outright if something calls it anyway,
    which is the only way a new browser fallback cannot slip in unnoticed.
    A test that genuinely wants the browser path monkeypatches these itself;
    its patch is applied after this one and wins.
    """
    from siphon.core import browser as real_browser

    def refuse(*_args, **_kwargs):
        raise AssertionError(
            'a test tried to open the real browser; '
            'use a fake page instead (see tests/conftest.py)')

    monkeypatch.setattr(real_browser, 'fetch', refuse)
    monkeypatch.setattr(real_browser, 'available', lambda *a, **k: False)


@pytest.fixture(autouse=True)
def keep_tests_out_of_real_user_data(monkeypatch, tmp_path):
    """No test may read or write the person's own settings or files.

    Everything Siphon keeps about a person — settings, the saved queue, the
    encryption key, logs, the browser profile — lives under one folder, and
    the download folder is wherever they chose.  A test that reaches either
    place is not testing, it is editing: running the suite used to change
    the settings file of whoever ran it, and one test un-hid a real video in
    a real download folder.  Even when harmless, it means the suite cannot
    be trusted on a machine that has anything worth keeping.

    So both are pointed at a throwaway folder for the length of each test,
    and anything written lands there instead.  Tests that want their own
    store still patch it themselves; their patch comes after this one and
    wins.
    """
    from siphon.core import config, paths

    data = tmp_path / 'appdata' / 'Siphon'
    downloads = tmp_path / 'downloads'
    for folder in (data, downloads):
        folder.mkdir(parents=True, exist_ok=True)

    def sandbox(appdata=None, **_kwargs):
        # An explicit folder is a test choosing one on purpose; honour it.
        return Path(appdata) if appdata is not None else data

    # config imported the name directly, the rest ask paths for it each time,
    # so both have to be pointed at the sandbox.
    monkeypatch.setattr(paths, 'product_data_dir', sandbox)
    monkeypatch.setattr(config, 'product_data_dir', sandbox)
    monkeypatch.setattr(config, 'get_download_directory', lambda: str(downloads))
    # The settings cache is keyed by path, but it is shared state between
    # tests: start each one with nothing remembered.
    monkeypatch.setattr(config, '_prefs_cache', {'key': None, 'data': {}})


@pytest.fixture
def real_folder_layout(monkeypatch, tmp_path):
    """Put the real path code back, for a test about the layout itself.

    One or two tests check where Siphon keeps things, which the sandbox above
    deliberately changes.  They get the real functions and an APPDATA of
    their own, so the layout is tested without a real folder in sight.
    """
    import importlib
    from siphon.core import config
    paths = importlib.reload(importlib.import_module('siphon.core.paths'))
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setattr(config, 'product_data_dir', paths.product_data_dir)
    return tmp_path
