"""Browsing a site the user added, worked out from the site's own pages."""
import pytest

from siphon.sites import genericbrowse as gb

ROOT = 'https://example.com'

LISTING = '''<html><body>
<form action="/search/" method="get"><input type="text" name="q"></form>
<nav><a href="/categories/anal/">Anal</a><a href="/categories/blonde/">Blonde</a></nav>
<div class="item"><a href="/videos/11/first-clip/" title="First clip">
  <img src="/i/11.jpg"><span class="duration">10:30</span></a></div>
<div class="item"><a href="/videos/12/second-clip/" title="Second clip">
  <img data-src="/i/12.jpg"><span class="duration">12:00</span></a></div>
<div class="item"><a href="/videos/13/third-clip/" title="Third clip">
  <img src="/i/13.jpg"></a></div>
<a href="/videos/11/first-clip/">text link, no picture</a>
<div class="pagination"><a href="/?page=2">2</a><a href="/?page=3">3</a></div>
</body></html>'''


def test_video_shape_and_cards_are_recognised():
    assert gb.detect_video_shape(LISTING, ROOT) == '/videos/#/*'
    videos = gb.parse_videos(LISTING, ROOT)
    assert [v['title'] for v in videos] == ['First clip', 'Second clip', 'Third clip']
    assert videos[0]['url'] == 'https://example.com/videos/11/first-clip/'
    assert videos[1]['thumbnail'] == 'https://example.com/i/12.jpg'
    assert videos[0]['duration'] == '10:30'
    assert videos[2]['duration'] == ''


def test_categories_come_from_the_site_and_videos_do_not():
    cats = gb.detect_categories(LISTING, ROOT)
    assert [c['name'] for c in cats] == ['Anal', 'Blonde']


def test_search_box_is_read_from_the_form():
    assert gb.detect_search(LISTING, ROOT) == 'https://example.com/search/?q={query}'


def test_paging_form_is_taken_from_the_page_links():
    form = gb.detect_page_form(LISTING, ROOT + '/')
    assert form == 'query:page'
    assert gb.apply_page_form(form, ROOT + '/newest/') == 'https://example.com/newest/?page={page}'


def test_paging_as_the_last_part_of_the_address():
    page = '<a href="/popular/2/">2</a><a href="/popular/3/">3</a>'
    assert gb.detect_page_form(page, ROOT + '/popular/') == 'path'
    assert gb.apply_page_form('path', ROOT + '/popular/') == 'https://example.com/popular/{page}/'


def test_page_links_of_a_video_are_not_mistaken_for_paging():
    page = '<a href="/videos/186367/clip-2-of-a-series/">2</a>'
    assert gb.detect_page_form(page, ROOT + '/') == ''


def test_category_links_do_not_win_over_videos():
    page = ('<a href="/categories/anal/"><img src="/a.jpg">Anal</a>'
            '<a href="/categories/teen/"><img src="/b.jpg">Teen</a>'
            '<a href="/categories/milf/"><img src="/c.jpg">Milf</a>'
            '<a href="/videos/1/x/"><img src="/1.jpg"></a>'
            '<a href="/videos/2/y/"><img src="/2.jpg"></a>'
            '<a href="/videos/3/z/"><img src="/3.jpg"></a>')
    assert gb.detect_video_shape(page, ROOT) == '/videos/#/*'


def test_browser_for_builds_one_adapter_per_host():
    first = gb.browser_for('Example.com', 'Example')
    assert gb.browser_for('www.example.com') is first
    assert first.ROOT == 'https://example.com'
    assert first.is_video_url('https://example.com/videos/5/x/') is True


def test_unknown_address_is_not_claimed_for_another_site():
    adapter = gb.browser_for('mysite.net')
    assert adapter.is_video_url('https://other.net/videos/5/x/') is False


def test_kvs_sites_start_from_the_known_layout():
    known = gb.engine_profile('kvs', ROOT)
    assert known['video_shape'] == '/videos/#/*'
    assert known['page_form'] == 'path'
    assert known['search'] == 'https://example.com/search/{query}/'
    assert gb.engine_profile('', ROOT) == {}


