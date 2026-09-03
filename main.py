# MegaBot — MEGA downloader & Telegram uploader
import sys
import logging

from aiohttp import web
from pyrogram import Client, idle
from pyrogram.enums import ParseMode

from config import API_ID, API_HASH, BOT_TOKEN, PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

if not all([API_ID, API_HASH, BOT_TOKEN]):
    print("Please set API_ID, API_HASH and BOT_TOKEN in your .env file.")
    sys.exit(1)

app = Client(
    "megabot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="megabot.plugins"),
    workers=16,
    parse_mode=ParseMode.HTML,
)


async def set_bot_commands(client):
    from pyrogram.types import BotCommand
    await client.set_bot_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("login", "Connect your MEGA account"),
        BotCommand("logout", "Disconnect your MEGA account"),
        BotCommand("settings", "Your preferences"),
        BotCommand("help", "How to use the bot"),
        BotCommand("stats", "Bot statistics (owner)"),
    ])


async def web_server():
    """Keep-alive endpoint for Docker / Railway style hosts."""
    web_app = web.Application()
    web_app.router.add_get("/", lambda _: web.Response(text="MegaBot is running"))
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info("Web keep-alive server on port %s", PORT)


async def check_database():
    """Fail fast with a clear message if MongoDB is unreachable or auth is bad."""
    from config import MONGO_URL
    from megabot.core.database import db
    if not MONGO_URL:
        logging.warning("MONGO_URL not set — bot will run without persistence!")
        return
    try:
        await db.client.admin.command("ping")
        logging.info("MongoDB connection OK")
    except Exception as e:
        logging.critical("MongoDB connection FAILED: %s", e)
        if "auth" in str(e).lower() or "8000" in str(e):
            logging.critical(
                "↳ The username/password in MONGO_URL is wrong, or the database "
                "user doesn't exist in MongoDB Atlas yet. Atlas → Database Access "
                "→ check user 'megabot' and its password."
            )
        raise SystemExit(1)


async def main():
    await check_database()
    await web_server()
    await app.start()
    await set_bot_commands(app)

    # start the background job queue
    from megabot.core.job_queue import job_queue
    await job_queue.start(app)

    logging.info("MegaBot started 🚀")
    await idle()
    await job_queue.stop()
    await app.stop()


if __name__ == "__main__":
    import asyncio
    # kurigram + Python 3.12: asyncio.run() creates a loop that conflicts
    # with Pyrogram's session handling — use the classic loop pattern instead
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("MegaBot stopped")