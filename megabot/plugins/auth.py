# /login & /logout — save the user's MEGA account in MongoDB
import asyncio
import logging
import re

from pyrogram import Client, filters
from pyrogram.types import Message

from megabot.core.database import db

log = logging.getLogger(__name__)

# in-memory login wizard state: user_id → {"step": "email"|"password", "email": str}
_login_state: dict[int, dict] = {}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@Client.on_message(filters.command("login") & filters.private)
async def login_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    existing = await db.get_mega_account(user_id)
    if existing:
        await message.reply_text(
            "🔐 You're already logged in as "
            f"<b>{existing['email']}</b>.\nUse /logout first to switch accounts."
        )
        return
    _login_state[user_id] = {"step": "email"}
    await message.reply_text(
        "<blockquote>🔐 <b>MEGA Login</b></blockquote>\n"
        "Send me your <b>MEGA email</b> address.\n"
        "<i>(Cancel anytime with /cancel)</i>"
    )


@Client.on_message(filters.command("logout") & filters.private)
async def logout_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    _login_state.pop(user_id, None)
    await db.delete_mega_session(user_id)
    if await db.delete_mega_account(user_id):
        await message.reply_text("👋 MEGA account removed. You're logged out.")
    else:
        await message.reply_text("You weren't logged in to any MEGA account.")


@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client: Client, message: Message):
    if _login_state.pop(message.from_user.id, None):
        await message.reply_text("🚫 Login cancelled.")
    else:
        await message.reply_text("Nothing to cancel.")


@Client.on_message(filters.private & filters.text & filters.regex(r"^(?!/)"))
async def login_wizard(client: Client, message: Message):
    """Intercepts plain text ONLY while a login wizard step is active."""
    user_id = message.from_user.id
    state = _login_state.get(user_id)
    if not state:
        # not in wizard → let the link handler (links.py) process it
        message.continue_propagation()
        return

    text = message.text.strip()

    if state["step"] == "email":
        if not EMAIL_RE.match(text):
            await message.reply_text("❌ That doesn't look like an email. Try again:")
            return
        _login_state[user_id] = {"step": "password", "email": text}
        await message.reply_text(
            f"📧 <b>{text}</b>\n\nNow send your <b>MEGA password</b>.\n"
            "⚠️ It will be stored in the bot's database — use an account you trust this with."
        )
        return

    if state["step"] == "password":
        email = state["email"]
        password = text
        wait = await message.reply_text("⏳ Verifying with MEGA…")

        # verify credentials in a worker thread (mega.py is blocking) and
        # keep the session (sid) right away — so jobs never re-login and
        # MEGA doesn't flag repeated logins as suspicious
        def _check():
            from megabot.downloaders.mega_raw import RawMega
            raw = RawMega(email, password)
            raw.login_with_session()
            return raw.session_state()

        try:
            state = await asyncio.to_thread(_check)
        except Exception as e:
            log.warning("MEGA login failed for %s: %s", email, e)
            msg = str(e)
            if "blocked" in msg.lower() or "locked" in msg.lower() \
                    or "-15" in msg or "-16" in msg:
                hint = ("\n⚠️ MEGA has locked/blocked this account (suspicious "
                        "activity). Unlock it on mega.nz in a browser, then try "
                        "/login again.")
            else:
                hint = ""
            try:
                await wait.edit_text(
                    "❌ <b>Login failed.</b> Check the email/password and try /login again." + hint
                )
            except Exception:
                pass
            _login_state.pop(user_id, None)
            return

        await db.save_mega_account(user_id, email, password)
        await db.save_mega_session(user_id, state["sid"], state["master_key"])
        _login_state.pop(user_id, None)
        await wait.edit_text(
            "✅ <b>Logged in!</b>\n"
            f"📧 <b>{email}</b> saved.\n\n"
            "Your downloads now use your own MEGA account. Send me a link!"
        )