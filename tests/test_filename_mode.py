import json

from siphon.core import config
from siphon.core import secretstore
from siphon.sites.base import M3U8Crawler


_TITLES = {}


class _NamingCrawler(M3U8Crawler):
    website_dirname_pattern = r'https://example\.test/([^/]+)/$'

    def get_url_infos(self):
        self._targetName = _TITLES[self._dirName]
        self._imageUrl = None
        self._m3u8url = 'https://cdn.example.test/master.m3u8'


def _crawler(tmp_path, monkeypatch, title, mode):
    monkeypatch.setattr(
        config, 'get_filename_mode', lambda: mode, raising=False)
    slug = f'video-{len(_TITLES)}'
    _TITLES[slug] = title
    return _NamingCrawler(
        f'https://example.test/{slug}/', savepath=str(tmp_path), silence=True)


def test_a_whole_title_is_kept_however_the_old_setting_was_left(
        tmp_path, monkeypatch):
    """"Code only" kept everything before the first space, to pull a
    Japanese studio code out of a title.  On any other title it threw the
    name away — "Rainy Window Jazz" became "Rainy" — so the setting is gone.
    Anyone who had chosen it keeps their whole titles rather than being left
    with truncated names and no setting to turn off.
    """
    path = tmp_path / 'ui_prefs.json'
    monkeypatch.setattr(config, '_ui_prefs_path', lambda: str(path))
    config.set_filename_mode('code-only')

    assert config.get_filename_mode() == 'full-title'

    crawler = _crawler(tmp_path, monkeypatch,
                       'Rainy Window Jazz', 'code-only')
    assert crawler.target_name() == 'Rainy Window Jazz'


def test_a_studio_code_title_is_also_kept_whole(tmp_path, monkeypatch):
    crawler = _crawler(tmp_path, monkeypatch,
                       'ABCD-123 A complete title with spaces', 'code-only')
    assert crawler.target_name() == 'ABCD-123 A complete title with spaces'


def test_the_whole_title_is_what_a_download_is_named(tmp_path, monkeypatch):
    title = 'ABCD-123 A complete title'
    crawler = _crawler(tmp_path, monkeypatch, title, 'full-title')

    assert crawler.target_name() == title


def test_filename_template_supports_allowlisted_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config, 'get_filename_template', lambda: '{site} {code} {title}')
    crawler = _crawler(
        tmp_path, monkeypatch, 'ABCD-123 A complete title', 'full-title')

    assert crawler.target_name() == (
        'example.test ABCD-123 ABCD-123 A complete title')


def test_invalid_filename_template_falls_back_to_title():
    assert config.normalize_filename_template('../{title}') == '{title}'
    assert config.normalize_filename_template('{unknown}') == '{title}'
    assert config.normalize_filename_template('literal-only') == '{title}'


def test_a_template_someone_already_saved_keeps_working():
    """{code} is no longer offered, but resetting a setting somebody chose,
    without saying so, is worse than honouring a field they picked."""
    assert config.normalize_filename_template(
        '{code} - {title}') == '{code} - {title}'


def test_the_fields_offered_do_not_include_the_studio_code():
    assert 'code' not in config.FILENAME_TEMPLATE_OFFERED
    assert set(config.FILENAME_TEMPLATE_OFFERED) == {'title', 'site'}


def test_the_help_text_offers_only_the_fields_that_are_offered():
    """The help used to name a field the setting no longer encourages."""
    from siphon.i18n.locales import STRINGS
    for language in ('en', 'tr'):
        text = STRINGS[language]['filename_template_desc']
        assert '{title}' in text
        assert '{code}' not in text


def test_the_filename_format_setting_is_gone_from_the_screen():
    import inspect
    from siphon.apps import browse
    source = inspect.getsource(browse.ModernApp)
    assert 'filename_mode_setting' not in source
    assert '_on_filename_mode_change' not in source


def test_the_saved_page_button_says_what_it_does():
    """"Teach from a saved page" did not say what the person has to do."""
    from siphon.i18n.locales import STRINGS
    for language in ('en', 'tr'):
        label = STRINGS[language]['mysites_teach']
        assert '.html' in label
        assert 'teach' not in label.lower()
        assert 'öğret' not in label.lower()
