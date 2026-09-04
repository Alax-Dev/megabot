# Unit tests for AI Agent Tools
import asyncio
import os
import shutil
import tempfile
import unittest

from megabot.ai.tools import execute_tool, TOOL_DEFINITIONS


class TestAITools(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.context = {"user_id": 99999, "is_owner": True}

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tool_definitions_valid(self):
        """Tool definitions must have name, description, and parameters."""
        self.assertTrue(len(TOOL_DEFINITIONS) >= 8)
        for t in TOOL_DEFINITIONS:
            self.assertIn("name", t)
            self.assertIn("description", t)
            self.assertIn("parameters", t)

    def test_get_system_stats(self):
        """get_system_stats returns disk, queue, and jobs info."""
        res = asyncio.run(execute_tool("get_system_stats", {}, self.context))
        self.assertEqual(res.get("status"), "success")
        self.assertIn("disk", res)
        self.assertIn("queue", res)

    def test_clean_disk_executes_safely(self):
        """clean_disk runs without error and returns summary."""
        res = asyncio.run(execute_tool("clean_disk", {}, self.context))
        self.assertEqual(res.get("status"), "success")
        self.assertIn("cleaned_folders", res)
        self.assertIn("freed_mb", res)

    def test_unknown_tool_handled_gracefully(self):
        """Unknown tool name returns error dictionary instead of raising."""
        res = asyncio.run(execute_tool("non_existent_tool", {}, self.context))
        self.assertEqual(res.get("status"), "error")
        self.assertIn("Unknown tool", res.get("message", ""))


if __name__ == "__main__":
    unittest.main()
