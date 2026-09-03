# /settings — per-user preferences with toggle buttons
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from megabot.core.database import db
from megabot.ui.keyboards import settings_kb

ARCHIVE_MODES = ["ask", "archive", "extract"]


async def _render(client, message, user_id):
    current = {
        "image_pdf": await db.get_user_setting(user_id, "image_pdf"),
        "video_thumbs": await db.get_user_setting(user_id, "video_thumbs"),
        "archive_mode": await db.get_user_setting(user_id, "archive_mode"),
    }
    text = ("<blockquote>⚙️ <b>Your Settings</b></blockquote>\n"
            "Tap a row to toggle it.")
    try:
        await message.edit_text(text, reply_markup=settings_kb(current),
                                disable_web_page_preview=True)
    except Exception:
        await message.reply_text(text, reply_markup=settings_kb(current))


@Client.on_message(filters.command("settings") & filters.private)
async def settings_cmd(client: Client, message: Message):
    await _render(client, message, message.from_user.id)


@Client.on_callback_query(filters.regex(r"^set:(\w+)$"))
async def settings_toggle(client: Client, cq: CallbackQuery):
    key = cq.matches[0].group(1)
    user_id = cq.from_user.id
    await cq.answer()

    if key == "archive_mode":
        current = await db.get_user_setting(user_id, "archive_mode")
        nxt = ARCHIVE_MODES[(ARCHIVE_MODES.index(current) + 1) % len(ARCHIVE_MODES)]
        await db.set_user_setting(user_id, "archive_mode", nxt)
    else:
        current = await db.get_user_setting(user_id, key)
        await db.set_user_setting(user_id, key, not current)

    await _render(client, cq.message, user_id)