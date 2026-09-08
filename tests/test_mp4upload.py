# Unit tests for MP4Upload downloader and link extraction
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
from megabot.downloaders.mp4upload import (
    MP4UploadDownloader,
    extract_mp4upload_links,
    is_mp4upload_link,
    mp4upload_link_key,
    unpack_dean_edwards,
)


class TestMP4UploadDownloader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_mp4upload_links(self):
        text = (
            "Watch this: https://www.mp4upload.com/abc123def and embed "
            "https://mp4upload.com/embed-xyz789.html and duplicate "
            "https://www.mp4upload.com/abc123def"
        )
        links = extract_mp4upload_links(text)
        self.assertEqual(len(links), 2)
        self.assertIn("https://www.mp4upload.com/abc123def", links)
        self.assertIn("https://mp4upload.com/embed-xyz789.html", links)

    def test_extract_supported_links_three_way(self):
        text = (
            "MEGA: https://mega.nz/file/vHQgXZbA#8U8273hjsd82 \n"
            "MediaFire: https://www.mediafire.com/file/abc123xyz/sample.pdf/file \n"
            "MP4Upload: https://www.mp4upload.com/uvw456"
        )
        links = extract_supported_links(text)
        self.assertEqual(len(links), 3)
        self.assertTrue(any("mega.nz" in l for l in links))
        self.assertTrue(any("mediafire.com" in l for l in links))
        self.assertTrue(any("mp4upload.com" in l for l in links))

    def test_is_mp4upload_link(self):
        self.assertTrue(is_mp4upload_link("https://www.mp4upload.com/abc123xyz"))
        self.assertTrue(is_mp4upload_link("http://mp4upload.com/embed-12345.html"))
        self.assertFalse(is_mp4upload_link("https://mediafire.com/file/123"))
        self.assertFalse(is_mp4upload_link("https://mega.nz/file/123#abc"))
        self.assertFalse(is_mp4upload_link("https://youtube.com"))

    def test_link_key(self):
        url = "https://www.mp4upload.com/embed-testkey123.html"
        self.assertEqual(mp4upload_link_key(url), "mp4u_testkey123")
        self.assertEqual(get_link_key(url), "mp4u_testkey123")

    def test_is_supported_link(self):
        self.assertTrue(is_supported_link("https://www.mp4upload.com/abc123xyz"))
        self.assertTrue(is_supported_link("https://www.mediafire.com/file/123/file.zip"))
        self.assertTrue(is_supported_link("https://mega.nz/file/123#abc"))
        self.assertFalse(is_supported_link("https://example.com/file.mp4"))

    def test_dean_edwards_unpacker(self):
        sample = (
            "eval(function(p,a,c,k,e,d){e=function(c){return c};if(!''.replace(/^/,String))"
            "{while(c--)d[c]=k[c]||c;k=[function(e){return d[e]}];e=function(){return'\\\\w+'};c=1};"
            "while(c--)if(k[c])p=p.replace(new RegExp('\\\\b'+e(c)+'\\\\b','g'),k[c]);return p}"
            "('1 0=\"2://3/4.5\";',6,6,'video_url|var|https|cdn.mp4upload.com|sample|mp4'.split('|'),0,{}))"
        )
        unpacked = unpack_dean_edwards(sample)
        self.assertIn("https://cdn.mp4upload.com/sample.mp4", unpacked)

    @patch("requests.Session.get")
    @patch("requests.Session.head")
    def test_probe_mp4upload(self, mock_head, mock_get):
        downloader = MP4UploadDownloader()

        sample_html = """
        <html>
            <head><title>My_Awesome_Video.mp4 - MP4Upload</title></head>
            <body>
                <script>
                player.src("https://www5.mp4upload.com:8686/d/samplekey/video.mp4");
                </script>
            </body>
        </html>
        """
        mock_resp_get = MagicMock()
        mock_resp_get.status_code = 200
        mock_resp_get.text = sample_html
        mock_get.return_value = mock_resp_get

        mock_resp_head = MagicMock()
        mock_resp_head.headers = {"content-length": "52428800"}
        mock_head.return_value = mock_resp_head

        info = downloader.probe("https://www.mp4upload.com/samplekey")
        self.assertEqual(info["name"], "My_Awesome_Video.mp4")
        self.assertEqual(info["size"], 52428800)
        self.assertEqual(info["kind"], "file")
        self.assertEqual(info["direct_url"], "https://www5.mp4upload.com:8686/d/samplekey/video.mp4")

    @patch("requests.Session.get")
    @patch("requests.Session.head")
    def test_download_mp4upload(self, mock_head, mock_get):
        downloader = MP4UploadDownloader()

        sample_html = """
        <html>
            <head><title>episode1.mp4</title></head>
            <body>
                <video src="https://cdn.mp4upload.com/stream/episode1.mp4"></video>
            </body>
        </html>
        """
        page_resp = MagicMock()
        page_resp.status_code = 200
        page_resp.text = sample_html

        video_bytes = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024
        stream_resp = MagicMock()
        stream_resp.status_code = 200
        stream_resp.headers = {"content-length": str(len(video_bytes))}
        stream_resp.__enter__.return_value = stream_resp
        stream_resp.__exit__.return_value = False
        stream_resp.iter_content.return_value = [video_bytes]

        mock_get.side_effect = [page_resp, stream_resp]

        mock_resp_head = MagicMock()
        mock_resp_head.headers = {"content-length": str(len(video_bytes))}
        mock_head.return_value = mock_resp_head

        progress_calls = []
        def progress_cb(done, total):
            progress_calls.append((done, total))

        target_file = downloader.download(
            "https://www.mp4upload.com/samplekey",
            self.temp_dir,
            progress_cb=progress_cb,
        )

        self.assertTrue(os.path.exists(target_file))
        self.assertEqual(os.path.basename(target_file), "episode1.mp4")
        with open(target_file, "rb") as f:
            self.assertEqual(f.read(), video_bytes)
        self.assertTrue(len(progress_calls) > 0)


if __name__ == "__main__":
    unittest.main()
