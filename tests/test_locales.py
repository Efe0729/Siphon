import re
import sys
import types

import pytest


def _stub_runtime_dependency(name, factory=None):
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = factory() if factory else types.ModuleType(name)


def _cloudscraper_stub():
    mod = types.ModuleType('cloudscraper')

    def create_scraper(*args, **kwargs):
        raise AssertionError('cloudscraper should not be used by offline tests')

    mod.create_scraper = create_scraper
    return mod


def _m3u8_stub():
    mod = types.ModuleType('m3u8')
    mod.load = lambda *args, **kwargs: None
    return mod


_stub_runtime_dependency('cloudscraper', _cloudscraper_stub)
_stub_runtime_dependency('m3u8', _m3u8_stub)

from siphon.core import config
from siphon.i18n import locales


LANGS = ['en', 'tr']
PLACEHOLDER_RE = re.compile(r'\{(\w+)\}')


@pytest.fixture(autouse=True)
def _reset_locale():
    yield
    locales.set_lang('en')


def _placeholders(value):
    return set(PLACEHOLDER_RE.findall(value))


def test_locale_key_parity():
    keys = set(locales.STRINGS['en'])
    for lang in LANGS:
        assert keys <= set(locales.STRINGS[lang])


def test_locale_placeholder_parity():
    for key in locales.STRINGS['en']:
        expected = _placeholders(locales.STRINGS['en'][key])
        for lang in LANGS:
            assert _placeholders(locales.STRINGS[lang][key]) == expected, key


def test_add_to_queue_locale_key_present():
    expected = {
        'en': 'Add to Queue',
        'tr': 'Sıraya ekle',
    }
    for lang, text in expected.items():
        assert locales.STRINGS[lang]['add_to_queue'] == text


def test_set_lang_accepts_supported_and_falls_back_to_english():
    locales.set_lang('tr')
    assert locales.get_lang() == 'tr'

    locales.set_lang('xx')
    assert locales.get_lang() == 'en'


def test_ui_font_tracks_current_language():
    locales.set_lang('tr')
    assert locales.ui_font() == 'Segoe UI'

    locales.set_lang('en')
    assert locales.ui_font() == 'Segoe UI'


def test_state_label_translates_known_codes_and_keeps_unknown_codes():
    locales.set_lang('en')
    assert locales.state_label('下載中') == 'Downloading'

    locales.set_lang('tr')
    assert locales.state_label('已下載') == 'Tamamlandı'
    assert locales.state_label('未知狀態') == '未知狀態'



def test_config_prefs_keep_theme_and_language(tmp_path, monkeypatch):
    path = tmp_path / 'ui_prefs.json'
    monkeypatch.setattr(config, '_ui_prefs_path', lambda: str(path))

    config.set_theme('dark')
    config.set_ui_lang('tr')

    assert config.get_theme() == 'dark'
    assert config.get_ui_lang() == 'tr'

    config.set_ui_lang('en')
    assert config.get_ui_lang() == 'en'

    config.set_theme('light')

    assert config.get_theme() == 'light'
    assert config.get_ui_lang() == 'en'


