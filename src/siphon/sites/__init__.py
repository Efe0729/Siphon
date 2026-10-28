"""Site registry for featured and compatibility-only URL adapters."""

from __future__ import annotations

from . import (site, site, site, site, site, site, site,
               site, site, site, site, trannyone, site,
               site, site, generic)
from .legacy import sites_91porn, sites_site


FEATURED_SITE_CLASSES = (
    site.Sitesite,
    site.Sitesite_Backup,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    site.Sitesite,
    trannyone.SiteTrannyone,
    site.Sitesite,
    site.Sitesite,
)

LEGACY_URL_ONLY_SITE_CLASSES = (
    sites_91porn.SitesiteOrg,
    sites_91porn.SiteThisAV,
    sites_91porn.SitePigAV,
    sites_91porn.SitePorn5F,
    sites_91porn.Site85Tube,
    sites_91porn.Site91Porn,
    sites_91porn.SitePornBest,
    sites_site.SitesiteLive,
    sites_site.SitesiteXYZ,
    sites_site.SitePornTW,
    sites_site.SitePornJP,
    sites_site.SitePornHK,
    sites_site.SitePornHoHo,
    sites_site.SitePornNVR,
    sites_site.SiteVideo01,
    sites_site.SitePornLuLu,
    sites_site.Sitesite,
    sites_site.SiteAApp11,
    sites_site.Sitesite,
    sites_site.SiteXJISHI,
)

# Sites the user added themselves are tried after every built-in one, so a
# built-in adapter always wins for its own host.
USER_SITE_CLASSES = (generic.SiteGeneric,)

# Backward-compatible public names used throughout the original application.
siteList = FEATURED_SITE_CLASSES + LEGACY_URL_ONLY_SITE_CLASSES + USER_SITE_CLASSES
siteUrlList = (site.siteList,)


def validate_url(url):
    for site in siteList:
        if site.validate_url(url):
            return site
    return None


def VaildateUrl(url):  # noqa: N802 - legacy API typo retained for v2 callers
    return validate_url(url)


def title_for(url):
    """The name this video will be saved under, or '' if it cannot be read.

    This asks the site's own adapter — the very code that will name the file
    when the download runs — so a queued row never says one thing and the
    saved file another.  The adapter knows where its site keeps the heading
    and loads the page in the off-screen browser when the site demands one,
    which plain guessing from the first kilobytes of HTML cannot do.
    """
    site = validate_url(url)
    if site is None:
        return ''
    try:
        adapter = site(url, silence=True)
        adapter.get_url_infos()
        return str(getattr(adapter, '_targetName', '') or '').strip()
    except Exception as exc:
        print(f'[title] {url}: {exc}', flush=True)
        return ''


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
        url = input("輸入支援的網址: ")
    job = create_site(url, dest, max_workers=max_workers)
    if job is None:
        print(f"不支援的網址: {url}")
        return 2
    if not job.is_url_vaildate():
        print(f"無法解析影片: {url}")
        return 1
    try:
        completed = job.start_download()
    except Exception as exc:
        print(f"下載錯誤: {exc}")
        return 1
    if completed is False:
        print("下載未完成")
        return 1
    print("下載完成!")
    return 0


if __name__ == "__main__":
    consoles_main("")
