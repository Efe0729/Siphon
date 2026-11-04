"""Public identity, compatibility, and migration contracts for Siphon."""

from pathlib import Path

from siphon import metadata
from siphon.core import crashlog
from siphon.core import paths
from siphon.i18n import locales


ROOT = Path(__file__).resolve().parents[1]


def test_product_identity_and_release_channels_are_centralized():
    assert metadata.PRODUCT_NAME == "Siphon"
    assert metadata.VERSION == "1.1.0"
    # The updater downloads and runs whatever it finds in this repository, so
    # it may only ever name the one this app is published from.  Empty means
    # "not published yet", and update checking stays switched off.
    repo = metadata.GITHUB_REPOSITORY
    assert repo == "" or repo.split("/")[0] == "Efe0729", repo
    assert metadata.LEGACY_GITHUB_REPOSITORIES == ()
    assert metadata.APP_DISPLAY_NAMES == {
        "browse": "Siphon",
        "headless": "Siphon CLI",
    }


def test_the_only_release_asset_is_our_own():
    """Siphon has its own first release: there are no older names to accept."""
    assert metadata.release_asset_candidates("browse") == ("Siphon.exe",)


# Siphon has no older names to migrate from: it keeps its data under its own
# name and nothing else.


def test_generic_migration_never_overwrites_existing_data(tmp_path):
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"
    legacy.mkdir()
    current.mkdir()
    (legacy / "same.txt").write_text("legacy", encoding="utf-8")
    (legacy / "missing.txt").write_text("copy-me", encoding="utf-8")
    (current / "same.txt").write_text("current", encoding="utf-8")

    report = paths.migrate_directory(legacy, current)

    assert (current / "same.txt").read_text(encoding="utf-8") == "current"
    assert (current / "missing.txt").read_text(encoding="utf-8") == "copy-me"
    assert report.copied_files == 1
    assert report.skipped_files == 1



def test_runtime_source_and_entrypoints_use_only_the_siphon_namespace():
    assert (ROOT / "src" / "siphon" / "__init__.py").is_file()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "siphon"' in pyproject
    assert 'siphon-app = "siphon.entrypoints.browse:main"' in pyproject
    assert list(ROOT.glob("*.py")) == []


def test_visible_runtime_branding_is_siphon():
    source = (ROOT / "src" / "siphon" / "core" / "crashlog.py").read_text(
        encoding="utf-8"
    )
    browse = (ROOT / "src" / "siphon" / "apps" / "browse.py").read_text(
        encoding="utf-8"
    )
    assert crashlog._app_version() == metadata.VERSION
    assert "Siphon" in source or "metadata" in source
    assert "DOWNLOAD  /  UPLOAD" in browse
    for strings in locales.STRINGS.values():
        for key in (
            "app_brand_1",
            "app_full_name",
            "st_header",
            "st_window_title",
            "st_version_by",
        ):
            assert key in strings


def test_canonical_windows_packaging_uses_siphon_names():
    packaging = ROOT / "packaging" / "windows"
    for name in (
        "Siphon.spec",
        "Siphon.version",
    ):
        assert (packaging / name).is_file()


def test_update_checking_is_off_until_a_repository_of_our_own_is_named():
    """An unset repository must switch the updater off, not fall back."""
    from siphon.core import updater

    assert updater.UPDATES_DISABLED is (not metadata.GITHUB_REPOSITORY)
    if not metadata.GITHUB_REPOSITORY:
        assert updater.check_latest()['version'] == '0'
        assert updater.PERSONAL_FORK is True
    else:
        # every address it would ask must be our own repository
        for url in updater.API_CANDIDATES:
            assert url.startswith(
                f'https://api.github.com/repos/{metadata.GITHUB_REPOSITORY}/'), url
