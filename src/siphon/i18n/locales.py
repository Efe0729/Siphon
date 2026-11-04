#!/usr/bin/env python
# coding: utf-8
"""Localization strings for the GUI apps."""

# Languages offered in the app (the others' tables stay below only for the
# original test-suite; they cannot be chosen any more).
LANGUAGES = [('en', 'English'), ('tr', 'Türkçe')]
FONTS = {
    'en': 'Segoe UI',
    'tr': 'Segoe UI',
}


STRINGS = {
    'en': {
        # Header
        'app_brand_1': 'Siphon',
        'app_brand_2': 'Download from any site, upload to the cloud',
        'status_ready': 'Ready',
        'open_btn': 'Open',
        'go_btn': 'Go',
        'lang_picker_title': 'Choose language',
        'proxy_card_title': 'Network proxy',
        'proxy_card_desc': 'Route only this app\'s site, thumbnail, and download traffic through a proxy. Windows proxy settings are not changed.',
        'proxy_url_label': 'Proxy URL',
        'proxy_url_placeholder': 'e.g. 127.0.0.1:7890',
        'proxy_save': 'Save',
        'proxy_windows': 'Windows',
        'proxy_clear': 'Disable',
        'proxy_saved': 'Saved',
        'proxy_enabled': 'Proxy enabled',
        'proxy_disabled': 'Proxy disabled',
        'proxy_windows_enabled': 'Using the Windows manual proxy',
        'proxy_windows_missing': 'No Windows manual proxy is enabled',
        'proxy_windows_pac': 'A Windows PAC configuration URL was detected; only manual ProxyServer is supported',
        'proxy_windows_invalid': 'The Windows manual proxy setting could not be parsed',
        'proxy_invalid': 'Invalid format; enter host:port or a full proxy URL',
        'proxy_help': 'Save a custom HTTP/HTTPS/SOCKS proxy, or use the enabled Windows manual ProxyServer. PAC URLs are reported but not executed; WPAD auto-detection is not yet supported. Changes apply immediately.',
        'cf_card_title': '🛡️ Cloudflare Bypass (Advanced)',
        'cf_card_desc': 'Import a cf_clearance value from a browser session that passed Cloudflare. Applies only to the selected host.',
        'cf_host_label': 'Host',
        'cf_cookie_label': 'cf_clearance Cookie',
        'cf_ua_label': 'User-Agent',
        'cf_save': 'Save',
        'cf_clear': 'Clear',
        'cf_saved': 'Saved',
        'cf_status': 'Set for: {hosts}',
        'cf_status_none': 'None set',
        'cf_help': (
            'Steps: open the site in Chrome → pass Cloudflare verification → F12 → Application → Cookies → '
            'copy the cf_clearance value above; for User-Agent, run navigator.userAgent in the Console and copy it.\n\n'
            'Caveats: cf_clearance is bound to your IP + User-Agent, so the app must use the same network/VPN and UA as the browser. '
            'It expires (about 30 minutes to a few hours), so copy it again when it stops working. It only works for that domain. '
            'This is an advanced best-effort method and is not guaranteed. For less hassle, use Cloudflare WARP (free, clean IP). '
            'Data is stored only on your computer.'
        ),

        # Tabs
        'tab_browse': 'Browse',
        'tab_download': 'Download',
        'tab_settings': 'Settings',

        # Browse tab
        'search_placeholder': 'Search...',
        'search_btn': 'Search',
        'download_selected': 'Download Selected',
        'first_page': '« First',
        'prev_page': '< Prev',
        'page_n': 'Page {n}',
        'next_page': 'Next >',
        'select': 'Select',
        'selected': 'Selected',
        'sidebar_title': 'Tags',
        'sidebar_no_tags': 'This site is browsed by its own categories.',
        'search_not_supported': "This site did not show Siphon how its search works, so searching is off for it.",
        'no_thumbnail': '(no thumbnail)',
        'loading_browse': 'Loading...',
        'no_results': 'No videos found',
        'empty_try_search': "No videos are listed here. Try the search box above, or pick another category.",
        'front_page_empty': "This site has no video list on its front page: its videos are found by search only. Type a word in the search box above.",
        'front_page_empty_nosearch': "This site has no video list on its front page, and no search address is known for it. Pick a category, or add a video link.",
        'fetch_error': 'Failed to load, please try again',
        'url_not_supported': 'Unsupported URL',
        'crawling_url': 'Crawling listing...',
        'crawl_added': 'Added {n} videos to download queue',
        'category_load_failed': 'Failed to load categories. Try again; Cloudflare may be blocking the request.',
        'mirrors_blocked': 'All mirrors were blocked by Cloudflare. Use a VPN or a different network.',
        'blocked_vpn_hint': 'All mirrors were blocked by Cloudflare. Use a VPN/different network, or import a cf_clearance cookie in Settings.',
        'parse_failed_short': 'Blocked or parse failed; please retry.',
        'open_folder_failed_title': 'Cannot Open Folder',

        # Download tab
        'save_location': 'Save to',
        'url_label': 'Video URL',
        'browse_folder': 'Browse',
        'download_btn': 'Download',
        'download_all_btn': 'Download All',
        'cancel_all': 'Cancel All',
        'retry_short': 'Retry',
        'clear_list': 'Clear',
        'add_to_queue': 'Add to Queue',
        'speed_limit': 'Speed',
        'unlimited': 'Unlimited',
        'max_n': 'Max {n}',
        'dl_list_empty': 'No downloads yet',

        # Download states

        # Settings tab
        'settings_title': 'Settings',
        'settings_desc': 'Manage download preferences and app info',
        'update_not_published': 'Update checking is not switched on yet — it starts working once this app has its own release page.',
        'update_current': 'Current version: v{version}',
        'update_idle': 'Updates have not been checked yet.',
        'update_check_btn': 'Check for updates',
        'update_now_btn': 'Update now',
        'update_prompt_title': 'Update available',
        'update_prompt_later': 'Not now',
        'update_checking': 'Checking for updates...',
        'update_uptodate': 'You are on the latest version.',
        'update_available': 'New version available: {version}',
        'update_downloading': 'Downloading {pct}%...',
        'update_failed': 'Update failed. Please try again later.',
        'update_from_source': 'Running from source. Please update manually.',
        'update_new_badge': '● New version',
        'update_restarting': 'Update downloaded. Restarting...',
        'download_settings': 'Download Settings',
        'nosites_title': 'No sites yet',
        'nosites_desc': 'Add a site and it appears here with its categories, search and pages. You only need its address — the front page is enough.',
        'nosites_button': 'Add a site',
        'mysites_teach': 'Save the page and upload it (.html)',
        'mysites_teach_offer': 'If you would rather not wait, you can fix it yourself now: '
                               'open the site in your browser, press Ctrl+S to save the page, '
                               'then press this button.',
        'mysites_doubt_too_few': 'Careful: only {n} video(s) were found on the whole page, too few for a listing. What was read is probably not the list of videos, and Browse may show you the wrong things.',
        'mysites_doubt_categories': "Careful: the names that were read are the site's own category names. "
                                    'The category tiles were taken for videos, so Browse will show categories instead.',
        'mysites_doubt_numbers': 'Careful: most of the names found are only numbers, so what was read is probably counts or badges rather than videos.',
        'mysites_teach_how': (
            'Some sites will not open from here at all — they want you signed '
            'in, or they are blocked where this computer is.  For those, save '
            'the page yourself and Siphon reads it from the file.\n\n'
            'How to save it:\n\n'
            '1. Open one of the site\'s video pages in your own browser.\n'
            '2. Press Ctrl+S.\n'
            '3. Under "Save as type", choose "Webpage, Complete" or '
            '"Webpage, HTML only" — either works.\n'
            '4. Save it somewhere you will find again, such as Downloads.\n'
            '5. If you can, do the same for the page that lists the videos '
            '(the front page). Two files teach more than one.\n\n'
            'Then pick the file (or both files) in the window that opens next.'),
        'mysites_teach_pick': 'Choose the page(s) you saved',
        'mysites_teach_files': 'Saved web pages',
        'mysites_teach_novideo': 'No video address in that page. Save the page the video actually plays on (Ctrl+S in your browser), or the page the player sits in.',
        'mysites_teach_noaddress': 'The saved page does not say which site it came from. Type the site address in the box first, then choose the file again.',
        'mysites_teach_unreadable': 'That file could not be read ({error}).',
        'mysites_teach_done': 'Learned {host}: video found ({kind}), {listed} videos read from the listing. Saved as the layout "{name}", so other sites built the same way are recognised from now on.',
        'mysites_teach_shape': 'Video address shape learned: {shape}.',
        'mysites_teach_noshape': 'But the file does not say which address it came from, so the video address shape was NOT learned. Open the video page itself, press Ctrl+S there (not on the page source) and choose Webpage, HTML only.',
        'mysites_testing_one': 'Trying {host}… {left} more to go.',
        'mysites_engine': 'The site is built on {engine}.',
        'mysites_batch_done': '{added} site(s) added, {failed} could not be read.',
        'mysites_batch_failed': 'Not added: {hosts}',
        'mysites_pick_label': 'Site',
        'mysites_new': '+  Add a new site',
        'mysites_off_item': '{name}  (off)',
        'mysites_hide': 'Turn off',
        'mysites_show': 'Turn on',
        'mysites_site_known': 'This app has its own code for this site',
        'mysites_site_general': 'Read with the general-purpose reader',
        'mysites_added_known': 'Added: {host}. This app has its own code for this site, so it is listed as {name} and uses that.',
        'mysites_state_on': 'shown in Browse',
        'mysites_state_off': 'hidden from Browse',
        'mysites_moved': '{name} moved to place {place}.',
        'mysites_turned_on': '{name} is shown in Browse again.',
        'mysites_turned_off': '{name} is hidden from Browse. It stays here and can be turned back on.',
        'mysites_remove_confirm': 'Remove {name} from your sites?',
        'mysites_removed': '{name} was removed.',
        'mysites_title': 'My Own Sites',
        'mysites_desc': ('Type the address of a site that is not in the list: its front '
                         'page, like example.com, or the full address of a video page. '
                         'The app opens it, looks for the video and — if it '
                         'finds one — remembers the site. It then appears in Browse with '
                         'its own categories, search and pages, and its links can be '
                         'pasted into Download like any other. Sites behind a "verify you '
                         'are human" check, or built with JavaScript, are read by opening '
                         'the browser already on this computer (Edge or Chrome) off-screen, '
                         'in a profile of its own. Your own browser windows are not '
                         'touched, and the page is read here, not sent anywhere.'),
        'learned_listing': '{n} videos on its listing',
        'learned_titles': 'Titles read — e.g. "{example}"',
        'learned_titles_none': 'Titles could not be read',
        'learned_qualities': 'Qualities: {list}',
        'learned_qualities_none': 'Only one quality',
        'learned_thumbs': '{n} pictures',
        'learned_search': 'Search works',
        'learned_search_none': 'Search not found — you can paste its address below',
        'mysites_search_label': 'Search address',
        'mysites_search_hint': 'Search for something on the site, then paste the address here',
        'mysites_search_save': 'Save search',
        'mysites_search_saved': 'Search saved for {host}.',
        'mysites_search_bad': 'Paste the full address of a search results page from this site.',
        'mysites_link_hint': 'A link to one of its videos works best — the front page is fine too',
        'mysites_url_label': 'Site address',
        'mysites_url_hint': 'example.com, another.com  —  several addresses are fine',
        'mysites_test': 'Test and add',
        'mysites_testing': 'Opening the site and looking for a video… this can take up to a minute.',
        'mysites_bad_url': 'Paste a full address starting with http.',
        'mysites_added': 'Added: {host} — found "{title}" ({kind}). You can now paste links '
                         'from this site into Download.',
        'mysites_added_links_only': 'Added: {host} - a video was found ({kind}), but this site could not have its listing read. It will look empty in Browse. Paste video links into Download instead; downloading works. Send a Report to get the listing fixed.',
        'mysites_failed': 'No video found on this page ({error}). Try another video of the '
                          'same site, or the page the video actually plays on.',
        'mysites_unreachable': 'The site could not be reached from this connection — it '
                               'looks blocked by the network or by DNS. Try again with a '
                               'VPN, or with a different DNS. The address is not wrong; '
                               'the page never opened. ({error})',
        'mysites_needs_report': 'this site looks broken and could not fix itself — press Report',
        'sort_default': 'Sort: default',
        'sort_name': 'Sort: by name',
        'sort_size': 'Sort: biggest first',
        'sort_newest': 'Sort: newest first',
        'sort_oldest': 'Sort: oldest first',
        'report_button': 'Report',
        'report_button_long': 'Report this problem',
        'report_offer': 'Something went wrong with this site. Sending the report '
                        'is what gets it fixed.',
        'report_title': 'Site report',
        'report_heading': 'Report for {host}',
        'report_public_warning': 'A GitHub issue is PUBLIC — anyone on the internet '
                                 'can read all of it, the site address included. If '
                                 'you would rather not, press Copy and send it any '
                                 'way you like.',
        'report_copy': 'Copy',
        'report_copied': 'Copied.',
        'report_open_github': 'Open an issue on GitHub',
        'report_opened': 'Opened in your browser.',
        'report_with_log': 'Include the log (only the lines about this site — you see all of it above before sending)',
        'report_mail': 'Send with Gmail',
        'report_mail_opened': 'A Gmail message is open in your browser. If you do not use Gmail, press Copy and send it from your own mail instead.',
        'report_mail_long': 'The report was too long to fit in the Gmail page. The whole of it is on your clipboard - select everything in Gmail and paste over it.',
        'report_mail_none': 'No mail program is set up on this computer. The report is on your clipboard - paste it in a message to {address}.',
        'report_no_mail': 'This copy has no contact address set. Use the GitHub issue or Copy.',
        'report_open_log': 'Open the log folder',
        'report_log_folder_opened': 'Folder opened. You can attach the whole log to an email or an issue.',
        'report_no_log': 'No log file was found.',
        'report_close': 'Close',
        'report_rechecking': 'Checking {host} again, so the report carries what is '
                             'true now…',
        'mysites_remove': 'Remove',
        'queue_card_title': 'Saved Download Queue',
        'queue_card_desc': 'Your download list is saved here and reloaded next launch.',
        'queue_path_label': 'File location',
        'open_queue_folder': 'Open Folder',
        'clear_saved_queue': 'Clear Saved Queue',
        'clear_saved_queue_confirm': 'Clear the saved download queue? The current list will be emptied. This cannot be undone.',
        'clear_saved_queue_done': 'Saved queue cleared.',
        'clear_saved_queue_failed': 'Could not clear the saved queue',
        'save_location_setting': 'Save Location',
        'save_location_desc': 'Configure the default download directory',
        'speed_limit_setting': 'Speed Limit',
        'speed_limit_desc': 'Limit the maximum bandwidth per download task',
        'concurrent_setting': 'Concurrent Downloads',
        'concurrent_desc': 'How many videos download at the same time (1–32).',
        'max_workers_per_video_setting': 'Per-video workers',
        'max_workers_per_video_desc': 'Connections used to download each video (1–{n}). Pick a site to give it its own value; sites without one follow "All sites (default)". If a site starts dropping connections, lower its value.',
        'slow_requeue_setting': 'Slow-download requeue',
        'slow_requeue_unit': 'KB/s (0 = off)',
        'slow_requeue_desc': 'Checks recent speed every {grace} seconds, including stalls. Below this KB/s threshold, requeues up to {n} times, then warns and continues. Requeue starts the transfer again. 0 disables it; a global speed cap also disables automatic requeue.',
        'slow_requeue_exhausted': 'Auto-requeued {n} times but still slow; no further automatic retries, still downloading',
        'app_full_name': 'Siphon',

        # Smalltool
        'st_header': 'Siphon Watcher',
        'st_window_title': '{app} v{version} — Multi-Site Auto Downloader',
        'st_version_by': 'v{version}',

        # Settings - resolution
        'resolution_setting': 'Video Quality',
        'resolution_desc': 'Choose Highest, 1080p, 720p, 480p, 360p, or Lowest for downloads',
        'resolution_highest': 'Highest Quality',
        'resolution_lowest': 'Lowest Quality (Saving Mode)',

        # Site language prefixes
    },
}

