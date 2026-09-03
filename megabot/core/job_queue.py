# Async job queue — global concurrency limit, per-user FIFO, cancellation support
import asyncio
import logging
import os
import shutil
import time

from config import MAX_CONCURRENT_JOBS, DOWNLOAD_DIR

log = logging.getLogger(__name__)


class JobQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self.running: dict[str, asyncio.Task] = {}   # job_id → task
        self.app = None

    async def start(self, app):
        self.app = app
        await self._cleanup_stale()
        for i in range(MAX_CONCURRENT_JOBS):
            self.workers.append(asyncio.create_task(self._worker(i)))
        log.info("Job queue started with %s workers", MAX_CONCURRENT_JOBS)

    async def _cleanup_stale(self):
        """On startup, remove crash-leftover dirs. Dirs whose job is still
        awaiting the user's archive choice are kept (max 7 days)."""
        from megabot.core.database import db
        if not os.path.isdir(DOWNLOAD_DIR):
            return
        for name in os.listdir(DOWNLOAD_DIR):
            path = os.path.join(DOWNLOAD_DIR, name)
            try:
                job = await db.get_job(name)
                if job and job.get("status") == "awaiting_choice":
                    age_h = (time.time() - os.path.getmtime(path)) / 3600
                    if age_h < 24 * 7:
                        continue  # still waiting for the user's button press
            except Exception as e:
                log.debug("Database check during cleanup skipped: %s", e)
            shutil.rmtree(path, ignore_errors=True)
            log.info("cleaned stale download dir %s", name)

    async def stop(self):
        for t in self.workers:
            t.cancel()
        for t in self.running.values():
            t.cancel()

    async def submit(self, job: dict):
        await self.queue.put(job)

    def queue_position(self, job_id: str) -> int:
        """1-based position of a job in the waiting queue (0 = not waiting)."""
        pos = 1
        for item in list(self.queue._queue):  # inspect pending items only
            if item.get("_id") == job_id:
                return pos
            pos += 1
        return 0

    async def cancel_job(self, job_id: str) -> bool:
        task = self.running.get(job_id)
        if task:
            task.cancel()
            return True
        return False

    async def _worker(self, worker_id: int):
        while True:
            job = await self.queue.get()
            job_id = job.get("_id")
            try:
                # import here to avoid circular imports at module load
                from megabot.core.pipeline import run_job
                task = asyncio.current_task()
                self.running[job_id] = task
                await run_job(self.app, job)
            except asyncio.CancelledError:
                log.info("Job %s cancelled", job_id)
                from megabot.core.database import db
                await db.set_job_status(job_id, "cancelled")
            except Exception:
                log.exception("Job %s failed", job_id)
                from megabot.core.database import db
                await db.set_job_status(job_id, "failed", error="internal error")
                # try to tell the user
                try:
                    from megabot.ui import texts
                    await self.app.send_message(
                        job["chat_id"], texts.ERROR_GENERIC, disable_web_page_preview=True
                    )
                except Exception:
                    pass
            finally:
                self.running.pop(job_id, None)
                # clean the download folder — EXCEPT when the job is paused
                # waiting for the user's archive choice; the files must stay
                # on disk until callbacks.py resumes the job (and cleans up)
                from megabot.core.database import db
                fresh = await db.get_job(job_id)
                if not fresh or fresh.get("status") != "awaiting_choice":
                    shutil.rmtree(f"{DOWNLOAD_DIR}/{job_id}", ignore_errors=True)
                self.queue.task_done()


# ── Singleton ────────────────────────────────────────────────
job_queue = JobQueue()