def test_a_search_that_answers_with_the_front_page_is_refused(tmp_path):
    """pxp.pink answered an unknown address with its home page, so the old
    check ("did videos come back?") passed and every search showed the same
    36 videos.  The answer must differ from the front page."""
    import functools, http.server, threading
    from siphon.sites import generic, kvs

    listing = ('<html><body>'
               '<form method="get" action="/search/"><input type="text" name="q"></form>'
               + ''.join(f'<a href="/videos/{n}/clip/"><img src="/t{n}.jpg"></a>'
                         for n in range(1, 6))
               + '</body></html>')
    (tmp_path / 'index.html').write_text(listing, encoding='utf-8')
    # the "search" page is the front page again
    (tmp_path / 'search').mkdir()
    (tmp_path / 'search' / 'index.html').write_text(listing, encoding='utf-8')

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with kvs.make_scraper() as scraper:
            page = scraper.get(root + '/').text
            assert generic._working_search(page, root, scraper) == ''
    finally:
        server.shutdown()


def test_two_listings_of_the_same_videos_are_recognised():
    from siphon.sites.generic import _same_videos
    home = [{'url': f'https://e.test/v/{n}/'} for n in range(10)]
    same = list(reversed(home))
    other = [{'url': f'https://e.test/v/{n}/'} for n in range(100, 110)]
    assert _same_videos(home, same)
    assert not _same_videos(home, other)
    assert not _same_videos(home, [])


def _tube(tmp_path, titles, search_path=None, search_param='q'):
    """A small site: a front page of videos, and optionally a real search."""
    cards = ''.join(
        f'<a href="/videos/{n}/clip/" title="{t}"><img src="/t{n}.jpg"></a>'
        for n, t in enumerate(titles))
    (tmp_path / 'index.html').write_text(
        '<html><body>' + cards + '</body></html>', encoding='utf-8')
    if search_path:
        folder = tmp_path / search_path
        folder.mkdir(parents=True, exist_ok=True)
        # a CGI-less stand-in: the server returns this for any query, so the
        # test server below rewrites it per request instead
    return cards


def test_the_app_finds_the_search_address_by_trying_and_checking(tmp_path):
    """No search box in the page, and the first shapes answer with rubbish.
    The one that really searches is found, and only that one is kept."""
    import functools, http.server, threading, urllib.parse
    from siphon.sites import generic, kvs

    titles = ['Adriana at the beach', 'Mountain hike', 'Kitchen stories',
              'Adriana again', 'Winter drive', 'Garden work']
    front = ''.join(
        f'<a href="/videos/{n}/clip/" title="{t}"><img src="/t{n}.jpg"></a>'
        for n, t in enumerate(titles))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parts = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parts.query)
            if parts.path == '/':
                body = front
            elif parts.path.startswith('/search/') and '/search/?' not in self.path:
                # the wrong shape: a page of categories, every time
                body = ''.join(
                    f'<a href="/videos/{n}/clip/" title="Category {n}">'
                    f'<img src="/c{n}.jpg"></a>' for n in range(90, 94))
            elif parts.path == '/search' and 'q' in query:
                word = query['q'][0].lower()
                body = ''.join(
                    f'<a href="/videos/{n}/clip/" title="{t}">'
                    f'<img src="/t{n}.jpg"></a>'
                    for n, t in enumerate(titles) if word in t.lower())
            else:
                body = front                      # unknown address -> home
            page = f'<html><body>{body}</body></html>'.encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = f'http://127.0.0.1:{server.server_address[1]}'
    opened = []
    # Looking for a search address must never start the off-screen browser:
    # once per address tried turned adding a site into minutes of waiting,
    # and it only showed up on a machine that actually has one installed.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(generic.real_browser, 'available',
                        lambda: opened.append('asked') or True)
    monkeypatch.setattr(generic.real_browser, 'fetch',
                        lambda *a, **k: pytest.fail('the browser was opened'))
    try:
        with kvs.make_scraper() as scraper:
            home = scraper.get(root + '/').text
            found = generic._working_search(home, root, scraper)
    finally:
        monkeypatch.undo()
        server.shutdown()

    assert found == root + '/search?q={query}', found


