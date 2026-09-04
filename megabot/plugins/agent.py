# /agent or /ai status and conversational assistant
import time
from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
from megabot.ai.client import call_openrouter_text, call_openrouter_json

AGENT_SYSTEM_PROMPT = """You are MegaBot AI Agent, a smart, friendly assistant integrated into MegaBot on Telegram.
You assist users with:
- Downloading files and folders from MEGA
- Extracting archives (ZIP, RAR, 7Z, TAR) and deleting unwanted junk/sample files
- Merging images into clean PDF documents
- Renaming, organizing, and filtering files
- Answering questions about MegaBot features (/start, /login, /settings)
- General assistance and tech questions

Formatting guidelines:
- Use Telegram HTML formatting: <b>bold</b>, <i>italic</i>, <code>code</code>, <blockquote>quotes</blockquote>.
- Keep responses concise, clear, and helpful.
- Note: MegaBot enforces complete user privacy. Only file names, extensions, and sizes are inspected; file contents are never read or stored.
"""

# Track bot agent message IDs for reply conversations
_agent_msg_ids = set()


@Client.on_message(filters.command(["agent", "ai"]) & filters.private & filters.incoming & ~filters.bot)
async def agent_command(client: Client, message: Message):
    if not message.from_user or message.from_user.is_bot:
        return

    if not OPENROUTER_API_KEY:
        await message.reply_text(
            "<blockquote>⚠️ <b>AI Agent Inactive</b></blockquote>\n"
            "<code>OPENROUTER_API_KEY</code> is not configured in your <code>.env</code> file.\n\n"
            "Add your key to <code>.env</code> to activate agent capabilities:\n"
            "<code>OPENROUTER_API_KEY=sk-...</code>",
            disable_web_page_preview=True,
        )
        return

    # Check if user provided a query directly: /agent <query>
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        query = parts[1].strip()
        await _respond_to_user(client, message, query)
        return

    # If no query, show interactive agent status & invitation
    status_msg = await message.reply_text("🤖 <i>Connecting to AI Agent…</i>")
    start = time.time()

    try:
        resp = await call_openrouter_json(
            'You are a health check assistant. Respond with JSON only: {"status": "ok"}',
            "ping",
        )
        latency = int((time.time() - start) * 1000)

        provider_name = "OrcaRouter" if "orcarouter" in OPENROUTER_BASE_URL.lower() else "OpenRouter"

        if resp and (resp.get("status") in ["ok", "operational"] or isinstance(resp, dict)):
            text = (
                "<blockquote>🤖 <b>MegaBot AI Agent: Online</b></blockquote>\n"
                f"• <b>Provider:</b> {provider_name}\n"
                f"• <b>Model:</b> <code>{OPENROUTER_MODEL}</code>\n"
                f"• <b>Latency:</b> <code>{latency} ms</code>\n"
                "• <b>Privacy Mode:</b> 🛡️ <i>Active (Zero file content exposed)</i>\n"
                "• <b>File Actions:</b> 📂 <i>Extract, Merge PDF, Zip, Delete Unwanted Files</i>\n"
                "• <b>Sandbox Jail:</b> 🔒 <i>Restricted to job directory</i>\n\n"
                "💬 <b>Talk to Me Directly:</b>\n"
                "• Type: <code>/agent &lt;your message&gt;</code>\n"
                "• Example: <code>/agent what files can you extract?</code>\n"
                "• Or simply <b>reply to this message</b> to chat with me!"
            )
        else:
            text = (
                "<blockquote>⚠️ <b>AI Agent: Provider Busy</b></blockquote>\n"
                f"The AI model <code>{OPENROUTER_MODEL}</code> is temporarily busy or returned an upstream error.\n\n"
                "You can still talk to the agent: <code>/agent &lt;your question&gt;</code>"
            )
    except Exception as e:
        text = (
            "<blockquote>❌ <b>AI Agent: Connection Error</b></blockquote>\n"
            f"Failed to communicate with provider: <code>{e}</code>"
        )

    sent = await status_msg.edit_text(text, disable_web_page_preview=True)
    if sent:
        _agent_msg_ids.add(sent.id)


@Client.on_message(filters.private & filters.incoming & ~filters.bot & filters.reply & ~filters.command(["start", "help", "settings", "stats", "login", "logout", "cancel"]))
async def agent_reply_handler(client: Client, message: Message):
    """Handle replies to agent messages as ongoing conversation."""
    if not OPENROUTER_API_KEY:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return
    # Check if replied to the bot's own message and it was an agent interaction
    if message.reply_to_message.from_user.is_self:
        if message.reply_to_message.id in _agent_msg_ids or "AI Agent" in (message.reply_to_message.text or ""):
            if message.text and not message.text.startswith("/"):
                await _respond_to_user(client, message, message.text)


async def _respond_to_user(client: Client, message: Message, user_text: str):
    """Generate and send conversational AI response."""
    await client.send_chat_action(message.chat.id, ChatAction.TYPING)
    thinking_msg = await message.reply_text("🤔 <i>Thinking…</i>")

    try:
        reply = await call_openrouter_text(AGENT_SYSTEM_PROMPT, user_text)
        if reply:
            sent = await thinking_msg.edit_text(reply)
            if sent:
                _agent_msg_ids.add(sent.id)
        else:
            await thinking_msg.edit_text(
                "<blockquote>⚠️ <b>AI Unavailable</b></blockquote>\n"
                "The upstream AI provider is temporarily unavailable or overloaded. Please try again in a moment."
            )
    except Exception as e:
        await thinking_msg.edit_text(f"❌ Error communicating with AI: <code>{e}</code>")
