"""User-added ("my own sites") support."""

import os
import threading
import http.server
import functools

import pytest

from siphon.core import config
from siphon.sites import generic
from siphon.sites.generic import SiteGeneric


PAGE = '''<html><head><title>Nice Clip - Example</title>
<meta property="og:image" content="/thumb.jpg"></head><body>
<video id="player">
  <source src="/files/12345/480.mp4" title="480p">
  <source src="/files/12345/1080.mp4" title="1080p">
</video>
<div class="related"><a href="/videos/999/other/">other</a>
  <script>var r = {"file":"/files/999/1080.mp4"};</script></div>
</body></html>'''


def test_find_sources_reads_the_player_and_sorts_by_quality():
    sources = generic.find_sources(PAGE, 'https://example.com/videos/12345/nice/')
    urls = [s['url'] for s in sources]
    assert 'https://example.com/files/12345/1080.mp4' in urls
    best = sources[-1]
    assert best['height'] == 1080
    # the related video's file must not win
    assert '12345' in best['url']


def test_find_sources_skips_previews_and_screenshots():
    page = ('<video><source src="/contents/videos_screenshots/1/preview_720p.mp4">'
            '<source src="/get_file/1/real_720p.mp4"></video>')
    urls = [s['url'] for s in generic.find_sources(page, 'https://example.com/v/1/')]
    assert urls == ['https://example.com/get_file/1/real_720p.mp4']


def test_find_sources_handles_escaped_javascript_addresses():
    page = '''<script>var p={"src":"https:\\/\\/cdn.example.com\\/v\\/a_720p.m3u8"};</script>'''
    sources = generic.find_sources(page, 'https://example.com/v/2/')
    assert sources and sources[-1]['kind'] == 'hls'
    assert sources[-1]['url'] == 'https://cdn.example.com/v/a_720p.m3u8'


def test_iframe_urls_skips_advertising_and_social_frames():
    page = ('<iframe src="https://www.youtube.com/embed/x"></iframe>'
            '<iframe src="https://a.exoclick.com/ad"></iframe>'
            '<iframe src="/embed/4321"></iframe>')
    assert generic.iframe_urls(page, 'https://example.com/v/3/') == [
        'https://example.com/embed/4321']


@pytest.fixture
def served(tmp_path):
    """A tiny web server with a video page and its MP4 file."""
    (tmp_path / 'page.html').write_text(PAGE, encoding='utf-8')
    (tmp_path / 'files' / '12345').mkdir(parents=True)
    (tmp_path / 'files' / '12345' / '1080.mp4').write_bytes(b'\0' * 2048)
    (tmp_path / 'files' / '12345' / '480.mp4').write_bytes(b'\0' * 512)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


@pytest.fixture
def only_custom_site(monkeypatch):
    """Keep the user's real list of added sites out of the test."""
    saved = {}
    monkeypatch.setattr(config, 'get_custom_sites',
                        lambda: [dict(h) for h in saved.get('sites', [])])
    def add(host, name=''):
        saved['sites'] = [{'host': host.lower(), 'name': name}]
        return True
    monkeypatch.setattr(config, 'add_custom_site', add)
    return add


def test_unknown_site_is_refused_until_it_is_added(served, only_custom_site):
    assert SiteGeneric.validate_url(served + '/page.html') is None
    only_custom_site('127.0.0.1')
    assert SiteGeneric.validate_url(served + '/page.html') == '127.0.0.1'


def test_probe_reports_the_title_and_source_kind(served, only_custom_site):
    result = generic.probe(served + '/page.html')
    assert result['kind'] == 'MP4'
    assert result['title'] == 'Nice Clip - Example'
    assert result['count'] >= 2


def test_probe_rejects_a_page_without_a_video(served):
    with pytest.raises(Exception):
        generic.probe(served + '/files/')


