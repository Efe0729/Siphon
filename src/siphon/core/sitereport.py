"""The report a user sends when a site is not read correctly.

Siphon ships with no sites in it: every address it can download from is one
somebody added, and when the reading goes wrong only that person can see how.
A report turns what they can see into something that can be acted on.

Two rules shape what goes in it.

It carries the diagnosis, not just the complaint.  "pxp.pink does not work"
costs a day of guessing; the same report saying the title came from
``title_tag`` and was the same text on all three videos names the fault
outright.  So the report holds what the check worked out, field by field,
and the three sample titles beside the rule each came from.

It carries nothing else.  A report may end up in a public issue, so it holds
one site and the reading of that site: no download history, no queue, no other
sites the person added, no file paths from their computer.  Everything in it
can be read off the site by anyone who visits it.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

from siphon import metadata


# What is wrong, in the words the issue title will use.  Ordered: the first
# one that fits is the heading, because a site whose listing cannot be read
# has nothing to say about its titles.
def diagnose(result):
    """A short phrase naming the fault, or '' when the reading looks sound."""
    if not result:
        return 'site could not be read'
    if not int(result.get('listed') or 0):
        return 'listing cannot be read'
    titles = [t for t in (result.get('sample_titles') or []) if t]
    if not titles:
        return 'titles cannot be read'
    if len(titles) > 1 and len(set(titles)) == 1:
        # Every video came back with the same name: the rule is reading
        # something the site prints on every page.
        return 'every video gets the same title'
    if not result.get('search'):
        return 'search does not work'
    if not int(result.get('thumbs') or 0):
        return 'no thumbnails'
    if not int(result.get('count') or 0):
        return 'no video source found'
    return ''


def _doubt(result):
    """Why the listing that was read is not believed, in English."""
    from siphon.sites.generic import doubt_in_english
    return doubt_in_english(result.get('listing_doubt'))


def _qualities_text(qualities, result):
    """The qualities, or why there are none to list.

    "none" next to six sources found reads as a fault.  Most sites simply do
    not label their files; the best one is then chosen without a menu.
    """
    if qualities:
        return ', '.join(qualities)
    sources = int(result.get('count') or 0)
    if sources:
        return f'not labelled by the page ({sources} sources; the best is used)'
    return 'none'


def _yes_no(value, yes='yes', no='no'):
    return yes if value else no


def build(host, result, error=''):
    """(title, body) for a report about one site.

    ``error`` is the message when the check failed outright, in which case
    there is no reading to describe and the message is the whole finding.
    """
    host = re.sub(r'^www\.', '', str(host or '').strip().lower())
    problem = diagnose(result) if result else (error and 'site could not be read')
    title = f'[site] {host} — {problem}' if problem else f'[site] {host}'

    lines = [f'**Site:** `{host}`',
             f'**Siphon:** {metadata.VERSION}', '']

    if not result:
        lines += ['The check did not finish.', '',
                  '```', str(error or 'no reason given'), '```']
        return title, '\n'.join(lines)

    titles = [t for t in (result.get('sample_titles') or []) if t]
    qualities = [q for q in (result.get('qualities') or []) if q]

    lines += [
        '| What | Found |',
        '| --- | --- |',
        f"| Engine | {result.get('engine_label') or result.get('engine') or 'not recognised'} |",
        f"| Video kind | {result.get('kind') or '?'} |",
        f"| Videos on the listing | {int(result.get('listed') or 0)} |",
        *( [f"| Why none were found | {result['listing_why']} |"]
           if result.get('listing_why') else [] ),
        *( [f"| Does not look like a listing | {_doubt(result)} |"]
           if result.get('listing_doubt') else [] ),
        f"| Of those, with a thumbnail | {int(result.get('thumbs') or 0)} |",
        f"| Categories found | {int(result.get('categories') or 0)} |",
        # Whether page links were SEEN, not whether paging works: that is only
        # known once page two has been fetched and shown different videos.
        f"| Page links seen on the listing | {_yes_no(result.get('paging'))} |",
        f"| Search address | {result.get('search') or 'none found'} |",
        f"| Title rule | {result.get('title_rule') or 'none worked'} |",
        f"| Why that rule | {result.get('title_why') or '-'} |",
        f"| Qualities offered | {_qualities_text(qualities, result)} |",
        f"| Sources on the page | {int(result.get('count') or 0)} |",
        '',
        '**Three videos, as Siphon read them:**',
    ]
    if titles:
        lines += [f'{n}. `{name}`' for n, name in enumerate(titles, 1)]
        if len(titles) > 1 and len(set(titles)) == 1:
            lines += ['', 'All three are the same text, so the rule above is '
                          'reading something the site shows on every page.']
    else:
        lines += ['None of them gave a title.']

    page = result.get('via') or ''
    if page:
        lines += ['', f'**Page tried:** {page}']

    # Only when the listing could not be read: how the page is built around
    # its links, which is what it takes to fix such a site.  Shape only —
    # tag and class names — so it says nothing about what anyone watched.
    shape = str(result.get('listing_shape') or '').strip()
    if shape:
        lines += ['', '**How the page is built around its links:**', '',
                  '```', shape, '```']
    return title, '\n'.join(lines)


LOG_LINES = 120


def log_tail(host, lines=LOG_LINES):
    """The log lines about one site, newest last ('' when there are none).

    A report is worth far more with the log beside it: the log is where the
    addresses tried and the reason each was refused are written down.  But
    the whole file names every site the person added and everything they did
    today, and a report may end up on a public page — so only the lines
    naming this one site come out, and the person sees them before sending.

    The file is already written redacted: a video address keeps its site and
    loses its path, and file names are not in it at all.
    """
    host = re.sub(r'^www\.', '', str(host or '').strip().lower())
    if not host:
        return ''
    try:
        from siphon.core import applog
        path = applog.log_path()
        if not path:
            return ''
        # The host has to match as a whole name, not as a piece of one: a
        # plain "in" test would pull "private.test" into a report about
        # "e.test" and hand over a site the person never mentioned.
        whole = re.compile(r'(?<![\w.-])' + re.escape(host) + r'(?![\w-])')
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            everything = [line.rstrip() for line in handle]
    except Exception:
        return ''

    # Only lines about this site count against the budget.  Keeping every
    # "app started" line as well filled a whole report with the dates the
    # app had been opened and left no room for anything about the site.
    about = [line for line in everything if whole.search(line)]
    if not about:
        return ''
    kept = about[-int(lines):]

    # One session line, above the kept lines, so the reader can see which
    # run this was — the newest one at or before where the kept lines start.
    first = everything.index(kept[0])
    started = [line for line in everything[:first + 1] if 'app started' in line]
    return '\n'.join(started[-1:] + kept)


def with_log(body, host, lines=LOG_LINES):
    """``body`` with this site's log lines appended, if there are any."""
    tail = log_tail(host, lines)
    if not tail:
        return body + ('\n\n*(the log holds nothing about this site yet)*')
    return (f'{body}\n\n<details>\n<summary>Log for {host} '
            f'(last {len(tail.splitlines())} lines)</summary>\n\n'
            f'```\n{tail}\n```\n\n</details>')


