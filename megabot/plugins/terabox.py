# /terabox — Manage TeraBox session cookie directly through Telegram
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

from config import OWNER_ID, TERABOX_COOKIE
from megabot.core.database import db
from megabot.downloaders.terabox import (
    _normalize_cookie,
    check_cookie_validity,
)

log = logging.getLogger(__name__)


@Client.on_message(filters.command(["terabox", "cookie"]) & filters.private & filters.incoming & ~filters.bot)
async def terabox_command(client: Client, message: Message):
    """View or update TeraBox session cookie directly from Telegram."""
    user_id = message.from_user.id
    is_owner = (user_id == OWNER_ID)

    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        # Show current cookie status & instructions
        user_cookie = await db.get_user_setting(user_id, "terabox_cookie")
        global_cookie = await db.get_config("terabox_cookie")
        active_cookie = user_cookie or global_cookie or TERABOX_COOKIE

        if active_cookie:
            masked = active_cookie[:8] + "…" + active_cookie[-4:] if len(active_cookie) > 14 else "••••••••"
            source = "Personal" if user_cookie else ("Global (Database)" if global_cookie else "Environment (.env)")
            check = check_cookie_validity(active_cookie)
            status_text = "Verified Active ✅" if check.get("valid") else f"Warning ⚠️ ({check.get('message')})"
            uname = check.get("username") or "Connected"

            text = (
                "<blockquote>📦 <b>TeraBox Session Status</b></blockquote>\n"
                f"• <b>Status:</b> {status_text}\n"
                f"• <b>Account:</b> <code>{uname}</code>\n"
                f"• <b>Cookie:</b> <code>{masked}</code>\n"
                f"• <b>Scope:</b> {source}\n\n"
                "<b>To update the cookie:</b>\n"
                "Send: <code>/terabox &lt;ndus_cookie&gt;</code>\n\n"
                "<b>To remove:</b>\n"
                "Send: <code>/terabox clear</code>"
            )
        else:
            text = (
                "<blockquote>📦 <b>TeraBox Session Cookie</b></blockquote>\n"
                "• <b>Status:</b> No cookie configured ⚠️\n\n"
                "TeraBox requires an <b>ndus</b> session cookie for high-speed direct downloads.\n\n"
                "<b>How to get your cookie:</b>\n"
                "1. Log into <a href='https://www.terabox.com'>terabox.com</a> in your browser.\n"
                "2. Press <b>F12</b> (Inspect) → <b>Application</b> (or Storage) → <b>Cookies</b>.\n"
                "3. Copy the value of the cookie named <b>ndus</b>.\n\n"
                "<b>To save it:</b>\n"
                "Send: <code>/terabox &lt;ndus_cookie&gt;</code>\n"
                "<i>Example:</i> <code>/terabox Y5abcdef123456...</code>"
            )

        await message.reply_text(text, disable_web_page_preview=True)
        return

    arg = parts[1].strip()

    # Clear cookie command
    if arg.lower() in ["clear", "delete", "logout", "remove"]:
        await db.set_user_setting(user_id, "terabox_cookie", None)
        if is_owner:
            await db.delete_config("terabox_cookie")
        await message.reply_text(
            "<blockquote>🗑️ <b>TeraBox Cookie Removed</b></blockquote>\n"
            "Saved TeraBox cookie has been cleared from the database."
        )
        return

    # User provided a new cookie
    norm = _normalize_cookie(arg)
    if len(norm) < 10:
        await message.reply_text("❌ Cookie seems too short. Please paste the full <code>ndus</code> cookie value.")
        return

    check_msg = await message.reply_text("🔍 <i>Validating TeraBox cookie with server…</i>")
    check = check_cookie_validity(norm)

    # Save to database
    await db.set_user_setting(user_id, "terabox_cookie", norm)
    scope = "Personal"

    if is_owner:
        # Owner sets the global bot-wide default for all users
        await db.set_config("terabox_cookie", norm)
        scope = "Global (Active for all bot users)"

    uname = check.get("username") or "TeraBox User"
    valid_icon = "✅" if check.get("valid") else "⚠️"
    msg_note = check.get("message")

    reply_text = (
        f"<blockquote>{valid_icon} <b>TeraBox Cookie Updated!</b></blockquote>\n"
        f"• <b>Account:</b> <b>{uname}</b>\n"
        f"• <b>Validation:</b> <i>{msg_note}</i>\n"
        f"• <b>Scope:</b> {scope}\n\n"
        "✨ <i>Saved directly to database! No VPS file editing or container restarts needed.</i>"
    )

    await check_msg.edit_text(reply_text, disable_web_page_preview=True)
