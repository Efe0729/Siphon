"""Speed-limit choices shared by the download and upload limiters.

Values are bytes per second; 0 means unlimited.  Text input accepts things
like "256", "256k", "256 KB/s", "1.5M" or "1.5 MB/s" (a bare number is KB/s).
"""

from __future__ import annotations

import re

KB = 1024
MB = 1024 * 1024
PRESETS = [256 * KB, 512 * KB, 1 * MB, 2 * MB, 5 * MB, 10 * MB, 15 * MB]
MAX_BPS = 1024 * MB

_PATTERN = re.compile(
    r'^\s*(\d+(?:[.,]\d+)?)\s*([kmg]?)(?:i?b)?\s*(?:/\s*s(?:ec)?|ps)?\s*$', re.I)


def parse_speed(text):
    """Return bytes/s, 0 for unlimited/empty, or None when the text is invalid."""
    text = str(text or '').strip()
    if not text or text.lower() in ('0', 'unlimited', 'none', 'off'):
        return 0
    match = _PATTERN.match(text)
    if not match:
        return None
    number = float(match.group(1).replace(',', '.'))
    unit = match.group(2).lower() or 'k'
    factor = {'k': KB, 'm': MB, 'g': 1024 * MB}[unit]
    value = int(number * factor)
    if value <= 0:
        return 0
    return min(max(value, 16 * KB), MAX_BPS)


def format_speed(bps, unlimited_label='Unlimited'):
    bps = int(bps or 0)
    if bps <= 0:
        return unlimited_label
    if bps >= MB:
        value = bps / MB
        text = f'{value:.0f}' if value == int(value) else f'{value:.2f}'.rstrip('0').rstrip('.')
        return f'{text} MB/s'
    value = bps / KB
    text = f'{value:.0f}' if value == int(value) else f'{value:.1f}'
    return f'{text} KB/s'


def menu_values(unlimited_label, custom_label, current_bps=0):
    """Dropdown entries: Unlimited, presets, the current custom value, Custom…"""
    values = [unlimited_label] + [format_speed(p) for p in PRESETS]
    current = format_speed(current_bps, unlimited_label)
    if current not in values:
        values.append(current)
    values.append(custom_label)
    return values


def ask_custom(title, prompt, current_bps=0, master=None):
    """Themed dialog: a number box and a KB/s | MB/s menu.

    Returns bytes/s, 0 for "no limit" (empty/0), or None if cancelled.
    """
    import tkinter as tk
    import customtkinter as ctk
    from siphon.i18n.locales import T, ui_font
    from siphon.ui.theme import (
        ACCENT, ACCENT_HOVER, BG_CARD, BG_CARD_HOVER, BG_DARK, BG_INPUT, BORDER,
        BORDER_HOVER, CONTROL_RADIUS, ERROR_C, TEXT_DIM, TEXT_PRI, WHITE)

    master = master or tk._default_root
    result = {'value': None}

    win = ctk.CTkToplevel(master)
    win.title(title)
    win.configure(fg_color=BG_DARK)
    win.resizable(False, False)
    try:
        win.transient(master)
    except tk.TclError:
        pass

    body = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=12,
                        border_width=1, border_color=BORDER)
    body.pack(fill='both', expand=True, padx=16, pady=16)
    ctk.CTkLabel(body, text=title, text_color=TEXT_PRI,
                 font=(ui_font(), 15, 'bold')).pack(anchor='w', padx=20, pady=(18, 2))
    ctk.CTkLabel(body, text=T('speed_custom_hint'), text_color=TEXT_DIM,
                 font=(ui_font(), 10), justify='left').pack(anchor='w', padx=20, pady=(0, 14))

    row = ctk.CTkFrame(body, fg_color='transparent')
    row.pack(fill='x', padx=20)
    # Pre-fill with the current limit, in the unit that reads best.
    if current_bps and current_bps >= MB and current_bps % (MB // 10) == 0:
        number, unit = f'{current_bps / MB:g}', 'MB/s'
    elif current_bps:
        number, unit = f'{current_bps / KB:g}', 'KB/s'
    else:
        number, unit = '', 'KB/s'
    number_var = ctk.StringVar(value=number)
    unit_var = ctk.StringVar(value=unit)
    entry = ctk.CTkEntry(row, textvariable=number_var, width=140, height=40,
                         corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
                         border_color=BORDER, border_width=1, text_color=TEXT_PRI,
                         font=(ui_font(), 14), justify='center',
                         placeholder_text='256')
    entry.pack(side='left')
    ctk.CTkOptionMenu(row, values=['KB/s', 'MB/s'], variable=unit_var,
                      width=110, height=40, corner_radius=CONTROL_RADIUS,
                      fg_color=BG_INPUT, button_color=BORDER_HOVER,
                      button_hover_color=ACCENT, text_color=TEXT_PRI,
                      dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                      dropdown_text_color=TEXT_PRI, font=(ui_font(), 13),
                      dropdown_font=(ui_font(), 13)).pack(side='left', padx=(10, 0))

    error_lbl = ctk.CTkLabel(body, text='', text_color=ERROR_C, font=(ui_font(), 10))
    error_lbl.pack(anchor='w', padx=20, pady=(6, 0))

    buttons = ctk.CTkFrame(body, fg_color='transparent')
    buttons.pack(fill='x', padx=20, pady=(8, 18))

    def apply(_event=None):
        raw = number_var.get().strip().replace(',', '.')
        if raw in ('', '0'):
            result['value'] = 0
            win.destroy()
            return
        try:
            number_value = float(raw)
        except ValueError:
            error_lbl.configure(text=T('speed_custom_invalid'))
            return
        if number_value < 0:
            error_lbl.configure(text=T('speed_custom_invalid'))
            return
        factor = MB if unit_var.get() == 'MB/s' else KB
        result['value'] = min(max(int(number_value * factor), 16 * KB), MAX_BPS)
        win.destroy()

    def cancel(_event=None):
        win.destroy()

    ctk.CTkButton(buttons, text=T('speed_custom_apply'), command=apply, width=110,
                  height=36, corner_radius=CONTROL_RADIUS, fg_color=ACCENT,
                  hover_color=ACCENT_HOVER, text_color=WHITE,
                  font=(ui_font(), 12, 'bold')).pack(side='right')
    ctk.CTkButton(buttons, text=T('speed_custom_cancel'), command=cancel, width=90,
                  height=36, corner_radius=CONTROL_RADIUS, fg_color='transparent',
                  border_width=1, border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                  text_color=TEXT_PRI, font=(ui_font(), 12)).pack(side='right', padx=(0, 8))

    win.bind('<Return>', apply)
    win.bind('<Escape>', cancel)
    win.protocol('WM_DELETE_WINDOW', cancel)
    # Centre over the main window.
    try:
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        win.geometry(f'+{max(0, x)}+{max(0, y)}')
    except (tk.TclError, AttributeError):
        pass
    win.after(80, lambda: (entry.focus_set(), entry.select_range(0, 'end')))
    try:
        win.grab_set()
    except tk.TclError:
        win.after(100, lambda: win.winfo_exists() and win.grab_set())
    win.wait_window()
    return result['value']
