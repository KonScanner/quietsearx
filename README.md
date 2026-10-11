# quietsearx

A hardened SearXNG metasearch instance for one person. It runs with Docker
Compose. It resolves every name over DNS-over-TLS, it can send every engine
request through Tor, and it can generate decoy searches that hide how often
you search.

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.13-blue)
![Compose](https://img.shields.io/badge/docker-compose-blue)

## What this is

SearXNG is a metasearch engine. It sends your query to other search engines
and it returns the results. The engines see the instance. They do not see
your browser.

This repository adds four things to a plain SearXNG instance.

1. A local CoreDNS resolver. It forwards every name lookup to Mullvad over
   DNS-over-TLS.
2. A settings file that removes identifying details from the outgoing
   requests.
3. An optional Tor container. It hides your address from the search engines.
4. An optional cover traffic generator. It sends decoy searches at random
   times.

Items 3 and 4 are off by default. Read the warnings before you turn them on.

## What is inside

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | The service definitions. |
| `searxng/settings.yml` | The SearXNG configuration. |
| `searxng/favicons.toml` | The favicon resolver and cache defaults. |
| `searxng/limiter.toml` | The bot detection defaults. |
| `coredns/Corefile` | The DNS resolver configuration. |
| `cover/cover.py` | The decoy search generator. |
| `cover/test_cover.py` | The tests for the generator. |
| `.env.example` | The template for your local settings. |
| `Makefile` | The check command. |

## Requirements

- Docker Engine with the Compose plugin.
- Python 3.13 or later, to run the tests. The containers do not need it.

## Start

Step 1. Create your `.env` file. The instance does not start without a
secret key.

```bash
cp .env.example .env
echo "SEARXNG_SECRET=$(openssl rand -hex 32)" >> .env
```

Step 2. Start the containers.

```bash
docker compose up -d
```

Step 3. Open http://localhost:47821

## Stop

```bash
docker compose down          # stop the containers
docker compose down -v       # stop and delete the Valkey volume
```

## Other commands

```bash
docker compose logs -f searxng                 # show the logs
docker compose restart searxng                 # apply a change to settings.yml
docker compose pull && docker compose up -d    # update the images
```

## Configuration

Set these values in your `.env` file. Only the first one is required.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SEARXNG_SECRET` | none | The session key. Generate it with `openssl rand -hex 32`. |
| `SEARXNG_PORT` | `47821` | The host port for the web interface. |
| `COVER_MEAN_INTERVAL` | `180` | The mean seconds between decoy searches. |
| `COVER_USER_AGENT` | a Chrome string | The User-Agent for decoy searches. |
| `COVER_LOG_QUERIES` | `0` | Set to `1` to write the decoy text to the log. |

The `.env` file stays out of git. See `.gitignore`.

## JSON API

The `json` format is on. Use it from a script or an agent.

```bash
curl -s 'http://localhost:47821/search?q=docker+compose&format=json' | jq '.results[0]'
```

The `csv` and `rss` formats are also on.

## Add the instance to Chrome

### Method 1: let Chrome find it

1. Open http://localhost:47821 in Chrome.
2. Run one search on the page.
3. Open `chrome://settings/searchEngines`.
4. Find **Local SearXNG** under *Inactive shortcuts*.
5. Click the three dots. Select **Activate**.

Chrome reads the OpenSearch descriptor at `/opensearch.xml`. This method also
gives you search suggestions as you type.

### Method 2: add it by hand

1. Open `chrome://settings/searchEngines`.
2. Click **Add** beside *Site search*.
3. Enter these values:

| Field | Value |
| --- | --- |
| Name | `SearXNG` |
| Shortcut | `sx` |
| URL with %s in place of query | `http://localhost:47821/search?q=%s` |

4. Click **Save**.

To search, type `sx` in the address bar, press Tab, then type your words.

### Make it the default search engine

1. Open `chrome://settings/searchEngines`.
2. Find your entry under *Site search*.
3. Click the three dots. Select **Make default**.

**Warning.** Chrome shows an error page for every search when the containers
do not run. Start the containers before you make this change.

## DNS

All name lookups from the SearXNG container go to **base.dns.mullvad.net**
over DNS-over-TLS on port 853. The `mullvad-dns` container runs CoreDNS and
does the encryption. See `coredns/Corefile`.

`base.dns.mullvad.net` blocks advertisements, trackers, and malware.

Check that it works. The first command gives no result. The second gives an
address.

```bash
docker exec searxng getent hosts doubleclick.net    # blocked
docker exec searxng getent hosts wikipedia.org      # allowed
```

To use a different Mullvad profile, change the address in `coredns/Corefile`.
Then run `docker compose restart mullvad-dns`.

| Address | Profile | Blocks |
| --- | --- | --- |
| 194.242.2.2 | `dns` | Nothing |
| 194.242.2.3 | `adblock` | Advertisements, trackers |
| 194.242.2.4 | `base` | Advertisements, trackers, malware |
| 194.242.2.5 | `extended` | The above, and social media |
| 194.242.2.6 | `family` | The above, and adult content, gambling |
| 194.242.2.9 | `all` | The above, and social media |

The certificate name must agree with the address. Change `tls_servername` in
the same file.

## Metadata protection

The instance already does these things:

| Measure | Effect |
| --- | --- |
| DNS-over-TLS to Mullvad | Your network operator cannot read the names you look up. |
| `query_in_title: false` | The query stays out of the page title, the browser history, and screen recordings. |
| `enable_http2: false` | HTTP/1.1 gives a more common TLS fingerprint than HTTP/2. |
| `useragent_suffix: ""` | Nothing identifies this instance to the search engines. |
| `image_proxy: true` | Image hosts see the instance, not your browser. |
| SearXNG itself | The search engines see the instance, not your browser. |

Two more measures are available. Both are off by default.

### Egress over Tor

Every engine request leaves through the Tor network. The search engines then
see a Tor exit address, not your address.

1. Open `searxng/settings.yml`. Remove the `#` from the `using_tor_proxy`
   block. Delete the two `inactive` onion engine entries in the `engines`
   block at the same time.
2. Start the container:

```bash
docker compose --profile tor up -d
```

Check the result:

```bash
docker run --rm --network quietsearx_searxng docker.io/curlimages/curl:latest \
  -s --socks5-hostname tor:9050 https://check.torproject.org/api/ip
```

**Warning.** Many search engines block or challenge Tor exit addresses.
Google and Bing often return a CAPTCHA. Searches also become slower. Test
your engines after you turn this on. Turn it off with
`docker compose --profile tor down`.

### Cover traffic

The `cover-traffic` container sends decoy searches. The delay between two
decoys follows an exponential distribution, so the traffic is a Poisson
process. The intervals are memoryless. An observer cannot predict the next
request from the requests before it.

```bash
docker compose --profile cover up -d
docker compose logs -f cover-traffic
```

Set the mean interval in seconds. The default is 180.

```bash
echo "COVER_MEAN_INTERVAL=300" >> .env
docker compose --profile cover up -d
```

Edit the `SUBJECTS` list in `cover/cover.py` to match your own subjects.
Decoys that do not resemble your real searches give less protection.

The generator applies four rules.

1. It draws every delay and every word from `random.SystemRandom`. That
   source reads the operating system entropy pool. The default generator of
   the `random` module is a Mersenne Twister. An observer can recover the
   state of a Mersenne Twister from its output and then predict every later
   value. A predictable schedule gives no protection.
2. It sends a browser `User-Agent`. A request that carries
   `Python-urllib/3.13` is easy to separate from a real search in the
   SearXNG log. Set `COVER_USER_AGENT` to the value that your own browser
   sends.
3. It keeps the decoy text out of the log. A log that lists every decoy lets
   a reader subtract the decoys from the SearXNG log and recover your real
   searches. Set `COVER_LOG_QUERIES=1` only when you debug the generator.
4. It stops at once on SIGTERM. The script runs as process 1 in the
   container. The kernel does not apply the default action of a signal to
   process 1, so a process with no handler ignores SIGTERM and waits for
   SIGKILL.

**Warning.** Decoy searches use bandwidth. They also count against the rate
limits of the search engines. A short interval can cause a CAPTCHA.

### What this does not do

Cover traffic raises the cost of traffic analysis. It does not remove the
signal. Your real searches arrive on top of the decoy process, so an observer
who counts requests over a long period still sees a rate above the decoy
rate. A design that hides the rate must send on a fixed schedule and must
carry a real query in place of a decoy when one is waiting. This generator
runs beside SearXNG. It does not see your real queries, so it cannot do that.

This setup is **not** a mixnet. Nym gives properties that Docker Compose
cannot give:

| Nym provides | This setup |
| --- | --- |
| Sphinx packets of one fixed size | No. Packet sizes vary with the query. |
| A per hop random delay at each mix node | No. Requests go out at once. |
| Continuous cover traffic between every node | Only decoys from this instance. |
| Protection against an observer who sees the whole network | No. Tor and this setup both fail against that adversary. |

Tor protects against an observer of one link. It does not protect against an
observer who watches both ends at the same time.

To use Nym in place of Tor, run a `nym-socks5-client`. Then point
`outgoing.proxies` at its SOCKS5 port. The change in `searxng/settings.yml`
is the address only.

## Development

Run the full check before every commit. It runs the linter, the formatter
check, the tests, and the Compose file validation.

```bash
make check
```

Run one part on its own:

```bash
make lint               # ruff check and ruff format --check
make test               # python3 -m unittest
make compose-validate   # docker compose config
make format             # apply the formatter and the safe fixes
```

The lint configuration lives in `pyproject.toml`. The repository is not a
Python package, so the file carries no package metadata.

## Contributing

The `main` branch is protected. Direct pushes to `main` are blocked.

1. Create a branch.
2. Open a pull request.
3. Wait for a review. The maintainer approves every change before it merges.

Run `make check` before you open the pull request. A change that fails the
check does not merge.

## License

MIT. See [LICENSE](LICENSE).

## Notes

- The rate limiter is off. This is correct for a private local instance. Set
  `limiter: true` in `searxng/settings.yml` when you make the instance
  public.
- The container owns `searxng/`, so your user cannot edit `settings.yml`
  directly. Take ownership first:

  ```bash
  sudo chown -R "$USER" searxng/
  # edit searxng/settings.yml, then:
  sudo chown -R 977:977 searxng/
  docker compose restart searxng
  ```

  The app runs as user `searxng`, uid 977. A file that your user owns stays
  readable for the app when its mode is `644`. The app cannot change the
  ownership itself.
- The onion engines `ahmia` and `torch` are `inactive` in
  `searxng/settings.yml`. SearXNG does not load them without Tor, and it
  writes one error per engine at every start. Delete the two entries when you
  turn on the tor profile.
- The image runs granian, not uWSGI. It starts one worker with four threads.
  The old `SEARXNG_UWSGI_WORKERS` and `SEARXNG_UWSGI_THREADS` variables had
  no effect on it.
- Select the search engines in the web interface. Open **Preferences** >
  **Engines**.
