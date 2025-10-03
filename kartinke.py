import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineQueryResultCachedPhoto
import aiosqlite
import asyncpg
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is not set in environment variables.")
    raise SystemExit(1)

DB_FILE = "photos.db"  # локальный fallback
DATABASE_URL = os.getenv("DATABASE_URL")  # Railway создаст эту переменную для Postgres

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

pg_pool = None
using_postgres = bool(DATABASE_URL)


async def init_db():
    global pg_pool, using_postgres
    if using_postgres:
        pg_pool = await asyncpg.create_pool(DATABASE_URL)
        async with pg_pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                message_id BIGINT PRIMARY KEY,
                file_id TEXT,
                caption TEXT,
                tags TEXT,
                created_at TIMESTAMP WITH TIME ZONE
            )
            """)
        print("Postgres DB initialized (using DATABASE_URL).")
    else:
        async with aiosqlite.connect(DB_FILE) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                message_id INTEGER PRIMARY KEY,
                file_id TEXT,
                caption TEXT,
                tags TEXT,
                created_at TEXT
            )
            """)
            await db.commit()
        print("SQLite DB initialized (local photos.db).")


async def save_photo(message_id: int, file_id: str, caption: str, tags: str, created_at: datetime):
    # Конвертируем datetime в UTC aware
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)

    if using_postgres:
        async with pg_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO photos (message_id, file_id, caption, tags, created_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (message_id) DO UPDATE
                  SET file_id = EXCLUDED.file_id,
                      caption = EXCLUDED.caption,
                      tags = EXCLUDED.tags,
                      created_at = EXCLUDED.created_at
            """, message_id, file_id, caption, tags, created_at)
    else:
        async with aiosqlite.connect(DB_FILE) as db:
            # SQLite хранит в ISO формате
            created_at_str = created_at.isoformat()
            await db.execute("""
                INSERT OR REPLACE INTO photos (message_id, file_id, caption, tags, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (message_id, file_id, caption, tags, created_at_str))
            await db.commit()


async def search_photos(text: str, limit: int = 50):
    text = text.lower()
    like = f"%{text}%"
    results = []
    if using_postgres:
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT message_id, file_id, caption FROM photos
                WHERE LOWER(caption) LIKE $1 OR LOWER(tags) LIKE $2
                ORDER BY message_id DESC
                LIMIT $3
            """, like, like, limit)
            for r in rows:
                results.append((r['file_id'], r['caption'], r['message_id']))
    else:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("""
                SELECT message_id, file_id, caption FROM photos
                WHERE LOWER(caption) LIKE ? OR LOWER(tags) LIKE ?
                ORDER BY message_id DESC
                LIMIT ?
            """, (like, like, limit)) as cursor:
                async for message_id, file_id, caption in cursor:
                    results.append((file_id, caption, message_id))
    return results


@dp.channel_post()
async def new_channel_post(message: types.Message):
    if message.photo:
        file_id = message.photo[-1].file_id
        caption = message.caption or ""
        tags = " ".join([w[1:] for w in caption.split() if w.startswith("#")])
        created_at = message.date  # datetime с таймзоной UTC
        await save_photo(message.message_id, file_id, caption, tags, created_at)
        print(f"Добавлено сообщение {message.message_id}: {caption}")


@dp.inline_query()
async def inline_search(query: types.InlineQuery):
    try:
        text = query.query.lower().strip()
        if not text:
            await query.answer(results=[], cache_time=10)
            return

        results = []
        rows = await search_photos(text, limit=50)
        for file_id, caption, message_id in rows:
            results.append(InlineQueryResultCachedPhoto(
                id=str(message_id),
                photo_file_id=file_id,
                caption=caption
            ))

        await query.answer(results=results, cache_time=10)
    except Exception as e:
        print("Ошибка при обработке inline_query:", e)


async def main():
    await init_db()
    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
