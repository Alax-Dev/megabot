# Autonomous AI Agent Plugin — Natural Language Brain & Tool Execution Engine
import asyncio
from collections import defaultdict
import json
import logging
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_BASE_URL,
    OWNER_ID,
    MAX_JOBS_PER_USER,
)
from megabot.ai.client import call_openrouter_text, call_openrouter_json
from megabot.ai.tools import TOOL_DEFINITIONS, execute_tool
from megabot.core.database import db
from megabot.downloaders import extract_supported_links, is_supported_link
from megabot.ui import texts

log = logging.getLogger(__name__)

# Sliding conversation memory: user_id -> list of {"role": "user"|"assistant", "content": str}
_conversation_memory = defaultdict(list)
MAX_HISTORY_TURNS = 8

AGENT_SYSTEM_PROMPT = f"""You are the autonomous MegaBot AI Agent on Telegram.
You have FULL authority and DIRECT access to tools to download links, extract/unzip archives, delete files, clean server storage, inspect files, manage jobs, and adjust settings.

AVAILABLE TOOLS:
{json.dumps(TOOL_DEFINITIONS, indent=2)}

CAPABILITIES & RULES:
1. TOOL DISPATCH:
   - When the user sends MEGA (mega.nz) or MediaFire (mediafire.com) link(s), or asks to download a URL:
     Call tool `start_download` with the URLs and any instructions (e.g., 'unzip archive', 'extract only mp4', 'merge images to pdf', 'delete samples').
   - When the user asks to unzip, decompress, or extract archives (ZIP, RAR, 7Z, TAR, GZ):
     Call tool `unzip_files`.
   - When the user asks to delete job files from server disk:
     Call tool `delete_job_files`.
   - When the user asks to clean disk or free up storage:
     Call tool `clean_disk`.
   - When the user asks to cancel a job:
     Call tool `cancel_job`.
   - When the user asks about jobs, queue, or history:
     Call tool `list_jobs` or `get_job_details`.
   - When the user asks what files are inside a downloaded job directory:
     Call tool `list_job_files`.
   - When the user asks about disk space or server statistics:
     Call tool `get_system_stats`.
   - When the user asks to change settings (archive mode, PDF merging, video thumbs):
     Call tool `update_user_setting`.
   - When the user asks to clear cache:
     Call tool `clear_cache`.

2. MULTI-STEP REASONING:
   - If a request requires multiple steps (e.g. check jobs then unzip, or cancel then delete), call the first tool.
   - You will receive the tool output and can call the next tool or give the final reply.

3. CONVERSATIONAL BEHAVIOR:
   - If the user greets, chats, asks what you can do, or asks about features:
     Respond warmly and clearly in Telegram HTML format (<b>, <i>, <code>, <blockquote>).
     Explicitly state that you have autonomous tools to download MEGA/MediaFire links, unzip archives, convert images to PDF, delete files, and manage disk space!

4. RESPONSE FORMAT (Respond with JSON only):
   To execute a tool:
   {{
     "action": "call_tool",
     "tool": "<tool_name>",
     "parameters": {{ ... }},
     "thought": "<brief reason>"
   }}

   To reply directly to the user:
   {{
     "action": "reply",
     "response": "<friendly response formatted in Telegram HTML (use <b>, <i>, <code>, <blockquote>)>"
   }}
"""


def _add_memory(user_id: int, role: str, content: str):
    """Store recent turn in per-user conversation memory."""
    if not content:
        return
    history = _conversation_memory[user_id]
    history.append({"role": role, "content": str(content)[:800]})
    if len(history) > MAX_HISTORY_TURNS * 2:
        _conversation_memory[user_id] = history[-MAX_HISTORY_TURNS * 2:]