def test_a_word_every_video_shares_is_not_used_to_test_the_search():
    """Searching the site's own furniture would match everything and prove
    nothing."""
    from siphon.sites.generic import _probe_words
    listed = [{'title': f'Studio Presents Clip {n}'} for n in range(10)]
    listed.append({'title': 'Studio Presents Avalanche'})
    words = _probe_words(listed)
    assert 'studio' not in words and 'presents' not in words
    assert 'avalanche' in words


def _pager_site(always_the_front_page, tmp_path):
    """A site serving a listing, which either answers ?page=2 properly or
    ignores it and hands back the front page — which is what most sites that
    do not paginate by address actually do."""
    import functools
    import http.server
    import threading

    def cards(first, count=5):
        return ''.join(
            f'<a href="/videos/{n}/clip/" title="Clip {n}">'
            f'<img src="/t{n}.jpg"></a>'
            for n in range(first, first + count))

    page_one = '<html><body>' + cards(1) + '</body></html>'
    page_two = '<html><body>' + cards(50) + '</body></html>'

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            wants_two = 'page=2' in self.path or self.path.rstrip('/').endswith('/2')
            body = page_one if (always_the_front_page or not wants_two) else page_two
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body.encode('utf-8'))

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}'


def _browser_for(root, monkeypatch):
    from siphon.core import config
    store = {}
    monkeypatch.setattr(config, 'get_site_profile', lambda host: dict(store))
    monkeypatch.setattr(config, 'set_site_profile',
                        lambda host, profile: store.update(profile))

    class Site(gb.GenericBrowser):
        NAME = 'Test'
        ROOT = root

    Site._learned = None
    Site._home_videos = None
    return Site, store


def test_a_site_that_ignores_page_two_is_not_reported_as_paging(monkeypatch):
    """The bug this guards: the reader accepted page two as soon as videos
    came back.  A site that hands the front page back always returns videos,
    so every spelling looked right and the user stayed on page one."""
    import pathlib
    import tempfile
    server, root = _pager_site(True, pathlib.Path(tempfile.mkdtemp()))
    try:
        Site, store = _browser_for(root, monkeypatch)
        videos = Site.fetch_page(Site.page_url(root + '/', 2))
        assert videos == []
        # And nothing was learned, so it is not believed next time either.
        assert store.get('page_form_ok') != '1'
    finally:
        server.shutdown()


def test_a_site_that_really_pages_is_learned_and_remembered(monkeypatch):
    import pathlib
    import tempfile
    server, root = _pager_site(False, pathlib.Path(tempfile.mkdtemp()))
    try:
        Site, store = _browser_for(root, monkeypatch)
        videos = Site.fetch_page(Site.page_url(root + '/', 2))
        assert [v['title'] for v in videos][:2] == ['Clip 50', 'Clip 51']
        assert store.get('page_form') == 'query:page'
        assert store.get('page_form_ok') == '1'
    finally:
        server.shutdown()


def test_a_proved_page_spelling_is_tried_first(monkeypatch):
    """Once proved, the spelling is used straight away: no site should be
    asked for four addresses on every page turn."""
    import pathlib
    import tempfile
    server, root = _pager_site(False, pathlib.Path(tempfile.mkdtemp()))
    try:
        Site, store = _browser_for(root, monkeypatch)
        store.update({'page_form': 'query:page', 'page_form_ok': '1'})
        assert Site._page_candidates('', root + '/')[0] == 'query:page'
    finally:
        server.shutdown()


def test_the_page_address_can_be_read_out_of_a_data_attribute():
    """Kernel Video Sharing, the engine most added sites run, writes its
    pager as links to '#' and keeps the real address in data-parameters.
    Nothing is hidden there — the address exists, just not in the href."""
    pager = ('<a href="#videos" data-block-id="list_videos_common_videos_list"'
             ' data-parameters="sort_by:post_date;from:2">2</a>')
    built = gb.inpage_page_url(pager, 'https://e.test/', 2)
    assert built.startswith('https://e.test/?')
    assert 'function=get_block' in built
    assert 'block_id=list_videos_common_videos_list' in built
    assert 'from=2' in built


