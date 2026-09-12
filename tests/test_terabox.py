# Unit tests for TeraBox Downloader
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from megabot.downloaders import (
    extract_supported_links,
    get_downloader,
    get_link_key,
    is_supported_link,
)
from megabot.downloaders.terabox import (
    TeraBoxDownloader,
    _normalize_cookie,
    extract_surl,
    extract_terabox_links,
    is_terabox_link,
    terabox_link_key,
)


class TestTeraBoxDownloader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_terabox_links(self):
        sample_text = (
            "Check these links:\n"
            "1. https://terabox.com/s/1AbC_dEf-123\n"
            "2. https://www.1024tera.com/s/1xyz987\n"
            "3. https://teraboxapp.com/sharing/link?surl=mytesttoken\n"
            "4. Some random text https://google.com\n"
            "5. https://freeterabox.com/s/simpletoken\n"
            "6. Duplicate https://terabox.com/s/1AbC_dEf-123\n"
        )
        links = extract_terabox_links(sample_text)
        self.assertEqual(len(links), 4)
        self.assertIn("https://terabox.com/s/1AbC_dEf-123", links)
        self.assertIn("https://www.1024tera.com/s/1xyz987", links)
        self.assertIn("https://teraboxapp.com/sharing/link?surl=mytesttoken", links)
        self.assertIn("https://freeterabox.com/s/simpletoken", links)

    def test_is_terabox_link(self):
        self.assertTrue(is_terabox_link("https://terabox.com/s/1AbC_dEf"))
        self.assertTrue(is_terabox_link("https://1024tera.com/s/1xyz987"))
        self.assertTrue(is_terabox_link("https://teraboxapp.com/sharing/link?surl=token123"))
        self.assertTrue(is_terabox_link("https://nephobox.com/s/1token"))
        self.assertFalse(is_terabox_link("https://mediafire.com/file/123/file.mp4"))
        self.assertFalse(is_terabox_link("https://mega.nz/file/xyz#123"))
        self.assertFalse(is_terabox_link("https://google.com"))

    def test_extract_surl(self):
        self.assertEqual(extract_surl("https://terabox.com/s/1AbC_dEf"), "1AbC_dEf")
        self.assertEqual(extract_surl("https://1024tera.com/s/xyz987"), "xyz987")
        self.assertEqual(extract_surl("https://teraboxapp.com/sharing/link?surl=token123"), "token123")
        self.assertEqual(extract_surl("https://nephobox.com/s/1token_456"), "1token_456")

    def test_terabox_link_key(self):
        key = terabox_link_key("https://terabox.com/s/1AbC_dEf")
        self.assertEqual(key, "tb_1AbC_dEf")

    def test_normalize_cookie(self):
        self.assertEqual(_normalize_cookie(""), "")
        self.assertEqual(_normalize_cookie("Y5abc123xyz"), "ndus=Y5abc123xyz")
        self.assertEqual(_normalize_cookie("ndus=Y5abc123xyz"), "ndus=Y5abc123xyz")
        self.assertEqual(_normalize_cookie("ndus=Y5abc; path=/;"), "ndus=Y5abc; path=/;")

    @patch("requests.Session.get")
    def test_probe_single_file_via_api(self, mock_get):
        downloader = TeraBoxDownloader(cookie="Y5mockcookie")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "errno": 0,
            "list": [
                {
                    "server_filename": "sample_video.mp4",
                    "size": 10485760,
                    "fs_id": "12345678",
                    "dlink": "https://d.terabox.app/file/sample_video.mp4",
                }
            ],
        }
        mock_get.return_value = mock_resp

        info = downloader.probe("https://terabox.com/s/1AbC_dEf")
        self.assertEqual(info["name"], "sample_video.mp4")
        self.assertEqual(info["size"], 10485760)
        self.assertEqual(info["kind"], "file")
        self.assertEqual(info["direct_url"], "https://d.terabox.app/file/sample_video.mp4")

    @patch("requests.Session.get")
    def test_probe_folder_via_api(self, mock_get):
        downloader = TeraBoxDownloader(cookie="Y5mockcookie")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "errno": 0,
            "list": [
                {
                    "server_filename": "part1.mp4",
                    "size": 5000000,
                    "fs_id": "111",
                    "dlink": "https://d.terabox.app/part1.mp4",
                },
                {
                    "server_filename": "part2.mp4",
                    "size": 6000000,
                    "fs_id": "222",
                    "dlink": "https://d.terabox.app/part2.mp4",
                },
            ],
        }
        mock_get.return_value = mock_resp

        info = downloader.probe("https://terabox.com/s/1FolderToken")
        self.assertEqual(info["kind"], "folder")
        self.assertEqual(info["size"], 11000000)
        self.assertEqual(len(info["files"]), 2)

    @patch("requests.Session.get")
    def test_download_single_file(self, mock_get):
        downloader = TeraBoxDownloader(cookie="Y5mockcookie")

        # Mock probe response
        mock_api_resp = MagicMock()
        mock_api_resp.status_code = 200
        mock_api_resp.json.return_value = {
            "errno": 0,
            "list": [
                {
                    "server_filename": "downloaded_test.mp4",
                    "size": 100,
                    "fs_id": "123",
                    "dlink": "https://d.terabox.app/downloaded_test.mp4",
                }
            ],
        }

        # Mock stream download response
        mock_stream_resp = MagicMock()
        mock_stream_resp.status_code = 200
        mock_stream_resp.headers = {"content-length": "100"}
        mock_stream_resp.iter_content = MagicMock(return_value=[b"chunk1_", b"chunk2_data"])

        mock_get.side_effect = [mock_api_resp, mock_stream_resp]

        progress_calls = []

        def on_progress(done, total):
            progress_calls.append((done, total))

        res_dir = downloader.download(
            "https://terabox.com/s/1AbC_dEf",
            self.temp_dir,
            progress_cb=on_progress,
        )
        self.assertEqual(res_dir, self.temp_dir)
        target_file = os.path.join(self.temp_dir, "downloaded_test.mp4")
        self.assertTrue(os.path.exists(target_file))
        with open(target_file, "rb") as f:
            self.assertEqual(f.read(), b"chunk1_chunk2_data")
        self.assertGreater(len(progress_calls), 0)

    def test_unified_dispatcher_integration(self):
        text = (
            "Links: https://mega.nz/file/abc#123 "
            "and https://www.mediafire.com/file/xyz/doc.pdf "
            "and https://www.mp4upload.com/v123456 "
            "and https://terabox.com/s/1TeraTest"
        )
        links = extract_supported_links(text)
        self.assertEqual(len(links), 4)
        self.assertIn("https://terabox.com/s/1TeraTest", links)

        self.assertTrue(is_supported_link("https://terabox.com/s/1TeraTest"))
        self.assertTrue(is_supported_link("https://1024tera.com/s/1TeraTest"))
        self.assertEqual(get_link_key("https://terabox.com/s/1TeraTest"), "tb_1TeraTest")

    def test_get_downloader_returns_terabox(self):
        import asyncio
        dl = asyncio.run(get_downloader("https://terabox.com/s/1TeraTest"))
        self.assertIsInstance(dl, TeraBoxDownloader)

    @patch("requests.get")
    def test_check_cookie_validity(self, mock_get):
        from megabot.downloaders.terabox import check_cookie_validity

        # Empty
        res_empty = check_cookie_validity("")
        self.assertFalse(res_empty["valid"])

        # Valid session
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errno": 0, "uname": "TeraMaster"}
        mock_get.return_value = mock_resp
        res_ok = check_cookie_validity("Y5validcookie")
        self.assertTrue(res_ok["valid"])
        self.assertEqual(res_ok["username"], "TeraMaster")

        # Expired session
        mock_resp.json.return_value = {"errno": -6}
        res_expired = check_cookie_validity("Y5expired")
        self.assertFalse(res_expired["valid"])
        self.assertIn("expired", res_expired["message"].lower())

    def test_execute_tool_set_terabox_cookie(self):
        import asyncio
        from megabot.ai.tools import execute_tool

        with patch("megabot.downloaders.terabox.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"errno": 0, "uname": "Alice"}
            mock_get.return_value = mock_resp

            context = {"user_id": 12345, "is_owner": True}
            res = asyncio.run(execute_tool("set_terabox_cookie", {"cookie": "Y5samplecookie12345"}, context))
            self.assertEqual(res["status"], "success")
            self.assertIn("Global", res["scope"])
            self.assertEqual(res["account"], "Alice")


if __name__ == "__main__":
    unittest.main()
