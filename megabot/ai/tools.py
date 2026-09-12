# AI Agent Tool Registry & Execution Engine
import asyncio
import logging
import os
import shutil
import uuid
from typing import Optional

from config import DOWNLOAD_DIR, OWNER_ID, MAX_JOBS_PER_USER
from megabot.core.database import db
from megabot.core.job_queue import job_queue
from megabot.downloaders import extract_supported_links, get_link_key, is_supported_link
from megabot.ui import texts

log = logging.getLogger(__name__)

# Available tools exposed to the AI Agent
TOOL_DEFINITIONS = [
    {
        "name": "start_download",
        "description": "Download one or more files/folders from MEGA, MediaFire, MP4Upload, or TeraBox. Automatically queues and tracks the download with optional custom instructions (e.g., unzip archives, merge images into PDF, filter files, keep archive).",
        "parameters": {
            "urls": "A list of MEGA, MediaFire, MP4Upload, or TeraBox URL strings, or a single URL string (required).",
            "instruction": "Optional instructions for what to do with the files (e.g. 'unzip archive', 'extract only videos', 'convert images to pdf', 'delete samples')."
        }
    },
    {
        "name": "list_jobs",
        "description": "List active, queued, or recently finished download jobs. Users see their own jobs; bot owner sees all.",
        "parameters": {
            "status": "Optional filter: 'all', 'queued', 'downloading', 'processing', 'uploading', 'done', 'failed', 'cancelled'. Default 'all'.",
            "limit": "Maximum number of jobs to return (default 5, max 10)."
        }
    },
    {
        "name": "get_job_details",
        "description": "Get detailed status, URLs, error logs, and current progress for a specific job ID.",
        "parameters": {
            "job_id": "The job ID to inspect (required)."
        }
    },
    {
        "name": "list_job_files",
        "description": "Inspect and list all downloaded files currently inside a job's sandboxed directory (filenames, sizes, types).",
        "parameters": {
            "job_id": "The job ID whose downloaded files to inspect (required)."
        }
    },
    {
        "name": "unzip_files",
        "description": "Unzip or extract archive files (ZIP, RAR, 7Z, TAR, GZ). Can immediately extract a job's downloaded archive or enable automatic unzipping for future downloads.",
        "parameters": {
            "job_id": "Optional job ID to unzip immediately. If omitted, targets user's latest job.",
            "enable_auto_unzip": "Optional boolean: set true to enable automatic archive extraction for all future downloads."
        }
    },
    {
        "name": "delete_job_files",
        "description": "Delete downloaded files for a specific job ID from the server disk to save space.",
        "parameters": {
            "job_id": "The job ID whose files should be deleted. If omitted, targets user's latest finished/failed job."
        }
    },
    {
        "name": "cancel_job",
        "description": "Cancel a running or queued job and delete its temporary files.",
        "parameters": {
            "job_id": "The job ID to cancel. If omitted, attempts to cancel user's active running or queued job."
        }
    },
    {
        "name": "clean_disk",
        "description": "Scan downloads directory and delete stale/orphaned folders to free up disk storage space.",
        "parameters": {}
    },
    {
        "name": "get_system_stats",
        "description": "Get current server disk usage, active workers, queue size, total jobs, and database stats.",
        "parameters": {}
    },
    {
        "name": "get_user_settings",
        "description": "View current user preferences (archive_mode, image_pdf, video_thumbs).",
        "parameters": {}
    },
    {
        "name": "update_user_setting",
        "description": "Change a user preference setting.",
        "parameters": {
            "key": "Setting name: 'archive_mode', 'image_pdf', 'video_thumbs', or 'terabox_cookie'.",
            "value": "New value. For archive_mode: 'extract', 'archive', or 'ask'. For image_pdf/video_thumbs: true or false. For terabox_cookie: string ndus cookie value."
        }
    },
    {
        "name": "clear_cache",
        "description": "Clear duplicate link cache so any previously downloaded MEGA, MediaFire, MP4Upload, or TeraBox link can be processed again immediately.",
        "parameters": {}
    },
    {
        "name": "get_account_info",
        "description": "Check if user has a custom MEGA account logged in.",
        "parameters": {}
    },
    {
        "name": "logout_mega_account",
        "description": "Log out user from their custom MEGA account and remove saved session credentials.",
        "parameters": {}
    }
]