@Client.on_message(filters.command(["agent", "ai"]) & filters.private & filters.incoming & ~filters.bot)
async def agent_command(client: Client, message: Message):
    """Show interactive AI Agent dashboard or run inline query."""
    if not message.from_user or message.from_user.is_bot:
        return

    # Check if user provided an inline query: /agent <query>
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        query = parts[1].strip()
        await _run_agent_turn(client, message, query)
        return

    # If no query, show interactive agent dashboard
    status_msg = await message.reply_text("🤖 <i>Connecting to AI Agent…</i>")
    start = time.time()

    provider_name = "OrcaRouter" if "orcarouter" in OPENROUTER_BASE_URL.lower() else "OpenRouter"

    try:
        resp = await call_openrouter_json(
            'You are a health check assistant. Respond with JSON only: {"status": "ok"}',
            "ping",
        )
        latency = int((time.time() - start) * 1000)

        text = (
            "<blockquote>🤖 <b>MegaBot Autonomous AI Agent</b></blockquote>\n"
            f"• <b>Status:</b> Online & Ready ✅\n"
            f"• <b>Provider:</b> {provider_name}\n"
            f"• <b>Model:</b> <code>{OPENROUTER_MODEL}</code>\n"
            f"• <b>Latency:</b> <code>{latency} ms</code>\n"
            "• <b>Privacy:</b> 🛡️ <i>Zero file content inspection</i>\n"
            "• <b>Sandbox:</b> 🔒 <i>Enforced job directory jail</i>\n\n"
            "🛠 <b>Autonomous Tools & Capabilities:</b>\n"
            "• 📥 <b>Downloads:</b> MEGA.nz & MediaFire.com (files & folders)\n"
            "• 📦 <b>Unzip:</b> Extract ZIP, RAR, 7Z, TAR archives automatically\n"
            "• 🖼️ <b>PDF:</b> Merge image sets into single ordered PDFs\n"
            "• 🗑️ <b>Files:</b> Delete job files & auto-clean server disk\n"
            "• 📋 <b>Jobs:</b> List, inspect, track, and cancel active jobs\n"
            "• ⚙️ <b>Settings:</b> Manage extraction modes & video thumbnails\n\n"
            "💬 <b>Chat with me directly:</b>\n"
            "Send any message, paste download links, or ask me to perform tasks!"
        )
    except Exception as e:
        text = (
            "<blockquote>⚠️ <b>AI Agent: Connection Warning</b></blockquote>\n"
            f"Could not contact AI provider: <code>{e}</code>\n"
            "<i>Downloads are still processed with built-in auto-extraction.</i>"
        )

    await status_msg.edit_text(text, disable_web_page_preview=True)


@Client.on_message(filters.command("cancel") & filters.private & filters.incoming & ~filters.bot)
async def cancel_command(client: Client, message: Message):
    """Direct shortcut command to cancel active jobs."""
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    target_id = parts[1].strip() if len(parts) > 1 else ""

    context = {
        "user_id": user_id,
        "is_owner": (user_id == OWNER_ID),
        "client": client,
        "chat_id": message.chat.id,
    }

    res = await execute_tool("cancel_job", {"job_id": target_id}, context)
    if res.get("status") == "success":
        await message.reply_text(f"<blockquote>❌ <b>Job Cancelled</b></blockquote>\n{res.get('message')}")
    else:
        await message.reply_text(f"<blockquote>⚠️ <b>Cancel Failed</b></blockquote>\n{res.get('message')}")


@Client.on_message(
    filters.private
    & filters.incoming
    & ~filters.bot
    & ~filters.service
    & filters.text
    & ~filters.command([
        "start", "help", "settings", "stats", "ban", "unban",
        "broadcast", "login", "logout", "cancel", "agent", "ai"
    ])
)
async def on_user_message(client: Client, message: Message):
    """Primary entry point for ALL user messages (text, questions, links, requests)."""
    if not message.from_user or message.from_user.is_bot or message.from_user.is_self:
        return

    user_id = message.from_user.id

    # Allow the login wizard to intercept credentials if active
    from megabot.plugins.auth import _login_state
    if user_id in _login_state:
        return

    await db.add_user(user_id, message.from_user.username)

    if await db.is_user_banned(user_id):
        await message.reply_text(texts.BANNED)
        return

    # Dispatch directly to the AI Agent reasoning engine
    await _run_agent_turn(client, message, message.text.strip())


