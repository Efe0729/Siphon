"""Noticing a site has changed, and learning it again by itself.

The point of these is that nothing happens while things work, that a dead
video does not count as a broken site, and that the app gives up rather than
hammering a site it cannot read.
"""

import pytest

from siphon.core import config
from siphon.sites import health


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    health.forget()
    monkeypatch.setattr(config, 'is_custom_site', lambda host: True)
    yield
    health.forget()


def _url(n):
    return f'https://e.test/v/{n}'


def test_one_failure_changes_nothing():
    """A single video can be region-locked or taken down; that is not the
    site changing its layout."""
    assert health.note_failure(_url(1), 'no video') is False


def test_the_same_video_failing_over_and_over_is_still_one_failure():
    """Retrying one dead video says nothing new about the site."""
    for _ in range(10):
        assert health.note_failure(_url(1), 'no video') is False


def test_three_different_videos_failing_triggers_relearning():
    assert health.note_failure(_url(1)) is False
    assert health.note_failure(_url(2)) is False
    assert health.note_failure(_url(3)) is True


def test_a_video_that_works_clears_what_was_counted():
    """The rule is evidently still fine, so earlier failures were the videos."""
    health.note_failure(_url(1))
    health.note_failure(_url(2))
    health.note_success(_url(9))
    assert health.note_failure(_url(3)) is False


def test_it_asks_to_relearn_only_once_while_already_doing_it():
    """Twenty queued videos failing must not start twenty relearns."""
    for n in range(1, 4):
        triggered = health.note_failure(_url(n))
    assert triggered is True
    for n in range(4, 20):
        assert health.note_failure(_url(n)) is False


def test_a_site_that_is_not_the_users_is_not_watched(monkeypatch):
    monkeypatch.setattr(config, 'is_custom_site', lambda host: False)
    for n in range(1, 6):
        assert health.note_failure(_url(n)) is False


def test_learning_again_keeps_a_rule_that_now_works(monkeypatch):
    """The quiet half of the feature: the user sees names come back and is
    never asked anything."""
    saved = {'title_rule': 'title_tag'}
    monkeypatch.setattr(config, 'custom_site_rules', lambda host: dict(saved))
    monkeypatch.setattr(config, 'set_custom_site_rules',
                        lambda host, rules: saved.update(rules))
    monkeypatch.setattr(config, 'get_site_profile', lambda host: {})
    monkeypatch.setattr(config, 'set_site_profile', lambda host, profile: None)

    from siphon.sites import generic
    monkeypatch.setattr(generic, 'probe', lambda url: {
        'title_rule': 'player_heading',
        'sample_titles': ['First', 'Second', 'Third'], 'search': ''})

    before, after = health.relearn('e.test')
    assert (before, after) == ('title_tag', 'player_heading')
    assert saved['title_rule'] == 'player_heading'
    assert health.needs_report('e.test') is False


def test_a_relearn_that_finds_the_same_notice_again_asks_for_a_report(monkeypatch):
    """Learning found a rule, but it still names every video the same, so the
    app cannot fix this one and says so instead of pretending."""
    monkeypatch.setattr(config, 'custom_site_rules', lambda host: {})
    from siphon.sites import generic
    monkeypatch.setattr(generic, 'probe', lambda url: {
        'title_rule': 'title_tag',
        'sample_titles': ['New Backup Domain'] * 3})

    _before, after = health.relearn('e.test')
    assert after == ''
    assert health.needs_report('e.test') is True


def test_a_site_it_cannot_reach_is_not_hammered(monkeypatch):
    """Learning failed, so no further relearn is started for this site."""
    monkeypatch.setattr(config, 'custom_site_rules', lambda host: {})
    from siphon.sites import generic

    def refuse(_url):
        raise Exception('blocked')

    monkeypatch.setattr(generic, 'probe', refuse)
    health.relearn('e.test')
    assert health.needs_report('e.test') is True
    for n in range(1, 10):
        assert health.note_failure(_url(n)) is False


def test_a_site_working_again_clears_the_report_request(monkeypatch):
    monkeypatch.setattr(config, 'custom_site_rules', lambda host: {})
    from siphon.sites import generic
    monkeypatch.setattr(generic, 'probe', lambda url: {'title_rule': '',
                                                       'sample_titles': []})
    health.relearn('e.test')
    assert health.needs_report('e.test') is True
    health.note_success(_url(1))
    assert health.needs_report('e.test') is False
