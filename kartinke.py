import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineQueryResultCachedPhoto
import asyncpg

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN or not DATABASE_URL:
    print("ERROR: BOT_TOKEN or DATABASE_URL not set!")
    raise SystemExit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
pg_pool = None


async def init_db():
    global pg_pool
    pg_pool = await asyncpg.create_pool(DATABASE_URL)
    async with pg_pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            message_id BIGINT PRIMARY KEY,
            file_id TEXT NOT NULL,
            caption TEXT,
            tags TEXT
        )
        """)
    print("Postgres DB initialized.")


async def save_photo(message_id: int, file_id: str, caption: str, tags: str):
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO photos (message_id, file_id, caption, tags)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (message_id) DO NOTHING
        """, message_id, file_id, caption, tags)


async def search_photos(query: str, limit: int = 50):
    query = f"%{query.lower()}%"
    results = []
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT message_id, file_id, caption FROM photos
            WHERE LOWER(caption) LIKE $1 OR LOWER(tags) LIKE $1
            ORDER BY message_id DESC
            LIMIT $2
        """, query, limit)
        for r in rows:
            results.append((r['file_id'], r['caption'], r['message_id']))
    return results


@dp.channel_post()
async def handle_new_post(message: types.Message):
    if not message.photo:
        return
    file_id = message.photo[-1].file_id
    caption = message.caption or ""
    tags = " ".join([w[1:] for w in caption.split() if w.startswith("#")])
    await save_photo(message.message_id, file_id, caption, tags)
    print(f"Saved photo {message.message_id}")


@dp.inline_query()
async def handle_inline(query: types.InlineQuery):
    text = query.query.strip().lower()
    if not text:
        await query.answer(results=[], cache_time=10)
        return

    rows = await search_photos(text)
    results = [
        InlineQueryResultCachedPhoto(
            id=str(message_id),
            photo_file_id=file_id,
            caption=caption
        ) for file_id, caption, message_id in rows
    ]
    await query.answer(results=results, cache_time=10)


async def main():
    await init_db()
    print("Bot started on Railway")
    # skip_updates=True — важно для облака
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
