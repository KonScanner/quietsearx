"""Report which enabled SearXNG engines answer a test query.

The SearXNG container keeps no log (see docker-compose.yml): a warning that
names a failed engine also contains the query text in the engine URL. This
script asks the JSON API for one engine at a time instead.

Run it from the repository root:

    python3 scripts/check_engines.py
    python3 scripts/check_engines.py --query "free knitting pattern"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:47821"
DEFAULT_QUERY = "book"
DEFAULT_TIMEOUT = 20.0

# The engine truth values. "ok" is the only one that counts as working.
OK = "ok"
FAILED = "failed"
FILTERED = "filtered"
EMPTY = "empty"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Return the command line arguments."""
    parser = argparse.ArgumentParser(description="Report which SearXNG engines answer.")
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"SearXNG base URL (default: {DEFAULT_URL})"
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help=f"Test query (default: {DEFAULT_QUERY!r})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Seconds to wait for one answer (default: {DEFAULT_TIMEOUT})",
    )
    return parser.parse_args(argv)


def get_json(url: str, params: dict[str, str] | None, timeout: float) -> dict[str, Any]:
    """Return the JSON object at the URL, with the query parameters added."""
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    # The URL comes from the operator and stays on the local network.
    with urllib.request.urlopen(f"{url}{query}", timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        msg = "the instance did not answer with a JSON object"
        raise TypeError(msg)
    return payload


def general_engines(config: dict[str, Any]) -> list[str]:
    """Return the enabled engine names that search the general category."""
    engines = config.get("engines")
    if not isinstance(engines, list):
        return []
    names: list[str] = []
    for engine in engines:
        if not isinstance(engine, dict):
            continue
        name = engine.get("name")
        categories = engine.get("categories")
        if not isinstance(name, str) or not engine.get("enabled"):
            continue
        if isinstance(categories, list) and "general" in categories:
            names.append(name)
    return names


def result_engines(result: dict[str, Any]) -> set[str]:
    """Return the engine names that contributed one result."""
    names = result.get("engines")
    if isinstance(names, list):
        return {str(name) for name in names}
    engine = result.get("engine")
    return {str(engine)} if engine else set()


def verdict(payload: dict[str, Any], engine: str) -> tuple[str, str]:
    """Return the state of one engine and the text that explains it."""
    results = payload.get("results")
    results = results if isinstance(results, list) else []
    unresponsive = payload.get("unresponsive_engines")
    unresponsive = unresponsive if isinstance(unresponsive, list) else []

    for entry in unresponsive:
        if isinstance(entry, (list, tuple)) and entry and entry[0] == engine:
            reason = str(entry[1]) if len(entry) > 1 else "no reason"
            return FAILED, reason

    answered = [
        result
        for result in results
        if isinstance(result, dict) and engine in result_engines(result)
    ]
    if answered:
        return OK, f"{len(answered)} result(s)"

    answered_by = {
        name for result in results if isinstance(result, dict) for name in result_engines(result)
    }
    if unresponsive or answered_by:
        # SearXNG fills this payload from other engines when it does not load
        # the named one: the engines parameter is ignored in that case.
        return FILTERED, "the instance ignored the engine, it may be inactive"
    return EMPTY, "no result for the test query"


def probe(base_url: str, engine: str, query: str, timeout: float) -> tuple[str, str]:
    """Ask one engine through the JSON API and return its verdict."""
    payload = get_json(
        f"{base_url}/search",
        {"q": query, "format": "json", "engines": engine, "timeout_limit": "5"},
        timeout,
    )
    return verdict(payload, engine)


def main(argv: list[str] | None = None) -> int:
    """Print the state of each enabled general engine and return an exit code."""
    args = parse_args(argv)
    base_url = args.url.rstrip("/")
    try:
        config = get_json(f"{base_url}/config", None, args.timeout)
    except (urllib.error.URLError, OSError, TypeError, ValueError) as error:
        print(f"Cannot reach SearXNG at {base_url}: {error}", file=sys.stderr)
        return 2

    engines = general_engines(config)
    if not engines:
        print(f"No enabled general engine at {base_url}.", file=sys.stderr)
        return 2

    width = max(len(name) for name in engines)
    working = 0
    for engine in sorted(engines):
        try:
            state, detail = probe(base_url, engine, args.query, args.timeout)
        except (urllib.error.URLError, OSError, TypeError, ValueError) as error:
            state, detail = FAILED, str(error)
        if state == OK:
            working += 1
        print(f"{engine:<{width}}  {state:<8}  {detail}")
    print(f"\n{working} of {len(engines)} enabled general engine(s) answered.")
    return 0 if working else 1


if __name__ == "__main__":
    raise SystemExit(main())
