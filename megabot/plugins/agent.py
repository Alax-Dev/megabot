# /agent or /ai autonomous assistant with tool use & bot management
import json
import logging
import time
from pyrogram import Client, filters
from pyrogram.enums import ChatAction
from pyrogram.types import Message

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL, OWNER_ID
from megabot.ai.client import call_openrouter_text, call_openrouter_json
from megabot.ai.tools import TOOL_DEFINITIONS, execute_tool

log = logging.getLogger(__name__)

# Track bot agent message IDs for ongoing reply conversations
_agent_msg_ids = set()

TOOLS_SYSTEM_PROMPT = f"""You are the autonomous MegaBot AI Agent on Telegram.
You have direct access to tools to manage jobs, tasks, files, settings, and disk storage.

AVAILABLE TOOLS:
{json.dumps(TOOL_DEFINITIONS, indent=2)}

INSTRUCTIONS:
1. Carefully analyze the user's intent:
   - If the user wants to take action (e.g., list/check jobs, cancel a job, delete files, clean disk, check stats, change settings, clear cache, check account, or manage tasks):
     Respond with JSON:
     {{
       "action": "call_tool",
       "tool": "<tool_name>",
       "parameters": {{ ... }},
       "thought": "<brief reason for calling this tool>"
     }}
   - If the user is asking general questions, chatting, or asking about features:
     Respond with JSON:
     {{
       "action": "reply",
       "response": "<friendly, clear response formatted in Telegram HTML (use <b>, <i>, <code>, <blockquote>)>"
     }}
2. Respond with valid JSON only. Do not enclose in markdown ticks if possible.
"""


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
        await _run_agent_turn(client, message, query)
        return

    # If no query, show interactive agent dashboard with tool capabilities
    status_msg = await message.reply_text("🤖 <i>Connecting to AI Agent…</i>")
    start = time.time()

    try:
        resp = await call_openrouter_json(
            'You are a health check assistant. Respond with JSON only: {"status": "ok"}',
            "ping",
        )
        latency = int((time.time() - start) * 1000)

        provider_name = "OrcaRouter" if "orcarouter" in OPENROUTER_BASE_URL.lower() else "OpenRouter"

        text = (
            "<blockquote>🤖 <b>MegaBot Autonomous AI Agent</b></blockquote>\n"
            f"• <b>Status:</b> Online & Ready ✅\n"
            f"• <b>Provider:</b> {provider_name}\n"
            f"• <b>Model:</b> <code>{OPENROUTER_MODEL}</code>\n"
            f"• <b>Latency:</b> <code>{latency} ms</code>\n"
            "• <b>Privacy:</b> 🛡️ <i>Zero file content inspection</i>\n"
            "• <b>Sandbox:</b> 🔒 <i>Enforced job directory jail</i>\n\n"
            "🛠 <b>Agent Tools & Actions:</b>\n"
            "• 📋 <b>Jobs:</b> List, inspect, and track active downloads\n"
            "• ❌ <b>Cancel:</b> Stop running or queued jobs\n"
            "• 🗑️ <b>Files:</b> Delete job files & auto-clean disk storage\n"
            "• ⚙️ <b>Settings:</b> Manage archive modes, PDF merging, and thumbs\n"
            "• 📊 <b>Stats:</b> Real-time disk and worker monitoring\n\n"
            "💬 <b>How to Talk to Me:</b>\n"
            "• Type: <code>/agent &lt;instruction or question&gt;</code>\n"
            "• Or simply <b>reply to this message</b>!\n\n"
            "<i>Try:</i>\n"
            "• <code>/agent show my active jobs</code>\n"
            "• <code>/agent clean disk and free space</code>\n"
            "• <code>/agent how much disk space is left?</code>\n"
            "• <code>/agent cancel job 0c4734d418</code>"
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
    """Handle replies to agent messages as ongoing conversation with tools."""
    if not OPENROUTER_API_KEY:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return
    # Check if replied to the bot's own message and it was an agent interaction
    if message.reply_to_message.from_user.is_self:
        if message.reply_to_message.id in _agent_msg_ids or "AI Agent" in (message.reply_to_message.text or ""):
            if message.text and not message.text.startswith("/"):
                await _run_agent_turn(client, message, message.text)


async def _run_agent_turn(client: Client, message: Message, user_text: str):
    """Autonomous agent reasoning loop with tool execution."""
    await client.send_chat_action(message.chat.id, ChatAction.TYPING)
    thinking_msg = await message.reply_text("🤖 <i>Agent reasoning…</i>")

    user_id = message.from_user.id
    is_owner = (user_id == OWNER_ID)
    context = {"user_id": user_id, "is_owner": is_owner}

    try:
        # Step 1: Query agent with tool definitions
        plan = await call_openrouter_json(TOOLS_SYSTEM_PROMPT, user_text)

        if not plan or not isinstance(plan, dict):
            # Fallback to direct conversational response
            fallback_text = await call_openrouter_text(
                "You are MegaBot AI Agent. Answer the user concisely and helpfully using Telegram HTML.",
                user_text
            )
            if fallback_text:
                sent = await thinking_msg.edit_text(fallback_text)
                if sent:
                    _agent_msg_ids.add(sent.id)
            else:
                await thinking_msg.edit_text("⚠️ Upstream AI provider is temporarily busy. Please try again.")
            return

        action = plan.get("action", "reply")

        # Step 2: If tool call requested
        if action == "call_tool":
            tool_name = plan.get("tool")
            params = plan.get("parameters", {})
            thought = plan.get("thought", "")

            status_update = f"⚙️ <i>Executing tool:</i> <code>{tool_name}</code>…"
            await thinking_msg.edit_text(status_update)

            # Execute tool safely
            tool_result = await execute_tool(tool_name, params, context)

            # Step 3: Summarize tool result for the user
            feedback_prompt = f"""You are the MegaBot AI Agent on Telegram.
You just executed the tool '{tool_name}' with parameters {json.dumps(params)}.
Tool execution output:
{json.dumps(tool_result, indent=2)}

Original user request: "{user_text}"

Now deliver a clear, friendly, and complete final answer to the user in Telegram HTML format (use <b>, <code>, <blockquote>).
Clearly explain what was done or what data was found. Be concise."""

            final_reply = await call_openrouter_text(feedback_prompt, "Summarize result")

            if not final_reply:
                # Fallback clean formatter if second LLM call times out
                final_reply = _format_tool_fallback(tool_name, tool_result)

            sent = await thinking_msg.edit_text(final_reply, disable_web_page_preview=True)
            if sent:
                _agent_msg_ids.add(sent.id)

        else:
            # Direct response
            resp_text = plan.get("response", "")
            if not resp_text:
                resp_text = plan.get("summary", "I am ready to help! What would you like me to do?")
            sent = await thinking_msg.edit_text(resp_text, disable_web_page_preview=True)
            if sent:
                _agent_msg_ids.add(sent.id)

    except Exception as e:
        log.exception("Agent turn error")
        await thinking_msg.edit_text(f"❌ Error during agent execution: <code>{e}</code>")


def _format_tool_fallback(tool_name: str, result: dict) -> str:
    """Format tool results if secondary LLM summarization is unavailable."""
    if tool_name == "list_jobs":
        jobs = result.get("jobs", [])
        if not jobs:
            return "<blockquote>📋 <b>No jobs found.</b></blockquote>\nYou have no active or recent jobs."
        lines = [f"<blockquote>📋 <b>Found {len(jobs)} job(s):</b></blockquote>"]
        for j in jobs:
            st = j.get("status", "unknown")
            jid = j.get("job_id")
            urls = j.get("urls", [])
            u_str = urls[0][:45] + "…" if urls else "unknown"
            lines.append(f"• <code>{jid}</code> | <b>{st.upper()}</b> | <code>{u_str}</code>")
        return "\n".join(lines)

    elif tool_name == "get_system_stats":
        disk = result.get("disk", {})
        queue = result.get("queue", {})
        return (
            "<blockquote>📊 <b>System & Queue Stats</b></blockquote>\n"
            f"• <b>Disk Free:</b> <code>{disk.get('free_mb', 0)} MB</code> / <code>{disk.get('total_mb', 0)} MB</code>\n"
            f"• <b>Active Workers:</b> <code>{queue.get('active_running', 0)}</code>\n"
            f"• <b>Queued Jobs:</b> <code>{queue.get('waiting', 0)}</code>\n"
            f"• <b>Total Lifetime Jobs:</b> <code>{result.get('jobs_total', 0)}</code>"
        )

    elif tool_name == "clean_disk":
        return f"<blockquote>🗑️ <b>Disk Cleanup Complete</b></blockquote>\n{result.get('message', 'Cleaned stale folders.')}"

    elif tool_name == "cancel_job":
        return f"<blockquote>❌ <b>Cancel Job</b></blockquote>\n{result.get('message', 'Job processed.')}"

    elif tool_name == "delete_job_files":
        return f"<blockquote>🗑️ <b>Delete Files</b></blockquote>\n{result.get('message', 'Files processed.')}"

    elif tool_name == "get_user_settings":
        s = result.get("settings", {})
        return (
            "<blockquote>⚙️ <b>Your Settings</b></blockquote>\n"
            f"• <b>Archive Mode:</b> <code>{s.get('archive_mode')}</code>\n"
            f"• <b>Auto PDF:</b> <code>{s.get('image_pdf')}</code>\n"
            f"• <b>Video Thumbs:</b> <code>{s.get('video_thumbs')}</code>"
        )

    else:
        return f"<blockquote>✅ <b>Tool Executed: {tool_name}</b></blockquote>\n<code>{json.dumps(result, indent=2)}</code>"
