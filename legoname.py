#!/usr/bin/env python3
"""GET /<set>[?locale=sv-se] with header X-API-Key -> {"set": "60348", "name": "Månbil"}"""
import hmac, json, os, re, sqlite3, sys, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
KEYS_FILE = os.environ.get("KEYS_FILE", "/app/data/keys.txt")
CACHE_DB = os.environ.get("CACHE_DB", "/app/cache/names.db")
NOT_FOUND_TTL = 86400  # retry unknown sets after a day; found names are kept forever
NAME_RE = re.compile(r'"__typename":"CS_BuildingInstructionData","name":("(?:[^"\\]|\\.)*")')


def parse(html):
    m = NAME_RE.search(html)
    return json.loads(m.group(1)) if m else None


def gql(set_num, locale):
    # shop catalog only (current sets); no auth needed, just a non-form content-type
    body = json.dumps({"query": "query($c:String!){product(productCode:$c){name}}", "variables": {"c": set_num}}).encode()
    req = urllib.request.Request("https://www.lego.com/api/graphql/ProductName", body,
                                 {"User-Agent": UA, "content-type": "application/json", "x-locale": locale[:3] + locale[3:].upper()})
    with urllib.request.urlopen(req, timeout=15) as r:
        return ((json.load(r).get("data") or {}).get("product") or {}).get("name")


def instructions(set_num, locale):
    # also covers retired sets
    url = f"https://www.lego.com/{locale}/service/building-instructions/{set_num}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return parse(r.read().decode())


def cached(set_num, locale, db=None):
    with sqlite3.connect(db or CACHE_DB, timeout=10) as c:
        c.execute("CREATE TABLE IF NOT EXISTS names (set_num TEXT, locale TEXT, name TEXT, ts REAL, PRIMARY KEY (set_num, locale))")
        return c.execute("SELECT name, ts FROM names WHERE set_num=? AND locale=?", (set_num, locale)).fetchone()


def lookup(set_num, locale="sv-se", db=None):
    """-> (name, source, timing_ms). source: cache | graphql | instructions | None (not found).
    Only the steps needed run; timing_ms has one entry per step that ran."""
    timing = {}

    def step(label, fn, *a):
        t = time.perf_counter()
        try:
            return fn(*a)
        finally:
            timing[label] = round((time.perf_counter() - t) * 1000, 1)

    row = step("cache", cached, set_num, locale, db)
    if row and (row[0] or time.time() - row[1] < NOT_FOUND_TTL):
        return row[0], "cache" if row[0] else None, timing
    # errors propagate and are never cached
    for label, fn in (("graphql", gql), ("instructions", instructions)):
        name = step(label, fn, set_num, locale)
        if name:
            save(set_num, locale, name, db)
            return name, label, timing
    save(set_num, locale, "", db)
    return "", None, timing


def save(set_num, locale, name, db=None):
    with sqlite3.connect(db or CACHE_DB, timeout=10) as c:
        c.execute("CREATE TABLE IF NOT EXISTS names (set_num TEXT, locale TEXT, name TEXT, ts REAL, PRIMARY KEY (set_num, locale))")
        c.execute("INSERT OR REPLACE INTO names VALUES (?, ?, ?, ?)", (set_num, locale, name, time.time()))


def authorized(key, path=None):
    # re-read every request so added/removed keys apply without restart; missing file = nobody gets in
    try:
        with open(path or KEYS_FILE) as f:
            keys = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except OSError:
        return False
    return bool(key) and any(hmac.compare_digest(key, k) for k in keys)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authorized(self.headers.get("X-API-Key", "")):
            return self.reply(401, {"error": "missing or invalid X-API-Key header"})
        u = urlparse(self.path)
        set_num = u.path.strip("/").split("-")[0]  # accept "60348" or "60348-1" (Rebrickable style)
        locale = parse_qs(u.query).get("locale", ["sv-se"])[0]
        if not set_num.isdigit() or not re.fullmatch(r"[a-z]{2}-[a-z]{2}", locale):
            return self.reply(400, {"error": "usage: /<set number>?locale=sv-se"})
        try:
            name, source, timing = lookup(set_num, locale)
        except Exception as e:
            return self.reply(502, {"error": str(e)})
        self.reply(200 if name else 404, {"set": set_num, "locale": locale, "name": name,
                                          "cached": "graphql" not in timing,  # answered without asking LEGO
                                          "source": source, "timing_ms": timing})

    def reply(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        assert parse('x"__typename":"CS_BuildingInstructionData","name":"Fordon \\u2013 hjullastare","s') == "Fordon – hjullastare"
        assert parse("nothing") is None
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as f:
            f.write("# comment\nkey-one\n\n  key-two  \n"); f.flush()
            assert authorized("key-one", f.name) and authorized("key-two", f.name)
            assert not authorized("", f.name) and not authorized("# comment", f.name) and not authorized("nope", f.name)
        assert not authorized("key-one", "/nonexistent")
        assert gql("10179", "sv-se") is None and instructions("10179", "sv-se")  # retired -> fallback
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "t.db")
            n, src, t = lookup("60348", db=db); assert (n, src, set(t)) == ("Månbil", "graphql", {"cache", "graphql"}), t
            n, src, t = lookup("10179", db=db); assert n and src == "instructions" and set(t) == {"cache", "graphql", "instructions"}
            n, src, t = lookup("99999999", db=db); assert (n, src, len(t)) == ("", None, 3)
            n, src, t = lookup("99999999", db=db); assert (n, src, set(t)) == ("", None, {"cache"})  # cached miss
            n, src, t = lookup("60348", db=db); assert (n, src, set(t)) == ("Månbil", "cache", {"cache"})
            with sqlite3.connect(db) as c:
                c.execute("UPDATE names SET name='CACHED' WHERE set_num='60348'")           # hit -> no refetch
                c.execute("INSERT INTO names VALUES ('60483','sv-se','',?)", (time.time() - NOT_FOUND_TTL - 1,))  # stale miss
            assert lookup("60348", db=db)[:2] == ("CACHED", "cache")
            assert lookup("60483", db=db)[:2] == ("Fordon – hjullastare", "graphql")
        print("ok")
    else:
        ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
