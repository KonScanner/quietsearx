"""Tests for the cover traffic generator.

Run them with:

    python3 -m unittest discover -s cover -t cover -v
"""

from __future__ import annotations

import random
import statistics
import threading
import unittest

import cover


class TestLoadConfig(unittest.TestCase):
    """load_config must accept good values and stop on bad values."""

    def test_defaults_apply_when_the_environment_is_empty(self) -> None:
        config = cover.load_config({})
        self.assertEqual(config.target, "http://searxng:8080")
        self.assertEqual(config.mean_interval, 180.0)
        self.assertEqual(config.user_agent, cover.DEFAULT_USER_AGENT)
        self.assertFalse(config.log_queries)

    def test_trailing_slash_is_removed_from_the_target(self) -> None:
        config = cover.load_config({"TARGET": "http://searxng:8080/"})
        self.assertEqual(config.target, "http://searxng:8080")

    def test_https_target_is_accepted(self) -> None:
        config = cover.load_config({"TARGET": "https://search.example.com"})
        self.assertEqual(config.target, "https://search.example.com")

    def test_file_scheme_target_stops_the_program(self) -> None:
        with self.assertLogs(cover.LOG, level="ERROR") as captured:
            with self.assertRaises(SystemExit) as caught:
                cover.load_config({"TARGET": "file:///etc/passwd"})
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("http or https", captured.output[0])

    def test_a_bad_mean_interval_stops_the_program(self) -> None:
        for raw, expected in (
            ("0", "greater than 0"),
            ("-5", "greater than 0"),
            ("inf", "finite"),
            ("nan", "finite"),
            ("abc", "must be a number"),
            ("", "must be a number"),
        ):
            with self.subTest(raw=raw):
                with self.assertLogs(cover.LOG, level="ERROR") as captured:
                    with self.assertRaises(SystemExit) as caught:
                        cover.load_config({"MEAN_INTERVAL": raw})
                self.assertEqual(caught.exception.code, 2)
                self.assertIn(expected, captured.output[0])

    def test_log_queries_reads_several_true_values(self) -> None:
        for raw in ("1", "true", "TRUE", "yes", " Yes "):
            with self.subTest(raw=raw):
                self.assertTrue(cover.load_config({"LOG_QUERIES": raw}).log_queries)

    def test_log_queries_is_off_for_other_values(self) -> None:
        for raw in ("0", "false", "no", ""):
            with self.subTest(raw=raw):
                self.assertFalse(cover.load_config({"LOG_QUERIES": raw}).log_queries)


class TestBuildQuery(unittest.TestCase):
    """Every decoy query must come from the word pools."""

    def test_query_contains_one_known_subject(self) -> None:
        rng = random.Random(20260830)
        for _ in range(500):
            query = cover.build_query(rng)
            matches = [s for s in cover.SUBJECTS if s in query]
            self.assertEqual(len(matches), 1, msg=query)

    def test_query_has_no_leading_or_trailing_space(self) -> None:
        rng = random.Random(7)
        for _ in range(500):
            query = cover.build_query(rng)
            self.assertEqual(query, query.strip())
            self.assertNotIn("  ", query)

    def test_query_is_never_empty(self) -> None:
        rng = random.Random(99)
        for _ in range(500):
            self.assertTrue(cover.build_query(rng))

    def test_the_pool_produces_more_than_one_query(self) -> None:
        rng = random.Random(3)
        seen = {cover.build_query(rng) for _ in range(300)}
        self.assertGreater(len(seen), 50)


class TestNextDelay(unittest.TestCase):
    """The delay must follow an exponential distribution with the given mean."""

    def test_sample_mean_matches_the_configured_mean(self) -> None:
        rng = random.Random(12345)
        delays = [cover.next_delay(rng, 180.0) for _ in range(200_000)]
        self.assertAlmostEqual(statistics.mean(delays), 180.0, delta=2.0)

    def test_every_delay_is_non_negative(self) -> None:
        rng = random.Random(555)
        for _ in range(10_000):
            self.assertGreaterEqual(cover.next_delay(rng, 1.0), 0.0)

    def test_a_small_mean_gives_a_small_delay(self) -> None:
        rng = random.Random(2024)
        delays = [cover.next_delay(rng, 0.5) for _ in range(50_000)]
        self.assertAlmostEqual(statistics.mean(delays), 0.5, delta=0.02)