def test_the_sort_being_viewed_wins_over_the_pagers_own():
    pager = ('<a href="#videos" data-block-id="list_videos_common_videos_list"'
             ' data-parameters="sort_by:post_date;from:2">2</a>')
    built = gb.inpage_page_url(pager, 'https://e.test/?sort_by=rating', 3)
    assert 'sort_by=rating' in built
    assert 'sort_by=post_date' not in built
    assert built.count('sort_by=') == 1


def test_a_page_with_no_such_pager_builds_no_address():
    assert gb.inpage_page_url('<html><body>nothing</body></html>',
                              'https://e.test/', 2) == ''


def _kvs_pager_site(honour_the_block):
    """A site whose only pager is a '#' link with data-parameters, and which
    either answers the block address or does not."""
    import http.server
    import threading

    def cards(first, count=5):
        return ''.join(
            f'<a href="/videos/{n}/clip/" title="Clip {n}">'
            f'<img src="/t{n}.jpg"></a>' for n in range(first, first + count))

    pager = ('<div class="pagination"><a href="#list" '
             'data-block-id="list_videos_common_videos_list" '
             'data-parameters="sort_by:post_date;from:2">2</a></div>')
    front = '<html><body>' + cards(1) + pager + '</body></html>'
    block = '<html><body>' + cards(50) + '</body></html>'

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if 'function=get_block' in self.path and honour_the_block:
                body = block
            elif 'page=' in self.path or self.path.rstrip('/').endswith('/2'):
                self.send_error(404)
                return
            else:
                body = front
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(body.encode('utf-8'))

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}'


def test_a_site_paging_only_through_its_data_attributes_still_turns_pages(
        monkeypatch):
    """The AJAX-only pager case: every ordinary page address 404s or hands the
    listing back, and the only real one is in the pager's data-parameters."""
    server, root = _kvs_pager_site(True)
    try:
        Site, store = _browser_for(root, monkeypatch)
        videos = Site.fetch_page(Site.page_url(root + '/', 2))
        assert [v['title'] for v in videos][:2] == ['Clip 50', 'Clip 51']
        assert store.get('page_form') == gb.INPAGE_FORM
        assert store.get('page_form_ok') == '1'
    finally:
        server.shutdown()


def test_the_data_attribute_address_is_checked_like_any_other(monkeypatch):
    """It gets no special trust: a block address that hands back the same
    videos is refused exactly as ?page=2 would be."""
    server, root = _kvs_pager_site(False)
    try:
        Site, store = _browser_for(root, monkeypatch)
        assert Site.fetch_page(Site.page_url(root + '/', 2)) == []
        assert store.get('page_form_ok') != '1'
    finally:
        server.shutdown()


def test_an_empty_listing_says_why_it_is_empty():
    """"0 videos" names the step that stopped and nothing about the cause,
    so every such site had to be opened by hand to find out.  The page is
    already in hand; it can say it itself."""
    page = '<html><body>' + ''.join(
        f'<div class=card><a href=/v{n}-clip.html>Clip {n}</a></div>'
        for n in range(40)) + '</body></html>'

    assert gb.parse_videos(page, ROOT) == []
    why = gb.why_no_listing(page, ROOT)
    assert '40 links' in why
    assert 'no picture in the link' in why
    assert 'outside the link' in why


def test_a_page_that_does_give_videos_explains_nothing():
    assert gb.why_no_listing(LISTING, ROOT) == ''


def test_links_to_other_sites_are_counted_as_such():
    page = ('<html><body>'
            '<a href="https://elsewhere.test/x"><img src=/a.jpg></a>'
            '<a href="https://elsewhere.test/y"><img src=/b.jpg></a>'
            '</body></html>')
    assert 'off site' in gb.why_no_listing(page, ROOT)


# ── cards whose picture is not inside the link ────────────────────────────

RUMBLE_SHAPED = '<html><body>' + ''.join(
    f'<div class="videostream"><img class="thumb" src="/t{n}.jpg">'
    f'<a class="link" href="/v6{n}abc-a-clip-{n}.html">Clip {n}</a></div>'
    for n in range(6)) + '</body></html>'


def test_a_card_is_read_when_its_picture_sits_beside_the_link():
    """Rumble builds a card as a box holding a picture and, beside it, a
    link.  Every link was passed over for having no picture of its own, so
    the whole listing read as empty."""
    videos = gb.parse_videos(RUMBLE_SHAPED, ROOT)
    assert len(videos) == 6
    assert videos[0]['title'] == 'Clip 0'
    assert videos[0]['thumbnail'] == 'https://example.com/t0.jpg'


