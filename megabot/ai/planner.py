# AI Planner — uses OpenRouter to inspect file metadata and create execution plans
import json
import logging

from megabot.ai.client import call_openrouter_json

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the AI Dispatcher and Intelligent File Processor for MegaBot.
Your task is to analyze file metadata (names, formats, extensions, sizes, and structure) along with any user request, and return a safe, ordered execution plan.

IMPORTANT PRIVACY & SECURITY POLICIES:
1. You only see sanitized structural metadata (names, sizes, types). You do NOT see raw file contents.
2. You can only operate inside the bot's temporary job directory.
3. You must NEVER attempt to access system files or environment files (.env).
4. All actions you emit must come from the allowed list below.

ALLOWED ACTIONS:
1. {"action": "extract_archive", "file": "<relative_path_to_archive>"}
   - Extracts a zip, rar, 7z, or tar file inside the workspace.
2. {"action": "images_to_pdf", "output_name": "<name>.pdf", "files": ["img1.jpg", "img2.jpg"]}
   - Merges image files into an ordered PDF. If "files" is omitted, all images in the folder are merged.
3. {"action": "create_zip", "output_name": "<name>.zip", "files": ["file1", "file2"]}
   - Packages specified files into a single zip archive.
4. {"action": "filter_files", "keep_extensions": [".mp4", ".mkv"]} or {"action": "filter_files", "keep_files": ["f1", "f2"]}
   - Filters the candidate list of files to keep for final processing or upload.
5. {"action": "rename_file", "from": "<old_name>", "to": "<new_name>"}
   - Renames a file cleanly within the job directory.
6. {"action": "upload", "files": ["<file1>", "<file2>"]}
   - Specifies which files to deliver to the user on Telegram. If omitted, all resulting files will be uploaded.

OUTPUT FORMAT:
Respond with valid JSON only:
{
  "summary": "Brief 1-sentence explanation of what will be done for the user",
  "actions": [
    ... list of actions in the order they should be executed ...
  ]
}

DECISION HEURISTICS:
- If the user gave an explicit instruction (e.g., "convert to pdf", "extract only videos", "zip all files", "keep as archive"), STRICTLY prioritize fulfilling the user's intent!
- If the user gave NO explicit instruction (default mode):
  - ≥ 3 images and no video: action "images_to_pdf".
  - Lone archive: action "extract_archive" if it contains media/images/documents, or leave as archive if it contains programs/unknowns.
  - Video files: keep videos ready for stream upload.
  - Many mixed/loose files (>10 files): bundle them into a zip with "create_zip" for clean delivery.
  - Single file: upload as-is.
"""


async def plan_actions(metadata: dict, user_prompt: str = "") -> dict | None:
    """
    Query OpenRouter with metadata and user prompt to receive an execution plan.
    """
    user_instruction = user_prompt.strip() if user_prompt else "No specific instruction provided. Choose the best processing strategy."

    prompt_content = {
        "user_instruction": user_instruction,
        "files_metadata": metadata,
    }

    user_message = f"Please analyze these files and generate an execution plan:\n\n{json.dumps(prompt_content, indent=2)}"

    plan = await call_openrouter_json(SYSTEM_PROMPT, user_message)
    if not plan or not isinstance(plan, dict) or "actions" not in plan:
        log.warning("Invalid or empty plan received from AI: %s", plan)
        return None

    log.info("AI generated plan: %s (summary: %s)", len(plan.get("actions", [])), plan.get("summary"))
    return plan
