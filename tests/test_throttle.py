import time

from sandpaper_py.throttle import RateLimiter


def test_rate_limiter_disabled():
    rl = RateLimiter(0)
    start = time.monotonic()
    for _ in range(5):
        rl.wait("https://example.com")
    assert time.monotonic() - start < 0.1


def test_rate_limiter_spaces_calls():
    rl = RateLimiter(20.0)
    start = time.monotonic()
    rl.wait("https://example.com")
    rl.wait("https://example.com")
    rl.wait("https://example.com")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.10


def test_rate_limiter_isolates_hosts():
    rl = RateLimiter(2.0)
    start = time.monotonic()
    rl.wait("https://a.com")
    rl.wait("https://b.com")
    elapsed = time.monotonic() - start
    assert elapsed < 0.4
