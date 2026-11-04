#!/usr/bin/env python
# coding: utf-8
"""Siphon: the desktop app — Browse, Download, Upload and Settings."""

import os
import sys
import re
import json
import time
import threading
import queue
import concurrent.futures
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import requests
from PIL import Image

from siphon.core import config
from siphon import sites as M3U8Sites
from siphon.core import dl_history
from siphon.core.ssl import get_shared_ssl_context
from siphon.core import secretstore
from siphon.core.config import headers
from siphon.i18n.locales import T, set_lang, get_lang, ui_font, LANGUAGES
from siphon.ui import scroll as ui_scroll

ui_scroll.install()
from siphon.apps.upload_tab import UploadTab
from siphon.upload.manager import UploadManager
from siphon.ui.theme import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_HOVER,
    BG_DARK,
    BG_CARD,
    BG_CARD_HOVER,
    BG_INPUT,
    BG_HEADER,
    BG_SIDEBAR,
    BG_BADGE,
    TEXT_PRI,
    TEXT_SEC,
    TEXT_DIM,
    BORDER,
    BORDER_HOVER,
    CONTROL_RADIUS,
    WHITE,
    browse_columns_for_width)
from siphon.metadata import APP_DISPLAY_NAMES
from siphon.apps.downloads import DONE_STATES, next_schedule_epoch

# The code that used to live in this file now lives in the modules below;
# the names are imported back so existing imports keep working.
from siphon.apps.app_basics import (
    APP_VERSION,
    BUILTIN_SITES,
    BUILTIN_SITE_ENTRIES,
    CSV_PATH,
    DEFAULT_CONCURRENT,
    DEFAULT_SITE_KEY,
    ERR_BLOCKED,
    HARD_LOAD_LIMIT,
    MAX_CONCURRENT,
    MAX_PERSIST_ROWS,
    MAX_VISIBLE_ROWS,
    RESUME_PATH,
    ROW_BUILD_BUDGET,
    SETTINGS_INLINE_HELP_WRAP,
    SITES,
    SITES_LOADING_HINT,
    SLOW_REQUEUE_GRACE_SECONDS,
    SLOW_REQUEUE_MAX_ATTEMPTS,
    _KEEP_PROGRESS_STATES,
    _QUEUED_STATES,
    _RUNNING_STATES,
    _STATE_PRIORITY,
    _VIDEO_EXTS,
    _crumb,
    _download_row_action,
    _download_size_text,
    _fallback_name,
    _fmt_duration,
    _fmt_size,
    _kvs_browser_for_url,
    _learned_report,
    _section_label,
    _select_persist,
    _visible_window,
    builtin_browser_for_host,
    fetch_page_data,
    register_user_sites,
    site_catalog)

from siphon.apps.file_actions import (
    _find_item_file,
    _hand_to_the_system,
    _open_folder,
    _reveal_in_explorer)

from siphon.apps.thumbnails import (
    _ADAPTER_TITLE_LIMIT,
    _THUMB_SIZE,
    _TITLE_ATTEMPTS,
    _clear_thumb,
    _fetch_thumbnail,
    _get_thumb_session,
    _thumb_cache,
    _thumb_cache_lock,
    _thumb_lock,
    _thumb_session,
    _thumbnail_request_context)

from siphon.apps.download_manager import (
    DownloadItem,
    DownloadManager,
    _DownloadTask)

from siphon.apps.app_settings import SettingsMixin

from siphon.apps.app_sites import SitesMixin

from siphon.apps.app_browse import BrowseTabMixin

from siphon.apps.app_downloads import DownloadsTabMixin

