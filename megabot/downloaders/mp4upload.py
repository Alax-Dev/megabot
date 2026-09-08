# MP4Upload downloader — BaseDownloader implementation for mp4upload.com
import logging
import os
import re
import urllib.parse
from typing import Callable, Optional
import requests

from megabot.downloaders.base import BaseDownloader

log = logging.getLogger(__name__)

MP4UPLOAD_URL_RE = re.compile(
    r"https?://(?:www\.)?mp4upload\.com/(?:embed-)?([a-zA-Z0-9_-]+)(?:\.html)?",
    re.I
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.mp4upload.com/",
    "Origin": "https://www.mp4upload.com",
}


def extract_mp4upload_links(text: str) -> list[str]:
    """Extract all MP4Upload URLs from text."""
    if not text:
        return []
    matches = [m.group(0) for m in MP4UPLOAD_URL_RE.finditer(text)]
    return list(dict.fromkeys(matches))


def is_mp4upload_link(url: str) -> bool:
    """Return True if URL is a valid MP4Upload link."""
    return bool(MP4UPLOAD_URL_RE.search(url or ""))


def mp4upload_link_key(url: str) -> str:
    """Stable cache identifier for an MP4Upload link."""
    m = MP4UPLOAD_URL_RE.search(url or "")
    file_id = m.group(1) if m else url
    return f"mp4u_{file_id}"


def unpack_dean_edwards(packed_js: str) -> str:
    """Pure Python unpacker for Dean Edwards p,a,c,k,e,d packed javascript."""
    m = re.search(
        r"eval\(function\(p,a,c,k,e,[rd]\).*?\}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)",
        packed_js,
        re.DOTALL
    )
    if not m:
        return packed_js

    payload, radix_str, count_str, symtab_str = m.groups()
    radix = int(radix_str)
    symtab = symtab_str.split('|')

    digits = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def unbase(val_str: str, r: int) -> int:
        res = 0
        for ch in val_str:
            if ch in digits:
                res = res * r + digits.index(ch)
        return res

    def replace_token(match):
        token = match.group(0)
        try:
            idx = unbase(token, radix)
            if idx < len(symtab) and symtab[idx]:
                return symtab[idx]
        except Exception:
            pass
        return token

    return re.sub(r"\b[0-9a-zA-Z]+\b", replace_token, payload)