# Workflow strings are kept together so queue UX can evolve independently of
# the older, much larger locale table.  Existing locales receive an English
# fallback for newly introduced controls until a reviewed translation exists.
_WORKFLOW_EN = {
    'selection_count': '{selected} selected · {page} on this page',
    'select_page_btn': 'Select page',
    'select_all_results_btn': 'Select all results',
    'clear_selection_btn': 'Clear',
    'selecting_all_results': 'Selecting all results… page {page} · {count} found',
    'selection_all_done': 'Selected {count} unique results',
    'selection_all_partial': 'Incomplete scan: {count} results found · {reason}',
    'selection_scan_repeated': 'The server repeated a page; stopped safely',
    'selection_scan_cancelled': 'Selection scan cancelled',
    'selection_preview_title': 'Review selected videos',
    'selection_preview_desc': '{count} videos · verify names, site and options before continuing',
    'selection_preview_empty': 'No videos are selected.',
    'selection_preview_add': 'Add to Queue',
    'selection_preview_download': 'Download Now',
    'selection_preview_cancel': 'Cancel',
    'selection_preview_more': '+{count} more selected items are included',
    'selection_preview_resolution': 'Resolution',
    'selection_preview_template': 'Filename template',
    'queue_summary': 'Added {added} · duplicates {duplicates} · unsupported {unsupported}',
    'queue_started_summary': 'Started {started} · duplicates {duplicates} · unsupported {unsupported}',
    'queue_filter_all': 'All',
    'queue_filter_active': 'Active',
    'queue_filter_queued': 'Queued',
    'queue_filter_failed': 'Failed',
    'queue_filter_done': 'History',
    'queue_filter_paused': 'Paused',
    'queue_filter_empty': 'No items match this filter.',
    'clear_queue_confirm': 'Clear every queue and history item? Active work will stop and temporary chunks may be removed.',
    'cancel_all_confirm': 'Cancel all active and queued work? Use Pause all if you want to keep resumable temporary chunks.',
    'pause_short': 'Pause',
    'pause_all': 'Pause all',
    'browser_notice_title': 'One thing before you start',
    'browser_notice_body': (
        'Some sites ask a visitor to prove they are not a robot, or build '
        'their pages with JavaScript. For those, Siphon opens the browser '
        'already on this computer (Edge or Chrome) off-screen, in a profile '
        'of its own, reads the page and closes it again.\n\n'
        'It is not your own browser window and your own browsing is not '
        'touched. Nothing is sent anywhere: the page is read on this '
        'computer only.\n\n'
        'You can read more in the README, under "Sites that fight back".'),
    'resume_all': 'Resume all',
    'resume_short': 'Resume',
    'import_urls': 'Import URLs',
    'paste_urls': 'Paste URLs',
    'export_queue': 'Export',
        'import_unsupported_hint': 'These addresses were skipped because their site has not been added yet: {hosts}\n\nAdd it in Settings → My own sites, then import again.',
        'import_no_urls': 'No addresses were found in that file. Put one address per line and try again.',
        'import_report': '{requested} addresses read.\n\nAdded: {added}\nStarted again: {requeued}\nAlready in the queue: {waiting}\nAlready downloaded: {finished}\nSite not added yet: {unsupported}',
    'import_complete': 'Imported {added} · duplicates {duplicates} · unsupported {unsupported}',
    'import_failed': 'Could not import URLs',
    'export_complete': 'Queue/history exported.',
    'export_failed': 'Could not export queue/history',
    'copy_diagnostics': 'Diagnostic details copied.',
    'disk_preflight_failed': 'The destination is not ready: {error}',
    'disk_low_space': 'Only {free} GB is free; at least {minimum} GB is required.',
    'job_details': '{site} · {code} · {resolution}',
    'eta_label': 'ETA {eta}',
    'eta_left': '{size} left · about {time} at {speed} {how}',
    'eta_left_no_speed': '{size} left',
    'eta_size_unknown': '{n} video(s) left (sizes known once they start)',
    'eta_at_limit': '(your limit)',
    'eta_at_current': '(current speed)',
    'eta_plus_unknown': '+ {n} of unknown size',
    'dl_sum_active': 'Downloading {n}',
    'dl_sum_queued': 'Queued {n}',
    'dl_sum_done': 'Done {n}',
    'dl_sum_left': '{size} left · about {time}',
    'filename_template_setting': 'Filename template',
    'filename_template_desc': 'Available fields: {title}, {site}. For example "{site} - {title}". Characters a filename cannot hold are rejected.',
    'download_schedule_setting': 'Daily start time',
    'download_schedule_desc': 'Optional local time in HH:MM. Blank starts downloads immediately.',
    'minimum_free_setting': 'Minimum free space',
    'minimum_free_desc': 'Check the destination before starting a batch (GB).',
    'auto_retry_setting': 'Network retries',
    'auto_retry_desc': 'Retry temporary network/Cloudflare failures with exponential backoff (0–10).',
    'notify_complete_setting': 'Completion notification',
    'notify_complete_desc': 'Play a system notification when a batch becomes idle.',
    'batch_complete': 'The download batch is complete.',
    'problem_unsupported_url': 'The URL is not supported by an installed site adapter.',
    'problem_disk_full': 'The destination does not have enough free space.',
    'problem_permission': 'The destination cannot be written. Check folder permissions.',
    'problem_ffmpeg_missing': 'ffmpeg is unavailable. Reinstall the app or configure ffmpeg.',
    'problem_blocked': 'The site or CDN blocked the request. Try later, a VPN, or Cloudflare settings.',
    'problem_network': 'The network connection was interrupted. Siphon will retry when allowed.',
    'problem_video_missing': 'The video was removed or is no longer available.',
    'problem_parse_or_unknown': 'The page may have changed or returned an unexpected response.',
}
for _locale in STRINGS.values():
    _locale.update(_WORKFLOW_EN)


