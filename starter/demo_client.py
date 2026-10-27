"""Drives server.py over STDIO with the official MCP client SDK and prints a transcript.

Run:  python demo_client.py
This is a scripted stand-in for an agent: it lists the tools, then calls each one with
good and bad input, exactly as an MCP client (Claude Desktop, IDE) would.
"""
import asyncio, json, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CALLS = [
    ("search_countries", {"query": "land", "limit": 3}),
    ("search_countries", {"query": "zzzzz"}),
    ("search_countries", {"query": "   "}),
    ("search_countries", {"query": "land", "limit": 0}),
    ("get_country_details", {"name": "Germany"}),
    ("get_country_details", {"name": "japan"}),
    ("get_country_details", {"name": "korea"}),
    ("get_country_details", {"name": "Atlantis"}),
    ("get_country_details", {"name": ""}),
    ("get_country_details", {"name": "x" * 500}),
]

async def main():
    params = StdioServerParameters(command=sys.executable, args=["server.py"], env=dict(os.environ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("TOOLS:", [t.name for t in tools.tools], "\n")
            for name, args in CALLS:
                res = await s.call_tool(name, args)
                parts = []
                for blk in res.content:
                    try:
                        parts.append(json.loads(blk.text))
                    except Exception:
                        parts.append(blk.text)
                # FastMCP sends each list item as its own content block; re-assemble
                is_list = name == "search_countries"
                payload = parts if is_list else (parts[0] if parts else None)
                text = json.dumps(payload, ensure_ascii=False, indent=2)
                short = args if len(json.dumps(args)) < 80 else {k: (v[:10] + '…') if isinstance(v, str) else v for k, v in args.items()}
                print(f">>> {name}({json.dumps(short, ensure_ascii=False)})")
                print(text, "\n")
asyncio.run(main())
