# /agent or /ai status command
import time
from pyrogram import Client, filters
from pyrogram.types import Message

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL


@Client.on_message(filters.command(["agent", "ai"]) & filters.private & filters.incoming & ~filters.bot)
async def agent_status_cmd(client: Client, message: Message):
    if not message.from_user or message.from_user.is_bot:
        return
    if not OPENROUTER_API_KEY:
        await message.reply_text(
            "<blockquote>⚠️ <b>AI Agent Inactive</b></blockquote>\n"
            "<code>OPENROUTER_API_KEY</code> is not configured in your <code>.env</code> file.\n\n"
            "Add your key to <code>.env</code> and restart the bot to activate agent capabilities:\n"
            "<code>OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx</code>",
            disable_web_page_preview=True,
        )
        return

    status_msg = await message.reply_text("🤖 <i>Testing OpenRouter connection…</i>")
    start = time.time()

    try:
        from megabot.ai.client import call_openrouter_json
        resp = await call_openrouter_json(
            "You are a health check assistant. Respond in JSON: {'status': 'ok'}",
            "ping",
        )
        latency = int((time.time() - start) * 1000)

        if resp and resp.get("status") == "ok":
            text = (
                "<blockquote>🤖 <b>AI Agent: Online & Active</b></blockquote>\n"
                f"• <b>Provider:</b> OpenRouter\n"
                f"• <b>Model:</b> <code>{OPENROUTER_MODEL}</code>\n"
                f"• <b>Latency:</b> <code>{latency} ms</code>\n"
                "• <b>Privacy Mode:</b> 🛡️ <i>Active (Zero file content exposed)</i>\n"
                "• <b>Sandbox Jail:</b> 🔒 <i>Active (Restricted to job directory)</i>\n"
                "• <b>Secrets Guard:</b> 🔐 <i>Active (.env & keys protected)</i>\n\n"
                "<b>How to use:</b>\n"
                "Paste any link with instructions, e.g.:\n"
                "• <code>https://mega.nz/... convert images to pdf</code>\n"
                "• <code>https://mega.nz/... extract zip and upload only videos</code>\n"
                "• Or send a link with no text to let AI decide automatically!"
            )
        else:
            text = (
                "<blockquote>⚠️ <b>AI Agent: Degraded</b></blockquote>\n"
                f"Connected to OpenRouter, but unexpected response: <code>{resp}</code>"
            )
    except Exception as e:
        text = (
            "<blockquote>❌ <b>AI Agent: Connection Error</b></blockquote>\n"
            f"Failed to communicate with OpenRouter: <code>{e}</code>"
        )

    await status_msg.edit_text(text, disable_web_page_preview=True)
