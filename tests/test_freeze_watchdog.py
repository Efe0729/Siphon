import time

from siphon.core import crashlog


class _App:
    """A window that never answers: it stores the callbacks and never runs them."""
    _is_closing = False

    def after(self, _ms, _callback):
        pass


def test_a_window_that_stops_answering_is_written_down():
    now = [0.0]
    said = []
    app = _App()
    crashlog.start_freeze_watchdog(app, limit=5, clock=lambda: now[0],
                                   report=said.append, every=0.01)
    now[0] = 30.0                       # 30 seconds and nobody answered
    for _ in range(200):
        if said:
            break
        time.sleep(0.01)
    app._is_closing = True
    assert said and '[freeze]' in said[0]
    assert 'thread' in said[0]          # it names what the threads are doing
    assert len(said) == 1               # once, not every two seconds


def test_a_window_that_answers_is_left_alone():
    now = [0.0]
    said = []

    class Alive(_App):
        def after(self, _ms, callback):
            now[0] += 1.0
            callback_holder.append(callback)

    callback_holder = []
    app = Alive()
    crashlog.start_freeze_watchdog(app, limit=5, clock=lambda: now[0],
                                   report=said.append, every=0.01)
    for _ in range(10):
        callback_holder.pop(0)()
        time.sleep(0.01)
    app._is_closing = True
    assert said == []
