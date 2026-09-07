# Unified Downloader Factory and Link Dispatcher
from typing import Optional

from megabot.downloaders.base import BaseDownloader
from megabot.downloaders.mega import MegaDownloader, extract_mega_links, link_key as mega_link_key
from megabot.downloaders.mediafire import (
    MediaFireDownloader,
    extract_mediafire_links,
    is_mediafire_link,
    mediafire_link_key,
)


def extract_supported_links(text: str) -> list[str]:
    """
    Extract all supported download links (MEGA & MediaFire) from text.
    Preserves order and deduplicates.
    """
    if not text:
        return []

    mega_links = extract_mega_links(text)
    mf_links = extract_mediafire_links(text)

    # Combine and deduplicate
    combined = []
    seen = set()
    for link in mega_links + mf_links:
        if link not in seen:
            seen.add(link)
            combined.append(link)

    return combined


def get_link_key(url: str) -> str:
    """Return a unique, stable cache identifier for any supported link."""
    if is_mediafire_link(url):
        return mediafire_link_key(url)
    return mega_link_key(url)


def is_supported_link(url: str) -> bool:
    """Check if a URL is handled by any supported downloader."""
    if not url:
        return False
    return is_mediafire_link(url) or "mega." in url.lower()


async def get_downloader(url: str, user_id: Optional[int] = None) -> BaseDownloader:
    """
    Instantiate and return the appropriate downloader instance for the URL.
    """
    if is_mediafire_link(url):
        return MediaFireDownloader()

    # Default to MEGA with user session credentials
    from megabot.core.database import db
    account = await db.get_mega_account(user_id) if user_id else None
    session = await db.get_mega_session(user_id) if user_id else None

    return MegaDownloader(
        email=account["email"] if account else None,
        password=account["password"] if account else None,
        saved_session=session,
    )
