"""The Settings tab and the update check: building the page and reacting to what is changed on it."""

import os
import sys
import threading
import tkinter as tk
import webbrowser
import customtkinter as ctk

from tkinter import filedialog, messagebox
from urllib.parse import urlsplit
from siphon.core import config, updater
from siphon.i18n.locales import T, get_lang, ui_font
from siphon.metadata import PRODUCT_NAME
from siphon.sites.base import last_mirror_failure
from siphon.ui import scroll as ui_scroll, speed_limit
from siphon.ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    BG_CARD,
    BG_CARD_HOVER,
    BG_DARK,
    BG_INPUT,
    BORDER,
    BORDER_CARD,
    BORDER_HOVER,
    CARD_RADIUS,
    CONTROL_RADIUS,
    ERROR_C,
    SUCCESS,
    TEXT_DIM,
    TEXT_PRI,
    TEXT_SEC,
    WARNING,
    WHITE)
from siphon.apps.app_basics import (
    APP_VERSION,
    MAX_CONCURRENT,
    SETTINGS_INLINE_HELP_WRAP,
    SITES,
    SLOW_REQUEUE_GRACE_SECONDS,
    SLOW_REQUEUE_MAX_ATTEMPTS)


class SettingsMixin:
    """The Settings tab and the update check: building the page and reacting to what is changed on it."""

    def _short_update_note(self, info):
        notes = (info or {}).get('notes') or ''
        for line in notes.splitlines():
            line = line.strip()
            if line:
                return line[:180]
        return ''

    def _show_update_prompt(self, info):
        if self._is_closing or self._update_prompt_shown:
            return
        self._update_prompt_shown = True
        prompt = None
        try:
            prompt = ctk.CTkToplevel(self)
            prompt.title(T('update_prompt_title'))
            prompt.configure(fg_color=BG_CARD)
            prompt.resizable(False, False)
            prompt.transient(self)

            pos_width, pos_height = 420, 220
            self.update_idletasks()
            x = self.winfo_rootx() + max((self.winfo_width() - pos_width) // 2, 0)
            y = self.winfo_rooty() + 80
            x = max(min(x, self.winfo_screenwidth() - pos_width), 0)
            y = max(min(y, self.winfo_screenheight() - pos_height), 0)

            body = ctk.CTkFrame(prompt, fg_color=BG_CARD, corner_radius=0)
            body.pack(fill='both', expand=True, padx=22, pady=20)

            ctk.CTkLabel(
                body, text=T('update_prompt_title'),
                font=(ui_font(), 16, 'bold'), text_color=TEXT_PRI
            ).pack(anchor='w')

            tag = (info or {}).get('tag') or (info or {}).get('version')
            ctk.CTkLabel(
                body, text=T('update_available', version=tag),
                font=(ui_font(), 12), text_color=TEXT_SEC,
                wraplength=360, justify='left'
            ).pack(anchor='w', pady=(12, 0))

            note = self._short_update_note(info)
            if note:
                ctk.CTkLabel(
                    body, text=note, font=(ui_font(), 10),
                    text_color=TEXT_DIM, wraplength=360, justify='left'
                ).pack(anchor='w', pady=(8, 0))

            row = ctk.CTkFrame(body, fg_color='transparent')
            row.pack(fill='x', pady=(18, 0))

            def _close():
                try:
                    prompt.destroy()
                except tk.TclError:
                    pass

            def _install():
                _close()
                self._start_update_install()

            later_btn = ctk.CTkButton(
                row, text=T('update_prompt_later'), width=118, height=34,
                corner_radius=8, fg_color='transparent', border_width=1,
                border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
                text_color=TEXT_PRI, command=_close)

            update_btn = ctk.CTkButton(
                row, text=T('update_now_btn'), width=118, height=34,
                corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                text_color=('#FFFFFF', '#FFFFFF'), command=_install
            )
            update_btn.pack(side='right')
            later_btn.pack(side='right', padx=(0, 8))

            prompt.protocol('WM_DELETE_WINDOW', _close)
            prompt.bind('<Escape>', lambda _event: _close())
            prompt.update_idletasks()
            prompt.geometry(f'+{x}+{y}')
            prompt.deiconify()
            prompt.lift()
            prompt.focus_force()
            later_btn.focus_force()
        except Exception:
            if prompt is not None:
                try:
                    prompt.destroy()
                except tk.TclError:
                    pass

    def _set_update_status(self, text, color=None):
        self._update_status_text = text
        self._update_status_color = color or TEXT_DIM
        self._refresh_update_ui()

    def _refresh_update_ui(self):
        available = bool(self._update_info)
        status = self._update_status_text or T('update_idle')
        if self._update_status_lbl is not None:
            try:
                self._update_status_lbl.configure(
                    text=status, text_color=self._update_status_color)
            except tk.TclError:
                pass
        if self._update_note_lbl is not None:
            try:
                if available:
                    note = self._short_update_note(self._update_info)
                    tag = self._update_info.get('tag') or self._update_info.get('version')
                    text = T('update_available', version=tag)
                    if note:
                        text = f'{text}  {note}'
                    self._update_note_lbl.configure(text=text)
                else:
                    self._update_note_lbl.configure(text='')
            except tk.TclError:
                pass
        if self._update_check_btn is not None:
            try:
                self._update_check_btn.configure(
                    state='disabled' if self._update_checking else 'normal')
            except tk.TclError:
                pass
        if self._update_now_btn is not None:
            try:
                if available:
                    if not self._update_now_btn.winfo_manager():
                        self._update_now_btn.pack(side='left', padx=(8, 0))
                    self._update_now_btn.configure(
                        state='disabled' if self._update_installing else 'normal')
                else:
                    self._update_now_btn.configure(state='disabled')
                    self._update_now_btn.pack_forget()
            except tk.TclError:
                pass
        if self._update_badge is not None:
            try:
                if available:
                    if not self._update_badge.winfo_manager():
                        self._update_badge.pack(side='left', padx=(8, 0))
                else:
                    self._update_badge.pack_forget()
            except tk.TclError:
                pass

    def _check_updates_clicked(self):
        """Update checking waits until this app has a release of its own."""
        if updater.PERSONAL_FORK:
            self._set_update_status(T('update_not_published'), TEXT_SEC)
            return
        self._start_update_check(manual=True)

    def _start_update_check(self, manual=False):
        if self._is_closing or self._update_checking:
            return
        self._update_checking = True
        if manual:
            self._set_update_status(T('update_checking'), TEXT_SEC)
        else:
            self._refresh_update_ui()

        def _worker():
            info = None
            newer = False
            try:
                info = updater.check_latest()
                newer = bool(info and updater.is_newer(
                    info.get('version', ''), APP_VERSION))
            except Exception:
                info = None
                newer = False

            def _apply():
                self._update_checking = False
                if newer:
                    self._update_info = info
                    tag = info.get('tag') or info.get('version')
                    self._set_update_status(
                        T('update_available', version=tag), SUCCESS)
                    if not manual and not self._update_prompt_shown:
                        self._show_update_prompt(info)
                elif manual:
                    self._update_info = None
                    self._set_update_status(T('update_uptodate'), TEXT_SEC)
                elif info is not None:
                    self._update_info = None
                    self._refresh_update_ui()
                else:
                    if manual:
                        self._set_update_status(T('update_failed'), ERROR_C)
                    else:
                        self._refresh_update_ui()

            self._ui(_apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _start_update_install(self):
        info = self._update_info
        if self._is_closing or self._update_installing or not info:
            return
        if not updater.is_frozen():
            try:
                webbrowser.open(info.get('html_url') or updater.API_LATEST)
            except Exception:
                pass
            self._set_update_status(T('update_from_source'), WARNING)
            return

        name = updater.current_exe_name()
        url = updater.find_asset_url(info, 'browse')
        if not url:
            self._set_update_status(T('update_failed'), ERROR_C)
            return

        self._update_installing = True
        self._set_update_status(T('update_downloading', pct=0), TEXT_SEC)

        def _worker():
            exe_dir = os.path.dirname(sys.executable)
            new_path = os.path.join(exe_dir, name + '.new')

            def _progress(downloaded, total):
                pct = int(downloaded * 100 / total) if total else 0
                self._ui(lambda p=pct: self._set_update_status(
                    T('update_downloading', pct=p), TEXT_SEC))

            ok = updater.download_asset(url, new_path, progress_cb=_progress)
            if ok and updater.apply_update_and_restart(new_path):
                self._ui(lambda: self._set_update_status(
                    T('update_restarting'), SUCCESS))
                self._ui(self._on_close)
                return

            def _failed():
                self._update_installing = False
                self._set_update_status(T('update_failed'), ERROR_C)

            self._ui(_failed)

        threading.Thread(target=_worker, daemon=True).start()

    def _show_update_settings(self, event=None):
        self._select_tab('settings')

    # ── Build UI ─────────────────────────────────────────────────────
    def _theme_glyph(self):
        return {'system': '◐', 'light': '☀', 'dark': '☾'}.get(self._theme_mode, '◐')

    def _cycle_theme(self):
        modes = ('system', 'light', 'dark')
        try:
            idx = modes.index(self._theme_mode)
        except ValueError:
            idx = 0
        self._theme_mode = modes[(idx + 1) % len(modes)]
        ctk.set_appearance_mode(self._theme_mode)
        config.set_theme(self._theme_mode)
        self._theme_btn.configure(text=self._theme_glyph())

    def _speed_values(self):
        return speed_limit.menu_values(
            T('unlimited'), T('speed_custom'),
            int(self._speed_mbps * 1024 * 1024))

    def _speed_label(self):
        return speed_limit.format_speed(
            int(self._speed_mbps * 1024 * 1024), T('unlimited'))

    def _resolution_values(self):
        return [T('resolution_highest'), '1080p', '720p', '480p', '360p',
                T('resolution_lowest')]

    def _resolution_pref_from_label(self, label):
        label = str(label or '').strip()
        if label == T('resolution_lowest'):
            return 'lowest'
        if label in {'1080p', '720p', '480p', '360p'}:
            return label[:-1]
        return 'highest'

    def _resolution_label(self):
        from siphon.sites.base import get_resolution_pref
        pref = get_resolution_pref()
        if pref == 'lowest':
            return T('resolution_lowest')
        if pref in {'1080', '720', '480', '360'}:
            return f'{pref}p'
        return T('resolution_highest')

    def _on_lang_change(self, display_name):
        code = self._lang_code_by_name.get(display_name)
        if not code or code == get_lang():
            return
        self._apply_language(code)

    def _var_get(self, name, default=''):
        var = getattr(self, name, None)
        if var is None:
            return default
        try:
            return var.get()
        except (AttributeError, tk.TclError):
            return default

    def _open_log_file(self):
        from siphon.core import applog
        path = applog.log_path()
        if path is None or not os.path.exists(path):
            messagebox.showinfo(T('open_log'), str(path or '-'))
            return
        try:
            if os.name == 'nt':
                os.startfile(str(path))
            else:
                import subprocess
                subprocess.Popen(['xdg-open', str(path)])
        except Exception as exc:
            messagebox.showerror(T('open_log'), f'{path}\n{exc}')

    def _build_update_card(self, content):
        upd = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                           border_width=1, border_color=BORDER_CARD)
        upd.pack(fill='x', pady=(0, 16))

        upd_hdr = ctk.CTkFrame(upd, fg_color='transparent')
        upd_hdr.pack(fill='x', padx=20, pady=(16, 12))
        ctk.CTkLabel(upd_hdr, text=PRODUCT_NAME,
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')

        ctk.CTkFrame(upd, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        row_info = ctk.CTkFrame(upd, fg_color='transparent')
        row_info.pack(fill='x', padx=20, pady=(14, 16))

        row_actions = ctk.CTkFrame(row_info, fg_color='transparent')
        row_actions.pack(side='right', anchor='e')

        left_info = ctk.CTkFrame(row_info, fg_color='transparent')
        left_info.pack(side='left', fill='x', expand=True, padx=(0, 16))
        ctk.CTkLabel(left_info, text=T('update_current', version=APP_VERSION),
                     font=(ui_font(), 12, 'bold'),
                     text_color=TEXT_PRI).pack(anchor='w')
        ctk.CTkLabel(left_info, text=T('app_brand_2'),
                     font=(ui_font(), 10),
                     text_color=TEXT_DIM).pack(anchor='w', pady=(2, 0))

        self._update_status_lbl = ctk.CTkLabel(
            left_info, text='', text_color=TEXT_DIM, font=(ui_font(), 11))
        self._update_status_lbl.pack(anchor='w', pady=(3, 0))

        self._update_note_lbl = ctk.CTkLabel(
            left_info, text='', text_color=TEXT_DIM, font=(ui_font(), 10),
            wraplength=620, justify='left')
        self._update_note_lbl.pack(anchor='w', pady=(1, 0))

        self._update_check_btn = ctk.CTkButton(
            row_actions, text=T('update_check_btn'), width=138, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=self._check_updates_clicked)
        self._update_check_btn.pack(side='left')
        self._update_now_btn = ctk.CTkButton(
            row_actions, text=T('update_now_btn'), width=118, height=38,
            corner_radius=CONTROL_RADIUS, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE,
            command=self._start_update_install)
        self._refresh_update_ui()

    # ── Settings Tab ─────────────────────────────────────────────────
    def _build_settings_tab(self):
        tab = self._tab_frames['settings']

        outer = ctk.CTkScrollableFrame(
            tab, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        outer.pack(fill='both', expand=True)

        # Content container
        content = ctk.CTkFrame(outer, fg_color='transparent')
        content.pack(fill='x', padx=64, pady=28)

        # ── Page title ──────────────────────────────────────────────
        title_row = ctk.CTkFrame(content, fg_color='transparent')
        title_row.pack(fill='x', pady=(0, 22))
        ctk.CTkLabel(title_row, text=T('settings_title'),
                     font=(ui_font(), 22, 'bold'),
                     text_color=TEXT_PRI).pack(anchor='w')
        ctk.CTkLabel(title_row, text=T('settings_desc'),
                     font=(ui_font(), 11),
                     text_color=TEXT_DIM).pack(anchor='w', pady=(4, 0))

        # ── Download Settings Card ──────────────────────────────────
        grp = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                            border_width=1, border_color=BORDER_CARD)
        grp.pack(fill='x', pady=(0, 16))

        # Card header
        grp_hdr = ctk.CTkFrame(grp, fg_color='transparent')
        grp_hdr.pack(fill='x', padx=20, pady=(16, 12))
        ctk.CTkLabel(grp_hdr, text=T('download_settings'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')

        ctk.CTkFrame(grp, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        # Save location
        row_dest = ctk.CTkFrame(grp, fg_color='transparent')
        row_dest.pack(fill='x', padx=20, pady=(16, 2))
        ctk.CTkLabel(row_dest, text=T('save_location_setting'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkEntry(row_dest, textvariable=self._dest_var,
                     height=38, corner_radius=CONTROL_RADIUS,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI).pack(side='left', fill='x',
                                               expand=True, padx=10)
        ctk.CTkButton(row_dest, text=T('browse_folder'), width=60, height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._pick_dest).pack(side='left')
        ctk.CTkLabel(grp, text=T('save_location_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 0), pady=(0, 10))

        # Speed limit
        row_speed = ctk.CTkFrame(grp, fg_color='transparent')
        row_speed.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_speed, text=T('speed_limit_setting'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        menu = ctk.CTkOptionMenu(row_speed, values=self._speed_values(),
                          variable=self._speed_var,
                          command=self._on_speed_change, width=130, height=34,
                          corner_radius=8,
                          fg_color=BG_INPUT, button_color=BORDER_HOVER,
                          button_hover_color=ACCENT, text_color=TEXT_PRI,
                          dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                          dropdown_text_color=TEXT_PRI)
        menu.pack(side='left', padx=10)
        self._speed_menus = getattr(self, '_speed_menus', []) + [menu]
        ctk.CTkLabel(grp, text=T('speed_limit_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 0), pady=(0, 10))

        # Concurrent downloads
        row_conc = ctk.CTkFrame(grp, fg_color='transparent')
        row_conc.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_conc, text=T('concurrent_setting'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        self._conc_var = ctk.StringVar(value=str(self._dlmgr.max_concurrent))
        self._conc_entry = ctk.CTkEntry(
            row_conc, textvariable=self._conc_var, width=80, height=34,
            corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, border_width=1,
            text_color=TEXT_PRI, justify='center')
        self._conc_entry.pack(side='left', padx=10)
        self._conc_entry.bind('<Return>', self._on_conc_change)
        self._conc_entry.bind('<FocusOut>', self._on_conc_change)
        ctk.CTkLabel(row_conc, text=T('max_n', n=MAX_CONCURRENT),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(side='left')
        ctk.CTkLabel(grp, text=T('concurrent_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 0), pady=(0, 10))

        # Segment workers used inside each individual video download
        row_workers = ctk.CTkFrame(grp, fg_color='transparent')
        row_workers.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_workers, text=T('max_workers_per_video_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        # Global default (kept for language-rebuild snapshots) + per-site picker.
        self._workers_var = ctk.StringVar(
            value=str(config.get_max_workers_per_video()))
        all_label = T('workers_all_sites')
        self._workers_site_var = ctk.StringVar(value=all_label)
        ctk.CTkOptionMenu(
            row_workers, values=[all_label] + config.worker_sites(),
            variable=self._workers_site_var,
            command=lambda _v: self._show_site_workers(),
            width=150, height=34, corner_radius=CONTROL_RADIUS,
            fg_color=ACCENT, button_color=ACCENT_HOVER,
            button_hover_color=ACCENT_HOVER, text_color=WHITE,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI, font=(ui_font(), 11, 'bold'),
            dropdown_font=(ui_font(), 11), dynamic_resizing=False,
        ).pack(side='left', padx=(10, 10))
        self._workers_slider = ctk.CTkSlider(
            row_workers, from_=1, to=config.MAX_WORKERS_PER_VIDEO,
            number_of_steps=config.MAX_WORKERS_PER_VIDEO - 1, width=220,
            progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            command=self._on_workers_slide)
        self._workers_slider.pack(side='left')
        self._workers_value_lbl = ctk.CTkLabel(
            row_workers, text='', width=34, text_color=TEXT_PRI,
            font=('Consolas', 13, 'bold'))
        self._workers_value_lbl.pack(side='left', padx=(8, 4))
        self._workers_range_lbl = ctk.CTkLabel(
            row_workers, text='', text_color=TEXT_DIM, font=(ui_font(), 10))
        self._workers_range_lbl.pack(side='left', padx=(0, 8))
        self._workers_reset_btn = ctk.CTkButton(
            row_workers, text=T('workers_use_default'), width=110, height=30,
            corner_radius=CONTROL_RADIUS, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, font=(ui_font(), 10),
            command=self._reset_site_workers)
        self._show_site_workers()
        ctk.CTkLabel(
            grp,
            text=T(
                'max_workers_per_video_desc',
                n=config.MAX_WORKERS_PER_VIDEO),
            text_color=TEXT_DIM, font=(ui_font(), 10),
            wraplength=SETTINGS_INLINE_HELP_WRAP,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        # Automatic requeue of downloads stuck below a speed threshold
        row_slow_requeue = ctk.CTkFrame(grp, fg_color='transparent')
        row_slow_requeue.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_slow_requeue, text=T('slow_requeue_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._slow_requeue_var = ctk.StringVar(
            value=str(config.get_slow_requeue_kbps()))
        self._slow_requeue_entry = ctk.CTkEntry(
            row_slow_requeue, textvariable=self._slow_requeue_var, width=80,
            height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, border_width=1,
            text_color=TEXT_PRI, justify='center')
        self._slow_requeue_entry.pack(side='left', padx=10)
        self._slow_requeue_entry.bind('<Return>', self._on_slow_requeue_change)
        self._slow_requeue_entry.bind('<FocusOut>', self._on_slow_requeue_change)
        ctk.CTkLabel(
            row_slow_requeue, text=T('slow_requeue_unit'),
            text_color=TEXT_DIM, font=(ui_font(), 10)).pack(side='left')
        ctk.CTkLabel(
            grp,
            text=T(
                'slow_requeue_desc',
                grace=SLOW_REQUEUE_GRACE_SECONDS,
                n=SLOW_REQUEUE_MAX_ATTEMPTS),
            text_color=TEXT_DIM, font=(ui_font(), 10),
            wraplength=SETTINGS_INLINE_HELP_WRAP,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        # Resolution preference
        row_res = ctk.CTkFrame(grp, fg_color='transparent')
        row_res.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_res, text=T('resolution_setting'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        self._res_var = ctk.StringVar(value=self._resolution_label())
        ctk.CTkOptionMenu(row_res,
                          values=self._resolution_values(),
                          variable=self._res_var,
                          command=self._on_res_change, width=180, height=34,
                          corner_radius=8,
                          fg_color=BG_INPUT, button_color=BORDER_HOVER,
                          button_hover_color=ACCENT, text_color=TEXT_PRI,
                          dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                          dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)
        ctk.CTkLabel(grp, text=T('resolution_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 0), pady=(0, 10))

        # "Filename format" used to sit here: a choice between the whole
        # title and "code only", which kept everything before the first
        # space.  That is a rule for Japanese studio codes — its own example
        # was FC2-PPV-1234567 — and on an ordinary title it simply throws
        # the name away: "Rainy Window Jazz" became "Rainy".  The template
        # below does the same job without guessing.

        row_template = ctk.CTkFrame(grp, fg_color='transparent')
        row_template.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_template, text=T('filename_template_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._filename_template_var = ctk.StringVar(
            value=config.get_filename_template())
        template_entry = ctk.CTkEntry(
            row_template, textvariable=self._filename_template_var,
            height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, text_color=TEXT_PRI)
        template_entry.pack(side='left', fill='x', expand=True, padx=10)
        template_entry.bind('<Return>', self._on_filename_template_change)
        template_entry.bind('<FocusOut>', self._on_filename_template_change)
        ctk.CTkLabel(
            grp, text=T('filename_template_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_schedule = ctk.CTkFrame(grp, fg_color='transparent')
        row_schedule.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_schedule, text=T('download_schedule_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._download_schedule_var = ctk.StringVar(
            value=config.get_download_schedule())
        schedule_entry = ctk.CTkEntry(
            row_schedule, textvariable=self._download_schedule_var,
            width=100, height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, text_color=TEXT_PRI,
            placeholder_text='HH:MM', justify='center')
        schedule_entry.pack(side='left', padx=10)
        schedule_entry.bind('<Return>', self._on_download_schedule_change)
        schedule_entry.bind('<FocusOut>', self._on_download_schedule_change)
        ctk.CTkLabel(
            grp, text=T('download_schedule_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_safety = ctk.CTkFrame(grp, fg_color='transparent')
        row_safety.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_safety, text=T('minimum_free_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._minimum_free_var = ctk.StringVar(
            value=str(config.get_minimum_free_gb()))
        minimum_entry = ctk.CTkEntry(
            row_safety, textvariable=self._minimum_free_var,
            width=80, height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, text_color=TEXT_PRI, justify='center')
        minimum_entry.pack(side='left', padx=10)
        minimum_entry.bind('<Return>', self._on_minimum_free_change)
        minimum_entry.bind('<FocusOut>', self._on_minimum_free_change)
        ctk.CTkLabel(
            row_safety, text='GB', text_color=TEXT_DIM,
            font=(ui_font(), 10)).pack(side='left')
        ctk.CTkLabel(
            grp, text=T('minimum_free_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_retry = ctk.CTkFrame(grp, fg_color='transparent')
        row_retry.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_retry, text=T('auto_retry_setting'), text_color=TEXT_PRI,
            font=(ui_font(), 12, 'bold'), width=116,
            anchor='w').pack(side='left')
        self._auto_retry_var = ctk.StringVar(
            value=str(config.get_auto_retry_count()))
        retry_entry = ctk.CTkEntry(
            row_retry, textvariable=self._auto_retry_var,
            width=80, height=34, corner_radius=8, fg_color=BG_INPUT,
            border_color=BORDER, text_color=TEXT_PRI, justify='center')
        retry_entry.pack(side='left', padx=10)
        retry_entry.bind('<Return>', self._on_auto_retry_change)
        retry_entry.bind('<FocusOut>', self._on_auto_retry_change)
        ctk.CTkLabel(
            grp, text=T('auto_retry_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=620,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        # Mouse-wheel scroll speed for every list in the app
        row_scroll = ctk.CTkFrame(grp, fg_color='transparent')
        row_scroll.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_scroll, text=T('scroll_speed_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        steps = ui_scroll.MAX_SPEED - ui_scroll.MIN_SPEED
        self._scroll_speed_lbl = ctk.CTkLabel(
            row_scroll, text=f'{ui_scroll.get_speed()}x', width=36,
            text_color=TEXT_PRI, font=('Consolas', 13, 'bold'))
        scroll_slider = ctk.CTkSlider(
            row_scroll, from_=ui_scroll.MIN_SPEED, to=ui_scroll.MAX_SPEED,
            number_of_steps=steps, width=220, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            command=self._on_scroll_speed)
        scroll_slider.set(ui_scroll.get_speed())
        scroll_slider.pack(side='left', padx=10)
        self._scroll_speed_lbl.pack(side='left')
        ctk.CTkLabel(
            grp, text=T('scroll_speed_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=SETTINGS_INLINE_HELP_WRAP,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        row_notify = ctk.CTkFrame(grp, fg_color='transparent')
        row_notify.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(
            row_notify, text=T('notify_complete_setting'),
            text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
            width=116, anchor='w').pack(side='left')
        self._notify_complete_var = ctk.BooleanVar(
            value=config.get_notify_on_complete())
        ctk.CTkSwitch(
            row_notify, text='', variable=self._notify_complete_var,
            command=self._on_notify_complete_change,
            progress_color=ACCENT).pack(side='left', padx=10)
        ctk.CTkLabel(
            grp, text=T('notify_complete_desc'), text_color=TEXT_DIM,
            font=(ui_font(), 10), wraplength=SETTINGS_INLINE_HELP_WRAP,
            justify='left', anchor='w').pack(
                anchor='w', padx=(136, 20), pady=(0, 10))

        # App-scoped network proxy
        proxy = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                             border_width=1, border_color=BORDER_CARD)
        proxy.pack(fill='x', pady=(0, 16))

        proxy_hdr = ctk.CTkFrame(proxy, fg_color='transparent')
        proxy_hdr.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(proxy_hdr, text=T('proxy_card_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')
        ctk.CTkLabel(proxy, text=T('proxy_card_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=20, pady=(0, 12))

        ctk.CTkFrame(proxy, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        self._proxy_var = ctk.StringVar(value=config.get_proxy_url())
        row_proxy = ctk.CTkFrame(proxy, fg_color='transparent')
        row_proxy.pack(fill='x', padx=20, pady=(16, 2))
        ctk.CTkLabel(row_proxy, text=T('proxy_url_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkEntry(
            row_proxy, textvariable=self._proxy_var,
            placeholder_text=T('proxy_url_placeholder'),
            height=34, corner_radius=8,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            text_color=TEXT_PRI).pack(side='left', fill='x', expand=True, padx=10)

        proxy_actions = ctk.CTkFrame(proxy, fg_color='transparent')
        proxy_actions.pack(fill='x', padx=20, pady=(10, 2))
        ctk.CTkButton(
            proxy_actions, text=T('proxy_save'), width=70, height=34,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE, command=self._on_proxy_save).pack(
                side='left', padx=(126, 6))
        ctk.CTkButton(
            proxy_actions, text=T('proxy_windows'), width=86, height=34,
            corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=self._on_proxy_windows).pack(side='left', padx=(0, 6))
        ctk.CTkButton(
            proxy_actions, text=T('proxy_clear'), width=70, height=34,
            corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, command=self._on_proxy_clear).pack(side='left')
        self._proxy_status_lbl = ctk.CTkLabel(
            proxy_actions, text='', text_color=TEXT_SEC, font=(ui_font(), 10))
        self._proxy_status_lbl.pack(side='left', padx=12)
        self._refresh_proxy_status()

        ctk.CTkLabel(proxy, text=T('proxy_help'),
                     text_color=TEXT_DIM, font=(ui_font(), 9),
                     wraplength=720, justify='left').pack(
                         anchor='w', padx=20, pady=(6, 18))

        # Cloudflare bypass
        cf = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                          border_width=1, border_color=BORDER_CARD)
        cf.pack(fill='x', pady=(0, 16))

        cf_hdr = ctk.CTkFrame(cf, fg_color='transparent')
        cf_hdr.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(cf_hdr, text=T('cf_card_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')
        ctk.CTkLabel(cf, text=T('cf_card_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=20, pady=(0, 12))

        ctk.CTkFrame(cf, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        hosts = sorted({h for mirrors in config.MIRRORS.values() for h in mirrors})
        default_host = hosts[0] if hosts else ''
        self._cf_host_var = ctk.StringVar(value=default_host)
        self._cf_cookie_var = ctk.StringVar()
        self._cf_ua_var = ctk.StringVar()

        row_host = ctk.CTkFrame(cf, fg_color='transparent')
        row_host.pack(fill='x', padx=20, pady=(16, 2))
        ctk.CTkLabel(row_host, text=T('cf_host_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkOptionMenu(row_host, values=hosts,
                          variable=self._cf_host_var,
                          command=self._on_cf_host_change, width=220, height=34,
                          corner_radius=8,
                          fg_color=BG_INPUT, button_color=BORDER_HOVER,
                          button_hover_color=ACCENT, text_color=TEXT_PRI,
                          dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
                          dropdown_text_color=TEXT_PRI).pack(side='left', padx=10)

        row_cookie = ctk.CTkFrame(cf, fg_color='transparent')
        row_cookie.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_cookie, text=T('cf_cookie_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkEntry(row_cookie, textvariable=self._cf_cookie_var,
                     height=34, corner_radius=8,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI).pack(side='left', fill='x',
                                               expand=True, padx=10)

        row_ua = ctk.CTkFrame(cf, fg_color='transparent')
        row_ua.pack(fill='x', padx=20, pady=(8, 2))
        ctk.CTkLabel(row_ua, text=T('cf_ua_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        ctk.CTkEntry(row_ua, textvariable=self._cf_ua_var,
                     height=34, corner_radius=8,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI).pack(side='left', fill='x',
                                               expand=True, padx=10)

        row_actions = ctk.CTkFrame(cf, fg_color='transparent')
        row_actions.pack(fill='x', padx=20, pady=(10, 2))
        ctk.CTkButton(row_actions, text=T('cf_save'), width=70, height=34, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=WHITE,
                      command=self._on_cf_save).pack(side='left', padx=(126, 6))
        ctk.CTkButton(row_actions, text=T('cf_clear'), width=70, height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._on_cf_clear).pack(side='left')
        ctk.CTkButton(row_actions, text=T('cfpass_auto'), height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=ACCENT,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._on_cf_auto).pack(side='left', padx=(6, 0))

        self._cf_status_lbl = ctk.CTkLabel(cf, text='', text_color=TEXT_SEC,
                                           font=(ui_font(), 10))
        self._cf_status_lbl.pack(anchor='w', padx=(146, 20), pady=(6, 4))

        ctk.CTkLabel(cf, text=T('cf_help'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 9),
                     wraplength=720,
                     justify='left').pack(anchor='w', padx=20, pady=(4, 18))

        self._on_cf_host_change(default_host)
        self._refresh_cf_status()

        # ── My own sites ────────────────────────────────────────────
        mine = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                            border_width=1, border_color=BORDER_CARD)
        mine.pack(fill='x', pady=(0, 16))

        mine_hdr = ctk.CTkFrame(mine, fg_color='transparent')
        mine_hdr.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(mine_hdr, text=T('mysites_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')
        ctk.CTkLabel(mine, text=T('mysites_desc'), text_color=TEXT_DIM,
                     font=(ui_font(), 10), wraplength=720,
                     justify='left').pack(anchor='w', padx=20, pady=(0, 12))

        ctk.CTkFrame(mine, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        # Picker: "+ add new" on top, then every site, in the user's order.
        row_pick = ctk.CTkFrame(mine, fg_color='transparent')
        row_pick.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(row_pick, text=T('mysites_pick_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        self._site_pick_var = ctk.StringVar(value=T('mysites_new'))
        self._site_pick = ctk.CTkOptionMenu(
            row_pick, values=[T('mysites_new')], variable=self._site_pick_var,
            command=self._on_site_pick, width=230, height=36,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER, dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 12), dropdown_font=(ui_font(), 12),
            dynamic_resizing=False)
        self._site_pick.pack(side='left', padx=10)

        def _tool(text, command, color=TEXT_PRI, width=42):
            return ctk.CTkButton(
                row_pick, text=text, width=width, height=36, corner_radius=8,
                fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER, text_color=color,
                font=(ui_font(), 12, 'bold'), command=command)

        self._site_up_btn = _tool('▲', lambda: self._move_site(-1))
        self._site_up_btn.pack(side='left', padx=(0, 4))
        self._site_down_btn = _tool('▼', lambda: self._move_site(1))
        self._site_down_btn.pack(side='left', padx=(0, 10))
        self._site_toggle_btn = _tool(T('mysites_hide'), self._toggle_site, width=96)
        self._site_toggle_btn.pack(side='left', padx=(0, 4))
        self._site_del_btn = _tool(T('mysites_remove'), self._remove_picked_site,
                                   ERROR_C, width=84)
        self._site_del_btn.pack(side='left')
        # A site that worked when it was added can break later, when the site
        # changes its layout.  This is where the user notices.
        self._site_report_btn = _tool(T('report_button'), self._report_picked_site,
                                      width=84)
        self._site_report_btn.pack(side='left', padx=(4, 0))

        # Shown for "+ add new": the address box.
        self._mysite_add_row = ctk.CTkFrame(mine, fg_color='transparent')
        self._mysite_add_row.pack(fill='x', padx=20, pady=(10, 2))
        ctk.CTkLabel(self._mysite_add_row, text=T('mysites_url_label'),
                     text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
                     width=116, anchor='w').pack(side='left')
        self._mysite_var = ctk.StringVar()
        mysite_entry = ctk.CTkEntry(
            self._mysite_add_row, textvariable=self._mysite_var, height=38,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT, border_color=BORDER,
            border_width=1, text_color=TEXT_PRI,
            placeholder_text=T('mysites_url_hint'))
        mysite_entry.pack(side='left', fill='x', expand=True, padx=10)
        self._mysite_entry = mysite_entry
        mysite_entry.bind('<Return>', lambda _e: self._test_custom_site())
        self._mysite_btn = ctk.CTkButton(
            self._mysite_add_row, text=T('mysites_test'), width=120, height=34,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color='#ffffff', command=self._test_custom_site)
        self._mysite_btn.pack(side='left')
        self._mysite_html_btn = ctk.CTkButton(
            self._mysite_add_row, text=T('mysites_teach'), width=150, height=34,
            corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, command=self._teach_from_html)
        self._mysite_html_btn.pack(side='left', padx=(6, 0))

        ctk.CTkLabel(mine, text=T('mysites_link_hint'), text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=(136, 20),
                                                pady=(4, 0))

        self._mysite_status = ctk.CTkLabel(mine, text='', text_color=TEXT_DIM,
                                           font=(ui_font(), 10), wraplength=720,
                                           justify='left')
        self._mysite_status.pack(anchor='w', padx=(136, 20), pady=(6, 4))

        # Shown only when a site was added but its search could not be found:
        # the one thing the app cannot work out alone is cheap for the user
        # to supply, and it is an address, not a file.
        self._mysite_search_row = ctk.CTkFrame(mine, fg_color='transparent')
        ctk.CTkLabel(self._mysite_search_row, text=T('mysites_search_label'),
                     text_color=TEXT_PRI, font=(ui_font(), 12, 'bold'),
                     width=116, anchor='w').pack(side='left')
        self._mysite_search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            self._mysite_search_row, textvariable=self._mysite_search_var,
            height=38, corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            border_color=BORDER, border_width=1, text_color=TEXT_PRI,
            placeholder_text=T('mysites_search_hint'))
        search_entry.pack(side='left', fill='x', expand=True, padx=10)
        search_entry.bind('<Return>', lambda _e: self._save_typed_search())
        ctk.CTkButton(
            self._mysite_search_row, text=T('mysites_search_save'), width=140,
            height=34, corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=self._save_typed_search).pack(side='left')
        self._mysite_search_host = ''

        # Shown only when the check found something wrong.  A site that was
        # read correctly needs no report, and a button offered every time
        # stops meaning anything.
        self._mysite_report_row = ctk.CTkFrame(mine, fg_color='transparent')
        self._mysite_report_note = ctk.CTkLabel(
            self._mysite_report_row, text='', text_color=WARNING,
            font=(ui_font(), 11), anchor='w', justify='left')
        self._mysite_report_note.pack(side='left', padx=(136, 10))
        ctk.CTkButton(
            self._mysite_report_row, text=T('report_button_long'), width=170,
            height=34, corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=self._report_added_site).pack(side='left')
        self._report_host, self._report_result, self._report_error = '', None, ''

        # Reporting gets the site fixed for everyone, in a few days.  Saving
        # the page and sending it fixes it now, for whoever is willing to do
        # it.  Both are offered, in that order, because most people want the
        # first and a few want the second.
        self._mysite_teach_row = ctk.CTkFrame(mine, fg_color='transparent')
        self._mysite_teach_note = ctk.CTkLabel(
            self._mysite_teach_row, text=T('mysites_teach_offer'),
            text_color=TEXT_DIM, font=(ui_font(), 11), anchor='w',
            justify='left', wraplength=430)
        self._mysite_teach_note.pack(side='left', padx=(136, 10))
        ctk.CTkButton(
            self._mysite_teach_row, text=T('mysites_teach'), width=230,
            height=34, corner_radius=8, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=self._teach_from_html).pack(side='left')

        self._refresh_site_picker()

        # Saved download queue
        queue = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
                             border_width=1, border_color=BORDER_CARD)
        queue.pack(fill='x', pady=(0, 16))

        queue_hdr = ctk.CTkFrame(queue, fg_color='transparent')
        queue_hdr.pack(fill='x', padx=20, pady=(16, 4))
        ctk.CTkLabel(queue_hdr, text=T('queue_card_title'),
                     font=(ui_font(), 15, 'bold'),
                     text_color=TEXT_PRI).pack(side='left')
        ctk.CTkLabel(queue, text=T('queue_card_desc'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(anchor='w', padx=20, pady=(0, 12))

        ctk.CTkFrame(queue, height=1, fg_color=BORDER).pack(fill='x', padx=20)

        row_queue_path = ctk.CTkFrame(queue, fg_color='transparent')
        row_queue_path.pack(fill='x', padx=20, pady=(16, 2))
        ctk.CTkLabel(row_queue_path, text=T('queue_path_label'), text_color=TEXT_PRI,
                     font=(ui_font(), 12, 'bold'), width=116,
                     anchor='w').pack(side='left')
        queue_path_entry = ctk.CTkEntry(
            row_queue_path, height=34, corner_radius=8,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            text_color=TEXT_PRI)
        queue_path_entry.pack(side='left', fill='x', expand=True, padx=10)
        queue_path_entry.insert(0, config.queue_csv_path())
        queue_path_entry.configure(state='readonly')

        row_queue_actions = ctk.CTkFrame(queue, fg_color='transparent')
        row_queue_actions.pack(fill='x', padx=20, pady=(10, 18))
        ctk.CTkButton(row_queue_actions, text=T('open_queue_folder'),
                      width=110, height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._open_queue_folder).pack(side='left', padx=(126, 6))
        ctk.CTkButton(row_queue_actions, text=T('clear_saved_queue'),
                      width=140, height=34, corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=ERROR_C,
                      command=self._clear_saved_queue).pack(side='left')

        # ── About, at the very bottom ───────────────────────────────
        self._build_update_card(content)

    def _on_cf_host_change(self, host):
        ov = config.get_cf_override(host) or {}
        self._cf_cookie_var.set(ov.get('cookie', ''))
        self._cf_ua_var.set(ov.get('ua', ''))

    def _refresh_proxy_status(self, saved=False):
        mode = config.get_proxy_mode()
        if mode == 'manual' and config.get_proxy_url():
            text, color = T('proxy_enabled'), SUCCESS
        elif mode == 'system':
            _display_url, status = config.refresh_system_proxy()
            if status == 'detected':
                text, color = T('proxy_windows_enabled'), SUCCESS
            elif status == 'pac':
                text, color = T('proxy_windows_pac'), WARNING
            elif status == 'invalid':
                text, color = T('proxy_windows_invalid'), ERROR_C
            else:
                text, color = T('proxy_windows_missing'), WARNING
        else:
            text, color = T('proxy_disabled'), TEXT_DIM
        if saved:
            text = f"{T('proxy_saved')} · {text}"
        self._proxy_status_lbl.configure(text=text, text_color=color)

    def _on_proxy_save(self):
        try:
            value = config.set_proxy_url(self._proxy_var.get())
        except (OSError, ValueError):
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._proxy_var.set(value)
        self._refresh_proxy_status(saved=True)

    def _on_proxy_windows(self):
        try:
            config.set_proxy_mode('system')
        except OSError:
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._refresh_proxy_status(saved=True)

    def _on_proxy_clear(self):
        try:
            config.set_proxy_url('')
        except OSError:
            self._proxy_status_lbl.configure(
                text=T('proxy_invalid'), text_color=ERROR_C)
            return
        self._proxy_var.set('')
        self._refresh_proxy_status()

    def _on_cf_save(self):
        host = self._cf_host_var.get()
        config.set_cf_override(host, self._cf_cookie_var.get(), self._cf_ua_var.get())
        self._refresh_cf_status()
        current = self._cf_status_lbl.cget('text')
        self._cf_status_lbl.configure(text=f"{T('cf_saved')} | {current}")

    def _blocked_kind(self):
        key = (self._site_key or '').lower()
        return last_mirror_failure.get(key, 'cloudflare')

    def _blocked_message(self):
        if self._blocked_kind() == 'unreachable':
            return T('site_unreachable', site=self._site_key)
        return T('mirrors_blocked')

    # ── one-click Cloudflare pass ───────────────────────────────────────
    def _cf_pass_host(self):
        browser = SITES.get(self._site_key, {}).get('browser')
        root = getattr(browser, 'ROOT', '')
        return urlsplit(root).hostname if root else ''

    def _start_cf_pass(self, host, reload=False):
        if getattr(self, '_cf_pass_running', False):
            return
        self._cf_pass_running = True
        from siphon.core import cfpass
        gen = self._build_gen
        try:
            self._status_lbl.configure(text=T('cfpass_waiting', host=host))
        except (AttributeError, tk.TclError):
            pass

        def work():
            try:
                cfpass.obtain(host)
                error = ''
            except Exception as exc:
                error = str(exc)
                print(f'[CF pass] {host}: {error}', flush=True)

            def done():
                self._cf_pass_running = False
                if error:
                    messagebox.showerror(T('cf_card_title'), T('cfpass_failed', error=error))
                    return
                try:
                    self._status_lbl.configure(text=T('cfpass_done', host=host))
                    self._refresh_cf_status()
                except (AttributeError, tk.TclError):
                    pass
                if reload:
                    self._load_categories()
            self._ui(done, gen=gen)
        threading.Thread(target=work, daemon=True).start()

    def _on_cf_auto(self):
        host = self._cf_host_var.get()
        if host:
            self._start_cf_pass(host)

    def _on_cf_clear(self):
        host = self._cf_host_var.get()
        config.clear_cf_override(host)
        self._cf_cookie_var.set('')
        self._cf_ua_var.set('')
        self._refresh_cf_status()

    def _refresh_cf_status(self):
        hosts = config.cf_override_hosts()
        if hosts:
            self._cf_status_lbl.configure(text=T('cf_status', hosts=', '.join(hosts)))
        else:
            self._cf_status_lbl.configure(text=T('cf_status_none'))

    def _on_speed_change(self, val):
        from siphon.sites.base import speed_limiter
        val = str(val)
        if val == T('speed_custom'):
            bps = speed_limit.ask_custom(
                T('speed_limit_setting'), T('speed_custom_prompt'),
                current_bps=int(self._speed_mbps * 1024 * 1024), master=self)
            if bps is None:          # cancelled or invalid: keep the old value
                self._speed_var.set(self._speed_label())
                return
        else:
            bps = speed_limit.parse_speed(
                '0' if val == T('unlimited') else val) or 0
        mbps = bps / (1024 * 1024)
        self._speed_mbps = mbps
        speed_limiter.set_limit(mbps)
        config.set_speed_limit_mbps(mbps)
        self._refresh_speed_menus()

    def _refresh_speed_menus(self):
        values = self._speed_values()
        for menu in getattr(self, '_speed_menus', []):
            try:
                menu.configure(values=values)
            except tk.TclError:
                pass
        self._speed_var.set(self._speed_label())

    def _on_res_change(self, val):
        from siphon.sites.base import set_resolution_pref
        pref = self._resolution_pref_from_label(val)
        set_resolution_pref(pref)
        config.set_resolution_pref(pref)

    def _on_filename_template_change(self, _event=None):
        value = config.set_filename_template(
            self._filename_template_var.get())
        self._filename_template_var.set(value)

    def _on_download_schedule_change(self, _event=None):
        try:
            value = config.set_download_schedule(
                self._download_schedule_var.get())
        except ValueError:
            value = config.get_download_schedule()
        self._download_schedule_var.set(value)

    def _on_minimum_free_change(self, _event=None):
        value = config.set_minimum_free_gb(
            self._minimum_free_var.get())
        self._minimum_free_var.set(str(value))

    def _on_auto_retry_change(self, _event=None):
        value = config.set_auto_retry_count(
            self._auto_retry_var.get())
        self._auto_retry_var.set(str(value))

    def _on_scroll_speed(self, raw):
        value = ui_scroll.set_speed(int(round(float(raw))))
        self._scroll_speed_lbl.configure(text=f'{value}x')

    def _on_notify_complete_change(self):
        config.set_notify_on_complete(
            self._notify_complete_var.get())

    def _on_conc_change(self, _event=None):
        try:
            requested = int(self._conc_var.get().strip())
        except (AttributeError, TypeError, ValueError):
            self._conc_var.set(str(self._dlmgr.max_concurrent))
            return
        value = config.set_download_concurrency(requested)
        self._dlmgr.max_concurrent = value
        self._conc_var.set(str(value))

    def _commit_workers_preference(self):
        current = config.get_max_workers_per_video()
        var = self.__dict__.get('_workers_var')
        if var is None:
            return current
        try:
            requested = int(var.get().strip())
        except (AttributeError, TypeError, ValueError):
            value = current
        else:
            value = config.set_max_workers_per_video(requested)
        var.set(str(value))
        return value

    def _on_workers_change(self, _event=None):
        self._commit_workers_preference()

    # ── per-site connections per video ──────────────────────────────────
    def _workers_site(self):
        site = self._workers_site_var.get()
        return site if site in config.worker_sites() else ''

    def _show_site_workers(self):
        site = self._workers_site()
        cap = config.site_worker_cap(site) if site else config.MAX_WORKERS_PER_VIDEO
        if site:
            value = config.get_max_workers_for_site(site)
            custom = site in config.get_site_workers_overrides()
        else:
            value = config.get_max_workers_per_video()
            custom = False
        self._workers_slider.configure(to=max(cap, 2), number_of_steps=max(cap - 1, 1))
        self._workers_slider.set(min(value, cap))
        self._workers_value_lbl.configure(text=str(min(value, cap)))
        note = T('workers_range', n=cap)
        if site and not custom:
            note += ' · ' + T('workers_inherits')
        self._workers_range_lbl.configure(text=note)
        if site and custom:
            if not self._workers_reset_btn.winfo_ismapped():
                self._workers_reset_btn.pack(side='left')
        else:
            self._workers_reset_btn.pack_forget()

    def _on_workers_slide(self, raw):
        value = int(round(float(raw)))
        site = self._workers_site()
        if site:
            config.set_site_workers(site, value)
        else:
            value = config.set_max_workers_per_video(value)
            self._workers_var.set(str(value))
        self._show_site_workers()

    def _reset_site_workers(self):
        site = self._workers_site()
        if site:
            config.set_site_workers(site, None)
        self._show_site_workers()

    def _commit_slow_requeue_preference(self):
        current = config.get_slow_requeue_kbps()
        var = self.__dict__.get('_slow_requeue_var')
        if var is None:
            return current
        try:
            requested = int(var.get().strip())
        except (AttributeError, TypeError, ValueError):
            value = current
        else:
            value = config.set_slow_requeue_kbps(requested)
        var.set(str(value))
        return value

    def _on_slow_requeue_change(self, _event=None):
        self._commit_slow_requeue_preference()

    def _pick_dest(self):
        d = filedialog.askdirectory()
        if d:
            self._dest_var.set(d)
            config.set_download_directory(d)

    def _open_dest_folder(self):
        import subprocess, platform
        dest = self._dest_var.get() or 'download'
        folder = os.path.abspath(dest)
        if not os.path.isdir(folder):
            messagebox.showerror(T('open_folder_failed_title'), folder)
            return
        system = platform.system()
        try:
            if system == 'Windows':
                os.startfile(folder)
            elif system == 'Darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except OSError as e:
            messagebox.showerror(T('open_folder_failed_title'), str(e))

    def _open_queue_folder(self):
        import subprocess, platform
        folder = os.path.dirname(config.queue_csv_path())
        system = platform.system()
        try:
            os.makedirs(folder, exist_ok=True)
            if system == 'Windows':
                os.startfile(folder)
            elif system == 'Darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except OSError as e:
            messagebox.showerror(T('open_folder_failed_title'), str(e))
