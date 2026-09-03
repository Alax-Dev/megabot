# Archive extraction — zip / rar / 7z / tar with zip-slip protection
import logging
import os
import tarfile
import zipfile

log = logging.getLogger(__name__)


class UnsafeArchiveError(Exception):
    pass


def _validate(member_name: str, dest_dir: str) -> str:
    """Refuse entries escaping dest_dir (zip-slip) or absolute paths."""
    target = os.path.realpath(os.path.join(dest_dir, member_name))
    if not target.startswith(os.path.realpath(dest_dir) + os.sep) \
            and target != os.path.realpath(dest_dir):
        raise UnsafeArchiveError(f"Unsafe path in archive: {member_name}")
    return target


def safe_extract(archive_path: str, dest_dir: str) -> str:
    """Extract any supported archive safely into dest_dir."""
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(archive_path)[1].lower()

    if ext == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            for info in zf.infolist():
                _validate(info.filename, dest_dir)
            zf.extractall(dest_dir)

    elif ext in (".tar", ".gz", ".tgz", ".bz2", ".xz"):
        with tarfile.open(archive_path) as tf:
            for member in tf.getmembers():
                _validate(member.name, dest_dir)
            tf.extractall(dest_dir)

    elif ext == ".rar":
        import shutil as _sh
        import subprocess

        def _has_output():
            for _dp, _dn, names in os.walk(dest_dir):
                if names:
                    return True
            return False

        # Best-effort extraction, same spirit as WinRAR opening a single
        # volume: files stored entirely inside ONE volume are readable even
        # without the other volumes, while the tool still exits with a fatal
        # code about the missing parts. So tolerate non-zero exits and keep
        # whatever made it to disk; only fail when nothing was recovered.
        attempts = []
        if _sh.which("7z"):
            attempts.append(["7z", "x", f"-o{dest_dir}", "-y", archive_path])
        unrar_tool = next((t for t in ("unrar", "unrar-free") if _sh.which(t)), None)
        if unrar_tool:
            attempts.append([unrar_tool, "x", "-y", "-o+", archive_path,
                             dest_dir + os.sep])
        for cmd in attempts:
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                pass  # partial recovery is fine — check what landed on disk
            if _has_output():
                break
        else:
            raise RuntimeError(
                "No extractor could read anything from this RAR — it may be "
                "a split volume whose content lives in another part, "
                "corrupted, or password-protected.")

    elif ext == ".7z":
        import py7zr
        with py7zr.SevenZipFile(archive_path) as sz:
            for name in sz.getnames():
                _validate(name, dest_dir)
            sz.extractall(dest_dir)

    else:
        raise ValueError(f"Unsupported archive format: {ext}")

    log.info("Extracted %s → %s", archive_path, dest_dir)
    return dest_dir


def safe_zip(file_paths: list[str], output_zip_path: str, dest_dir: str) -> str:
    """Safely create a zip archive containing file_paths inside dest_dir."""
    _validate(os.path.basename(output_zip_path), dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in file_paths:
            if os.path.isfile(p):
                # Ensure each file is inside dest_dir
                _validate(os.path.relpath(p, dest_dir), dest_dir)
                arcname = os.path.relpath(p, dest_dir)
                zf.write(p, arcname=arcname)
    log.info("Zipped %d files → %s", len(file_paths), output_zip_path)
    return output_zip_path