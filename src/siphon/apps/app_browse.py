"""The Browse tab: a site listing, selecting videos, and sending them to the queue."""

import threading
import time
import tkinter as tk
import customtkinter as ctk

from tkinter import filedialog, messagebox
from urllib.parse import urlsplit
from siphon import sites as M3U8Sites
from siphon.apps.downloads import (
    ACTIVE_STATES,
    DONE_STATES,
    QUEUED_STATES,
    QueueAddSummary,
    export_items,
    extract_urls,
    load_url_file,
    next_schedule_epoch,
    site_name,
    storage_preflight,
    video_code)
from siphon.core import config
from siphon.i18n.locales import T, ui_font
from siphon.sites.base import MirrorsBlockedError, is_unreachable_error
from siphon.ui.preview import open_video_preview
from siphon.ui.theme import (
    ACCENT,
    ACCENT_DIM,
    ACCENT_HOVER,
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
    TEXT_DIM,
    TEXT_PRI,
    TEXT_SEC,
    WHITE)
from siphon.apps.app_basics import (
    SITES,
    SITES_LOADING_HINT,
    _crumb,
    _kvs_browser_for_url,
    _section_label,
    fetch_page_data)
from siphon.apps.thumbnails import (
    _THUMB_SIZE,
    _fetch_thumbnail)


