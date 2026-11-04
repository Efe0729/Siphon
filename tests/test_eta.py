from siphon.core import eta


def test_the_limit_is_only_used_while_nothing_is_moving():
    assert eta.pick(500_000, 1_500_000) == (500_000.0, False)
    assert eta.pick(0, 1_500_000) == (1_500_000.0, True)
    assert eta.pick(0, 0) == (0.0, False)


def test_a_limit_far_above_the_line_does_not_promise_two_minutes():
    # 100 MB/s limit, 500 KB/s really: 600 MB takes 20 minutes, not 6 seconds.
    speed, from_limit = eta.pick(500_000, 100_000_000)
    assert not from_limit
    assert 600_000_000 / speed == 1200


def test_the_average_follows_a_change_but_not_one_fast_second():
    now = [0.0]
    average = eta.SpeedAverage(window=10, clock=lambda: now[0])
    for _ in range(20):
        now[0] += 1
        steady = average.update(500_000)
    assert steady == 500_000
    now[0] += 1
    after_spike = average.update(5_000_000)
    assert after_spike < 1_500_000
    for _ in range(60):
        now[0] += 1
        later = average.update(1_000_000)
    assert 950_000 < later <= 1_000_000


def test_a_stopped_transfer_forgets_its_old_speed():
    now = [0.0]
    average = eta.SpeedAverage(clock=lambda: now[0])
    average.update(800_000)
    now[0] += 1
    assert average.update(0) == 0.0
    now[0] += 1
    assert average.update(300_000) == 300_000
