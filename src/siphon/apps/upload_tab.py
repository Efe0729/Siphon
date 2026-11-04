"""Upload tab for Siphon: send local folders/files to a cloud account via rclone."""

from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from siphon.i18n.locales import STRINGS, T, ui_font
from siphon.ui.theme import (
    ACCENT, ACCENT_HOVER, BG_BADGE, BG_CARD, BG_CARD_HOVER, BG_DARK, BG_INPUT,
    BG_SECTION, BORDER, BORDER_HOVER, CONTROL_RADIUS, ERROR_C, SUCCESS,
    TEXT_DIM, TEXT_PRI, TEXT_SEC, WARNING, color_for_mode,
)
from siphon.core import config
from siphon.upload import manager as um
from siphon.upload import rclone
from siphon.ui import speed_limit

_UPLOAD_STRINGS = {
    'tab_upload': 'Upload',
    'up_account': 'Cloud account',
    'up_folder': 'Auto-upload folder',
    'up_refresh': 'Refresh',
    'up_connect_drive': 'Connect Google Drive',
    'up_connecting': 'A browser window opened — sign in to Google and click "Allow". Waiting…',
    'up_connected': 'Connected: {name}',
    'up_connect_failed': 'Could not connect: {error}',
    'up_no_account': '(no account)',
    'up_choose': 'Choose…',
    'up_auto': 'Upload automatically when a download finishes',
    'up_delete_after': 'Delete the local copy after a successful upload',
    'up_delete_confirm': 'Local files will be deleted after each successful upload. Continue?',
    'up_add_folder': '+ Add folder contents',
    'up_add_files': '+ Add files',
    'up_cancel_all': 'Cancel all',
    'up_clear_done': 'Clear uploaded',
    'up_empty': 'No uploads yet. Add a folder or files, or turn on automatic upload.',
    'up_need_account': 'Choose or connect a cloud account first.',
    'up_rclone_missing': (
        'rclone is not installed. Open PowerShell, run:  winget install Rclone.Rclone  '
        '— then close and reopen this app.'),
    'up_state_waiting': 'Waiting',
    'up_state_uploading': 'Uploading',
    'up_state_done': 'Uploaded',
    'up_state_failed': 'Failed',
    'up_state_cancelled': 'Cancelled',
    'up_retry': 'Retry',
    'up_cancel': 'Cancel',
    'up_auto_tag': 'auto',
    'up_move_tag': 'move',
    'up_picker_title': 'Choose cloud folder',
    'up_picker_up': '↑ Up',
    'up_picker_new': 'New folder',
    'up_picker_new_prompt': 'Folder name:',
    'up_picker_use': 'Use this folder',
    'up_picker_loading': 'Loading…',
    'up_picker_for': 'Upload to which folder?  ·  {what}',
    'up_picker_files': '{n} file(s)',
    'up_folder_empty': 'That folder has no files to upload.',
    'up_added_n': '{n} upload(s) added → {dest}',
    'up_dest': 'Destination',
    'up_sign_in_expired': 'Google sign-in expired — click "Google key…", then "Save and sign in", allow access in the browser, and press "Retry all".',
    'up_key_btn': 'Google key…',
    'up_key_own': '✓ Using your own Google key',
    'up_key_shared': '⚠ Using rclone\'s shared Google key — it often hits Google\'s request quota (uploads restart). Add your own key with "Google key…".',
    'up_key_title': 'Your own Google key',
    'up_key_help': 'Paste the Client ID and Client secret you created in Google Cloud Console (APIs & Services → Credentials → OAuth client, type "Desktop app"). After saving, a browser window opens: sign in with the same Google account and allow access.',
    'up_key_open_console': 'Open Google Cloud Console',
    'up_key_id': 'Client ID',
    'up_key_secret': 'Client secret',
    'up_key_save': 'Save and sign in',
    'up_key_missing': 'Fill in both fields.',
    'up_key_bad_id': 'The Client ID should end with .apps.googleusercontent.com',
    'up_key_waiting': 'A browser window opened — sign in with your Google account and click "Allow" (on the "Google hasn\'t verified this app" page: Advanced → Go to …). Waiting…',
    'up_key_done': 'Your own Google key is now used for {name}.',
    'up_key_failed': 'Could not save the key: {error}',
    'up_resent': 'connection dropped — {size} had to be sent again',
    'eta_left': '{size} left · about {time} at {speed} {how}',
    'eta_left_no_speed': '{size} left',
    'eta_size_unknown': '{n} video(s) left (size known once they start)',
    'eta_at_limit': '(your limit)',
    'eta_at_current': '(current speed)',
    'up_starts_in': 'starts in about {time}',
    'up_eta_paused_note': 'paused uploads not counted',
    'eta_plus_unknown': '+ {n} video(s) of unknown size',
    'up_retry_all': 'Retry all',
    'up_clear_cancelled': 'Clear cancelled',
    'up_cancel_all_confirm': 'Cancel {n} upload(s) that are uploading, waiting or paused?\n\nThey stay in the list as "Cancelled" — "Retry all" puts them back in the queue.',
    'up_nothing_to_cancel': 'Nothing to cancel.',
    'up_retried_n': '{n} upload(s) put back in the queue',
    'up_nothing_to_retry': 'No failed or cancelled uploads.',
    'up_cleared_n': '{n} row(s) removed from the list',
    'up_more_hidden': '+ {n} more upload(s) in the list (shown as the ones above finish or are cleared)',
    'download_anyway': 'Download anyway',
    'already_downloaded_title': 'Already downloaded',
    'already_downloaded_msg': '{n} video(s) were downloaded before, so they were not downloaded again. Use "Download anyway" on a row if you still want it:',
    'already_downloaded_status': '{n} video(s) already downloaded before — skipped',
    'already_downloaded_detail': 'Already downloaded on {info} — skipped',
    'up_skipped_title': 'Already on the cloud',
    'up_skipped_msg': '{n} file(s) are already in the cloud folder, so they were not uploaded:',
    'up_state_skipped': 'Already there',
    'up_skipped_detail': 'A file with this name is already in the cloud folder, so it was not uploaded',
    'up_skipped_kept': ' (local copy kept)',
    'up_existing': 'If it exists',
    'up_existing_skip': 'Skip (same name)',
    'up_existing_replace': 'Replace if different',
    'up_existing_note': 'when the cloud folder already has a file with that name',
    'up_restart_note': 'restarted after the app was closed at {p}% (cloud uploads cannot continue inside a file)',
    'up_parallel': 'At the same time',
    'up_parallel_note': 'files · the speed limit is shared between them',
    'up_pause': 'Pause',
    'up_resume': 'Resume',
    'up_state_paused': 'Paused',
    'up_from': 'From',
    'up_files_n': '{n} files',
    'up_queue_pos': 'Queue position #{n}',
    'up_waiting_size': '{size} to upload',
    'up_elapsed': 'elapsed {t}',
    'up_paused_at': 'Paused at {p}%',
    'up_paused_note': 'progress kept · the next upload in the queue can start',
    'up_done_detail': 'Uploaded {size} in {t} · avg {speed}/s · finished {clock}',
    'up_cancelled_at': 'Cancelled at {p}%',
    'up_started': 'started {clock}',
    'up_picker_missing': '“{path}” was not found — showing the top level.',
    'open_log': 'Open log',
    'browse_loading_page': 'Loading {site} · page {n}…',
    'browse_loading_site': 'Loading {site}…',
    'browse_last_page': 'That was the last page.',
    'site_unreachable': '{site} can\'t be reached from this connection — it looks blocked by your internet provider. Turn on Cloudflare WARP (or a VPN) and choose the site again.',
    'resume_restored': 'Continued {n} download(s) from the last session',
    'cfpass_button': 'Get Cloudflare pass for {host}',
    'cfpass_hint': 'A browser window opens. Pass the "verify you are human" check there; the app saves the pass and closes the window by itself.',
    'cfpass_auto': 'Get automatically (opens browser)',
    'cfpass_waiting': 'Pass the Cloudflare check in the browser window for {host}…',
    'cfpass_done': 'Cloudflare pass saved for {host}',
    'cfpass_failed': 'Could not get the Cloudflare pass: {error}',
    'scroll_speed_setting': 'Scroll speed',
    'scroll_speed_desc': 'How far the lists move per mouse-wheel notch. 1x is the original (slow) speed. Applies immediately.',
    'speed_custom': 'Custom…',
    'speed_custom_hint': 'Type a number and pick the unit. Leave it empty or 0 for no limit.',
    'speed_custom_invalid': 'Please type a number, e.g. 256 or 1.5',
    'speed_custom_apply': 'Apply',
    'speed_custom_cancel': 'Cancel',
    'speed_custom_prompt': 'Enter a limit, e.g. 256 KB/s or 1.5 MB/s (a plain number means KB/s):',
    'up_speed_limit': 'Upload speed',
    'up_speed_limit_note': 'separate from the download limit · applies immediately',
    'workers_all_sites': 'All sites (default)',
    'workers_range': '1–{n}',
    'workers_inherits': 'using default',
    'workers_use_default': 'Use default',
    'up_retrying': '· retry {n}/{m} (previous attempt failed: {reason})',
}
# English text for every UI language (other languages fall back to it).
for _lang_strings in STRINGS.values():
    for _key, _text in _UPLOAD_STRINGS.items():
        _lang_strings.setdefault(_key, _text)

