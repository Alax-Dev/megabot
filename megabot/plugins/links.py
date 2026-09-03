# Link handler — pick up MEGA URLs, create jobs, enqueue them
import uuid

from pyrogram import Client, filters
from pyrogram.types import Message

from config import MAX_JOBS_PER_USER
from megabot.core.database import db
from megabot.core.job_queue import job_queue
from megabot.downloaders.mega import extract_mega_links, link_key
from megabot.ui import texts


@Client.on_message(filters.private & filters.text & ~filters.command(["start", "help", "settings", "stats", "ban", "unban", "broadcast", "login", "logout", "cancel"]))
async def on_link(client: Client, message: Message):
    user_id = message.from_user.id

    # let the login wizard intercept plain text first
    from megabot.plugins.auth import _login_state
    if user_id in _login_state:
        return

    await db.add_user(user_id, message.from_user.username)

    if await db.is_user_banned(user_id):
        await message.reply_text(texts.BANNED)
        return

    links = extract_mega_links(message.text)
    if not links:
        await message.reply_text(texts.NO_LINK, disable_web_page_preview=True)
        return

    active = await db.active_jobs_for_user(user_id)
    if active >= MAX_JOBS_PER_USER:
        await message.reply_text(texts.BUSY.format(limit=MAX_JOBS_PER_USER))
        return

    from megabot.downloaders.mega_raw import RawMega

    links = links[:5]  # hard cap: 5 links per message

    # Extract any accompanying instructions or notes from the user's message
    cleaned_prompt = message.text or ""
    for u in links:
        cleaned_prompt = cleaned_prompt.replace(u, "")
    user_prompt = cleaned_prompt.strip()

    # multiple links in one message → ONE batch job. This is what makes
    # split-archive sets work: all volumes land in the same download dir,
    # so extraction can chain from volume 1 (mega.nz/file URLs carry no
    # filename, so grouping by name is only possible after download).
    if len(links) > 1:
        job_id = uuid.uuid4().hex[:10]
        status_msg = await message.reply_text(
            texts.status_queued(f"{len(links)} links"),
            disable_web_page_preview=True)
        job = await db.create_job(job_id, user_id, message.chat.id, links,
                                  status_msg.id, prompt=user_prompt)
        for u in links:
            await db.cache_link(link_key(u), {"job_id": job_id, "url": u})
        await job_queue.submit(job)
        return

    for url in links:
        # folder links need the full handle#key — refuse truncated ones early
        if "/folder/" in url and not RawMega.parse_folder_url(url):
            await message.reply_text(texts.FOLDER_LINK_TRUNCATED)
            continue

        # dedup cache
        key = link_key(url)
        if await db.get_cached_link(key):
            await message.reply_text(texts.DUPLICATE)
            continue

        job_id = uuid.uuid4().hex[:10]
        status_msg = await message.reply_text(texts.status_queued(url),
                                              disable_web_page_preview=True)
        job = await db.create_job(job_id, user_id, message.chat.id, url,
                                  status_msg.id, prompt=user_prompt)
        await db.cache_link(key, {"job_id": job_id, "url": url})
        await job_queue.submit(job)