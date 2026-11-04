"""The Downloads tab: the queue as rows, and everything done to them."""

import json
import os
import threading
import tkinter as tk
import webbrowser
import customtkinter as ctk

from tkinter import messagebox
from siphon.apps.downloads import QUEUED_STATES, extract_urls, filter_items, site_name, video_code
from siphon.core import config
from siphon.i18n.locales import T, state_label, ui_font
from siphon.ui.theme import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_HOVER,
    BG_BADGE,
    BG_CARD,
    BG_CARD_HOVER,
    BG_DARK,
    BG_HEADER,
    BG_INPUT,
    BG_SECTION,
    BG_SIDEBAR,
    BORDER,
    BORDER_CARD,
    BORDER_HOVER,
    CARD_RADIUS,
    CONTROL_RADIUS,
    ERROR_C,
    ERROR_DIM,
    SUCCESS,
    SUCCESS_DIM,
    TEXT_DIM,
    TEXT_PRI,
    TEXT_SEC,
    WARNING,
    WARNING_DIM,
    WHITE,
    color_for_mode)
from siphon.apps.app_basics import (
    CSV_PATH,
    ERR_BLOCKED,
    _KEEP_PROGRESS_STATES,
    _download_row_action,
    _fallback_name,
    _fmt_duration,
    _fmt_size)
from siphon.apps.download_manager import (
    DownloadItem)
from siphon.apps.file_actions import (
    _find_item_file,
    _reveal_in_explorer)
from siphon.apps.thumbnails import (
    _ADAPTER_TITLE_LIMIT,
    _TITLE_ATTEMPTS,
    _clear_thumb,
    _fetch_thumbnail)


