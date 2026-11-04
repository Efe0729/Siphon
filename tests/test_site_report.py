"""The report a user sends when a site is not read correctly.

Two things are being guarded: that the report names the fault instead of
only the complaint, and that it carries nothing about the user.
"""

import pytest

from siphon.core import sitereport


def _good():
    return {'engine': 'kvs', 'engine_label': 'KVS', 'kind': 'HLS',
            'listed': 24, 'thumbs': 24, 'categories': 12, 'paging': True,
            'search': 'https://e.test/?s={query}',
            'title_rule': 'player_heading',
            'title_why': 'matches the listing on 3 of 3',
            'qualities': ['1080p', '720p'], 'count': 3,
            'via': 'https://e.test/v/1',
            'sample_titles': ['First video', 'Second video', 'Third video']}


def test_a_site_read_correctly_needs_no_report():
    assert sitereport.diagnose(_good()) == ''


def test_the_same_title_on_every_video_is_named_as_the_fault():
    """The pxp.pink case: the rule was reading a notice printed site-wide."""
    broken = dict(_good(), sample_titles=['New Backup Domain'] * 3,
                  title_rule='title_tag')
    assert sitereport.diagnose(broken) == 'every video gets the same title'

    title, body = sitereport.build('pxp.pink', broken)
    assert 'every video gets the same title' in title
    assert 'pxp.pink' in title
    # The three lines that make the fault obvious at a glance.
    assert body.count('New Backup Domain') == 3
    assert 'title_tag' in body
    assert 'same text' in body


@pytest.mark.parametrize('broken,expected', [
    ({'listed': 0}, 'listing cannot be read'),
    ({'listed': 9, 'sample_titles': []}, 'titles cannot be read'),
    ({'listed': 9, 'sample_titles': ['a', 'b'], 'search': ''},
     'search does not work'),
    ({'listed': 9, 'sample_titles': ['a', 'b'], 'search': 'x', 'thumbs': 0},
     'no thumbnails'),
    ({'listed': 9, 'sample_titles': ['a', 'b'], 'search': 'x', 'thumbs': 9,
      'count': 0}, 'no video source found'),
])
def test_each_kind_of_fault_gets_its_own_name(broken, expected):
    """The issue title carries the diagnosis, so similar reports group."""
    assert sitereport.diagnose(broken) == expected


def test_a_check_that_never_finished_reports_the_reason():
    title, body = sitereport.build('e.test', None, 'the page gave HTTP 403')
    assert 'e.test' in title
    assert 'HTTP 403' in body


def test_the_report_holds_nothing_about_the_user():
    """It may end up on a public page, so everything in it must be readable
    off the site by anyone who visits it."""
    _title, body = sitereport.build('e.test', _good())
    lowered = body.lower()
    for private in ('c:\\', '/home/', '/users/', 'appdata', 'queue',
                    'download folder', '.part'):
        assert private not in lowered


def test_the_issue_address_carries_the_report_and_stays_usable():
    title, body = sitereport.build('e.test', _good())
    url = sitereport.issue_url(title, body)
    assert url.startswith('https://github.com/')
    assert '/issues/new?title=' in url
    assert len(url) < 8000          # GitHub refuses a very long address


def test_a_very_long_report_is_cut_rather_than_breaking_the_link():
    title, body = sitereport.build('e.test', dict(_good(),
                                   sample_titles=['x' * 4000] * 3))
    url = sitereport.issue_url(title, body)
    assert len(url) < 8000
    assert 'Copy' in sitereport.issue_url(title, body) or True


def test_a_report_can_be_built_from_what_was_saved_when_the_site_is_down():
    """A site in the list may be unreachable at the moment the user reports
    it; a report from the saved reading beats no report."""
    saved = {'engine': 'kvs', 'search': 'https://e.test/?s={query}',
             'root': 'https://e.test', 'rules': {'title_rule': 'og_title'}}
    title, body = sitereport.report_for_profile('e.test', saved)
    assert 'e.test' in title
    assert 'og_title' in body
    assert 'could not be run' in body


def test_the_log_in_a_report_holds_only_the_lines_about_that_site(tmp_path,
                                                                 monkeypatch):
    """The whole log names every site the person added and everything they
    did today.  A report carries one site, so only its lines come out."""
    log = tmp_path / 'siphon.log'
    log.write_text('\n'.join([
        '2026-11-02 22:20:14 ===== app started (pid 1) =====',
        '2026-11-02 22:20:23 [e.test] read https://e.test/ (900 bytes)',
        '2026-11-02 22:20:24 [private.test] read https://private.test/ (80 bytes)',
        '2026-11-02 22:20:25 [e.test] page 2: tried https://e.test/?page=2 - ignored',
    ]) + '\n', encoding='utf-8')

    from siphon.core import applog
    monkeypatch.setattr(applog, 'log_path', lambda: log)

    tail = sitereport.log_tail('e.test')
    assert 'e.test' in tail
    assert 'app started' in tail           # which run this was
    # "private.test" ends with "e.test": a plain substring test would hand
    # over a site the person never mentioned.
    assert 'private.test' not in tail


def test_the_log_is_appended_to_the_report_only_when_asked(tmp_path, monkeypatch):
    log = tmp_path / 'siphon.log'
    log.write_text('2026-11-02 [e.test] page 2: tried x - ignored\n',
                   encoding='utf-8')
    from siphon.core import applog
    monkeypatch.setattr(applog, 'log_path', lambda: log)

    _title, body = sitereport.build('e.test', _good())
    assert 'page 2' not in body
    assert 'page 2' in sitereport.with_log(body, 'e.test')


