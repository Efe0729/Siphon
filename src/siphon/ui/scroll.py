"""Faster, adjustable mouse-wheel scrolling for CustomTkinter scroll areas.

On Windows CustomTkinter moves only ~20 pixels per wheel notch.  install()
multiplies the wheel step by the "Scroll speed" setting (1-10, default 5)
for every scrollable list in the app; changes apply immediately.
"""

from __future__ import annotations

from siphon.core import config

MIN_SPEED, MAX_SPEED, DEFAULT_SPEED = 1, 10, 5


def get_speed():
    try:
        value = int(config._load_prefs().get('scroll_speed', DEFAULT_SPEED))
    except (TypeError, ValueError):
        value = DEFAULT_SPEED
    return max(MIN_SPEED, min(value, MAX_SPEED))


def set_speed(value):
    value = max(MIN_SPEED, min(int(value), MAX_SPEED))
    with config._prefs_lock:
        prefs = config._load_prefs()
        prefs['scroll_speed'] = value
        config._save_prefs(prefs)
    _cache['speed'] = value
    return value


_cache = {}


class _ScaledEvent:
    def __init__(self, event, factor):
        self._event = event
        self.delta = int(getattr(event, 'delta', 0) * factor)

    def __getattr__(self, name):
        return getattr(self._event, name)


def install():
    import customtkinter as ctk
    cls = ctk.CTkScrollableFrame
    if getattr(cls, '_siphon_scroll_patched', False):
        return
    original = cls._mouse_wheel_all
    _cache['speed'] = get_speed()

    def _mouse_wheel_all(self, event):
        speed = _cache.get('speed', DEFAULT_SPEED)
        # speed 1 = CustomTkinter's original step; 5 = 5x faster
        if getattr(event, 'delta', 0):
            event = _ScaledEvent(event, speed)
        return original(self, event)

    cls._mouse_wheel_all = _mouse_wheel_all
    cls._siphon_scroll_patched = True
