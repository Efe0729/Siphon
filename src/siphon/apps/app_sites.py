"""Adding, ordering, reporting and teaching the sites the person added."""

import re
import threading
import tkinter as tk
import webbrowser
import customtkinter as ctk

from tkinter import filedialog, messagebox
from urllib.parse import urlsplit
from siphon.core import config
from siphon.i18n.locales import T, ui_font
from siphon.ui.theme import (
    ACCENT,
    BG_CARD_HOVER,
    BG_DARK,
    BG_INPUT,
    BORDER_HOVER,
    CONTROL_RADIUS,
    ERROR_C,
    SUCCESS,
    TEXT_DIM,
    TEXT_PRI,
    WARNING)
from siphon.apps.app_basics import (
    _learned_report,
    builtin_browser_for_host,
    register_user_sites,
    site_catalog)
from siphon.apps.file_actions import (
    _open_folder)


class SitesMixin:
    """Adding, ordering, reporting and teaching the sites the person added."""

    def _go_add_site(self):
        """Open Settings with the cursor already in the "add a site" box."""
        self._select_tab('settings')
        picker = getattr(self, '_site_pick', None)
        if picker is not None and picker.winfo_exists():
            self._site_pick_var.set(T('mysites_new'))
            self._on_site_pick(T('mysites_new'))
        entry = getattr(self, '_mysite_entry', None)
        if entry is not None and entry.winfo_exists():
            try:
                entry.master.master._parent_canvas.yview_moveto(1.0)
            except (AttributeError, tk.TclError):
                pass
            entry.focus_set()

    # ── My own sites ────────────────────────────────────────────────
    def _site_entries(self):
        return site_catalog()

    def _picked_site(self):
        """The site chosen in the picker, or None for "+ add new"."""
        name = self._site_pick_var.get()
        if name == T('mysites_new'):
            return None
        for entry in self._site_entries():
            if entry['name'] == name:
                return entry
        return None

    def _refresh_site_picker(self, keep=''):
        """Redraw the picker and the buttons beside it."""
        if getattr(self, '_site_pick', None) is None or not self._site_pick.winfo_exists():
            return
        entries = self._site_entries()
        labels = [T('mysites_new')] + [
            (entry['name'] if not entry['hidden']
             else T('mysites_off_item', name=entry['name']))
            for entry in entries]
        self._site_pick.configure(values=labels)
        wanted = keep or self._site_pick_var.get()
        if wanted not in labels:
            wanted = T('mysites_new')
        self._site_pick_var.set(wanted)
        self._on_site_pick(wanted)

    def _on_site_pick(self, choice):
        """Show either the address box or the buttons for the chosen site."""
        adding = choice == T('mysites_new')
        name = '' if adding else re.sub(r'\s*\(.*\)$', '', choice)
        entry = None
        for candidate in self._site_entries():
            if candidate['name'] == name:
                entry = candidate
                break
        row = getattr(self, '_mysite_add_row', None)
        if row is not None and row.winfo_exists():
            if adding and not row.winfo_manager():
                row.pack(fill='x', padx=20, pady=(10, 2), before=self._mysite_status)
            elif not adding and row.winfo_manager():
                row.pack_forget()
        for button in (self._site_up_btn, self._site_down_btn,
                       self._site_toggle_btn, self._site_del_btn,
                       self._site_report_btn):
            if button.winfo_exists():
                button.configure(state='disabled' if entry is None else 'normal')
        if entry is None:
            self._set_mysite_status('')
            return
        self._site_toggle_btn.configure(
            text=T('mysites_show') if entry['hidden'] else T('mysites_hide'))
        where = T('mysites_site_known') if entry['builtin'] else T('mysites_site_general')
        state = T('mysites_state_off') if entry['hidden'] else T('mysites_state_on')
        line = f"{where} · {state}"
        # The app noticed this site failing, learned it again by itself, and
        # that did not help either.  Say so here, where the user is already
        # looking at the site.
        from siphon.sites import health
        if health.needs_report(entry.get('host', '')):
            line += ' · ' + T('mysites_needs_report')
        self._set_mysite_status(line)

    def _move_site(self, step):
        """Move the chosen site up or down in the Browse list."""
        entry = self._picked_site()
        if entry is None:
            return
        names = [item['name'] for item in self._site_entries()]
        index = names.index(entry['name'])
        target = index + step
        if not 0 <= target < len(names):
            return
        names[index], names[target] = names[target], names[index]
        config.set_site_order(names)
        self._refresh_site_menu()
        self._refresh_site_picker(keep=self._site_pick_var.get())
        self._set_mysite_status(T('mysites_moved', name=entry['name'],
                                  place=target + 1), SUCCESS)

    def _toggle_site(self):
        """Switch a site off (hidden from Browse) or back on."""
        entry = self._picked_site()
        if entry is None:
            return
        config.set_site_hidden(entry['name'], not entry['hidden'])
        self._refresh_site_menu()
        label = (entry['name'] if entry['hidden']
                 else T('mysites_off_item', name=entry['name']))
        self._refresh_site_picker(keep=label)
        self._set_mysite_status(
            T('mysites_turned_on' if entry['hidden'] else 'mysites_turned_off',
              name=entry['name']), SUCCESS)

    def _remove_picked_site(self):
        """Remove a site the user added; a built-in one is only switched off."""
        entry = self._picked_site()
        if entry is None:
            return
        if not messagebox.askyesno(T('mysites_remove'),
                                   T('mysites_remove_confirm', name=entry['name'])):
            return
        for site in config.get_custom_sites():
            known_name, _known = builtin_browser_for_host(site['host'])
            if entry['name'] in ((site.get('name') or site['host']), known_name):
                config.remove_custom_site(site['host'])
        config.set_site_hidden(entry['name'], False)
        self._refresh_site_menu()
        self._refresh_site_picker(keep=T('mysites_new'))
        self._set_mysite_status(T('mysites_removed', name=entry['name']), SUCCESS)

    def _refresh_site_menu(self):
        """Keep the Browse tab's site list in step with Settings."""
        names = register_user_sites()
        menu = getattr(self, '_site_menu', None)
        if menu is None or not menu.winfo_exists():
            return
        if not names:
            self._show_no_sites()
            return
        self._show_browse_chrome(True)
        menu.configure(values=names)
        if self._site_key not in names:
            self._on_site_change(names[0])

    def _set_mysite_status(self, text, color=None):
        label = getattr(self, '_mysite_status', None)
        if label is not None and label.winfo_exists():
            label.configure(text=text, text_color=color or TEXT_DIM)

    def _test_custom_site(self):
        """Add every address in the box: one, or a whole list at once."""
        from siphon.sites.generic import normalize_site_url
        raw = self._mysite_var.get() or ''
        wanted = [part for part in re.split(r'[\s,;]+', raw.strip()) if part]
        wanted = [part for part in wanted if normalize_site_url(part)]
        if not wanted:
            self._set_mysite_status(T('mysites_bad_url'), ERROR_C)
            return
        self._add_queue = wanted[1:]
        self._add_done, self._add_failed = [], []
        self._add_one(wanted[0])

    def _add_one(self, url):
        """Add a single address: instantly when this app knows the site,
        otherwise by opening it and looking for a video."""
        from siphon.sites.generic import normalize_site_url
        self._adding_url = url
        host = (urlsplit(normalize_site_url(url)).hostname or '').lower()
        known_name, known = builtin_browser_for_host(host)
        if known is not None:
            self._custom_site_done({'host': re.sub(r'^www\.', '', host),
                                    'title': '', 'kind': '', 'count': 0,
                                    'engine': '', 'engine_label': '',
                                    'root': f'https://{host}'}, '')
            return
        button = getattr(self, '_mysite_btn', None)
        if button is not None and button.winfo_exists():
            button.configure(state='disabled')
        left = len(getattr(self, '_add_queue', []) or [])
        self._set_mysite_status(
            T('mysites_testing_one', host=host, left=left) if left
            else T('mysites_testing'))

        def work():
            from siphon.sites import generic
            try:
                result = generic.probe(url)
            except generic.SiteUnreachableError as exc:
                # The site never answered, so there was no page to look in:
                # the reason the user needs is their connection, not the page.
                self._ui(lambda e=exc: self._custom_site_done(
                    None, str(e), unreachable=True))
                return
            except Exception as exc:
                self._ui(lambda e=exc: self._custom_site_done(None, str(e)))
                return
            self._ui(lambda r=result: self._custom_site_done(r, ''))

        threading.Thread(target=work, daemon=True).start()

    def _show_site_report(self, host, result, error='', prebuilt=None):
        """The report window: read it, then open an issue or copy it.

        Both buttons, because the choice is the user's.  A GitHub issue is
        public and gets the fault fixed; the Copy button is for anyone who
        would rather not post the address of a site they visit on a public
        page, and the window says so plainly rather than in small print.
        """
        from siphon.core import sitereport
        title, body = prebuilt or sitereport.build(host, result, error)

        popup = tk.Toplevel(self)
        popup.title(T('report_title'))
        popup.transient(self)
        idx = 0 if ctk.get_appearance_mode() == 'Light' else 1

        def C(token):
            return token[idx] if isinstance(token, (tuple, list)) else token

        popup.configure(bg=C(BG_DARK))
        ctk.CTkLabel(popup, text=T('report_heading', host=host),
                     text_color=TEXT_PRI, font=(ui_font(), 14, 'bold'),
                     anchor='w', justify='left').pack(
                         fill='x', padx=20, pady=(18, 2))
        ctk.CTkLabel(popup, text=T('report_public_warning'), text_color=WARNING,
                     font=(ui_font(), 11), anchor='w', justify='left',
                     wraplength=560).pack(fill='x', padx=20, pady=(0, 10))

        box = ctk.CTkTextbox(popup, width=580, height=300, wrap='word',
                             fg_color=BG_INPUT, text_color=TEXT_PRI,
                             font=('Consolas', 11))
        box.pack(fill='both', expand=True, padx=20)

        note = ctk.CTkLabel(popup, text='', text_color=SUCCESS,
                            font=(ui_font(), 11))

        # The log is where the addresses tried and the reason each was
        # refused are written down, which is most of what makes a report
        # useful.  It is off by default and shown in full above before
        # anything is sent: nobody should find out afterwards what they
        # handed over.
        with_log = ctk.BooleanVar(value=False)

        def report_text():
            text = sitereport.with_log(body, host) if with_log.get() else body
            return f'{title}\n\n{text}'

        def redraw(*_args):
            box.configure(state='normal')
            box.delete('1.0', 'end')
            box.insert('1.0', report_text())
            box.configure(state='disabled')
            note.configure(text='')

        redraw()

        ctk.CTkCheckBox(popup, text=T('report_with_log'), variable=with_log,
                        command=redraw, text_color=TEXT_PRI,
                        font=(ui_font(), 11), checkbox_width=18,
                        checkbox_height=18).pack(
                            anchor='w', padx=20, pady=(8, 0))
        note.pack(pady=(6, 0))

        buttons = ctk.CTkFrame(popup, fg_color='transparent')
        buttons.pack(fill='x', padx=20, pady=(8, 18))

        def copy():
            try:
                self.clipboard_clear()
                self.clipboard_append(report_text())
                note.configure(text=T('report_copied'))
            except tk.TclError:
                pass

        def open_issue():
            webbrowser.open(sitereport.issue_url(title, report_text()))
            note.configure(text=T('report_opened'))

        def send_mail():
            text = report_text()
            address = sitereport.mail_url(title, text)
            if not address:
                note.configure(text=T('report_no_mail'))
                return
            # A long report does not fit in a web address, so the clipboard
            # carries the whole of it and the page carries as much as it can:
            # the person pastes over what arrives there.
            if sitereport.mail_is_cut_short(text):
                copy()
            if not webbrowser.open(address):
                copy()
                note.configure(
                    text=T('report_mail_none',
                           address=sitereport.contact_email()),
                    text_color=WARNING)
                return
            note.configure(
                text=T('report_mail_long' if sitereport.mail_is_cut_short(text)
                       else 'report_mail_opened'),
                text_color=WARNING if sitereport.mail_is_cut_short(text)
                else SUCCESS)

        def open_log_folder():
            folder = sitereport.log_folder()
            if not folder:
                note.configure(text=T('report_no_log'))
                return
            _open_folder(folder)
            note.configure(text=T('report_log_folder_opened'))

        ctk.CTkButton(buttons, text=T('report_open_github'), height=36,
                      corner_radius=CONTROL_RADIUS, fg_color=ACCENT,
                      command=open_issue).pack(side='left')
        if sitereport.mail_url('x', 'y'):
            ctk.CTkButton(buttons, text=T('report_mail'), height=36, width=120,
                          corner_radius=CONTROL_RADIUS, fg_color='transparent',
                          border_width=1, border_color=BORDER_HOVER,
                          text_color=TEXT_PRI, hover_color=BG_CARD_HOVER,
                          command=send_mail).pack(side='left', padx=(8, 0))
        ctk.CTkButton(buttons, text=T('report_open_log'), height=36, width=140,
                      corner_radius=CONTROL_RADIUS, fg_color='transparent',
                      border_width=1, border_color=BORDER_HOVER,
                      text_color=TEXT_PRI, hover_color=BG_CARD_HOVER,
                      command=open_log_folder).pack(side='left', padx=(8, 0))
        ctk.CTkButton(buttons, text=T('report_copy'), height=36, width=120,
                      corner_radius=CONTROL_RADIUS, fg_color='transparent',
                      border_width=1, border_color=BORDER_HOVER,
                      text_color=TEXT_PRI, hover_color=BG_CARD_HOVER,
                      command=copy).pack(side='left', padx=8)
        ctk.CTkButton(buttons, text=T('report_close'), height=36, width=100,
                      corner_radius=CONTROL_RADIUS, fg_color='transparent',
                      border_width=1, border_color=BORDER_HOVER,
                      text_color=TEXT_DIM, hover_color=BG_CARD_HOVER,
                      command=popup.destroy).pack(side='right')
        return popup

    def _report_added_site(self):
        """Report the site that was just checked, from the result on screen."""
        self._show_site_report(getattr(self, '_report_host', ''),
                               getattr(self, '_report_result', None),
                               getattr(self, '_report_error', ''))

    def _offer_teaching(self, host, needed):
        """Show the "save the page and upload it" row when it would help."""
        row = getattr(self, '_mysite_teach_row', None)
        if row is None or not row.winfo_exists():
            return
        try:
            if host and needed:
                if not row.winfo_manager():
                    row.pack(fill='x', padx=20, pady=(0, 10))
            elif row.winfo_manager():
                row.pack_forget()
        except tk.TclError:
            pass

    def _offer_report(self, host, result, error=''):
        """Show the report row when the check found a fault, hide it when not."""
        row = getattr(self, '_mysite_report_row', None)
        if row is None or not row.winfo_exists():
            return
        from siphon.core import sitereport
        problem = sitereport.diagnose(result) if result else (error and 'unreadable')
        self._report_host, self._report_result, self._report_error = (
            host, result, error)
        try:
            if host and problem:
                self._mysite_report_note.configure(text=T('report_offer'))
                if not row.winfo_manager():
                    row.pack(fill='x', padx=20, pady=(2, 10))
            elif row.winfo_manager():
                row.pack_forget()
        except tk.TclError:
            pass

    def _report_picked_site(self):
        """Report a site from the list, checking it again first.

        A site in the list broke at some point after it was added, so what was
        saved then describes a layout that no longer exists.  The report is
        worth only as much as the reading behind it, so the site is read again
        and the fresh finding is what gets sent.
        """
        entry = self._picked_site()
        if entry is None:
            return
        host = entry.get('host') or ''
        if not host:
            return
        self._set_mysite_status(T('report_rechecking', host=host))

        def work():
            from siphon.sites import generic
            from siphon.core import sitereport
            try:
                fresh = generic.probe(f'https://{host}/')
            except Exception as exc:
                print(f'[report] {host}: fresh check failed: {exc}', flush=True)
                saved = config.get_site_profile(host)
                built = sitereport.report_for_profile(host, saved)
                self._ui(lambda b=built: (
                    self._set_mysite_status(''),
                    self._show_site_report(host, None, prebuilt=b)))
                return
            self._ui(lambda r=fresh: (self._set_mysite_status(''),
                                      self._show_site_report(host, r)))

        threading.Thread(target=work, daemon=True).start()

    def _offer_search_box(self, host):
        """Show the "paste the search address" row, for this host only."""
        row = getattr(self, '_mysite_search_row', None)
        if row is None or not row.winfo_exists():
            return
        self._mysite_search_host = host
        try:
            if host:
                self._mysite_search_var.set('')
                row.pack(fill='x', padx=20, pady=(2, 10))
            else:
                row.pack_forget()
        except tk.TclError:
            pass

    def _save_typed_search(self):
        """Keep a search address the user pasted, as a {query} template.

        They searched for something on the site and copied the address, so
        the word they used is in it: whatever they typed is replaced by the
        placeholder, and the site can be searched from Browse afterwards.
        """
        from siphon.sites import generic
        host = getattr(self, '_mysite_search_host', '')
        typed = (self._mysite_search_var.get() or '').strip()
        if not host or not typed.startswith('http'):
            self._set_mysite_status(T('mysites_search_bad'), ERROR_C)
            return
        template = generic.search_template_from(typed)
        if not template:
            self._set_mysite_status(T('mysites_search_bad'), ERROR_C)
            return
        profile = config.get_site_profile(host)
        profile['search'] = template
        config.set_site_profile(host, profile)
        self._offer_search_box('')
        self._set_mysite_status(T('mysites_search_saved', host=host), SUCCESS)

    def _teach_from_html(self):
        """Learn a site from pages saved in the user's own browser.

        For a site this app cannot open by itself (members only, region
        blocked, a check it will not pass): the user saves a video page — and
        if possible a listing page — with Ctrl+S, and the layout is read from
        those files instead.
        """
        from siphon.sites import generic
        typed = (self._mysite_var.get() or '').strip()
        if not messagebox.askokcancel(T('mysites_teach'), T('mysites_teach_how')):
            return
        files = filedialog.askopenfilenames(
            title=T('mysites_teach_pick'),
            filetypes=[(T('mysites_teach_files'), '*.html *.htm *.txt'),
                       ('All files', '*.*')])
        if not files:
            return
        pages = []
        for path in list(files)[:4]:
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as handle:
                    pages.append((path, handle.read()))
            except OSError as exc:
                self._set_mysite_status(T('mysites_teach_unreadable', error=str(exc)),
                                        ERROR_C)
                return
        # The page with a video in it is the video page; the one listing many
        # videos is the listing.
        video_page = listing_page = None
        for path, text in pages:
            address = generic.page_address(text) or ''
            if generic.find_sources(text, address or 'https://site/v/1/'):
                video_page = video_page or (path, text, address)
            else:
                listing_page = listing_page or (path, text, address)
        if video_page is None:
            self._set_mysite_status(T('mysites_teach_novideo'), ERROR_C)
            return
        _path, text, address = video_page
        # The saved file knows which site it came from; what the user typed is
        # only the fallback.
        root = generic.page_site(text) or generic.normalize_site_url(typed).rstrip('/')
        address = address or (root + '/video/')
        host = (urlsplit(root).hostname or '').lower()
        if not host:
            self._set_mysite_status(T('mysites_teach_noaddress'), ERROR_C)
            return
        listing_text = listing_page[1] if listing_page else ''
        listing_url = ((listing_page[2] if listing_page else '')
                       or (generic.page_site(listing_text) if listing_text else '')
                       or root) + '/'
        learned = generic.learn_from_html(text, address,
                                          listing_text=listing_text,
                                          listing_url=listing_url.replace('//', '/', 0),
                                          page_known=bool(
                                              generic.page_address(text)))
        host = re.sub(r'^www\.', '', host)
        profile = config.get_site_profile(host)
        profile.update(learned['profile'])
        profile.setdefault('root', f'https://{host}')
        config.set_site_profile(host, profile)
        config.add_custom_site(host, host)
        name = learned['engine_label'] or host
        config.save_site_template(name, learned['markers'], learned['template'])
        self._mysite_var.set('')
        self._refresh_site_menu()
        self._refresh_site_picker(keep=host)
        proved = bool(learned['profile'].get('video_shape_ok'))
        print(f"[Site] taught {host} from a saved page: address "
              f"{'read' if generic.page_address(text) else 'NOT in the file'}, "
              f"video shape {learned['profile'].get('video_shape', '-')} "
              f"({'proved' if proved else 'not proved'}), "
              f"{learned['videos_listed']} videos read from the listing",
              flush=True)
        message = T('mysites_teach_done', host=host, kind=learned['kind'] or '?',
                    listed=learned['videos_listed'], name=name)
        if proved:
            message += ' ' + T('mysites_teach_shape',
                               shape=learned['profile']['video_shape'])
        else:
            message += ' ' + T('mysites_teach_noshape')
        self._set_mysite_status(message, SUCCESS if proved else ERROR_C)

    def _custom_site_done(self, result, error, unreachable=False):
        """One address finished: record it, then move on to the next."""
        button = getattr(self, '_mysite_btn', None)
        if button is not None and button.winfo_exists():
            button.configure(state='normal')
        done = getattr(self, '_add_done', None)
        failed = getattr(self, '_add_failed', None)
        if done is None:
            done, failed = [], []
            self._add_done, self._add_failed = done, failed
        note = ''
        if not result:
            failed.append((getattr(self, '_adding_url', ''), error))
            note = T('mysites_unreachable' if unreachable else 'mysites_failed',
                     error=error)
            colour = ERROR_C
        else:
            profile = config.get_site_profile(result['host'])
            profile['root'] = result.get('root') or f"https://{result['host']}"
            if result.get('engine'):
                profile['engine'] = result['engine']
            if result.get('search'):
                profile['search'] = result['search']
            else:
                # It was tried and did not work: better no search box than
                # one that quietly shows the front page every time.
                profile.pop('search', None)
            config.set_site_profile(result['host'], profile)
            # What the check worked out about this site: which of the title
            # rules actually names a video here.  Confirmed on this site, so
            # it is kept against this host alone.
            rules = {}
            if result.get('title_rule'):
                rules['title_rule'] = result['title_rule']
            config.add_custom_site(result['host'], result['host'], rules)
            self._refresh_site_menu()
            known_name, known = builtin_browser_for_host(result['host'])
            done.append(known_name or result['host'])
            self._refresh_site_picker(keep=known_name or result['host'])
            colour = SUCCESS
            if known is not None:
                note = T('mysites_added_known', host=result['host'], name=known_name)
            else:
                # A site whose listing could not be read is still added, and
                # downloading from it by pasting a link does work — that is
                # confirmed, not assumed.  But saying only "added" leaves the
                # person to discover on their own that Browse is empty, so
                # say which half works.
                # A listing of three category tiles is not a listing, and
                # saying "added" for it is worse than failing: the person is
                # told it worked and finds out days later that it did not.
                doubt = str(result.get('listing_doubt') or '')
                browsable = int(result.get('listed') or 0) > 0 and not doubt
                note = T('mysites_added' if browsable
                         else 'mysites_added_links_only',
                         host=result['host'], title=result['title'],
                         kind=result['kind'])
                if doubt:
                    name, _, number = doubt.partition(':')
                    note += '\n' + T('mysites_doubt_' + name, n=number or '?')
                if result.get('engine_label'):
                    note += ' ' + T('mysites_engine', engine=result['engine_label'])
                note += '\n' + _learned_report(result)
                self._offer_search_box(
                    result['host'] if not result.get('search') else '')
        # A site the network blocked is not a site fault: there is nothing in
        # such a report that anyone could act on.
        if unreachable:
            self._offer_report('', None)
        elif result:
            self._offer_report(result['host'], result)
            self._offer_teaching(result['host'],
                                 bool(result.get('listing_doubt'))
                                 or not int(result.get('listed') or 0))
        else:
            from siphon.sites.generic import normalize_site_url
            adding = getattr(self, '_adding_url', '')
            failed_host = (urlsplit(normalize_site_url(adding)).hostname
                           or '').lower().replace('www.', '')
            self._offer_report(failed_host, None, error)
            self._offer_teaching(failed_host, True)
        queue = getattr(self, '_add_queue', None) or []
        if queue:
            self._add_queue = queue[1:]
            self._add_one(queue[0])
            return
        self._mysite_var.set('')
        if len(done) + len(failed) > 1:
            summary = T('mysites_batch_done', added=len(done), failed=len(failed))
            if failed:
                summary += ' ' + T('mysites_batch_failed',
                                   hosts=', '.join(url for url, _e in failed))
            self._set_mysite_status(summary, SUCCESS if done else ERROR_C)
        else:
            self._set_mysite_status(note, colour)
        self._add_done, self._add_failed = [], []