def test_a_picture_is_never_claimed_by_one_of_several_links():
    """A box with two links gives no way to know whose picture it is, and
    guessing brings back rows showing another video's thumbnail."""
    shared = ('<html><body><div class="row"><img src="/one.jpg">'
              '<a href="/v1abc-first.html">First</a>'
              '<a href="/v2abc-second.html">Second</a></div></body></html>')
    assert gb.parse_videos(shared, ROOT) == []


def test_the_search_for_a_picture_does_not_reach_the_whole_page():
    """Far enough up and any picture would be claimed by any link."""
    deep = ('<html><body><img src="/banner.jpg">'
            '<div><div><div><div><div>'
            '<a href="/v1abc-first.html">First</a>'
            '</div></div></div></div></div></body></html>')
    assert gb.parse_videos(deep, ROOT) == []


def test_a_picture_inside_the_link_still_wins():
    both = ('<html><body><div><img src="/outside.jpg">'
            '<a href="/v1abc-first.html"><img src="/inside.jpg">First</a>'
            '</div></body></html>')
    found = gb.parse_videos(both, ROOT)
    assert found and found[0]['thumbnail'].endswith('/inside.jpg')


@pytest.mark.parametrize('path,shape', [
    ('/v6abc-some-title.html', '/*'),
    ('/v6def-another-one.html', '/*'),
    ('/watch/12345.php', '/watch/#'),
    ('/videos/12/clip/', '/videos/#/*'),
])
def test_a_page_ending_does_not_split_one_family_into_many(path, shape):
    """'/v6abc-a.html' and '/v6def-b.html' are the same family.  While the
    ending counted as part of the name, each address was a family of one and
    none ever reached the three links a listing needs."""
    assert gb._shape(path) == shape


def test_an_ordinary_page_is_not_swept_in_as_a_video():
    assert gb._shape('/about.html') == '/about.html'
    assert gb._shape('/terms.php') == '/terms.php'


# ── a card that links to the same video twice ────────────────────────────

TWO_LINKS_PER_CARD = '<html><body>' + ''.join(
    f'<div class="thumb-block">'
    f'<div class="thumb"><a href="/video-{n}abc/real-title-{n}">'
    f'<img src="/t{n}.jpg"></a></div>'
    f'<div class="thumb-under"><p>'
    f'<a href="/video-{n}abc/real-title-{n}">Real Title {n}</a></p></div>'
    f'</div>' for n in range(8)) + '</body></html>'


def test_a_cards_title_is_taken_from_whichever_link_carries_it():
    """A card links to the video twice: once around the picture, once around
    the title.  Only the picture link counts as a card, so the one holding
    the name was dropped and rows came out named after the address."""
    videos = gb.parse_videos(TWO_LINKS_PER_CARD, ROOT)
    assert len(videos) == 8
    assert videos[0]['title'] == 'Real Title 0'
    assert videos[0]['thumbnail'] == 'https://example.com/t0.jpg'
    for video in videos:
        assert video['url'] not in video['title']


def test_the_longest_name_wins_among_several_links_to_one_video():
    """A card also links to a video from "3 comments" and the like."""
    page = ('<html><body><div class="card">'
            '<a href="/video-1abc/x"><img src="/t.jpg"></a>'
            '<a href="/video-1abc/x">12 comments</a>'
            '<a href="/video-1abc/x">The Real Title Of This Video</a>'
            '</div></body></html>')
    found = gb.parse_videos(page, ROOT)
    assert found[0]['title'] == 'The Real Title Of This Video'


def test_a_card_with_its_own_title_is_left_alone():
    page = ('<html><body><div class="card">'
            '<a href="/video-1abc/x" title="Its Own Title">'
            '<img src="/t.jpg"></a></div></body></html>')
    assert gb.parse_videos(page, ROOT)[0]['title'] == 'Its Own Title'


# ── the shape sample a report carries ────────────────────────────────────

