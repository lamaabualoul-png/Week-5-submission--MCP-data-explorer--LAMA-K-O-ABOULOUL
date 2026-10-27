# Week 5 Writeup — Data Explorer MCP Server

## 1. Transcript: an MCP client calling both tools

I drove `server.py` over STDIO with the official MCP Python client (`demo_client.py`),
which speaks the same protocol Claude Desktop uses: `initialize` → `tools/list` →
`tools/call`. Each block below is a real call and its real response.

```text
TOOLS: ['search_countries', 'get_country_details'] 

>>> search_countries({"query": "land", "limit": 3})
[
  {
    "name": "Åland Islands",
    "capital": "Mariehamn",
    "region": "Europe",
    "subregion": "Northern Europe"
  },
  {
    "name": "French Southern and Antarctic Lands",
    "capital": "Port-aux-Français",
    "region": "Antarctic",
    "subregion": ""
  },
  {
    "name": "Caribbean Netherlands",
    "capital": "Kralendijk",
    "region": "Americas",
    "subregion": "Caribbean"
  }
] 

>>> search_countries({"query": "zzzzz"})
[] 

>>> search_countries({"query": "   "})
[
  {
    "error": "query must not be empty",
    "hint": "provide a country name such as \"Germany\""
  }
] 

>>> search_countries({"query": "land", "limit": 0})
[
  {
    "error": "limit must be at least 1"
  }
] 

>>> get_country_details({"name": "Germany"})
{
  "name": "Germany",
  "official_name": "Federal Republic of Germany",
  "cca3": "DEU",
  "capital": "Berlin",
  "region": "Europe",
  "subregion": "Western Europe",
  "currencies": [
    {
      "code": "EUR",
      "name": "Euro",
      "symbol": "€"
    }
  ],
  "languages": [
    "German"
  ],
  "borders": [
    {
      "code": "AUT",
      "name": "Austria"
    },
    {
      "code": "BEL",
      "name": "Belgium"
    },
    {
      "code": "CZE",
      "name": "Czechia"
    },
    {
      "code": "DNK",
      "name": "Denmark"
    },
    {
      "code": "FRA",
      "name": "France"
    },
    {
      "code": "LUX",
      "name": "Luxembourg"
    },
    {
      "code": "NLD",
      "name": "Netherlands"
    },
    {
      "code": "POL",
      "name": "Poland"
    },
    {
      "code": "CHE",
      "name": "Switzerland"
    }
  ],
  "flag_url": "https://raw.githubusercontent.com/mledoze/countries/master/data/DEU.svg"
} 

>>> get_country_details({"name": "japan"})
{
  "name": "Japan",
  "official_name": "Japan",
  "cca3": "JPN",
  "capital": "Tokyo",
  "region": "Asia",
  "subregion": "Eastern Asia",
  "currencies": [
    {
      "code": "JPY",
      "name": "Japanese yen",
      "symbol": "¥"
    }
  ],
  "languages": [
    "Japanese"
  ],
  "borders": [],
  "flag_url": "https://raw.githubusercontent.com/mledoze/countries/master/data/JPN.svg"
} 

>>> get_country_details({"name": "korea"})
{
  "error": "'korea' is ambiguous: 2 countries match",
  "hint": "call get_country_details again with one of the candidate names",
  "candidates": [
    "South Korea",
    "North Korea"
  ]
} 

>>> get_country_details({"name": "Atlantis"})
{
  "error": "no country found matching 'Atlantis'",
  "hint": "check the spelling or use search_countries to find the right name"
} 

>>> get_country_details({"name": ""})
{
  "error": "name must not be empty",
  "hint": "provide a country name such as \"Germany\""
} 

>>> get_country_details({"name": "xxxxxxxxxx…"})
{
  "error": "name is too long (max 100 characters)"
}
```

### Agent conversation in Claude Desktop

> **TODO (paste yours here before submitting):** after registering the server in Claude
> Desktop (see README), ask it: *"Search for countries with 'land' in the name, then get
> the details for Finland, and tell me which currency it uses and who its neighbours are."*
> Paste the conversation (or a screenshot) showing the `search_countries` and
> `get_country_details` tool-call cards. Also try *"Get details for Atlantis"* to show an
> error being handled gracefully.

## 2. How I handled errors

- **Validate before doing work.** Empty, whitespace-only, non-string, or over-long
  (> 100 chars) input returns `{"error", "hint"}` before any network call. `limit` must
  be an integer ≥ 1 (booleans are rejected) and is capped at 25 so one call can't flood the
  model's context.
- **Translate every upstream failure into a message.** `load_countries()` catches timeouts,
  connection errors, HTTP 4xx/5xx, invalid JSON and wrongly-shaped data, and re-raises one
  `UpstreamError` with a readable reason. The tools turn that into a structured error
  instead of letting an exception reach the protocol layer. The failed download is not
  cached, so the next call retries.
- **Distinguish "nothing found" from "something broke".** `search_countries` returns `[]`
  for no match (a valid answer); a real failure is an `{"error"}` item.
  `get_country_details` returns an error with a hint to use `search_countries`.
- **Don't guess on ambiguity.** `"korea"` matches two countries, so the tool returns
  `candidates` and asks the caller to pick, rather than silently choosing one. An exact
  match (e.g. `"guinea"`, or a code like `"DEU"`) still wins.
- **Defensive data access.** Fields are read with `.get()` so a country missing
  `capital`, `borders` or `currencies` (islands, Antarctica) yields `None`/`[]`, not a
  `KeyError`. Border codes are resolved to names so the agent doesn't need extra calls.
- **Keep stdout clean.** STDIO uses stdout for the protocol, so the server only logs to stderr.
- **Validated** with `test_server.py` (timeout, connect error, HTTP 404/500, bad JSON, wrong
  shape, bad types/limits, capping, ambiguity, island nations): all checks pass.

## 3. What I learned

An agent can only reason over the context it can reach, and an MCP server is the
gatekeeper that decides exactly what that is: I chose which two operations exist, which
fields come back, and how many results fit in one reply, so the model never sees the whole
dataset. Returning small, structured, model-friendly results (with names resolved and
sensible limits) keeps the context window clean, while clear `error`/`hint` messages let
the agent recover on its own instead of hallucinating an answer after a failure. Because
tool descriptions and docstrings are what the model reads to decide when to call a tool,
writing them precisely is itself a way of controlling context. Finally, validating input
and bounding output is a safety boundary as well as a quality one, since the agent is an
untrusted caller of my code.
