# Callback handlers — archive choice, cancel
import asyncio
import shutil

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from megabot.core.database import db
from megabot.core.job_queue import job_queue
from megabot.ui import texts


@Client.on_callback_query(filters.regex(r"^arch:(\w+):(archive|extract)$"))
async def archive_choice(client: Client, cq: CallbackQuery):
    job_id = cq.matches[0].group(1)
    choice = cq.matches[0].group(2)

    job = await db.get_job(job_id)
    if not job or job["user_id"] != cq.from_user.id:
        await cq.answer("Not your job.", show_alert=True)
        return
    if job["status"] != "awaiting_choice":
        await cq.answer("This job already moved on.", show_alert=True)
        return

    await cq.answer()
    await db.set_job_status(job_id, "uploading")

    from config import DOWNLOAD_DIR
    from megabot.analyzers.classify import classify
    from megabot.core.pipeline import _process_and_upload, _edit_status

    dest_dir = f"{DOWNLOAD_DIR}/{job_id}"
    analysis = await asyncio.to_thread(classify, dest_dir)

    if not any(analysis[k] for k in ("archives", "images", "videos", "others")):
        # files vanished (e.g. cleaned up after a restart) — nothing to resume
        await db.set_job_status(job_id, "failed", error="files expired")
        await cq.message.edit_text(texts.error_expired(),
                                   disable_web_page_preview=True)
        return

    # re-register as running task so cancel still works during this phase
    task = asyncio.create_task(
        _process_and_upload(client, job, dest_dir, analysis,
                            extract_archive=(choice == "extract"))
    )
    job_queue.running[job_id] = task
    try:
        await task
    except asyncio.CancelledError:
        await db.set_job_status(job_id, "cancelled")
        await _edit_status(client, job, texts.status_cancelled())
    finally:
        job_queue.running.pop(job_id, None)
        # the worker kept these files alive for us — now it's our job to clean
        shutil.rmtree(dest_dir, ignore_errors=True)


@Client.on_callback_query(filters.regex(r"^cancel:(\w+)$"))
async def cancel_job(client: Client, cq: CallbackQuery):
    job_id = cq.matches[0].group(1)
    job = await db.get_job(job_id)
    if not job or job["user_id"] != cq.from_user.id:
        await cq.answer("Not your job.", show_alert=True)
        return

    cancelled = await job_queue.cancel_job(job_id)
    if cancelled:
        await db.set_job_status(job_id, "cancelled")
        await cq.answer("Job cancelled.")
        try:
            await cq.message.edit_text(texts.status_cancelled(),
                                       disable_web_page_preview=True)
        except Exception:
            pass
    elif job.get("status") == "awaiting_choice":
        # paused job — no running task to cancel, just mark it and clean up
        await db.set_job_status(job_id, "cancelled")
        from config import DOWNLOAD_DIR
        shutil.rmtree(f"{DOWNLOAD_DIR}/{job_id}", ignore_errors=True)
        await cq.answer("Job cancelled.")
        try:
            await cq.message.edit_text(texts.status_cancelled(),
                                       disable_web_page_preview=True)
        except Exception:
            pass
    else:
        await cq.answer("This job is no longer running.")