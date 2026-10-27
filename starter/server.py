"""Data Explorer — MCP server for Week 5.

Wraps the open `mledoze/countries` dataset and exposes it to an agent as two MCP
tools over STDIO:

    search_countries(query, limit)  -> list of short country summaries
    get_country_details(name)       -> currencies, languages, borders, flag URL

Data source: the open `mledoze/countries` dataset (the data REST Countries was built
on), served as one JSON file from GitHub. No API key. It is fetched over HTTPS on the
first successful call and cached in memory. Failures are NOT cached, so a transient
network error doesn't poison the server for the rest of the session.

Error contract (both tools): a tool never raises. Problems come back as a structured
message the model can read and act on:
    {"error": "<what went wrong>", "hint": "<what to try next>"}
(search_countries wraps it in a one-element list so its return type stays a list.)

Setup:
    pip install -r requirements.txt
Run (STDIO) — register this command in your MCP client (e.g. Claude Desktop / an IDE):
    python server.py

NOTE: with STDIO transport, stdout carries the MCP protocol. Never print() to stdout
in this file; use `log` (stderr) for diagnostics.
"""
import logging
import sys

import httpx
from mcp.server.fastmcp import FastMCP

DATA_URL = "https://raw.githubusercontent.com/mledoze/countries/master/countries.json"
# Each country has a 3-letter `cca3` code; its flag lives at this URL.
FLAG_URL = "https://raw.githubusercontent.com/mledoze/countries/master/data/{cca3}.svg"

MAX_QUERY_LEN = 100       # reject absurdly long input before doing any work
DEFAULT_LIMIT = 5
MAX_LIMIT = 25            # cap results so a single call can't flood the model's context
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("data-explorer")

mcp = FastMCP("data-explorer")

_countries: list[dict] | None = None  # in-memory cache of the dataset


# --------------------------------------------------------------------------- helpers
class UpstreamError(Exception):
    """Raised by load_countries() with a human/model-readable message."""


