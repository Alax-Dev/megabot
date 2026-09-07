# MediaFire downloader — BaseDownloader implementation for MediaFire links
import json
import logging
import os
import re
import urllib.parse
from typing import Callable, Optional
import requests

from megabot.downloaders.base import BaseDownloader

log = logging.getLogger(__name__)

MEDIAFIRE_URL_RE = re.compile(
    r"https?://(?:www\.)?mediafire\.com/(?:file|download|folder|view)/[a-zA-Z0-9_.\-]+(?:/[a-zA-Z0-9_.\-]+)*/?",
    re.I
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def extract_mediafire_links(text: str) -> list[str]:
    """Pull all MediaFire links out of arbitrary text."""
    if not text:
        return []
    matches = MEDIAFIRE_URL_RE.findall(text)
    # Deduplicate while preserving order
    return list(dict.fromkeys(matches))


def is_mediafire_link(url: str) -> bool:
    """Return True if URL is a valid MediaFire link."""
    return bool(MEDIAFIRE_URL_RE.search(url or ""))


def mediafire_link_key(url: str) -> str:
    """Stable identifier for a MediaFire link (for the dedup cache)."""
    m = re.search(r"/(?:file|download|view|folder)/([a-zA-Z0-9_-]+)", url)
    return f"mf_{m.group(1)}" if m else f"mf_{url}"


class MediaFireDownloader(BaseDownloader):
    """
    Downloads files and folders from MediaFire.
    Extracts direct download links from MediaFire HTML and streams downloads.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def login(self) -> None:
        """MediaFire direct downloads are anonymous."""
        pass

    def probe(self, url: str) -> dict:
        """Inspect MediaFire URL to determine filename, filesize, and kind."""
        if "/folder/" in url:
            return self._probe_folder(url)
        return self._probe_file(url)

    def _probe_file(self, url: str) -> dict:
        info = self._resolve_file_info(url)
        return {
            "name": info["name"],
            "size": info["size"],
            "kind": "file",
            "direct_url": info.get("direct_url"),
        }

    def _probe_folder(self, url: str) -> dict:
        m = re.search(r"/folder/([a-zA-Z0-9_-]+)", url)
        folder_key = m.group(1) if m else ""
        folder_name = "MediaFire Folder"
        total_size = 0
        file_urls = []

        if folder_key:
            try:
                api_url = (
                    f"https://www.mediafire.com/api/1.4/folder/get_content.php?"
                    f"folder_key={folder_key}&content_type=files&response_format=json"
                )
                resp = self.session.get(api_url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    files_data = (
                        data.get("response", {})
                        .get("folder_content", {})
                        .get("files", [])
                    )
                    for f in files_data:
                        total_size += int(f.get("size", 0))
                        file_name = f.get("filename", "")
                        quickkey = f.get("quickkey", "")
                        if quickkey:
                            file_urls.append(f"https://www.mediafire.com/file/{quickkey}/{file_name}")
            except Exception as e:
                log.warning("MediaFire folder API query failed: %s", e)

        # Fallback to HTML if API did not return files
        if not file_urls:
            try:
                resp = self.session.get(url, timeout=15)
                html = resp.text
                title_match = re.search(r"<title>(.*?)(?: - MediaFire)?</title>", html, re.I)
                if title_match:
                    folder_name = title_match.group(1).strip()
                matches = re.findall(r'href=["\'](https?://(?:www\.)?mediafire\.com/file/[^"\']+)["\']', html)
                file_urls = list(dict.fromkeys(matches))
            except Exception as e:
                log.warning("MediaFire folder HTML probe error: %s", e)

        return {
            "name": folder_name,
            "size": total_size,
            "kind": "folder",
            "files": file_urls,
        }

    def _resolve_file_info(self, url: str) -> dict:
        """Fetch the MediaFire page and extract direct download link, name, and size."""
        resp = self.session.get(url, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"MediaFire page returned HTTP {resp.status_code}")

        html = resp.text

        # 1. Search for direct download link in HTML
        direct_url = None
        patterns = [
            r'id=["\']downloadButton["\']\s+href=["\']([^"\']+)["\']',
            r'aria-label=["\']Download file["\']\s+href=["\']([^"\']+)["\']',
            r'class=["\'][^"\']*popsok[^"\']*["\']\s+href=["\']([^"\']+)["\']',
            r'href=["\'](https?://download\d*\.mediafire\.com/[^"\']+)["\']',
            r'(https?://download\d*\.mediafire\.com/[^\s"\'<>]+)',
            r'(https?://[a-zA-Z0-9.\-_]*mediafire\.com/dynamicdownload\.php\?[^\s"\'<>]+)',
        ]
        for pat in patterns:
            match = re.search(pat, html, re.I)
            if match:
                direct_url = match.group(1)
                break

        if not direct_url:
            raise RuntimeError(
                "Could not find direct download link on MediaFire page. "
                "The file may have been deleted, blocked, or requires a password."
            )

        # 2. Extract Filename
        name = None
        # Try HTML elements
        name_patterns = [
            r'<div\s+class=["\']filename["\']>(.*?)</div>',
            r'<div\s+class=["\']dl-btn-label["\']\s+title=["\']([^"\']+)["\']',
            r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
            r'<span\s+class=["\']filename["\']>(.*?)</span>',
        ]
        for np in name_patterns:
            nm = re.search(np, html, re.I | re.S)
            if nm:
                raw_name = nm.group(1).strip()
                # Clean any html tags
                cleaned = re.sub(r"<[^>]+>", "", raw_name).strip()
                if cleaned and cleaned != "MediaFire":
                    name = cleaned
                    break

        if not name:
            # Fallback to URL path
            parsed = urllib.parse.urlparse(direct_url)
            name = urllib.parse.unquote(os.path.basename(parsed.path))
        if not name:
            name = "mediafire_file"

        # Sanitize filename
        name = re.sub(r'[\\/*?:"<>|]', "_", name).strip()

        # 3. Extract File Size
        size = 0
        try:
            # Try HEAD request on direct URL
            head_resp = self.session.head(direct_url, allow_redirects=True, timeout=10)
            if "content-length" in head_resp.headers:
                size = int(head_resp.headers["content-length"])
        except Exception:
            pass

        if not size:
            # Parse from HTML details
            size_match = re.search(r'\((\d+(?:\.\d+)?\s*(?:B|KB|MB|GB))\)', html, re.I)
            if size_match:
                size_str = size_match.group(1)
                size = self._parse_size(size_str)

        return {
            "name": name,
            "size": size,
            "direct_url": direct_url,
        }

    def _parse_size(self, size_str: str) -> int:
        """Convert '12.5 MB' into bytes."""
        m = re.match(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)", size_str.strip(), re.I)
        if not m:
            return 0
        num = float(m.group(1))
        unit = m.group(2).upper()
        multipliers = {"B": 1, "KB": 1024, "MB": 1024 * 1024, "GB": 1024 * 1024 * 1024}
        return int(num * multipliers.get(unit, 1))

    def download(self, url: str, dest_dir: str,
                 progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
        """Download file or folder from MediaFire into dest_dir."""
        os.makedirs(dest_dir, exist_ok=True)

        if "/folder/" in url:
            return self._download_folder(url, dest_dir, progress_cb)
        return self._download_file(url, dest_dir, progress_cb)

    def _download_file(self, url: str, dest_dir: str, progress_cb=None) -> str:
        info = self._resolve_file_info(url)
        direct_url = info["direct_url"]
        filename = info["name"]
        total_size = info["size"]

        target_path = os.path.join(dest_dir, filename)

        with self.session.get(direct_url, stream=True, timeout=60) as r:
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

        log.info("MediaFire download complete: %s (%d bytes)", target_path, done)
        return target_path

    def _download_folder(self, url: str, dest_dir: str, progress_cb=None) -> str:
        folder_info = self._probe_folder(url)
        files = folder_info.get("files", [])
        if not files:
            raise RuntimeError("No downloadable files found in MediaFire folder.")

        folder_name = folder_info.get("name", "MediaFire_Folder")
        folder_path = os.path.join(dest_dir, re.sub(r'[\\/*?:"<>|]', "_", folder_name))
        os.makedirs(folder_path, exist_ok=True)

        total_files = len(files)
        for idx, file_url in enumerate(files, 1):
            try:
                self._download_file(file_url, folder_path, progress_cb)
            except Exception as e:
                log.warning("Failed to download %s from MediaFire folder: %s", file_url, e)

        return folder_path
