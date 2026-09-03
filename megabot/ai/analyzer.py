# Privacy-Preserving File Format & Structure Analyzer
import os
import tarfile
import zipfile
from natsort import natsorted

from megabot.ai.security import is_forbidden_file, validate_sandbox_path
from megabot.processors.uploader import human_size

# File categorization by common extensions
CATEGORIES = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".gif", ".svg", ".ico", ".heic"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".ts", ".wmv", ".3gp"},
    "audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".alac"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst"},
    "document": {".pdf", ".epub", ".mobi", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt"},
    "text_data": {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".srt", ".vtt"},
    "code": {".py", ".js", ".ts", ".html", ".css", ".java", ".cpp", ".c", ".go", ".rs", ".sh"},
}


def categorize_extension(ext: str) -> str:
    ext = ext.lower()
    for category, extensions in CATEGORIES.items():
        if ext in extensions:
            return category
    return "binary_other"


def inspect_archive_members_safely(archive_path: str) -> list[dict]:
    """
    Safely inspect the internal filenames and member formats of an archive
    WITHOUT extracting or reading the file contents into memory.
    Guarantees privacy: only filenames and extensions are recorded.
    """
    ext = os.path.splitext(archive_path)[1].lower()
    members = []

    try:
        if ext == ".zip":
            with zipfile.ZipFile(archive_path) as zf:
                for info in zf.infolist()[:60]:
                    if not info.is_dir() and not is_forbidden_file(info.filename):
                        m_ext = os.path.splitext(info.filename)[1].lower()
                        members.append({
                            "name": os.path.basename(info.filename),
                            "extension": m_ext,
                            "category": categorize_extension(m_ext),
                            "size_human": human_size(info.file_size),
                        })
        elif ext in (".tar", ".gz", ".tgz", ".bz2", ".xz"):
            with tarfile.open(archive_path) as tf:
                count = 0
                for m in tf.getmembers():
                    if m.isfile() and not is_forbidden_file(m.name):
                        m_ext = os.path.splitext(m.name)[1].lower()
                        members.append({
                            "name": os.path.basename(m.name),
                            "extension": m_ext,
                            "category": categorize_extension(m_ext),
                            "size_human": human_size(m.size),
                        })
                        count += 1
                        if count >= 60:
                            break
        elif ext == ".7z":
            import py7zr
            with py7zr.SevenZipFile(archive_path) as sz:
                for name in sz.getnames()[:60]:
                    if not is_forbidden_file(name):
                        m_ext = os.path.splitext(name)[1].lower()
                        members.append({
                            "name": os.path.basename(name),
                            "extension": m_ext,
                            "category": categorize_extension(m_ext),
                        })
    except Exception:
        pass

    return members


def extract_safe_metadata(job_dir: str) -> dict:
    """
    Walks job_dir and returns safe structural metadata for the AI.
    
    PRIVACY GUARANTEE:
    - NO file bytes or contents are read or exposed.
    - NO image pixels, audio waves, or private document text are read.
    - Protected files (.env, credentials, etc.) are strictly scrubbed out.
    """
    files_meta = []
    category_counts = {}
    total_bytes = 0

    # Ensure job_dir is valid
    canonical_job_dir = os.path.realpath(job_dir)

    for root, _dirs, names in os.walk(canonical_job_dir):
        for name in natsorted(names):
            full_path = os.path.join(root, name)
            
            # Security verification
            try:
                safe_path = validate_sandbox_path(canonical_job_dir, full_path)
            except Exception:
                continue

            size = os.path.getsize(safe_path)
            total_bytes += size
            rel_path = os.path.relpath(safe_path, canonical_job_dir)
            ext = os.path.splitext(name)[1].lower()
            category = categorize_extension(ext)

            category_counts[category] = category_counts.get(category, 0) + 1

            meta = {
                "name": rel_path,
                "extension": ext or "none",
                "category": category,
                "size_human": human_size(size),
            }

            # If it is an archive, get safe table-of-contents without reading contents
            if category == "archive":
                inner_members = inspect_archive_members_safely(safe_path)
                if inner_members:
                    meta["archive_contents_sample"] = inner_members[:20]
                    meta["archive_total_entries"] = len(inner_members)

            files_meta.append(meta)

    return {
        "total_files": len(files_meta),
        "total_size": human_size(total_bytes),
        "category_breakdown": category_counts,
        "files": files_meta[:100],  # Cap metadata to 100 files for prompt efficiency
    }
