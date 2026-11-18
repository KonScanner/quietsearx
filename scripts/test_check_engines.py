"""Tests for the engine health check.

Run them with:

    python3 -m unittest discover -s scripts -t scripts -v
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import check_engines


def config_with(*engines: dict[str, object]) -> dict[str, object]:
    """Return a /config payload with the given engine entries."""
    return {"engines": list(engines)}


def result(url: str, engines: list[str]) -> dict[str, object]:
    """Return one /search result that names its engines."""
    return {"url": url, "engines": engines}


class TestGeneralEngines(unittest.TestCase):
    """general_engines must return only enabled engines of the general category."""

    def test_enabled_general_engines_are_returned(self) -> None:
        config = config_with(
            {"name": "bing", "enabled": True, "categories": ["general", "web"]},
            {"name": "mwmbl", "enabled": True, "categories": ["general"]},
        )
        self.assertEqual(check_engines.general_engines(config), ["bing", "mwmbl"])

    def test_disabled_and_other_categories_are_left_out(self) -> None:
        config = config_with(
            {"name": "bing", "enabled": True, "categories": ["general"]},
            {"name": "duckduckgo", "enabled": False, "categories": ["general"]},
            {"name": "kickass", "enabled": True, "categories": ["files"]},
        )
        self.assertEqual(check_engines.general_engines(config), ["bing"])

    def test_a_malformed_payload_returns_no_engine(self) -> None:
        self.assertEqual(check_engines.general_engines({}), [])
        self.assertEqual(check_engines.general_engines({"engines": "bing"}), [])


class TestVerdict(unittest.TestCase):
    """verdict must tell a working engine from a failed or unloaded one."""

    def test_a_named_engine_in_the_results_is_ok(self) -> None:
        payload = {"results": [result("https://example.com/a", ["bing"])]}
        self.assertEqual(check_engines.verdict(payload, "bing"), (check_engines.OK, "1 result(s)"))

    def test_an_unresponsive_engine_reports_the_reason(self) -> None:
        payload = {"results": [], "unresponsive_engines": [["duckduckgo", "CAPTCHA"]]}
        self.assertEqual(check_engines.verdict(payload, "duckduckgo"), ("failed", "CAPTCHA"))

    def test_results_from_other_engines_mean_the_engine_was_filtered(self) -> None:
        payload = {"results": [result("https://example.com/a", ["mwmbl"])]}
        state, _detail = check_engines.verdict(payload, "ginger")
        self.assertEqual(state, check_engines.FILTERED)

    def test_a_fallback_payload_means_the_engine_was_filtered(self) -> None:
        payload = {"results": [], "unresponsive_engines": [["brave", "suspended"]]}
        state, _detail = check_engines.verdict(payload, "mojeek")
        self.assertEqual(state, check_engines.FILTERED)

    def test_an_engine_with_no_result_is_empty(self) -> None:
        payload = {"results": [], "unresponsive_engines": []}
        self.assertEqual(
            check_engines.verdict(payload, "wikipedia"),
            (check_engines.EMPTY, "no result for the test query"),
        )

    def test_a_single_engine_field_is_read(self) -> None:
        payload = {"results": [{"url": "https://example.com/a", "engine": "seznam"}]}
        state, detail = check_engines.verdict(payload, "seznam")
        self.assertEqual((state, detail), (check_engines.OK, "1 result(s)"))


class TestMain(unittest.TestCase):
    """main must report the engines and return a useful exit code."""

    def test_a_working_engine_makes_the_check_pass(self) -> None:
        config = config_with({"name": "bing", "enabled": True, "categories": ["general"]})
        payload = {"results": [result("https://example.com/a", ["bing"])]}

        def fake_get_json(
            url: str, _params: dict[str, str] | None, _timeout: float
        ) -> dict[str, object]:
            return config if url.endswith("/config") else payload

        with patch.object(check_engines, "get_json", side_effect=fake_get_json):
            self.assertEqual(check_engines.main(["--url", "http://instance:8080"]), 0)

    def test_no_working_engine_makes_the_check_fail(self) -> None:
        config = config_with({"name": "brave", "enabled": True, "categories": ["general"]})
        payload = {"results": [], "unresponsive_engines": [["brave", "suspended"]]}

        def fake_get_json(
            url: str, _params: dict[str, str] | None, _timeout: float
        ) -> dict[str, object]:
            return config if url.endswith("/config") else payload

        with patch.object(check_engines, "get_json", side_effect=fake_get_json):
            self.assertEqual(check_engines.main(["--url", "http://instance:8080"]), 1)

    def test_an_unreachable_instance_returns_two(self) -> None:
        with patch.object(check_engines, "get_json", side_effect=OSError("refused")):
            self.assertEqual(check_engines.main(["--url", "http://instance:8080"]), 2)


if __name__ == "__main__":
    unittest.main()
