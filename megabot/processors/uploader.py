# Telegram uploader — sequential sends with live progress on the status message
import asyncio
import logging
import os
import subprocess
import time

from config import PROGRESS_TEMPLATE, BAR_LENGTH, BAR_FULL, BAR_EMPTY

log = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".ts", ".wmv"}


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def make_progress_bar(percent: float) -> str:
    filled = int(BAR_LENGTH * percent / 100)
    return BAR_FULL * filled + BAR_EMPTY * (BAR_LENGTH - filled)


def video_thumbnail(video_path: str) -> str | None:
    """Grab one frame with ffmpeg as a JPEG thumbnail. None on failure."""
    thumb = video_path + ".thumb.jpg"
    try:
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-ss", "00:00:02", "-vframes", "1",
             "-vf", "scale=480:-2", "-y", thumb],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
        return thumb if os.path.exists(thumb) and os.path.getsize(thumb) else None
    except Exception as e:
        log.debug("thumbnail failed for %s: %s", video_path, e)
        return None


class UploadProgress:
    """Sends files one by one, editing the job's status message with progress."""

    def __init__(self, app, job: dict, files: list[str]):
        self.app = app
        self.job = job
        self.files = files
        self._last_edit = 0.0
        self._start = 0.0
        self._loop = None

    async def _edit(self, text: str):
        try:
            await self.app.edit_message_text(
                self.job["chat_id"], self.job["message_id"], text,
                disable_web_page_preview=True,
            )
        except Exception:
            pass  # identical message / edit flood — non-fatal

    def _progress_cb(self, current: int, total: int):
        # pyrogram invokes this from an executor thread — there is no event
        # loop there, so schedule the status edit on the bot's loop that we
        # captured in send(). Any failure must stay silent: raising here
        # corrupts the running upload itself.
        try:
            now = time.time()
            if now - self._last_edit < 3.0 or self._loop is None:
                return
            self._last_edit = now
            percent = current * 100 / total if total else 0
            elapsed = max(now - self._start, 0.001)
            speed = current / elapsed
            eta = (total - current) / speed if speed else 0
            text = PROGRESS_TEMPLATE.format(
                bar=make_progress_bar(percent),
                percent=int(percent),
                name=self._current_name,
                speed=f"{human_size(speed)}/s",
                eta=f"{int(eta // 60)}m {int(eta % 60)}s",
                current=human_size(current),
                total=human_size(total),
            )
            asyncio.run_coroutine_threadsafe(self._edit(text), self._loop)
        except Exception:
            pass

    async def send(self, path: str, thumbs_enabled: bool = True) -> bool:
        """Upload one file. Returns True on success."""
        if not os.path.exists(path):
            return False

        self._loop = asyncio.get_running_loop()   # capture bot's loop for the cb
        self._current_name = os.path.basename(path)
        self._start = time.time()
        self._last_edit = 0.0
        size = os.path.getsize(path)
        ext = os.path.splitext(path)[1].lower()
        caption = f"📁 <b>{os.path.basename(path)}</b> ({human_size(size)})"

        try:
            if ext in VIDEO_EXTS:
                thumb = video_thumbnail(path) if thumbs_enabled else None
                await self.app.send_video(
                    self.job["chat_id"], path,
                    caption=caption, supports_streaming=True,
                    thumb=thumb, progress=self._progress_cb,
                )
                if thumb:
                    os.remove(thumb)
            elif ext == ".pdf":
                await self.app.send_document(
                    self.job["chat_id"], path, caption=caption,
                    progress=self._progress_cb,
                )
            else:
                await self.app.send_document(
                    self.job["chat_id"], path, caption=caption,
                    progress=self._progress_cb,
                )
            return True
        except Exception as e:
            log.error("upload failed for %s: %s", path, e)
            await self._edit(f"⚠️ Failed to upload <b>{os.path.basename(path)}</b>\n<code>{e}</code>")
            return False