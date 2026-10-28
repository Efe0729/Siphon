<h1 align="center">Siphon</h1>

<p align="center">
  <strong>Download from any site you add, upload to the cloud.</strong><br />
  A desktop downloader that learns a site from its own pages, so adding one
  takes an address instead of a code change.
</p>

---

## What it does

Siphon ships with **no sites in it**. You add the sites you use, and it works
out the rest by reading them:

- **Browse** — your sites appear with their own categories, search and pages,
  with thumbnails, titles and running times.
- **Download** — paste a link, import a list, or pick videos while browsing.
  A queue with positions, pause/resume, retries, speed limit, scheduling and
  an estimate of the time left.
- **Upload** — send finished files to Google Drive: per-upload destination,
  parallel transfers, pause/resume, skipping files already there, and a queue
  that survives a restart.

## Adding a site

Settings → **My own sites** → type an address (`example.com` is enough, a
video page works too) → **Test and add**. Several addresses at once are fine.

Siphon then reads the site itself: where its videos are, how its listings page,
how its search box is built, and which engine it was built on (Kernel Video
Sharing and friends are recognised and come with their layout already known).
What it learns is remembered, and a layout learned from one site is reused on
the next site built the same way.

If a site cannot be opened from here at all — members only, region blocked —
save one of its video pages from your browser (Ctrl+S) and use **Teach from a
saved page**: the same information is read out of the file.

### Sites that fight back

A site behind a "verify you are human" check, or one that builds its player or
its listings with JavaScript, is opened in the browser already installed on the
computer (Edge or Chrome), off-screen and in Siphon's own profile. The page is
taken from there, the pass is kept, and ordinary requests work again
afterwards. Nothing to configure.

## Installing (Windows, from source)

1. Install [Python](https://www.python.org/downloads/) — tick **Add python.exe
   to PATH** while installing.
2. Put this folder wherever you like, for example `%USERPROFILE%\Siphon`.
3. Double-click **Siphon.bat**. The first run builds Siphon its own Python
   environment and installs what it needs, which takes a few minutes; after
   that it starts straight away.

**Derle.bat** turns the same folder into a single `dist\Siphon.exe` that needs
no Python. It is only worth running once you are done changing things.

## Where your things are kept

Settings, the download queue, the history and the upload queue live in
`%APPDATA%\Siphon`. They are stored scrambled: on Windows they are tied to
your Windows account through DPAPI, so another account on the same computer
cannot read which sites you added or what you downloaded.

A log is kept in the app's own folder, under `logs\`, to make problems
easier to report. Video names, file names and the addresses of individual
videos are left out of it — it records that a download failed and which site
answered, not what you were downloading.


## Known limitations

- **Screen readers and keyboard navigation.** The interface draws its own
  controls, so a screen reader sees very little of it and not everything can
  be reached from the keyboard. This is a real gap, not an oversight; it would
  take a different toolkit to fix properly.
- **Update checking** is off until this app has a release page of its own
  (see `GITHUB_REPOSITORY` in `src/siphon/metadata.py`).

## Your responsibility

Siphon ships with no sites in it and takes no view on what you add. What you
download, and whether it is yours to download, is between you and the site you
take it from: respect their terms and the law where you live.

## Credit

Siphon is a personal fork of
[UAV-Downloader](https://github.com/Alos21750/UAV-Downloader) by ALOS
(Apache-2.0). The download core comes from there; site discovery, the browser
fallback, the upload tab and the current interface were built on top of it.
Licensed under Apache-2.0 — see [LICENSE](./LICENSE) and
[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).
