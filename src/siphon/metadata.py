"""Single source of truth for public product and release identity."""

from __future__ import annotations


PRODUCT_NAME = "Siphon"
VERSION = "1.1.0"
COMPANY_NAME = "Efe0729"
# ─────────────────────────────────────────────────────────────────────────
# Your own repository, as "owner/name" (for example "efe/Siphon").  While
# this is empty, "check for updates" stays switched off.
#
# It must never name a repository you do not control: the updater downloads
# and runs what it finds there, so pointing it elsewhere would install
# somebody else's build on your users' computers.
# ─────────────────────────────────────────────────────────────────────────
GITHUB_REPOSITORY = "Efe0729/Siphon"
LEGACY_GITHUB_REPOSITORIES = ()

# ─────────────────────────────────────────────────────────────────────────
# Where a site report can be emailed, for someone who would rather not open
# a public issue.  While this is empty, the report window offers only the
# GitHub issue, the clipboard and the log folder — and no email button.
#
# Whatever is written here ships inside the program and can be read by
# anyone who has a copy, so put an address you are willing to publish.  It
# opens in the person's own mail program: Siphon sends nothing itself and
# holds no mail account of its own.
# ─────────────────────────────────────────────────────────────────────────
CONTACT_EMAIL = "contact.efe0729@gmail.com"

APP_DISPLAY_NAMES = {
    "browse": "Siphon",
    "headless": "Siphon CLI",
}

APP_DESCRIPTIONS = {
    "browse": "Download from any site, upload to the cloud",
    "headless": "Docker and command-line downloader",
}

_RELEASE_ASSETS = {
    "browse": (
        "Siphon.exe",
    ),
}



def release_asset_candidates(channel: str) -> tuple[str, ...]:
    """Return canonical-first asset names for a logical release channel."""
    try:
        return _RELEASE_ASSETS[str(channel)]
    except KeyError as exc:
        raise ValueError(f"unknown release channel: {channel!r}") from exc


def github_api_latest_url() -> str:
    return (
        "https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}/releases/latest"
    )
