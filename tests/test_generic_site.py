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


def test_page_title_reads_a_real_title(served):
    """A queued row gets its name from the page, not from the address."""
    assert generic.page_title(served + '/page.html') == 'Nice Clip - Example'


def test_a_page_that_only_repeats_its_own_address_names_nothing():
    """A heading that is just the url slug is not a name."""
    page = ('<html><head><title>nice-clip-example</title></head>'
            '<body><h1>nice-clip-example</h1></body></html>')
    url = 'https://example.com/videos/12345/nice-clip-example/'
    assert generic.title_candidates(page, url) == {}
    assert generic._title_from(page, url) == ''


def test_page_title_is_quiet_when_the_page_cannot_be_read(served):
    assert generic.page_title(served + '/nothing-here.html') == ''


BANNER_PAGE = ("""<html><head><title>New Backup Domain:videos-mirror.eu</title></head>
<body><h1 class="notice">New Backup Domain:videos-mirror.eu</h1>
""" + ' ' * 20000 + """
<div class="player_details"><h1>The Real Video Name</h1></div>
<video><source src="/files/5/720.mp4"></video></body></html>""")


def test_page_title_looks_past_a_site_wide_notice(tmp_path):
    """The notice the site shows on every page must not become the title."""
    import functools, http.server, threading
    (tmp_path / 'v.html').write_text(BANNER_PAGE, encoding='utf-8')
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        title = generic.page_title(
            f'http://127.0.0.1:{server.server_address[1]}/v.html')
    finally:
        server.shutdown()
    assert title == 'The Real Video Name'


def test_the_queue_name_is_the_name_the_file_will_get(served, only_custom_site):
    """One reading, not two: the row and the saved file must agree.

    The plain read of the page head is a guess; the site's own adapter is what
    names the file.  The queue asks the adapter, so the two cannot drift.
    """
    import siphon.sites as sites
    only_custom_site('127.0.0.1')
    page = served + '/page.html'

    site = SiteGeneric(page, savepath='/tmp')
    site.get_url_infos()

    assert sites.title_for(page) == site._targetName == 'Nice Clip - Example'


def test_a_page_that_cannot_be_read_names_nothing(only_custom_site, served):
    """A failure must leave the row alone, never raise into the queue."""
    import siphon.sites as sites
    only_custom_site('127.0.0.1')
    assert sites.title_for(served + '/files/') == ''


def test_a_site_that_was_never_added_names_nothing():
    import siphon.sites as sites
    assert sites.title_for('https://not-added-by-the-user.example/v/1/') == ''


# ── learning which rule names a video on a given site ───────────────────────
def _video_page(notice, heading, og=''):
    meta = f'<meta property="og:title" content="{og}">' if og else ''
    return (f'<html><head><title>{notice}</title>{meta}</head><body>'
            f'<h1 class="notice">{notice}</h1>'
            f'<div class="player_details"><h1>{heading}</h1></div>'
            '</body></html>')


def test_a_heading_repeated_on_every_video_is_refused():
    """fourth.test prints "New Backup Domain" as the first heading of every page."""
    notice = 'New Backup Domain:videos-mirror.eu'
    pages = [(_video_page(notice, name), f'https://example.com/videos/{n}/x/')
             for n, name in enumerate(('Morning Jazz', 'Acoustic Session', 'Sadie'))]

    rule, why = generic.learn_title_rule(pages)
    assert rule == 'player_heading', why
    # the notice sits in both <title> and the first <h1>, so both are out
    assert generic._title_from(pages[0][0], pages[0][1], rule) == 'Morning Jazz'


def test_the_listing_decides_which_rule_is_right():
    """The site's own listing already knows the names: the rule that
    reproduces them wins, whatever order they would otherwise be tried in."""
    pages = [(_video_page('Site', f'Heading {n}', og=f'Real Name {n}'),
              f'https://example.com/videos/{n}/x/') for n in range(3)]

    rule, why = generic.learn_title_rule(
        pages, ['Real Name 0', 'Real Name 1', 'Real Name 2'])
    assert rule == 'og_title', why


def test_a_site_whose_pages_are_all_the_same_teaches_nothing():
    pages = [('<html><head><title>Tube</title></head><body><h1>Tube</h1></body></html>',
              f'https://example.com/videos/{n}/x/') for n in range(3)]
    rule, why = generic.learn_title_rule(pages)
    assert rule == ''
    assert 'same' in why