# What other code (and the tests) reach through this module.
__all__ = [
    'APP_VERSION',
    'BUILTIN_SITES',
    'BUILTIN_SITE_ENTRIES',
    'CSV_PATH',
    'DEFAULT_CONCURRENT',
    'DEFAULT_SITE_KEY',
    'DownloadItem',
    'DownloadManager',
    'ERR_BLOCKED',
    'HARD_LOAD_LIMIT',
    'Image',
    'M3U8Sites',
    'MAX_CONCURRENT',
    'MAX_PERSIST_ROWS',
    'MAX_VISIBLE_ROWS',
    'RESUME_PATH',
    'ROW_BUILD_BUDGET',
    'SETTINGS_INLINE_HELP_WRAP',
    'SITES',
    'SITES_LOADING_HINT',
    'SLOW_REQUEUE_GRACE_SECONDS',
    'SLOW_REQUEUE_MAX_ATTEMPTS',
    'T',
    '_ADAPTER_TITLE_LIMIT',
    '_DownloadTask',
    '_KEEP_PROGRESS_STATES',
    '_QUEUED_STATES',
    '_RUNNING_STATES',
    '_STATE_PRIORITY',
    '_THUMB_SIZE',
    '_TITLE_ATTEMPTS',
    '_VIDEO_EXTS',
    '_clear_thumb',
    '_crumb',
    '_download_row_action',
    '_download_size_text',
    '_fallback_name',
    '_fetch_thumbnail',
    '_find_item_file',
    '_fmt_duration',
    '_fmt_size',
    '_get_thumb_session',
    '_hand_to_the_system',
    '_kvs_browser_for_url',
    '_learned_report',
    '_open_folder',
    '_reveal_in_explorer',
    '_section_label',
    '_select_persist',
    '_thumb_cache',
    '_thumb_cache_lock',
    '_thumb_lock',
    '_thumb_session',
    '_thumbnail_request_context',
    '_visible_window',
    'builtin_browser_for_host',
    'config',
    'fetch_page_data',
    'headers',
    'register_user_sites',
    'requests',
    'site_catalog',
    'threading',
    'time',
    'tk']

































































