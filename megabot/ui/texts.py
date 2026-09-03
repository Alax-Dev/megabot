# All user-facing texts — HTML parse mode, consistent emoji style
from megabot.processors.uploader import human_size, make_progress_bar

LOGO = "⚡"

WELCOME = """<blockquote>{} <b>MegaBot</b></blockquote>
🚀 <b>Your MEGA → Telegram pipeline.</b>

Send me any <b>MEGA link</b> and I will:
📥 Download it with my MEGA account
🔍 Analyze what's inside
📦 Archive? You choose — upload as-is or decompress
🖼️ Image set? I merge it into one ordered <b>PDF</b>
🎬 Videos? Uploaded sequentially, ready to stream

<b>Just paste a link to begin</b> 👇""".format(LOGO)

HELP = """<blockquote>{} <b>How to use MegaBot</b></blockquote>
1️⃣ Paste one or more MEGA links (file or folder)
2️⃣ Watch the live status card with progress bar
3️⃣ If it's an archive — pick what to do with the buttons
4️⃣ Receive your files right here

<b>Supported:</b> zip, rar, 7z, tar • images → PDF • videos • any file

<b>Commands</b>
/start — start the bot
/login — connect your MEGA account
/logout — disconnect it
/settings — your preferences""".format(LOGO)

BANNED = "🚫 You are banned from using this bot."

ERROR_GENERIC = "❌ Something went wrong while processing your job. Please try again."

NO_LINK = ("🤔 I couldn't find a MEGA link in that message.\n"
           "Send me something like:\n<code>https://mega.nz/file/xxxxx#yyyy</code>")

BUSY = ("⏳ You already have an active job. Please wait for it to finish — "
        "max {limit} job(s) at a time.")

DUPLICATE = ("♻️ This link was processed recently.\n"
             "Send it again in a new message if you really want it re-processed.")

FOLDER_LINK_TRUNCATED = ("🔗 That folder link looks truncated — it must contain "
                         "both parts: <code>…/folder/XXXX#YYYY</code>.\n"
                         "Copy the full link from MEGA (Share → Copy link).")


# ── status cards ─────────────────────────────────────────────

def status_queued(url: str) -> str:
    return ("<blockquote>⏳ <b>Queued</b>\n"
            f"🔗 <code>{url[:80]}</code>\n"
            "🧭 Waiting for a free worker…</blockquote>")


def status_folder_listing(name: str, n: int) -> str:
    return ("<blockquote>📂 <b>Folder detected</b>\n"
            f"📁 <b>{name}</b> — {n} file(s)\n"
            "Listing contents…</blockquote>")


def status_analyzing(name: str) -> str:
    return f"<blockquote>🔍 <b>Analyzing</b>\n📁 <b>{name}</b>\nFiguring out what's inside…</blockquote>"


def status_ai_analyzing(name: str) -> str:
    return f"<blockquote>🤖 <b>AI Analyzing</b>\n📁 <b>{name}</b>\nAnalyzing file structure privately…</blockquote>"


def progress_download(name: str, done: int, total: int) -> str:
    percent = int(done * 100 / total) if total else 0
    return ("<blockquote>📥 <b>Downloading from MEGA</b>\n"
            f"{make_progress_bar(percent)} <b>{percent}%</b>\n"
            f"📁 <b>{name}</b>\n"
            f"📦 {human_size(done)} / {human_size(total)}</blockquote>")


def archive_choice(name: str, path: str) -> str:
    return ("<blockquote>📦 <b>Archive detected</b>\n"
            f"📁 <b>{name}</b></blockquote>\n"
            "What should I do with it?")


def status_extracting(name: str) -> str:
    return f"<blockquote>📂 <b>Decompressing</b>\n📁 <b>{name}</b>\nExtracting contents…</blockquote>"


def status_making_pdf(name: str) -> str:
    return f"<blockquote>🖼️ <b>Building PDF</b>\n📁 <b>{name}</b>\nMerging images in order…</blockquote>"


