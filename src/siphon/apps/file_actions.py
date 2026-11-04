"""Opening a downloaded file or its folder in the system's own programs."""

import os

from siphon.apps.app_basics import (
    _VIDEO_EXTS)

def _find_item_file(item, known_path=None, default_dest='download'):
    """The downloaded file of a row: the remembered path, else <dest>/<name>.mp4,
    else the newest video in <dest> whose name starts with the row's name."""
    if getattr(item, 'local', False) and os.path.isfile(str(item.url)):
        return os.path.abspath(item.url)
    if known_path and os.path.isfile(known_path):
        return os.path.abspath(known_path)
    folder = os.path.abspath(item.dest or default_dest)
    name = str(item.name or '').strip()
    if not name or not os.path.isdir(folder):
        return None
    for ext in _VIDEO_EXTS:
        candidate = os.path.join(folder, name + ext)
        if os.path.isfile(candidate):
            return candidate
    key = name.casefold()
    matches = []
    try:
        for entry in os.scandir(folder):
            stem, ext = os.path.splitext(entry.name)
            if (entry.is_file() and ext.lower() in _VIDEO_EXTS
                    and stem.casefold().startswith(key)):
                matches.append(entry.path)
    except OSError:
        return None
    return max(matches, key=os.path.getmtime) if matches else None


def _hand_to_the_system(target):
    """Open a folder, a file or a mailto: address the way the computer does.

    Not through a web browser: a browser opens web pages, and handing it a
    mailto: address gets a blank tab — which is what happened.  The computer
    knows which program answers for which kind of address; this asks it.

    False when nothing answered, so the caller can offer another way.
    """
    import platform
    import subprocess
    system = platform.system()
    try:
        if system == 'Windows':
            os.startfile(target)
        elif system == 'Darwin':
            subprocess.Popen(['open', target])
        else:
            subprocess.Popen(['xdg-open', target])
        return True
    except Exception as exc:
        print(f'[files] nothing on this computer opened {target}: {exc}',
              flush=True)
        return False


def _open_folder(folder):
    """Show a folder in the computer's own file window."""
    return _hand_to_the_system(folder)


def _reveal_in_explorer(path):
    """Open the file's folder with the file selected.  False if that failed."""
    import platform
    import subprocess
    path = os.path.abspath(path)
    try:
        system = platform.system()
        if system == 'Windows':
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        elif system == 'Darwin':
            subprocess.Popen(['open', '-R', path])
        else:
            return False   # most Linux file managers can't select a file
        return True
    except OSError:
        return False
