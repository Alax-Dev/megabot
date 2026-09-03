# Central job pipeline: probe → download → analyze → (ask) → process → upload
import asyncio
import logging
import os
import time

from config import (DOWNLOAD_DIR, MAX_FILE_SIZE_MB, MIN_FREE_DISK_MB,
                    RETRY_ATTEMPTS)
from megabot.core.database import db
from megabot.ui import texts
from megabot.ui.keyboards import archive_choice_kb, cancel_kb

log = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


async def _free_disk_mb() -> float:
    import shutil
    usage = shutil.disk_usage(DOWNLOAD_DIR)
    return usage.free / (1024 * 1024)


async def _edit_status(app, job, text, kb=None):
    try:
        await app.edit_message_text(
            job["chat_id"], job["message_id"], text,
            reply_markup=kb, disable_web_page_preview=True,
        )
    except Exception as e:
        # message identical or edited too fast — non-fatal
        log.debug("status edit skipped: %s", e)


async def run_job(app, job: dict):
    job_id = job["_id"]
    urls = job["url"] if isinstance(job.get("url"), list) else [job["url"]]
    multi = len(urls) > 1

    from megabot.downloaders.mega import MegaDownloader

    # ── 1. probe ─────────────────────────────────────────────
    await db.set_job_status(job_id, "downloading")
    display_url = urls[0] if not multi else f"{len(urls)} links (batch)"
    await _edit_status(app, job, texts.status_queued(display_url), cancel_kb(job_id))

    # use the user's own MEGA account if they logged in via /login;
    # the cached session (sid) avoids a fresh MEGA login on every job —
    # repeated logins are what trigger MEGA's suspicious-login lockouts
    account = await db.get_mega_account(job["user_id"])
    session = await db.get_mega_session(job["user_id"])
    downloader = MegaDownloader(
        email=account["email"] if account else None,
        password=account["password"] if account else None,
        saved_session=session,
    )
    infos = []
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            await asyncio.to_thread(downloader.login)
            if downloader.session_fresh:
                state = downloader.session_state()
                await db.save_mega_session(job["user_id"],
                                           state["sid"], state["master_key"])
            infos = []
            for u in urls:
                infos.append(await asyncio.to_thread(downloader.probe, u))
            break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("probe attempt %s failed: %s", attempt, e)
            if "blocked" in str(e).lower():
                # EBLOCKED — no point retrying, the account needs manual unlock
                await db.set_job_status(job_id, "failed", error=str(e)[:300])
                await _edit_status(app, job, texts.error_blocked())
                return
            if attempt == RETRY_ATTEMPTS:
                await db.set_job_status(job_id, "failed", error=str(e)[:300])
                await _edit_status(app, job, texts.error_probe(e))
                return
            await asyncio.sleep(2 ** attempt)

    name = infos[0]["name"] if len(infos) == 1 else f"{len(infos)}-part archive set"
    size = sum(i.get("size", 0) for i in infos)

    # guards: size limit and disk space
    if size and size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await db.set_job_status(job_id, "failed", error="too large")
        await _edit_status(app, job, texts.error_too_large(name, size))
        return
    if size and await _free_disk_mb() < size / (1024 * 1024) * 2 + MIN_FREE_DISK_MB:
        await db.set_job_status(job_id, "failed", error="not enough disk space")
        await _edit_status(app, job, texts.error_disk_space())
        return

    # ── 2. download with live progress ───────────────────────
    dest_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(dest_dir, exist_ok=True)

    last_edit = {"t": 0.0}
    loop = asyncio.get_running_loop()   # capture the bot's loop, not the worker's
    done_before = [0]                   # bytes finished by earlier parts

    def progress_cb(done_bytes: int, total_bytes: int):
        now = time.time()
        if now - last_edit["t"] < 3.0:
            return
        last_edit["t"] = now
        asyncio.run_coroutine_threadsafe(
            _edit_status(app, job, texts.progress_download(
                name, done_before[0] + done_bytes, size),
                cancel_kb(job_id)),
            loop,
        )

    for idx, url in enumerate(urls, 1):
        part_label = f" ({idx}/{len(urls)})" if multi else ""
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                await asyncio.to_thread(
                    downloader.download, url, dest_dir, progress_cb
                )
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("download attempt %s failed%s: %s", attempt, part_label, e)
                if "blocked" in str(e).lower():
                    await db.set_job_status(job_id, "failed", error=str(e)[:300])
                    await _edit_status(app, job, texts.error_blocked())
                    return
                if attempt == RETRY_ATTEMPTS:
                    await db.set_job_status(job_id, "failed", error=str(e)[:300])
                    await _edit_status(app, job, texts.error_download(e))
                    return
                await asyncio.sleep(2 ** attempt)
        done_before[0] += infos[idx - 1].get("size", 0) or 0

    await db.set_job_status(job_id, "processing")

    # ── 3. AI / OpenRouter Processing (if enabled) ───────────
    from config import OPENROUTER_API_KEY
    ai_files = None
    if OPENROUTER_API_KEY:
        try:
            from megabot.ai.pipeline_hook import run_ai_pipeline
            await _edit_status(app, job, texts.status_ai_analyzing(name), cancel_kb(job_id))
            user_prompt = job.get("prompt", "")
            ai_files = await run_ai_pipeline(app, job, dest_dir, user_prompt, _edit_status)
        except Exception as e:
            log.warning("AI processing hook failed: %s", e)
            ai_files = None

    if ai_files:
        await db.set_job_status(job_id, "uploading")
        await _upload_files(app, job, name, ai_files)
        return

    await _edit_status(app, job, texts.status_analyzing(name), cancel_kb(job_id))

    # ── 4. analyze downloaded content (rule-based fallback) ─
    from megabot.analyzers.classify import classify
    analysis = await asyncio.to_thread(classify, dest_dir)
    kind = analysis["kind"]

    # ── 5. branch on content kind ────────────────────────────
    if kind == "archive":
        # lone middle volume of a split set → try to rescue the missing
        # volumes from the user's own MEGA account before giving up
        from megabot.analyzers.classify import lone_continuation_volume
        if len(analysis["archives"]) == 1 and \
                lone_continuation_volume(analysis["archives"][0]):
            lone = analysis["archives"][0]
            await _edit_status(app, job, texts.status_rescue_search(), cancel_kb(job_id))

            def rescue_cb(d, t, label=""):
                now = time.time()
                if now - last_edit["t"] < 3.0:
                    return
                last_edit["t"] = now
                asyncio.run_coroutine_threadsafe(
                    _edit_status(app, job, texts.progress_rescue(label, d, t),
                                 cancel_kb(job_id)),
                    loop,
                )

            rescued = await asyncio.to_thread(
                downloader.rescue_siblings, lone, dest_dir, rescue_cb)
            if rescued:
                analysis = await asyncio.to_thread(classify, dest_dir)
                kind = analysis["kind"]
                await _edit_status(app, job, texts.status_analyzing(name), cancel_kb(job_id))
            else:
                # Don't refuse the job: a lone middle volume usually still
                # holds fully readable files (WinRAR opens it for the same
                # reason). Continue into the normal archive flow — extraction
                # is best-effort now and recovers whatever is inside.
                log.info("no sibling volumes in account — best-effort extract of %s",
                         os.path.basename(lone))

    if kind == "archive":
        archive_path = analysis["archives"][0]
        mode = await db.get_user_setting(job["user_id"], "archive_mode")
        if mode == "ask":
            await db.set_job_status(job_id, "awaiting_choice")
            await _edit_status(
                app, job,
                texts.archive_choice(name, archive_path),
                archive_choice_kb(job_id),
            )
            return  # resumed from the callback handler
        extract = (mode == "extract")
    else:
        extract = False

    await db.set_job_status(job_id, "uploading")
    await _process_and_upload(app, job, dest_dir, analysis, extract_archive=extract)


