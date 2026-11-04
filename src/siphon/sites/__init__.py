"""Site registry.

Siphon ships with no sites of its own: every address it can download from
is one the user added, handled by the generic adapter.
"""

from __future__ import annotations

from . import generic


USER_SITE_CLASSES = (generic.SiteGeneric,)

siteList = USER_SITE_CLASSES
siteUrlList = ()


def validate_url(url):
    for site in siteList:
        if site.validate_url(url):
            return site
    return None


def VaildateUrl(url):  # noqa: N802 - legacy API typo retained for v2 callers
    return validate_url(url)


def describe(url):
    """(name, picture) for a video, or ('', '') if its page cannot be read.

    This asks the site's own adapter — the very code that will name the file
    when the download runs — so a queued row never says one thing and the
    saved file another.  The adapter knows where its site keeps the heading
    and loads the page in the off-screen browser when the site demands one,
    which plain guessing from the first kilobytes of HTML cannot do.

    The picture comes back from the same page read, so a link pasted into the
    queue costs no more than it did when only the name was wanted.
    """
    site = validate_url(url)
    if site is None:
        return '', ''
    try:
        adapter = site(url, silence=True)
        adapter.get_url_infos()
        return (str(getattr(adapter, '_targetName', '') or '').strip(),
                str(getattr(adapter, '_imageUrl', '') or '').strip())
    except Exception as exc:
        print(f'[title] {url}: {exc}', flush=True)
        return '', ''


def title_for(url):
    """Just the name; see describe()."""
    return describe(url)[0]


def create_site(
        url, savepath="", silence=False, max_workers=None,
        resolution=None, filename_template=None):
    site = validate_url(url)
    if site is None:
        return None
    kwargs = {
        'savepath': savepath,
        'silence': silence,
        'max_workers': max_workers,
    }
    if resolution is not None:
        kwargs['resolution'] = resolution
    if filename_template is not None:
        kwargs['filename_template'] = filename_template
    return site(url, **kwargs)


def CreateSite(  # noqa: N802
        url, savepath="", silence=False, max_workers=None,
        resolution=None, filename_template=None):
    return create_site(
        url, savepath, silence, max_workers,
        resolution, filename_template)


def create_site_url_list(url, silence=False):
    for url_list in siteUrlList:
        candidate = url_list(url, silence=silence)
        if candidate.isVaildLinks():
            return candidate
    return None


def CreateSiteUrlList(url, silence=False):  # noqa: N802
    return create_site_url_list(url, silence)


def consoles_main(url, dest=None, max_workers=None):
    if not url:
        url = input("Enter a supported URL: ")
    job = create_site(url, dest, max_workers=max_workers)
    if job is None:
        print(f"Unsupported URL: {url}")
        return 2
    if not job.is_url_vaildate():
        print(f"Could not parse video: {url}")
        return 1
    try:
        completed = job.start_download()
    except Exception as exc:
        print(f"Download error: {exc}")
        return 1
    if completed is False:
        print("Download incomplete")
        return 1
    print("Download complete!")
    return 0


if __name__ == "__main__":
    consoles_main("")
