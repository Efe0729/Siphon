#!/usr/bin/env python
# coding: utf-8
"""Siphon CLI for Docker, NAS, and local terminal use — no GUI.

Downloads one or more supported URLs to ``--output`` or ``$DOWNLOAD_DIR``.
Docker sets ``DOWNLOAD_DIR=/downloads``; a normal local installation defaults
to ``./download`` instead of trying to create a directory at the drive root.
URLs are taken from, in order: command-line args, the $URLS / $URL env var
(space/comma separated), and a text file ($URLS_FILE, default
``<output>/urls.txt`` — one URL per line, '#' comments allowed).

Examples:
  docker run --rm -v /nas/videos:/downloads siphon:local https://example.com/videos/abc-123/
  docker run --rm -v /nas/videos:/downloads -e URLS_FILE=/downloads/urls.txt siphon:local
"""
import argparse
import os
import sys

# --- issue #23: point SSL/curl_cffi at certifi's ASCII-safe CA bundle BEFORE any
# curl_cffi import, so a non-UTF-8 default cert path can't crash the resolver. ---
try:
    import certifi as _certifi
    _ca = _certifi.where()
    if _ca and os.path.exists(_ca):
        os.environ.setdefault('SSL_CERT_FILE', _ca)
        os.environ.setdefault('SSL_CERT_DIR', os.path.dirname(_ca))
except Exception:
    pass

from siphon import sites as M3U8Sites
from siphon.core import config
from siphon.core.storage import StorageWriteError
from siphon.sites import base as M3U8Crawler


_RESOLUTIONS = ('highest', '1080', '720', '480', '360', 'lowest')


def _configure_console_encoding():
    """Keep redirected Windows output from crashing on localized messages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            try:
                reconfigure(encoding='utf-8', errors='replace')
            except (OSError, ValueError):
                pass


def get_parser():
    parser = argparse.ArgumentParser(
        description=(
            'Siphon CLI — download supported video URLs without a GUI'
        )
    )
    parser.add_argument('urls', nargs='*', metavar='URL')
    parser.add_argument(
        '-o', '--output', metavar='DIR',
        help='download directory (default: $DOWNLOAD_DIR or ./download)')
    parser.add_argument(
        '--resolution', choices=_RESOLUTIONS,
        help='preferred video resolution (default: $RESOLUTION or highest)')
    parser.add_argument(
        '--max-workers-per-video', type=int,
        choices=range(
            config.MIN_WORKERS_PER_VIDEO,
            config.MAX_WORKERS_PER_VIDEO + 1),
        metavar='N',
        help='maximum segment workers per video, from 1 to 16')
    return parser


def gather_urls(cli_urls=None, download_dir=None):
    urls = [str(u).strip() for u in (cli_urls or ()) if str(u).strip()]
    env = (os.environ.get('URLS') or os.environ.get('URL') or '')
    urls += [u.strip() for u in env.replace(',', ' ').split() if u.strip()]
    destination = download_dir or os.environ.get('DOWNLOAD_DIR') or os.path.abspath('download')
    path = os.environ.get('URLS_FILE', os.path.join(destination, 'urls.txt'))
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as fh:
            urls += [ln.strip() for ln in fh if ln.strip() and not ln.lstrip().startswith('#')]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def main(argv=None):
    _configure_console_encoding()
    args = get_parser().parse_args(argv)

    dest = args.output or os.environ.get('DOWNLOAD_DIR') or os.path.abspath('download')
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError as exc:
        print(f'[Storage error] Cannot create output directory {dest}: {exc}',
              flush=True)
        return 2

    res = args.resolution or os.environ.get('RESOLUTION')
    if res:
        normalized_resolution = str(res).strip().lower()
        if normalized_resolution not in _RESOLUTIONS:
            print(
                f'Invalid resolution {res!r}; choose one of '
                f'{", ".join(_RESOLUTIONS)}.',
                flush=True)
            return 2
        M3U8Crawler.set_resolution_pref(normalized_resolution)

    max_workers = args.max_workers_per_video
    raw_workers = (
        os.environ.get('MAX_WORKERS_PER_VIDEO')
        if max_workers is None else None)
    if raw_workers is not None and raw_workers.strip():
        try:
            parsed_workers = int(raw_workers.strip())
        except ValueError:
            print('MAX_WORKERS_PER_VIDEO must be an integer from 1 to 16.',
                  flush=True)
            return 2
        if not (config.MIN_WORKERS_PER_VIDEO <= parsed_workers <=
                config.MAX_WORKERS_PER_VIDEO):
            print('MAX_WORKERS_PER_VIDEO must be from 1 to 16.', flush=True)
            return 2
        max_workers = parsed_workers

    urls = gather_urls(args.urls, dest)
    if not urls:
        print("no URL provided. Pass URL(s) as arguments, set the URLS env var, or add a"
              " urls.txt to the download dir.\n"
              "  docker run --rm -v /nas/videos:/downloads siphon:local <URL>", flush=True)
        return 2

    worker_label = (
        max_workers if max_workers is not None
        else config.get_max_workers_per_video())
    print(f"Download folder: {dest} | resolution: {M3U8Crawler.get_resolution_pref()} | "
          f"threads per video: {worker_label} | total {len(urls)} URLs", flush=True)
    ok = fail = 0
    for url in urls:
        print(f"\n========== {url} ==========", flush=True)
        try:
            site = M3U8Sites.CreateSite(
                url, dest, max_workers=max_workers)
            if site is None:
                print(f"[Skipped] Unsupported URL: {url}", flush=True); fail += 1; continue
            if not site.is_url_vaildate():
                print(f"[Failed] Could not parse video (site changed / blocked by Cloudflare / video missing): {url}", flush=True); fail += 1; continue
            completed = site.start_download()
            if completed is False:
                print(f"[Failed] Download incomplete: {url}", flush=True)
                fail += 1
                continue
            print(f"[Done] {url}", flush=True); ok += 1
        except StorageWriteError as exc:
            print(f'[Storage error] {url}: {exc}', flush=True)
            fail += 1
            break
        except Exception as exc:
            print(f"[Error] {url}: {exc}", flush=True); fail += 1
    print(f"\n===== Done {ok}, failed {fail} =====", flush=True)
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
