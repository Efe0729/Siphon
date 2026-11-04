"""Open the original site's full player, not a trailer or a download job.

Playback uses the user's system browser/session. This deliberately does not
embed untrusted site JavaScript in Tk or expose any Python bridge to it.
"""
from urllib.parse import urlsplit
import webbrowser

from siphon.sites import siteList


def open_video_preview(url, *, opener=None):
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ValueError('Unsupported preview URL')
    if any(ord(character) < 33 or ord(character) == 127 for character in url):
        raise ValueError('Unsupported preview URL')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443)):
            raise ValueError('Unsupported preview URL')
    except ValueError:
        raise ValueError('Unsupported preview URL') from None
    # A path that climbs out of itself, spelled plainly or percent-encoded.
    path = parsed.path
    if ('%' in path or '\\' in url
            or any(piece in {'.', '..'} for piece in path.split('/'))):
        raise ValueError('Unsupported preview URL')
    # Only a site the user added: this hands the address to their browser.
    if not any(site.validate_url(url) for site in siteList):
        raise ValueError('Unsupported preview URL')
    return bool((opener or webbrowser.open)(url, new=2))
