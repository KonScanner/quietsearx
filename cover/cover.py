"""Cover traffic generator for a local SearXNG instance.

The generator sends decoy searches at random intervals. The intervals follow
an exponential distribution, so the traffic has no fixed period. An observer
cannot predict the next request from the requests before it.

The purpose is to hide the count and the timing of your real searches.

This is not a mixnet. It does not hide the content of one query from the
search engine. It only makes your real queries harder to isolate.

The environment supplies the configuration:

    TARGET          Base URL of the SearXNG instance.
    MEAN_INTERVAL   Mean number of seconds between decoy searches.
    USER_AGENT      The User-Agent header for each decoy search.
    LOG_QUERIES     Set to 1 to write the decoy text to the log.
"""

from __future__ import annotations

import http.client
import logging
import math
import os
import random
import signal
import threading
import types
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn

LOG = logging.getLogger("cover")

# A cryptographically secure source of randomness. The value of cover traffic
# is that an observer cannot predict or replay the schedule. The default
# generator of the random module is a Mersenne Twister. Its internal state is
# recoverable from its output, so it is the wrong tool for this purpose.
RNG = random.SystemRandom()

# The read limit for one response body. The generator discards the body. The
# read only makes the request look like a normal page load.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# The time limit for one decoy request, in seconds.
REQUEST_TIMEOUT = 30.0

# The default User-Agent. Set the USER_AGENT variable to the value that your
# own browser sends. A decoy that carries a different User-Agent from your
# real searches is easy to separate from them in the SearXNG log.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

# Subjects that a person plausibly searches for. Edit this list to match your
# own subjects. Decoys that do not resemble your real searches give less
# protection.
SUBJECTS: tuple[str, ...] = (
    "weather",
    "recipe",
    "train times",
    "dictionary",
    "population",
    "opening hours",
    "conversion",
    "python list",
    "docker volume",
    "grammar rules",
    "bicycle repair",
    "coffee beans",
    "linux kernel",
    "postgres index",
    "guitar chords",
    "tide table",
    "unit price",
    "map scale",
    "boiling point",
    "prime numbers",
    "sourdough starter",
    "rust lifetime",
    "http status",
    "regex lookahead",
    "yaml anchor",
)

# Words that turn a subject into a natural query. The empty entries keep a
# bare subject as the most frequent shape.
PREFIXES: tuple[str, ...] = ("", "", "", "how to", "what is", "best")
SUFFIXES: tuple[str, ...] = ("", "", "", "example", "meaning", "explained", "near me")


@dataclass(frozen=True, slots=True)
class Config:
    """The settings for one run of the generator."""

    target: str
    mean_interval: float
    user_agent: str
    log_queries: bool


def _fail(message: str) -> NoReturn:
    """Write an error message and stop the program."""
    LOG.error("%s", message)
    raise SystemExit(2)


def load_config(env: Mapping[str, str]) -> Config:
    """Read the configuration from the environment.

    The function stops the program when a value is absent or unusable. A
    container restarts on failure, so the message must say how to correct
    the value.
    """
    target = env.get("TARGET", "http://searxng:8080").rstrip("/")
    scheme = urllib.parse.urlparse(target).scheme
    if scheme not in ("http", "https"):
        _fail(
            f"TARGET must be an http or https URL. Got {target!r} with "
            f"scheme {scheme!r}. Example: http://searxng:8080"
        )

    raw_interval = env.get("MEAN_INTERVAL", "180")
    try:
        mean_interval = float(raw_interval)
    except ValueError:
        _fail(f"MEAN_INTERVAL must be a number of seconds. Got {raw_interval!r}. Example: 180")
    if not math.isfinite(mean_interval) or mean_interval <= 0:
        _fail(
            f"MEAN_INTERVAL must be a finite number greater than 0. "
            f"Got {mean_interval!r}. Example: 180"
        )

    return Config(
        target=target,
        mean_interval=mean_interval,
        user_agent=env.get("USER_AGENT", DEFAULT_USER_AGENT),
        log_queries=env.get("LOG_QUERIES", "0").strip().lower() in ("1", "true", "yes"),
    )


def build_query(rng: random.Random) -> str:
    """Return one decoy query that reads like a natural search."""
    parts = (rng.choice(PREFIXES), rng.choice(SUBJECTS), rng.choice(SUFFIXES))
    return " ".join(part for part in parts if part)


def next_delay(rng: random.Random, mean_interval: float) -> float:
    """Return the number of seconds to wait before the next decoy search.

    The delay follows an exponential distribution with the given mean. A
    sequence of such delays is a Poisson process. The intervals are
    memoryless, so an observer cannot predict the next request.
    """
    return rng.expovariate(1.0 / mean_interval)


def build_request(config: Config, query: str) -> urllib.request.Request:
    """Return the HTTP request for one decoy search."""
    url = f"{config.target}/search?" + urllib.parse.urlencode({"q": query})
    # load_config accepts an http or https target only, so the scheme is safe.
    return urllib.request.Request(  # noqa: S310
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": config.user_agent,
        },
    )


def send(config: Config, query: str) -> None:
    """Send one decoy search and discard the response body."""
    request = build_request(config, query)
    # The scheme of the target is http or https. load_config checks it.
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310
        response.read(MAX_RESPONSE_BYTES)


def install_signal_handlers(stop: threading.Event) -> None:
    """Make SIGTERM and SIGINT stop the loop.

    The container runs this script as process 1. The kernel does not apply
    the default action of a signal to process 1, so a process with no
    handler ignores SIGTERM and waits for SIGKILL. The kernel does deliver
    a signal that has a handler.
    """

    def handle(_signum: int, _frame: types.FrameType | None) -> None:
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, handle)


def run(config: Config, stop: threading.Event, rng: random.Random = RNG) -> None:
    """Send decoy searches until the stop event is set."""
    sent = 0
    failed = 0
    while not stop.is_set():
        # Event.wait returns as soon as the event is set. time.sleep does
        # not: Python resumes an interrupted sleep, so a signal that arrives
        # during a long sleep cannot end it.
        if stop.wait(next_delay(rng, config.mean_interval)):
            break
        query = build_query(rng)
        try:
            send(config, query)
        except (OSError, http.client.HTTPException) as exc:
            failed += 1
            LOG.warning("decoy %d failed: %s: %s", sent + failed, type(exc).__name__, exc)
            continue
        sent += 1
        # The decoy text stays out of the log by default. A log that lists
        # every decoy lets a reader subtract the decoys from the SearXNG log
        # and recover the real searches.
        if config.log_queries:
            LOG.info("decoy %d sent: %s", sent, query)
        else:
            LOG.info("decoy %d sent", sent)
    LOG.info("stopped. sent=%d failed=%d", sent, failed)


def main() -> int:
    """Run the generator. Return the exit code."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(os.environ)
    stop = threading.Event()
    install_signal_handlers(stop)
    LOG.info(
        "cover traffic on. target=%s mean_interval=%.1fs log_queries=%s",
        config.target,
        config.mean_interval,
        config.log_queries,
    )
    run(config, stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
