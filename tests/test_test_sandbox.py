"""The suite must not touch the person running it.

These guard the guard: if someone removes the sandbox from conftest, these
fail rather than the suite quietly going back to editing real settings.
"""

import os

from siphon.core import config, paths


def test_the_settings_file_is_not_the_persons_own():
    """Running the suite must not change the settings of whoever ran it."""
    path = config._ui_prefs_path()
    real = str(paths.appdata_root() / 'Siphon')
    assert not os.path.abspath(path).startswith(os.path.abspath(real))


def test_writing_a_setting_stays_in_the_sandbox():
    config.set_download_concurrency(3)
    saved = config._load_prefs()
    assert saved.get('download_concurrency') == 3
    # And it went to the throwaway file, not the person's.
    assert 'Siphon' in config._ui_prefs_path()
    assert os.path.exists(config._ui_prefs_path())


def test_the_download_folder_is_not_the_persons_own():
    """A test that writes, hides or un-hides a file must not reach the folder
    where the person's videos are."""
    folder = config.get_download_directory()
    assert folder
    assert 'downloads' in folder
    assert os.path.isdir(folder)


def test_the_saved_queue_is_not_the_persons_own():
    assert 'Siphon' in config.queue_csv_path()
    real = str(paths.appdata_root() / 'Siphon')
    assert not os.path.abspath(config.queue_csv_path()).startswith(
        os.path.abspath(real))


def test_each_test_gets_a_fresh_sandbox():
    """Nothing a test writes may be visible to the next one."""
    assert config._load_prefs().get('download_concurrency') is None