class MP4UploadDownloader(BaseDownloader):
    """
    Downloads videos from mp4upload.com.
    Resolves embed player streams or form download actions and streams the video.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def login(self) -> None:
        """MP4Upload downloads are anonymous."""
        pass

    def probe(self, url: str) -> dict:
        """Inspect MP4Upload link to resolve direct video URL, filename, and size."""
        info = self._resolve_video_info(url)
        return {
            "name": info["name"],
            "size": info["size"],
            "kind": "file",
            "direct_url": info["direct_url"],
        }

    def _resolve_video_info(self, url: str) -> dict:
        m = MP4UPLOAD_URL_RE.search(url)
        if not m:
            raise RuntimeError(f"Invalid MP4Upload URL: {url}")
        file_id = m.group(1)

        direct_url = None
        filename = None
        filesize = 0

        # Method 1: Try embed page player extraction
        embed_url = f"https://www.mp4upload.com/embed-{file_id}.html"
        try:
            resp = self.session.get(embed_url, timeout=20)
            if resp.status_code == 200:
                html = resp.text

                # Look for unpacked or packed javascript
                unpacked = unpack_dean_edwards(html)
                src_patterns = [
                    r'player\.src\(\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
                    r'src:\s*["\'](https?://[^"\']+\.mp4[^"\']*)["\']',
                    r'<video[^>]+src=["\'](https?://[^"\']+)["\']',
                    r'["\'](https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)["\']',
                ]
                for sp in src_patterns:
                    sm = re.search(sp, unpacked, re.I)
                    if sm:
                        direct_url = sm.group(1)
                        break

                # Extract title
                title_match = re.search(r'<title>(.*?)(?: - MP4Upload)?</title>', html, re.I)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    if raw_title and raw_title.lower() != "mp4upload":
                        filename = raw_title
        except Exception as e:
            log.debug("MP4Upload embed extraction attempt failed: %s", e)

        # Method 2: Fallback to web form POST
        if not direct_url:
            try:
                page_url = f"https://www.mp4upload.com/{file_id}"
                init_resp = self.session.get(page_url, timeout=20)
                if init_resp.status_code == 200:
                    init_html = init_resp.text
                    inputs = dict(re.findall(r'<input\s+type=["\']hidden["\']\s+name=["\']([A-Za-z_]+)["\']\s+value=["\'](.*?)["\']', init_html, re.I))

                    if "fname" in inputs and inputs["fname"]:
                        filename = inputs["fname"]

                    # Step 1 post
                    post_data_1 = {
                        "op": inputs.get("op", "download2"),
                        "usr_login": inputs.get("usr_login", ""),
                        "id": inputs.get("id", file_id),
                        "fname": inputs.get("fname", ""),
                        "referer": inputs.get("referer", page_url),
                        "method_free": "Free Download",
                    }
                    step1_resp = self.session.post(page_url, data=post_data_1, timeout=20)
                    if step1_resp.status_code == 200:
                        step1_html = step1_resp.text
                        inputs2 = dict(re.findall(r'<input\s+type=["\']hidden["\']\s+name=["\']([A-Za-z_]+)["\']\s+value=["\'](.*?)["\']', step1_html, re.I))
                        post_data_2 = {
                            "op": inputs2.get("op", "download3"),
                            "id": inputs2.get("id", file_id),
                            "rand": inputs2.get("rand", ""),
                            "referer": page_url,
                            "method_free": "Free Download",
                            "method_premium": "",
                        }
                        # Look for form action
                        action_match = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', step1_html, re.I)
                        action_url = action_match.group(1) if action_match else "https://www.mp4upload.com/F1"
                        if not action_url.startswith("http"):
                            action_url = urllib.parse.urljoin("https://www.mp4upload.com/", action_url)

                        dl_resp = self.session.post(action_url, data=post_data_2, allow_redirects=False, timeout=20)
                        if "Location" in dl_resp.headers:
                            direct_url = dl_resp.headers["Location"]
            except Exception as e:
                log.debug("MP4Upload form extraction fallback failed: %s", e)

        if not direct_url:
            raise RuntimeError(
                f"Could not resolve direct video link from MP4Upload for {url}. "
                "The file may have expired, been deleted, or requires authorization."
            )

        # Sanitize filename
        if not filename:
            parsed = urllib.parse.urlparse(direct_url)
            filename = urllib.parse.unquote(os.path.basename(parsed.path))
        if not filename or filename == "video.mp4":
            filename = f"mp4upload_{file_id}.mp4"
        if not filename.lower().endswith(".mp4"):
            filename += ".mp4"

        filename = re.sub(r'[\\/*?:"<>|]', "_", filename).strip()

        # Query file size via HEAD request
        try:
            head_headers = DEFAULT_HEADERS.copy()
            head_headers["Referer"] = embed_url
            head_resp = self.session.head(direct_url, headers=head_headers, allow_redirects=True, timeout=10)
            if "content-length" in head_resp.headers:
                filesize = int(head_resp.headers["content-length"])
        except Exception:
            pass

        return {
            "name": filename,
            "size": filesize,
            "direct_url": direct_url,
            "embed_url": embed_url,
        }

    def download(self, url: str, dest_dir: str,
                 progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
        """Stream MP4Upload video into dest_dir with progress tracking."""
        os.makedirs(dest_dir, exist_ok=True)
        info = self._resolve_video_info(url)
        direct_url = info["direct_url"]
        filename = info["name"]
        total_size = info["size"]

        target_path = os.path.join(dest_dir, filename)

        req_headers = DEFAULT_HEADERS.copy()
        req_headers["Referer"] = info.get("embed_url", "https://www.mp4upload.com/")

        with self.session.get(direct_url, headers=req_headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            if not total_size and "content-length" in r.headers:
                try:
                    total_size = int(r.headers["content-length"])
                except Exception:
                    pass

            done = 0
            with open(target_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb and total_size:
                            progress_cb(done, total_size)

        log.info("MP4Upload download complete: %s (%d bytes)", target_path, done)
        return target_path
