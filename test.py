import asyncio
from core import fetch_lyrics

async def main():
    result = await fetch_lyrics("Wolfine", "Bella")
    print(result)

asyncio.run(main())