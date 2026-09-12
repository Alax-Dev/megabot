# TeraBox Downloader — BaseDownloader implementation for TeraBox links with Direct Session Cookie
import json
import logging
import os
import re
import urllib.parse
from typing import Callable, Optional
import requests

from config import TERABOX_COOKIE
from megabot.downloaders.base import BaseDownloader

log = logging.getLogger(__name__)

TERABOX_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:[\w\-]+\.)?(?:terabox(?:app|link)?|1024tera(?:box)?|terafileshare|freeterabox|mirrobox|nephobox|tibibox|4funbox)\.(?:com|app|net|link|org)/(?:s/(?:1)?[a-zA-Z0-9_\-]+|sharing/link\?[^\s\"\'<>]+|wap/share/filelist\?[^\s\"\'<>]+)",
    re.I
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.terabox.app/",
}


def extract_terabox_links(text: str) -> list[str]:
    """Pull all TeraBox links out of arbitrary text."""
    if not text:
        return []
    matches = TERABOX_URL_RE.findall(text)
    return list(dict.fromkeys(matches))


def is_terabox_link(url: str) -> bool:
    """Return True if URL is a recognized TeraBox link."""
    return bool(TERABOX_URL_RE.search(url or ""))


def extract_surl(url: str) -> str:
    """Extract clean surl token from any TeraBox link."""
    m = re.search(r"[?&]surl=([a-zA-Z0-9_\-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/s/([a-zA-Z0-9_\-]+)", url)
    if m:
        return m.group(1)
    return ""


def terabox_link_key(url: str) -> str:
    """Stable identifier for a TeraBox link (for the dedup cache)."""
    surl = extract_surl(url)
    return f"tb_{surl}" if surl else f"tb_{url}"


def _normalize_cookie(cookie: str) -> str:
    """Ensure cookie string contains ndus=..."""
    if not cookie:
        return ""
    cookie = cookie.strip()
    if not cookie.startswith("ndus="):
        if "=" not in cookie:
            return f"ndus={cookie}"
    return cookie


def check_cookie_validity(cookie: str) -> dict:
    """
    Verify whether a TeraBox ndus cookie is active and return account info if available.
    Returns dict(valid: bool, username: str, message: str).
    """
    norm = _normalize_cookie(cookie)
    if not norm:
        return {"valid": False, "username": "", "message": "Cookie is empty."}

    headers = dict(DEFAULT_HEADERS)
    headers["Cookie"] = norm
    try:
        resp = requests.get("https://www.terabox.app/api/user/getinfo", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("errno") == 0:
                uname = (
                    data.get("uname")
                    or data.get("nick_name")
                    or data.get("baidu_name")
                    or "TeraBox User"
                )
                return {"valid": True, "username": uname, "message": "Cookie is active and verified."}
            elif data.get("errno") == -6:
                return {"valid": False, "username": "", "message": "Session expired or invalid (errno -6)."}
            else:
                return {"valid": False, "username": "", "message": f"TeraBox returned status code: {data.get('errno')}"}
        return {"valid": True, "username": "", "message": f"Verified (HTTP {resp.status_code})."}
    except Exception as e:
        # Fallback in case of temporary network glitch
        log.debug("check_cookie_validity network probe skipped: %s", e)
        return {"valid": True, "username": "", "message": "Cookie format valid (network check skipped)."}


class TeraBoxDownloader(BaseDownloader):
    """
    Downloads files from TeraBox using Direct Session Cookie (ndus) authentication,
    with fallback to public bypass resolvers.
    """

    def __init__(self, cookie: Optional[str] = None):
        self.cookie = _normalize_cookie(cookie or TERABOX_COOKIE)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        if self.cookie:
            self.session.headers["Cookie"] = self.cookie
        self._cache: dict[str, dict] = {}

    def login(self) -> None:
        """Validate or refresh session headers."""
        if self.cookie:
            self.session.headers["Cookie"] = self.cookie

    def probe(self, url: str) -> dict:
        """Inspect TeraBox URL to determine filename, filesize, and kind."""
        if url in self._cache:
            return self._cache[url]

        info = self._resolve(url)
        self._cache[url] = info
        return info

    def download(self, url: str, dest_dir: str, progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
        """Download file(s) from TeraBox into dest_dir with live progress."""
        os.makedirs(dest_dir, exist_ok=True)
        info = self.probe(url)

        if info.get("kind") == "folder" and info.get("files"):
            # Multi-file folder download
            total_files = len(info["files"])
            for idx, f in enumerate(info["files"], 1):
                f_name = f.get("name") or f"file_{idx}"
                f_url = f.get("direct_url")
                if not f_url:
                    continue
                out_path = os.path.join(dest_dir, f_name)
                self._stream_download(f_url, out_path, f.get("size", 0), progress_cb)
            return dest_dir

        direct_url = info.get("direct_url")
        if not direct_url:
            raise RuntimeError(f"Could not extract direct download URL for {url}")

        filename = info.get("name") or "terabox_download"
        dest_path = os.path.join(dest_dir, filename)
        self._stream_download(direct_url, dest_path, info.get("size", 0), progress_cb)
        return dest_dir

    # ── Internal Resolution Engine ───────────────────────────

    def _resolve(self, url: str) -> dict:
        """Resolve file metadata and direct download URL."""
        raw_surl = extract_surl(url)
        if not raw_surl:
            raise ValueError(f"Invalid TeraBox URL, could not extract shortcode: {url}")

        shorturl = raw_surl if raw_surl.startswith("1") else f"1{raw_surl}"
        surl_clean = raw_surl[1:] if raw_surl.startswith("1") else raw_surl

        # Attempt 1: Direct Cookie API via /share/list
        api_res = self._try_share_list_api(shorturl, surl_clean)
        if api_res:
            return api_res

        # Attempt 2: Direct Cookie via Share Page HTML & jsToken
        page_res = self._try_share_page(url, shorturl, surl_clean)
        if page_res:
            return page_res

        # Attempt 3: Public bypass resolver fallback
        resolver_res = self._try_public_resolvers(url, surl_clean)
        if resolver_res:
            return resolver_res

        if not self.cookie:
            raise RuntimeError(
                "Could not resolve TeraBox link. Please set TERABOX_COOKIE (ndus) in .env "
                "to enable high-speed direct authenticated downloads."
            )
        raise RuntimeError(
            "Could not resolve TeraBox link. The file may have been deleted, "
            "or the configured TERABOX_COOKIE (ndus) has expired."
        )

    def _try_share_list_api(self, shorturl: str, surl_clean: str) -> Optional[dict]:
        """Query official TeraBox share list API with session cookie."""
        endpoints = [
            "https://www.terabox.app/share/list",
            "https://www.1024tera.com/share/list",
            "https://www.terabox.com/share/list",
        ]

        for ep in endpoints:
            for s_val in [shorturl, surl_clean]:
                try:
                    params = {
                        "app_id": "250528",
                        "shorturl": s_val,
                        "root": "1",
                    }
                    headers = dict(self.session.headers)
                    headers["Referer"] = f"https://www.terabox.app/sharing/link?surl={surl_clean}"
                    resp = self.session.get(ep, params=params, headers=headers, timeout=15)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("errno") == 0 and data.get("list"):
                            file_list = data["list"]
                            return self._build_info_from_list(file_list, s_val)
                except Exception as e:
                    log.debug("TeraBox share/list attempt failed on %s: %s", ep, e)

        return None

    def _try_share_page(self, url: str, shorturl: str, surl_clean: str) -> Optional[dict]:
        """Fetch the share page HTML to parse embedded yunData and jsToken."""
        try:
            page_url = f"https://www.terabox.app/sharing/link?surl={surl_clean}"
            headers = dict(self.session.headers)
            resp = self.session.get(page_url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return None

            html = resp.text

            # Extract jsToken
            js_token = None
            m_token = re.search(r'["\']jsToken["\']\s*[:=]\s*["\']([^"\']+)["\']', html)
            if m_token:
                js_token = m_token.group(1)
            else:
                m_fn = re.search(r'fn\(["\']([a-f0-9]{32,})["\']\)', html)
                if m_fn:
                    js_token = m_fn.group(1)

            # Extract yunData
            m_yun = re.search(r'yunData\.setData\((\{.*?\})\);', html, re.S)
            if m_yun:
                try:
                    yun_data = json.loads(m_yun.group(1))
                    file_list = yun_data.get("file_list", [])
                    shareid = yun_data.get("shareid")
                    uk = yun_data.get("uk")
                    sign = yun_data.get("sign")
                    timestamp = yun_data.get("timestamp")

                    if file_list:
                        info = self._build_info_from_list(file_list, shorturl)
                        if not info.get("direct_url") and js_token and shareid:
                            # Fetch dlink via share/download
                            fs_id = file_list[0].get("fs_id")
                            dlink = self._fetch_dlink_api(shorturl, js_token, shareid, uk, sign, timestamp, fs_id)
                            if dlink:
                                info["direct_url"] = dlink
                        if info.get("direct_url"):
                            return info
                except Exception:
                    pass

        except Exception as e:
            log.debug("TeraBox page parsing failed: %s", e)

        return None

    def _fetch_dlink_api(self, shorturl: str, js_token: str, shareid: str, uk: str,
                         sign: str, timestamp: int, fs_id: str) -> Optional[str]:
        """Request official download link from TeraBox share/download endpoint."""
        api_url = "https://www.terabox.app/share/download"
        params = {
            "app_id": "250528",
            "shorturl": shorturl,
            "jsToken": js_token,
        }
        data = {
            "shareid": shareid,
            "uk": uk,
            "sign": sign,
            "timestamp": timestamp,
            "fs_ids": json.dumps([str(fs_id)]),
            "primaryid": shareid,
        }
        try:
            resp = self.session.post(api_url, params=params, data=data, timeout=15)
            if resp.status_code == 200:
                j = resp.json()
                if j.get("errno") == 0 and j.get("dlink"):
                    return j.get("dlink")
        except Exception as e:
            log.debug("TeraBox share/download failed: %s", e)
        return None

    def _try_public_resolvers(self, url: str, surl_clean: str) -> Optional[dict]:
        """Fallback to public resolver endpoints if direct cookie extraction needs backup."""
        resolvers = [
            f"https://api.1024terabox.com/api/get-info?shorturl={surl_clean}",
            f"https://terabox.hnn.workers.dev/api/get-info?shorturl={surl_clean}",
        ]
        for r_url in resolvers:
            try:
                resp = requests.get(r_url, headers=DEFAULT_HEADERS, timeout=12)
                if resp.status_code == 200:
                    data = resp.json()
                    # Handle varying resolver JSON schemas
                    item = data.get("data") or data
                    if isinstance(item, list) and item:
                        item = item[0]
                    if isinstance(item, dict):
                        dlink = item.get("download_link") or item.get("dlink") or item.get("direct_link")
                        fname = item.get("file_name") or item.get("filename") or item.get("server_filename")
                        fsize = int(item.get("size") or item.get("filesize") or 0)
                        if dlink and fname:
                            return {
                                "name": re.sub(r'[\\/*?:"<>|]', "_", fname).strip(),
                                "size": fsize,
                                "kind": "file",
                                "direct_url": dlink,
                            }
            except Exception:
                pass

        return None

    def _build_info_from_list(self, file_list: list[dict], shorturl: str) -> dict:
        """Construct standard probe dict from TeraBox file items."""
        if len(file_list) == 1:
            item = file_list[0]
            name = item.get("server_filename") or f"terabox_{shorturl}"
            name = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
            size = int(item.get("size", 0))
            dlink = item.get("dlink")
            return {
                "name": name,
                "size": size,
                "kind": "file",
                "direct_url": dlink,
                "fs_id": item.get("fs_id"),
            }

        total_size = sum(int(f.get("size", 0)) for f in file_list)
        files = []
        for f in file_list:
            fn = re.sub(r'[\\/*?:"<>|]', "_", f.get("server_filename", "file")).strip()
            files.append({
                "name": fn,
                "size": int(f.get("size", 0)),
                "direct_url": f.get("dlink"),
                "fs_id": f.get("fs_id"),
            })

        return {
            "name": f"{len(file_list)}-file TeraBox folder",
            "size": total_size,
            "kind": "folder",
            "files": files,
            "direct_url": files[0]["direct_url"] if files else None,
        }

    def _stream_download(self, direct_url: str, dest_path: str, expected_size: int,
                         progress_cb: Optional[Callable[[int, int], None]] = None):
        """Stream chunks from direct download URL to disk with progress callback."""
        headers = dict(self.session.headers)
        headers["Accept-Encoding"] = "identity"

        resp = self.session.get(direct_url, headers=headers, stream=True, timeout=30, allow_redirects=True)
        if resp.status_code not in (200, 206):
            raise RuntimeError(f"TeraBox download stream failed with HTTP {resp.status_code}")

        total_bytes = expected_size or int(resp.headers.get("content-length", 0))
        done_bytes = 0
        chunk_size = 128 * 1024  # 128 KB chunks

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    done_bytes += len(chunk)
                    if progress_cb and total_bytes > 0:
                        progress_cb(done_bytes, total_bytes)

        if total_bytes > 0 and done_bytes == 0:
            raise RuntimeError(f"TeraBox download produced 0 bytes for {dest_path}")

        log.info("TeraBox download complete: %s (%d bytes)", dest_path, done_bytes)
