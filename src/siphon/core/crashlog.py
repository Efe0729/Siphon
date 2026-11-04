# coding: utf-8
"""Global crash logging for the frozen GUI builds (issues #24).

A GUI app launched via pythonw has no console, so a crash just makes the window
vanish with no information. Two kinds of crash need two mechanisms:

  * Python-level uncaught exceptions  -> sys.excepthook / threading.excepthook
    -> crash_log.txt + a copyable dialog.
  * NATIVE fatal errors (segfault / Windows access-violation / C-level abort in
    Tk, PIL, curl_cffi, a DLL, ...) -> these BYPASS sys.excepthook entirely and
    leave no Python traceback (issue #24: user got a silent crash with an EMPTY
    crash_log). For those we arm faulthandler, which installs C-level fault
    handlers and dumps every thread's Python stack to crash_native.log.

We also drop breadcrumbs (breadcrumb()) so even a hard crash tells us how far
startup got (categories loaded? page loaded? thumbnails?).
"""
import atexit
import os
import sys
import threading
import traceback
from datetime import datetime

from siphon.metadata import PRODUCT_NAME, VERSION

_fault_file = None   # kept open for the process lifetime so faulthandler can write on crash


def _disarm_faulthandler():
    """Release the native crash log cleanly during normal interpreter exit."""
    global _fault_file
    try:
        import faulthandler
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass
    handle, _fault_file = _fault_file, None
    if handle is not None:
        try:
            handle.close()
        except Exception:
            pass


atexit.register(_disarm_faulthandler)


def _base_dir():
    # Same folder as the app log ("Open log"): <project>/logs when run from
    # source, the app's data folder (AppData) for a packaged .exe — never
    # next to the .exe, which may sit in Downloads or a read-only Program Files.
    try:
        from siphon.core.applog import _default_log_dir
        base = str(_default_log_dir())
        os.makedirs(base, exist_ok=True)
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    try:
        probe = os.path.join(base, ".w_test_%d" % os.getpid())
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except Exception:
        base = os.path.expanduser("~")
    return base


def _path(name="crash_log.txt"):
    return os.path.join(_base_dir(), name)


def _log_path():
    return _path("crash_log.txt")


def _app_version():
    return VERSION


def _write(kind, exc_type, exc_value, exc_tb):
    try:
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        header = (
            "=" * 70 + "\n"
            + f"{PRODUCT_NAME} crash log\n"
            + "time   : %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            + "version: %s\n" % _app_version()
            + "python : %s\n" % sys.version.split()[0]
            + "platform: %s\n" % sys.platform
            + "source : %s\n" % kind
            + "-" * 70 + "\n"
        )
        with open(_path("crash_log.txt"), "a", encoding="utf-8") as f:
            f.write(header + tb + "\n")
        return tb
    except Exception:
        return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))