def status_uploading(name: str, i: int, n: int) -> str:
    return f"<blockquote>📤 <b>Uploading</b>\n📁 <b>{name}</b>\nFile {i} / {n}…</blockquote>"


def status_done(name: str, sent: int, total: int) -> str:
    return f"<blockquote>✅ <b>Done</b>\n📁 <b>{name}</b>\n📤 {sent}/{total} file(s) delivered 🎉</blockquote>"


def status_cancelled() -> str:
    return "<blockquote>🛑 <b>Cancelled</b>\nJob stopped, partial files removed.</blockquote>"


# ── errors ───────────────────────────────────────────────────

def error_probe(e: Exception) -> str:
    return (f"<blockquote>❌ <b>Link not readable</b>\n"
            f"<code>{str(e)[:200]}</code>\n"
            "Check the link is valid and public.</blockquote>")


def error_download(e: Exception) -> str:
    return (f"<blockquote>❌ <b>Download failed</b>\n"
            f"<code>{str(e)[:200]}</code>\n"
            "MEGA may be rate-limiting — try again in a few minutes.</blockquote>")


def error_too_large(name: str, size: int) -> str:
    return ("<blockquote>❌ <b>Too large</b>\n"
            f"📁 <b>{name}</b> is {human_size(size)} — over the bot limit.</blockquote>")


def error_disk_space() -> str:
    return "<blockquote>❌ <b>Not enough disk space</b>\nThe server can't hold this file right now.</blockquote>"


def error_empty() -> str:
    return "<blockquote>❌ <b>Nothing to upload</b>\nThe archive appears to be empty.</blockquote>"


def error_expired() -> str:
    return ("<blockquote>⌛ <b>Files expired</b>\n"
            "The download was cleaned up while waiting for your choice.\n"
            "Send the link again to retry.</blockquote>")


def error_blocked() -> str:
    return ("<blockquote>🚫 <b>MEGA account blocked</b>\n"
            "MEGA flagged this account as suspicious. Open mega.nz in a browser, "
            "follow the unlock steps, then use /login again.</blockquote>")


def status_rescue_search() -> str:
    return ("<blockquote>🧩 <b>Split archive detected</b>\n"
            "Searching your MEGA account for the missing parts…</blockquote>")


def progress_rescue(label: str, done: int, total: int) -> str:
    percent = int(done * 100 / total) if total else 0
    return ("<blockquote>🧩 <b>Fetching missing parts from your MEGA</b>\n"
            f"{make_progress_bar(percent)} <b>{percent}%</b>\n"
            f"📁 <b>{label}</b>\n"
            f"📦 {human_size(done)} / {human_size(total)}</blockquote>")


def error_missing_volumes(fname: str) -> str:
    return ("<blockquote>🧩 <b>Only one part received</b>\n"
            f"📁 <code>{fname[:80]}</code> is a <b>middle volume</b> of a split "
            "archive — I also checked your MEGA account but couldn't find "
            "the other parts there.\n\n"
            "👉 Send <b>ALL parts together in ONE message</b> (or the MEGA "
            "folder link) and I'll download and extract the whole set.</blockquote>")


def error_extract(e: Exception) -> str:
    msg = str(e)
    if "first volume" in msg.lower():
        return ("<blockquote>🧩 <b>Split archive — missing part 1</b>\n"
                "This RAR is one volume of a multi-part set and the first "
                "volume (.part1.rar / .rar) is missing.\n"
                "Send me <b>ALL parts together in one message</b> "
                "(paste every MEGA link at once) and I'll extract the whole "
                "set.</blockquote>")
    if "non-zero exit status" in msg.lower():
        return ("<blockquote>❌ <b>Extraction failed</b>\n"
                "The archive is likely incomplete, corrupted, or password-protected.\n"
                "If it's a split set, send <b>all parts in one message</b>.</blockquote>")
    return (f"<blockquote>❌ <b>Extraction failed</b>\n"
            f"<code>{msg[:200]}</code></blockquote>")