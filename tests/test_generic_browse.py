"""Browsing a site the user added, worked out from the site's own pages."""

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
