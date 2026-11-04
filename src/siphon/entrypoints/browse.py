#!/usr/bin/env python
# coding: utf-8

import ctypes
import multiprocessing
import sys

if __name__ == '__main__':
    # PyInstaller replaces this with an early child-process dispatcher.  It
    # must run before SSL, crash logging, Tk, or crawler imports so the local
    # translation worker never starts a second GUI.
    multiprocessing.freeze_support()

from siphon.core.bootstrap import (
    install_runtime_guards,
    run_translation_diagnostic_if_requested,
)

install_runtime_guards()

from siphon.core import applog
applog.install()

if __name__ == '__main__':
    run_translation_diagnostic_if_requested()

# Enable DPI awareness BEFORE any Tk/GUI imports
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # Per-monitor V2
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from siphon.cli.args import av_recommand, get_parser
from siphon import sites as M3U8Sites

from siphon.apps.browse import gui_modern_main as _gui_main

def main():
    url_arg = ""
    parser = get_parser()
    args = parser.parse_args()

    if len(args.url) != 0:
        url_arg = args.url
    elif args.random:
        url_arg = av_recommand() or ""   # None (site changed/blocked) -> empty, not a crash

    if args.nogui:
        result = M3U8Sites.consoles_main(
            url_arg, args.output, args.max_workers_per_video)
        return 0 if result is None else int(result)
    _gui_main(url_arg, args.output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
