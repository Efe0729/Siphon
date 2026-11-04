"""The ordering shared between sites.

What is shared is only which rules have been right before; no site's own
answer is ever copied to another site.  A wrong ordering must therefore cost
nothing but a little time, never a wrong title.
"""

import pytest

from siphon.core import config
from siphon.sites import generic


@pytest.fixture
def wins(monkeypatch):
    """A tally that lives only in this test."""
    tally = {}
    monkeypatch.setattr(config, 'rule_wins', lambda: dict(tally))
    return tally


def test_a_fresh_install_uses_the_built_in_order(wins):
    assert generic.rule_order() == generic.TITLE_RULE_ORDER


def test_a_rule_that_worked_on_more_sites_is_tried_first(wins):
    wins.update({'title_tag': 7, 'og_title': 3})
    order = generic.rule_order()
    assert order[0] == 'title_tag'
    assert order[1] == 'og_title'
    # Every rule is still in the list: nothing is dropped for being unpopular.
    assert set(order) == set(generic.TITLE_RULE_ORDER)


def test_rules_with_the_same_score_keep_the_built_in_order(wins):
    wins.update({'first_h1': 2, 'og_title': 2})
    order = generic.rule_order()
    assert order.index('og_title') < order.index('first_h1')


def test_the_ordering_never_overrides_what_the_site_itself_says(wins):
    """The whole safety argument in one test: the tally says title_tag, the
    site's listing says player_heading, and the site wins."""
    wins.update({'title_tag': 50})
    pages = [
        ('<title>Site Notice</title><h1 class="player">First video</h1>', 'https://e.test/1'),
        ('<title>Site Notice</title><h1 class="player">Second video</h1>', 'https://e.test/2'),
        ('<title>Site Notice</title><h1 class="player">Third video</h1>', 'https://e.test/3'),
    ]
    listed = ['First video', 'Second video', 'Third video']
    rule, why = generic.learn_title_rule(pages, listed)
    assert rule != 'title_tag'
    assert 'matches the listing' in why


def test_a_site_is_counted_once_however_many_times_it_is_added(tmp_path, monkeypatch):
    """The tally counts sites, not videos or re-checks."""
    store = {}
    monkeypatch.setattr(config, '_load_prefs', lambda: dict(store))
    monkeypatch.setattr(config, '_save_prefs', lambda prefs: store.update(prefs))

    for _ in range(5):
        config.note_rule_win('og_title', 'e.test')
    assert config.rule_wins() == {'og_title': 1}


def test_a_site_that_changes_its_rule_moves_its_vote(monkeypatch):
    """A site redesigned and now needs another rule: its old vote goes with
    it, otherwise the tally would count one site twice."""
    store = {}
    monkeypatch.setattr(config, '_load_prefs', lambda: dict(store))
    monkeypatch.setattr(config, '_save_prefs', lambda prefs: store.update(prefs))

    config.note_rule_win('og_title', 'e.test')
    config.note_rule_win('player_heading', 'other.test')
    config.note_rule_win('player_heading', 'e.test')

    assert config.rule_wins() == {'player_heading': 2}
