"""The end of a download.

A file used to be cut into one piece per connection.  A connection that
finished its piece then sat idle, so the slowest piece was downloaded alone
and the last part of every file crawled along at the speed of one
connection — which is what a 1 GB film dropping to 80 KB/s at 99% was.
"""

import http.server
import threading
import time

import pytest

from siphon.sites.downloader import _split_byte_ranges as split

MB = 1024 * 1024


def _sizes(ranges):
    return [end - start + 1 for start, end in ranges]


@pytest.mark.parametrize('total,connections', [
    (100 * MB, 4), (1024 * MB, 4), (5 * 1024 * MB, 4), (3 * MB, 4),
    (64 * MB, 8), (1, 4), (500, 1),
])
def test_the_pieces_cover_the_file_exactly(total, connections):
    """Whatever the sizes, the file must be covered once: a gap is a corrupt
    video and an overlap is bytes written over each other."""
    ranges = split(total, connections)
    assert ranges[0][0] == 0
    assert ranges[-1][1] == total - 1
    assert sum(_sizes(ranges)) == total
    for (_a, b), (c, _d) in zip(ranges, ranges[1:]):
        assert c == b + 1


def test_there_are_more_pieces_than_connections():
    """The whole point: a connection that finishes has something to pick up."""
    ranges = split(1024 * MB, 4)
    assert len(ranges) > 4


def test_the_last_piece_is_small_enough_to_not_be_the_whole_tail():
    """With one piece per connection, the tail of a 1 GB file was 256 MB on
    one connection.  It should now be a few MB."""
    ranges = split(1024 * MB, 4)
    assert _sizes(ranges)[-1] <= 16 * MB


def test_a_very_large_file_is_still_cut_into_small_pieces():
    """A cap on the number of pieces brought the slow tail straight back for
    big films."""
    ranges = split(5 * 1024 * MB, 4)
    assert _sizes(ranges)[-1] <= 16 * MB


def test_a_small_file_still_uses_every_connection():
    ranges = split(3 * MB, 4)
    assert len(ranges) == 4


def test_a_file_is_not_cut_into_thousands_of_pieces():
    """Each piece is its own request; a thousand of them for one film is
    rude to the site and slower overall."""
    assert len(split(50 * 1024 * MB, 8)) <= 512


def _finish_time(pieces, speeds):
    """How long a download takes, in made-up time units.

    ``speeds`` is one number per connection: bytes a connection gets through
    per unit of time.  Each connection takes the next piece when it is free,
    which is what a thread pool with fewer threads than pieces does.
    """
    import heapq
    free = [(0.0, n) for n in range(len(speeds))]
    heapq.heapify(free)
    for size in pieces:
        at, who = heapq.heappop(free)
        heapq.heappush(free, (at + size / speeds[who], who))
    return max(at for at, _who in free)


def test_a_slow_connection_no_longer_decides_when_the_file_finishes():
    """The complaint, as arithmetic.

    Four connections, one of them ten times slower than the rest — a server
    throttling one, a bad route, packet loss.  With one piece per connection
    that slow connection owns a quarter of the file and everyone else waits
    for it; that is the download sitting at 99% at 80 KB/s.  Taking pieces
    from a queue hands the slow connection only as much as it can carry.
    """
    total = 1024 * MB
    speeds = [10.0, 10.0, 10.0, 1.0]        # the last one is the straggler

    one_each = _finish_time(_sizes(split(total, 4, max_pieces=4)), speeds)
    from_a_queue = _finish_time(_sizes(split(total, 4)), speeds)

    assert from_a_queue < one_each / 2, (
        f'a queue finished in {from_a_queue:.0f} against {one_each:.0f}: '
        'not the improvement this change exists for')
    # And the whole file is still downloaded, not merely downloaded faster.
    assert sum(_sizes(split(total, 4))) == total


