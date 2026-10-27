"""Hardening tests: run with `python test_server.py` (no network needed).

Simulates upstream failures by monkeypatching httpx.get, and checks that both tools
return structured errors instead of raising.
"""
import httpx
import server

REQ = httpx.Request("GET", server.DATA_URL)


def reset():
    server._countries = None  # clear cache between scenarios


def fake_get(behaviour):
    def _get(*a, **k):
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour
    return _get


def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    assert cond, label


def is_err(x):
    d = x[0] if isinstance(x, list) else x
    return isinstance(d, dict) and "error" in d


real_get = httpx.get
scenarios = {
    "timeout": httpx.ReadTimeout("slow", request=REQ),
    "connect error": httpx.ConnectError("down", request=REQ),
    "HTTP 500": httpx.Response(500, request=REQ),
    "HTTP 404": httpx.Response(404, request=REQ),
    "invalid JSON": httpx.Response(200, content=b"<html>oops</html>", request=REQ),
    "wrong shape": httpx.Response(200, json={"not": "a list"}, request=REQ),
}
for label, behaviour in scenarios.items():
    reset()
    httpx.get = fake_get(behaviour)
    # raise_for_status needs a request attached; Response(..., request=REQ) has it
    check(f"search_countries handles {label}", is_err(server.search_countries("ger")))
    check(f"get_country_details handles {label}", is_err(server.get_country_details("germany")))
    check(f"failure not cached after {label}", server._countries is None)
httpx.get = real_get

# bad input (no network required because validation happens first)
reset()
bad = [None, 123, "", "   ", "x" * 101, ["a"]]
for v in bad:
    check(f"search_countries bad query {str(v)[:12]!r}", is_err(server.search_countries(v)))
    check(f"get_country_details bad name {str(v)[:12]!r}", is_err(server.get_country_details(v)))
for lim in [0, -3, "5", 2.5, True, None]:
    check(f"search_countries bad limit {lim!r}", is_err(server.search_countries("ger", lim)))

# live data checks (skipped if offline)
try:
    server.load_countries()
    check("limit is capped at MAX_LIMIT", len(server.search_countries("a", 9999)) <= server.MAX_LIMIT)
    check("no-match search returns [] (not an error)", server.search_countries("zzzzz") == [])
    d = server.get_country_details("DEU")
    check("lookup by cca3 code works", d.get("name") == "Germany")
    check("details include all four required fields",
          all(k in d for k in ("currencies", "languages", "borders", "flag_url")))
    check("island nation has empty borders, not error", server.get_country_details("japan")["borders"] == [])
    check("ambiguous name lists candidates", "candidates" in server.get_country_details("korea"))
except server.UpstreamError:
    print("SKIP live-data checks (offline)")
print("\nAll checks passed.")
