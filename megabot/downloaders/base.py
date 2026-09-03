# Downloader interface — add new hosts by subclassing BaseDownloader
from abc import ABC, abstractmethod
from typing import Callable, Optional


class BaseDownloader(ABC):
    """Every downloader must be able to probe a URL (name/size/kind)
    and download it to a destination directory with a progress callback."""

    @abstractmethod
    def login(self) -> None:
        """Authenticate with the host (no-op for anonymous hosts)."""

    @abstractmethod
    def probe(self, url: str) -> dict:
        """Return {"name": str, "size": int, "kind": "file"|"folder"}."""

    @abstractmethod
    def download(self, url: str, dest_dir: str,
                 progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
        """Download url into dest_dir; return the path of what was downloaded."""