"""Permanent record of finished downloads (survives clearing the list).

Used to refuse downloading a video again: by its page address (before the
download starts) and by its file name (once the site's title is known).
Stored as JSON next to the download queue.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

_KEEP_QUERY = {'v'}          # e.g. a site that uses watch?v=<id>


def norm_url(url):
    """Same video → same key (no www./language subdomain, no tracking query)."""
    try:
        parts = urlsplit(str(url or '').strip())
    except ValueError:
        return str(url or '').strip().lower()
    host = (parts.hostname or '').lower()
    host = re.sub(r'^(?:www|[a-z]{2})\.(?=[^.]+\.[^.]+$)', '', host)
    path = parts.path.rstrip('/')
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if k in _KEEP_QUERY))
    return f'{host}{path}' + (f'?{query}' if query else '')


def norm_name(name):
    text = os.path.splitext(str(name or ''))[0] if str(name or '').lower().endswith(
        ('.mp4', '.mkv', '.ts', '.webm')) else str(name or '')
    return re.sub(r'\s+', ' ', text).strip().casefold()


class DownloadHistory:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._by_url = {}
        self._by_name = {}
        self._load()

    def _load(self):
        try:
            from siphon.core import secretstore
            text = secretstore.read_text(self.path)
            data = json.loads(text) if text.strip() else {}
        except Exception:
            data = {}
        for entry in data.get('items', []) if isinstance(data, dict) else []:
            if isinstance(entry, dict) and entry.get('url'):
                self._index(entry)

    def _index(self, entry):
        self._by_url[norm_url(entry['url'])] = entry
        key = norm_name(entry.get('name'))
        if key:
            self._by_name[key] = entry

    def _save(self):
        items = list({id(e): e for e in self._by_url.values()}.values())
        items.sort(key=lambda e: e.get('at', 0))
        try:
            from siphon.core import secretstore
            secretstore.write_text(self.path, json.dumps(
                {'version': 1, 'items': items}, ensure_ascii=False))
        except OSError as exc:
            print(f'[history] could not save: {exc}', flush=True)

    def __len__(self):
        return len(self._by_url)

    def match_url(self, url):
        with self._lock:
            return self._by_url.get(norm_url(url))

    def match_name(self, name, url=''):
        """A finished download with this file name (from another address)."""
        key = norm_name(name)
        if not key:
            return None
        with self._lock:
            entry = self._by_name.get(key)
        if entry and url and norm_url(entry.get('url')) == norm_url(url):
            return None
        return entry

    def average_size(self, last=40):
        """Mean size in bytes of the most recent finished downloads (0 if none known)."""
        with self._lock:
            sizes = [e.get('size') for e in sorted(self._by_url.values(),
                                                   key=lambda e: e.get('at', 0))
                     if e.get('size')]
        sizes = sizes[-last:]
        return int(sum(sizes) / len(sizes)) if sizes else 0

    def add(self, url, name, path='', at=None, save=True, size=0):
        entry = {'url': str(url), 'name': str(name or ''), 'path': str(path or ''),
                 'at': float(at or time.time())}
        if size:
            entry['size'] = int(size)
        with self._lock:
            self._index(entry)
            if save:
                self._save()
        return entry

    def add_many(self, entries):
        with self._lock:
            added = 0
            for url, name, at in entries:
                if url and norm_url(url) not in self._by_url:
                    self._index({'url': str(url), 'name': str(name or ''), 'path': '',
                                 'at': float(at or time.time())})
                    added += 1
            if added:
                self._save()
        return added

    def remove(self, url):
        with self._lock:
            entry = self._by_url.pop(norm_url(url), None)
            if entry:
                key = norm_name(entry.get('name'))
                if self._by_name.get(key) is entry:
                    self._by_name.pop(key, None)
                self._save()
        return entry


def when(entry):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime((entry or {}).get('at') or 0))


def describe(entry):
    """'downloaded 2026-10-25 14:02 as "Title"' for messages."""
    if not entry:
        return ''
    when = time.strftime('%Y-%m-%d %H:%M', time.localtime(entry.get('at') or 0))
    return f'{when} · "{entry.get("name") or entry.get("url")}"'
