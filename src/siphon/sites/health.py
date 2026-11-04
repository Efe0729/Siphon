"""Noticing that a site has changed, and learning it again.

A site's layout is read once, when the user adds it, and then trusted.
Sites redesign themselves, so that reading goes stale — and the user sees it
as Siphon breaking: rows named after a notice, empty titles, downloads that
find no video.

Checking every site at every launch was considered and rejected: forty sites
times four pages is a hundred and sixty requests the moment the app opens,
which is both the pattern Cloudflare looks for and wasted, since sites do not
change weekly.

This does the opposite.  The app already uses these rules constantly, so it
does not need to go looking: a rule that has stopped working announces itself
by failing.  Three failures on three different videos of one site is not bad
luck, it is a layout that moved.  That is when — once, in the background —
the site is learned again.  Idle costs nothing.
"""

from __future__ import annotations

import threading

from siphon.core import config


# Three, not two: two failures in a row happen on a good site when a video is
# region-locked, taken down, or behind a login.  Three different videos
# failing is the site, not the videos.
FAILURES_BEFORE_RELEARN = 3

_lock = threading.Lock()
_failed = {}            # host -> {url, ...} videos that failed since the last win
_relearning = set()     # hosts being learned right now
_gave_up = set()        # hosts where learning again did not help either


def _host(url):
    from urllib.parse import urlsplit
    import re
    return re.sub(r'^www\.', '', (urlsplit(str(url or '')).hostname or '').lower())


def note_success(url):
    """A video from this site worked, so whatever was failing is not the site."""
    host = _host(url)
    if not host:
        return
    with _lock:
        _failed.pop(host, None)
        _gave_up.discard(host)


def note_failure(url, reason=''):
    """Record a video that could not be read; True when it is time to relearn.

    Counted per video address, not per attempt: retrying one dead video ten
    times says nothing about the site.
    """
    host = _host(url)
    if not host or not config.is_custom_site(host):
        return False
    with _lock:
        if host in _relearning or host in _gave_up:
            return False
        seen = _failed.setdefault(host, set())
        seen.add(str(url))
        if len(seen) < FAILURES_BEFORE_RELEARN:
            return False
        _relearning.add(host)
    print(f'[health] {host}: {len(_failed[host])} videos failed '
          f'({reason or "no reason given"}); learning the site again', flush=True)
    return True


def relearn(host):
    """Read the site again and keep what it teaches.  Returns what changed.

    ('', '') when learning found nothing better, so the caller can offer the
    report button: the app tried by itself and could not fix it.
    """
    from siphon.sites import generic
    host = _host(f'https://{host}') or str(host or '')
    before = config.custom_site_rules(host).get('title_rule', '')
    try:
        found = generic.probe(f'https://{host}/')
    except Exception as exc:
        print(f'[health] {host}: could not be read again: {exc}', flush=True)
        _finish(host, healed=False)
        return before, ''
    after = found.get('title_rule') or ''
    titles = [t for t in (found.get('sample_titles') or []) if t]
    healed = bool(after and titles and len(set(titles)) > 1)
    if healed:
        rules = config.custom_site_rules(host)
        rules['title_rule'] = after
        config.set_custom_site_rules(host, rules)
        if found.get('search'):
            profile = config.get_site_profile(host)
            profile['search'] = found['search']
            config.set_site_profile(host, profile)
        print(f'[health] {host}: titles now read by {after} '
              f'(was {before or "nothing"})', flush=True)
    else:
        print(f'[health] {host}: learning again did not help', flush=True)
    _finish(host, healed)
    return before, (after if healed else '')


def _finish(host, healed):
    with _lock:
        _relearning.discard(host)
        if healed:
            _failed.pop(host, None)
        else:
            # Do not keep retrying a site that cannot be read: the user is
            # offered the report instead.
            _gave_up.add(host)


def needs_report(host):
    """True when the app tried to fix this site itself and could not."""
    return _host(f'https://{host}') in _gave_up or str(host or '') in _gave_up


def heal_in_background(url, on_done=None):
    """Relearn the site behind ``url`` off the main thread, once.

    Call it after ``note_failure`` returned True.  ``on_done(host, before,
    after)`` is called when it finishes, so the interface can say what
    happened or offer the report.
    """
    host = _host(url)
    if not host:
        return

    def work():
        before, after = relearn(host)
        if on_done is not None:
            try:
                on_done(host, before, after)
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()


def forget(host=''):
    """Clear what has been noticed; for tests and for a site being re-added."""
    with _lock:
        if host:
            key = _host(f'https://{host}') or host
            _failed.pop(key, None)
            _relearning.discard(key)
            _gave_up.discard(key)
        else:
            _failed.clear()
            _relearning.clear()
            _gave_up.clear()
