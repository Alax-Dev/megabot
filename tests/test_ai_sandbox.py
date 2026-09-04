# Unit & security boundary tests for MegaBot AI
import os
import shutil
import tempfile
import unittest

from megabot.ai.analyzer import extract_safe_metadata
from megabot.ai.security import (
    SecurityViolation,
    is_forbidden_file,
    sanitize_filename,
    validate_sandbox_path,
)
from megabot.processors.archives import safe_zip


class TestAISecurityAndPrivacy(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.job_dir = os.path.join(self.temp_dir, "job_test_123")
        os.makedirs(self.job_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sandbox_jail_blocks_parent_escape(self):
        """AI cannot access parent directory or system directories."""
        parent_file = os.path.join(self.temp_dir, "outside.txt")
        with open(parent_file, "w") as f:
            f.write("sensitive outside data")

        # Try to access ../outside.txt from within job_dir
        with self.assertRaises(SecurityViolation):
            validate_sandbox_path(self.job_dir, parent_file)

        with self.assertRaises(SecurityViolation):
            validate_sandbox_path(self.job_dir, "/etc/passwd")

        with self.assertRaises(SecurityViolation):
            validate_sandbox_path(self.job_dir, os.path.join(self.job_dir, "../../etc/passwd"))

    def test_secret_blacklist_blocks_env(self):
        """Forbidden secret files (.env, session, etc.) are blocked."""
        self.assertTrue(is_forbidden_file(".env"))
        self.assertTrue(is_forbidden_file(".env.production"))
        self.assertTrue(is_forbidden_file("megabot.session"))
        self.assertTrue(is_forbidden_file("config.py"))
        self.assertTrue(is_forbidden_file("bot_token.key"))
        self.assertFalse(is_forbidden_file("normal_video.mp4"))
        self.assertFalse(is_forbidden_file("photo.jpg"))

        # Even if a file named .env is created inside the sandbox, validate_sandbox_path must reject it
        fake_env = os.path.join(self.job_dir, ".env")
        with open(fake_env, "w") as f:
            f.write("SECRET_KEY=12345")

        with self.assertRaises(SecurityViolation):
            validate_sandbox_path(self.job_dir, fake_env)

    def test_privacy_metadata_analyzer_never_exposes_file_contents(self):
        """Metadata analyzer returns only structural stats, excluding secret files and content bytes."""
        # Create normal files
        img_path = os.path.join(self.job_dir, "sample.jpg")
        with open(img_path, "wb") as f:
            f.write(b"\xFF\xD8\xFF" + b"some private image bytes" * 50)

        txt_path = os.path.join(self.job_dir, "notes.txt")
        with open(txt_path, "w") as f:
            f.write("This is highly private confidential diary entry!")

        # Create forbidden file in same directory
        env_path = os.path.join(self.job_dir, ".env")
        with open(env_path, "w") as f:
            f.write("SUPER_SECRET_TOKEN=xyz")

        meta = extract_safe_metadata(self.job_dir)

        # 1. Total files should be 2 (sample.jpg and notes.txt); .env must be strictly excluded!
        self.assertEqual(meta["total_files"], 2)

        filenames = [f["name"] for f in meta["files"]]
        self.assertIn("sample.jpg", filenames)
        self.assertIn("notes.txt", filenames)
        self.assertNotIn(".env", filenames)

        # 2. Guarantee no file contents or private text in the metadata
        for f in meta["files"]:
            self.assertNotIn("content", f)
            self.assertNotIn("raw", f)
            self.assertNotIn("text", f)
            self.assertNotIn("diary", str(f))
            self.assertNotIn("confidential", str(f))

    def test_safe_filename_sanitizer(self):
        """Sanitizer cleans directory traversal attempts."""
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename(".env"), "output")
        self.assertEqual(sanitize_filename("clean_name.pdf"), "clean_name.pdf")

    def test_safe_zip_creation(self):
        """Zipping files safely packages files within the sandbox."""
        file1 = os.path.join(self.job_dir, "file1.txt")
        file2 = os.path.join(self.job_dir, "file2.txt")
        with open(file1, "w") as f:
            f.write("one")
        with open(file2, "w") as f:
            f.write("two")

        out_zip = os.path.join(self.job_dir, "test.zip")
        res = safe_zip([file1, file2], out_zip, self.job_dir)
        self.assertTrue(os.path.exists(res))
        self.assertTrue(os.path.getsize(res) > 0)

    def test_executor_blocks_malicious_actions(self):
        """Executor ignores or blocks malicious actions attempting to escape or read secrets."""
        import asyncio
        from megabot.ai.executor import execute_plan

        # Create sample files
        f1 = os.path.join(self.job_dir, "vid.mp4")
        with open(f1, "w") as f:
            f.write("video content")

        async def mock_edit(app, job, text, kb=None):
            pass

        job = {"_id": "test_job_1", "chat_id": 123, "message_id": 456}

        # Plan attempting path traversal and secrets
        malicious_plan = {
            "summary": "Trying to breach boundaries",
            "actions": [
                {"action": "extract_archive", "file": "../../etc/shadow"},
                {"action": "rename_file", "from": "vid.mp4", "to": "../escaped.mp4"},
                {"action": "rename_file", "from": "vid.mp4", "to": ".env"},
            ]
        }

        # Run executor
        res = asyncio.run(execute_plan(None, job, self.job_dir, malicious_plan, mock_edit))
        
        # Verify that escaped files do not exist and sandbox remains clean
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir, "escaped.mp4")))
        self.assertFalse(os.path.exists(os.path.join(self.job_dir, ".env")))
        self.assertIn(f1, res)

    def test_executor_executes_delete_file_safely(self):
        """Executor safely deletes target files inside the sandbox and prevents traversal."""
        import asyncio
        from megabot.ai.executor import execute_plan

        f1 = os.path.join(self.job_dir, "keep.mp4")
        f2 = os.path.join(self.job_dir, "junk.txt")
        f_outside = os.path.join(self.temp_dir, "outside.txt")
        with open(f1, "w") as f: f.write("keep")
        with open(f2, "w") as f: f.write("junk")
        with open(f_outside, "w") as f: f.write("protect")

        async def mock_edit(app, job, text, kb=None):
            pass

        job = {"_id": "test_job_del", "chat_id": 123, "message_id": 456}

        plan = {
            "summary": "Delete junk and try to delete outside file",
            "actions": [
                {"action": "delete_file", "files": ["junk.txt", "../outside.txt"]},
            ]
        }

        res = asyncio.run(execute_plan(None, job, self.job_dir, plan, mock_edit))
        self.assertFalse(os.path.exists(f2))         # junk.txt was deleted
        self.assertTrue(os.path.exists(f1))          # keep.mp4 was preserved
        self.assertTrue(os.path.exists(f_outside))   # outside.txt was NOT deleted (sandboxed)


if __name__ == "__main__":
    unittest.main()
