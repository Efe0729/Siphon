"""Single source of truth for public product and release identity."""

from __future__ import annotations


PRODUCT_NAME = "Siphon"
VERSION = "1.0.0"
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

FEATURED_SITES = ("site", "site", "site", "site")


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
