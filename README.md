# legoapi

A small API that returns the official localized name of a LEGO set, as LEGO itself
names it on lego.com. Rebrickable and similar sites only have English names;
this gives you for example the Swedish name of set 60348, "Månbil".

```
GET /60348?locale=sv-se   ->  {"name": "Månbil", ...}
```

Plain Python, no dependencies, one container.

## How it works

For each request the backend tries, in order:

1. **Cache**: a local SQLite file. Found names are kept forever, "not found" for 24 hours.
2. **LEGO GraphQL**: the endpoint the LEGO shop uses. Fast, but only knows sets currently in the shop.
3. **LEGO building instructions page**: slower, but also covers retired sets.

The first source that has the name answers, and the result is cached. No LEGO account
or token is needed. These are not official public APIs and LEGO may change them at any time.

## Setup

```sh
git clone https://github.com/robotman4/legoapi.git
cd legoapi

# API keys: one per line
mkdir -p volumes/data volumes/cache
cp keys.example.txt volumes/data/keys.txt
openssl rand -hex 24          # generate a key, put it in keys.txt

# the container runs as user nobody (uid 65534) and must be able to write the cache
sudo chown 65534:65534 volumes/cache

docker compose up -d --build
```

The API is now on `http://localhost:8080`. Keys are re-read on every request, so you can
add or remove keys in `keys.txt` without restarting.

## Usage

Send the key in the `X-API-Key` header:

```sh
curl -H "X-API-Key: YOUR_KEY" http://localhost:8080/60348
```

```json
{"set": "60348", "locale": "sv-se", "name": "Månbil", "cached": false,
 "source": "graphql", "timing_ms": {"cache": 0.7, "graphql": 238.4}}
```

- Set numbers can be plain (`60348`) or in Rebrickable style (`60348-1`).
- `locale` defaults to `sv-se`. Any lego.com locale works, for example `de-de` or `fr-fr`.
- `source` says which step answered: `cache`, `graphql`, `instructions`, or `null` if not found.
- `timing_ms` shows how long each step that ran took on the backend.

| Status | Meaning |
|---|---|
| 200 | Name found |
| 404 | Set not found (`name` is empty) |
| 400 | Bad set number or locale |
| 401 | Missing or invalid API key |
| 502 | LEGO could not be reached (not cached, the next request retries) |

## Command line tool

`lego.py` calls the API and prints a readable summary with timing per step. Handy for
troubleshooting. Run it from the project folder:

```sh
./lego.py 60348 10179-1
./lego.py 60348 -l de-de
```

It picks up the first key from `volumes/data/keys.txt` and talks to `http://localhost:8080`.
Override with `LEGOAPI_KEY` and `LEGOAPI_URL`.

## HTTPS

The container only serves plain HTTP. To expose it on the internet, put a reverse proxy in front
that handles certificates, for example:

- [Traefik](https://traefik.io/): configured with Docker labels in `compose.yml`
- [Caddy](https://caddyserver.com/): automatic HTTPS with a few lines of config
- [Pangolin](https://github.com/fosrl/pangolin): tunneled access, no open ports needed

With Caddy, for example:

```
api.example.com {
    reverse_proxy localhost:8080
}
```

If the proxy runs in Docker on the same network, it can reach the container directly and
you can remove the `ports:` mapping from `compose.yml`.

## Configuration

| Variable | Default | Used by |
|---|---|---|
| `KEYS_FILE` | `/app/data/keys.txt` | backend |
| `CACHE_DB` | `/app/cache/names.db` | backend |
| `LEGOAPI_URL` | `http://localhost:8080` | lego.py |
| `LEGOAPI_KEY` | first key in `volumes/data/keys.txt` | lego.py |

To clear the cache, delete `volumes/cache/names.db`.

Run the self-test (makes real requests to lego.com):

```sh
docker compose run --rm app python legoname.py test
```

Not affiliated with the LEGO Group.
