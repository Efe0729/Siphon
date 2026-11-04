"""English console output plus a persistent log file.

The original app prints its progress and errors in Chinese.  ``install()``
wraps stdout/stderr so every line is translated to English (known phrases
only) and also appended, with a timestamp, to ``logs/siphon.log``.
Live progress lines that redraw in place (``\\r...``) are shown on the
console but kept out of the file so it stays readable.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from pathlib import Path

# (Chinese, English) — applied longest-first, so whole sentences win over
# the short fragments they contain.
_PHRASES = [
    # status / progress
    ('取消下載....', 'Cancelling download...'),
    ('下載已取消', 'Download cancelled'),
    ('下載完成!', 'Download complete!'),
    ('下載完成: ', 'Download complete: '),
    ('下載未完成', 'Download incomplete'),
    ('下載中: ', 'Downloading: '),
    ('檔案名稱: ', 'File name: '),
    ('儲存位置: ', 'Save location: '),
    ('縮圖: ', 'Thumbnail: '),
    ('檔案已存在!!', 'File already exists!'),
    ('下載網址 ', 'Download URL '),
    (' 錯誤!! (', ' error! ('),
    (' 錯誤!!', ' error!'),
    ('下載錯誤: ', 'Download error: '),
    ('下載目錄: ', 'Download folder: '),
    ('[下載失敗] ', '[Download failed] '),
    ('[瀏覽錯誤] ', '[Browse error] '),
    ('[完成] ', '[Done] '),
    ('[錯誤] ', '[Error] '),
    ('[失敗] 下載未完成: ', '[Failed] Download incomplete: '),
    ('[失敗] 無法解析影片（版面改版 / 被 Cloudflare 阻擋 / 影片不存在）: ',
     '[Failed] Could not parse video (site changed / blocked by Cloudflare / video missing): '),
    ('[跳過] 不支援的網址: ', '[Skipped] Unsupported URL: '),
    ('不支援的網址: ', 'Unsupported URL: '),
    ('無法解析影片: ', 'Could not parse video: '),
    ('已在清單中: ', 'Already in list: '),
    ('請先輸入網址', 'Please enter a URL first'),
    ('下載清單是空的，請先加入網址', 'Download list is empty, add URLs first'),
    ('下載清單已經是空的', 'Download list is already empty'),
    ('清單中沒有需要下載的項目', 'Nothing in the list needs downloading'),
    ('請先選取要刪除的項目', 'Select items to delete first'),
    ('速度限制: 無限制', 'Speed limit: unlimited'),
    ('速度限制: ', 'Speed limit: '),
    ('同時下載數: ', 'Concurrent downloads: '),
    ('每部影片下載執行緒: ', 'Threads per video: '),
    (' | 每片執行緒: ', ' | threads per video: '),
    (' | 解析度: ', ' | resolution: '),
    ('重試第 ', 'Retry #'),
    (' 次，剩餘 ', ', remaining '),
    ('，剩餘 ', ', remaining '),
    (' | 剩餘 ', ' | remaining '),
    (' | 共 ', ' | total '),
    (' 片段，已完成 ', ' segments, done '),
    (' 片段 | ', ' segments | '),
    (' 片段...', ' segments...'),
    (' 個片段失敗', ' segments failed'),
    (' 個片段', ' segments'),
    ('片段 ', 'Segment '),
    ('開始合成影片...共有 ', 'Merging video... total '),
    ('合成影片中, 剩餘 ', 'Merging video, remaining '),
    ('合成完成，花費 ', 'Merge finished, took '),
    (' 遺失, 合成失敗!!!', ' missing, merge failed!!!'),
    ('[合成] ffmpeg 無法使用或重新封裝失敗，改用原始合併（檔案可播放，但部分播放器/NAS 拖曳進度可能異常）',
     '[Merge] ffmpeg unavailable or remux failed; used plain merge (plays fine, seeking may be off in some players)'),
    ('[合成] ffmpeg 執行錯誤: ', '[Merge] ffmpeg error: '),
    ('[合成] ffmpeg 重新封裝失敗 rc=', '[Merge] ffmpeg remux failed rc='),
    ('[合成] 找不到 ffmpeg，略過重新封裝', '[Merge] ffmpeg not found, skipping remux'),
    ('正在重新封裝為可正常拖曳的 MP4 ...', 'Remuxing to a seekable MP4 ...'),
    ('爬取完成！花費 ', 'Crawl finished! took '),
    ('爬取結束，', 'Crawl ended, '),
    ('部影片。已取得', ' videos. Got'),
    (']共有', '] has'),
    ('部影片', ' videos'),
    ('頁，', ' pages, '),
    ('共 ', 'total '),
    ('已加入 ', 'Added '),
    ('已刪除 ', 'Deleted '),
    ('已清除 ', 'Cleared '),
    ('已載入 ', 'Loaded '),
    (' 個項目', ' items'),
    (' 個網址', ' URLs'),
    (' 個下載任務', ' download tasks'),
    (' 個，失敗 ', ', failed '),
    (' 個 =====', ' =====' ),
    ('===== 完成 ', '===== Done '),
    ('網址 ', 'URL '),
    ('[慢速自動重排] ', '[Slow auto-requeue] '),
    (' 速度 ', ' speed '),
    (' KB/s 低於門檻 ', ' KB/s is below threshold '),
    (' KB/s，第 ', ' KB/s, attempt '),
    (' 次自動重新排隊', ' automatic requeue'),
    (' 已自動重試 ', ' already auto-retried '),
    (' 次仍低速，停止自動重試並繼續下載', ' times and is still slow; continuing without retry'),
    (' 分鐘', ' min'),
    (' 秒', ' s'),
    # error messages raised by the download code
    ('İndirme parçası不完整（連線中斷？請重試）', 'Direct download range incomplete (connection dropped? retry)'),
    ('直接İndirme yarım kaldı (bağlantı koptu) — tekrar deneyin', 'Direct download incomplete (connection dropped? retry)'),
    ('İndirme yarım kaldı (bağlantı koptu) — tekrar deneyin', 'Download incomplete (connection dropped? retry)'),
    ('Video sunucusu parçalı indirmeye doğru cevap vermedi', 'Source did not answer the range request correctly'),
    ('İndirilen parça beklenenden uzun', 'Range longer than expected'),
    ('Bağlantı indirme bitmeden kapandı', 'Connection closed early'),
    ('İndirilen parça diske yazılamadı', 'Write to disk failed'),
    ('Kaldığı yerden devam edilemedi (HTTP ', 'Resume failed (HTTP '),
    ('Doğrudan indirme başarısız (HTTP ', 'Direct download failed (HTTP '),
    ('İndirme parçası', 'Direct download range: '),
    ('未收到資料', 'no data received'),
    ('連線提前結束', 'connection closed early'),
    ('Şifre çözme anahtarı alınamadı', 'Could not get AES key'),
    ('Video listesi (m3u8) alınamadı (HTTP ', 'm3u8 request failed (HTTP '),
    ('Video listesinde geçerli parça yok — engellenmiş ya da site değişmiş olabilir', 'm3u8 has no valid segments (blocked or site changed)'),
    ('Video listesi (m3u8) geçersiz — engellenmiş ya da site değişmiş olabilir: ', 'm3u8 content invalid (blocked or site changed): '),
    ('Sayfa okunamadı (Cloudflare engeli ya da site değişikliği): ', 'Page parsing failed (Cloudflare block or site changed): '),
    ('Sayfa okunamadı (site değişmiş ya da video yok): ', 'Page parsing failed (site changed or video missing): '),
    ('Bu videonun oynatma kaynağı bulunamadı (site değişmiş olabilir)', 'No server source for this video (site changed?)'),
    ('Bu video için indirilebilir kaynak yok (sayfadaki kaynaklar: ', 'No download source for this video (page sources '),
    ('；來源失效、存取受限或播放器改版）', '; source dead, restricted or player changed)'),
    ('Sitenin tüm adresleri Cloudflare tarafından engellendi — VPN ya da başka bir ağ deneyin (all mirrors blocked by Cloudflare)',
     'All mirrors are blocked by Cloudflare (network/IP reputation; try a VPN or another network)'),
    ('Video sunucusu (surrit.com) Cloudflare tarafından engellendi — VPN/WARP ya da başka bir ağ deneyin',
     'Video CDN (surrit.com) is blocked by Cloudflare; try a VPN/WARP or another network'),
]
_PHRASES.sort(key=lambda pair: len(pair[0]), reverse=True)
_HAS_CJK = __import__('re').compile(r'[㐀-鿿＀-￯ğüşıöçĞÜŞİÖÇ]')

_MAX_BYTES = 5 * 1024 * 1024
_lock = threading.Lock()
_log_path: Path | None = None


def translate(text: str) -> str:
    if not text or not _HAS_CJK.search(text):
        return text
    for zh, en in _PHRASES:
        if zh in text:
            text = text.replace(zh, en)
    return text


def _default_log_dir() -> Path:
    # Running from a source checkout: keep logs next to the project.
    root = Path(__file__).resolve().parents[3]
    if (root / 'pyproject.toml').is_file():
        return root / 'logs'
    from siphon.core.paths import product_data_dir
    return product_data_dir() / 'logs'


def log_path() -> Path | None:
    return _log_path


def _open_log(name: str) -> Path | None:
    try:
        folder = _default_log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            old = path.with_suffix('.old.log')
            try:
                old.unlink()
            except OSError:
                pass
            path.rename(old)
        return path
    except OSError:
        return None


# ── What the log file is not allowed to remember ────────────────────────────
# The settings, queue and history are stored scrambled so that nobody can read
# which sites were added or what was downloaded.  A log sitting next to them in
# plain text would hand all of it back, so the lines that carry a video's name,
# a saved file's path or a full address are trimmed on their way to the file.
# The console still shows everything, for watching a problem as it happens.
_REDACT_AFTER = re.compile(
    r'^(?P<keep>.*?\b(?:File name|Save location|Download folder|Thumbnail|'
    r'Downloading|Download complete|title)\s*:\s*)(?P<secret>.+)$', re.I)
_URL = re.compile(r'\bhttps?://([^\s/]+)(/\S*)?')
_WIN_PATH = re.compile(r'\b[A-Za-z]:\\[^\s"\']+')
_HIDDEN = '<hidden>'

# An address between these two characters is the structure of a site, not
# somebody's viewing: the address of a search box, the spelling of "page 2".
# Those have to survive into the log file, because they are the whole of a
# site report.  Everything else keeps being hidden.
_KEEP_OPEN, _KEEP_CLOSE = '\x01', '\x02'
_KEPT = re.compile(f'{_KEEP_OPEN}(.*?){_KEEP_CLOSE}')


def keep(value) -> str:
    """Mark an address as site structure, so the log file keeps it whole.

    Only for addresses Siphon worked out by itself — a search address built
    from a word taken off the site's own listing, a page-2 address it
    guessed.  Never for an address that came from the person: what they
    searched for, or which video they opened, stays out of the file.
    """
    return f'{_KEEP_OPEN}{value}{_KEEP_CLOSE}'


def unmark(text: str) -> str:
    """The same text with the markers gone, for showing on the console."""
    return text.replace(_KEEP_OPEN, '').replace(_KEEP_CLOSE, '')


def redact(line: str) -> str:
    """A log line with the private parts taken out."""
    kept = []

    def park(match):
        kept.append(match.group(1))
        return f'{_KEEP_OPEN}{len(kept) - 1}{_KEEP_CLOSE}'

    line = _KEPT.sub(park, line)
    found = _REDACT_AFTER.match(line)
    if found:
        line = found.group('keep') + _HIDDEN
    else:
        line = _URL.sub(lambda m: f'https://{m.group(1)}/{_HIDDEN}'
                        if m.group(2) and m.group(2) != '/' else m.group(0), line)
        line = _WIN_PATH.sub(_HIDDEN, line)
    return _KEPT.sub(lambda m: kept[int(m.group(1))], line)


class _Tee:
    """File-like wrapper: translate, show on console, append lines to the log."""

    def __init__(self, stream, path: Path | None, label: str):
        self._stream = stream
        self._path = path
        self._label = label
        self._pending = ''
        self.encoding = getattr(stream, 'encoding', None) or 'utf-8'
        self.errors = 'replace'

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        text = translate(text)
        if self._stream is not None:
            try:
                self._stream.write(unmark(text))
            except Exception:
                pass
        self._to_file(text)
        return len(text)

    def _to_file(self, text):
        if self._path is None:
            return
        self._pending += text
        if '\n' not in self._pending:
            if len(self._pending) > 8000:
                self._pending = self._pending[-2000:]
            return
        *lines, self._pending = self._pending.split('\n')
        out = []
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        for line in lines:
            # keep only what a \r progress redraw finally left on the line
            line = redact(line.rsplit('\r', 1)[-1].rstrip())
            if line.strip():
                out.append(f'{stamp} {self._label}{line}\n')
        if not out:
            return
        with _lock:
            try:
                with open(self._path, 'a', encoding='utf-8') as fh:
                    fh.writelines(out)
            except OSError:
                pass

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return bool(self._stream and self._stream.isatty())
        except Exception:
            return False

    def fileno(self):
        if self._stream is None:
            raise OSError('no console')
        return self._stream.fileno()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def install(name: str = 'siphon.log') -> Path | None:
    """Wrap sys.stdout / sys.stderr once.  Safe to call more than once."""
    global _log_path
    if isinstance(sys.stdout, _Tee):
        return _log_path
    _log_path = _open_log(name)
    if _log_path is not None:
        try:
            with open(_log_path, 'a', encoding='utf-8') as fh:
                fh.write(f'\n{time.strftime("%Y-%m-%d %H:%M:%S")} ===== app started (pid {os.getpid()}) =====\n')
        except OSError:
            _log_path = None
    sys.stdout = _Tee(sys.stdout, _log_path, '')
    sys.stderr = _Tee(sys.stderr, _log_path, '[stderr] ')
    return _log_path