def test_adding_a_site_learns_how_it_names_its_videos(tmp_path, only_custom_site):
    """End to end: the front page is read, three videos are opened, and the
    heading that is a notice on every one of them loses to the real one."""
    import functools, http.server, threading
    notice = 'New Backup Domain:example-backup.eu'
    names = {'101': 'Wheel Of Anal', '202': 'Anal Classic', '303': 'Sadie Comeback'}
    for n, name in names.items():
        folder = tmp_path / 'videos' / n / 'clip'
        folder.mkdir(parents=True)
        (folder / 'index.html').write_text(
            f'<html><head><title>{notice}</title></head><body>'
            f'<h1 class="notice">{notice}</h1>'
            f'<div class="player_details"><h1>{name}</h1></div>'
            f'<video><source src="/files/{n}/720.mp4" title="720p"></video>'
            '</body></html>', encoding='utf-8')
    (tmp_path / 'index.html').write_text(
        '<html><body>' + ''.join(
            f'<a href="/videos/{n}/clip/" title="{name}"><img src="/t{n}.jpg"></a>'
            for n, name in names.items()) + '</body></html>', encoding='utf-8')

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = generic.probe(f'http://127.0.0.1:{server.server_address[1]}/')
    finally:
        server.shutdown()

    assert result['title_rule'] == 'player_heading', result['title_why']
    assert result['listed'] == 3 and result['thumbs'] == 3
    assert notice not in result['sample_titles']
    assert sorted(result['sample_titles']) == sorted(names.values())


def test_what_the_site_taught_us_is_remembered_and_used(tmp_path, monkeypatch):
    """The whole point: learn once at add time, and every queued row and
    saved file afterwards is named by that rule instead of guessing again.

    This site puts its own notice in og:title, which the default order
    trusts before any heading, and the video's name in a plain <h1>.
    """
    import functools, http.server, threading
    notice = 'Visit our new address: example-backup.eu'
    page = (f'<html><head><title>{notice}</title>'
            f'<meta property="og:title" content="{notice}">'
            f'</head><body><h1>Wheel Of Anal</h1>'
            '<video><source src="/files/1/720.mp4" title="720p"></video>'
            '</body></html>')
    folder = tmp_path / 'videos' / '101' / 'clip'
    folder.mkdir(parents=True)
    (folder / 'index.html').write_text(page, encoding='utf-8')

    stored = {}
    monkeypatch.setattr(config, 'custom_site_rules', lambda host: dict(stored))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_address[1]}/videos/101/clip/'
    try:
        # Nothing learned yet: og:title is trusted first, so the notice wins.
        assert generic.page_title(url) == notice

        # What adding the site worked out, now remembered against the host.
        stored['title_rule'] = 'first_h1'
        assert generic.page_title(url) == 'Wheel Of Anal'
    finally:
        server.shutdown()


def test_a_front_page_that_also_holds_a_video_still_teaches_from_its_listing(
        tmp_path, only_custom_site):
    """The front page often plays something itself.  Learning from that one
    page alone taught nothing, so the listing's videos are opened regardless.
    """
    import functools, http.server, threading
    notice = 'New Backup Domain:example-backup.eu'
    names = {'101': 'Wheel Of Anal', '202': 'Anal Classic', '303': 'Sadie'}
    for n, name in names.items():
        folder = tmp_path / 'videos' / n / 'clip'
        folder.mkdir(parents=True)
        (folder / 'index.html').write_text(
            f'<html><head><title>{notice}</title>'
            f'<meta property="og:title" content="{name}"></head><body>'
            f'<h1 class="notice">{notice}</h1>'
            f'<video><source src="/files/{n}/720.mp4" title="720p"></video>'
            '</body></html>', encoding='utf-8')
    # the front page lists the videos AND plays a trailer of its own
    (tmp_path / 'index.html').write_text(
        '<html><head><title>Example tube</title></head><body>'
        '<video><source src="/files/promo/480.mp4" title="480p"></video>'
        + ''.join(f'<a href="/videos/{n}/clip/" title="{name}">'
                  f'<img src="/t{n}.jpg"></a>' for n, name in names.items())
        + '</body></html>', encoding='utf-8')

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = generic.probe(f'http://127.0.0.1:{server.server_address[1]}/')
    finally:
        server.shutdown()

    assert result['listed'] == 3
    # og:title reproduces the names the listing gave, so it wins over the
    # notice standing in <title> and in the page's first heading
    assert result['title_rule'] == 'og_title', result['title_why']
    assert sorted(result['sample_titles']) == sorted(names.values())


