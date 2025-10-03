import os
import asyncio
import hashlib
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineQueryResultCachedPhoto
import aiosqlite
import asyncpg
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN is not set in environment variables.")
    print("Set BOT_TOKEN and restart.")
    raise SystemExit(1)

DB_FILE = "photos.db"  # локальный fallback
DATABASE_URL = os.getenv("DATABASE_URL")  # Railway создаст эту переменную для Postgres

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# глобальная переменная для пула Postgres (если используется)
pg_pool = None
using_postgres = bool(DATABASE_URL)


async def init_db():
    global pg_pool, using_postgres
    if using_postgres:
        # Создаём пул и таблицу в Postgres
        pg_pool = await asyncpg.create_pool(DATABASE_URL)
        async with pg_pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                message_id BIGINT PRIMARY KEY,
                file_id TEXT,
                caption TEXT,
                tags TEXT,
                created_at TIMESTAMP
            )
            """)
        print("Postgres DB initialized (using DATABASE_URL).")
    else:
        # локальный sqlite (для разработки)
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


async def save_photo(message_id: int, file_id: str, caption: str, tags: str, created_at):
    if using_postgres:
        async with pg_pool.acquire() as conn:
            # ON CONFLICT чтобы не дублировать message_id
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
            await db.execute("""
                INSERT OR REPLACE INTO photos (message_id, file_id, caption, tags, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (message_id, file_id, caption, tags, created_at))
            await db.commit()


async def search_photos(text: str, limit: int = 50):
    text = text.lower()
    like = f"%{text}%"
    results = []
    if using_postgres:
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT file_id, caption FROM photos
                WHERE LOWER(caption) LIKE $1 OR LOWER(tags) LIKE $2
                ORDER BY message_id DESC
                LIMIT $3
            """, like, like, limit)
            for r in rows:
                results.append((r['file_id'], r['caption']))
    else:
        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("""
                SELECT file_id, caption FROM photos
                WHERE LOWER(caption) LIKE ? OR LOWER(tags) LIKE ?
                ORDER BY message_id DESC
                LIMIT ?
            """, (like, like, limit)) as cursor:
                async for file_id, caption in cursor:
                    results.append((file_id, caption))
    return results


@dp.channel_post()
async def new_channel_post(message: types.Message):
    if message.photo:
        file_id = message.photo[-1].file_id
        caption = message.caption or ""
        tags = " ".join([w[1:] for w in caption.split() if w.startswith("#")])
        created_at = message.date.isoformat()
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
        for file_id, caption in rows:
            result_id = hashlib.md5(file_id.encode()).hexdigest()
            results.append(InlineQueryResultCachedPhoto(
                id=result_id,
                photo_file_id=file_id,
                # title/caption optional
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