def test_every_connection_keeps_working_until_near_the_end():
    """With one piece each, three connections finish early and idle.  Taking
    from a queue, nobody stops until the work runs out."""
    import concurrent.futures

    ranges = split(64 * MB, 4)
    handled = {}

    def fetch(index):
        handled.setdefault(threading.current_thread().name, []).append(index)
        time.sleep(0.02)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for item in [pool.submit(fetch, n) for n in range(len(ranges))]:
            item.result()

    assert len(ranges) > 4
    assert max(len(got) for got in handled.values()) > 1, (
        'no connection took a second piece, so nothing was shared out')
    assert sorted(n for got in handled.values() for n in got) == list(
        range(len(ranges)))


# ── resuming a download that was cut up the old way ──────────────────────

def test_a_resumed_download_is_recut_without_losing_a_byte():
    """A paused download carries the layout it was started with, so one
    begun before pieces were made small still crawls at the end.  What has
    arrived must survive the recut exactly."""
    from siphon.sites.downloader import _resplit_unfinished

    total = 1024 * MB
    old = [(0, 268435455), (268435456, 536870911),
           (536870912, 805306367), (805306368, total - 1)]
    written = [268435456, 268435456, 268435456, 10 * MB]

    ranges, got = _resplit_unfinished(old, written)

    assert sum(got) == sum(written)          # nothing re-downloaded
    assert len(ranges) > len(old)
    covered = sorted(ranges)
    assert covered[0][0] == 0
    assert covered[-1][1] == total - 1
    for (_a, b), (c, _d) in zip(covered, covered[1:]):
        assert c == b + 1                    # no gap, no overlap
    assert sum(end - start + 1 for start, end in ranges) == total


def test_the_part_already_on_disk_stays_one_piece():
    """Its bytes are there; cutting it up would only invite re-downloading."""
    from siphon.sites.downloader import _resplit_unfinished
    ranges, got = _resplit_unfinished([(0, 100 * MB - 1)], [40 * MB])
    assert ranges[0] == (0, 40 * MB - 1)
    assert got[0] == 40 * MB


def test_a_finished_piece_is_left_alone():
    from siphon.sites.downloader import _resplit_unfinished
    ranges, got = _resplit_unfinished([(0, 99)], [100])
    assert ranges == [(0, 99)]
    assert got == [100]


def test_an_untouched_piece_is_cut_up_from_the_start():
    from siphon.sites.downloader import _resplit_unfinished
    ranges, got = _resplit_unfinished([(0, 32 * MB - 1)], [0])
    assert len(ranges) == 4
    assert got == [0, 0, 0, 0]
    assert ranges[0][0] == 0 and ranges[-1][1] == 32 * MB - 1


# ── the whole thing, against a real server ───────────────────────────────

def _ranged_server(slow_after=None, delay=0.0, size=3 * MB, asked=None,
                   stall_for=0.0):
    """A server that honours Range requests, optionally crawling for bytes
    past ``slow_after`` — a server throttling the end of a file."""
    import hashlib
    import http.server
    import os

    body = os.urandom(size)
    digest = hashlib.sha256(body).hexdigest()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_GET(self):
            wanted = self.headers.get('Range', '')
            if asked is not None:
                asked.append(wanted)
            first, _, last = wanted.partition('=')[2].partition('-')
            start = int(first or 0)
            end = int(last) if last else len(body) - 1
            end = min(end, len(body) - 1)
            piece = body[start:end + 1]
            self.send_response(206)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(len(piece)))
            self.send_header('Content-Range',
                             f'bytes {start}-{end}/{len(body)}')
            self.end_headers()
            if slow_after is not None and start >= slow_after and stall_for:
                # A connection that goes quiet in the middle of a piece.
                self.wfile.write(piece[:64 * 1024])
                self.wfile.flush()
                time.sleep(stall_for)
            elif slow_after is not None and start >= slow_after and delay:
                for at in range(0, len(piece), 64 * 1024):
                    self.wfile.write(piece[at:at + 64 * 1024])
                    time.sleep(delay)
            else:
                self.wfile.write(piece)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_address[1]}/v.mp4', digest