def test_added_site_downloads_the_best_quality(served, only_custom_site, tmp_path):
    only_custom_site('127.0.0.1')
    site = SiteGeneric(served + '/page.html', savepath=str(tmp_path / 'out'))
    site.get_url_infos()
    assert site.is_url_vaildate()
    assert site._direct_url.endswith('/files/12345/1080.mp4')
    assert site._targetName == 'Nice Clip - Example'
    assert site.start_download()
    written = [f for f in os.listdir(tmp_path / 'out') if f.endswith('.mp4')]
    assert written and os.path.getsize(tmp_path / 'out' / written[0]) == 2048


def test_engine_detection_names_the_site_builder():
    assert generic.detect_engine(
        '<script src="/player/kt_player.js?v=5.5.1"></script>')[0] == 'kvs'
    assert generic.detect_engine('<script>jwplayer("p").setup({})</script>')[0] == 'jwplayer'
    assert generic.detect_engine('<div class="video-js"></div>')[0] == 'videojs'
    assert generic.detect_engine('<html><body>plain</body></html>') == ('', '')


def test_schema_org_video_is_used_as_a_source():
    page = ('<script type="application/ld+json">{"@type":"VideoObject",'
            '"contentUrl":"https://cdn.example.com/v/9/1080.mp4"}</script>')
    sources = generic.find_sources(page, 'https://example.com/v/9/')
    assert sources and sources[-1]['url'] == 'https://cdn.example.com/v/9/1080.mp4'


SAVED_PAGE = '''<html><head><title>Saved clip - Example</title>
<link rel="canonical" href="https://example.com/videos/77/saved-clip/">
<meta name="generator" content="TubeEngine 4"></head><body>
<script src="/js/kt_player.js?v=6.1"></script>
<video><source src="/get_file/1/abc/77_720p.mp4" title="720p"></video>
</body></html>'''

SAVED_LISTING = '''<html><body>
<form action="/search/" method="get"><input type="text" name="q"></form>
<a href="/categories/anal/">Anal</a><a href="/categories/teen/">Teen</a>
<a href="/videos/1/a/"><img src="/1.jpg"></a><a href="/videos/2/b/"><img src="/2.jpg"></a>
<a href="/videos/3/c/"><img src="/3.jpg"></a>
<div class="pager"><a href="/2/">2</a><a href="/3/">3</a></div>
</body></html>'''


def test_saved_page_says_where_it_came_from():
    assert generic.page_address(SAVED_PAGE) == 'https://example.com/videos/77/saved-clip/'
    assert generic.page_address('<html><body>nothing</body></html>') == ''


def test_learning_from_a_saved_page_reads_the_whole_layout():
    learned = generic.learn_from_html(
        SAVED_PAGE, 'https://example.com/videos/77/saved-clip/',
        listing_text=SAVED_LISTING, listing_url='https://example.com/')
    assert learned['sources'] == 1 and learned['kind'] == 'MP4'
    assert learned['videos_listed'] == 3 and learned['categories'] == 2
    assert learned['profile']['video_shape'] == '/videos/#/*'
    assert learned['profile']['search'] == 'https://example.com/search/?q={query}'
    assert learned['profile']['page_form'] == 'path'
    # the shareable copy carries no trace of the site it was learned from
    assert learned['template']['search'] == '{root}/search/?q={query}'
    assert 'example.com' not in str(learned['template'])


def test_a_learned_layout_is_recognised_on_another_site():
    learned = generic.learn_from_html(SAVED_PAGE, 'https://example.com/videos/77/x/')
    template = dict(name='TubeEngine 4', markers=learned['markers'],
                    **learned['template'])
    other = SAVED_PAGE.replace('example.com', 'another-site.net')
    assert generic.match_template(other, [template]) is template
    assert generic.match_template('<html><body>plain page</body></html>',
                                  [template]) is None


def test_page_title_reads_a_real_title_and_refuses_a_slug(served, monkeypatch):
    """A queued row gets its name from the page, not from the address."""
    assert generic.page_title(served + '/page.html') == 'Nice Clip - Example'

    monkeypatch.setattr(generic.kvs, 'pick_title',
                        lambda *a, **k: 'big-ass-anal')
    assert generic.page_title(served + '/page.html') == ''


def test_page_title_is_quiet_when_the_page_cannot_be_read(served):
    assert generic.page_title(served + '/nothing-here.html') == ''
