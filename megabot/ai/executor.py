# AI Plan Executor — executes actions securely inside the sandboxed job directory
import asyncio
import logging
import os
import shutil
from natsort import natsorted

from megabot.ai.analyzer import CATEGORIES, categorize_extension
from megabot.ai.security import sanitize_filename, validate_sandbox_path, SecurityViolation
from megabot.processors.archives import safe_extract, safe_zip
from megabot.processors.images2pdf import images_to_pdf
from megabot.ui.keyboards import cancel_kb

log = logging.getLogger(__name__)


def _list_all_files(base_dir: str) -> list[str]:
    """Return all safe files currently under base_dir."""
    found = []
    canonical = os.path.realpath(base_dir)
    for root, _dirs, names in os.walk(canonical):
        for n in names:
            full = os.path.join(root, n)
            try:
                safe = validate_sandbox_path(canonical, full)
                found.append(safe)
            except Exception:
                continue
    return natsorted(found, key=lambda p: os.path.basename(p).lower())


async def execute_plan(app, job: dict, dest_dir: str, plan: dict,
                       edit_status_fn) -> list[str]:
    """
    Executes the actions specified in plan within dest_dir.
    Guarantees that all paths stay within dest_dir and no protected files are accessed.
    Returns the list of final file paths to upload.
    """
    job_id = job["_id"]
    actions = plan.get("actions", [])
    summary = plan.get("summary", "")
    canonical_dest = os.path.realpath(dest_dir)

    if summary:
        try:
            await edit_status_fn(
                app, job,
                f"<blockquote>🤖 <b>AI Plan</b>\n💡 {summary}</blockquote>",
                cancel_kb(job_id)
            )
            await asyncio.sleep(1.0)
        except Exception:
            pass

    current_files = _list_all_files(canonical_dest)
    explicit_uploads = None

    for idx, act in enumerate(actions, 1):
        if not isinstance(act, dict):
            continue

        action_type = act.get("action")
        log.info("Executing AI action [%d/%d]: %s", idx, len(actions), action_type)

        try:
            if action_type == "extract_archive":
                target_file = act.get("file")
                archive_path = None
                if target_file:
                    candidate = os.path.join(canonical_dest, target_file)
                    if os.path.isfile(candidate):
                        archive_path = validate_sandbox_path(canonical_dest, candidate)

                if not archive_path:
                    # Look for first available archive in current files
                    for f in current_files:
                        if categorize_extension(os.path.splitext(f)[1]) == "archive":
                            archive_path = f
                            break

                if archive_path and os.path.isfile(archive_path):
                    out_dir = os.path.join(canonical_dest, "extracted")
                    os.makedirs(out_dir, exist_ok=True)
                    await edit_status_fn(
                        app, job,
                        f"<blockquote>📂 <b>AI Action</b>\nDecompressing <b>{os.path.basename(archive_path)}</b>…</blockquote>",
                        cancel_kb(job_id)
                    )
                    await asyncio.to_thread(safe_extract, archive_path, out_dir)
                    # Refresh file list
                    current_files = _list_all_files(canonical_dest)

            elif action_type == "images_to_pdf":
                out_name = sanitize_filename(act.get("output_name", "document.pdf"), "document.pdf")
                if not out_name.lower().endswith(".pdf"):
                    out_name += ".pdf"
                pdf_path = validate_sandbox_path(canonical_dest, os.path.join(canonical_dest, out_name))

                # Collect image files
                target_images = []
                requested_images = act.get("files", [])
                if requested_images and isinstance(requested_images, list):
                    for rf in requested_images:
                        candidate = os.path.join(canonical_dest, rf)
                        if os.path.isfile(candidate):
                            target_images.append(validate_sandbox_path(canonical_dest, candidate))

                if not target_images:
                    target_images = [
                        f for f in current_files
                        if categorize_extension(os.path.splitext(f)[1]) == "image"
                    ]

                if target_images:
                    await edit_status_fn(
                        app, job,
                        f"<blockquote>🖼️ <b>AI Action</b>\nCreating <b>{out_name}</b> from {len(target_images)} images…</blockquote>",
                        cancel_kb(job_id)
                    )
                    await asyncio.to_thread(images_to_pdf, target_images, pdf_path)
                    current_files = _list_all_files(canonical_dest)

            elif action_type == "create_zip":
                out_name = sanitize_filename(act.get("output_name", "bundle.zip"), "bundle.zip")
                if not out_name.lower().endswith(".zip"):
                    out_name += ".zip"
                zip_path = validate_sandbox_path(canonical_dest, os.path.join(canonical_dest, out_name))

                # Files to zip
                zip_targets = []
                req_files = act.get("files", [])
                if req_files and isinstance(req_files, list):
                    for rf in req_files:
                        candidate = os.path.join(canonical_dest, rf)
                        if os.path.isfile(candidate):
                            zip_targets.append(validate_sandbox_path(canonical_dest, candidate))

                if not zip_targets:
                    zip_targets = [f for f in current_files if f != zip_path]

                if zip_targets:
                    await edit_status_fn(
                        app, job,
                        f"<blockquote>📦 <b>AI Action</b>\nCreating <b>{out_name}</b> with {len(zip_targets)} items…</blockquote>",
                        cancel_kb(job_id)
                    )
                    await asyncio.to_thread(safe_zip, zip_targets, zip_path, canonical_dest)
                    current_files = _list_all_files(canonical_dest)

            elif action_type == "rename_file":
                src_name = act.get("from")
                dst_raw = act.get("to", "")
                if "/" in dst_raw or "\\" in dst_raw or ".." in dst_raw:
                    log.warning("Rejected directory traversal in rename: %s", dst_raw)
                    continue
                dst_name = sanitize_filename(dst_raw, "")
                if src_name and dst_name:
                    src_path = validate_sandbox_path(canonical_dest, os.path.join(canonical_dest, src_name))
                    dst_path = validate_sandbox_path(canonical_dest, os.path.join(canonical_dest, dst_name))
                    if os.path.exists(src_path) and not os.path.exists(dst_path):
                        os.rename(src_path, dst_path)
                        current_files = _list_all_files(canonical_dest)

            elif action_type == "filter_files":
                keep_exts = set(act.get("keep_extensions", []))
                keep_names = set(act.get("keep_files", []))
                filtered = []
                for f in current_files:
                    ext = os.path.splitext(f)[1].lower()
                    base = os.path.basename(f)
                    if (keep_exts and ext in keep_exts) or (keep_names and base in keep_names):
                        filtered.append(f)
                if filtered:
                    current_files = filtered

            elif action_type == "upload":
                req_uploads = act.get("files", [])
                if req_uploads and isinstance(req_uploads, list):
                    explicit_uploads = []
                    for rf in req_uploads:
                        candidate = os.path.join(canonical_dest, rf)
                        if os.path.isfile(candidate):
                            explicit_uploads.append(validate_sandbox_path(canonical_dest, candidate))

        except SecurityViolation as sv:
            log.error("AI action blocked by security jail: %s", sv)
        except Exception as e:
            log.warning("AI action %s failed: %s", action_type, e)

    final_files = explicit_uploads if explicit_uploads else current_files
    # Deduplicate and sort
    seen = set()
    result = []
    for f in final_files:
        if f not in seen and os.path.isfile(f):
            seen.add(f)
            result.append(f)

    return result