async def _process_and_upload(app, job, dest_dir: str, analysis: dict,
                              extract_archive: bool = False):
    """Turn downloaded content into Telegram uploads."""
    job_id = job["_id"]
    kind = analysis["kind"]

    files_to_send: list[str] = []
    pdf_path = None

    if kind == "archive" and extract_archive:
        from megabot.processors.archives import safe_extract
        archive_path = analysis["archives"][0]
        out_dir = os.path.join(dest_dir, "extracted")
        os.makedirs(out_dir, exist_ok=True)
        await _edit_status(app, job, texts.status_extracting(analysis["name"]), cancel_kb(job_id))
        try:
            await asyncio.to_thread(safe_extract, archive_path, out_dir)
        except Exception as e:
            # e.g. a split-archive volume without its part 1 — fail loudly
            log.warning("extraction failed for %s: %s", archive_path, e)
            await db.set_job_status(job_id, "failed", error=str(e)[:300])
            await _edit_status(app, job, texts.error_extract(e))
            return
        from megabot.analyzers.classify import classify
        inner = await asyncio.to_thread(classify, out_dir)
        log.info("archive %s extracted → kind=%s, %d file(s)",
                 archive_path, inner["kind"],
                 len(inner["archives"]) + len(inner["videos"]) + len(inner["images"]) + len(inner["others"]))
        # continue processing the EXTRACTED content — replacing kind/analysis
        # entirely. (Keeping kind="archive" here let the elif-chain below
        # overwrite files_to_send with the raw volumes instead.)
        kind, analysis, dest_dir = inner["kind"], inner, out_dir

    if kind == "image_set":
        from megabot.processors.images2pdf import images_to_pdf
        await _edit_status(app, job, texts.status_making_pdf(analysis["name"]), cancel_kb(job_id))
        pdf_name = os.path.splitext(os.path.basename(analysis["name"]))[0] or "images"
        pdf_path = os.path.join(dest_dir, f"{pdf_name}.pdf")
        await asyncio.to_thread(images_to_pdf, analysis["images"], pdf_path)
        files_to_send = [pdf_path]
    elif kind == "video_set":
        files_to_send = analysis["videos"]
    elif kind == "single":
        files_to_send = analysis["others"] + analysis["images"] + analysis["videos"]
    elif kind == "archive":  # upload archive as-is
        files_to_send = analysis["archives"]
    else:  # mixed
        files_to_send = analysis["archives"] + analysis["videos"] + \
            analysis["images"] + analysis["others"]

    await _upload_files(app, job, analysis["name"], files_to_send)


async def _upload_files(app, job: dict, display_name: str, files_to_send: list[str]):
    """Sequential upload with progress edits."""
    job_id = job["_id"]
    if not files_to_send:
        await db.set_job_status(job_id, "failed", error="nothing to upload")
        await _edit_status(app, job, texts.error_empty())
        return

    from megabot.processors.uploader import UploadProgress
    prog = UploadProgress(app, job, files_to_send)
    sent = 0
    for i, path in enumerate(files_to_send, 1):
        await _edit_status(app, job, texts.status_uploading(display_name, i, len(files_to_send)))
        ok = await prog.send(path, thumbs_enabled=await db.get_user_setting(job["user_id"], "video_thumbs"))
        if ok:
            sent += 1
        await asyncio.sleep(1.2)  # be gentle with Telegram flood limits

    if sent == 0:
        # every upload failed — don't pretend success
        await db.set_job_status(job_id, "failed", error="all uploads failed")
        await _edit_status(app, job, texts.ERROR_GENERIC)
        return
    await db.set_job_status(job_id, "done", files_sent=sent)
    await db.bump_user_jobs(job["user_id"])
    await _edit_status(app, job, texts.status_done(display_name, sent, len(files_to_send)))