# Security and Sandboxing Layer for AI Operations
import fnmatch
import os
import re

# Protected patterns: files matching these are strictly forbidden from being
# read, exposed in metadata, modified, or uploaded by any AI or automated tool.
FORBIDDEN_PATTERNS = [
    ".env*",
    "*.env*",
    "*.session*",
    "*.session-journal*",
    "*.key",
    "*.pem",
    "*.db",
    "*.sqlite*",
    "megabot.log*",
    "config.py",
    "*token*",
    "*secret*",
    "*credential*",
    "*password*",
    ".git*",
    "__pycache__*",
]


class SecurityViolation(Exception):
    """Raised when an operation attempts to breach directory boundaries or access protected files."""
    pass


def is_forbidden_file(path_or_name: str) -> bool:
    """Check if the given filename or path matches any sensitive/secret file pattern."""
    base = os.path.basename(path_or_name).strip().lower()
    base_no_dot = base.lstrip(".")
    for pat in FORBIDDEN_PATTERNS:
        pat_l = pat.lower()
        if fnmatch.fnmatch(base, pat_l) or fnmatch.fnmatch(base_no_dot, pat_l.lstrip(".")):
            return True
    return False


def validate_sandbox_path(base_dir: str, target_path: str) -> str:
    """
    Validate that target_path strictly resolves within base_dir (directory jail).
    Also ensures the target does not point to a forbidden/secret file.
    
    Returns the resolved, canonical absolute path if safe.
    Raises SecurityViolation if any boundary is crossed.
    """
    canonical_base = os.path.realpath(base_dir)
    canonical_target = os.path.realpath(target_path)

    # 1. Directory traversal / jail check
    try:
        common = os.path.commonpath([canonical_base, canonical_target])
    except ValueError:
        raise SecurityViolation(f"Cross-drive or invalid path: {target_path}")

    if common != canonical_base:
        raise SecurityViolation(
            f"Directory traversal detected: path '{target_path}' escapes sandbox '{base_dir}'"
        )

    # 2. Secret file check
    if is_forbidden_file(canonical_target):
        raise SecurityViolation(
            f"Access denied to protected file: '{os.path.basename(canonical_target)}'"
        )

    return canonical_target


def sanitize_filename(filename: str, default: str = "output") -> str:
    """
    Sanitize a filename suggested by user or AI so it cannot traverse directories
    or contain invalid characters.
    """
    if is_forbidden_file(filename):
        return default

    # Strip any directory path components
    base = os.path.basename(filename).strip()
    
    # Remove dangerous characters
    base = re.sub(r'[\\/*?:"<>|]', "_", base)
    
    # Strip leading dots (prevent hidden files / relative dots)
    base = base.lstrip(".")
    
    if not base or is_forbidden_file(base):
        base = default
        
    return base

