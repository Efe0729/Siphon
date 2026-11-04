# Windows and your antivirus

Siphon runs from source: you start it with `Siphon.bat`, which runs the Python
files in `src\siphon`. There is no downloaded executable to trust, and nothing
installs itself into Windows.

Two things are worth knowing.

## Python packages

The first run of `Siphon.bat` builds a private Python environment inside the
app's folder (`.build`) and installs the packages listed in `requirements.txt`
from the official Python package index. Nothing else is downloaded, and nothing is
installed system-wide, so removing the app's folder removes everything it
brought with it.

## The browser Siphon opens

For sites behind a "verify you are human" check, Siphon starts the Edge or
Chrome already installed on the computer, off-screen, with a profile of its
own under `%APPDATA%\Siphon\cf_browser`. That profile is separate from your
normal browsing: it holds no bookmarks, no saved passwords and no history of
yours. The window closes by itself a few minutes after it is last used.

## If an antivirus complains

Scanners sometimes flag any program that drives a browser or downloads video.
Siphon's whole source is in this folder and can be read; if a scanner objects
to `.venv\Scripts\python.exe`, it is objecting to Python itself.

Should you ever build a single `.exe` from this source, note that unsigned
executables built with PyInstaller are frequently flagged; running from source
avoids that entirely.