def breadcrumb(msg):
    """Append a startup/progress marker. Cheap, flushed — so even a hard native
    crash tells us how far the app got (issue #24: 'before or after thumbnails')."""
    try:
        with open(_path("startup.log"), "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.now().strftime("%H:%M:%S.%f")[:-3], msg))
    except Exception:
        pass


def _arm_faulthandler():
    """Catch NATIVE fatal errors (segfault / access-violation / C-abort) that
    bypass sys.excepthook and leave crash_log.txt empty. faulthandler dumps all
    threads' Python stacks to crash_native.log at the moment of the fault."""
    global _fault_file
    try:
        import faulthandler
        if _fault_file is not None:
            _disarm_faulthandler()
        # start a fresh native log each run so the user pastes only the last crash
        _fault_file = open(_path("crash_native.log"), "w", encoding="utf-8")
        _fault_file.write(
            f"{PRODUCT_NAME} native-fault log  ·  version %s  ·  "
            "python %s  ·  %s\n"
            "(if this file has a traceback below, the app hit a NATIVE crash — "
            "please paste it to the GitHub issue)\n%s\n"
            % (_app_version(), sys.version.split()[0],
               datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "-" * 60))
        _fault_file.flush()
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception:
        pass


def _missing_module(tb):
    """The package name from a 'No module named ...' crash ('' otherwise).

    Starting without the required packages is the one crash a user can fix
    themselves, so it gets a plain answer instead of a traceback.
    """
    import re
    found = re.search(r"No module named '([^']+)'", tb or '')
    return found.group(1).split('.')[0] if found else ''


def _show_dialog(tb):
    path = _log_path()
    missing = _missing_module(tb)
    if missing:
        msg = (
            f"{PRODUCT_NAME} başlayamadı: '{missing}' eklentisi kurulu değil.\n\n"
            "Çözümü: uygulamanın klasöründeki '.build' klasörünü silin, sonra "
            "'Siphon.bat' dosyasına çift tıklayın; eksik paketleri kendisi kurar.\n\n"
            f"{PRODUCT_NAME} could not start: the '{missing}' package is missing.\n"
            "Delete the '.build' folder next to the app, then run 'Siphon.bat': "
            "it installs what is missing.\n\n"
            f"{tb[-800:]}"
        )
    else:
        msg = (
            f"{PRODUCT_NAME} beklenmedik bir hatayla karşılaştı. "
            f"Kayıt dosyası:\n{path}\n\n"
            "Bu dosyayı (ya da aşağıdaki yazıyı) paylaşırsanız sorun giderilebilir.\n\n"
            f"An unexpected error occurred. A log was saved to:\n{path}\n\n"
            f"{tb[-1500:]}"
        )
    # Prefer a native Win32 MessageBox: it's process-global and safe even when a
    # Tk root already exists / its mainloop has died (building a 2nd tk.Tk() in a
    # crashing GUI app often double-faults). Fall back to a fresh Tk dialog only
    # if MessageBox is unavailable (non-Windows).
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, msg, f"{PRODUCT_NAME} — Hata / Error", 0x10)
        return
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import scrolledtext
        win = tk.Tk()
        win.title(f"{PRODUCT_NAME} — Hata / Error")
        win.geometry("760x520")
        box = scrolledtext.ScrolledText(win, wrap="word")
        box.insert("1.0", msg)
        box.pack(fill="both", expand=True, padx=12, pady=8)
        tk.Button(win, text="Kapat / Close", command=win.destroy).pack(pady=(0, 12))
        win.mainloop()
    except Exception:
        pass


def install(show_dialog=True):
    # native fatal errors (the #24 case: empty crash_log = not a Python exception)
    _arm_faulthandler()
    breadcrumb("crashlog installed (v%s, python %s)" % (_app_version(), sys.version.split()[0]))

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb = _write("sys.excepthook", exc_type, exc_value, exc_tb)
        if show_dialog:
            _show_dialog(tb)

    sys.excepthook = hook

    # background threads (downloads/scrapers run on threads) — Python 3.8+
    try:
        def thook(args):
            if issubclass(args.exc_type, KeyboardInterrupt):
                return
            _write("threading[%s]" % getattr(args.thread, "name", "?"),
                   args.exc_type, args.exc_value, args.exc_traceback)
        threading.excepthook = thook
    except Exception:
        pass


def start_freeze_watchdog(app, limit=15.0, clock=None, report=None, every=2.0):
    """Write down what every thread is doing if the window stops responding.

    A window that hangs leaves nothing behind: no error, no crash file, only a
    person who closes it by force.  This asks the window to answer once a
    second; when no answer comes for ``limit`` seconds the stack of every
    thread goes into the log, which names the line that is stuck.

    ``clock`` and ``report`` are for tests.
    """
    import time as _time
    clock = clock or _time.monotonic
    report = report or (lambda text: print(text, flush=True))
    beat = [clock()]

    def _ping():
        beat[0] = clock()
        try:
            if not getattr(app, '_is_closing', False):
                app.after(1000, _ping)
        except Exception:
            pass

    def _stacks():
        names = {t.ident: t.name for t in threading.enumerate()}
        parts = []
        for ident, frame in sys._current_frames().items():
            parts.append(f'--- thread {names.get(ident, ident)} ---\n'
                         + ''.join(traceback.format_stack(frame)))
        return '\n'.join(parts)

    def _watch():
        told = False
        while not getattr(app, '_is_closing', False):
            _time.sleep(every)
            quiet = clock() - beat[0]
            if quiet > limit and not told:
                told = True
                report(f'[freeze] the window has not answered for {int(quiet)}s; '
                       'what every thread is doing:\n' + _stacks())
            elif quiet <= limit and told:
                told = False
                report('[freeze] the window answers again')

    try:
        app.after(1000, _ping)
    except Exception:
        return None
    thread = threading.Thread(target=_watch, name='freeze-watchdog', daemon=True)
    thread.start()
    return thread
