# /start & /help
from pyrogram import Client, filters
from pyrogram.types import Message

from megabot.core.database import db
from megabot.ui import texts


@Client.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    await db.add_user(message.from_user.id, message.from_user.username)
    if await db.is_user_banned(message.from_user.id):
        await message.reply_text(texts.BANNED)
        return
    await message.reply_text(texts.WELCOME, disable_web_page_preview=True)


@Client.on_message(filters.command("help") & filters.private)
async def help_cmd(client: Client, message: Message):
    await message.reply_text(texts.HELP, disable_web_page_preview=True)