# Source-player preview is deliberately a system-browser tab, not an embedded
# player or a promise to bypass provider access restrictions.
for _language, _preview in {
    'en': ('Preview ↗', 'Opened the source player in your browser. Playback depends on site access.', 'Could not open preview. Check the source URL and default browser.'),
}.items():
    STRINGS[_language].update(zip(
        ('preview_browser', 'preview_opened', 'preview_failed'), _preview))

STATE_LABELS = {
    '下載中': {'en': 'Downloading'},
    '準備中': {'en': 'Preparing'},
    '等待中': {'en': 'Queued'},
    '等待重試': {'en': 'Retry scheduled'},
    '已排程': {'en': 'Scheduled'},
    '已暫停': {'en': 'Paused'},
    '已存在': {'en': 'Duplicate'},
    '已下載': {'en': 'Done'},
    '未完成': {'en': 'Incomplete'},
    '已取消': {'en': 'Cancelled'},
    '網址錯誤': {'en': 'Bad URL'},
    '封鎖/解析失敗': {'en': 'Blocked'},
}

# Turkish: the English table with every text translated (technical values
# such as site URL language codes stay English).
from siphon.i18n.tr import TR as _TR, STATE_TR as _STATE_TR
STRINGS['tr'] = dict(STRINGS['en'])
STRINGS['tr'].update(_TR)
for _code, _label in _STATE_TR.items():
    STATE_LABELS.setdefault(_code, {})['tr'] = _label

# Active language - set before GUI init
_current_lang = 'en'


def set_lang(lang: str):
    global _current_lang
    _current_lang = lang if lang in STRINGS else 'en'


def T(key: str, **kwargs) -> str:
    """Translate a key to the current language."""
    lang_strings = STRINGS.get(_current_lang, STRINGS['en'])
    if key in lang_strings:
        s = lang_strings[key]
    else:
        s = STRINGS['en'].get(key, key)
    if kwargs:
        return s.format(**kwargs)
    return s


def get_lang() -> str:
    return _current_lang


def ui_font():
    return FONTS.get(_current_lang, 'Segoe UI')


def state_label(code):
    labels = STATE_LABELS.get(code, {})
    return labels.get(_current_lang) or labels.get('en') or code
