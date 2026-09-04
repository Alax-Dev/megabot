# AI Agent Tool Registry & Execution Engine
import asyncio
import logging
import os
import shutil
import time

from config import DOWNLOAD_DIR, OWNER_ID
from megabot.core.database import db
from megabot.core.job_queue import job_queue

log = logging.getLogger(__name__)

# Available tools exposed to the AI Agent
TOOL_DEFINITIONS = [
    {
        "name": "list_jobs",
        "description": "List active, queued, or recently finished jobs. Users see their own jobs; owner sees all.",
        "parameters": {
            "status": "Optional filter: 'all', 'queued', 'downloading', 'processing', 'uploading', 'done', 'failed', 'cancelled'. Default 'all'.",
            "limit": "Maximum number of jobs to return (default 5, max 10)."
        }
    },
    {
        "name": "cancel_job",
        "description": "Cancel a running or queued job by its job ID.",
        "parameters": {
            "job_id": "The 8-10 character job ID to cancel (required)."
        }
    },
    {
        "name": "delete_job_files",
        "description": "Delete downloaded files for a specific job ID from the server disk.",
        "parameters": {
            "job_id": "The job ID whose files should be deleted (required)."
        }
    },
    {
        "name": "clean_disk",
        "description": "Scan downloads directory and delete stale/orphaned folders to free up disk space.",
        "parameters": {}
    },
    {
        "name": "get_system_stats",
        "description": "Get current server disk usage, active workers, queue size, total jobs, and database stats.",
        "parameters": {}
    },
    {
        "name": "get_user_settings",
        "description": "View current user configuration (archive_mode, image_pdf, video_thumbs).",
        "parameters": {}
    },
    {
        "name": "update_user_setting",
        "description": "Change a user preference setting.",
        "parameters": {
            "key": "Setting name: 'archive_mode', 'image_pdf', or 'video_thumbs'.",
            "value": "New value. For archive_mode: 'ask', 'extract', or 'archive'. For image_pdf/video_thumbs: true or false."
        }
    },
    {
        "name": "clear_cache",
        "description": "Clear duplicate link cache so any previously processed MEGA link can be submitted again.",
        "parameters": {}
    },
    {
        "name": "get_account_info",
        "description": "Check if user has a custom MEGA account logged in.",
        "parameters": {}
    },
    {
        "name": "logout_mega_account",
        "description": "Log out user from their custom MEGA account and remove saved credentials.",
        "parameters": {}
    }
]


async def execute_tool(tool_name: str, params: dict, context: dict) -> dict:
    """
    Execute a tool safely using the provided context (user_id, is_owner).
    Returns a dictionary with execution results.
    """
    user_id = context.get("user_id")
    is_owner = context.get("is_owner", False)

    try:
        if tool_name == "list_jobs":
            status = params.get("status", "all")
            limit = min(int(params.get("limit", 5)), 10)
            target_user = None if is_owner else user_id
            jobs = await db.list_jobs(user_id=target_user, status=status, limit=limit)
            
            job_list = []
            for j in jobs:
                jid = j.get("_id")
                is_running = jid in job_queue.running
                job_list.append({
                    "job_id": jid,
                    "status": "running" if is_running else j.get("status"),
                    "urls": j.get("url") if isinstance(j.get("url"), list) else [j.get("url")],
                    "created_at": str(j.get("created_at")),
                    "files_sent": j.get("files_sent", 0),
                    "error": j.get("error"),
                })
            return {"status": "success", "count": len(job_list), "jobs": job_list}

        elif tool_name == "cancel_job":
            job_id = str(params.get("job_id", "")).strip()
            if not job_id:
                return {"status": "error", "message": "job_id is required"}

            job = await db.get_job(job_id)
            if not job:
                return {"status": "error", "message": f"Job {job_id} not found."}
            if not is_owner and job.get("user_id") != user_id:
                return {"status": "error", "message": "Permission denied: you can only cancel your own jobs."}

            cancelled = await job_queue.cancel_job(job_id)
            await db.set_job_status(job_id, "cancelled")
            
            # Clean directory if exists
            job_dir = os.path.join(DOWNLOAD_DIR, job_id)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir, ignore_errors=True)

            return {
                "status": "success",
                "message": f"Job {job_id} has been cancelled and temporary files removed.",
                "was_running": cancelled
            }

        elif tool_name == "delete_job_files":
            job_id = str(params.get("job_id", "")).strip()
            if not job_id:
                return {"status": "error", "message": "job_id is required"}

            job = await db.get_job(job_id)
            if job and not is_owner and job.get("user_id") != user_id:
                return {"status": "error", "message": "Permission denied: not your job files."}

            job_dir = os.path.join(DOWNLOAD_DIR, job_id)
            if not os.path.exists(job_dir):
                return {"status": "success", "message": f"No files found for job {job_id} on disk (already cleaned)."}

            # Calculate size before deleting
            size_mb = 0
            for root, _, files in os.walk(job_dir):
                for f in files:
                    try:
                        size_mb += os.path.getsize(os.path.join(root, f)) / (1024 * 1024)
                    except Exception:
                        pass

            shutil.rmtree(job_dir, ignore_errors=True)
            return {
                "status": "success",
                "message": f"Successfully deleted files for job {job_id}.",
                "freed_mb": round(size_mb, 2)
            }

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

                # Check if job is awaiting user choice
                job = await db.get_job(name)
                if job and job.get("status") == "awaiting_choice":
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
                "message": f"Cleaned {cleaned} stale directories, freeing {round(total_freed_mb, 2)} MB."
            }

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

        elif tool_name == "update_user_setting":
            key = params.get("key")
            val = params.get("value")
            if key not in ["archive_mode", "image_pdf", "video_thumbs"]:
                return {"status": "error", "message": f"Invalid setting key '{key}'. Must be archive_mode, image_pdf, or video_thumbs."}

            if key == "archive_mode":
                val = str(val).lower()
                if val not in ["ask", "extract", "archive"]:
                    return {"status": "error", "message": "archive_mode must be 'ask', 'extract', or 'archive'."}
            elif key in ["image_pdf", "video_thumbs"]:
                if isinstance(val, str):
                    val = val.lower() in ["true", "1", "yes", "on"]
                else:
                    val = bool(val)

            await db.set_user_setting(user_id, key, val)
            return {"status": "success", "message": f"Setting '{key}' successfully updated to {val}."}

        elif tool_name == "clear_cache":
            deleted = await db.clear_link_cache()
            return {"status": "success", "cleared_entries": deleted, "message": f"Cleared {deleted} cached link entries."}

        elif tool_name == "get_account_info":
            account = await db.get_mega_account(user_id)
            if not account:
                return {"status": "success", "logged_in": False, "message": "Using anonymous guest MEGA mode."}
            email = account.get("email", "")
            masked = email[:3] + "***@" + email.split("@")[-1] if "@" in email else "user"
            return {"status": "success", "logged_in": True, "email_masked": masked}

        elif tool_name == "logout_mega_account":
            await db.delete_mega_account(user_id)
            await db.delete_mega_session(user_id)
            return {"status": "success", "message": "Successfully logged out of MEGA and deleted saved session."}

        else:
            return {"status": "error", "message": f"Unknown tool: '{tool_name}'"}

    except Exception as e:
        log.exception("Tool execution error in %s", tool_name)
        return {"status": "error", "message": f"Internal tool execution error: {e}"}