class TestBuildRequest(unittest.TestCase):
    """The decoy request must look like a browser request."""

    def setUp(self) -> None:
        self.config = cover.load_config({"TARGET": "http://searxng:8080"})

    def test_the_query_is_url_encoded(self) -> None:
        request = cover.build_request(self.config, "what is http status")
        self.assertEqual(
            request.full_url,
            "http://searxng:8080/search?q=what+is+http+status",
        )

    def test_a_query_with_punctuation_is_escaped(self) -> None:
        request = cover.build_request(self.config, "a&b=c #d")
        self.assertIn("q=a%26b%3Dc+%23d", request.full_url)
        self.assertNotIn(" ", request.full_url)

    def test_the_request_carries_the_configured_user_agent(self) -> None:
        request = cover.build_request(self.config, "weather")
        self.assertEqual(request.get_header("User-agent"), cover.DEFAULT_USER_AGENT)

    def test_the_default_user_agent_is_not_the_urllib_default(self) -> None:
        request = cover.build_request(self.config, "weather")
        self.assertNotIn("Python-urllib", request.get_header("User-agent"))

    def test_a_custom_user_agent_is_used(self) -> None:
        config = cover.load_config({"USER_AGENT": "Mozilla/5.0 (Test)"})
        request = cover.build_request(config, "weather")
        self.assertEqual(request.get_header("User-agent"), "Mozilla/5.0 (Test)")


class TestRun(unittest.TestCase):
    """The loop must stop at once and must not log the decoy text by default."""

    def test_a_set_stop_event_sends_nothing(self) -> None:
        config = cover.load_config({"MEAN_INTERVAL": "3600"})
        stop = threading.Event()
        stop.set()
        sent: list[str] = []
        original = cover.send
        cover.send = lambda cfg, query: sent.append(query)
        try:
            cover.run(config, stop)
        finally:
            cover.send = original
        self.assertEqual(sent, [])

    def test_the_loop_stops_when_the_event_is_set_during_a_wait(self) -> None:
        config = cover.load_config({"MEAN_INTERVAL": "600"})
        stop = threading.Event()
        threading.Timer(0.2, stop.set).start()
        original = cover.send
        cover.send = lambda cfg, query: None
        try:
            cover.run(config, stop)
        finally:
            cover.send = original

    def test_the_decoy_text_stays_out_of_the_log_by_default(self) -> None:
        config = cover.load_config({"MEAN_INTERVAL": "0.001"})
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        original = cover.send
        cover.send = lambda cfg, query: None
        try:
            with self.assertLogs(cover.LOG, level="INFO") as captured:
                cover.run(config, stop)
        finally:
            cover.send = original
        joined = " ".join(captured.output)
        for subject in cover.SUBJECTS:
            self.assertNotIn(subject, joined)

    def test_log_queries_writes_the_decoy_text(self) -> None:
        config = cover.load_config({"MEAN_INTERVAL": "0.001", "LOG_QUERIES": "1"})
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        original = cover.send
        cover.send = lambda cfg, query: None
        try:
            with self.assertLogs(cover.LOG, level="INFO") as captured:
                cover.run(config, stop)
        finally:
            cover.send = original
        joined = " ".join(captured.output)
        self.assertTrue(any(s in joined for s in cover.SUBJECTS))

    def test_a_network_error_does_not_stop_the_loop(self) -> None:
        config = cover.load_config({"MEAN_INTERVAL": "0.001"})
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        calls = []

        def failing_send(cfg: cover.Config, query: str) -> None:
            calls.append(query)
            raise OSError("connection refused")

        original = cover.send
        cover.send = failing_send
        try:
            with self.assertLogs(cover.LOG, level="WARNING") as captured:
                cover.run(config, stop)
        finally:
            cover.send = original
        self.assertGreater(len(calls), 1)
        self.assertTrue(any("failed" in line for line in captured.output))


class TestSignalHandlers(unittest.TestCase):
    """A signal must set the stop event."""

    def test_sigterm_sets_the_stop_event(self) -> None:
        import os
        import signal

        stop = threading.Event()
        previous_term = signal.getsignal(signal.SIGTERM)
        previous_int = signal.getsignal(signal.SIGINT)
        try:
            cover.install_signal_handlers(stop)
            os.kill(os.getpid(), signal.SIGTERM)
            self.assertTrue(stop.wait(2.0))
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            signal.signal(signal.SIGINT, previous_int)


if __name__ == "__main__":
    unittest.main()
