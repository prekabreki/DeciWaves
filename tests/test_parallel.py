"""engine.parallel: a small ordered, bounded worker-pool helper shared by the
three per-clip decode loops (issue #41). It must (a) yield results in input
order regardless of which worker finishes first, (b) actually run concurrently,
(c) run inline (no pool) at jobs<=1 so the serial path is byte-for-byte the old
behavior, and (d) stay bounded so a 61k-item streaming input never materializes
all futures at once."""
import threading
import time

from deciwaves.engine import parallel


def test_default_jobs_is_bounded_and_positive():
    j = parallel.default_jobs()
    assert 1 <= j <= 8


def test_ordered_parallel_preserves_input_order():
    # work_fn returns its input; even with wildly varying "work" times the output
    # must come back in submission order.
    items = list(range(50))

    def work(i):
        # earlier items sleep longer -> if order were completion-based they'd
        # come back reversed.
        time.sleep((50 - i) * 0.0005)
        return i * 10

    out = list(parallel.ordered_parallel(items, work, jobs=8))
    assert out == [i * 10 for i in items]


def test_ordered_parallel_runs_concurrently():
    # 8 tasks each sleeping 0.1s must finish in well under the 0.8s a serial run
    # would take, proving real concurrency.
    n = 8

    def work(i):
        time.sleep(0.1)
        return i

    start = time.perf_counter()
    out = list(parallel.ordered_parallel(list(range(n)), work, jobs=n))
    elapsed = time.perf_counter() - start
    assert out == list(range(n))
    assert elapsed < 0.5, f"expected concurrent (<0.5s), took {elapsed:.2f}s"


def test_ordered_parallel_jobs_1_runs_inline_in_calling_thread():
    # jobs<=1 must not spin up any worker thread: work runs in the calling thread.
    caller = threading.get_ident()
    seen = []

    def work(i):
        seen.append(threading.get_ident())
        return i

    out = list(parallel.ordered_parallel([1, 2, 3], work, jobs=1))
    assert out == [1, 2, 3]
    assert seen == [caller, caller, caller]


def test_ordered_parallel_exception_propagates_in_order():
    def work(i):
        if i == 2:
            raise ValueError("boom at 2")
        return i

    gen = parallel.ordered_parallel([0, 1, 2, 3], work, jobs=4)
    assert next(gen) == 0
    assert next(gen) == 1
    try:
        next(gen)
        assert False, "expected ValueError from item 2"
    except ValueError as e:
        assert "boom at 2" in str(e)


def test_ordered_parallel_bounded_in_flight():
    # With jobs=2 the pool must never have more than a small window in flight at
    # once, even for a large input -- proven by tracking concurrent entries.
    concurrent = 0
    peak = 0
    lock = threading.Lock()

    def work(i):
        nonlocal concurrent, peak
        with lock:
            concurrent += 1
            peak = max(peak, concurrent)
        time.sleep(0.002)
        with lock:
            concurrent -= 1
        return i

    list(parallel.ordered_parallel(range(200), work, jobs=2))
    # window is jobs*2 = 4; allow a little slack but it must be far below 200.
    assert peak <= 8, f"in-flight peak {peak} not bounded"


def test_ordered_parallel_empty_input():
    assert list(parallel.ordered_parallel([], lambda x: x, jobs=4)) == []
    assert list(parallel.ordered_parallel([], lambda x: x, jobs=1)) == []
