#!/usr/bin/env python
# coding: utf-8
"""Shared visual system for the Siphon and Siphon Watcher desktop apps."""


# Deep Ocean / Electric Cyan-Blue visual system for Siphon.
# CustomTkinter resolves every (light, dark) tuple automatically.
ACCENT = ('#0284C7', '#0EA5E9')
ACCENT_HOVER = ('#0369A1', '#0284C7')
ACCENT_DIM = ('#E0F2FE', '#0C243E')

SUCCESS = ('#15803D', '#22C55E')
SUCCESS_DIM = ('#DCFCE7', '#0D2818')
WARNING = ('#B45309', '#F59E0B')
WARNING_DIM = ('#FEF3C7', '#2B1F0E')
ERROR_C = ('#DC2626', '#F87171')
ERROR_DIM = ('#FEE2E2', '#2D1418')

BG_DARK = ('#F1F5F9', '#090D16')
BG_CARD = ('#FFFFFF', '#111827')
BG_CARD_HOVER = ('#E2E8F0', '#1E293B')
BG_INPUT = ('#F8FAFC', '#0D1322')
BG_HEADER = ('#FFFFFF', '#0B111E')
BG_SECTION = ('#E2E8F0', '#0F172A')
BG_SIDEBAR = ('#E2E8F0', '#0B111E')
BG_BADGE = ('#E2E8F0', '#1E293B')

TEXT_PRI = ('#0F172A', '#F1F5F9')
TEXT_SEC = ('#475569', '#94A3B8')
TEXT_DIM = ('#64748B', '#64748B')
TEXT_LINK = ('#0284C7', '#38BDF8')

BORDER = ('#CBD5E1', '#1E293B')
BORDER_HOVER = ('#94A3B8', '#334155')
BORDER_CARD = ('#E2E8F0', '#1E293B')

WHITE = ('#FFFFFF', '#FFFFFF')
CARD_RADIUS = 14
CONTROL_RADIUS = 10


def color_for_mode(token, mode='dark'):
    """Resolve a CustomTkinter color tuple for plain Tk fallback widgets."""
    if not isinstance(token, (tuple, list)):
        return token
    return token[0 if str(mode).lower() == 'light' else 1]


def browse_columns_for_width(width):
    """Readable browse-card density for the root window width."""
    width = max(0, int(width or 0))
    if width >= 1500:
        return 4
    if width >= 1080:
        return 3
    return 2


def category_columns_for_width(width):
    """Siphon Watcher category density without clipping localized labels."""
    return 3 if int(width or 0) >= 1120 else 2
