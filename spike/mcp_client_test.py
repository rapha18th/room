"""Smoke-test Room's MCP endpoint with the official client. Usage: python spike/mcp_client_test.py <url>"""
import asyncio, json, sys, time
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787/mcp/"

async def main():
    async with streamable_http_client(URL) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            t = time.time()
            r = await s.call_tool("score_reference", {"name": "Greggs", "kind": "brand", "cities": ["London", "Dallas"]})
            print(f"score_reference {time.time()-t:.1f}s:", (r.structured_content or r.content[0].text)[:400] if not r.structured_content else json.dumps(r.structured_content)[:400])
            t = time.time()
            r = await s.call_tool("rewrite_for_city", {"text": "This summer, trade the Starbucks run for something louder. Burna Boy on the speakers, Squid Game on the big screen, and Nando's on every table. Bring the friend who still wears Crocs. We'll forgive them.", "city": "Atlanta", "also_check": ["London"]})
            out = r.structured_content or json.loads(r.content[0].text)
            print(f"rewrite_for_city {time.time()-t:.1f}s:", json.dumps({k: out[k] for k in ("script", "room_score_before", "room_score_after")}, ensure_ascii=False))
            for line in out["trace"]: print("   ", line)

asyncio.run(main())