def test_the_page_describes_its_own_shape():
    """A site whose listing cannot be read can only be fixed by seeing how
    its page is built, and nobody should have to save a page and send it."""
    page = ('<html><body><div class="content">' + ''.join(
        f'<div class="videostream thumbnail__grid">'
        f'<div class="thumbnail__thumb">'
        f'<img class="thumbnail__image" src="/t{n}.jpg"></div>'
        f'<a class="videostream__link" href="/v6{n}abc-clip.html">Clip</a>'
        f'</div>' for n in range(9)) + '</div></body></html>')
    sample = gb.page_shape_sample(page, ROOT)

    assert '9 links shaped' in sample
    assert 'a.videostream__link' in sample
    assert 'div.videostream' in sample
    assert '0 of them with a picture inside' in sample
    assert '1 level(s) up' in sample


def test_the_sample_describes_the_listing_not_the_menu():
    """The first links on any page are its menu; describing those says
    nothing, which is what the first version of this did."""
    page = ('<html><body>'
            '<header class="header"><div class="header-div">'
            + ''.join(f'<a class="nav" href="/page{n}">Menu {n}</a>'
                      for n in range(6)) +
            '</div></header><div class="content">'
            + ''.join(f'<div class="card"><img src="/t{n}.jpg">'
                      f'<a class="link" href="/v6{n}abc-clip.html">Clip</a>'
                      f'</div>' for n in range(9)) +
            '</div></body></html>')
    sample = gb.page_shape_sample(page, ROOT)

    assert 'a.link' in sample
    assert 'header' not in sample
    assert 'Menu' not in sample


def test_the_families_are_listed_largest_first():
    page = ('<html><body><div class="content">'
            + ''.join(f'<a href="/v6{n}abc-clip.html">Clip</a>'
                      for n in range(20))
            + ''.join(f'<a href="/c/cat{n}">Cat</a>' for n in range(4))
            + '</div></body></html>')
    sample = gb.page_shape_sample(page, ROOT)
    assert sample.index('20 links shaped') < sample.index('4 links shaped')


def test_the_shape_sample_carries_no_titles_or_addresses():
    """It may travel in a public issue, so it holds the page's bones and
    nothing about what is on it."""
    page = ('<html><body><div class="card">'
            '<a href="/video-1abc/a-very-private-title">'
            'A Very Private Title</a></div></body></html>')
    sample = gb.page_shape_sample(page, ROOT)

    assert 'A Very Private Title' not in sample
    assert 'a-very-private-title' not in sample
    assert 'video-1abc' not in sample


def test_only_a_few_families_are_described():
    page = '<html><body><div class="content">' + ''.join(
        f'<a href="/kind{n % 9}/v{n}abc-x.html">Clip</a>'
        for n in range(50)) + '</div></body></html>'
    assert gb.page_shape_sample(page, ROOT).count('links shaped') <= 4


def _tiles_and_videos_home():
    """A home page like a category portal's: many big picture tiles for categories, and
    fewer cards for real videos."""
    tiles = ''.join(
        f'<div class="tile"><a href="/tags/cat{n}"><img src="/t/{n}.jpg">'
        f'<b>Category {n}</b></a></div>' for n in range(12))
    cards = ''.join(
        f'<div class="thumb-block"><a href="/video-ab{n}cd/clip_{n}">'
        f'<img src="/v/{n}.jpg"></a>'
        f'<p><a href="/video-ab{n}cd/clip_{n}" title="Clip {n} full">Clip {n} full</a></p></div>'
        for n in range(5))
    return f'<html><body>{tiles}<div id="v">{cards}</div></body></html>'


def _portal_like(monkeypatch, store_start):
    Site, store = _browser_for('http://site.test', monkeypatch)
    store.update(store_start)
    page = _tiles_and_videos_home()
    monkeypatch.setattr(Site, '_get', classmethod(lambda cls, url, render=False: page))
    return Site, store