# ── Main App ─────────────────────────────────────────────────────────
class ModernApp(SettingsMixin, SitesMixin, BrowseTabMixin, DownloadsTabMixin, ctk.CTk):
    def __init__(self, url: str = '', dest: str = 'download', lang: str = 'en'):
        super().__init__()
        self._is_closing = False
        self._startup_complete = False
        self._close_requested = False
        self._ui_callbacks = queue.SimpleQueue()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

        get_shared_ssl_context()

        config.load_cf_overrides()
        self._lang_code_by_name = {name: code for code, name in LANGUAGES}
        self._lang_name_by_code = {code: name for code, name in LANGUAGES}
        self._theme_mode = config.get_theme()
        ctk.set_appearance_mode(self._theme_mode)
        ctk.set_default_color_theme('blue')

        stored = config.get_ui_lang()
        if stored and stored not in self._lang_name_by_code:
            stored = 'en'          # a language that is no longer offered
        set_lang(stored or 'en')
        self._needs_lang_prompt = (stored is None)

        self.title(APP_DISPLAY_NAMES['browse'])
        self.geometry('1280x820')
        self.minsize(980, 680)
        self.configure(fg_color=BG_DARK)

        self._dest = (
            config.get_download_directory()
            if dest == 'download' and config.get_download_directory()
            else dest)
        self._url_input = url
        self._rebuilding = False

        # Rows whose page was already read for a title (once each).
        self._titles_tried: dict[str, int] = {}   # url -> sweeps spent on it
        self._title_worker_busy = False

        # Browse state
        register_user_sites()
        self._site_key = (list(SITES) or [DEFAULT_SITE_KEY])[0]
        self._categories: list[dict] = []
        self._current_base_url = ''
        self._page = 1
        self._has_next = True
        self._videos: list[dict] = []
        self._selected_urls: set = set()
        # Keep the complete card metadata in insertion order.  A set alone
        # loses both the displayed title and the order in which pages were
        # selected, which made the queue look unrelated to the grid.
        self._selected_videos: dict[str, dict] = {}
        self._select_all_running = False
        self._sidebar_expanded: dict[str, bool] = {}
        self._grid_gen: int = 0  # bumps on each page refresh so stale thumbs are dropped
        self._grid_columns = browse_columns_for_width(1280)
        self._resize_after_id = None
        self._page_req: int = 0
        self._build_gen: int = 0
        self._active_tab_idx: int = 0
        self._last_loaded_page: int = 1
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._card_widgets: dict = {}  # url -> {card, sel_btn}
        self._dl_rows: dict = {}   # url -> {row, state_lbl, name_lbl, pb, pct, spd, remove}
        self._dl_filter = 'all'
        self._dl_sort = config.get_download_sort()
        self._batch_was_busy = False
        self._batch_notified = True
        self._dl_empty_lbl = None
        self._dl_pool = []
        self._dl_first = 0
        self._dl_view_items = []
        self._dl_gen = 0
        self._thumb_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
        self._speed_mbps = config.get_speed_limit_mbps()
        self._download_autosave_ticks = 0
        self._last_download_save_sig = None
        self._update_info = None
        self._update_checking = False
        self._update_installing = False
        self._update_prompt_shown = False
        self._update_status_text = ''
        self._update_status_color = TEXT_DIM
        self._update_badge = None
        self._update_status_lbl = None
        self._update_note_lbl = None
        self._update_check_btn = None
        self._update_now_btn = None

        try:
            from siphon.core import crashlog
            crashlog.start_freeze_watchdog(self)
        except Exception:
            pass

        # Download manager
        self._upmgr = UploadManager()
        try:
            self._upmgr.restore(os.path.join(
                os.path.dirname(config.queue_csv_path()), 'upload_queue.json'))
        except Exception as exc:
            print(f'[Upload] could not restore the upload list: {exc}', flush=True)
        self._dlmgr = DownloadManager(
            max_concurrent=config.get_download_concurrency(),
            on_finished=self._upmgr.add_downloaded_video)
        self._dlmgr.load_csv(CSV_PATH)

        from siphon.sites.base import set_resolution_pref
        set_resolution_pref(config.get_resolution_pref())
        from siphon.sites.base import speed_limiter
        speed_limiter.set_limit(self._speed_mbps)

        self._build_ui()
        self.bind('<Configure>', self._on_root_resize, add='+')
        # Windows sometimes leaves parts of the window black after it was in
        # the background (alt-tab); repaint everything when it comes back.
        self.bind('<FocusIn>', self._on_window_focus, add='+')
        self.bind('<Map>', self._on_window_focus, add='+')
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self._startup_complete = True
        if self._close_requested:
            self._on_close()
            return
        self.after(30, self._drain_ui_callbacks)
        # Start periodic refresh for downloads
        self._refresh_downloads()
        # Continue what was running / queued when the app was last closed.
        self._setup_download_history()
        self.after(800, self._restore_resume_list)
        # Start clipboard monitor (main-thread safe)
        self._clp_text = ''
        self._clipboard_poll()

        # Tk rejects worker-thread ``after`` calls before mainloop starts.  Defer
        # every worker that can complete quickly until the event loop is active.
        self.after_idle(self._start_initial_background_tasks)
        if self._needs_lang_prompt:
            self.after(250, self._first_run_language_prompt)
        self.after(1500 if self._needs_lang_prompt else 700,
                   self._browser_first_run_notice)

    def _browser_first_run_notice(self):
        """Say, once, that Siphon will drive a real browser on this computer.

        It happens out of sight, so it should not be a surprise discovered in
        Task Manager.
        """
        if self._is_closing or config.browser_notice_seen():
            return
        config.set_browser_notice_seen()
        try:
            messagebox.showinfo(T('browser_notice_title'), T('browser_notice_body'))
        except tk.TclError:
            pass

    def _start_initial_background_tasks(self):
        if self._is_closing:
            return
        self._load_categories()
        self._repair_hidden_downloads()

    def _repair_hidden_downloads(self):
        """Bring back videos an earlier build left hidden, once.

        That build hid the .part file and Windows carried the mark onto the
        finished video, so a download that had worked could not be seen.  The
        fix stops it happening again; this undoes what already happened, in
        the background and without asking, because there is nothing for the
        user to decide and no way for them to find those files themselves.
        """
        if config.hidden_downloads_repaired():
            return

        def work():
            try:
                from siphon.core.storage import unhide_finished_downloads
                fixed = unhide_finished_downloads(config.get_download_directory())
            except Exception as exc:
                print(f'[files] could not un-hide old downloads: {exc}', flush=True)
                return
            config.set_hidden_downloads_repaired()
            if fixed:
                print(f'[files] {fixed} finished download(s) were hidden and '
                      'are visible again', flush=True)

        threading.Thread(target=work, daemon=True).start()

    def _ask_language_first_run(self):
        popup = None
        try:
            idx = 0 if ctk.get_appearance_mode() == 'Light' else 1
            def C(tok):                      # resolve a (light,dark) token to a single hex string
                return tok[idx] if isinstance(tok, (tuple, list)) else tok
            bg, card, fg, border, accent, cardh = (
                C(BG_DARK), C(BG_CARD), C(TEXT_PRI), C(BORDER_HOVER), C(ACCENT), C(BG_CARD_HOVER))

            popup = tk.Toplevel(self)
            popup.title(T('lang_picker_title'))
            popup.configure(bg=bg)
            popup.resizable(False, False)
            popup.transient(self)

            picker_font = 'Microsoft JhengHei'   # renders all 4 native scripts
            tk.Label(popup, text=T('lang_picker_title'), bg=bg, fg=fg,
                     font=(picker_font, 15, 'bold')).pack(padx=32, pady=(24, 14))

            def _choose(code='en'):
                config.set_ui_lang(code)
                if code != get_lang():
                    self._apply_language(code)
                try:
                    popup.destroy()
                except tk.TclError:
                    pass

            for code, name in LANGUAGES:
                tk.Button(popup, text=name, width=22,
                          bg=card, fg=fg, activebackground=accent, activeforeground='#ffffff',
                          relief='flat', bd=1, highlightbackground=border, highlightthickness=1,
                          padx=12, pady=9, font=(picker_font, 12), cursor='hand2',
                          command=lambda c=code: _choose(c)).pack(padx=32, pady=5)

            popup.protocol('WM_DELETE_WINDOW', lambda: _choose(get_lang() or 'en'))
            popup.update_idletasks()
            w = max(popup.winfo_reqwidth(), 320)
            h = max(popup.winfo_reqheight(), 280)
            x = max((self.winfo_screenwidth() - w) // 2, 0)
            y = max((self.winfo_screenheight() - h) // 3, 0)
            popup.geometry(f'{w}x{h}+{x}+{y}')
            # Force the picker visible (plain tk.Toplevel shows reliably in frozen builds)
            popup.deiconify()
            popup.lift()
            try:
                popup.attributes('-topmost', True)
                popup.after(300, lambda: popup.winfo_exists() and popup.attributes('-topmost', False))
            except tk.TclError:
                pass
            popup.update_idletasks()
            popup.focus_force()
        except Exception:
            if popup is not None:
                try:
                    popup.destroy()
                except tk.TclError:
                    pass
            try:
                config.set_ui_lang('en')
            except Exception:
                pass

    def _first_run_language_prompt(self):
        if self._is_closing:
            return
        try:
            self.deiconify()
            self.update_idletasks()
        except tk.TclError:
            pass
        self._ask_language_first_run()

    def _ui(self, fn, gen: int | None = None):
        if self._is_closing:
            return
        if gen is not None and gen != self._build_gen:
            return

        # No Tk calls from worker threads, even before mainloop or while
        # CustomTkinter processes a close event during its startup update.
        self._ui_callbacks.put((gen, fn))

    def _drain_ui_callbacks(self):
        for _ in range(64):
            if self._is_closing:
                return
            try:
                gen, fn = self._ui_callbacks.get_nowait()
            except queue.Empty:
                break
            if gen is not None and gen != self._build_gen:
                continue
            try:
                fn()
            except tk.TclError:
                pass
        try:
            if not self._is_closing:
                self.after(30, self._drain_ui_callbacks)
        except tk.TclError:
            pass











    def _on_root_resize(self, event):
        if event.widget is not self or self._is_closing:
            return
        try:
            logical_width = event.width / max(self._get_window_scaling(), 1.0)
        except Exception:
            logical_width = event.width
        columns = browse_columns_for_width(logical_width)
        if columns == self._grid_columns:
            return
        self._grid_columns = columns
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        try:
            self._resize_after_id = self.after(180, self._apply_responsive_grid)
        except tk.TclError:
            self._resize_after_id = None

    def _apply_responsive_grid(self):
        self._resize_after_id = None
        if (self._is_closing or not self._videos or
                getattr(self, '_grid_scroll', None) is None):
            return
        self._refresh_grid()

    def _current_tab_index(self):
        return self._active_tab_idx

    def _set_tab_index(self, idx: int):
        idx = max(0, min(int(idx), len(self._tab_keys) - 1))
        self._select_tab(self._tab_keys[idx])

    def _select_tab(self, key):
        if key not in getattr(self, '_tab_frames', {}):
            return
        for f in self._tab_frames.values():
            f.pack_forget()
        self._tab_frames[key].pack(fill='both', expand=True)
        for k, w in self._tab_buttons.items():
            active = (k == key)
            try:
                w['holder'].configure(
                    fg_color=(ACCENT_DIM if active else 'transparent'),
                    border_width=(1 if active else 0),
                    border_color=(ACCENT if active else BORDER))
                w['lbl'].configure(
                    text_color=(ACCENT if active else TEXT_SEC),
                    font=(ui_font(), 13, 'bold') if active else (ui_font(), 13))
                w['underline'].configure(fg_color=(ACCENT if active else 'transparent'))
            except tk.TclError:
                pass
        self._active_tab_idx = self._tab_keys.index(key)








    def _apply_language(self, code):
        self._rebuilding = True
        from siphon.sites.base import get_resolution_pref, set_resolution_pref

        try:
            snapshot = {
                'tab_idx': self._current_tab_index(),
                'dest': self._var_get('_dest_var', self._dest),
                'dl_url': self._var_get('_dl_url_var', self._url_input),
                'cf_host': self._var_get('_cf_host_var'),
                'cf_cookie': self._var_get('_cf_cookie_var'),
                'cf_ua': self._var_get('_cf_ua_var'),
                'page_jump': self._var_get('_page_jump_var'),
                'concurrency': self._dlmgr.max_concurrent,
                'max_workers_per_video': self._commit_workers_preference(),
                'slow_requeue_kbps': self._commit_slow_requeue_preference(),
                'speed_mbps': self._speed_mbps,
                'resolution_pref': get_resolution_pref(),
                'site_key': self._site_key,
            }

            set_lang(code)
            config.set_ui_lang(code)
            self._build_gen += 1
            self._page_req += 1
            self._grid_gen += 1

            for child in self.winfo_children():
                try:
                    child.destroy()
                except tk.TclError:
                    pass

            self._card_widgets = {}
            self._dl_rows = {}
            self._dl_pool = []
            self._dl_first = 0
            self._dl_view_items = []
            self._dl_gen += 1
            self._categories = []
            self._selected_urls.clear()
            self._selected_videos.clear()
            self._videos = []
            self._browse_blocked = False
            self._browse_empty_message = ''
            self._cf_status_lbl = None
            self._site_menu = None
            self._cat_menu = None
            self._grid_scroll = None
            self._dl_scroll = None
            self._sidebar = None
            self._status_lbl = None

            self._dest = snapshot['dest']
            self._url_input = snapshot['dl_url']
            self._site_key = snapshot['site_key']
            self._speed_mbps = snapshot['speed_mbps']
            set_resolution_pref(snapshot['resolution_pref'])

            self._build_ui()

            self._site_key = snapshot['site_key']
            self._site_var.set(snapshot['site_key'])
            self._dest_var.set(snapshot['dest'])
            self._dl_url_var.set(snapshot['dl_url'])
            self._page_jump_var.set(snapshot['page_jump'])
            self._conc_var.set(str(snapshot['concurrency']))
            self._workers_var.set(str(snapshot['max_workers_per_video']))
            self._slow_requeue_var.set(str(snapshot['slow_requeue_kbps']))
            self._speed_var.set(self._speed_label())
            self._res_var.set(self._resolution_label())
            if snapshot['cf_host']:
                self._cf_host_var.set(snapshot['cf_host'])
            self._cf_cookie_var.set(snapshot['cf_cookie'])
            self._cf_ua_var.set(snapshot['cf_ua'])
            self._refresh_cf_status()
            self._set_tab_index(snapshot['tab_idx'])
            self._update_selection_count()
            self._rebuild_sidebar()
            self._load_categories()
        finally:
            self._rebuilding = False
        self._refresh_downloads(schedule=False)

    def _build_ui(self):
        # ── Root split: Left Vertical Navigation Rail + Right Workspace ──
        shell = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        shell.pack(fill='both', expand=True)

        rail = ctk.CTkFrame(shell, width=224, fg_color=BG_HEADER, corner_radius=0)
        rail.pack(side='left', fill='y')
        rail.pack_propagate(False)

        # Subtle vertical divider between rail and workspace
        ctk.CTkFrame(shell, width=1, fg_color=BORDER, corner_radius=0).pack(
            side='left', fill='y')

        # ── Brand card at top of rail ────────────────────────────────
        brand = ctk.CTkFrame(rail, fg_color='transparent')
        brand.pack(fill='x', padx=18, pady=(22, 16))

        brand_row = ctk.CTkFrame(brand, fg_color='transparent')
        brand_row.pack(fill='x')
        logo_badge = ctk.CTkFrame(
            brand_row, width=36, height=36, corner_radius=10, fg_color=ACCENT)
        logo_badge.pack(side='left', padx=(0, 12))
        logo_badge.pack_propagate(False)
        ctk.CTkLabel(
            logo_badge, text='◈', font=(ui_font(), 17, 'bold'),
            text_color=WHITE).place(relx=0.5, rely=0.5, anchor='center')

        brand_titles = ctk.CTkFrame(brand_row, fg_color='transparent')
        brand_titles.pack(side='left', fill='x', expand=True)
        ctk.CTkLabel(brand_titles, text=APP_DISPLAY_NAMES['browse'],
                     font=(ui_font(), 18, 'bold'),
                     text_color=TEXT_PRI).pack(anchor='w')
        ctk.CTkLabel(brand_titles, text='DOWNLOAD  /  UPLOAD',
                     font=('Consolas', 8, 'bold'),
                     text_color=ACCENT).pack(anchor='w')

        ctk.CTkFrame(rail, height=1, fg_color=BORDER, corner_radius=0).pack(
            fill='x', padx=16, pady=(0, 14))

        # ── Vertical Pill Navigation ─────────────────────────────────
        self._tab_keys = ['browse', 'download', 'upload', 'settings']
        tab_icons = {
            'browse': '🌐',
            'download': '⬇',
            'upload': '☁',
            'settings': '⚙',
        }
        tab_labels = {
            'browse': f"{tab_icons['browse']}   {T('tab_browse')}",
            'download': f"{tab_icons['download']}   {T('tab_download')}",
            'upload': f"{tab_icons['upload']}   {T('tab_upload')}",
            'settings': f"{tab_icons['settings']}   {T('tab_settings')}",
        }

        nav_stack = ctk.CTkFrame(rail, fg_color='transparent')
        nav_stack.pack(fill='x', padx=12)

        self._tab_buttons = {}
        for key in self._tab_keys:
            holder = ctk.CTkFrame(
                nav_stack, height=44, fg_color='transparent',
                corner_radius=CONTROL_RADIUS)
            holder.pack(fill='x', pady=3)
            holder.pack_propagate(False)

            underline = ctk.CTkFrame(
                holder, width=4, height=22, fg_color='transparent',
                corner_radius=2)
            underline.pack(side='left', padx=(6, 0), pady=11)

            lbl = ctk.CTkLabel(
                holder, text=tab_labels[key], anchor='w',
                font=(ui_font(), 13), text_color=TEXT_SEC, cursor='hand2')
            lbl.pack(side='left', fill='both', expand=True, padx=12)

            holder.bind('<Button-1>', lambda e, k=key: self._select_tab(k))
            lbl.bind('<Button-1>', lambda e, k=key: self._select_tab(k))
            self._tab_buttons[key] = {
                'holder': holder,
                'lbl': lbl,
                'underline': underline,
            }

        # ── Bottom controls inside rail (status, language, theme, version) ──
        rail_footer = ctk.CTkFrame(rail, fg_color='transparent')
        rail_footer.pack(side='bottom', fill='x', padx=14, pady=14)

        # Status & Log card
        status_card = ctk.CTkFrame(
            rail_footer, fg_color=BG_CARD, corner_radius=CONTROL_RADIUS,
            border_width=1, border_color=BORDER)
        status_card.pack(fill='x', pady=(0, 10))
        self._status_lbl = ctk.CTkLabel(
            status_card, text=T('status_ready'),
            font=('Consolas', 10), text_color=TEXT_SEC,
            anchor='w', justify='left', wraplength=176)
        self._status_lbl.pack(fill='x', padx=10, pady=(8, 4))
        ctk.CTkButton(
            status_card, text=T('open_log'), height=26,
            corner_radius=8, fg_color=BG_INPUT,
            border_width=1, border_color=BORDER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 10, 'bold'),
            command=self._open_log_file).pack(fill='x', padx=8, pady=(0, 8))

        # Language + Theme row
        controls_row = ctk.CTkFrame(rail_footer, fg_color='transparent')
        controls_row.pack(fill='x', pady=(0, 8))
        self._lang_var = ctk.StringVar(
            value=self._lang_name_by_code.get(get_lang(), 'English'))
        self._lang_menu = ctk.CTkOptionMenu(
            controls_row, values=[name for _, name in LANGUAGES],
            variable=self._lang_var, command=self._on_lang_change,
            height=34, corner_radius=CONTROL_RADIUS,
            fg_color=BG_CARD, button_color=BORDER_HOVER,
            button_hover_color=ACCENT, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 11), dropdown_font=(ui_font(), 11))
        self._lang_menu.pack(side='left', fill='x', expand=True, padx=(0, 6))

        self._theme_btn = ctk.CTkButton(
            controls_row, text=self._theme_glyph(), width=36, height=34,
            corner_radius=CONTROL_RADIUS, fg_color=BG_CARD, border_width=1,
            border_color=BORDER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 14),
            command=self._cycle_theme)
        self._theme_btn.pack(side='right')

        # Version badge
        version_box = ctk.CTkFrame(
            rail_footer, fg_color=BG_BADGE, corner_radius=8,
            border_width=1, border_color=BORDER)
        version_box.pack(fill='x')
        ctk.CTkLabel(version_box, text=f'Siphon v{APP_VERSION}',
                     font=('Consolas', 10, 'bold'),
                     text_color=TEXT_SEC).pack(side='left', padx=10, pady=5)
        self._update_badge = ctk.CTkLabel(
            version_box, text=T('update_new_badge'),
            font=(ui_font(), 10, 'bold'), text_color=ACCENT)
        try:
            self._update_badge.configure(cursor='hand2')
        except Exception:
            pass
        self._update_badge.bind('<Button-1>', self._show_update_settings)

        # ── Right Workspace Container ────────────────────────────────
        self._tab_container = ctk.CTkFrame(shell, fg_color=BG_DARK, corner_radius=0)
        self._tab_container.pack(side='left', fill='both', expand=True)
        self._tab_frames = {}
        for key in self._tab_keys:
            self._tab_frames[key] = ctk.CTkFrame(
                self._tab_container, fg_color=BG_DARK, corner_radius=0)

        self._build_browse_tab()
        self._build_download_tab()
        self._upload_tab = UploadTab(self, self._tab_frames['upload'], self._upmgr)
        self._build_settings_tab()

        self._select_tab(self._tab_keys[self._active_tab_idx])

    # ── continue downloads after a restart ───────────────────────────────
    def _save_resume_list(self):
        mgr = self._dlmgr
        with mgr._lock:
            running = [url for url in mgr._active
                       if mgr._items.get(url) is not None
                       and mgr._items[url].state in _RUNNING_STATES]
            queued = [task.url for task in mgr._pending]
            # Items waiting in the list without a task (e.g. scheduled ones).
            queued += [url for url, item in mgr._items.items()
                       if item.state in _QUEUED_STATES and not item.local]
        order = list(dict.fromkeys(running + queued))
        secretstore.write_text(RESUME_PATH, json.dumps(
            {'urls': order, 'running': len(set(running))}))
        print(f'[resume] {len(set(running))} running + '
              f'{len(order) - len(set(running))} queued download(s) will '
              'continue on next start', flush=True)

    def _setup_download_history(self):
        """Permanent history of finished downloads; seeded once from the list."""
        try:
            self._dlmgr.history = dl_history.DownloadHistory(os.path.join(
                os.path.dirname(CSV_PATH), 'download_history.json'))
            self._seed_history_sizes()
            seeded = self._dlmgr.history.add_many(
                (i.url, i.name, getattr(i, 'completed_at', 0) or i.updated_at)
                for i in self._dlmgr.get_items()
                if i.state == '已下載' and not i.local)
            if seeded:
                print(f'[history] {seeded} finished download(s) added to the history',
                      flush=True)
        except Exception as exc:
            print(f'[history] unavailable: {exc}', flush=True)
            self._dlmgr.history = None
        self._already_pending = []
        self._dlmgr.on_already_downloaded = (
            lambda url, entry: self._ui(lambda: self._note_already(url, entry)))

    def _seed_history_sizes(self):
        """Give history entries without a size the size shown in the list
        ('300.0 MB / 300.0 MB' → 300 MB), so download-time estimates work
        before any new download finishes."""
        history = self._dlmgr.history
        units = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}
        changed = False
        for item in self._dlmgr.get_items():
            if item.state != '已下載' or not item.size_text:
                continue
            found = re.findall(r'([\d.]+)\s*(TB|GB|MB|KB|B)\b', item.size_text)
            if not found:
                continue
            number, unit = found[-1]
            try:
                size = int(float(number) * units[unit])
            except (ValueError, KeyError):
                continue
            entry = history.match_url(item.url)
            if entry is None:
                history.add(item.url, item.name, '', getattr(item, 'completed_at', 0)
                            or item.updated_at, save=False, size=size)
                changed = True
            elif not entry.get('size'):
                entry['size'] = size
                changed = True
        if changed:
            with history._lock:
                history._save()

    def _note_already(self, url, entry):
        """Collect 'already downloaded' hits for a moment, then show one message."""
        first = not self._already_pending
        self._already_pending.append(entry or {'url': url})
        if first:
            self.after(600, self._show_already)

    def _show_already(self):
        entries, self._already_pending = self._already_pending, []
        if not entries or self._is_closing:
            return
        names = [f'• {e.get("name") or e.get("url")}' for e in entries[:12]]
        if len(entries) > 12:
            names.append(f'… +{len(entries) - 12}')
        text = T('already_downloaded_msg', n=len(entries)) + '\n\n' + '\n'.join(names)
        try:
            self._status_lbl.configure(text=T('already_downloaded_status', n=len(entries)))
        except (AttributeError, tk.TclError):
            pass
        self._refresh_downloads(schedule=False)
        messagebox.showinfo(T('already_downloaded_title'), text, parent=self)

    def _restore_resume_list(self):
        try:
            text = secretstore.read_text(RESUME_PATH)
            urls = list(json.loads(text).get('urls') or []) if text.strip() else []
        except (OSError, ValueError, Exception):
            return
        try:
            os.remove(RESUME_PATH)
        except OSError:
            pass
        started = 0
        for url in urls:
            item = self._dlmgr._items.get(url)
            if item is None or item.state in DONE_STATES or item.state == '已暫停':
                continue
            if self._dlmgr.enqueue(url, item.dest or self._dest):
                started += 1
        if started:
            print(f'[resume] continued {started} download(s) from last session', flush=True)
            try:
                self._status_lbl.configure(text=T('resume_restored', n=started))
            except (AttributeError, tk.TclError):
                pass
            self._refresh_downloads(schedule=False)

    def _on_window_focus(self, event=None):
        if event is not None and event.widget is not self:
            return
        now = time.monotonic()
        if now - getattr(self, '_last_repaint', 0.0) < 1.5:
            return
        self._last_repaint = now
        self.after(60, self._force_repaint)

    def _force_repaint(self):
        if self._is_closing:
            return
        try:
            self.update_idletasks()
            if sys.platform.startswith('win'):
                # Re-composite the whole window (cheap, no visible flicker).
                self.attributes('-alpha', 0.995)
                self.after(40, lambda: self.attributes('-alpha', 1.0))
        except tk.TclError:
            pass







































    def _add_selected_to_queue(
            self, resolution: str = '', filename_template: str = ''):
        # "Add to Queue" puts the videos in the real download queue (in
        # order, with a ▲ n ▼ position); they start as slots free up.
        due = next_schedule_epoch(config.get_download_schedule())
        summary = ModernApp._queue_selected(
            self, start_download=True, resolution=resolution,
            filename_template=filename_template, not_before=due)
        ModernApp._show_queue_summary(self, summary, started=True)
        return summary

    def _download_selected(
            self, resolution: str = '', filename_template: str = '',
            not_before: float = 0):
        summary = ModernApp._queue_selected(
            self, start_download=True, resolution=resolution,
            filename_template=filename_template, not_before=not_before)
        ModernApp._show_queue_summary(self, summary, started=True)
        return summary






























































    # ---- reporting a site that is not read correctly ----------------------








































    # ── Close ────────────────────────────────────────────────────────
    def _on_close(self):
        self._is_closing = True
        try:
            from siphon.core import browser as real_browser
            threading.Thread(target=real_browser.shutdown, daemon=True).start()
        except Exception:
            pass
        try:
            self._upmgr.close()
        except Exception:
            pass
        if not getattr(self, '_startup_complete', True):
            self._close_requested = True
            return
        try:
            self._thumb_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self._save_resume_list()
        except Exception as exc:
            print(f'[resume] could not save the running queue: {exc}', flush=True)
        try:
            with self._dlmgr._lock:
                for item in self._dlmgr._items.values():
                    if item.state in (
                            '準備中', '下載中', '等待中', '等待重試',
                            '已排程'):
                        item.state = '未完成'
                        item.speed = ''
                self._dlmgr.save_csv(CSV_PATH)
        except Exception:
            pass
        self._dlmgr.cancel_all(cleanup=False)
        self.destroy()


def gui_modern_main(url: str = '', dest: str = 'download', lang: str = 'en'):
    _crumb("gui_modern_main: constructing ModernApp")
    app = ModernApp(url=url, dest=dest, lang=lang)
    _crumb("gui_modern_main: app constructed, entering mainloop")
    try:
        if not app._is_closing:
            app.mainloop()
    except tk.TclError:
        # CTk.mainloop calls update() while styling the Windows titlebar.
        # A legitimate close handled during that update destroys the root.
        if not app._is_closing:
            raise
    _crumb("gui_modern_main: mainloop returned (normal exit)")
