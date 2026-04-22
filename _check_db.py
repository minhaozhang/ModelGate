import asyncio, asyncpg

async def main():
    c = await asyncpg.connect("postgresql://api-proxy:Zaq1%403edc@dbhost:5432/api-proxy")
    for t in ["api_keys", "providers", "models", "mcp_servers", "request_logs"]:
        r = await c.fetchval(f"SELECT count(*) FROM {t}")
        print(f"{t}: {r}")
    await c.close()

asyncio.run(main())
