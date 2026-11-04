# Architecture and source layout

Siphon uses a `src` layout so runtime packages, build files, documentation,
and tests have explicit boundaries.

```text
src/siphon/
  apps/          the desktop app (see below) and Tk-independent helpers
  cli/           Siphon CLI and command-line argument handling
  core/          configuration, paths, SSL, updater, browser fallback, logging
  entrypoints/   Windows and installed application entrypoints
  i18n/          application strings (English, Turkish)
  sites/         the generic site reader, downloader and site learning
  ui/            shared theme and widgets
  upload/        the rclone-driven upload queue
  web/           the opt-in NAS web queue
packaging/windows/
  PyInstaller specification and Windows version resources
scripts/
  build and repository-maintenance automation
tests/
  unit, integration, regression and packaging contracts
docs/
  user and contributor documentation plus visual assets
```

## The desktop app

`apps/browse.py` holds the window itself (`ModernApp`: start-up, language,
tabs, closing). The rest of the window is split by what it shows, each part a
mixin that `ModernApp` inherits:

- `app_settings.py` — the Settings tab
- `app_sites.py` — adding, ordering, reporting and teaching sites
- `app_browse.py` — the Browse tab
- `app_downloads.py` — the Downloads tab

Alongside them: `download_manager.py` (the queue), `thumbnails.py`,
`file_actions.py`, `app_basics.py` (shared small helpers), `downloads.py`
(Tk-independent queue helpers) and `upload_tab.py`.

## Public entrypoints

- `siphon-app` → `siphon.entrypoints.browse:main`
- `siphon-cli` → `siphon.cli.headless:main`

Both entrypoints install shared runtime guards before importing GUI
dependencies, which keeps SSL certificate setup and crash reporting
consistent.

## Site boundary

Siphon ships with no sites. `siphon.sites` holds one generic reader
(`generic.py`, `genericbrowse.py`) that learns a site the user adds: where its
videos are, how its listings page and how its search works. What it learned is
stored per site. `downloader.py` does the downloading, `kvs.py` knows the
Kernel Video Sharing engine, and `core/browser.py` opens a hidden Edge or
Chrome for sites that need a real browser.

## Persistence boundary

User data lives under `%APPDATA%\Siphon`, stored through `core/secretstore.py`
(tied to the Windows account with DPAPI). The download queue, history and
upload queue survive a restart. `apps/downloads.py` owns the Tk-independent
import/export, filtering, storage preflight, error taxonomy and schedule
calculation; the GUI is only presentation and confirmation. Duplicate URLs are
merged intentionally and reported to the user instead of silently disappearing.

## Release boundary

Windows release bytes are produced by the pinned GitHub Actions workflow and
published as `Siphon.exe` with checksums. The in-app updater installs only an
asset with that name from this project's own Releases page.