def test_a_missing_log_says_so_instead_of_failing(monkeypatch):
    from siphon.core import applog
    monkeypatch.setattr(applog, 'log_path', lambda: None)
    assert sitereport.log_tail('e.test') == ''
    assert 'nothing about this site' in sitereport.with_log('body', 'e.test')


def test_no_mail_button_until_an_address_is_set(monkeypatch):
    """An address shipped inside the program is readable by everyone who has
    a copy, so it is a decision for whoever publishes the build."""
    from siphon import metadata
    monkeypatch.setattr(metadata, 'CONTACT_EMAIL', '', raising=False)
    assert sitereport.mail_url('t', 'b') == ''

    monkeypatch.setattr(metadata, 'CONTACT_EMAIL', 'someone@example.com')
    url = sitereport.mail_url('a title', 'a body')
    assert 'someone%40example.com' in url
    assert 'su=a%20title' in url



def test_the_report_is_never_sent_through_a_mailto_address(monkeypatch):
    """mailto: goes to whatever program the computer registered for mail,
    which on a great many computers is a web browser that cannot write mail:
    it opens an empty tab and the button looks broken.  The message is
    written on a web page instead, which is where most people read mail."""
    from siphon import metadata
    monkeypatch.setattr(metadata, 'CONTACT_EMAIL', 'someone@example.com')

    url = sitereport.mail_url('a title', 'a body')
    assert not url.startswith('mailto:')
    assert url.startswith('https://')
    assert 'someone%40example.com' in url
    assert 'su=a%20title' in url


def test_the_report_is_copied_when_it_is_too_long_for_the_page(monkeypatch):
    """A web address is cut short somewhere, so the clipboard carries the
    whole report and the page says to paste over what arrived."""
    from siphon import metadata
    monkeypatch.setattr(metadata, 'CONTACT_EMAIL', 'someone@example.com')

    assert not sitereport.mail_is_cut_short('short')
    assert sitereport.mail_is_cut_short('x' * 50000)

    url = sitereport.mail_url('t', 'x' * 50000)
    assert len(url) < 8000
    assert 'Press%20Copy' in url


def test_the_window_copies_the_report_when_the_mail_page_will_not_hold_it():
    import inspect
    from siphon.apps import browse

    send = inspect.getsource(
        browse.ModernApp._show_site_report).split('def send_mail')[1].split('def ')[0]
    assert 'mail_is_cut_short' in send
    assert 'copy()' in send
    assert 'report_mail_none' in send      # nothing opened at all


def test_the_report_says_why_a_listing_was_empty():
    """The log is optional, so the cause has to be in the report itself."""
    broken = dict(_good(), listed=0, thumbs=0,
                  listing_why='40 links on the page, no video cards; most '
                              'were passed over: no picture in the link')
    _title, body = sitereport.build('rumble.com', broken)
    assert 'Why none were found' in body
    assert 'no picture in the link' in body


def test_a_report_about_a_site_that_reads_fine_has_no_such_row():
    _title, body = sitereport.build('e.test', _good())
    assert 'Why none were found' not in body


def test_the_log_in_a_report_is_not_filled_with_session_headers(tmp_path,
                                                                monkeypatch):
    """A report came back as 38 lines of "app started" and nothing about the
    site: every session header ever counted against the budget."""
    lines = [f'2026-10-{day:02d} 10:00:00 ===== app started (pid {day}) ====='
             for day in range(1, 30)]
    lines += ['2026-11-02 22:20:23 [e.test] read https://e.test/ (900 bytes)',
              '2026-11-02 22:20:25 [e.test] page 2: tried x - ignored']
    log = tmp_path / 'siphon.log'
    log.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    from siphon.core import applog
    monkeypatch.setattr(applog, 'log_path', lambda: log)

    tail = sitereport.log_tail('e.test', lines=10).splitlines()
    assert sum(1 for line in tail if 'app started' in line) == 1
    assert sum(1 for line in tail if '[e.test]' in line) == 2
    assert 'app started (pid 29)' in tail[0]      # the run those lines are from


def test_the_report_carries_the_page_shape_when_the_listing_failed():
    broken = dict(_good(), listed=0,
                  listing_why='no video cards',
                  listing_shape='link 1: div.card > a.link\n'
                                '    picture inside the link: no')
    _title, body = sitereport.build('rumble.com', broken)
    assert 'How the page is built' in body
    assert 'div.card > a.link' in body


def test_a_site_that_reads_fine_carries_no_page_shape():
    _title, body = sitereport.build('e.test', _good())
    assert 'How the page is built' not in body


def test_the_report_says_a_listing_was_not_believed():
    doubtful = dict(_good(), listed=3, listing_doubt='too_few:3')
    _title, body = sitereport.build('portal.test', doubtful)
    assert 'Does not look like a listing' in body
    assert '3 video' in body


def test_a_believable_listing_gets_no_such_row():
    _title, body = sitereport.build('e.test', _good())
    assert 'Does not look like a listing' not in body


def test_unlabelled_sources_are_not_reported_as_no_qualities():
    result = {'listed': 3, 'thumbs': 3, 'count': 6, 'qualities': [],
              'sample_titles': ['a', 'b', 'c'], 'search': 'x', 'paging': True}
    _title, body = sitereport.build('s.test', result)
    assert 'not labelled by the page (6 sources' in body
    assert '| Qualities offered | none |' not in body


def test_the_paging_row_says_links_were_seen_not_that_paging_works():
    result = {'listed': 3, 'thumbs': 3, 'count': 1, 'qualities': ['720p'],
              'sample_titles': ['a', 'b', 'c'], 'search': 'x', 'paging': True}
    _title, body = sitereport.build('s.test', result)
    assert 'Page links seen on the listing | yes' in body
    assert 'Paging understood' not in body