def test_a_taught_video_shape_is_not_replaced_by_the_tiles(monkeypatch):
    """The bug: Browse re-guessed the shape from the home page on every open,
    chose the category tiles, and showed them as videos."""
    from siphon.sites import generic
    page = ('<html><body><video><source src="http://site.test/v.mp4"></video>'
            '</body></html>')
    learned = generic.learn_from_html(
        page, 'http://site.test/video-abxcd/some_title')['profile']
    assert learned['video_shape_ok'] == '1'
    shape = learned['video_shape']
    Site, store = _portal_like(monkeypatch, {'video_shape': shape,
                                             'video_shape_ok': '1'})
    Site.fetch_categories()
    assert store['video_shape'] == shape
    videos = Site.fetch_page('http://site.test/')
    assert videos and all('/video-' in v['url'] for v in videos)
    assert not any('/tags/' in v['url'] for v in videos)


def test_a_taught_shape_that_matches_nothing_shows_nothing(monkeypatch):
    """Better an empty page than category tiles dressed up as videos."""
    Site, store = _portal_like(monkeypatch, {'video_shape': '/nothing-like-this/*',
                                             'video_shape_ok': '1'})
    assert Site.fetch_page('http://site.test/') == []
    assert store['video_shape'] == '/nothing-like-this/*'


def test_a_shape_nobody_proved_is_still_guessed(monkeypatch):
    Site, store = _portal_like(monkeypatch, {})
    assert Site.fetch_page('http://site.test/')


def test_a_browser_that_will_not_start_does_not_take_the_sections_down(monkeypatch):
    """The bug: a proved shape found no cards in the plain page, the browser
    was tried as a second read, it failed, and the failure escaped as
    "Failed to load categories" for a page that had been read fine."""
    from siphon.core import browser as real_browser
    shape = gb._shape('/video-abxcd/some_title-here')
    Site, store = _portal_like(monkeypatch, {'video_shape': '/gone/*',
                                             'video_shape_ok': '1'})
    monkeypatch.setattr(real_browser, 'available', lambda: True)
    original = Site._get.__func__

    def _get(cls, url, render=None):
        if render:
            raise RuntimeError('the browser did not start')
        return original(cls, url, render)

    monkeypatch.setattr(Site, '_get', classmethod(_get))
    assert Site.fetch_categories()      # the sections came back at all


def test_a_front_page_of_only_categories_opens_on_the_first_category(monkeypatch):
    """A site whose front page is tiles for categories and no videos used to
    open on an empty "Home"."""
    Site, store = _portal_like(monkeypatch, {'video_shape': '/gone/*',
                                             'video_shape_ok': '1'})
    sections = Site.fetch_categories()
    assert sections, 'the categories on the front page were not offered'
    assert sections[0]['name'] != 'Home'


def test_a_front_page_with_videos_still_opens_on_home(monkeypatch):
    Site, store = _portal_like(monkeypatch, {})
    assert Site.fetch_categories()[0]['name'] == 'Home'


def test_a_page_with_no_videos_says_what_it_is(monkeypatch, capsys):
    """The log must answer "what did it read?" so nobody has to save pages."""
    Site, store = _browser_for('http://site.test', monkeypatch)
    page = ('<html><head><title>Are you 18?</title></head><body>'
            'Please confirm your age <a href="/enter">Enter</a></body></html>')
    monkeypatch.setattr(Site, '_get', classmethod(lambda cls, url, render=False: page))
    assert Site.fetch_page('http://site.test/') == []
    out = capsys.readouterr().out
    assert 'this page has no videos' in out
    assert 'Are you 18?' in out
    assert 'Please confirm your age' in out


def test_an_empty_front_page_is_flagged_and_a_category_page_is_not(monkeypatch):
    Site, store = _browser_for('http://site.test', monkeypatch)
    page = '<html><head><title>Hi</title></head><body>nothing</body></html>'
    monkeypatch.setattr(Site, '_get', classmethod(lambda cls, url, render=False: page))
    Site.fetch_page('http://site.test/')
    assert Site.front_page_empty is True
    Site.fetch_page('http://site.test/tags/x')
    assert Site.front_page_empty is False


def test_the_real_search_box_wins_over_a_decoy_form():
    from siphon.sites.genericbrowse import detect_search, detect_search_all
    page = ('<form action="/" method="get"><input name="query"></form>'
            '<form action="/search/video" method="get"><input name="q"></form>')
    assert detect_search(page, 'https://x.com') == 'https://x.com/search/video?q={query}'
    assert len(detect_search_all(page, 'https://x.com')) == 2