class DownloadsTabMixin:
    """The Downloads tab: the queue as rows, and everything done to them."""

    # ── Download Tab ─────────────────────────────────────────────────
    def _build_download_tab(self):
        tab = self._tab_frames['download']

        # ── Floating Input card ─────────────────────────────────────
        input_frame = ctk.CTkFrame(
            tab, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD)
        input_frame.pack(fill='x', padx=16, pady=(14, 8))

        # Save location
        row1 = ctk.CTkFrame(input_frame, fg_color='transparent')
        row1.pack(fill='x', padx=18, pady=(12, 5))
        ctk.CTkLabel(row1, text=T('save_location'), text_color=TEXT_SEC, width=86,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        self._dest_var = ctk.StringVar(value=self._dest)
        ctk.CTkEntry(row1, textvariable=self._dest_var,
                     height=38, corner_radius=CONTROL_RADIUS,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI, font=(ui_font(), 11)).pack(side='left', fill='x',
                                               expand=True, padx=10)
        ctk.CTkButton(row1, text=T('browse_folder'), width=72, height=38, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._pick_dest).pack(side='left')
        ctk.CTkButton(row1, text=T('open_btn'), width=60, height=38, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._open_dest_folder).pack(side='left', padx=(6, 0))

        # Download URL
        row2 = ctk.CTkFrame(input_frame, fg_color='transparent')
        row2.pack(fill='x', padx=18, pady=(0, 12))
        ctk.CTkLabel(row2, text=T('url_label'), text_color=TEXT_SEC, width=86,
                     font=(ui_font(), 11, 'bold'), anchor='w').pack(side='left')
        self._dl_url_var = ctk.StringVar(value=self._url_input)
        ctk.CTkEntry(row2, textvariable=self._dl_url_var,
                     height=38, corner_radius=CONTROL_RADIUS,
                     fg_color=BG_INPUT, border_color=BORDER, border_width=1,
                     text_color=TEXT_PRI, font=('Consolas', 10)).pack(side='left', fill='x',
                                               expand=True, padx=10)

        # ── Floating Action bar ─────────────────────────────────────
        bar = ctk.CTkFrame(
            tab, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD, height=106)
        bar.pack(fill='x', padx=16, pady=(0, 8))
        bar.pack_propagate(False)
        bar.grid_columnconfigure(1, weight=1)

        actions_left = ctk.CTkFrame(bar, fg_color='transparent')
        actions_left.grid(row=0, column=0, padx=(16, 8), pady=10, sticky='w')
        ctk.CTkButton(actions_left, text=T('download_btn'), width=112, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=WHITE,
                      font=(ui_font(), 11, 'bold'),
                      command=self._download_url).pack(side='left')
        ctk.CTkButton(actions_left, text=T('download_all_btn'), width=126, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._download_all).pack(side='left', padx=(8, 0))
        local_actions = ctk.CTkFrame(bar, fg_color='transparent')
        local_actions.grid(row=1, column=0, columnspan=3,
                           padx=16, pady=(0, 10), sticky='w')
        ctk.CTkButton(
            local_actions, text=T('import_urls'), width=112, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            command=self._import_urls_file).pack(side='left', padx=(8, 0))
        ctk.CTkButton(
            local_actions, text=T('paste_urls'), width=104, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            command=self._paste_urls).pack(side='left', padx=(8, 0))
        ctk.CTkButton(
            local_actions, text=T('export_queue'), width=92, height=38,
            corner_radius=CONTROL_RADIUS, fg_color='transparent',
            border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
            command=self._export_queue).pack(side='left', padx=(8, 0))

        speed = ctk.CTkFrame(bar, fg_color='transparent')
        speed.grid(row=0, column=1, pady=10)
        ctk.CTkLabel(speed, text=T('speed_limit'), text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(side='left', padx=(0, 8))
        self._speed_var = ctk.StringVar(value=self._speed_label())
        self._speed_menus = []
        menu = ctk.CTkOptionMenu(
            speed, values=self._speed_values(), variable=self._speed_var,
            command=self._on_speed_change, width=118, height=38,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER, dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 10), dropdown_font=(ui_font(), 10))
        menu.pack(side='left')
        self._speed_menus.append(menu)

        destructive = ctk.CTkFrame(bar, fg_color='transparent')
        destructive.grid(row=0, column=2, padx=(8, 16), pady=10, sticky='e')
        ctk.CTkButton(destructive, text=T('pause_all'), width=88, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1,
                      border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=WARNING,
                      command=self._dlmgr.pause_all).pack(side='left')
        ctk.CTkButton(destructive, text=T('resume_all'), width=88, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1,
                      border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=SUCCESS,
                      command=self._dlmgr.resume_all).pack(side='left',
                                                           padx=(8, 0))
        ctk.CTkButton(destructive, text=T('cancel_all'), width=88, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=ERROR_C,
                      command=self._cancel_all).pack(side='left', padx=(8, 0))
        ctk.CTkButton(destructive, text=T('clear_list'), width=70, height=38,
                      corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
                      command=self._clear_queue).pack(side='left', padx=(8, 0))

        filter_bar = ctk.CTkFrame(
            tab, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD, height=48)
        filter_bar.pack(fill='x', padx=16, pady=(0, 6))
        filter_bar.pack_propagate(False)
        self._dl_filter_labels = {
            'all': T('queue_filter_all'),
            'active': T('queue_filter_active'),
            'queued': T('queue_filter_queued'),
            'failed': T('queue_filter_failed'),
            'done': T('queue_filter_done'),
            'paused': T('queue_filter_paused'),
        }
        self._dl_filter_var = ctk.StringVar(
            value=self._dl_filter_labels[self._dl_filter])
        ctk.CTkSegmentedButton(
            filter_bar, values=list(self._dl_filter_labels.values()),
            variable=self._dl_filter_var,
            command=self._on_download_filter_change,
            height=32, corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            unselected_color=BG_INPUT,
            unselected_hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI, font=(ui_font(), 10, 'bold')).pack(
                side='left', padx=16, pady=8)

        # Sorting is separate from filtering: the tabs choose which rows, this
        # chooses their order.  "Default" is the grouping the list is built
        # around; the rest are for finding one row in a long list.
        self._dl_sort_labels = {
            'default': T('sort_default'), 'name': T('sort_name'),
            'size': T('sort_size'), 'newest': T('sort_newest'),
            'oldest': T('sort_oldest'),
        }
        self._dl_sort_var = ctk.StringVar(
            value=self._dl_sort_labels[self._dl_sort])
        ctk.CTkOptionMenu(
            filter_bar, values=list(self._dl_sort_labels.values()),
            variable=self._dl_sort_var, command=self._on_download_sort_change,
            width=150, height=32, corner_radius=CONTROL_RADIUS,
            fg_color=BG_INPUT, button_color=BORDER_HOVER,
            button_hover_color=ACCENT, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI, font=(ui_font(), 10),
            dropdown_font=(ui_font(), 11), dynamic_resizing=False).pack(
                side='left', pady=8)

        # A clear total — counts plus the time left for the whole queue —
        # right above the list, not only in the small bottom bar.
        self._dl_summary_lbl = ctk.CTkLabel(
            filter_bar, text='', text_color=TEXT_SEC, anchor='e',
            font=(ui_font(), 11, 'bold'))
        self._dl_summary_lbl.pack(side='right', padx=16)

        # ── Download list ───────────────────────────────────────────
        # A fixed pool of rows is moved over the list instead of one widget
        # per download: a thousand queued videos then cost the same as ten.
        list_area = ctk.CTkFrame(tab, fg_color=BG_DARK, corner_radius=0)
        list_area.pack(fill='both', expand=True)
        self._dl_scrollbar = ctk.CTkScrollbar(
            list_area, command=self._dl_on_scrollbar,
            button_color=BORDER, button_hover_color=BORDER_HOVER)
        self._dl_scrollbar.pack(side='right', fill='y', padx=(0, 4), pady=4)
        self._dl_scrollbar_shown = True
        self._dl_viewport = tk.Frame(
            list_area, bg=color_for_mode(
                BG_DARK, 'dark' if ctk.get_appearance_mode().lower() == 'dark'
                else 'light'),
            highlightthickness=0, bd=0)
        self._dl_viewport.pack(side='left', fill='both', expand=True)
        self._dl_scroll = self._dl_viewport      # kept: "is the list built?"
        self._dl_pool: list[dict] = []
        self._dl_first = 0
        self._dl_view_items: list[DownloadItem] = []
        self._dl_empty_lbl = ctk.CTkLabel(
            self._dl_viewport, text=T('dl_list_empty'), text_color=TEXT_DIM,
            font=(ui_font(), 13))
        self._dl_viewport.bind(
            '<Configure>', lambda _e: self._dl_on_resize())
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self._dl_viewport.bind(seq, self._dl_on_wheel, add='+')

    def _retry_download(self, url: str):
        item = next((i for i in self._dlmgr.get_items() if i.url == url), None)
        if item is None:
            return
        dest = item.dest or self._dest_var.get() or 'download'
        restart = getattr(self._dlmgr, 'restart', None)
        if callable(restart) and restart(url, dest):
            return
        item.progress = 0
        item.speed = ''
        item.error = ''
        item.auto_requeues = 0
        item.retry_count = 0
        self._dlmgr.enqueue(url, dest)

    def _handle_download_action(self, url: str):
        item = next((i for i in self._dlmgr.get_items() if i.url == url), None)
        if item is None:
            return
        action = _download_row_action(item)
        if action == 'pause':
            self._dlmgr.pause(url)
        elif action == 'resume':
            self._dlmgr.resume(url, item.dest or self._dest_var.get())
        elif action == 'retry':
            self._retry_download(url)
        elif action == 'force':
            item.error = ''
            self._dlmgr.enqueue(url, item.dest or self._dest_var.get() or 'download',
                                force=True)
            self._refresh_downloads(schedule=False)

    def _on_download_filter_change(self, label):
        reverse = {value: key for key, value in self._dl_filter_labels.items()}
        self._dl_filter = reverse.get(label, 'all')
        self._dl_gen += 1
        # The rows belong to the pool and are reused for whatever the filter
        # now shows.  Destroying them here emptied the list for good: the pool
        # kept handing out widgets that no longer existed.
        self._dl_rows.clear()
        self._dl_first = 0
        self._refresh_downloads(schedule=False)

    def _filtered_download_items(self, items):
        # The queue's own order decides where a waiting row sits, so that
        # moving a download to the front of the queue moves its row too.
        return filter_items(items, self._dl_filter,
                            self._dlmgr.queue_positions(), self._dl_sort)

    def _on_download_sort_change(self, label):
        """Put the list in the order the person picked, and keep it."""
        reverse = {text: key for key, text in self._dl_sort_labels.items()}
        self._dl_sort = reverse.get(label, 'default')
        config.set_download_sort(self._dl_sort)
        self._dl_first = 0          # a new order starts at the top
        self._refresh_downloads(schedule=False)

    def _notify_batch_complete(self):
        if not config.get_notify_on_complete() or self._is_closing:
            return
        try:
            self._status_lbl.configure(text=T('batch_complete'))
        except (AttributeError, tk.TclError):
            pass
        try:
            if os.name == 'nt':
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                self.bell()
        except Exception:
            pass

    def _cancel_all(self):
        if ((self._dlmgr.active_count or self._dlmgr.pending_count) and
                not messagebox.askyesno(
                    T('cancel_all'), T('cancel_all_confirm'))):
            return
        self._dlmgr.cancel_all()

    def _clear_queue(self):
        if self._dlmgr.get_items() and not messagebox.askyesno(
                T('clear_list'), T('clear_queue_confirm')):
            return
        self._dlmgr.clear_all()
        self._dl_gen += 1
        self._last_download_save_sig = None
        try:
            self._dlmgr.save_csv(CSV_PATH)
        except Exception as e:
            print(f'[clear queue save failed] {e}', flush=True)
        self._refresh_downloads(schedule=False)

    def _clear_saved_queue(self):
        if not messagebox.askyesno(T('clear_saved_queue'),
                                   T('clear_saved_queue_confirm')):
            return
        self._dlmgr.clear_all()
        self._dl_gen += 1
        self._last_download_save_sig = None
        try:
            self._dlmgr.save_csv(CSV_PATH)
            if getattr(self, '_status_lbl', None) is not None:
                self._status_lbl.configure(text=T('clear_saved_queue_done'))
            messagebox.showinfo(T('clear_saved_queue'), T('clear_saved_queue_done'))
        except Exception as e:
            messagebox.showerror(T('clear_saved_queue_failed'), str(e))
        finally:
            self._refresh_downloads(schedule=False)

    # ── Download list refresh (incremental — no destroy/rebuild storm) ──
    _STATE_COLORS = {
        '下載中': ACCENT, '準備中': WARNING, '等待中': WARNING,
        '已下載': SUCCESS,
        '未完成': WARNING, '已取消': TEXT_DIM,
        '網址錯誤': ERROR_C, '封鎖/解析失敗': ERROR_C,
        '等待重試': WARNING, '已排程': ACCENT, '已暫停': TEXT_DIM,
        '已存在': SUCCESS,
    }

    _STATE_BACKGROUNDS = {
        '下載中': ACCENT_DIM, '準備中': WARNING_DIM, '等待中': WARNING_DIM,
        '已下載': SUCCESS_DIM,
        '未完成': WARNING_DIM, '已取消': BG_BADGE,
        '網址錯誤': ERROR_DIM, '封鎖/解析失敗': ERROR_DIM,
        '等待重試': WARNING_DIM, '已排程': ACCENT_DIM,
        '已暫停': BG_BADGE,
        '已存在': SUCCESS_DIM,
    }

    def _queue_step(self, url, delta):
        pos = (getattr(self, '_queue_pos', {}) or {}).get(url)
        if pos is None:
            return
        if self._dlmgr.move_in_queue(url, pos + delta):
            self._refresh_downloads(schedule=False)

    def _queue_edit_position(self, url):
        """Turn the number into a small entry; Enter moves the item there."""
        w = self._dl_rows.get(url)
        pos = (getattr(self, '_queue_pos', {}) or {}).get(url)
        if w is None or pos is None or w.get('q_editor') is not None:
            return
        var = ctk.StringVar(value=str(pos))
        editor = ctk.CTkEntry(
            w['queue_box'], textvariable=var, width=34, height=22,
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
                self._dlmgr.move_in_queue(url, int(value))
            self._refresh_downloads(schedule=False)

        editor.bind('<Return>', lambda _e: finish(True))
        editor.bind('<KP_Enter>', lambda _e: finish(True))
        editor.bind('<Escape>', lambda _e: finish(False))
        editor.bind('<FocusOut>', lambda _e: finish(True))

    def _resolve_missing_titles(self, items):
        """Give queued rows their real names.

        A pasted link only carries the site's own video number, so the row
        would read "924865622775" until the download starts.  Each waiting
        row's page is read in the background, just for its title.

        A page that cannot be named right now — the site is busy, or it
        answered with a bot check — is tried again on a later sweep rather
        than left as a number for good, up to _TITLE_ATTEMPTS times.
        """
        if getattr(self, '_title_worker_busy', False):
            return
        waiting = [item.url for item in items
                   if not item.local and item.state in QUEUED_STATES
                   and (not item.name or item.name == _fallback_name(item.url))
                   and self._titles_tried.get(item.url, 0) < _TITLE_ATTEMPTS]
        if not waiting:
            return
        waiting = waiting[:120]
        self._title_worker_busy = True

        def work():
            try:
                from concurrent.futures import ThreadPoolExecutor
                import siphon.sites as sites
                from siphon.sites import generic
                seen: dict = {}
                missed = []

                def take(url, title, trusted=False):
                    """True when the title was used, False when refused.

                    ``trusted`` marks the site adapter's answer, which is the
                    name the file will be saved under: two videos really can
                    share a name, so it is never second-guessed.
                    """
                    if not title:
                        return False
                    if not trusted:
                        # The same text on three different videos is a notice
                        # the site puts on every page, not a title.
                        seen.setdefault(title, []).append(url)
                        if len(seen[title]) == 3:
                            for stale in seen[title]:
                                self._ui(lambda u=stale, t=title:
                                         self._clear_title(u, t))
                                missed.append(stale)
                        if len(seen[title]) >= 3:
                            return False
                    self._ui(lambda u=url, t=title: self._apply_title(u, t))
                    return True

                # First pass: read the top of each page.  Cheap and parallel,
                # so most rows are named within a second or two.
                with ThreadPoolExecutor(max_workers=8) as pool:
                    for url, title in zip(waiting,
                                          pool.map(generic.page_title, waiting)):
                        if not take(url, title):
                            missed.append(url)

                # Second pass, for the rest: ask the site's own adapter, which
                # is the code that will name the file when the download runs.
                # It knows where that site keeps its heading and opens the
                # off-screen browser when the site insists on one, so it costs
                # seconds a page; what does not fit in this sweep is picked up
                # by the next one.
                tried = self._titles_tried
                # Least-tried first, so a long list works its way through
                # instead of the same few pages being retried every sweep.
                rest = sorted(dict.fromkeys(missed),
                              key=lambda u: tried.get(u, 0))[:_ADAPTER_TITLE_LIMIT]
                for url in rest:
                    tried[url] = tried.get(url, 0) + 1
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for url, (title, picture) in zip(rest,
                                                     pool.map(sites.describe, rest)):
                        if self._is_closing:
                            break
                        take(url, title, trusted=True)
                        # The same page read also carries the video's own
                        # picture, so a pasted link gets one too.
                        if picture:
                            self._ui(lambda u=url, p=picture:
                                     self._apply_thumbnail(u, p))
            except Exception as exc:
                print(f'[title] {exc}', flush=True)
            finally:
                self._title_worker_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _clear_title(self, url, title):
        """Take back a name that turned out to be the site's own banner."""
        for item in self._dlmgr.get_items():
            if item.url == url and item.name == title:
                item.name = _fallback_name(url)
                break

    def _apply_thumbnail(self, url, picture):
        """Give a row the picture its page carries, if it has none yet."""
        for item in self._dlmgr.get_items():
            if item.url == url and not item.thumbnail:
                item.thumbnail = str(picture)[:2048]
                break

    def _apply_title(self, url, title):
        for item in self._dlmgr.get_items():
            if item.url == url and (not item.name
                                    or item.name == _fallback_name(url)):
                item.name = title
                break

    def _refresh_downloads(self, schedule: bool = True):
        if self._is_closing:
            return
        if (self._rebuilding or getattr(self, '_status_lbl', None) is None
                or getattr(self, '_dl_scroll', None) is None):
            # Names are filled in even while another tab is open.
            try:
                self._resolve_missing_titles(self._dlmgr.get_items())
            except Exception:
                pass
            if schedule:
                try:
                    self.after(1000, self._refresh_downloads)
                except tk.TclError:
                    pass
            return
        try:
            all_items = self._dlmgr.get_items()
            self._resolve_missing_titles(all_items)
            items = self._filtered_download_items(all_items)
            self._queue_pos = self._dlmgr.queue_positions()
            if not self._dl_pool:
                self._dl_on_resize()
            self._render_downloads(items)

            # Update status bar
            a = self._dlmgr.active_count
            p = self._dlmgr.pending_count
            parts = []
            if a:
                parts.append(f'{state_label("下載中")} {a}/{self._dlmgr.max_concurrent}')
            if p:
                parts.append(f'{state_label("等待中")} {p}')
            done = sum(1 for i in all_items if i.state == '已下載')
            if done:
                parts.append(f'{state_label("已下載")} {done}')
            eta_text = self._download_eta_text() if (a or p) else ''
            if eta_text:
                parts.append(eta_text)
            self._status_lbl.configure(text='  |  '.join(parts) if parts else T('status_ready'))
            self._update_download_summary(a, p, done, eta_text)
            self._autosave_downloads(all_items)
            busy = bool(a or p)
            if busy:
                self._batch_was_busy = True
                self._batch_notified = False
            elif self._batch_was_busy and not self._batch_notified:
                self._batch_notified = True
                self._notify_batch_complete()
        except Exception as e:
            print(f'[download refresh failed] {e}', flush=True)
        finally:
            if schedule and not self._is_closing:
                try:
                    self.after(1000, self._refresh_downloads)
                except tk.TclError:
                    pass

    def _update_download_summary(self, active, pending, done, eta_text):
        """The bold line above the list: what is running, and how long the
        whole queue should take."""
        label = getattr(self, '_dl_summary_lbl', None)
        if label is None or not label.winfo_exists():
            return
        parts = []
        if active:
            parts.append(T('dl_sum_active', n=active))
        if pending:
            parts.append(T('dl_sum_queued', n=pending))
        if done:
            parts.append(T('dl_sum_done', n=done))
        # The total time left, built straight from the estimate so it reads the
        # same in every language.
        try:
            est = self._dlmgr.queue_estimate() if (active or pending) else None
        except Exception:
            est = None
        if est and est.get('videos'):
            size = _fmt_size(est['bytes']) if est['bytes'] else ''
            prefix = '≈ ' if est['estimated'] else ''
            if est['speed'] > 0 and est['bytes']:
                parts.append(T('dl_sum_left',
                               size=prefix + size,
                               time=_fmt_duration(est['bytes'] / est['speed'])))
            elif size:
                parts.append(prefix + size)
        try:
            label.configure(text='   ·   '.join(parts))
        except tk.TclError:
            pass

    def _download_eta_text(self):
        """'≈ 5.4 GB left · about 1h 30m at 1 MB/s (limit)' for the status bar."""
        try:
            est = self._dlmgr.queue_estimate()
        except Exception:
            return ''
        if not est['videos']:
            return ''
        size = _fmt_size(est['bytes']) if est['bytes'] else ''
        if est['unknown'] and not est['bytes']:
            return T('eta_size_unknown', n=est['videos'])
        prefix = '≈ ' if est['estimated'] else ''
        speed = est['speed']
        if speed <= 0:
            return T('eta_left_no_speed', size=prefix + size)
        speed_text = (f'{speed / 1024:.0f} KB/s' if speed < 1024 * 1024
                      else f'{speed / 1024 / 1024:.1f} MB/s')
        text = T('eta_left', size=prefix + size, time=_fmt_duration(est['bytes'] / speed),
                 speed=speed_text,
                 how=T('eta_at_limit') if est['limited'] else T('eta_at_current'))
        if est['unknown']:
            text += ' ' + T('eta_plus_unknown', n=est['unknown'])
        return text

    def _autosave_downloads(self, items: list[DownloadItem]):
        self._download_autosave_ticks += 1
        if self._download_autosave_ticks < 10:
            return
        self._download_autosave_ticks = 0
        sig = tuple((
            i.url, i.name, i.state, i.progress, i.dest,
            i.resolution,
            i.filename_template, i.error, i.error_code,
            i.retry_count, i.not_before,
        ) for i in items)
        if sig == self._last_download_save_sig:
            return
        try:
            self._dlmgr.save_csv(CSV_PATH)
            self._last_download_save_sig = sig
        except Exception:
            pass

    DL_ROW_HEIGHT = 92          # one row plus the gap under it

    def _make_dl_row(self) -> dict:
        """Build one empty row for the pool.

        The row is not tied to a download: every button asks the row which
        address it is showing right now, so the same widgets can be moved to
        whatever is on screen.
        """
        w: dict = {'url': ''}
        row = ctk.CTkFrame(
            self._dl_viewport, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD, height=self.DL_ROW_HEIGHT - 16)
        row.pack_propagate(False)

        # Waiting-queue position: ▲ / number (click to type) / ▼
        queue_box = ctk.CTkFrame(row, fg_color='transparent', width=40)
        queue_box.pack(side='left', fill='y', padx=(8, 0), pady=4)
        queue_box.pack_propagate(False)
        q_up = ctk.CTkButton(
            queue_box, text='▲', width=30, height=18, corner_radius=4,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 9),
            command=lambda: self._queue_step(w['url'], -1))
        q_num = ctk.CTkLabel(
            queue_box, text='', width=30, height=22, corner_radius=4,
            fg_color=BG_BADGE, text_color=TEXT_PRI, cursor='hand2',
            font=('Consolas', 11, 'bold'))
        q_num.bind('<Button-1>', lambda _e: self._queue_edit_position(w['url']))
        q_down = ctk.CTkButton(
            queue_box, text='▼', width=30, height=18, corner_radius=4,
            fg_color='transparent', hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, font=(ui_font(), 9),
            command=lambda: self._queue_step(w['url'], +1))

        state_holder = ctk.CTkFrame(
            row, width=92, height=32, corner_radius=6, fg_color=BG_BADGE)
        state_holder.pack(side='left', padx=(14, 10))
        state_holder.pack_propagate(False)
        state_lbl = ctk.CTkLabel(
            state_holder, text='—', text_color=TEXT_SEC,
            font=(ui_font(), 10, 'bold'))
        state_lbl.pack(fill='both', expand=True, padx=6)

        thumb_holder = ctk.CTkFrame(
            row, width=88, height=50, corner_radius=6, fg_color=BG_SIDEBAR)
        thumb_holder.pack(side='left', padx=(0, 10), pady=10)
        thumb_holder.pack_propagate(False)
        thumb_lbl = ctk.CTkLabel(
            thumb_holder, text='', text_color=TEXT_DIM, font=(ui_font(), 8))
        thumb_lbl.pack(fill='both', expand=True)

        remove_btn = ctk.CTkButton(
            row, text='✕', width=32, height=32, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_DIM,
            font=('Consolas', 12),
            command=lambda: self._dlmgr.remove_item(w['url']))
        remove_btn.pack(side='right', padx=(6, 14))

        link_btn = ctk.CTkButton(
            row, text='🔗', width=32, height=32, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=(ui_font(), 11),
            command=lambda: self._open_item_page(w['url']))
        link_btn.pack(side='right', padx=(2, 0))

        folder_btn = ctk.CTkButton(
            row, text='▣', width=32, height=32, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=TEXT_SEC,
            font=('Consolas', 11),
            command=lambda: self._open_item_folder(w['url']))
        folder_btn.pack(side='right', padx=(2, 0))

        retry_btn = ctk.CTkButton(
            row, text='', width=82, height=32, corner_radius=CONTROL_RADIUS,
            fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
            hover_color=BG_CARD_HOVER, text_color=ACCENT,
            font=(ui_font(), 10, 'bold'),
            command=lambda: self._handle_download_action(w['url']))

        metrics = ctk.CTkFrame(row, fg_color='transparent')
        metrics.pack(side='right', padx=(6, 2))
        pb = ctk.CTkProgressBar(metrics, width=150, height=8, corner_radius=5,
                                fg_color=BG_INPUT, progress_color=ACCENT)
        pb.set(0)
        pct_lbl = ctk.CTkLabel(metrics, text='', text_color=TEXT_SEC,
                               font=('Consolas', 10, 'bold'), width=46)
        spd_lbl = ctk.CTkLabel(metrics, text='', text_color=TEXT_SEC,
                               font=('Consolas', 9), width=76)

        text_stack = ctk.CTkFrame(row, fg_color='transparent')
        text_stack.pack(side='left', fill='both', expand=True,
                        padx=(0, 10), pady=10)
        name_lbl = ctk.CTkLabel(text_stack, text='', text_color=TEXT_PRI,
                                font=(ui_font(), 11, 'bold'), anchor='w')
        name_lbl.pack(fill='x', anchor='w')
        detail_lbl = ctk.CTkLabel(text_stack, text='', text_color=TEXT_DIM,
                                  font=('Consolas', 9), anchor='w',
                                  cursor='hand2')
        detail_lbl.pack(fill='x', anchor='w', pady=(3, 0))
        detail_lbl.bind('<Button-1>',
                        lambda _e: self._copy_job_diagnostics(w['url']))

        w.update({
            'row': row, 'state_holder': state_holder, 'state_lbl': state_lbl,
            'name_lbl': name_lbl, 'detail_lbl': detail_lbl, 'metrics': metrics,
            'pb': pb, 'pct_lbl': pct_lbl, 'spd_lbl': spd_lbl,
            'retry_btn': retry_btn, '_before_remove': remove_btn,
            'folder_btn': folder_btn, 'thumb_lbl': thumb_lbl,
            'pb_visible': False, 'pct_visible': False, 'spd_visible': False,
            'retry_visible': False, 'last_retry_action': None,
            'last_state': None, 'last_name': None, 'last_detail': None,
            'last_progress': -1, 'last_speed': None, 'last_thumbnail': None,
            'queue_box': queue_box, 'q_up': q_up, 'q_num': q_num,
            'q_down': q_down, 'q_visible': False, 'last_q': None,
            'q_editor': None, '_placed': None, '_width': None,
        })
        self._dl_bind_wheel(row)
        return w

    def _dl_bind_wheel(self, widget):
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            tk.Misc.bind(widget, seq, self._dl_on_wheel, add='+')
        for child in widget.winfo_children():
            self._dl_bind_wheel(child)

    def _bind_dl_row(self, w: dict, item: DownloadItem):
        """Show ``item`` in a pooled row, forgetting whatever was there."""
        if w['url'] != item.url:
            w.update({'url': item.url, 'last_state': None, 'last_name': None,
                      'last_detail': None, 'last_progress': -1,
                      'last_speed': None, 'last_thumbnail': None,
                      'last_q': None, 'last_retry_action': None})
            if w.get('q_editor') is not None:
                try:
                    w['q_editor'].destroy()
                    w['q_num'].pack(side='top', pady=1, after=w['q_up'])
                except tk.TclError:
                    pass
                w['q_editor'] = None
            try:
                _clear_thumb(w['thumb_lbl'])
            except tk.TclError:
                pass
        self._update_dl_row(w, item)

    # ── scrolling ───────────────────────────────────────────────────
    def _dl_visible_count(self):
        height = max(1, self._dl_viewport.winfo_height())
        return max(1, height // self.DL_ROW_HEIGHT)

    def _dl_on_resize(self):
        needed = max(1, -(-max(1, self._dl_viewport.winfo_height())
                          // self.DL_ROW_HEIGHT)) + 1
        while len(self._dl_pool) < needed:
            try:
                self._dl_pool.append(self._make_dl_row())
            except Exception as exc:
                print(f'[download row build failed] {exc}', flush=True)
                break
        self._render_downloads()

    def _dl_on_wheel(self, event):
        if getattr(event, 'num', None) == 4:
            step = -1
        elif getattr(event, 'num', None) == 5:
            step = 1
        else:
            delta = getattr(event, 'delta', 0)
            if not delta:
                return 'break'
            step = -1 if delta > 0 else 1
            if abs(delta) >= 240:
                step *= max(1, abs(delta) // 120)
        from siphon.ui import scroll as _scroll
        speed = _scroll._cache.get('speed')
        if speed is None:
            speed = _scroll._cache['speed'] = _scroll.get_speed()
        rows = max(1, round(speed / 4))
        self._dl_scroll_to(self._dl_first + step * rows)
        return 'break'

    def _dl_on_scrollbar(self, *args):
        total = len(self._dl_view_items)
        if not total or not args:
            return
        if args[0] == 'moveto':
            self._dl_scroll_to(int(round(float(args[1]) * total)))
        elif args[0] == 'scroll':
            amount = int(args[1])
            unit = (self._dl_visible_count()
                    if len(args) > 2 and args[2] == 'pages' else 1)
            self._dl_scroll_to(self._dl_first + amount * unit)

    def _dl_scroll_to(self, first):
        limit = max(0, len(self._dl_view_items) - self._dl_visible_count())
        first = max(0, min(int(first), limit))
        if first != self._dl_first:
            self._dl_first = first
            self._render_downloads(self._dl_view_items)

    def _render_downloads(self, items=None):
        """Place the pooled rows over the visible slice of the list."""
        if getattr(self, '_dl_viewport', None) is None:
            return
        if items is not None:
            self._dl_view_items = items
        items = self._dl_view_items
        total = len(items)
        visible = self._dl_visible_count()
        self._dl_first = max(0, min(self._dl_first, max(0, total - visible)))
        try:
            if total:
                self._dl_empty_lbl.place_forget()
            else:
                self._dl_empty_lbl.configure(
                    text=(T('queue_filter_empty')
                          if self._dlmgr.get_items() else T('dl_list_empty')))
                self._dl_empty_lbl.place(relx=0.5, y=40, anchor='n')
            width = max(1, self._dl_viewport.winfo_width())
            placed = {}
            for slot, w in enumerate(self._dl_pool):
                index = self._dl_first + slot
                if index < total:
                    item = items[index]
                    self._bind_dl_row(w, item)
                    placed[item.url] = w
                    if w['_width'] != width:
                        w['row'].configure(width=width - 24,
                                           height=self.DL_ROW_HEIGHT - 16)
                        w['_width'] = width
                    if w['_placed'] != slot:
                        w['row'].place(x=12, y=slot * self.DL_ROW_HEIGHT + 8)
                        w['_placed'] = slot
                elif w['_placed'] is not None:
                    w['row'].place_forget()
                    w['_placed'] = None
                    w['url'] = ''
            self._dl_rows = placed
            if total:
                self._dl_scrollbar.set(
                    self._dl_first / total,
                    min(1.0, (self._dl_first + visible) / total))
            else:
                self._dl_scrollbar.set(0, 1)
            # No bar at all while everything fits: a full-height track next to
            # three downloads only suggests there is more to scroll to.
            self._dl_show_scrollbar(total > visible)
        except tk.TclError:
            pass

    def _dl_show_scrollbar(self, wanted: bool):
        if bool(getattr(self, '_dl_scrollbar_shown', True)) == bool(wanted):
            return
        self._dl_scrollbar_shown = bool(wanted)
        try:
            if wanted:
                self._dl_scrollbar.pack(side='right', fill='y',
                                        padx=(0, 4), pady=4,
                                        before=self._dl_viewport)
            else:
                self._dl_scrollbar.pack_forget()
        except tk.TclError:
            pass

    def _update_queue_box(self, w: dict, item: DownloadItem):
        """The ▲ n ▼ box: only a row waiting its turn has a position."""
        pos = (getattr(self, '_queue_pos', {}) or {}).get(item.url)
        show = pos is not None
        if show != w['q_visible']:
            try:
                if show:
                    w['q_up'].pack(side='top', pady=1)
                    w['q_num'].pack(side='top', pady=1, after=w['q_up'])
                    w['q_down'].pack(side='top', pady=1)
                else:
                    for key in ('q_up', 'q_num', 'q_down'):
                        w[key].pack_forget()
            except tk.TclError:
                return
            w['q_visible'] = show
        if show and w['last_q'] != pos and w.get('q_editor') is None:
            try:
                w['q_num'].configure(text=str(pos))
            except tk.TclError:
                return
            w['last_q'] = pos

    def _update_dl_row(self, w: dict, item: DownloadItem):
        """Update an existing row's fields in place without rebuilding widgets."""
        self._update_queue_box(w, item)
        if w['last_thumbnail'] != item.thumbnail:
            w['last_thumbnail'] = item.thumbnail
            if item.thumbnail:
                self._load_download_thumb_async(
                    item.thumbnail, w, item.url, self._build_gen, item.site)
            else:
                # This video has no picture of its own, so the row must not
                # keep the one belonging to whatever it showed before.
                _clear_thumb(w['thumb_lbl'])
        # State text + color
        if w['last_state'] != item.state:
            color = self._STATE_COLORS.get(item.state, TEXT_SEC)
            try:
                w['state_holder'].configure(
                    fg_color=self._STATE_BACKGROUNDS.get(item.state, BG_BADGE),
                    width=92)
                w['state_lbl'].configure(
                    text=state_label(item.state) if item.state else '—',
                    text_color=color)
            except Exception:
                return
            w['last_state'] = item.state

        # Name and supporting detail (error or source URL) are separate levels.
        display_name = item.name or item.url
        resolution = item.resolution or config.get_resolution_pref()
        detail = T(
            'job_details', site=item.site or site_name(item.url),
            code=video_code(item.url, display_name), resolution=resolution)
        detail_color = TEXT_DIM
        if item.state == '已存在' and item.error:
            detail, detail_color = item.error, SUCCESS
        elif item.error and item.state in (
                '未完成', '封鎖/解析失敗', '已下載', '下載中'):
            if item.error == ERR_BLOCKED:
                err_text = T('blocked_vpn_hint')
            elif item.error_code:
                err_text = T(f'problem_{item.error_code}')
                if item.error and item.error not in err_text:
                    err_text = f'{err_text} · {item.error}'
            else:
                err_text = item.error
            err = err_text.replace('\n', ' ').strip()
            if len(err) > 110:
                err = err[:107] + '...'
            detail = err
            detail_color = WARNING if item.state in ('已下載', '下載中') else ERROR_C
        if w['last_name'] != display_name:
            try:
                w['name_lbl'].configure(text=display_name)
            except Exception:
                return
            w['last_name'] = display_name
        if w['last_detail'] != detail:
            try:
                w['detail_lbl'].configure(text=detail, text_color=detail_color)
            except Exception:
                return
            w['last_detail'] = detail

        retry_action = _download_row_action(item)
        if w['last_retry_action'] != retry_action:
            if retry_action:
                labels = {
                    'pause': 'pause_short',
                    'resume': 'resume_short',
                    'retry': 'retry_short',
                    'force': 'download_anyway',
                }
                label = T(labels.get(retry_action, 'retry_short'))
                try:
                    w['retry_btn'].configure(text=f'↻ {label}')
                except Exception:
                    return
            w['last_retry_action'] = retry_action
        if retry_action and not w['retry_visible']:
            w['retry_btn'].pack(side='right', padx=(2, 0), before=w['_before_remove'])
            w['retry_visible'] = True
        elif not retry_action and w['retry_visible']:
            try:
                w['retry_btn'].pack_forget()
            except Exception:
                pass
            w['retry_visible'] = False

        # Progress bar: show only while downloading
        # '下載中' keeps the bar visible even at 0% (e.g. a direct MP4 that
        # just restarted on a single connection) so the row never looks idle.
        is_downloading = item.state == '下載中'
        is_stopped_partial = (
            item.state in _KEEP_PROGRESS_STATES and item.progress > 0)
        if is_downloading or is_stopped_partial:
            if not w['pb_visible']:
                w['pb'].pack(side='left', padx=(0, 4))
                w['pb_visible'] = True
            if w['last_progress'] != item.progress:
                w['pb'].set(max(0.0, min(1.0, item.progress / 100)))
                w['last_progress'] = item.progress
            pct_text = f'{item.progress}%'
            if not w['pct_visible']:
                w['pct_lbl'].pack(side='left')
                w['pct_visible'] = True
            if w['pct_lbl'].cget('text') != pct_text:
                w['pct_lbl'].configure(text=pct_text)
        else:
            if w['pb_visible']:
                try: w['pb'].pack_forget()
                except Exception: pass
                w['pb_visible'] = False
            if w['pct_visible']:
                try: w['pct_lbl'].pack_forget()
                except Exception: pass
                w['pct_visible'] = False

        # Speed (or, for a paused/stopped item, just how much is downloaded)
        if (is_downloading and (item.speed or item.eta)) or (
                is_stopped_partial and item.size_text):
            if not w['spd_visible']:
                w['spd_lbl'].pack(side='left', padx=4)
                w['spd_visible'] = True
            if is_downloading:
                metric = ' · '.join(
                    part for part in (item.size_text, item.speed) if part)
            else:
                metric = item.size_text
            if is_downloading and item.eta:
                metric = f'{metric} · {T("eta_label", eta=item.eta)}'.strip(' ·')
            if w['last_speed'] != metric:
                w['spd_lbl'].configure(text=metric, width=300)
                w['last_speed'] = metric
        else:
            if w['spd_visible']:
                try: w['spd_lbl'].pack_forget()
                except Exception: pass
                w['spd_visible'] = False
                w['last_speed'] = None

    def _load_download_thumb_async(
            self, url: str, w: dict, for_url: str, build_gen: int,
            site_key: str = ''):
        def _worker():
            image = _fetch_thumbnail(url, site_key)
            if image is None:
                return

            def _apply():
                if self._is_closing or build_gen != self._build_gen:
                    return
                # The row is shared: while this picture was downloading it may
                # have been scrolled onto a different video.
                if w['url'] != for_url:
                    return
                label = w['thumb_lbl']
                try:
                    if not label.winfo_exists():
                        return
                    ctk_image = ctk.CTkImage(
                        light_image=image, dark_image=image, size=(80, 45))
                    label.configure(image=ctk_image, text='')
                    label._ctk_img_ref = ctk_image
                except Exception:
                    pass

            self._ui(_apply, gen=build_gen)

        try:
            self._thumb_executor.submit(_worker)
        except RuntimeError:
            pass

    def _copy_job_diagnostics(self, url: str):
        item = next((candidate for candidate in self._dlmgr.get_items()
                     if candidate.url == url), None)
        if item is None:
            return
        details = {
            'job_id': item.job_id,
            'site': item.site,
            'code': video_code(item.url, item.name),
            'state': state_label(item.state),
            'progress': item.progress,
            'url': item.url,
            'destination': item.dest,
            'resolution': item.resolution,
            'filename_template': item.filename_template,
            'error_code': item.error_code,
            'error': item.error,
            'retry_count': item.retry_count,
        }
        try:
            self.clipboard_clear()
            self.clipboard_append(json.dumps(
                details, ensure_ascii=False, indent=2))
            self._status_lbl.configure(text=T('copy_diagnostics'))
        except tk.TclError:
            pass

    def _open_item_page(self, url):
        """Open the video's page (where it was downloaded from) in the browser."""
        item = self._dlmgr._items.get(url)
        if item is not None and getattr(item, 'local', False):
            self._open_item_folder(url)      # local files have no web page
            return
        if str(url).startswith(('http://', 'https://')):
            webbrowser.open(url)

    def _open_item_folder(self, url: str):
        item = next((candidate for candidate in self._dlmgr.get_items()
                     if candidate.url == url), None)
        if item is None:
            return
        path = _find_item_file(item, getattr(self._dlmgr, 'finished_paths', {}).get(url),
                               self._dest_var.get() or 'download')
        if path and _reveal_in_explorer(path):
            return
        current = self._dest_var.get()
        try:
            self._dest_var.set(item.dest or current)
            self._open_dest_folder()
        finally:
            self._dest_var.set(current)

    # ── Clipboard monitor (main-thread safe) ─────────────────────────
    def _clipboard_poll(self):
        if self._is_closing:
            return
        if self._rebuilding:
            try:
                self.after(800, self._clipboard_poll)
            except tk.TclError:
                pass
            return
        try:
            clp = self.clipboard_get()
            if clp != self._clp_text:
                self._clp_text = clp
                urls = extract_urls(clp)
                if urls and getattr(self, '_dl_url_var', None) is not None:
                    # Clipboard monitoring is a convenience hint only.  It no
                    # longer mutates the persistent queue without a click.
                    self._dl_url_var.set(urls[0])
        except (tk.TclError, Exception):
            pass
        finally:
            if not self._is_closing:
                try:
                    self.after(800, self._clipboard_poll)
                except tk.TclError:
                    pass