def _download(url, where, workers=4):
    """Run the real ranged downloader and return the file's digest."""
    import hashlib
    from siphon.sites import downloader as dl

    job = dl.MediaSite.__new__(dl.MediaSite)
    job._direct_url = url
    job._direct_cookies = {}
    job._extra_headers = {}
    job._cancel_job = False
    job._progress_callback = None
    job._t2_executor = None
    job.direct_site_name = 'test'
    job._max_workers = workers
    job.direct_range_workers_max = workers
    job._dest_folder = str(where)

    part = str(where / 'v.mp4.part')
    out = job._download_direct_ranges(part, url, time.time())
    assert out is not None, 'the server refused ranged downloading'
    with open(part, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def test_a_file_downloaded_in_pieces_is_byte_for_byte_the_file(tmp_path):
    """Everything above only matters if the file still arrives whole."""
    server, url, digest = _ranged_server()
    try:
        assert _download(url, tmp_path) == digest
    finally:
        server.shutdown()


def test_a_server_that_throttles_the_end_still_gives_the_whole_file(tmp_path):
    """The case this work exists for: the tail crawls, connections take
    over parts of it, and the file must still be exactly right."""
    server, url, digest = _ranged_server(slow_after=2 * MB, delay=0.01)
    try:
        assert _download(url, tmp_path) == digest
    finally:
        server.shutdown()


def test_connections_take_over_the_slow_tail_rather_than_waiting(tmp_path):
    """Smaller pieces shorten the finish; they do not end it, because the
    last piece is still one connection.  When nothing is left to pick up,
    a free connection cuts into what is still going.

    Counted by the requests the server sees: one per piece if nobody helps,
    more than that once the tail is shared out.
    """
    requests = []
    server, url, digest = _ranged_server(
        slow_after=16 * MB, delay=0.02, size=24 * MB, asked=requests)
    try:
        assert _download(url, tmp_path) == digest
    finally:
        server.shutdown()

    # Where each request began.  A piece is asked for from its own start,
    # so a request beginning in the middle of a piece can only be a
    # connection that took over someone else's tail.  (The very first
    # request is the one-byte probe that asks whether ranges work at all.)
    starts = set()
    for asked in requests:
        first = asked.partition('=')[2].partition('-')[0]
        if first.isdigit():
            starts.add(int(first))
    boundaries = {start for start, _end in split(24 * MB, 4)}

    took_over = starts - boundaries
    assert took_over, (
        f'every request began at a piece boundary ({sorted(starts)}): '
        'nobody took over the slow tail, so one connection finished the '
        'file alone')


def test_pause_does_not_wait_for_a_connection_that_has_gone_quiet(tmp_path):
    """The bug: Pause stopped the download but its worker waited for every
    connection to finish its current read.  One stalled at the end of the file
    (the 16 KB/s crawl) held the worker for as long as the read lasted, the
    old download still counted as running, and Resume did nothing."""
    server, url, _digest = _ranged_server(slow_after=6 * MB, size=24 * MB,
                                          stall_for=12)
    try:
        from siphon.sites import downloader as dl
        job = dl.MediaSite.__new__(dl.MediaSite)
        job._direct_url = url
        job._direct_cookies = {}
        job._extra_headers = {}
        job._cancel_job = False
        job._progress_callback = None
        job._t2_executor = None
        job.direct_site_name = 'test'
        job._max_workers = 4
        job.direct_range_workers_max = 4
        job._dest_folder = str(tmp_path)
        finished = {}

        def run():
            finished['out'] = job._download_direct_ranges(
                str(tmp_path / 'v.mp4.part'), url, time.time())
            finished['at'] = time.time()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        time.sleep(1.5)                  # connections are now stuck
        job._cancel_job = True
        asked_at = time.time()
        worker.join(5)
        assert not worker.is_alive(), 'the worker is still waiting on a stuck connection'
        assert finished['at'] - asked_at < 3
        # What had arrived is kept, so Resume carries on from it.
        assert (tmp_path / 'v.mp4.part.state.json').exists()
    finally:
        server.shutdown()