def log_folder():
    """Where the log file is, for a button that opens it ('' if unknown)."""
    try:
        from siphon.core import applog
        path = applog.log_path()
        return str(path.parent) if path else ''
    except Exception:
        return ''


def contact_email():
    """The address a report can be emailed to ('' when none was set)."""
    return str(getattr(metadata, 'CONTACT_EMAIL', '') or '').strip()


# A browser address is cut short somewhere above this, and the limit is not
# the same everywhere, so the report is trimmed well below any of them.
MAIL_ROOM = 1600


def mail_url(title, body):
    """A page for writing the report as an email, opened in the browser.

    Not a ``mailto:`` address.  That hands the message to whichever program
    the computer has registered for mail, which on a great many computers is
    a web browser that cannot write mail at all: the browser opens, shows an
    empty tab, and the person is left thinking the button is broken.  Most
    people read their mail on a web page anyway, so the message is written
    on that page instead.

    Empty when no contact address was set.  A message written this way can
    carry no attachment, so the log-folder button stands beside this one.
    """
    to = contact_email()
    if not to:
        return ''
    if len(body) > MAIL_ROOM:
        body = body[:MAIL_ROOM] + (
            '\n\n--- cut short to fit. Press Copy in Siphon for the whole '
            'report, and paste it over this. ---')
    return ('https://mail.google.com/mail/?view=cm&fs=1'
            f'&to={quote(to)}&su={quote(title)}&body={quote(body)}')


def mail_is_cut_short(body):
    """Whether this report is too long to fit in the browser address."""
    return len(body) > MAIL_ROOM


def issue_url(title, body):
    """A GitHub "new issue" address with the report already filled in.

    GitHub refuses a very long address, so an over-long body is cut and the
    user is told to paste the rest; that is better than a link that fails.
    """
    base = f'https://github.com/{metadata.GITHUB_REPOSITORY}/issues/new'
    room = 6000 - len(title)
    if len(body) > room:
        body = body[:room] + '\n\n*(cut short — paste the rest from the Copy button)*'
    return f'{base}?title={quote(title)}&body={quote(body)}'


def report_for_profile(host, profile):
    """A report built from what was saved about a site, with no page fetched.

    Used in the site list, where a fresh check is the better report but may
    not be possible: the site may be down, or the user offline.
    """
    host = re.sub(r'^www\.', '', str(host or '').strip().lower())
    rules = (profile or {}).get('rules') or {}
    saved = {
        'engine': (profile or {}).get('engine', ''),
        'engine_label': (profile or {}).get('engine', ''),
        'search': (profile or {}).get('search', ''),
        'title_rule': rules.get('title_rule', ''),
        'title_why': 'from what was saved when the site was added',
        'listed': 0, 'thumbs': 0, 'count': 0, 'categories': 0,
        'paging': False, 'sample_titles': [], 'qualities': [],
        'via': (profile or {}).get('root') or f'https://{host}',
    }
    title, body = build(host, saved)
    body += ('\n\n*Built from what was saved about this site; the live check '
             'could not be run just now.*')
    return title, body


def host_of(url):
    return re.sub(r'^www\.', '', (urlsplit(str(url or '')).hostname or '').lower())
