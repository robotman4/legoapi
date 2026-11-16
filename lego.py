#!/usr/bin/env python3
"""Ask the legoapi backend: ./lego.py 60373 [60348-1 ...] [-l de-de]
Shows which steps the backend ran (cache, GraphQL, instructions) with their backend timing,
plus this script's own round-trip time.
Key: $LEGOAPI_KEY, else the first key in volumes/data/keys.txt next to this script.
URL: $LEGOAPI_URL, else https://<Host> from a Traefik rule in compose.yml next to this script,
     else http://localhost:8080"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def base_url():
    if os.environ.get("LEGOAPI_URL"):
        return os.environ["LEGOAPI_URL"].rstrip("/")
    try:  # behind Traefik: use the Host(`...`) rule from compose.yml
        with open(os.path.join(HERE, "compose.yml")) as f:
            return "https://" + re.search(r"Host\(`([^`]+)`\)", f.read()).group(1)
    except (OSError, AttributeError):
        return "http://localhost:8080"


URL = base_url()
KEYS_FILE = os.path.join(HERE, "volumes/data/keys.txt")
B, D, R = ("\033[1m", "\033[2m", "\033[0m") if sys.stdout.isatty() else ("", "", "")
STEPS = (("cache", "💾", "Cache       "), ("graphql", "⚡", "GraphQL     "), ("instructions", "📘", "Instructions"))
ICON = {k: i for k, i, _ in STEPS}


def api_key():
    if os.environ.get("LEGOAPI_KEY"):
        return os.environ["LEGOAPI_KEY"]
    try:
        with open(KEYS_FILE) as f:
            return next(l.strip() for l in f if l.strip() and not l.startswith("#"))
    except (OSError, StopIteration):
        sys.exit(f"🔑 no API key: set LEGOAPI_KEY or add one to {KEYS_FILE}")


def call(set_num, locale, key):
    req = urllib.request.Request(f"{URL}/{set_num}?locale={locale}", headers={"X-API-Key": key})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r), time.time() - t
    except urllib.error.HTTPError as e:  # 4xx/5xx still carry a JSON body
        try:
            body = json.load(e)
        except ValueError:
            body = {"error": e.reason}
        return e.code, body, time.time() - t
    except (urllib.error.URLError, OSError) as e:
        return None, {"error": f"backend unreachable: {getattr(e, 'reason', e)}"}, time.time() - t


def show(set_num, locale, key):
    code, body, dt = call(set_num, locale, key)
    print(f"\n🧱 {B}{set_num}{R}  🌍 {locale}")
    timing, source = body.get("timing_ms", {}), body.get("source")
    for k, icon, label in STEPS:
        if k not in timing:
            continue  # step not needed, backend skipped it
        if k == source:
            status = "✅ hit" if k == "cache" else "✅ found"
        elif k == "cache" and code == 404 and len(timing) == 1:
            status = "🚫 cached as not found"
        else:
            status = "➖ miss" if k == "cache" else "➖ not found"
        print(f"   {icon} {label}  {status:<22}{D}{timing[k]:>8.1f} ms{R}")
    print(f"   🔁 Round trip    {D}HTTP {code or '-'} · {dt * 1000:.0f} ms{R}")
    if body.get("name"):
        print(f"   🏷️  {B}{body['name']}{R}  {D}{ICON.get(source, '')} {source or ''}{R}")
        return True
    if code == 404:
        print("   😢 not found" + (f"  {D}(LEGO is asked again after 24h){R}" if len(timing) == 1 else ""))
    elif code == 401:
        print(f"   🔑 {body.get('error')}")
    else:
        print(f"   ❌ {body.get('error', body)}")
    return False


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sets", nargs="+", help="set numbers, e.g. 60373 or 60373-1")
    p.add_argument("-l", "--locale", default="sv-se")
    a = p.parse_args()
    key = api_key()
    ok = [show(s, a.locale.lower(), key) for s in a.sets]
    sys.exit(0 if all(ok) else 1)