def test_a_search_address_that_does_not_search_is_not_kept(tmp_path, only_custom_site):
    """A guessed search address answers with the front page, which made every
    search look like it worked.  It is tried once and dropped when it does
    not return videos."""
    import functools, http.server, threading
    (tmp_path / 'index.html').write_text(
        '<html><body><form method="get" action="/search/">'
        '<input type="text" name="q"></form>'
        '<a href="/videos/1/a/"><img src="/t1.jpg"></a></body></html>',
        encoding='utf-8')
    (tmp_path / 'search').mkdir()
    # the search page answers, but with nothing on it
    (tmp_path / 'search' / 'index.html').write_text(
        '<html><body><p>No results</p></body></html>', encoding='utf-8')

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        from siphon.sites import kvs
        with kvs.make_scraper() as scraper:
            page = scraper.get(root + '/').text
            assert generic._working_search(page, root, scraper) == ''
    finally:
        server.shutdown()


def test_a_pasted_link_gets_its_name_and_its_picture(tmp_path, only_custom_site):
    """Browse cards carry a picture; a pasted link had none.  The page is
    already opened to read the name, so the picture comes back with it."""
    import functools, http.server, threading, siphon.sites as sites
    only_custom_site('127.0.0.1')
    folder = tmp_path / 'videos' / '101' / 'clip'
    folder.mkdir(parents=True)
    (folder / 'index.html').write_text(
        '<html><head><title>Example tube</title>'
        '<meta property="og:image" content="/covers/101.jpg">'
        '</head><body><div class="player_details"><h1>Wheel Of Anal</h1></div>'
        '<video><source src="/files/101/720.mp4" title="720p"></video>'
        '</body></html>', encoding='utf-8')

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        name, picture = sites.describe(root + '/videos/101/clip/')
    finally:
        server.shutdown()

    assert name == 'Wheel Of Anal'
    assert picture.endswith('/covers/101.jpg')


def test_a_video_link_is_enough_the_front_page_is_fetched_for_its_listing(
        tmp_path, only_custom_site):
    """A video link is the better thing to be given: it proves the download
    works.  The listing it does not carry is fetched from the front page
    rather than asked of the user."""
    import functools, http.server, threading
    names = {'101': 'Wheel Of Anal', '202': 'Anal Classic', '303': 'Sadie'}
    for n, name in names.items():
        folder = tmp_path / 'videos' / n / 'clip'
        folder.mkdir(parents=True)
        (folder / 'index.html').write_text(
            f'<html><head><title>Example tube</title></head><body>'
            f'<div class="player_details"><h1>{name}</h1></div>'
            f'<video><source src="/files/{n}/720.mp4" title="720p"></video>'
            '</body></html>', encoding='utf-8')
    (tmp_path / 'index.html').write_text(
        '<html><body>' + ''.join(
            f'<a href="/videos/{n}/clip/" title="{name}"><img src="/t{n}.jpg"></a>'
            for n, name in names.items()) + '</body></html>', encoding='utf-8')

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        # only one address is given, and it is a video page
        result = generic.probe(root + '/videos/101/clip/')
    finally:
        server.shutdown()

    assert result['listed'] == 3, 'the front page was not read for its listing'
    assert result['title_rule'] == 'player_heading', result['title_why']


@pytest.mark.parametrize('pasted,expected', [
    ('https://e.test/search?q=adriana', 'https://e.test/search?q={query}'),
    ('https://e.test/?s=adriana', 'https://e.test/?s={query}'),
    ('https://e.test/video/search?search=adriana&page=1',
     'https://e.test/video/search?search={query}&page=1'),
    ('https://e.test/search/adriana/', 'https://e.test/search/{query}/'),
    ('https://e.test/tags/adriana', 'https://e.test/tags/{query}'),
])
def test_a_pasted_search_address_becomes_a_reusable_one(pasted, expected):
    """The user searched for a word and copied the address, so the word is
    in it: that part becomes the placeholder and the rest is left alone."""
    assert generic.search_template_from(pasted) == expected


@pytest.mark.parametrize('pasted', [
    '', 'not a url', 'ftp://e.test/search?q=a', 'https://e.test/',
])
def test_an_address_with_no_word_in_it_is_refused(pasted):
    assert generic.search_template_from(pasted) == ''