def load_countries() -> list[dict]:
    """Download the dataset once and cache it. Raises UpstreamError on any failure."""
    global _countries
    if _countries is not None:
        return _countries
    try:
        resp = httpx.get(DATA_URL, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        raise UpstreamError("the country dataset request timed out") from None
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(
            f"the country dataset server returned HTTP {exc.response.status_code}"
        ) from None
    except httpx.HTTPError as exc:  # connection errors, DNS, TLS, ...
        raise UpstreamError(f"could not reach the country dataset ({type(exc).__name__})") from None
    except ValueError:  # invalid JSON
        raise UpstreamError("the country dataset response was not valid JSON") from None

    if not isinstance(data, list) or not data:
        raise UpstreamError("the country dataset had an unexpected shape")
    _countries = data
    log.info("loaded %d countries", len(data))
    return _countries


def _err(message: str, hint: str | None = None) -> dict:
    out = {"error": message}
    if hint:
        out["hint"] = hint
    return out


def _clean_text(value, field: str) -> tuple[str | None, dict | None]:
    """Validate a free-text argument. Returns (clean_value, None) or (None, error)."""
    if not isinstance(value, str):
        return None, _err(f"{field} must be a string", f"pass {field} as text, e.g. \"Germany\"")
    value = value.strip()
    if not value:
        return None, _err(f"{field} must not be empty", "provide a country name such as \"Germany\"")
    if len(value) > MAX_QUERY_LEN:
        return None, _err(f"{field} is too long (max {MAX_QUERY_LEN} characters)")
    return value, None


def _names(c: dict) -> list[str]:
    """All lowercase name variants for a country, defensively read."""
    n = c.get("name") or {}
    out = [str(n.get("common", "")), str(n.get("official", ""))]
    out += [str(x) for x in (c.get("altSpellings") or [])]
    return [s.lower() for s in out if s]


def _first_capital(c: dict):
    caps = c.get("capital") or []
    return caps[0] if caps else None


# --------------------------------------------------------------------------- tools
@mcp.tool()
def search_countries(query: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Search countries by name. Returns a list of {name, capital, region, subregion}.

    Matches the query as a case-insensitive substring of the common or official name.
    An empty list means "no country matched" (that is not an error). On a real problem
    (bad input, network failure) returns a one-item list: [{"error": ..., "hint": ...}].

    Args:
        query: Part of a country name, e.g. "land" or "united". Max 100 characters.
        limit: Maximum results to return, 1-25 (default 5).
    """
    q, problem = _clean_text(query, "query")
    if problem:
        return [problem]

    if isinstance(limit, bool) or not isinstance(limit, int):
        return [_err("limit must be an integer", f"use a whole number from 1 to {MAX_LIMIT}")]
    if limit < 1:
        return [_err("limit must be at least 1")]
    limit = min(limit, MAX_LIMIT)

    try:
        countries = load_countries()
    except UpstreamError as exc:
        return [_err(f"upstream request failed: {exc}", "try again in a moment")]

    q = q.lower()
    results = []
    for c in countries:
        n = c.get("name") or {}
        if q in str(n.get("common", "")).lower() or q in str(n.get("official", "")).lower():
            results.append(
                {
                    "name": n.get("common"),
                    "capital": _first_capital(c),
                    "region": c.get("region"),
                    "subregion": c.get("subregion"),
                }
            )
            if len(results) >= limit:
                break
    return results  # [] when nothing matched


@mcp.tool()
def get_country_details(name: str) -> dict:
    """Get details for ONE country: currencies, languages, borders, and flag URL.

    The name is matched case-insensitively against common name, official name, and
    alternate spellings/codes (e.g. "Germany", "deu", "Türkiye"). An exact match wins.
    If the name is ambiguous (e.g. "korea") the tool returns the candidate names
    instead of guessing, so call it again with one of them.

    Returns on success:
        {name, official_name, cca3, capital, region, subregion,
         currencies: [{code, name, symbol}], languages: [str],
         borders: [{code, name}], flag_url}
    Returns on failure: {"error": ..., "hint": ...} (optionally with "candidates").

    Args:
        name: Country name or code, e.g. "Germany". Max 100 characters.
    """
    clean, problem = _clean_text(name, "name")
    if problem:
        return problem

    try:
        countries = load_countries()
    except UpstreamError as exc:
        return _err(f"upstream request failed: {exc}", "try again in a moment")

    q = clean.lower()

    # 1) exact match on any name variant or on the cca2/cca3/ccn3 codes
    exact = [
        c for c in countries
        if q in _names(c) or q in (str(c.get("cca3", "")).lower(), str(c.get("cca2", "")).lower())
    ]
    # 2) otherwise substring match on common/official name
    if exact:
        matches = exact
    else:
        matches = [
            c for c in countries
            if q in str((c.get("name") or {}).get("common", "")).lower()
            or q in str((c.get("name") or {}).get("official", "")).lower()
        ]

    if not matches:
        return _err(
            f"no country found matching '{clean}'",
            "check the spelling or use search_countries to find the right name",
        )
    if len(matches) > 1:
        return {
            **_err(
                f"'{clean}' is ambiguous: {len(matches)} countries match",
                "call get_country_details again with one of the candidate names",
            ),
            "candidates": [m["name"]["common"] for m in matches[:10] if m.get("name")],
        }

    c = matches[0]
    cca3 = c.get("cca3")
    by_code = {x.get("cca3"): x for x in countries}

    currencies = [
        {"code": code, "name": (v or {}).get("name"), "symbol": (v or {}).get("symbol")}
        for code, v in (c.get("currencies") or {}).items()
    ]
    languages = list((c.get("languages") or {}).values())
    borders = [
        {"code": b, "name": ((by_code.get(b) or {}).get("name") or {}).get("common")}
        for b in (c.get("borders") or [])
    ]

    return {
        "name": (c.get("name") or {}).get("common"),
        "official_name": (c.get("name") or {}).get("official"),
        "cca3": cca3,
        "capital": _first_capital(c),
        "region": c.get("region"),
        "subregion": c.get("subregion"),
        "currencies": currencies,
        "languages": languages,
        "borders": borders,  # [] for island nations — not an error
        "flag_url": FLAG_URL.format(cca3=cca3) if cca3 else None,
    }


if __name__ == "__main__":
    mcp.run()  # STDIO transport
