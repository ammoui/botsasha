import asyncio
import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")

async def main():
    if not DATABASE_URL:
        print("DATABASE_URL not set")
        return
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS photos (
        message_id BIGINT PRIMARY KEY,
        file_id TEXT,
        caption TEXT,
        tags TEXT,
        created_at TIMESTAMP
    )
    """)
    print("Таблица photos создана")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