@pytest.mark.parametrize('failure', [
    # What a filtered connection actually says: the name resolved to the
    # machine itself, so the certificate is for the wrong host.
    "SSL: certificate subject name 'localhost.localdomain' does not match",
    'Could not resolve host: example.test',
    'Connection refused',
])
def test_a_site_the_network_blocks_says_so_instead_of_blaming_the_page(failure):
    """A blocked site never sends its page, so there is no video to find in
    it.  Reporting "no video on this page" would send the user looking at the
    site and at Siphon when the fault is in neither."""

    class Blocked:
        def get(self, *_a, **_k):
            raise OSError(failure)

    def never(*_a, **_k):
        raise AssertionError('the browser was opened; it sits on the same '
                             'blocked network and would be told the same')

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(generic.real_browser, 'available', lambda *a, **k: True)
        patch.setattr(generic.real_browser, 'fetch', never)
        with pytest.raises(generic.SiteUnreachableError) as caught:
            generic._fetch(Blocked(), 'https://example.test/v/1', '')

    said = str(caught.value)
    assert 'example.test' in said
    assert 'could not be reached' in said
    assert 'no video' not in said.lower()


def test_an_ordinary_refusal_still_tries_the_browser():
    """Only a network that never reached the site skips the browser: a page
    that answered with a Cloudflare check is exactly what it is for."""

    class Checked:
        def get(self, *_a, **_k):
            raise RuntimeError('too many redirects')

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(generic.real_browser, 'available', lambda *a, **k: True)
        patch.setattr(generic.real_browser, 'fetch',
                      lambda *a, **k: ('<html>a real page</html>', []))
        patch.setattr(generic.real_browser, 'looks_blocked', lambda *a, **k: False)
        patch.setattr(generic.real_browser, 'remember_pass', lambda *a, **k: None)
        text, _media = generic._fetch(Checked(), 'https://example.test/v/1', '')

    assert 'a real page' in text


# ── a listing that is not a listing ──────────────────────────────────────

def _cards(*titles):
    return [{'title': t, 'url': f'https://e.test/v/{n}'}
            for n, t in enumerate(titles)]


def test_a_proper_listing_is_not_doubted():
    assert generic.listing_looks_wrong(
        _cards(*[f'Some real video {n}' for n in range(24)])) == ''


def test_three_things_on_a_whole_page_are_not_a_listing():
    """The category-portal case: three category tiles counted as a listing and the site
    was reported as added, which is worse than failing — the person is told
    it worked and finds out days later that it did not."""
    doubt = generic.listing_looks_wrong(
        _cards('46.328', 'Muzik', 'Oyunlar'))
    assert doubt == 'too_few:3'
    assert '3 video' in generic.doubt_in_english(doubt)


def test_the_sites_own_category_names_are_recognised():
    categories = [{'name': 'Music'}, {'name': 'Gaming'},
                  {'name': 'Sports'}, {'name': 'Documentary'}]
    doubt = generic.listing_looks_wrong(
        _cards('Music', 'Gaming', 'Sports', 'Documentary',
               'Something Else', 'Another Thing'),
        categories)
    assert doubt == 'categories'
    assert 'category' in generic.doubt_in_english(doubt)


def test_names_that_are_only_numbers_are_counts_not_videos():
    doubt = generic.listing_looks_wrong(
        _cards('46.328', '12.900', '8.112', '1.004', '77', 'A real title'))
    assert doubt == 'numbers'


def test_an_empty_listing_is_left_to_the_other_message():
    """"No listing at all" is already reported, and saying it twice in two
    different ways helps nobody."""
    assert generic.listing_looks_wrong([]) == ''


def test_the_doubt_is_a_code_so_each_language_says_it_itself():
    """A sentence built in one language cannot be unpicked by the other."""
    from siphon.i18n.locales import STRINGS
    for code in ('too_few', 'categories', 'numbers'):
        assert code in generic.DOUBT_IN_ENGLISH
        for language in ('en', 'tr'):
            assert f'mysites_doubt_{code}' in STRINGS[language]


def test_the_saved_pages_address_is_read_whatever_order_its_tag_is_in():
    from siphon.sites import generic
    assert generic.page_address(
        '<link href="https://s.test/video-a1/t" rel="canonical"/>'
    ) == 'https://s.test/video-a1/t'
    assert generic.page_address(
        "<meta content='https://s.test/v/9' property='og:url'>"
    ) == 'https://s.test/v/9'
    assert generic.page_address('<head></head>') == ''
