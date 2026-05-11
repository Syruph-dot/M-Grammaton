import threading
import time

from request_pool import PoolResult, RequestPool


def test_request_pool_defers_remaining_requests_to_next_cycle():
    pool = RequestPool(window_seconds=0.2, token_budget=5)
    start = time.monotonic()
    finish_times = {}
    results = {}
    lock = threading.Lock()
    start_gate = threading.Barrier(4)

    def submit_job(name, tokens):
        start_gate.wait()
        result = pool.submit(lambda: PoolResult(name, tokens))
        with lock:
            results[name] = result
            finish_times[name] = time.monotonic() - start

    threads = [
        threading.Thread(target=submit_job, args=("first", 3)),
        threading.Thread(target=submit_job, args=("second", 3)),
        threading.Thread(target=submit_job, args=("third", 3)),
    ]

    for thread in threads:
        thread.start()
    start_gate.wait()
    for thread in threads:
        thread.join()

    pool.close()

    assert results == {"first": "first", "second": "second", "third": "third"}
    assert max(finish_times.values()) >= 0.18