async def execute_tool(tool_name: str, params: dict, context: dict) -> dict:
    """
    Execute a tool safely using the provided context (user_id, is_owner, client, chat_id).
    Returns a dictionary with execution results.
    """
    user_id = context.get("user_id")
    is_owner = context.get("is_owner", False)
    client = context.get("client")
    chat_id = context.get("chat_id")

    try:
        # ── 1. start_download ────────────────────────────────
        if tool_name == "start_download":
            raw_urls = params.get("urls")
            if not raw_urls:
                return {"status": "error", "message": "No URLs provided to download."}

            if isinstance(raw_urls, str):
                urls = extract_supported_links(raw_urls) or [raw_urls.strip()]
            elif isinstance(raw_urls, list):
                urls = []
                for u in raw_urls:
                    urls.extend(extract_supported_links(str(u)) or [str(u).strip()])
            else:
                return {"status": "error", "message": "Invalid format for URLs."}

            # Filter valid URLs
            valid_urls = [u for u in urls if is_supported_link(u)]
            if not valid_urls:
                return {
                    "status": "error",
                    "message": "No valid MEGA, MediaFire, MP4Upload, or TeraBox links found. Links must start with mega.nz, mediafire.com, mp4upload.com, or terabox/1024tera."
                }

            valid_urls = valid_urls[:5]  # limit 5 per batch

            # Check active jobs limit
            if user_id:
                active = await db.active_jobs_for_user(user_id)
                if active >= MAX_JOBS_PER_USER:
                    return {
                        "status": "error",
                        "message": f"User already has {active} active job(s). Maximum allowed is {MAX_JOBS_PER_USER}. Wait for one to finish."
                    }

            # Check folder link validity
            from megabot.downloaders.mega_raw import RawMega
            for u in valid_urls:
                if "mega." in u and "/folder/" in u and not RawMega.parse_folder_url(u):
                    return {
                        "status": "error",
                        "message": f"MEGA folder link '{u}' is truncated. It requires both folder ID and decryption key (#key)."
                    }

            # Check duplicate cache
            for u in valid_urls:
                key = get_link_key(u)
                cached = await db.get_cached_link(key)
                if cached:
                    c_jid = cached.get("job_id")
                    if c_jid:
                        job_doc = await db.get_job(c_jid)
                        if job_doc and job_doc.get("status") in ["queued", "downloading", "processing", "uploading"]:
                            return {
                                "status": "error",
                                "message": f"Link '{u}' is currently being processed in active job {c_jid}. Please wait for it to complete."
                            }

            instruction = str(params.get("instruction", "")).strip()
            job_id = uuid.uuid4().hex[:10]

            # Create status card message on Telegram if client & chat_id are present
            status_msg_id = 0
            if client and chat_id:
                try:
                    display_text = texts.status_queued(f"{len(valid_urls)} link(s)" if len(valid_urls) > 1 else valid_urls[0])
                    msg = await client.send_message(chat_id, display_text, disable_web_page_preview=True)
                    status_msg_id = msg.id
                except Exception as me:
                    log.warning("Could not send initial status card message: %s", me)

            job = await db.create_job(
                job_id,
                user_id=user_id or 0,
                chat_id=chat_id or 0,
                url=valid_urls if len(valid_urls) > 1 else valid_urls[0],
                message_id=status_msg_id,
                prompt=instruction
            )

            for u in valid_urls:
                await db.cache_link(get_link_key(u), {"job_id": job_id, "url": u})

            await job_queue.submit(job)

            return {
                "status": "success",
                "job_id": job_id,
                "urls": valid_urls,
                "instruction": instruction,
                "message": f"Job {job_id} queued successfully for {len(valid_urls)} link(s)."
            }

        # ── 2. list_jobs ─────────────────────────────────────
        elif tool_name == "list_jobs":
            status = params.get("status", "all")
            limit = min(int(params.get("limit", 5)), 10)
            target_user = None if is_owner else user_id
            jobs = await db.list_jobs(user_id=target_user, status=status, limit=limit)

            job_list = []
            for j in jobs:
                jid = j.get("_id")
                is_running = jid in job_queue.running
                st = "running" if is_running else j.get("status")
                raw_u = j.get("url")
                urls = raw_u if isinstance(raw_u, list) else [raw_u]
                job_list.append({
                    "job_id": jid,
                    "status": st,
                    "urls": urls,
                    "created_at": str(j.get("created_at")),
                    "files_sent": j.get("files_sent", 0),
                    "prompt": j.get("prompt", ""),
                    "error": j.get("error"),
                })
            return {"status": "success", "count": len(job_list), "jobs": job_list}

        # ── 3. get_job_details ───────────────────────────────
        elif tool_name == "get_job_details":
            job_id = str(params.get("job_id", "")).strip()
            if not job_id:
                return {"status": "error", "message": "job_id is required"}

            job = await db.get_job(job_id)
            if not job:
                return {"status": "error", "message": f"Job {job_id} not found."}
            if not is_owner and job.get("user_id") != user_id:
                return {"status": "error", "message": "Permission denied: not your job."}

            is_running = job_id in job_queue.running
            job_dir = os.path.join(DOWNLOAD_DIR, job_id)
            has_files_on_disk = os.path.exists(job_dir)

            return {
                "status": "success",
                "job_id": job_id,
                "current_status": "running" if is_running else job.get("status"),
                "urls": job.get("url"),
                "prompt": job.get("prompt", ""),
                "files_sent": job.get("files_sent", 0),
                "has_files_on_disk": has_files_on_disk,
                "error": job.get("error"),
                "created_at": str(job.get("created_at")),
            }

        # ── 4. list_job_files ────────────────────────────────
        elif tool_name == "list_job_files":
            job_id = str(params.get("job_id", "")).strip()
            if not job_id:
                return {"status": "error", "message": "job_id is required"}

            job = await db.get_job(job_id)
            if job and not is_owner and job.get("user_id") != user_id:
                return {"status": "error", "message": "Permission denied: not your job."}

            job_dir = os.path.join(DOWNLOAD_DIR, job_id)
            if not os.path.isdir(job_dir):
                return {"status": "success", "job_id": job_id, "file_count": 0, "files": [], "message": f"No files on disk for job {job_id}."}

            found_files = []
            for root, _, files in os.walk(job_dir):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, job_dir)
                    try:
                        sz = os.path.getsize(full)
                        found_files.append({
                            "path": rel,
                            "filename": f,
                            "size_bytes": sz,
                            "size_mb": round(sz / (1024 * 1024), 2),
                            "ext": os.path.splitext(f)[1].lower()
                        })
                    except Exception:
                        pass

            return {"status": "success", "job_id": job_id, "file_count": len(found_files), "files": found_files}

        # ── 5. cancel_job ────────────────────────────────────
        elif tool_name == "cancel_job":
            job_id = str(params.get("job_id", "")).strip()
            if not job_id and user_id:
                # Target user's active job automatically
                active_jobs = await db.list_jobs(user_id=user_id, limit=5)
                for j in active_jobs:
                    if j.get("status") in ["queued", "downloading", "processing", "uploading"]:
                        job_id = j.get("_id")
                        break

            if not job_id:
                return {"status": "error", "message": "No job_id provided and no active job found."}

            job = await db.get_job(job_id)
            if not job:
                return {"status": "error", "message": f"Job {job_id} not found."}
            if not is_owner and job.get("user_id") != user_id:
                return {"status": "error", "message": "Permission denied: you can only cancel your own jobs."}

            cancelled = await job_queue.cancel_job(job_id)
            await db.set_job_status(job_id, "cancelled")

            job_dir = os.path.join(DOWNLOAD_DIR, job_id)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir, ignore_errors=True)

            return {
                "status": "success",
                "job_id": job_id,
                "message": f"Job {job_id} has been cancelled and its workspace cleaned up.",
                "was_running": cancelled
            }

        # ── 6. delete_job_files ──────────────────────────────
        elif tool_name == "delete_job_files":
            job_id = str(params.get("job_id", "")).strip()
            if not job_id and user_id:
                # Target latest job
                user_jobs = await db.list_jobs(user_id=user_id, limit=1)
                if user_jobs:
                    job_id = user_jobs[0].get("_id")

            if not job_id:
                return {"status": "error", "message": "job_id is required"}

            job = await db.get_job(job_id)
            if job and not is_owner and job.get("user_id") != user_id:
                return {"status": "error", "message": "Permission denied: not your job files."}

            job_dir = os.path.join(DOWNLOAD_DIR, job_id)
            if not os.path.exists(job_dir):
                return {"status": "success", "message": f"No files found for job {job_id} on disk (already cleaned)."}

            size_mb = 0.0
            for root, _, files in os.walk(job_dir):
                for f in files:
                    try:
                        size_mb += os.path.getsize(os.path.join(root, f)) / (1024 * 1024)
                    except Exception:
                        pass

            shutil.rmtree(job_dir, ignore_errors=True)
            return {
                "status": "success",
                "job_id": job_id,
                "message": f"Successfully deleted files for job {job_id}.",
                "freed_mb": round(size_mb, 2)
            }

        # ── 7. clean_disk ────────────────────────────────────
        elif tool_name == "clean_disk":
            if not os.path.isdir(DOWNLOAD_DIR):
                return {"status": "success", "freed_mb": 0, "cleaned_folders": 0}

            cleaned = 0
            total_freed_mb = 0.0
            active_ids = set(job_queue.running.keys())

            for name in os.listdir(DOWNLOAD_DIR):
                if name in active_ids:
                    continue  # do not touch active jobs
                folder = os.path.join(DOWNLOAD_DIR, name)
                if not os.path.isdir(folder):
                    continue

                for root, _, files in os.walk(folder):
                    for f in files:
                        try:
                            total_freed_mb += os.path.getsize(os.path.join(root, f)) / (1024 * 1024)
                        except Exception:
                            pass

                shutil.rmtree(folder, ignore_errors=True)
                cleaned += 1

            return {
                "status": "success",
                "cleaned_folders": cleaned,
                "freed_mb": round(total_freed_mb, 2),
                "message": f"Cleaned {cleaned} stale directories, freeing {round(total_freed_mb, 2)} MB of disk space."
            }

        # ── 8. get_system_stats ──────────────────────────────
        elif tool_name == "get_system_stats":
            total_disk_mb, used_disk_mb, free_disk_mb = 0, 0, 0
            try:
                stat = shutil.disk_usage(DOWNLOAD_DIR if os.path.exists(DOWNLOAD_DIR) else ".")
                total_disk_mb = round(stat.total / (1024 * 1024), 1)
                used_disk_mb = round(stat.used / (1024 * 1024), 1)
                free_disk_mb = round(stat.free / (1024 * 1024), 1)
            except Exception:
                pass

            total_jobs = await db.count_jobs()
            queued_jobs = await db.count_jobs("queued")
            active_jobs = len(job_queue.running)

            return {
                "status": "success",
                "disk": {
                    "free_mb": free_disk_mb,
                    "used_mb": used_disk_mb,
                    "total_mb": total_disk_mb,
                },
                "queue": {
                    "active_running": active_jobs,
                    "waiting": queued_jobs,
                },
                "jobs_total": total_jobs,
            }

        # ── 9. get_user_settings ─────────────────────────────
        elif tool_name == "get_user_settings":
            archive_mode = await db.get_user_setting(user_id, "archive_mode")
            image_pdf = await db.get_user_setting(user_id, "image_pdf")
            video_thumbs = await db.get_user_setting(user_id, "video_thumbs")
            return {
                "status": "success",
                "settings": {
                    "archive_mode": archive_mode,
                    "image_pdf": image_pdf,
                    "video_thumbs": video_thumbs,
                }
            }

        # ── 10. update_user_setting ──────────────────────────
        elif tool_name == "update_user_setting":
            key = params.get("key")
            val = params.get("value")
            if key not in ["archive_mode", "image_pdf", "video_thumbs", "terabox_cookie"]:
                return {"status": "error", "message": f"Invalid setting key '{key}'. Must be archive_mode, image_pdf, video_thumbs, or terabox_cookie."}

            if key == "archive_mode":
                val = str(val).lower()
                if val not in ["extract", "archive", "ask"]:
                    return {"status": "error", "message": "archive_mode must be 'extract', 'archive', or 'ask'."}
            elif key in ["image_pdf", "video_thumbs"]:
                if isinstance(val, str):
                    val = val.lower() in ["true", "1", "yes", "on"]
                else:
                    val = bool(val)
            elif key == "terabox_cookie":
                val = str(val).strip()

            await db.set_user_setting(user_id, key, val)
            return {"status": "success", "message": f"Setting '{key}' successfully updated."}

        # ── 11. unzip_files ──────────────────────────────────
        elif tool_name == "unzip_files":
            if user_id:
                await db.set_user_setting(user_id, "archive_mode", "extract")
            msg = "✅ Automatic archive extraction (unzip) is active for your downloads."

            job_id = str(params.get("job_id", "")).strip()
            if not job_id and user_id:
                # Find latest job with an archive
                jobs = await db.list_jobs(user_id=user_id, limit=3)
                for j in jobs:
                    test_dir = os.path.join(DOWNLOAD_DIR, j["_id"])
                    if os.path.isdir(test_dir):
                        job_id = j["_id"]
                        break

            if job_id:
                job_dir = os.path.join(DOWNLOAD_DIR, job_id)
                if os.path.isdir(job_dir):
                    from megabot.processors.archives import safe_extract
                    extracted_count = 0
                    for root, _, files in os.walk(job_dir):
                        for f in files:
                            ext = os.path.splitext(f)[1].lower()
                            if ext in [".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2"]:
                                arc_path = os.path.join(root, f)
                                out = os.path.join(job_dir, "extracted")
                                try:
                                    safe_extract(arc_path, out)
                                    extracted_files = [
                                        os.path.join(dp, fn)
                                        for dp, _, fns in os.walk(out)
                                        for fn in fns
                                        if os.path.isfile(os.path.join(dp, fn)) and os.path.getsize(os.path.join(dp, fn)) > 0
                                    ]
                                    if extracted_files:
                                        try:
                                            os.remove(arc_path)
                                        except Exception:
                                            pass
                                        extracted_count += 1
                                    else:
                                        shutil.rmtree(out, ignore_errors=True)
                                except Exception as ee:
                                    log.warning("Tool unzip failed on %s: %s", arc_path, ee)
                                    shutil.rmtree(out, ignore_errors=True)
                    if extracted_count:
                        msg += f" Successfully unzipped {extracted_count} archive(s) in job {job_id}."
                    else:
                        msg += f" No archive files currently found in workspace for job {job_id}."

            return {"status": "success", "message": msg}

        # ── 12. clear_cache ──────────────────────────────────
        elif tool_name == "clear_cache":
            deleted = await db.clear_link_cache()
            return {"status": "success", "cleared_entries": deleted, "message": f"Cleared {deleted} cached link entries. All links can now be processed anew."}

        # ── 13. get_account_info ─────────────────────────────
        elif tool_name == "get_account_info":
            account = await db.get_mega_account(user_id)
            if not account:
                return {"status": "success", "logged_in": False, "message": "Using anonymous high-speed guest downloader."}
            email = account.get("email", "")
            masked = email[:3] + "***@" + email.split("@")[-1] if "@" in email else "user"
            return {"status": "success", "logged_in": True, "email_masked": masked}

        # ── 14. logout_mega_account ──────────────────────────
        elif tool_name == "logout_mega_account":
            await db.delete_mega_account(user_id)
            await db.delete_mega_session(user_id)
            return {"status": "success", "message": "Successfully logged out of custom MEGA account."}

        else:
            return {"status": "error", "message": f"Unknown tool: '{tool_name}'"}

    except Exception as e:
        log.exception("Tool execution error in %s", tool_name)
        return {"status": "error", "message": f"Internal tool execution error: {e}"}
