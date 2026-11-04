"""Preview must open only a known source page, without enqueueing a download."""
import pytest

from siphon.ui.preview import open_video_preview
@pytest.fixture(autouse=True)
def _sites_the_user_added(monkeypatch):
    """Preview hands an address to the user's browser: only sites they added."""
    from siphon.core import config
    added = {'example.test', 'other.test', 'third.test', 'fourth.test', 'fifth.test'}
    monkeypatch.setattr(
        config, 'is_custom_site',
        lambda host: str(host or '').lower().removeprefix('www.') in added)



@pytest.mark.parametrize('url', [
    'https://example.test/videos/ssni-123/',
    'https://third.test/462685.html',
    'https://other.test/en/sone-543',
    'https://fourth.test/watch?v=12345',
])
def test_preview_opens_supported_source_in_browser(url):
    calls = []
    def opener(value, **kwargs):
        calls.append((value, kwargs))
        return True
    assert open_video_preview(url, opener=opener)
    assert calls == [(url, {'new': 2})]


# Any page on a site the user added is theirs to open; what stays refused is
# another scheme, another host, a credential in the address, or a path that
# climbs out of itself.
@pytest.mark.parametrize('url', [
    'file:///C:/private.txt', 'javascript:alert(1)',
    'https://other.test.evil.example/en/sone-543',
    'https://user:password@other.test/en/sone-543',
    'https://127.0.0.1/private',
    'https://example.test/videos/../../escape/',
    'https://example.test/videos/%2e%2e%2fescape/',
    'https://other.test/en/sone-543\n', 'https://other.test/' + '1' * 5000,
])
def test_preview_rejects_untrusted_url_without_opening(url):
    calls = []
    with pytest.raises(ValueError):
        open_video_preview(url, opener=lambda *a, **k: calls.append(a))
    assert not calls


def test_preview_reports_browser_launch_failure():
    assert not open_video_preview(
        'https://example.test/videos/ssni-123/', opener=lambda *a, **k: False)


def test_card_preview_never_changes_download_queue(monkeypatch):
    from types import SimpleNamespace
    from siphon.apps import app_browse, browse
    calls, messages = [], []
    monkeypatch.setattr(app_browse, 'open_video_preview',
                        lambda url: calls.append(url) or True, raising=False)
    app = SimpleNamespace(_status_lbl=SimpleNamespace(
        configure=lambda **kw: messages.append(kw['text'])))
    browse.ModernApp._preview_video(app, 'https://example.test/videos/ssni-123/')
    assert calls == ['https://example.test/videos/ssni-123/']
    assert messages
