"""The speed a time-left estimate should be worked out from.

A speed limit is a ceiling, not a speed.  With the limit set to 1.5 MB/s on a
connection that is really giving 500 KB/s, "time left" worked out from the
limit is three times too short; with the limit set far above what the line can
do it is absurdly short.  The estimate uses what is actually arriving, and
falls back to the limit only while nothing is arriving yet.
"""

from __future__ import annotations

import time

# How far back the average looks, in seconds.  Short enough to follow a real
# change in speed, long enough that one fast second does not move the estimate.
WINDOW = 10.0


class SpeedAverage:
    """A running average of a measured speed (bytes per second)."""

    def __init__(self, window=WINDOW, clock=time.monotonic):
        self.window = float(window)
        self._clock = clock
        self._value = 0.0
        self._at = None

    def update(self, measured):
        """Feed the speed measured right now; returns the smoothed speed."""
        now = self._clock()
        measured = max(0.0, float(measured or 0))
        if measured <= 0:
            # Nothing is arriving: no speed to average, and an old figure
            # must not outlive the transfer it was measured on.
            self._value, self._at = 0.0, None
            return 0.0
        if self._at is None or self._value <= 0:
            self._value = measured
        else:
            step = max(0.0, now - self._at)
            weight = min(1.0, step / self.window) if self.window else 1.0
            self._value += (measured - self._value) * max(weight, 0.05)
        self._at = now
        return self._value


def pick(measured, limit):
    """(speed, from_limit): what to divide by, and whether it is the limit.

    The measured speed whenever there is one; the limit only as a stand-in
    while nothing has started arriving.
    """
    if measured and measured > 0:
        return float(measured), False
    if limit and limit > 0:
        return float(limit), True
    return 0.0, False