_STATE_COLORS = {
    um.WAITING: TEXT_SEC, um.UPLOADING: ACCENT, um.DONE: SUCCESS,
    um.FAILED: ERROR_C, um.CANCELLED: TEXT_DIM, um.PAUSED: WARNING, um.SKIPPED: SUCCESS,
}


def _fmt_bytes(value):
    value = float(value or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return f'{value:.0f} {unit}' if unit in ('B', 'KB') else f'{value:.1f} {unit}'
        value /= 1024
    return ''


def _fmt_duration(seconds):
    """'3h 25m', '12m', '45s'."""
    seconds = max(0, int((seconds or 0) + 0.5))
    if seconds < 60:
        return f'{seconds}s'
    minutes = -(-seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f'{days}d {hours}h'
    return f'{hours}h {minutes:02d}m' if hours else f'{minutes}m'


def _fmt_eta(seconds):
    if seconds in (None, '') or seconds < 0:
        return ''
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def _btn(parent, text, command, primary=False, width=0):
    kwargs = dict(text=text, command=command, height=34, corner_radius=CONTROL_RADIUS,
                  font=(ui_font(), 11, 'bold' if primary else 'normal'))
    if width:
        kwargs['width'] = width
    if primary:
        kwargs.update(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color='#ffffff')
    else:
        kwargs.update(fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI)
    return ctk.CTkButton(parent, **kwargs)


class UploadTab:
    def __init__(self, app, frame, manager: um.UploadManager):
        self.app = app
        self.frame = frame
        self.mgr = manager
        self._gen = getattr(app, '_build_gen', 0)
        self._rows = {}
        self._rendered_ids = None
        self._seen_version = -1
        self._remotes = []
        self._build()
        self.refresh_remotes()
        self._poll()

    # ── layout ─────────────────────────────────────────────────────────
    def _build(self):
        top = ctk.CTkFrame(self.frame, fg_color=BG_SECTION, corner_radius=0)
        top.pack(fill='x')

        row = ctk.CTkFrame(top, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=(14, 6))
        ctk.CTkLabel(row, text=T('up_account'), text_color=TEXT_SEC, width=110,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        self._remote_var = ctk.StringVar(value=um.get_remote() or T('up_no_account'))
        self._remote_menu = ctk.CTkOptionMenu(
            row, values=[T('up_no_account')], variable=self._remote_var,
            command=self._on_remote, width=220, height=34, corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT, button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER, dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 11))
        self._remote_menu.pack(side='left', padx=10)
        _btn(row, T('up_refresh'), self.refresh_remotes).pack(side='left')
        self._connect_btn = _btn(row, T('up_connect_drive'), self._connect_drive, primary=True)
        self._connect_btn.pack(side='left', padx=(8, 0))
        self._key_btn = _btn(row, T('up_key_btn'), self._open_key_dialog)
        self._key_btn.pack(side='left', padx=(8, 0))
        self._key_lbl = ctk.CTkLabel(top, text='', text_color=TEXT_DIM, anchor='w',
                                     justify='left', wraplength=900, font=(ui_font(), 10))
        self._key_lbl.pack(fill='x', padx=(150, 20), pady=(0, 2))

        row = ctk.CTkFrame(top, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=6)
        ctk.CTkLabel(row, text=T('up_folder'), text_color=TEXT_SEC, width=110,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        self._folder_var = ctk.StringVar(value=um.get_folder())
        entry = ctk.CTkEntry(row, textvariable=self._folder_var, height=34,
                             corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
                             border_color=BORDER, border_width=1, text_color=TEXT_PRI,
                             font=(ui_font(), 11))
        entry.pack(side='left', fill='x', expand=True, padx=10)
        entry.bind('<FocusOut>', lambda _e: um.set_folder(self._folder_var.get()))
        entry.bind('<Return>', lambda _e: um.set_folder(self._folder_var.get()))
        _btn(row, T('up_choose'), self._choose_folder, width=90).pack(side='left')

        row = ctk.CTkFrame(top, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=6)
        ctk.CTkLabel(row, text=T('up_speed_limit'), text_color=TEXT_SEC, width=110,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        self._speed_var = ctk.StringVar(
            value=speed_limit.format_speed(um.get_bwlimit_bps(), T('unlimited')))
        self._speed_menu = ctk.CTkOptionMenu(
            row, values=self._speed_values(), variable=self._speed_var,
            command=self._on_speed, width=140, height=34,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER, dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 11), dropdown_font=(ui_font(), 11))
        self._speed_menu.pack(side='left', padx=10)
        ctk.CTkLabel(row, text=T('up_speed_limit_note'), text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(side='left')

        row = ctk.CTkFrame(top, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=6)
        ctk.CTkLabel(row, text=T('up_parallel'), text_color=TEXT_SEC, width=110,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        self._parallel_var = ctk.StringVar(value=str(um.get_parallel()))
        ctk.CTkOptionMenu(
            row, values=[str(n) for n in range(1, um.MAX_PARALLEL + 1)],
            variable=self._parallel_var, command=lambda v: self.mgr.set_parallel(int(v)),
            width=80, height=34, corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI, font=(ui_font(), 11),
            dropdown_font=(ui_font(), 11)).pack(side='left', padx=10)
        ctk.CTkLabel(row, text=T('up_parallel_note'), text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(side='left')

        row = ctk.CTkFrame(top, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=6)
        ctk.CTkLabel(row, text=T('up_existing'), text_color=TEXT_SEC, width=110,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        existing_labels = {'skip': T('up_existing_skip'), 'replace': T('up_existing_replace')}
        self._existing_var = ctk.StringVar(value=existing_labels[um.get_existing_mode()])
        ctk.CTkOptionMenu(
            row, values=list(existing_labels.values()), variable=self._existing_var,
            command=lambda v: um.set_existing_mode(
                next(k for k, label in existing_labels.items() if label == v)),
            width=200, height=34, corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI, font=(ui_font(), 11),
            dropdown_font=(ui_font(), 11)).pack(side='left', padx=10)
        ctk.CTkLabel(row, text=T('up_existing_note'), text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(side='left')

        row = ctk.CTkFrame(top, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=(6, 4))
        self._auto_var = ctk.BooleanVar(value=um.get_auto_upload())
        ctk.CTkSwitch(row, text=T('up_auto'), variable=self._auto_var,
                      command=lambda: um.set_auto_upload(self._auto_var.get()),
                      progress_color=ACCENT, text_color=TEXT_PRI,
                      font=(ui_font(), 11)).pack(side='left', padx=(110, 0))
        row = ctk.CTkFrame(top, fg_color='transparent')
        row.pack(fill='x', padx=20, pady=(4, 6))
        self._delete_var = ctk.BooleanVar(value=um.get_delete_after())
        ctk.CTkCheckBox(row, text=T('up_delete_after'), variable=self._delete_var,
                        command=self._on_delete_toggle, fg_color=ACCENT,
                        hover_color=ACCENT_HOVER, text_color=TEXT_PRI,
                        font=(ui_font(), 11)).pack(side='left', padx=(110, 0))

        self._info_lbl = ctk.CTkLabel(top, text='', text_color=WARNING, anchor='w',
                                      justify='left', font=(ui_font(), 11),
                                      wraplength=820)
        self._info_lbl.pack(fill='x', padx=(130, 20), pady=(0, 12))

        ctk.CTkFrame(self.frame, height=1, fg_color=BORDER, corner_radius=0).pack(fill='x')

        bar = ctk.CTkFrame(self.frame, fg_color='transparent')
        bar.pack(fill='x', padx=20, pady=10)
        _btn(bar, T('up_add_folder'), self._add_folder, primary=True).pack(side='left')
        _btn(bar, T('up_add_files'), self._add_files).pack(side='left', padx=8)
        _btn(bar, T('up_clear_done'), self._clear_finished).pack(side='right')
        _btn(bar, T('up_clear_cancelled'), self._clear_cancelled).pack(side='right', padx=(0, 8))
        _btn(bar, T('up_retry_all'), self._retry_all).pack(side='right', padx=(0, 8))
        _btn(bar, T('up_cancel_all'), self._cancel_all).pack(side='right', padx=(0, 8))

        # The same orders the Download list offers, so one habit covers both.
        self._sort = config.get_upload_sort()
        self._sort_labels = {
            'default': T('sort_default'), 'name': T('sort_name'),
            'size': T('sort_size'), 'newest': T('sort_newest'),
            'oldest': T('sort_oldest'),
        }
        self._sort_var = ctk.StringVar(value=self._sort_labels[self._sort])
        ctk.CTkOptionMenu(
            bar, values=list(self._sort_labels.values()),
            variable=self._sort_var, command=self._on_sort_change,
            width=150, height=32, corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT, button_color=BORDER_HOVER,
            button_hover_color=ACCENT, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI, font=(ui_font(), 10),
            dropdown_font=(ui_font(), 11), dynamic_resizing=False).pack(
                side='left', padx=8)

        self._summary_lbl = ctk.CTkLabel(self.frame, text='', text_color=TEXT_SEC, anchor='w',
                                         font=(ui_font(), 11))
        self._summary_lbl.pack(fill='x', padx=22, pady=(0, 4))

        # Virtual list: only the rows that fit on screen exist; scrolling
        # re-fills them with other uploads, so every upload is reachable and a
        # queue of thousands stays as light as a queue of ten.
        holder = ctk.CTkFrame(self.frame, fg_color=BG_DARK, corner_radius=0)
        holder.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self._scrollbar = ctk.CTkScrollbar(holder, command=self._on_scrollbar,
                                           button_color=BORDER_HOVER,
                                           button_hover_color=ACCENT)
        self._scrollbar.pack(side='right', fill='y', pady=4)
        self._scrollbar_shown = True
        self._viewport = tk.Frame(holder, bg=self._bg_color(), highlightthickness=0, bd=0)
        self._viewport.pack(side='left', fill='both', expand=True)
        self._viewport.bind('<Configure>', lambda _e: self._on_resize())
        self._bind_wheel(self._viewport)
        self._pool = []          # row widget sets, reused while scrolling
        self._first = 0          # index of the first upload shown
        self._view_jobs = []
        self._empty_lbl = ctk.CTkLabel(self._viewport, text=T('up_empty'),
                                       text_color=TEXT_DIM, font=(ui_font(), 12))

    # ── helpers ────────────────────────────────────────────────────────
    def _alive(self):
        return (not getattr(self.app, '_is_closing', False)
                and getattr(self.app, '_build_gen', 0) == self._gen)

    def _ui(self, fn):
        self.app._ui(fn, self._gen)

    def _info(self, text, color=WARNING):
        try:
            self._info_lbl.configure(text=text, text_color=color)
        except tk.TclError:
            pass

    def _current_remote(self):
        name = self._remote_var.get()
        return name if name in self._remotes else ''

    # ── account ────────────────────────────────────────────────────────
    def refresh_remotes(self, select=None):
        if not rclone.find_rclone():
            self._remotes = []
            self._remote_menu.configure(values=[T('up_no_account')])
            self._remote_var.set(T('up_no_account'))
            self._connect_btn.configure(state='disabled')
            self._info(T('up_rclone_missing'))
            return
        self._connect_btn.configure(state='normal')

        def work():
            try:
                names = [name for name, _kind in rclone.list_remotes()]
                error = ''
            except Exception as exc:
                names, error = [], str(exc)
            self._ui(lambda: self._apply_remotes(names, error, select))
        threading.Thread(target=work, daemon=True).start()

    def _apply_remotes(self, names, error, select):
        self._remotes = names
        self._remote_menu.configure(values=names or [T('up_no_account')])
        wanted = select or um.get_remote()
        if wanted in names:
            self._remote_var.set(wanted)
        elif names:
            self._remote_var.set(names[0])
        else:
            self._remote_var.set(T('up_no_account'))
        um.set_remote(self._current_remote())
        self._info(error or ('' if names else T('up_need_account')))
        self._refresh_key_status()

    def _on_remote(self, value):
        um.set_remote(value if value in self._remotes else '')
        self._refresh_key_status()

    # ── own Google client ID ───────────────────────────────────────────
    def _refresh_key_status(self):
        remote = self._current_remote()
        if not remote:
            self._key_lbl.configure(text='')
            return

        def work():
            own = rclone.uses_own_client(remote)
            kind = rclone.remote_settings(remote).get('type', '')

            def show():
                if kind and kind != 'drive':
                    self._key_lbl.configure(text='')
                elif own:
                    self._key_lbl.configure(text=T('up_key_own'), text_color=SUCCESS)
                else:
                    self._key_lbl.configure(text=T('up_key_shared'), text_color=WARNING)
            self._ui(show)
        threading.Thread(target=work, daemon=True).start()

    def _open_key_dialog(self):
        if not rclone.find_rclone():
            messagebox.showwarning(T('tab_upload'), T('up_rclone_missing'))
            return
        KeyDialog(self.app, self._current_remote(), self._on_key_saved)

    def _on_key_saved(self, name):
        self.refresh_remotes(select=name)
        self._info(T('up_key_done', name=name), SUCCESS)

    def _connect_drive(self):
        self._connect_btn.configure(state='disabled')
        self._info(T('up_connecting'), TEXT_SEC)

        def work():
            try:
                name = rclone.free_remote_name('gdrive')
                rclone.connect_google_drive(name)
            except Exception as exc:
                message = T('up_connect_failed', error=exc)
                self._ui(lambda: (self._info(message, ERROR_C),
                                  self._connect_btn.configure(state='normal')))
                return

            def done():
                self._connect_btn.configure(state='normal')
                self.refresh_remotes(select=name)
                self._info(T('up_connected', name=name), SUCCESS)
            self._ui(done)
        threading.Thread(target=work, daemon=True).start()

    def _speed_values(self):
        return speed_limit.menu_values(
            T('unlimited'), T('speed_custom'), um.get_bwlimit_bps())

    def _on_speed(self, value):
        if value == T('speed_custom'):
            bps = speed_limit.ask_custom(
                T('up_speed_limit'), T('speed_custom_prompt'),
                current_bps=um.get_bwlimit_bps(), master=self.app)
            if bps is None:
                self._speed_var.set(
                    speed_limit.format_speed(um.get_bwlimit_bps(), T('unlimited')))
                return
        else:
            bps = speed_limit.parse_speed(
                '0' if value == T('unlimited') else value) or 0
        self.mgr.set_speed_limit(bps)
        self._speed_menu.configure(values=self._speed_values())
        self._speed_var.set(speed_limit.format_speed(bps, T('unlimited')))

    def _on_delete_toggle(self):
        value = self._delete_var.get()
        if value and not messagebox.askyesno(T('up_delete_after'), T('up_delete_confirm')):
            self._delete_var.set(False)
            value = False
        um.set_delete_after(value)

    # ── adding jobs ────────────────────────────────────────────────────
    def _ready(self):
        if not rclone.find_rclone():
            messagebox.showwarning(T('tab_upload'), T('up_rclone_missing'))
            return False
        if not self._current_remote():
            messagebox.showwarning(T('tab_upload'), T('up_need_account'))
            return False
        um.set_folder(self._folder_var.get())
        return True

    def _add_folder(self):
        """Pick a local folder, then where it goes; every file gets its own row."""
        if not self._ready():
            return
        folder = filedialog.askdirectory(mustexist=True)
        if not folder:
            return
        count = sum(1 for _r, _d, files in os.walk(folder) for name in files
                    if not name.endswith(('.part', '.tmp', '.state.json')))
        if not count:
            messagebox.showinfo(T('tab_upload'), T('up_folder_empty'))
            return
        remote = self._current_remote()
        what = (os.path.basename(folder.rstrip('\\/')) or folder) + '  (' + \
            T('up_picker_files', n=count) + ')'

        def picked(cloud):
            jobs = self.mgr.add_folder_files(folder, remote=remote, folder=cloud)
            self._after_add(jobs, remote, cloud)
        FolderPicker(self.app, remote, um.get_last_pick(), picked,
                     subtitle=T('up_picker_for', what=what))

    def _add_files(self):
        """Pick files, then where they go."""
        if not self._ready():
            return
        paths = list(filedialog.askopenfilenames())
        if not paths:
            return
        remote = self._current_remote()
        what = (os.path.basename(paths[0]) if len(paths) == 1
                else T('up_picker_files', n=len(paths)))

        def picked(cloud):
            jobs = self.mgr.add_files(paths, remote=remote, folder=cloud)
            self._after_add(jobs, remote, cloud)
        FolderPicker(self.app, remote, um.get_last_pick(), picked,
                     subtitle=T('up_picker_for', what=what))

    def _after_add(self, jobs, remote, cloud):
        um.set_last_pick(cloud)
        self._info(T('up_added_n', n=len(jobs), dest=rclone.remote_path(remote, cloud)),
                   SUCCESS)

    def _choose_folder(self):
        if not self._ready():
            return
        FolderPicker(self.app, self._current_remote(), self._folder_var.get(),
                     self._on_folder_chosen)

    def _on_folder_chosen(self, folder):
        self._folder_var.set(folder)
        um.set_folder(folder)

    # ── job list ───────────────────────────────────────────────────────
    def _poll(self):
        if not self._alive():
            return
        try:
            if self.mgr.version != self._seen_version:
                self._seen_version = self.mgr.version
                self._render()
            self.app.after(500, self._poll)
        except tk.TclError:
            pass

    ROW_HEIGHT = 92          # fixed height of one upload row (incl. gap)

    def _bg_color(self):
        mode = 'dark' if ctk.get_appearance_mode().lower() == 'dark' else 'light'
        return color_for_mode(BG_DARK, mode)

    def _visible_count(self):
        height = max(1, self._viewport.winfo_height())
        return max(1, height // self.ROW_HEIGHT)

    def _on_resize(self):
        needed = max(1, -(-max(1, self._viewport.winfo_height()) // self.ROW_HEIGHT))
        while len(self._pool) < needed:
            self._pool.append(self._make_row())
        self._render()

    def _bind_wheel(self, widget):
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            tk.Misc.bind(widget, seq, self._on_wheel, add='+')
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _on_wheel(self, event):
        if getattr(event, 'num', None) == 4:
            step = -1
        elif getattr(event, 'num', None) == 5:
            step = 1
        else:
            delta = getattr(event, 'delta', 0)
            if not delta:
                return 'break'
            step = -1 if delta > 0 else 1
            if abs(delta) >= 240:               # fast wheels / touchpads
                step *= max(1, abs(delta) // 120)
        from siphon.ui import scroll as _scroll
        speed = _scroll._cache.get('speed')
        if speed is None:
            speed = _scroll._cache['speed'] = _scroll.get_speed()
        rows = max(1, round(speed / 4))   # speed 1-10 → 1-3 rows per notch
        self._scroll_to(self._first + step * rows)
        return 'break'

    def _on_scrollbar(self, *args):
        total = len(self._view_jobs)
        if not total or not args:
            return
        if args[0] == 'moveto':
            self._scroll_to(int(round(float(args[1]) * total)))
        elif args[0] == 'scroll':
            amount = int(args[1])
            unit = self._visible_count() if len(args) > 2 and args[2] == 'pages' else 1
            self._scroll_to(self._first + amount * unit)

    def _scroll_to(self, first):
        limit = max(0, len(self._view_jobs) - self._visible_count())
        first = max(0, min(int(first), limit))
        if first != self._first:
            self._first = first
            self._render(refresh_jobs=False)

    def _render(self, refresh_jobs=True):
        if refresh_jobs or not self._view_jobs:
            all_jobs = self._ordered_jobs()
            self._check_skipped(all_jobs)
            self._queue_pos = {jid: n + 1 for n, jid in enumerate(self.mgr.queue_ids())}
            self._update_summary(all_jobs)
            self._starts_in = self._start_estimates(all_jobs)
            self._view_jobs = all_jobs
        jobs = self._view_jobs
        total = len(jobs)
        visible = self._visible_count()
        self._first = max(0, min(self._first, max(0, total - visible)))
        try:
            if total:
                self._empty_lbl.place_forget()
            else:
                self._empty_lbl.place(relx=0.5, y=40, anchor='n')
            width = max(1, self._viewport.winfo_width())
            for slot, w in enumerate(self._pool):
                index = self._first + slot
                if index < total:
                    self._bind_row(w, jobs[index])
                    if w.get('_placed') != (slot, width):
                        if w.get('_size') != width:
                            w['row'].configure(width=width - 8, height=self.ROW_HEIGHT - 8)
                            w['_size'] = width
                        w['row'].place(x=4, y=slot * self.ROW_HEIGHT + 4)
                        w['_placed'] = (slot, width)
                    self._update_row(w, jobs[index])
                elif w.get('_placed') is not None:
                    w['row'].place_forget()
                    w['_placed'] = None
                    w['job_id'] = None
            if total:
                self._scrollbar.set(self._first / total,
                                    min(1.0, (self._first + visible) / total))
            else:
                self._scrollbar.set(0, 1)
            # No bar at all while everything fits.
            self._show_scrollbar(total > visible)
        except tk.TclError:
            pass

    def _show_scrollbar(self, wanted: bool):
        if bool(getattr(self, '_scrollbar_shown', True)) == bool(wanted):
            return
        self._scrollbar_shown = bool(wanted)
        try:
            if wanted:
                self._scrollbar.pack(side='right', fill='y', pady=4,
                                     before=self._viewport)
            else:
                self._scrollbar.pack_forget()
        except tk.TclError:
            pass

    def _upload_speed(self, jobs):
        """(bytes/s, is_limit): the speed uploads really have right now,
        averaged over a few seconds.  The limit is only a ceiling, so it
        stands in only while nothing is moving yet."""
        from siphon.core import eta
        average = getattr(self, '_speed_average', None)
        if average is None:
            average = self._speed_average = eta.SpeedAverage(window=5)
        measured = average.update(
            sum(j.speed for j in jobs if j.state == um.UPLOADING))
        return eta.pick(measured, um.get_bwlimit_bps())

    def _start_estimates(self, jobs):
        """{job id: seconds until it starts} for waiting uploads."""
        speed = getattr(self, '_eta_speed', 0) or 0
        if speed <= 0:
            return {}
        ahead = sum(max(0, (j.total_bytes or j.size_bytes) - j.done_bytes)
                    for j in jobs if j.state == um.UPLOADING)
        by_id = {j.id: j for j in jobs}
        result = {}
        for jid in self.mgr.queue_ids():
            job = by_id.get(jid)
            if job is None:
                continue
            # The limit is shared, so a file starts roughly when the bytes
            # ahead of it are done (whatever the number of parallel uploads).
            result[jid] = ahead / speed if ahead > 0 else 0
            ahead += job.size_bytes
        return result

    def _upload_eta(self, jobs):
        remaining = 0
        for job in jobs:
            if job.state == um.WAITING:
                remaining += job.size_bytes
            elif job.state == um.UPLOADING:
                total = job.total_bytes or job.size_bytes
                remaining += max(0, total - job.done_bytes)
        if not remaining:
            return ''
        speed, limited = self._upload_speed(jobs)
        self._eta_speed = speed
        size = _fmt_bytes(remaining)
        if speed <= 0:
            return T('eta_left_no_speed', size=size)
        return T('eta_left', size=size, time=_fmt_duration(remaining / speed),
                 speed=f'{_fmt_bytes(speed)}/s',
                 how=T('eta_at_limit') if limited else T('eta_at_current'))

    def _update_summary(self, jobs):
        counts = {}
        for job in jobs:
            counts[job.state] = counts.get(job.state, 0) + 1
        parts = [f'{T("up_state_" + state)}: {counts[state]}'
                 for state in (um.UPLOADING, um.WAITING, um.PAUSED, um.DONE,
                               um.SKIPPED, um.FAILED, um.CANCELLED) if counts.get(state)]
        eta = self._upload_eta(jobs)
        if eta:
            parts.append(eta)
        try:
            self._summary_lbl.configure(text='   ·   '.join(parts))
        except tk.TclError:
            pass

    def _check_skipped(self, jobs):
        """Tell the user (once) about uploads skipped because the file is
        already in the cloud folder."""
        skipped = {j.id: j for j in jobs if j.state == um.SKIPPED}
        seen = getattr(self, '_skip_seen', None)
        if seen is None:                      # first draw: restored history
            self._skip_seen = set(skipped)
            return
        new = [j for jid, j in skipped.items() if jid not in seen]
        if not new:
            return
        seen.update(j.id for j in new)
        pending = getattr(self, '_skip_pending', [])
        self._skip_pending = pending + new
        if not pending:
            self.app.after(1500, self._show_skipped)

    def _show_skipped(self):
        jobs, self._skip_pending = getattr(self, '_skip_pending', []), []
        if not jobs or not self._alive():
            return
        lines = [f'• {j.name}  →  {j.destination}' for j in jobs[:12]]
        if len(jobs) > 12:
            lines.append(f'… +{len(jobs) - 12}')
        self._info(T('up_skipped_msg', n=len(jobs)).rstrip(':'), SUCCESS)
        try:
            messagebox.showinfo(T('up_skipped_title'),
                                T('up_skipped_msg', n=len(jobs)) + '\n\n' + '\n'.join(lines),
                                parent=self.app)
        except tk.TclError:
            pass                      # the window is closing

    def _on_sort_change(self, label):
        """Put the list in the order the person picked, and keep it."""
        reverse = {text: key for key, text in self._sort_labels.items()}
        self._sort = reverse.get(label, 'default')
        config.set_upload_sort(self._sort)
        self._first = 0             # a new order starts at the top
        self._render()

    def _ordered_jobs(self):
        """Running and paused-in-progress uploads first, then the waiting
        queue in run order, then paused-before-start, then finished ones
        (newest first) — unless another order was picked, in which case that
        one replaces the grouping entirely.
        """
        jobs = self.mgr.jobs()
        chosen = getattr(self, '_sort', 'default')
        if chosen == 'name':
            return sorted(jobs, key=lambda j: str(j.name or '').lower())
        if chosen == 'size':
            return sorted(jobs, key=lambda j: (j.total_bytes or j.size_bytes or 0),
                          reverse=True)
        if chosen in ('newest', 'oldest'):
            def when(job):
                return float(job.finished_at or job.started_at
                             or job.created_at or 0)
            return sorted(jobs, key=when, reverse=chosen == 'newest')
        live = [j for j in jobs if j.state == um.UPLOADING
                or (j.state == um.PAUSED and j.started_at and j.finished_at is None)]
        waiting = [j for j in jobs if j.state == um.WAITING]
        held = [j for j in jobs if j.state == um.PAUSED and j not in live]
        done = sorted((j for j in jobs if j.state in um.FINISHED),
                      key=lambda j: (j.finished_at or 0, j.seq), reverse=True)
        return live + waiting + held + done

    def _make_row(self):
        """One reusable row; _bind_row() points it at an upload.

        Laid out like a Download row: one short horizontal strip, with the
        progress bar on the right instead of a full-width bar of its own.
        """
        row = ctk.CTkFrame(self._viewport, fg_color=BG_CARD, corner_radius=8,
                           border_width=1, border_color=BORDER,
                           height=self.ROW_HEIGHT - 8)
        row.pack_propagate(False)     # keep the fixed row size
        w = {'row': row, 'job_id': None, '_placed': None, 'q_visible': False,
             'last_q': None, 'q_editor': None}

        queue_box = ctk.CTkFrame(row, fg_color='transparent', width=38)
        queue_box.pack(side='left', fill='y', padx=(8, 0), pady=4)
        queue_box.pack_propagate(False)
        w['queue_box'] = queue_box
        w['q_up'] = ctk.CTkButton(queue_box, text='▲', width=30, height=16, corner_radius=4,
                                  fg_color='transparent', hover_color=BG_CARD_HOVER,
                                  text_color=TEXT_SEC, font=(ui_font(), 9),
                                  command=lambda: self._queue_step(w['job_id'], -1))
        w['q_num'] = ctk.CTkLabel(queue_box, text='', width=30, height=20, corner_radius=4,
                                  fg_color=BG_BADGE, text_color=TEXT_PRI, cursor='hand2',
                                  font=('Consolas', 11, 'bold'))
        w['q_num'].bind('<Button-1>', lambda _e: self._queue_edit(w))
        w['q_down'] = ctk.CTkButton(queue_box, text='▼', width=30, height=16, corner_radius=4,
                                    fg_color='transparent', hover_color=BG_CARD_HOVER,
                                    text_color=TEXT_SEC, font=(ui_font(), 9),
                                    command=lambda: self._queue_step(w['job_id'], +1))

        state_holder = ctk.CTkFrame(row, width=90, height=30, corner_radius=6,
                                    fg_color=BG_BADGE)
        state_holder.pack(side='left', padx=(12, 10))
        state_holder.pack_propagate(False)
        w['state'] = ctk.CTkLabel(state_holder, text='', font=(ui_font(), 10, 'bold'))
        w['state'].pack(fill='both', expand=True, padx=4)

        # Buttons first (rightmost), then the metrics column, then the text.
        w['action'] = _btn(row, '', lambda: self._row_action(w['job_id']), width=70)
        w['action'].configure(height=30)
        w['action'].pack(side='right', padx=(6, 10))
        w['pause'] = _btn(row, '', lambda: self._pause_action(w['job_id']), width=70)
        w['pause'].configure(height=30)
        w['pause'].pack(side='right')

        metrics = ctk.CTkFrame(row, fg_color='transparent')
        metrics.pack(side='right', padx=(6, 6))
        w['bar'] = ctk.CTkProgressBar(metrics, width=140, height=8, corner_radius=5,
                                      progress_color=ACCENT, fg_color=BG_INPUT)
        w['bar'].set(0)
        w['bar'].pack(pady=(0, 2))
        w['pct'] = ctk.CTkLabel(metrics, text='', text_color=TEXT_SEC,
                                font=('Consolas', 10, 'bold'))
        w['pct'].pack()

        stack = ctk.CTkFrame(row, fg_color='transparent')
        stack.pack(side='left', fill='both', expand=True, padx=(0, 10), pady=6)
        w['title'] = ctk.CTkLabel(stack, text='', text_color=TEXT_PRI, anchor='w',
                                  font=(ui_font(), 12, 'bold'))
        w['title'].pack(fill='x', anchor='w')
        w['detail'] = ctk.CTkLabel(stack, text='', text_color=TEXT_SEC, anchor='w',
                                   justify='left', font=('Consolas', 9))
        w['detail'].pack(fill='x', anchor='w', pady=(2, 0))
        w['dest'] = ctk.CTkLabel(stack, text='', text_color=TEXT_DIM, anchor='w',
                                 font=(ui_font(), 9))
        w['dest'].pack(fill='x', anchor='w')
        self._bind_wheel(row)
        return w

    def _bind_row(self, w, job):
        """Show `job` in the pooled row `w` (texts that only depend on the job)."""
        if w['job_id'] == job.id:
            return
        w['job_id'] = job.id
        w['sig'] = None
        w['last_q'] = None
        tags = []
        if job.auto:
            tags.append(T('up_auto_tag'))
        if job.move:
            tags.append(T('up_move_tag'))
        self._put(w, 'title', text=job.name + (f'   [{", ".join(tags)}]' if tags else ''))
        self._put(w, 'dest', text=f'📁 {job.destination}')

    @staticmethod
    def _put(w, key, **kwargs):
        # Only touch a widget when its look really changes: every
        # CustomTkinter configure() redraws the whole widget.
        cache = w.setdefault('_cache', {})
        items = tuple(sorted(kwargs.items()))
        if cache.get(key) != items:
            cache[key] = items
            w[key].configure(**kwargs)

    def _detail(self, job):
        """(text, colour) of the status line under the progress bar."""
        size_known = job.total_bytes or job.size_bytes
        done_of = (f'{_fmt_bytes(job.done_bytes)} / {_fmt_bytes(size_known)}'
                   if size_known else _fmt_bytes(job.done_bytes))
        elapsed = um.elapsed_seconds(job)
        clock = lambda ts: time.strftime('%H:%M', time.localtime(ts)) if ts else ''
        if job.state == um.UPLOADING:
            # The % sits on the progress bar now, so the line stays short:
            # how much, how fast, how long left.
            parts = [done_of]
            if job.speed:
                parts.append(f'{_fmt_bytes(job.speed)}/s')
            eta = _fmt_eta(job.eta)
            if eta:
                parts.append(f'ETA {eta}')
            text, color = '   ·   '.join(parts), TEXT_SEC
            if job.restart_note:
                text += '\n' + T('up_restart_note', p=job.restart_note)
            if job.resent_bytes > 1024 * 1024:
                text += '\n' + T('up_resent', size=_fmt_bytes(job.resent_bytes))
                color = WARNING
            if job.attempt > 1:
                reason = job.retry_reason.replace('\n', ' ')
                if len(reason) > 90:
                    reason = reason[:87] + '...'
                text += '\n' + T('up_retrying', n=job.attempt, m=job.max_attempts,
                                  reason=reason)
                color = WARNING
            return text, color
        if job.state == um.PAUSED:
            if job.started_at:
                return ('   ·   '.join([T('up_paused_at', p=job.progress), done_of,
                                         T('up_elapsed', t=_fmt_eta(elapsed) or '0s'),
                                         T('up_paused_note')]), WARNING)
            return T('up_waiting_size', size=_fmt_bytes(job.size_bytes)), WARNING
        if job.state == um.WAITING:
            pos = (getattr(self, '_queue_pos', {}) or {}).get(job.id, 0)
            parts = [T('up_queue_pos', n=pos)] if pos else []
            if job.size_bytes:
                parts.append(T('up_waiting_size', size=_fmt_bytes(job.size_bytes)))
            wait = (getattr(self, '_starts_in', {}) or {}).get(job.id)
            if wait is not None:
                parts.append(T('up_starts_in', time=_fmt_duration(wait)))
            text = '   ·   '.join(parts)
            if job.restart_note:
                text += '\n' + T('up_restart_note', p=job.restart_note)
            return text, TEXT_SEC
        if job.state == um.DONE:
            total = job.total_bytes or job.size_bytes
            avg = total / elapsed if elapsed > 0 else 0
            return (T('up_done_detail', size=_fmt_bytes(total), t=_fmt_eta(elapsed) or '0s',
                      speed=_fmt_bytes(avg), clock=clock(job.finished_at)), SUCCESS)
        if job.state == um.SKIPPED:
            return T('up_skipped_detail') + (T('up_skipped_kept') if job.move else ''), TEXT_SEC
        if job.state == um.FAILED:
            if job.error == 'SIGN_IN_EXPIRED':
                return T('up_sign_in_expired'), ERROR_C
            return job.error, ERROR_C
        if job.state == um.CANCELLED:
            return T('up_cancelled_at', p=job.progress), TEXT_DIM
        return '', TEXT_SEC

    def _update_queue_box(self, w, job):
        if w.get('q_editor') is not None:
            return
        positions = getattr(self, '_queue_pos', {}) or {}
        pos, total = positions.get(job.id), len(positions)
        if w['last_q'] == (pos, total):
            return
        w['last_q'] = (pos, total)
        try:
            if pos is None:
                if w['q_visible']:
                    for key in ('q_up', 'q_num', 'q_down'):
                        w[key].pack_forget()
                    w['q_visible'] = False
                return
            if not w['q_visible']:
                w['q_up'].pack(side='top')
                w['q_num'].pack(side='top', pady=1)
                w['q_down'].pack(side='top')
                w['q_visible'] = True
            self._put(w, 'q_num', text=str(pos))
            self._put(w, 'q_up', state='disabled' if pos <= 1 else 'normal')
            self._put(w, 'q_down', state='disabled' if pos >= total else 'normal')
        except tk.TclError:
            pass

    def _queue_step(self, job_id, delta):
        pos = (getattr(self, '_queue_pos', {}) or {}).get(job_id)
        if pos is not None and self.mgr.move_in_queue(job_id, pos + delta):
            self._render()

    def _queue_edit(self, w):
        """Turn the number into a small entry; Enter moves the upload there."""
        job_id = w.get('job_id')
        pos = (getattr(self, '_queue_pos', {}) or {}).get(job_id)
        if job_id is None or pos is None or w.get('q_editor') is not None:
            return
        var = ctk.StringVar(value=str(pos))
        editor = ctk.CTkEntry(w['queue_box'], textvariable=var, width=34, height=22,
                              corner_radius=4, border_width=1, border_color=ACCENT,
                              fg_color=BG_INPUT, text_color=TEXT_PRI, justify='center',
                              font=('Consolas', 11, 'bold'))
        w['q_num'].pack_forget()
        editor.pack(side='top', pady=1, after=w['q_up'])
        w['q_editor'] = editor
        editor.focus_set()
        editor.select_range(0, 'end')

        def finish(apply):
            if w.get('q_editor') is not editor:
                return
            w['q_editor'] = None
            value = var.get().strip()
            try:
                editor.destroy()
                w['q_num'].pack(side='top', pady=1, after=w['q_up'])
            except tk.TclError:
                pass
            w['last_q'] = None
            if apply and value.isdigit():
                self.mgr.move_in_queue(job_id, int(value))
            self._render()

        editor.bind('<Return>', lambda _e: finish(True))
        editor.bind('<KP_Enter>', lambda _e: finish(True))
        editor.bind('<Escape>', lambda _e: finish(False))
        editor.bind('<FocusOut>', lambda _e: finish(True))

    def _update_row(self, w, job):
        self._update_queue_box(w, job)
        sig = (job.id, job.state, job.progress, job.done_bytes >> 16, int(job.speed) >> 12,
               (getattr(self, '_queue_pos', {}) or {}).get(job.id),
               int(time.time()) if job.state == um.UPLOADING else 0,
               job.attempt, job.error, job.restart_note,
               int((getattr(self, '_starts_in', {}) or {}).get(job.id, -60) // 60))
        if w.get('sig') == sig:
            return
        w['sig'] = sig
        put = lambda key, **kw: self._put(w, key, **kw)
        try:
            put('state', text=T('up_state_' + job.state),
                text_color=_STATE_COLORS.get(job.state, TEXT_SEC))
            if w.get('_bar_value') != job.progress:
                w['_bar_value'] = job.progress
                w['bar'].set(job.progress / 100)
            put('bar', progress_color=(WARNING if job.state == um.PAUSED else
                                       SUCCESS if job.state in (um.DONE, um.SKIPPED) else ACCENT))
            put('pct', text=(f'{job.progress}%'
                             if job.state in (um.UPLOADING, um.PAUSED) else ''),
                text_color=_STATE_COLORS.get(job.state, TEXT_SEC))
            text, color = self._detail(job)
            put('detail', text=text, text_color=color)
            if job.state in (um.WAITING, um.UPLOADING, um.PAUSED):
                put('action', text=T('up_cancel'), state='normal')
            elif job.state in (um.FAILED, um.CANCELLED):
                put('action', text=T('up_retry'), state='normal')
            else:
                put('action', text='✓', state='disabled')
            if job.state in (um.WAITING, um.UPLOADING, um.PAUSED):
                put('pause', text=T('up_resume' if job.state == um.PAUSED else 'up_pause'),
                    state='normal')
                if not w['pause'].winfo_manager():
                    w['pause'].pack(side='right', after=w['action'])
            elif w['pause'].winfo_manager():
                w['pause'].pack_forget()
        except tk.TclError:
            pass

    def _count(self, states):
        return sum(1 for j in self.mgr.jobs() if j.state in states)

    def _cancel_all(self):
        n = self._count((um.WAITING, um.UPLOADING, um.PAUSED))
        if not n:
            self._info(T('up_nothing_to_cancel'), TEXT_SEC)
            return
        if messagebox.askyesno(T('up_cancel_all'), T('up_cancel_all_confirm', n=n),
                               parent=self.app):
            self.mgr.cancel_all()
            self._render()

    def _retry_all(self):
        n = self.mgr.retry_all()
        self._info(T('up_retried_n', n=n) if n else T('up_nothing_to_retry'),
                   SUCCESS if n else TEXT_SEC)
        self._render()

    def _clear_finished(self):
        n = self._count((um.DONE, um.SKIPPED))
        self.mgr.clear_finished()
        self._info(T('up_cleared_n', n=n), TEXT_SEC)
        self._render()

    def _clear_cancelled(self):
        n = self._count((um.FAILED, um.CANCELLED))
        self.mgr.clear_cancelled()
        self._info(T('up_cleared_n', n=n), TEXT_SEC)
        self._render()

    def _job(self, job_id):
        return next((j for j in self.mgr.jobs() if j.id == job_id), None)

    def _row_action(self, job_id):
        job = self._job(job_id)
        if job is None:
            return
        if job.state in (um.WAITING, um.UPLOADING, um.PAUSED):
            self.mgr.cancel(job.id)
        elif job.state in (um.FAILED, um.CANCELLED):
            self.mgr.retry(job.id)

    def _pause_action(self, job_id):
        job = self._job(job_id)
        if job is None:
            return
        if job.state == um.PAUSED:
            self.mgr.resume(job.id)
        elif job.state in (um.WAITING, um.UPLOADING):
            if not self.mgr.pause(job.id):
                self._info(T('up_state_failed') + ': pause', ERROR_C)


class KeyDialog(ctk.CTkToplevel):
    """Enter your own Google client ID/secret for the Drive account."""

    CONSOLE_URL = 'https://console.cloud.google.com/apis/credentials'

    def __init__(self, app, remote, on_done):
        super().__init__(app)
        self.app, self.remote, self.on_done = app, remote, on_done
        self.title(T('up_key_title'))
        self.geometry('620x430')
        self.configure(fg_color=BG_DARK)
        self.transient(app)
        body = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=12,
                            border_width=1, border_color=BORDER)
        body.pack(fill='both', expand=True, padx=16, pady=16)
        ctk.CTkLabel(body, text=T('up_key_title'), text_color=TEXT_PRI,
                     font=(ui_font(), 15, 'bold')).pack(anchor='w', padx=20, pady=(16, 4))
        ctk.CTkLabel(body, text=T('up_key_help'), text_color=TEXT_SEC, justify='left',
                     wraplength=540, font=(ui_font(), 11)).pack(anchor='w', padx=20)
        _btn(body, T('up_key_open_console'), self._open_console).pack(anchor='w', padx=20,
                                                                       pady=(10, 6))
        current = rclone.remote_settings(remote) if remote else {}
        self._id_var = ctk.StringVar(value=current.get('client_id', ''))
        self._secret_var = ctk.StringVar(value=current.get('client_secret', ''))
        for label, var in ((T('up_key_id'), self._id_var),
                           (T('up_key_secret'), self._secret_var)):
            ctk.CTkLabel(body, text=label, text_color=TEXT_SEC,
                         font=(ui_font(), 11, 'bold')).pack(anchor='w', padx=20, pady=(8, 0))
            ctk.CTkEntry(body, textvariable=var, height=34, corner_radius=CONTROL_RADIUS,
                         fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                         text_color=TEXT_PRI, font=('Consolas', 11)).pack(fill='x', padx=20)
        self._msg = ctk.CTkLabel(body, text='', text_color=WARNING, justify='left',
                                 wraplength=540, font=(ui_font(), 10))
        self._msg.pack(anchor='w', padx=20, pady=(8, 0))
        self._save_btn = _btn(body, T('up_key_save'), self._save, primary=True)
        self._save_btn.pack(anchor='e', padx=20, pady=(6, 16))
        self.after(50, self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _open_console(self):
        import webbrowser
        webbrowser.open(self.CONSOLE_URL)

    def _save(self):
        client_id = self._id_var.get().strip()
        secret = self._secret_var.get().strip()
        if not client_id or not secret:
            self._msg.configure(text=T('up_key_missing'), text_color=ERROR_C)
            return
        if not client_id.endswith('.apps.googleusercontent.com'):
            self._msg.configure(text=T('up_key_bad_id'), text_color=ERROR_C)
            return
        self._save_btn.configure(state='disabled')
        self._msg.configure(text=T('up_key_waiting'), text_color=TEXT_SEC)
        remote = self.remote

        def work():
            try:
                if remote and rclone.remote_settings(remote).get('type') == 'drive':
                    rclone.set_drive_client(remote, client_id, secret)
                    name = remote
                else:
                    name = rclone.free_remote_name('gdrive')
                    rclone.connect_google_drive(name, client_id, secret)
            except Exception as exc:
                message = T('up_key_failed', error=exc)

                def failed():
                    if self.winfo_exists():
                        self._msg.configure(text=message, text_color=ERROR_C)
                        self._save_btn.configure(state='normal')
                self.app._ui(failed)
                return

            def done():
                self.on_done(name)
                try:
                    self.grab_release()
                    self.destroy()
                except tk.TclError:
                    pass
            self.app._ui(done)
        threading.Thread(target=work, daemon=True).start()


class FolderPicker(ctk.CTkToplevel):
    """Small dialog for browsing folders on the cloud account."""

    def __init__(self, app, remote, start, on_pick, subtitle=''):
        super().__init__(app)
        self.app = app
        self.remote = remote
        self.on_pick = on_pick
        self.path = (start or '').replace('\\', '/').strip('/')
        self.title(T('up_picker_title'))
        self.geometry('460x480')
        self.configure(fg_color=BG_DARK)
        self.transient(app)

        if subtitle:
            ctk.CTkLabel(self, text=subtitle, text_color=TEXT_PRI, anchor='w',
                         justify='left', wraplength=420,
                         font=(ui_font(), 12, 'bold')).pack(fill='x', padx=16, pady=(14, 0))
        self._path_lbl = ctk.CTkLabel(self, text='', text_color=TEXT_SEC, anchor='w',
                                      justify='left', font=('Consolas', 11))
        self._path_lbl.pack(fill='x', padx=16, pady=(8 if subtitle else 14, 6))
        mode = 'dark' if ctk.get_appearance_mode().lower() == 'dark' else 'light'
        self._listbox = tk.Listbox(self, bg=color_for_mode(BG_INPUT, mode),
                                   fg=color_for_mode(TEXT_PRI, mode),
                                   selectbackground=color_for_mode(ACCENT, mode),
                                   selectforeground='#ffffff',
                                   activestyle='none', borderwidth=0, highlightthickness=0,
                                   font=(ui_font(), 11))
        self._listbox.pack(fill='both', expand=True, padx=16, pady=6)
        self._listbox.bind('<Double-Button-1>', self._enter)
        bar = ctk.CTkFrame(self, fg_color='transparent')
        bar.pack(fill='x', padx=16, pady=(6, 14))
        _btn(bar, T('up_picker_up'), self._up, width=70).pack(side='left')
        _btn(bar, T('up_picker_new'), self._new, width=100).pack(side='left', padx=8)
        _btn(bar, T('up_picker_use'), self._use, primary=True).pack(side='right')
        self.after(50, self._safe_grab)
        self._load()

    def _safe_grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _load(self):
        self._path_lbl.configure(text=rclone.remote_path(self.remote, self.path))
        self._listbox.delete(0, 'end')
        self._listbox.insert('end', T('up_picker_loading'))
        path = self.path

        def work():
            try:
                names, error = rclone.list_folders(self.remote, path), ''
            except Exception as exc:
                names, error = [], str(exc)
            self.app._ui(lambda: self._fill(path, names, error))
        threading.Thread(target=work, daemon=True).start()

    def _fill(self, path, names, error):
        if path != self.path or not self.winfo_exists():
            return
        self._listbox.delete(0, 'end')
        if error and self.path:
            # The remembered folder may have been renamed/deleted: start at the top.
            missing, self.path = self.path, ''
            self._load()
            self._path_lbl.configure(
                text=T('up_picker_missing', path=missing) + '\n'
                + rclone.remote_path(self.remote, ''))
            return
        if error:
            self._listbox.insert('end', error.strip().splitlines()[-1][:200])
            return
        for name in names:
            self._listbox.insert('end', '📁 ' + name)

    def _selected_name(self):
        sel = self._listbox.curselection()
        if not sel:
            return None
        text = self._listbox.get(sel[0])
        return text[2:] if text.startswith('📁 ') else None

    def _enter(self, _event=None):
        name = self._selected_name()
        if name:
            self.path = f'{self.path}/{name}' if self.path else name
            self._load()

    def _up(self):
        self.path = self.path.rsplit('/', 1)[0] if '/' in self.path else ''
        self._load()

    def _new(self):
        dialog = ctk.CTkInputDialog(text=T('up_picker_new_prompt'), title=T('up_picker_new'))
        name = (dialog.get_input() or '').strip().strip('/\\')
        if not name:
            return
        target = f'{self.path}/{name}' if self.path else name

        def work():
            try:
                rclone.make_folder(self.remote, target)
            except Exception as exc:
                # Bound as a default argument, not read from the enclosing
                # scope: Python clears the name at the end of an except
                # block, so a lambda that reads it later raises NameError and
                # the person is shown that instead of what actually failed.
                self.app._ui(lambda reason=str(exc): messagebox.showerror(
                    T('up_picker_new'), reason))
                return
            self.app._ui(self._load)
        threading.Thread(target=work, daemon=True).start()

    def _use(self):
        name = self._selected_name()
        if name:
            self.path = f'{self.path}/{name}' if self.path else name
        self.on_pick(self.path)
        self.destroy()