class BrowseTabMixin:
    """The Browse tab: a site listing, selecting videos, and sending them to the queue."""

    # ── Browse Tab ───────────────────────────────────────────────────
    def _build_browse_tab(self):
        tab = self._tab_frames['browse']

        # ── Floating two-level workspace command bar ────────────────
        top = ctk.CTkFrame(
            tab, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD, height=112)
        top.pack(fill='x', padx=16, pady=(14, 4))
        top.pack_propagate(False)
        self._browse_toolbar = top

        filters = ctk.CTkFrame(top, fg_color='transparent')
        filters.pack(fill='x', padx=20, pady=(10, 6))
        self._site_var = ctk.StringVar(value=self._site_key)
        self._site_menu = ctk.CTkOptionMenu(
            filters, values=list(SITES.keys()), variable=self._site_var,
            command=self._on_site_change, width=170, height=36,
            corner_radius=CONTROL_RADIUS,
            fg_color=ACCENT, button_color=ACCENT_HOVER,
            button_hover_color=ACCENT_HOVER, text_color=WHITE,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 12, 'bold'), dropdown_font=(ui_font(), 12),
            dynamic_resizing=False)
        self._site_menu.pack(side='left')

        self._cat_var = ctk.StringVar(value=T('loading_browse'))
        self._cat_menu = ctk.CTkOptionMenu(
            filters, values=[T('loading_browse')], variable=self._cat_var,
            command=self._on_cat_change, width=190, height=36,
            fg_color=BG_INPUT, button_color=BORDER_HOVER,
            button_hover_color=ACCENT, text_color=TEXT_PRI,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color=TEXT_PRI, corner_radius=CONTROL_RADIUS,
            font=(ui_font(), 11), dropdown_font=(ui_font(), 11))
        self._cat_menu.pack(side='left', padx=(10, 0))

        self._search_var = ctk.StringVar()
        self._search_entry = ctk.CTkEntry(
            filters, textvariable=self._search_var,
            placeholder_text=T('search_placeholder'), height=36,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            corner_radius=CONTROL_RADIUS, text_color=TEXT_PRI,
            font=(ui_font(), 11))
        self._search_entry.pack(
            side='left', fill='x', expand=True, padx=(10, 8))
        self._search_entry.bind('<Return>', lambda e: self._on_search())
        # Sort for the current search only (shown while search results are on screen).
        self._search_sort_var = ctk.StringVar(value='')
        self._search_sort_menu = ctk.CTkOptionMenu(
            filters, values=[''], variable=self._search_sort_var,
            command=self._on_search_sort, width=140, height=36,
            corner_radius=CONTROL_RADIUS, fg_color=BG_INPUT,
            button_color=BORDER_HOVER, button_hover_color=ACCENT,
            text_color=TEXT_PRI, dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER, dropdown_text_color=TEXT_PRI,
            font=(ui_font(), 11), dropdown_font=(ui_font(), 11))
        self._search_sort_visible = False
        self._search_btn = ctk.CTkButton(
            filters, text=T('search_btn'), command=self._on_search,
            width=76, height=36, corner_radius=CONTROL_RADIUS,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE, font=(ui_font(), 11, 'bold'))
        self._search_btn.pack(side='left')
        self._search_query = ''

        actions = ctk.CTkFrame(top, fg_color='transparent')
        actions.pack(fill='x', padx=20, pady=(0, 10))

        self._sel_lbl = ctk.CTkLabel(
            actions, text=f'0 {T("selected")}', text_color=TEXT_SEC,
            font=(ui_font(), 11, 'bold'))
        self._sel_lbl.pack(side='left')
        ctk.CTkButton(actions, text=T('download_selected'),
                      command=lambda: self._review_selected(True),
                      width=128, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=WHITE, font=(ui_font(), 11, 'bold')).pack(
                          side='right', padx=(8, 0))
        ctk.CTkButton(actions, text=T('add_to_queue'),
                      command=lambda: self._review_selected(False),
                      width=104, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER,
                      text_color=TEXT_PRI, font=(ui_font(), 11)).pack(side='right')
        ctk.CTkButton(actions, text=T('select_all_results_btn'),
                      command=self._select_all_results,
                      width=134, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1,
                      border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER,
                      text_color=TEXT_PRI, font=(ui_font(), 10)).pack(
                          side='right', padx=(0, 8))
        ctk.CTkButton(actions, text=T('select_page_btn'), command=self._select_all_on_page,
                      width=92, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER,
                      text_color=TEXT_PRI, font=(ui_font(), 11)).pack(
                          side='right', padx=(0, 8))
        ctk.CTkButton(actions, text=T('clear_selection_btn'),
                      command=self._clear_selection_in_place,
                      width=62, height=34, corner_radius=CONTROL_RADIUS,
                      fg_color='transparent', border_width=0,
                      hover_color=BG_CARD_HOVER,
                      text_color=TEXT_DIM, font=(ui_font(), 10)).pack(
                          side='right', padx=(0, 4))

        # ── Content area: sidebar + grid ────────────────────────────
        content = ctk.CTkFrame(tab, fg_color=BG_DARK, corner_radius=0)
        content.pack(fill='both', expand=True)

        # The tag sidebar was removed; videos use the full width.
        self._sidebar = None

        # Video grid area
        grid_area = ctk.CTkFrame(content, fg_color=BG_DARK, corner_radius=0)
        grid_area.pack(side='left', fill='both', expand=True)

        self._grid_scroll = ctk.CTkScrollableFrame(
            grid_area, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BORDER_HOVER)
        self._grid_scroll.pack(fill='both', expand=True)

        # ── Floating Pagination bar ─────────────────────────────────
        nav = ctk.CTkFrame(
            tab, fg_color=BG_CARD, corner_radius=CARD_RADIUS,
            border_width=1, border_color=BORDER_CARD, height=48)
        nav.pack(fill='x', padx=16, pady=(4, 14))
        nav.pack_propagate(False)
        self._browse_nav = nav

        nav_inner = ctk.CTkFrame(nav, fg_color='transparent')
        nav_inner.pack(pady=6)

        ctk.CTkButton(nav_inner, text=T('first_page'), width=64, height=30,
                      corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=lambda: self._goto_page(1)).pack(side='left', padx=3)
        ctk.CTkButton(nav_inner, text=T('prev_page'), width=74, height=30,
                      corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=lambda: self._goto_page(self._page - 1)
                      ).pack(side='left', padx=3)
        self._page_lbl = ctk.CTkLabel(nav_inner, text=T('page_n', n=1), text_color=TEXT_PRI,
                                       font=(ui_font(), 12, 'bold'),
                                       width=80)
        self._page_lbl.pack(side='left', padx=10)
        ctk.CTkButton(nav_inner, text=T('next_page'), width=74, height=30,
                      corner_radius=8,
                      fg_color=ACCENT,
                      hover_color=ACCENT_HOVER,
                      text_color=('#FFFFFF', '#FFFFFF'),
                      command=lambda: self._goto_page(self._page + 1)
                      ).pack(side='left', padx=3)

        # Page jump input
        ctk.CTkFrame(nav_inner, width=1, fg_color=BORDER).pack(
            side='left', fill='y', pady=4, padx=10)
        self._page_jump_var = ctk.StringVar(value='')
        page_entry = ctk.CTkEntry(nav_inner, textvariable=self._page_jump_var,
                                   width=50, height=30, corner_radius=8,
                                   fg_color=BG_INPUT, border_color=BORDER,
                                   border_width=1, text_color=TEXT_PRI,
                                   placeholder_text='#',
                                   justify='center')
        page_entry.pack(side='left', padx=3)
        page_entry.bind('<Return>', lambda e: self._jump_to_page())
        ctk.CTkButton(nav_inner, text=T('go_btn'), width=40, height=30,
                      corner_radius=8,
                      fg_color='transparent', border_width=1, border_color=BORDER_HOVER,
                      hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                      command=self._jump_to_page).pack(side='left', padx=3)

        self._rebuild_sidebar()

    # ── Browse logic ─────────────────────────────────────────────────
    def _load_categories(self):
        if self._is_closing:
            return
        if not SITES:
            self._show_no_sites()
            return
        self._show_browse_chrome(True)
        _crumb("load_categories: site=%s" % self._site_key)
        self._page_req += 1
        my_req = self._page_req
        my_gen = self._build_gen
        site_key = self._site_key
        browser = SITES[site_key]['browser']
        self._show_grid_loading(T('browse_loading_site', site=site_key))

        def _fetch():
            failed = False
            try:
                cats = browser.fetch_categories()
            except Exception as exc:
                import traceback
                print(f'[Browse] could not read the sections of {site_key}: '
                      f'{exc!r}\n{traceback.format_exc()}', flush=True)
                failed = True
                cats = []
            if not cats and hasattr(browser, 'HOMEPAGE_SECTIONS'):
                cats = [{'name': name, 'url': url, 'count': 0, 'section': True}
                        for name, url in browser.HOMEPAGE_SECTIONS]

            def _apply():
                nonlocal cats
                if self._is_closing or my_req != self._page_req or my_gen != self._build_gen:
                    return
                cats = [dict(c, name=_section_label(c['name'])) for c in (cats or [])]
                self._categories = cats
                if cats and not failed:
                    self._current_base_url = cats[0]['url']
                    self._page = 1
                    self._last_loaded_page = 1
                    self._has_next = True
                    self._browse_blocked = False
                    self._browse_empty_message = ''
                    self._update_cat_menu([c['name'] for c in cats])
                    self._load_page()
                    return
                if cats:
                    self._current_base_url = cats[0]['url']
                    self._update_cat_menu([c['name'] for c in cats])
                else:
                    self._current_base_url = ''
                    self._cat_menu.configure(values=[])
                    self._cat_var.set('')
                self._videos = []
                self._has_next = False
                self._browse_blocked = False
                self._browse_empty_message = T('category_load_failed')
                self._status_lbl.configure(text=T('category_load_failed'))
                self._refresh_grid()

            self._ui(_apply, gen=my_gen)

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_cat_menu(self, names: list[str]):
        self._cat_menu.configure(values=names)
        if names:
            self._cat_var.set(names[0])

    def _show_grid_loading(self, text):
        """Replace the grid with a clear 'loading' message right away."""
        self._grid_gen += 1          # stops any card building still in progress
        try:
            for w in self._grid_scroll.winfo_children():
                w.destroy()
            self._card_widgets = {}
            ctk.CTkLabel(self._grid_scroll, text=text, text_color=TEXT_SEC,
                         font=(ui_font(), 15, 'bold')).pack(pady=(60, 6))
            ctk.CTkLabel(self._grid_scroll, text=SITES_LOADING_HINT,
                         text_color=TEXT_DIM, font=(ui_font(), 10)).pack()
            self._grid_scroll._parent_canvas.yview_moveto(0)
        except (AttributeError, tk.TclError):
            pass

    def _show_browse_chrome(self, visible):
        """Hide the site picker, search and page buttons while there is no site."""
        for name, side, pady in (
            ('_browse_toolbar', 'top', (14, 4)),
            ('_browse_nav', 'bottom', (4, 14)),
        ):
            widget = getattr(self, name, None)
            if widget is None or not widget.winfo_exists():
                continue
            try:
                if visible and not widget.winfo_manager():
                    widget.pack(fill='x', side=side, padx=16, pady=pady)
                elif not visible and widget.winfo_manager():
                    widget.pack_forget()
            except tk.TclError:
                pass

    def _show_no_sites(self):
        """Browse with nothing in it yet: say what to do and go there."""
        self._show_browse_chrome(False)
        self._grid_gen += 1
        try:
            for widget in self._grid_scroll.winfo_children():
                widget.destroy()
            self._card_widgets = {}
            ctk.CTkLabel(self._grid_scroll, text=T('nosites_title'),
                         text_color=TEXT_PRI,
                         font=(ui_font(), 16, 'bold')).pack(pady=(80, 8))
            ctk.CTkLabel(self._grid_scroll, text=T('nosites_desc'),
                         text_color=TEXT_DIM, font=(ui_font(), 11),
                         wraplength=560, justify='center').pack()
            ctk.CTkButton(self._grid_scroll, text=T('nosites_button'),
                          width=200, height=42, corner_radius=CONTROL_RADIUS,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          text_color=WHITE, font=(ui_font(), 13, 'bold'),
                          command=self._go_add_site).pack(pady=(18, 0))
            self._grid_scroll._parent_canvas.yview_moveto(0)
        except (AttributeError, tk.TclError):
            pass

    def _load_page(self):
        if not self._current_base_url:
            return
        self._show_grid_loading(
            T('browse_loading_page', site=self._site_key, n=self._page))
        if getattr(self, '_status_lbl', None) is not None:
            self._status_lbl.configure(text=T('loading_browse'))
        self._page_req += 1
        my_req = self._page_req
        my_gen = self._build_gen
        site_key = self._site_key
        browser = SITES[site_key]['browser']
        base = self._current_base_url
        page_snapshot = self._page
        url = browser.page_url(base, page_snapshot)

        def _fetch():
            blocked = False
            try:
                data = fetch_page_data(browser, url)
                videos = data.get('videos', [])
                error = data.get('error', '')
            except MirrorsBlockedError:
                blocked = True
                videos = []
                error = ''
            self._ui(
                lambda: self._apply_page(
                    my_req, videos, page_snapshot, blocked, my_gen, error),
                gen=my_gen)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_page(self, req: int, videos: list[dict], page_snapshot: int,
                    blocked: bool = False, gen: int | None = None,
                    error: str = ''):
        if self._is_closing or req != self._page_req:
            return
        if gen is not None and gen != self._build_gen:
            return
        if error:
            self._page = self._last_loaded_page
            self._has_next = False
            if is_unreachable_error(error):
                self._browse_empty_message = T('site_unreachable', site=self._site_key)
            else:
                self._browse_empty_message = f'{T("fetch_error")} · {error[:160]}'
            if page_snapshot <= 1:
                self._videos = []    # new site/category failed: show the error, not old cards
            self._page_lbl.configure(text=T('page_n', n=self._page))
            self._status_lbl.configure(text=self._browse_empty_message)
            self._refresh_grid()     # previous page back (paging) or the error message
            return
        if (videos and page_snapshot > 1 and self._videos
                and [v.get('url') for v in videos] == [v.get('url') for v in self._videos]):
            # The site answered with the same list again: there is no next page
            # (or this site's paging isn't understood) — don't show duplicates.
            print(f'[Browse] page {page_snapshot} repeated page {self._last_loaded_page}; '
                  'treating it as the last page', flush=True)
            videos = []
        if not videos and page_snapshot > 1 and not blocked:
            self._page = self._last_loaded_page
            self._has_next = False
            self._page_lbl.configure(text=T('page_n', n=self._page))
            self._status_lbl.configure(text=T('browse_last_page'))
            self._refresh_grid()     # no more pages: show the last one again
            return
        if self._open_first_section_instead(videos, page_snapshot, blocked):
            return
        self._videos = videos
        self._browse_blocked = blocked
        self._browse_empty_message = (
            f'{T("fetch_error")} · {error[:160]}' if error
            else '')
        if (not videos and not error and not blocked and page_snapshot <= 1
                and getattr(SITES.get(self._site_key, {}).get('browser'),
                            'front_page_empty', False)):
            # Not a failure: the front page of some sites is built for each
            # visitor and is empty for a new one.
            site = SITES.get(self._site_key, {}).get('browser')
            try:
                searchable = bool(site.search_url('a'))
            except Exception:
                searchable = False
            self._browse_empty_message = T(
                'front_page_empty' if searchable else 'front_page_empty_nosearch')
        if (not videos and not error and not blocked and page_snapshot <= 1
                and not self._browse_empty_message):
            # An empty list that is not an error: point at the search box
            # rather than leaving a bare "No videos found".
            site = SITES.get(self._site_key, {}).get('browser')
            try:
                searchable = bool(site.search_url('a'))
            except Exception:
                searchable = False
            if searchable:
                self._browse_empty_message = T('empty_try_search')
        self._has_next = bool(videos)
        if videos:
            self._last_loaded_page = page_snapshot
            self._page = page_snapshot
        _crumb("apply_page: %d videos -> refresh_grid" % len(videos))
        self._refresh_grid()
        _crumb("apply_page: grid refreshed")
        self._page_lbl.configure(text=T('page_n', n=self._page))
        self._status_lbl.configure(
            text=(self._blocked_message() if blocked else
                  self._browse_empty_message or T('status_ready')))

    def _open_first_section_instead(self, videos, page_snapshot, blocked):
        """A site whose front page is only a list of sections shows nothing
        under "Home".  Open its first section instead of an empty screen.

        Done once per site per run, so going back to Home on purpose is
        respected.  Returns True when it moved on to the section.
        """
        if videos or blocked or page_snapshot > 1:
            return False
        cats = self._categories or []
        if len(cats) < 2 or self._cat_var.get() != cats[0]['name']:
            return False
        tried = getattr(self, '_sections_opened_for', None)
        if tried is None:
            tried = self._sections_opened_for = set()
        if self._site_key in tried:
            return False
        tried.add(self._site_key)
        first = cats[1]['name']
        print(f'[Browse] {self._site_key}: the front page shows no videos, '
              f'so opening its first section ({first})', flush=True)
        self._cat_var.set(first)
        self._on_cat_change(first)
        return True

    def _video_version_badge(self, url: str, title: str):
        return None

    def _refresh_grid(self):
        try:
            for w in self._grid_scroll.winfo_children():
                w.destroy()
        except (AttributeError, tk.TclError):
            return
        self._card_widgets = {}
        self._grid_gen += 1
        gen = self._grid_gen
        build_gen = self._build_gen

        if not self._videos:
            if self._browse_blocked:
                msg = self._blocked_message()
            else:
                msg = self._browse_empty_message or T('no_results')
            ctk.CTkLabel(self._grid_scroll, text=msg,
                         text_color=TEXT_DIM,
                         font=(ui_font(), 14)).pack(pady=(40, 12))
            host = self._cf_pass_host()
            if (self._browse_blocked and host
                    and self._blocked_kind() == 'cloudflare'):
                ctk.CTkButton(
                    self._grid_scroll, text=T('cfpass_button', host=host),
                    height=40, corner_radius=CONTROL_RADIUS, fg_color=ACCENT,
                    hover_color=ACCENT_HOVER, text_color=WHITE,
                    font=(ui_font(), 12, 'bold'),
                    command=lambda h=host: self._start_cf_pass(h, reload=True)).pack()
                ctk.CTkLabel(self._grid_scroll, text=T('cfpass_hint'),
                             text_color=TEXT_DIM, font=(ui_font(), 10),
                             wraplength=560, justify='center').pack(pady=(8, 0))
            return

        # Responsive card density: 2 compact / 3 default / 4 wide.
        columns = max(2, self._grid_columns)
        try:
            logical_width = self.winfo_width() / max(self._get_window_scaling(), 1.0)
        except Exception:
            logical_width = self.winfo_width()
        estimated_card_width = max(
            240, int((max(logical_width, 980) - 240) / columns) - 24)
        title_wrap = max(180, min(330, estimated_card_width - 34))
        # Cards are built a few rows at a time so the window stays responsive
        # (building ~50 cards in one go froze the app for ~2 seconds).
        videos = list(self._videos)
        row_holder = [None]
        chunk = max(columns, 2)   # one row at a time

        def _build_card(i, v):
            if i % columns == 0:
                row_holder[0] = ctk.CTkFrame(self._grid_scroll, fg_color='transparent')
                row_holder[0].pack(fill='x', padx=14, pady=7)
            row_frame = row_holder[0]

            url = v.get('url', '')
            title = v.get('title', '')
            dur = v.get('duration', '')
            thumb_url = v.get('thumbnail', '')
            is_sel = url in self._selected_urls

            card = ctk.CTkFrame(row_frame, fg_color=ACCENT_DIM if is_sel else BG_CARD,
                                corner_radius=CARD_RADIUS,
                                border_width=2 if is_sel else 1,
                                border_color=ACCENT if is_sel else BORDER_CARD)
            card.pack(side='left', padx=7, pady=7, fill='x', expand=True)

            # Thumbnail placeholder (16:9)
            thumb_holder = ctk.CTkFrame(card, fg_color=BG_SIDEBAR,
                                         height=_THUMB_SIZE[1], corner_radius=6)
            thumb_holder.pack(fill='x', padx=10, pady=(10, 0))
            thumb_holder.pack_propagate(False)
            thumb_lbl = ctk.CTkLabel(thumb_holder, text=T('loading_browse'),
                                      text_color=TEXT_DIM,
                                      fg_color='transparent',
                                      font=(ui_font(), 11))
            thumb_lbl.pack(expand=True)

            # Duration badge
            if dur:
                dur_lbl = ctk.CTkLabel(thumb_holder, text=f' {dur} ',
                                        text_color='#FFFFFF',
                                        fg_color='#000000',
                                        corner_radius=4,
                                        font=('Consolas', 9, 'bold'))
                dur_lbl.place(relx=1.0, rely=1.0, anchor='se', x=-6, y=-6)

            # Title
            title_text = title[:72] + '...' if len(title) > 72 else title
            title_row = ctk.CTkFrame(card, fg_color='transparent')
            title_row.pack(fill='x', padx=12, pady=(10, 5))
            version_badge = self._video_version_badge(url, title)
            wrap = title_wrap - 44 if version_badge else title_wrap
            if version_badge:
                badge_text, badge_color = version_badge
                ctk.CTkLabel(title_row, text=badge_text,
                             text_color='#FFFFFF', fg_color=badge_color,
                             corner_radius=4, width=34, height=18,
                             font=(ui_font(), 9, 'bold')).pack(
                    side='left', padx=(0, 6), anchor='n')
            ctk.CTkLabel(title_row, text=title_text, text_color=TEXT_PRI,
                         font=(ui_font(), 11),
                         wraplength=wrap, justify='left').pack(
                side='left', fill='x', expand=True, anchor='w')

            # Bottom row
            bottom = ctk.CTkFrame(card, fg_color='transparent')
            bottom.pack(fill='x', padx=12, pady=(0, 12))

            sel_text = ('✓ ' + T('selected')) if is_sel else T('select')
            sel_btn = ctk.CTkButton(
                bottom, text=sel_text, width=76, height=30,
                corner_radius=CONTROL_RADIUS,
                fg_color=ACCENT if is_sel else 'transparent',
                border_width=0 if is_sel else 1,
                border_color=BORDER_HOVER,
                hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                text_color=('#FFFFFF', '#FFFFFF') if is_sel else TEXT_PRI,
                font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10),
                command=lambda u=url: self._toggle_select(u)
            )
            sel_btn.pack(side='right')

            ctk.CTkButton(
                bottom, text=T('preview_browser'), width=112, height=30,
                corner_radius=CONTROL_RADIUS, fg_color='transparent',
                border_width=1, border_color=BORDER_HOVER,
                hover_color=BG_CARD_HOVER, text_color=TEXT_PRI,
                font=(ui_font(), 10),
                command=lambda u=url: self._preview_video(u),
            ).pack(side='right', padx=(0, 6))

            self._card_widgets[url] = {'card': card, 'sel_btn': sel_btn}

            # Clickable card
            def _bind_click(widget, video_url=url):
                widget.bind('<Button-1>', lambda e, u=video_url: self._toggle_select(u))
                widget.configure(cursor='hand2')
            _bind_click(card)
            _bind_click(thumb_holder)
            _bind_click(thumb_lbl)

            # Background thumbnail load
            if thumb_url:
                self._load_thumb_async(
                    thumb_url, thumb_lbl, gen, build_gen, self._site_key)
            else:
                thumb_lbl.configure(text=T('no_thumbnail'))

        def _build_chunk(start):
            if (self._is_closing or gen != self._grid_gen
                    or build_gen != self._build_gen):
                return
            try:
                for index in range(start, min(start + chunk, len(videos))):
                    _build_card(index, videos[index])
                # Lay out these cards now; otherwise all the layout work piles
                # up and runs in one long freeze after the last card.
                self.update_idletasks()
            except tk.TclError:
                return
            if start + chunk < len(videos):
                self.after(15, lambda: _build_chunk(start + chunk))

        _build_chunk(0)

    def _load_thumb_async(self, thumb_url: str, label: ctk.CTkLabel,
                          gen: int, build_gen: int, site_key: str = ''):
        """Fetch thumbnail in a background thread; marshal result back to the
        main thread via .after() so Tk widget updates stay thread-safe.
        The gen counter prevents stale thumbs from polluting a newer page."""
        def _worker():
            if self._is_closing or gen != self._grid_gen or build_gen != self._build_gen:
                return
            img = _fetch_thumbnail(thumb_url, site_key)
            if img is None:
                def _apply_missing():
                    if (self._is_closing or gen != self._grid_gen or
                            build_gen != self._build_gen):
                        return
                    try:
                        if label.winfo_exists():
                            label.configure(text=T('no_thumbnail'), image=None)
                    except Exception:
                        pass
                self._ui(_apply_missing, gen=build_gen)
                return
            # Only apply if this label is still part of the current page.
            def _apply():
                if self._is_closing or gen != self._grid_gen or build_gen != self._build_gen:
                    return
                try:
                    if not label.winfo_exists():
                        return
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img,
                                            size=img.size)
                    label.configure(image=ctk_img, text='')
                    # Keep a reference on the widget so GC doesn't reclaim it
                    label._ctk_img_ref = ctk_img
                except Exception:
                    pass
            self._ui(_apply, gen=build_gen)
        try:
            self._thumb_executor.submit(_worker)
        except RuntimeError:
            pass

    def _preview_video(self, url: str):
        """Preview through the source site's browser player, without queuing."""
        try:
            opened = open_video_preview(url)
        except Exception:
            opened = False
        self._status_lbl.configure(
            text=T('preview_opened' if opened else 'preview_failed'))

    def _toggle_select(self, url: str):
        if url in self._selected_urls:
            self._selected_urls.discard(url)
            self._selected_videos.pop(url, None)
        else:
            self._selected_urls.add(url)
            video = next(
                (item for item in self._videos
                if item.get('url', '') == url),
                {'url': url},
            )
            self._selected_videos[url] = dict(video)
        # Update the specific card in-place (no full grid rebuild)
        w = self._card_widgets.get(url)
        if w:
            is_sel = url in self._selected_urls
            try:
                w['card'].configure(
                    fg_color=ACCENT_DIM if is_sel else BG_CARD,
                    border_width=2 if is_sel else 1,
                    border_color=ACCENT if is_sel else BORDER_CARD)
                w['sel_btn'].configure(
                    text=('✓ ' + T('selected')) if is_sel else T('select'),
                    fg_color=ACCENT if is_sel else 'transparent',
                    border_width=0 if is_sel else 1,
                    hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                    text_color=WHITE if is_sel else TEXT_PRI,
                    font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10))
            except Exception:
                pass
        self._update_selection_count()

    def _update_selection_count(self):
        n = len(self._selected_urls)
        page_selected = sum(
            1 for video in self._videos
            if video.get('url', '') in self._selected_urls)
        self._sel_lbl.configure(
            text=T('selection_count', selected=n, page=page_selected),
            text_color=ACCENT if n else TEXT_SEC)

    def _set_card_selected(self, url: str, is_sel: bool):
        w = self._card_widgets.get(url)
        if not w:
            return
        try:
            w['card'].configure(
                fg_color=ACCENT_DIM if is_sel else BG_CARD,
                border_width=2 if is_sel else 1,
                border_color=ACCENT if is_sel else BORDER_CARD)
            w['sel_btn'].configure(
                text=('✓ ' + T('selected')) if is_sel else T('select'),
                fg_color=ACCENT if is_sel else 'transparent',
                border_width=0 if is_sel else 1,
                hover_color=ACCENT_HOVER if is_sel else BG_CARD_HOVER,
                text_color=WHITE if is_sel else TEXT_PRI,
                font=(ui_font(), 10, 'bold') if is_sel else (ui_font(), 10))
        except Exception:
            pass

    def _clear_selection_in_place(self):
        scan = getattr(self, '_selection_scan_cancel', None)
        if scan is not None:
            scan.set()
        selected = list(self._selected_urls)
        self._selected_urls.clear()
        self._selected_videos.clear()
        for url in selected:
            self._set_card_selected(url, False)
        self._update_selection_count()

    def _goto_page(self, p: int):
        if p < 1:
            return
        if p > self._page and not self._has_next:
            return
        self._page = p
        self._load_page()

    def _jump_to_page(self):
        """Jump to page number entered in the page-jump field."""
        try:
            p = int(self._page_jump_var.get().strip())
            if p >= 1 and not (p > self._page and not self._has_next):
                self._goto_page(p)
        except (ValueError, TypeError):
            pass
        self._page_jump_var.set('')

    def _select_all_on_page(self):
        """Select all videos currently displayed on the page."""
        for v in self._videos:
            url = v.get('url', '')
            if url:
                self._selected_urls.add(url)
                # Assignment refreshes metadata without changing the original
                # insertion order when a selected card is visited again.
                self._selected_videos[url] = dict(v)
                self._set_card_selected(url, True)
        self._update_selection_count()

    def _select_all_results(self):
        """Fetch and select every unique result from the current listing."""
        if self._select_all_running or not self._current_base_url:
            return
        self._select_all_running = True
        site_key = self._site_key
        browser = SITES[site_key]['browser']
        base_url = self._current_base_url
        build_gen = self._build_gen
        cancel = threading.Event()
        self._selection_scan_cancel = cancel

        def _cancelled():
            return (cancel.is_set() or self._is_closing or
                    build_gen != self._build_gen or
                    self._site_key != site_key or
                    self._current_base_url != base_url)

        def _page_url(page):
            return browser.page_url(base_url, page)

        def _worker():
            selected: dict[str, dict] = {}
            page = 1
            reason = ''
            fingerprints = set()
            while not _cancelled():
                try:
                    videos = browser.fetch_page(_page_url(page))
                except MirrorsBlockedError:
                    reason = T('mirrors_blocked')
                    break
                except Exception as exc:
                    print(f'[select all results] page {page}: {exc}', flush=True)
                    reason = T('fetch_error')
                    break
                if not videos:
                    break
                fingerprint = frozenset(
                    str(video.get('url', '')) for video in videos)
                if fingerprint in fingerprints:
                    reason = T('selection_scan_repeated')
                    break
                fingerprints.add(fingerprint)
                before = len(selected)
                for video in videos:
                    url = video.get('url', '')
                    if not url or not M3U8Sites.VaildateUrl(url):
                        continue
                    selected.setdefault(url, dict(video))
                count = len(selected)
                self._ui(lambda p=page, n=count: self._status_lbl.configure(
                    text=T('selecting_all_results', page=p, count=n)),
                    gen=build_gen)
                if len(selected) == before:
                    reason = T('selection_scan_repeated')
                    break
                page += 1
                # Small, cancelable listing pacing; no arbitrary page ceiling.
                for _ in range(3):
                    if _cancelled():
                        break
                    time.sleep(0.1)

            if _cancelled():
                reason = T('selection_scan_cancelled')
            self._select_all_running = False

            def _apply():
                if (self._is_closing or build_gen != self._build_gen or
                        getattr(self, '_selection_scan_cancel', None) is not cancel or
                        self._site_key != site_key or
                        self._current_base_url != base_url):
                    return
                # Clear selection cancels the scan, not merely its display.
                for url, video in (() if cancel.is_set() else selected.items()):
                    self._selected_urls.add(url)
                    self._selected_videos[url] = video
                    self._set_card_selected(url, True)
                self._update_selection_count()
                self._status_lbl.configure(
                    text=(T('selection_all_partial', count=len(selected), reason=reason)
                          if reason else
                          T('selection_all_done', count=len(selected))))

            self._ui(_apply, gen=build_gen)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_site_change(self, val):
        self._site_key = val
        self._search_query = ''
        self._show_search_sort(False)
        self._categories.clear()
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._rebuild_sidebar()
        self._load_categories()

    def _on_cat_change(self, val):
        idx = next((i for i, c in enumerate(self._categories)
                    if c['name'] == val), -1)
        if idx < 0:
            return
        self._search_query = ''
        self._show_search_sort(False)
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._load_page()

    def _search_sorts(self):
        browser = SITES.get(self._site_key, {}).get('browser')
        return [(_section_label(label), value)
                for label, value in (getattr(browser, 'SEARCH_SORTS', []) or [])]

    def _show_search_sort(self, show):
        sorts = self._search_sorts() if show else []
        try:
            if sorts:
                labels = [label for label, _value in sorts]
                self._search_sort_menu.configure(values=labels)
                if self._search_sort_var.get() not in labels:
                    self._search_sort_var.set(labels[0])
                if not self._search_sort_visible:
                    self._search_sort_menu.pack(side='left', padx=(0, 8),
                                                before=self._search_btn)
                    self._search_sort_visible = True
            elif self._search_sort_visible:
                self._search_sort_menu.pack_forget()
                self._search_sort_visible = False
        except (AttributeError, tk.TclError):
            pass

    def _on_search_sort(self, _label):
        if self._search_query:
            self._on_search(query=self._search_query)

    def _on_search(self, query=None):
        q = (query if query is not None else self._search_var.get()).strip()
        if not q:
            return
        if query is None and q != self._search_query:
            # A new search starts with the site's default order.
            self._search_sort_var.set('')
        self._search_query = q
        self._show_search_sort(True)
        sort_value = dict(self._search_sorts()).get(self._search_sort_var.get(), '')
        from urllib.parse import quote
        browser = SITES.get(self._site_key, {}).get('browser')
        # Each site searches at the address it taught us; '' means it never
        # showed us one, and a guess would just re-show the front page.
        found = (browser.search_url(q, sort_value)
                 if hasattr(browser, 'search_url') else '')
        if not found:
            self._browse_empty_message = T('search_not_supported')
            self._show_grid_loading(self._browse_empty_message)
            return
        self._current_base_url = found
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._load_page()

    def _on_tag_click(self, url: str, name: str):
        self._current_base_url = url
        self._page = 1
        self._last_loaded_page = 1
        self._has_next = True
        self._browse_blocked = False
        self._browse_empty_message = ''
        self._selected_urls.clear()
        self._selected_videos.clear()
        self._update_selection_count()
        self._cat_var.set(f'🏷 {name}')
        self._load_page()

    # ── Sidebar ──────────────────────────────────────────────────────
    def _rebuild_sidebar(self):
        if self._sidebar is None:   # tag sidebar removed from Browse
            return
        for w in self._sidebar.winfo_children():
            w.destroy()

        ctk.CTkLabel(self._sidebar, text=T('sidebar_title'),
                     text_color=ACCENT,
                     font=(ui_font(), 14, 'bold')).pack(
            anchor='w', padx=14, pady=(14, 10))

        # Subtle divider
        ctk.CTkFrame(self._sidebar, height=1,
                     fg_color=BORDER).pack(fill='x', padx=8, pady=(0, 6))

        # A site the user added is browsed by its own categories; there is
        # no curated tag list to show.
        ctk.CTkLabel(self._sidebar, text=T('sidebar_no_tags'),
                     text_color=TEXT_DIM,
                     font=(ui_font(), 10)).pack(pady=20)

    def _toggle_group(self, group: str):
        self._sidebar_expanded[group] = not self._sidebar_expanded.get(group, False)
        self._rebuild_sidebar()

    # ── Download actions ─────────────────────────────────────────────
    def _review_selected(self, start_download: bool = False):
        ordered = list(self._selected_videos) or list(self._selected_urls)
        if not ordered:
            self._status_lbl.configure(text=T('selection_preview_empty'))
            return
        popup = ctk.CTkToplevel(self)
        popup.title(T('selection_preview_title'))
        popup.geometry('760x620')
        popup.minsize(620, 460)
        popup.transient(self)
        popup.configure(fg_color=BG_DARK)

        header = ctk.CTkFrame(popup, fg_color=BG_SECTION, corner_radius=0)
        header.pack(fill='x')
        ctk.CTkLabel(
            header, text=T('selection_preview_title'), text_color=TEXT_PRI,
            font=(ui_font(), 17, 'bold')).pack(
                anchor='w', padx=20, pady=(16, 2))
        ctk.CTkLabel(
            header, text=T('selection_preview_desc', count=len(ordered)),
            text_color=TEXT_DIM, font=(ui_font(), 10)).pack(
                anchor='w', padx=20, pady=(0, 14))

        options = ctk.CTkFrame(popup, fg_color=BG_CARD)
        options.pack(fill='x', padx=16, pady=12)
        resolution_var = ctk.StringVar(value=self._resolution_label())
        template_var = ctk.StringVar(value=config.get_filename_template())
        ctk.CTkLabel(
            options, text=T('selection_preview_resolution'),
            text_color=TEXT_SEC, font=(ui_font(), 10, 'bold')).grid(
                row=0, column=0, padx=(14, 8), pady=12, sticky='w')
        ctk.CTkOptionMenu(
            options, values=self._resolution_values(),
            variable=resolution_var, width=140, height=32,
            fg_color=BG_INPUT, button_color=BORDER_HOVER,
            button_hover_color=ACCENT,
            dropdown_fg_color=BG_CARD).grid(
                row=0, column=1, padx=(0, 18), pady=12, sticky='w')
        ctk.CTkLabel(
            options, text=T('selection_preview_template'),
            text_color=TEXT_SEC, font=(ui_font(), 10, 'bold')).grid(
                row=0, column=2, padx=(0, 8), pady=12, sticky='w')
        template_entry = ctk.CTkEntry(
            options, textvariable=template_var, height=32,
            fg_color=BG_INPUT, border_color=BORDER,
            text_color=TEXT_PRI)
        template_entry.grid(
            row=0, column=3, padx=(0, 14), pady=12, sticky='ew')
        options.grid_columnconfigure(3, weight=1)

        listing = ctk.CTkScrollableFrame(
            popup, fg_color=BG_DARK, corner_radius=0,
            scrollbar_button_color=BORDER)
        listing.pack(fill='both', expand=True, padx=16)
        choices = {
            url: ctk.BooleanVar(value=True) for url in ordered
        }
        for url in ordered[:200]:
            video = self._selected_videos.get(url, {})
            enabled = choices[url]
            row = ctk.CTkFrame(
                listing, fg_color=BG_CARD, corner_radius=8,
                border_width=1, border_color=BORDER_CARD)
            row.pack(fill='x', pady=4)
            ctk.CTkCheckBox(
                row, text='', variable=enabled, width=24,
                fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(
                    side='left', padx=(12, 6), pady=10)
            labels = ctk.CTkFrame(row, fg_color='transparent')
            labels.pack(side='left', fill='x', expand=True, pady=8)
            title = str(video.get('title') or url.rstrip('/').split('/')[-1])
            ctk.CTkLabel(
                labels, text=title, text_color=TEXT_PRI,
                font=(ui_font(), 10, 'bold'), anchor='w').pack(fill='x')
            ctk.CTkLabel(
                labels,
                text=f'{site_name(url)} · {video_code(url, title)} · {url}',
                text_color=TEXT_DIM, font=('Consolas', 8),
                anchor='w').pack(fill='x', pady=(2, 0))
        if len(ordered) > 200:
            ctk.CTkLabel(
                listing,
                text=T('selection_preview_more', count=len(ordered) - 200),
                text_color=TEXT_DIM, font=(ui_font(), 10)).pack(
                    anchor='w', padx=12, pady=10)

        footer = ctk.CTkFrame(popup, fg_color=BG_HEADER, corner_radius=0)
        footer.pack(fill='x', pady=(12, 0))

        def _commit(download):
            keep = {url for url, variable in choices.items() if variable.get()}
            for url in list(self._selected_urls):
                if url not in keep:
                    self._selected_urls.discard(url)
                    self._selected_videos.pop(url, None)
            if not keep:
                popup.destroy()
                self._update_selection_count()
                return
            if download and not self._preflight_download_destination():
                return
            resolution = self._resolution_pref_from_label(
                resolution_var.get())
            template = config.normalize_filename_template(
                template_var.get())
            due = next_schedule_epoch(config.get_download_schedule())
            if download:
                self._download_selected(
                    resolution, template, not_before=due)
            else:
                self._add_selected_to_queue(resolution, template)
            popup.destroy()

        ctk.CTkButton(
            footer, text=T('selection_preview_cancel'), width=96,
            height=36, fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_SEC, command=popup.destroy).pack(
                side='left', padx=16, pady=12)
        secondary_text = (
            T('selection_preview_add') if start_download
            else T('selection_preview_download'))
        secondary_action = (False if start_download else True)
        ctk.CTkButton(
            footer, text=secondary_text, width=132, height=36,
            fg_color='transparent', border_width=1,
            border_color=BORDER_HOVER, hover_color=BG_CARD_HOVER,
            text_color=TEXT_PRI,
            command=lambda: _commit(secondary_action)).pack(
                side='right', padx=(0, 8), pady=12)
        primary_text = (
            T('selection_preview_download') if start_download
            else T('selection_preview_add'))
        ctk.CTkButton(
            footer, text=primary_text, width=142, height=36,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=WHITE,
            command=lambda: _commit(start_download)).pack(
                side='right', padx=(0, 8), pady=12)
        popup.grab_set()
        popup.focus_force()

    def _preflight_download_destination(self) -> bool:
        minimum = config.get_minimum_free_gb()
        result = storage_preflight(
            self._dest_var.get() or 'download',
            minimum_free_bytes=int(minimum * 1024 ** 3))
        if result.ok:
            config.set_download_directory(result.path)
            return True
        if result.error == 'low_space':
            message = T(
                'disk_low_space', free=f'{result.free_bytes / 1024 ** 3:.2f}',
                minimum=f'{minimum:.2f}')
        else:
            message = T('disk_preflight_failed', error=result.error)
        self._status_lbl.configure(text=message)
        messagebox.showerror(T('open_folder_failed_title'), message)
        return False

    def _queue_selected(
            self, *, start_download: bool, resolution: str = '',
            filename_template: str = '', not_before: float = 0):
        dest = self._dest_var.get() or 'download'
        requested = added = duplicates = unsupported = started = 0
        ordered = list(self._selected_videos) or list(self._selected_urls)
        for url in ordered:
            requested += 1
            if M3U8Sites.VaildateUrl(url):
                video = self._selected_videos.get(url, {})
                contains = getattr(self._dlmgr, 'contains', None)
                existed = bool(contains(url)) if callable(contains) else False
                self._dlmgr.add_item(
                    url, name=str(video.get('title') or ''),
                    state='等待中', dest=dest, resolution=resolution,
                    filename_template=filename_template,
                    thumbnail=str(video.get('thumbnail') or ''),
                    site=self._site_key)
                if existed:
                    duplicates += 1
                else:
                    added += 1
                if start_download:
                    try:
                        accepted = self._dlmgr.enqueue(
                            url, dest, not_before=not_before)
                    except TypeError:
                        accepted = self._dlmgr.enqueue(url, dest)
                    if accepted is not False:
                        started += 1
            else:
                unsupported += 1
                print(f'[queue] unsupported selected URL: {url}')
        self._clear_selection_in_place()
        return QueueAddSummary(
            requested=requested, added=added, duplicates=duplicates,
            unsupported=unsupported, started=started)

    def _show_queue_summary(self, summary: QueueAddSummary, started=False):
        key = 'queue_started_summary' if started else 'queue_summary'
        text = T(
            key, added=summary.added, started=summary.started,
            duplicates=summary.duplicates,
            unsupported=summary.unsupported)
        label = getattr(self, '_status_lbl', None)
        if label is not None:
            try:
                label.configure(text=text)
            except Exception:
                pass
        print(text, flush=True)

    def _download_url(self):
        url = self._dl_url_var.get().strip()
        if not url:
            return
        if not self._preflight_download_destination():
            return
        resolution = config.get_resolution_pref()
        filename_template = config.get_filename_template()
        due = next_schedule_epoch(config.get_download_schedule())
        # Direct video URL
        if M3U8Sites.VaildateUrl(url):
            dest = self._dest_var.get() or 'download'
            self._dlmgr.add_item(
                url, state='等待中', dest=dest, resolution=resolution,
                filename_template=filename_template)
            self._dlmgr.enqueue(url, dest, not_before=due)
            self._dl_url_var.set('')
            return
        # Listing / actress / category URL — crawl all videos
        if self._is_listing_url(url):
            self._dl_url_var.set('')
            self._status_lbl.configure(text=T('crawling_url'))
            dest = self._dest_var.get() or 'download'
            threading.Thread(
                target=self._crawl_listing,
                args=(url, dest, resolution, filename_template, due),
                daemon=True).start()
            return
        self._status_lbl.configure(text=T('url_not_supported'))
        print(T('url_not_supported') + f': {url}')

    def _is_listing_url(self, url: str) -> bool:
        """A page that lists videos, rather than one video's own page.

        Each site answers for itself, from the layout it taught us when it
        was added."""
        name, browser = _kvs_browser_for_url(url)
        if not name:
            return False
        if hasattr(browser, 'is_video_url'):
            return not browser.is_video_url(url)
        return '/videos/' not in urlsplit(url).path

    def _crawl_listing(
            self, url: str, dest: str, resolution: str = '',
            filename_template: str = '', not_before: float = 0):
        """Crawl a listing URL across all pages; add every video to the queue."""
        gen = self._build_gen
        seen: set[str] = set()
        kvs_name, kvs_browser = _kvs_browser_for_url(url)
        epoch = self._dlmgr._cancel_epoch
        fingerprints = set()
        reason = ''
        page = 1

        def _cancelled():
            return (self._is_closing or gen != self._build_gen or
                    epoch != self._dlmgr._cancel_epoch)

        while not _cancelled():
            try:
                if kvs_browser is None:
                    break
                page_url = kvs_browser.page_url(url, page)
                videos = kvs_browser.fetch_page(page_url)
            except MirrorsBlockedError as e:
                print(f'[crawl] page {page} blocked: {e}')
                reason = T('mirrors_blocked')
                break
            except Exception as e:
                print(f'[crawl] page {page} error: {e}')
                reason = T('fetch_error')
                break

            if _cancelled():
                break
            if not videos:
                if page == 1:
                    print(f'[crawl] No videos found on first page: {url}')
                break
            fingerprint = frozenset(str(v.get('url', '')) for v in videos)
            if fingerprint in fingerprints:
                reason = T('selection_scan_repeated')
                break
            fingerprints.add(fingerprint)

            new_count = 0
            for v in videos:
                if _cancelled():
                    break
                video_url = v.get('url', '')
                if video_url and video_url not in seen and M3U8Sites.VaildateUrl(video_url):
                    seen.add(video_url)
                    new_count += 1
                    name = v.get('title', '')
                    candidate = dict(v)
                    candidate['_site'] = kvs_name or ''
                    candidate['_source_listing_url'] = url
                    self._dlmgr.add_item(
                        video_url, name=name, state='等待中', dest=dest,
                        resolution=resolution,
                        filename_template=filename_template,
                        thumbnail=str(v.get('thumbnail') or ''),
                        site=candidate['_site'])
                    self._dlmgr.enqueue(
                        video_url, dest, not_before=not_before)

            if new_count == 0:
                reason = T('selection_scan_repeated')
                break  # No new videos on this page, stop

            self._ui(lambda n=len(seen): self._status_lbl.configure(
                text=T('crawling_url') + f' ({n})'), gen=gen)
            page += 1
            for _ in range(3):
                if _cancelled():
                    break
                time.sleep(0.1)

        n = len(seen)
        if _cancelled():
            reason = T('selection_scan_cancelled')
        self._ui(lambda: self._status_lbl.configure(
            text=(T('selection_all_partial', count=n, reason=reason)
                  if reason else T('crawl_added', n=n))), gen=gen)

    def _download_all(self):
        if not self._preflight_download_destination():
            return
        resolution = config.get_resolution_pref()
        filename_template = config.get_filename_template()
        due = next_schedule_epoch(config.get_download_schedule())
        # If the URL field has a listing URL, crawl it first
        url = self._dl_url_var.get().strip()
        if url:
            if M3U8Sites.VaildateUrl(url):
                dest = self._dest_var.get() or 'download'
                self._dlmgr.add_item(
                    url, state='等待中', dest=dest, resolution=resolution,
                    filename_template=filename_template)
                self._dlmgr.enqueue(url, dest, not_before=due)
                self._dl_url_var.set('')
            elif self._is_listing_url(url):
                self._dl_url_var.set('')
                self._status_lbl.configure(text=T('crawling_url'))
                dest = self._dest_var.get() or 'download'
                threading.Thread(
                    target=self._crawl_listing,
                    args=(url, dest, resolution, filename_template, due),
                    daemon=True).start()
                return
        dest = self._dest_var.get() or 'download'
        count = 0
        for item in self._dlmgr.get_items():
            # Local file rows are not downloads.
            if item.local:
                continue
            # Skip items that are already active or completed; queued ('等待中')
            # items still need enqueue() to (re)start them.
            if item.state in ('已下載', '下載中', '準備中', '已存在'):
                continue
            if self._dlmgr.enqueue(
                    item.url, item.dest or dest, not_before=due):
                count += 1
        if count:
            print(f'Added {count} download tasks')

    def _import_urls(self, urls) -> QueueAddSummary:
        """Put a list of addresses into the queue, and say what happened.

        An address already in the list is not simply ignored: one that
        stopped (paused, cancelled, failed) is started again, which is what
        importing the same list twice is usually meant to do.  Nothing ever
        happens silently — the result is always shown.
        """
        dest = self._dest_var.get() or 'download'
        due = next_schedule_epoch(config.get_download_schedule())
        requested = added = requeued = waiting = finished = unsupported = 0
        skipped = []
        for url in urls:
            requested += 1
            if not M3U8Sites.VaildateUrl(url):
                unsupported += 1
                skipped.append(url)
                continue
            existing = next((item for item in self._dlmgr.get_items()
                             if item.url == url), None)
            if existing is not None:
                if existing.state in DONE_STATES:
                    finished += 1
                    continue
                if existing.state in ACTIVE_STATES or existing.state in QUEUED_STATES:
                    waiting += 1
                    continue
                # Paused, cancelled or failed: start it again.
                if self._dlmgr.enqueue(url, existing.dest or dest, not_before=due):
                    requeued += 1
                else:
                    waiting += 1
                continue
            self._dlmgr.add_item(
                url, state='等待中', dest=dest,
                resolution=config.get_resolution_pref(),
                filename_template=config.get_filename_template(),
                site=site_name(url))
            # Put it in the real queue straight away so it gets a queue
            # position (▲ n ▼) and starts when a slot is free.
            self._dlmgr.enqueue(url, dest, not_before=due)
            added += 1
        summary = QueueAddSummary(
            requested=requested, added=added,
            duplicates=waiting + finished, unsupported=unsupported)
        report = T('import_report', requested=requested, added=added,
                   requeued=requeued, waiting=waiting, finished=finished,
                   unsupported=unsupported)
        if skipped:
            hosts = sorted({(urlsplit(u).hostname or u).replace('www.', '')
                            for u in skipped})
            print('[import] not added as a site yet: ' + ', '.join(hosts[:10]),
                  flush=True)
            report += '\n\n' + T('import_unsupported_hint',
                                  hosts=', '.join(hosts[:6]))
        self._status_lbl.configure(text=T(
            'import_complete', added=added + requeued,
            duplicates=waiting + finished, unsupported=unsupported))
        self._refresh_downloads(schedule=False)
        messagebox.showinfo(T('import_urls'), report)
        return summary

    def _import_urls_file(self):
        path = filedialog.askopenfilename(filetypes=[
            ('URL files', '*.txt *.csv *.json *.text *.log'),
            ('All files', '*.*'),
        ])
        if not path:
            return
        try:
            urls = load_url_file(path)
        except Exception as exc:
            print(f'[import] {path}: {exc}', flush=True)
            messagebox.showerror(T('import_failed'), f'{exc}')
            return
        if not urls:
            messagebox.showinfo(T('import_failed'), T('import_no_urls'))
            return
        self._import_urls(urls)

    def _paste_urls(self):
        try:
            text = self.clipboard_get()
        except tk.TclError as exc:
            messagebox.showerror(T('import_failed'), str(exc))
            return
        self._import_urls(extract_urls(text))

    def _export_queue(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.csv',
            filetypes=[('CSV', '*.csv'), ('JSON', '*.json')],
            initialfile='siphon-downloads.csv')
        if not path:
            return
        try:
            export_items(self._dlmgr.get_items(), path)
            self._status_lbl.configure(text=T('export_complete'))
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror(T('export_failed'), str(exc))