async def _run_agent_turn(client: Client, message: Message, user_text: str):
    """Autonomous agent reasoning loop with tool execution and multi-turn context."""
    user_id = message.from_user.id
    is_owner = (user_id == OWNER_ID)
    chat_id = message.chat.id

    detected_links = extract_supported_links(user_text)

    context = {
        "user_id": user_id,
        "is_owner": is_owner,
        "client": client,
        "chat_id": chat_id,
    }

    # If OpenRouter is not configured:
    if not OPENROUTER_API_KEY:
        if detected_links:
            res = await execute_tool("start_download", {"urls": detected_links, "instruction": user_text}, context)
            if res.get("status") == "success":
                await message.reply_text(
                    f"🚀 <b>Download Queued!</b>\nJob ID: <code>{res.get('job_id')}</code>\n"
                    "<i>(Configure OPENROUTER_API_KEY to activate full AI conversational capabilities.)</i>"
                )
            else:
                await message.reply_text(f"❌ {res.get('message')}")
            return
        else:
            await message.reply_text(
                "<blockquote>🤖 <b>MegaBot AI Agent</b></blockquote>\n"
                "To chat with the AI Agent and use autonomous tools, set <code>OPENROUTER_API_KEY</code> in your <code>.env</code> file.\n\n"
                "You can still download MEGA and MediaFire links by pasting them here!",
                disable_web_page_preview=True,
            )
            return

    await client.send_chat_action(chat_id, ChatAction.TYPING)
    status_msg = await message.reply_text("🤖 <i>Agent reasoning…</i>")

    # Build context with conversation history and detected links
    recent_history = ""
    if _conversation_memory[user_id]:
        h_lines = []
        for turn in _conversation_memory[user_id][-6:]:
            pfx = "User" if turn["role"] == "user" else "AI Agent"
            h_lines.append(f"{pfx}: {turn['content']}")
        recent_history = "\nRecent Conversation History:\n" + "\n".join(h_lines)

    extra_info = ""
    if detected_links:
        extra_info += f"\nDetected Download Links: {json.dumps(detected_links)}\n"

    current_prompt = f"User Request: {user_text}{extra_info}{recent_history}"

    max_steps = 3
    final_reply_text = None

    for step in range(max_steps):
        try:
            plan = await call_openrouter_json(AGENT_SYSTEM_PROMPT, current_prompt)
        except Exception as e:
            log.warning("OpenRouter call failed in step %d: %s", step, e)
            plan = None

        if not plan or not isinstance(plan, dict):
            # Fallback: if links are detected on step 0, ensure download starts!
            if step == 0 and detected_links:
                res = await execute_tool("start_download", {"urls": detected_links, "instruction": user_text}, context)
                if res.get("status") == "success":
                    final_reply_text = (
                        f"<blockquote>🚀 <b>Download Queued</b></blockquote>\n"
                        f"• <b>Job ID:</b> <code>{res.get('job_id')}</code>\n"
                        f"• <b>Links:</b> {len(detected_links)} link(s)\n"
                        f"• <b>Extraction:</b> <i>Auto-extract archives enabled</i>\n\n"
                        f"<i>Live progress status is running above!</i>"
                    )
                else:
                    final_reply_text = f"❌ {res.get('message')}"
                break

            # Fallback conversational response
            fb_text = await call_openrouter_text(
                "You are MegaBot AI Agent. Answer concisely in Telegram HTML.",
                user_text
            )
            final_reply_text = fb_text or "⚠️ I'm temporarily unable to reach the AI engine. Please try again shortly."
            break

        action = plan.get("action", "reply")

        if action == "call_tool":
            tool_name = plan.get("tool")
            params = plan.get("parameters", {})
            if not isinstance(params, dict):
                params = {}

            # If user sent links and model called start_download without passing URLs, auto-fill
            if tool_name == "start_download" and not params.get("urls") and detected_links:
                params["urls"] = detected_links

            try:
                await status_msg.edit_text(f"⚙️ <i>Using tool:</i> <code>{tool_name}</code>…")
            except Exception:
                pass

            # Execute tool
            tool_res = await execute_tool(tool_name, params, context)

            # If tool is start_download and successful, we can finalize immediately
            if tool_name == "start_download" and tool_res.get("status") == "success":
                jid = tool_res.get("job_id")
                n_urls = len(tool_res.get("urls", []))
                inst = tool_res.get("instruction", "")
                inst_str = f"\n• <b>Instructions:</b> <i>{inst}</i>" if inst else ""
                final_reply_text = (
                    f"<blockquote>🚀 <b>Download Started</b></blockquote>\n"
                    f"• <b>Job ID:</b> <code>{jid}</code>\n"
                    f"• <b>Links:</b> {n_urls} link(s)\n"
                    f"• <b>Mode:</b> Auto-extract archives active{inst_str}\n\n"
                    f"<i>Watch the live progress card above!</i>"
                )
                break

            # Otherwise, feed tool result back for next iteration
            current_prompt = (
                f"Original User Request: {user_text}\n"
                f"You executed tool '{tool_name}' with parameters {json.dumps(params)}.\n"
                f"Tool Result:\n{json.dumps(tool_res, indent=2)}\n\n"
                "If the task is complete, respond with action 'reply' and provide a clear, helpful response in Telegram HTML. "
                "If another tool is needed, respond with action 'call_tool'."
            )

        else:
            # Action is reply
            final_reply_text = plan.get("response") or plan.get("summary")
            break

    if not final_reply_text:
        final_reply_text = "✅ Done."

    try:
        await status_msg.edit_text(final_reply_text, disable_web_page_preview=True)
    except Exception as e:
        log.warning("Could not edit status message: %s", e)
        try:
            await message.reply_text(final_reply_text, disable_web_page_preview=True)
        except Exception:
            pass

    # Save to memory
    _add_memory(user_id, "user", user_text)
    _add_memory(user_id, "assistant", final_reply_text)
