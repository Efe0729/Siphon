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
        'version_label': 'v1.0.0',
        'by_author': '',
        'status_ready': 'Ready',
        'site_label': 'Site',
        'open_btn': 'Open',
        'go_btn': 'Go',
        'lang_label': 'Language',
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
        'browse_category': 'Browse Videos',
        'category_label': 'Category:',
        'sort_latest': 'Latest',
        'search_placeholder': 'Search...',
        'search_btn': 'Search',
        'site_filter_button': 'Full filters',
        'site_filter_active': 'Filters active',
        'site_filter_title': 'site full filters',
        'site_filter_desc': 'Combine genre, sort, published date, duration, and multiple tags—including Ura Anime, short anime, and the complete tag catalog.',
        'site_filter_any': 'Any',
        'site_filter_query': 'Keywords',
        'site_filter_genre': 'Genre',
        'site_filter_sort': 'Sort',
        'site_filter_date': 'Published',
        'site_filter_duration': 'Duration',
        'site_filter_tags': 'Tags',
        'site_filter_tag_search': 'Search 240 tags…',
        'site_filter_selected_tags': '{count} selected',
        'site_filter_other_tags': 'Other tags',
        'site_filter_apply': 'Apply filters',
        'site_filter_reset': 'Clear all',
        'site_filter_result': '⚙ Custom filter results',
        'download_selected': 'Download Selected',
        'select_all_btn': 'Select All',
        'first_page': '« First',
        'prev_page': '< Prev',
        'page_n': 'Page {n}',
        'next_page': 'Next >',
        'select': 'Select',
        'selected': 'Selected',
        'sidebar_title': 'Tags',
        'tags_site_only': 'Tags: site only',
        'no_thumbnail': '(no thumbnail)',
        'loading_browse': 'Loading...',
        'no_results': 'No videos found',
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
        'requeue_short': 'Requeue',
        'clear_list': 'Clear',
        'add_to_queue': 'Add to Queue',
        'browse_import': 'Browse Selected Open',
        'speed_limit': 'Speed',
        'unlimited': 'Unlimited',
        'concurrent': 'Concurrent',
        'max_n': 'Max {n}',
        'dl_list_empty': 'No downloads yet',
        'dl_list_more_not_shown': '+{n} more not shown',

        # Download states
        'state_downloading': 'Downloading',
        'state_waiting': 'Waiting',
        'state_downloaded': 'Downloaded',
        'state_cancelled': 'Cancelled',
        'state_error': 'Error',
        'state_merging': 'Merging',

        # Settings tab
        'settings_title': 'Settings',
        'settings_desc': 'Manage download preferences and app info',
        'update_not_published': 'Update checking is not switched on yet — it starts working once this app has its own release page.',
        'update_card_title': 'Updates',
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
        'mysites_teach': 'Teach from a saved page',
        'mysites_teach_pick': 'Choose the page(s) you saved',
        'mysites_teach_files': 'Saved web pages',
        'mysites_teach_novideo': 'No video address in that page. Save the page the video actually plays on (Ctrl+S in your browser), or the page the player sits in.',
        'mysites_teach_noaddress': 'The saved page does not say which site it came from. Type the site address in the box first, then choose the file again.',
        'mysites_teach_unreadable': 'That file could not be read ({error}).',
        'mysites_teach_done': 'Learned {host}: video found ({kind}), {listed} videos read from the listing. Saved as the layout "{name}", so other sites built the same way are recognised from now on.',
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
        'mysites_builtin_off': '{name} is built in, so it was turned off instead of removed. You can turn it back on from this list.',
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
        'mysites_url_label': 'Site address',
        'mysites_url_hint': 'example.com, another.com  —  several addresses are fine',
        'mysites_test': 'Test and add',
        'mysites_testing': 'Opening the site and looking for a video… this can take up to a minute.',
        'mysites_bad_url': 'Paste a full address starting with http.',
        'mysites_added': 'Added: {host} — found "{title}" ({kind}). You can now paste links '
                         'from this site into Download.',
        'mysites_builtin': '{host} is already supported; nothing to add.',
        'mysites_failed': 'No video found on this page ({error}). Try another video of the '
                          'same site, or the page the video actually plays on.',
        'mysites_empty': 'No sites added yet.',
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
        'max_workers_per_video_desc': 'Connections used to download each video (1–{n}). Pick a site to give it its own value; sites without one follow "All sites (default)". Limits: site 4, site 8, site/site 4. If a site starts dropping connections, lower its value.',
        'slow_requeue_setting': 'Slow-download requeue',
        'slow_requeue_unit': 'KB/s (0 = off)',
        'slow_requeue_desc': 'Checks recent speed every {grace} seconds, including stalls. Below this KB/s threshold, requeues up to {n} times, then warns and continues. Requeue starts the transfer again. 0 disables it; a global speed cap also disables automatic requeue.',
        'slow_requeue_exhausted': 'Auto-requeued {n} times but still slow; no further automatic retries, still downloading',
        'filename_mode_setting': 'Filename format',
        'filename_mode_full': 'Code + full title',
        'filename_mode_code': 'Code only',
        'filename_mode_desc': 'Code only keeps everything before the first whitespace (for example FC2-PPV-1234567); a title without whitespace stays unchanged. Applies to newly created downloads.',
        'about': 'About',
        'app_full_name': 'Siphon',
        'disclaimer': 'For educational and research purposes only',

        # Smalltool
        'st_title': 'Multi-Site Auto Downloader',
        'st_header': 'Siphon Watcher',
        'st_header_sub': 'Multi-Site Auto Download',
        'st_save_location': 'Save to:',
        'st_browse': 'Browse',
        'st_baseline_date': 'After date:',
        'st_date_hint': '(YYYY-MM-DD, only download videos after this date)',
        'st_calendar': 'Calendar',
        'st_date_quick': 'Quick date',
        'st_date_yesterday': 'Yesterday',
        'st_date_month_1': '1 month ago',
        'st_date_month_2': '2 months ago',
        'st_date_month_3': '3 months ago',
        'st_date_month_6': '6 months ago',
        'st_calendar_title': 'Select baseline date',
        'st_weekdays': 'Mon|Tue|Wed|Thu|Fri|Sat|Sun',
        'st_date_today': 'Today',
        'st_calendar_cancel': 'Cancel',
        'st_site_settings_button': 'Per-site date & folder',
        'st_site_settings_title': 'Per-site monitoring settings',
        'st_site_settings_desc': 'Give each site its own detection date and download folder. Fields using the shared default automatically follow the Watcher main screen.',
        'st_site_settings_default': 'All sites use the shared defaults',
        'st_site_settings_custom_count': '{count} site(s) use custom settings',
        'st_site_use_default_folder': 'Use shared folder',
        'st_site_use_default_date': 'Use shared date',
        'st_site_settings_save': 'Save site settings',
        'st_site_folder_required': 'The custom folder for {site} cannot be empty.',
        'st_site_date_invalid': 'The date for {site} is invalid. Use YYYY-MM-DD.',
        'st_folder_error': 'Cannot use save folder',
        'st_folder_error_msg': 'Could not create or use this folder:\n{path}\n\n{error}',
        'st_select_hint': 'Select sites and categories (multi-select):',
        'st_select_all': 'Select All',
        'st_filter_categories': 'Search categories',
        'st_categories_expand': 'Edit categories',
        'st_categories_collapse': 'Collapse',
        'st_settings_expand': 'Show settings',
        'st_settings_collapse': 'Hide settings',
        'st_activity_show': 'Show activity',
        'st_activity_hide': 'Hide activity',
        'st_group_feeds': 'Feeds / Charts',
        'st_group_categories': 'Main Categories',
        'st_group_providers': 'Channels / Providers',
        'st_group_genres': 'Genres',
        'st_group_makers': 'Makers (Advanced)',
        'st_group_dates': 'Published date',
        'st_group_durations': 'Duration',
        'st_site_tags_features': 'Content features',
        'st_site_tags_relationships': 'Relationships',
        'st_site_tags_roles': 'Roles / occupations',
        'st_site_tags_characters': 'Character traits',
        'st_site_tags_appearance': 'Appearance',
        'st_site_tags_clothing': 'Clothing',
        'st_site_tags_locations': 'Locations',
        'st_site_tags_themes': 'Stories / themes',
        'st_site_tags_acts': 'Acts / positions',
        'st_start': 'Start monitoring',
        'st_stop': 'Stop',
        'st_check_now': 'Check now',
        'st_idle': 'Idle',
        'st_running': '● Running',
        'st_scanning': '● Scanning',
        'st_downloading': '● Downloading',
        'st_stopped': 'Stopped',
        'st_footer': 'Tip: Closing the window stops the program. Minimize to keep it running. The automatic-check schedule is customizable.',
        'st_footer_short': 'Custom automatic-check schedule',
        'st_activity': 'Activity',
        'st_schedule': 'Schedule',
        'st_schedule_title': 'Automatic check schedule',
        'st_schedule_interval': 'Every',
        'st_schedule_hours': 'hours',
        'st_schedule_daily': 'Daily at',
        'st_schedule_local_time': 'Computer local time: {zone} (UTC{offset})',
        'st_schedule_hint': 'Check every 1–168 hours, or daily using this computer’s local time.',
        'st_schedule_save': 'Save schedule',
        'st_schedule_summary_interval': 'Every {hours} h',
        'st_schedule_summary_daily': 'Daily at {time} (local time)',
        'st_schedule_invalid_hours': 'Enter a whole number from 1 to 168 hours.',
        'st_schedule_invalid_time': 'Enter a valid 24-hour time (HH:MM).',
        'st_schedule_saved': 'Schedule saved.',
        'st_scan_queued': 'Check Now queued.',
        'st_waiting_schedule': 'Waiting for the next scheduled check',
        'st_stopping': '● Stopping',
        'st_progress_idle': 'No active download',
        'st_scan_progress': 'Scanning {site} / {category} · Page {page}',
        'st_candidates_found': '{count} eligible found',
        'st_no_folder': 'No Folder',
        'st_no_folder_msg': 'Please select a download folder first.',
        'st_no_cat': 'No Category',
        'st_no_cat_msg': 'Please select at least one site category.',
        'st_bad_date': 'Invalid Date',
        'st_bad_date_msg': 'Date format should be YYYY-MM-DD.',
        'st_started_msg': 'Monitoring started — you can minimize this window.',
        'st_subtitle': 'Unattended New-Release Automation',
        'st_window_title': '{app} v{version} — Multi-Site Auto Downloader',
        'st_version_by': 'v{version}',
        'st_lang_label': 'Language',
        'st_lang_picker_title': 'Choose language',
        'st_detect_failed': '⚠ Detection failed, retrying',
        'st_choose_folder': 'Choose video save folder',
        'st_blocked': 'Blocked',
        'st_interval': 'Interval',
        'st_site': 'Site',
        'st_category': 'Category',
        'st_status': 'Status',
        'st_log': 'Log',
        'st_resolution': 'Quality:',
        'st_resolution_highest': 'Highest Quality',
        'st_resolution_lowest': 'Lowest Quality (Saving Mode)',
        'st_version_preference': 'Version priority:',
        'st_pref_chinese': 'Chinese subtitles first',
        'st_pref_uncensored': 'Uncensored / leak first',
        'st_pref_standard': 'Standard version first',
        'st_pref_all': 'All versions (separate folders)',
        'st_storage_failed': 'Storage I/O failed; monitoring stopped. Check space and device health before retrying',
        'st_pref_english': 'English subtitles first',
        'st_pref_reducing_mosaic': 'Reduced mosaic first',
        'st_scan_running': 'Background scan is already running; please wait.',
        'st_checking_now': 'Checking now...',
        'st_preparing': 'Preparing...',
        'st_folder_set': 'Save location set to {path}',
        'st_target_log': 'Target: {sites} — {categories}',
        'st_baseline_log': 'Baseline date: {date}',
        'st_no_output_configured': 'No output folder configured.',
        'st_no_targets_selected': 'No sites/categories selected.',
        'st_worker_started': 'Worker started.',
        'st_worker_stopped': 'Worker stopped.',

        # Settings - resolution
        'resolution_setting': 'Video Quality',
        'resolution_desc': 'Choose Highest, 1080p, 720p, 480p, 360p, or Lowest for downloads',
        'resolution_highest': 'Highest Quality',
        'resolution_lowest': 'Lowest Quality (Saving Mode)',

        # Site language prefixes
        'site_lang': 'en',
        'site_lang': '',
        'site_lang': 'en',
    },
}

# Workflow strings are kept together so queue UX can evolve independently of
# the older, much larger locale table.  Existing locales receive an English
# fallback for newly introduced controls until a reviewed translation exists.
_WORKFLOW_EN = {
    'selection_count': '{selected} selected · {page} on this page',
    'select_page_btn': 'Select page',
    'select_all_results_btn': 'Select all results',
    'review_selected_btn': 'Review selection',
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
    'filename_template_desc': 'Available fields: {title}, {code}, {site}. Invalid path characters are rejected.',
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
