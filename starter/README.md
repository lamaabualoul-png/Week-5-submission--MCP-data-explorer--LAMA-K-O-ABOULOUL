# Data Explorer — MCP Server (Week 5)

A [Model Context Protocol](https://modelcontextprotocol.io) server, built with `FastMCP`,
that gives an AI agent two tools over the open, no-key
**[mledoze/countries](https://github.com/mledoze/countries)** dataset (the data REST
Countries was built on). Transport: **STDIO only**.

| Tool | Purpose |
|---|---|
| `search_countries` | Find countries whose name contains some text |
| `get_country_details` | Currencies, languages, borders and flag URL for one country |

## Install

Requires Python 3.10+.

```bash
cd starter
pip install -r requirements.txt     # mcp<2 and httpx
```

## Run

```bash
python server.py
```

It prints nothing and waits for an MCP client on STDIO — that is normal. (STDIO means
stdout carries the protocol, so the server never `print()`s; logs go to stderr.)

To exercise it without a GUI client:

```bash
python demo_client.py   # scripted MCP client: lists tools, calls both with good + bad input
python test_server.py   # simulates timeouts / HTTP errors / bad JSON / bad input
```

## Register in an MCP client

### Claude Desktop

Edit the config file (Claude Desktop → Settings → Developer → *Edit Config*):

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "data-explorer": {
      "command": "python",
      "args": ["/absolute/path/to/starter/server.py"]
    }
  }
}
```

Use the **absolute** path. If `python` isn't the interpreter where you installed the
requirements, put that interpreter's full path in `command` (e.g.
`/usr/local/bin/python3` or `C:\\Python312\\python.exe`). Fully quit and reopen Claude
Desktop; the tools appear under the 🔌/tools menu. Then ask, e.g. *"Search for countries
with 'land' in the name, then get the details for Finland."*

### Claude Code (alternative)

```bash
claude mcp add data-explorer -- python /absolute/path/to/starter/server.py
```

## Tool reference

All tools **never raise**. Problems come back as `{"error": "...", "hint": "..."}` so the
agent can read the message and recover. An empty result is *not* an error.

### `search_countries(query, limit=5)`

Case-insensitive substring match against the common **and** official country name.

| Parameter | Type | Description |
|---|---|---|
| `query` | string | Part of a country name. Required, non-empty, ≤ 100 chars. |
| `limit` | integer | Max results, 1–25 (values above 25 are capped). Default 5. |

**Returns** a list of `{name, capital, region, subregion}`; `[]` if nothing matched;
or a one-item list `[{"error", "hint"}]` on failure.

Example input → output:

```json
{"query": "ger", "limit": 2}
```
```json
[
  {"name": "Germany", "capital": "Berlin", "region": "Europe", "subregion": "Western Europe"},
  {"name": "Algeria", "capital": "Algiers", "region": "Africa", "subregion": "Northern Africa"}
]
```

### `get_country_details(name)`

Looks up **one** country by common name, official name, alternate spelling, or
2/3-letter code (`"Germany"`, `"deu"`, `"DE"`). An exact match always wins over a partial
one. If a partial name matches several countries, the tool returns the candidates
instead of guessing.

| Parameter | Type | Description |
|---|---|---|
| `name` | string | Country name or code. Required, non-empty, ≤ 100 chars. |

**Returns** on success:

```json
{
  "name": "Germany",
  "official_name": "Federal Republic of Germany",
  "cca3": "DEU",
  "capital": "Berlin",
  "region": "Europe",
  "subregion": "Western Europe",
  "currencies": [{"code": "EUR", "name": "Euro", "symbol": "€"}],
  "languages": ["German"],
  "borders": [{"code": "AUT", "name": "Austria"}, {"code": "BEL", "name": "Belgium"}, "..."],
  "flag_url": "https://raw.githubusercontent.com/mledoze/countries/master/data/DEU.svg"
}
```

Island nations return `"borders": []` (not an error).

**Error examples**

```json
{"error": "no country found matching 'Atlantis'",
 "hint": "check the spelling or use search_countries to find the right name"}
```
```json
{"error": "'korea' is ambiguous: 2 countries match",
 "hint": "call get_country_details again with one of the candidate names",
 "candidates": ["South Korea", "North Korea"]}
```

### Error handling summary

| Situation | Behaviour |
|---|---|
| Empty / whitespace / non-string / > 100 char input | `{"error": ...}` before any network call |
| `limit` not an integer or < 1 | `{"error": ...}`; `limit` > 25 is silently capped |
| Network timeout / connection failure | `{"error": "upstream request failed: ..."}` |
| HTTP 4xx / 5xx from the data host | `{"error": "...returned HTTP <code>"}` |
| Response is not valid JSON / wrong shape | `{"error": ...}` |
| No match | `search_countries` → `[]`; `get_country_details` → `{"error": "no country found..."}` |
| Ambiguous name | `{"error": ..., "candidates": [...]}` |
| Failed download | Not cached — the next call retries |

## Files

| File | |
|---|---|
| `server.py` | The MCP server (both tools) |
| `requirements.txt` | Dependencies |
| `writeup.md` | Agent transcript, error handling notes, reflection |
| `demo_client.py` | Scripted MCP client that drives both tools over STDIO |
| `test_server.py` | Failure-mode tests (timeouts, HTTP errors, bad input) |
