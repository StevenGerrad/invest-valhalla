"""离线验证 B 站视频元数据和音频下载。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from valhalla.integration.fetcher.bilibili import client as bilibili


VIDEO = {
    "bvid": "BV1xx411c7mD",
    "title": "Sample",
    "owner": {"name": "Creator"},
    "pubdate": 1700000000,
    "duration": 80,
    "cid": 42,
}
TRACKS = {
    "dash": {"audio": [
        {"baseUrl": "https://example.test/low", "bandwidth": 1},
        {"base_url": "https://example.test/high", "bandwidth": 2},
    ]},
}


class AudioStream(httpx.AsyncByteStream):
    """模拟可在传输途中中断的音频响应体，只用于测试 HTTP 流式写入。"""

    def __init__(self, *, interrupted=False):
        """配置模拟音频流的行为。

        :param interrupted: 为 True 时在返回首段内容后中断，默认完整返回。
        """
        self.interrupted = interrupted

    async def __aiter__(self):
        """先返回一段内容，再按设置模拟中断。

        :raises httpx.ReadError: 已启用模拟中断。
        """
        yield b"audio"
        if self.interrupted:
            raise httpx.ReadError("private stream URL")


class BilibiliFetcherTests(unittest.IsolatedAsyncioTestCase):
    """验证分页、元数据与下载行为，使用模拟响应和临时目录隔离真实环境。"""

    async def test_creator_pagination_and_config_precedence(self):
        """验证分页结果，以及单次请求参数优先于模块配置。"""
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "override.toml"
            # 在同一文件内放入其他来源的同名字段，验证配置覆盖仅作用于 B 站配置节。
            config_file.write_text(
                "[bilibili]\npage_size = 7\n[other_provider]\npage_size = 12\n",
                encoding="utf-8",
            )
            config = bilibili.BilibiliConfig.load(config_file)
        self.assertEqual(config.download_timeout_seconds, 300)
        fetcher = bilibili.BilibiliFetcher(config=config)
        list_videos = AsyncMock(return_value={
            "page": {"count": 5},
            "list": {"vlist": [{
                "bvid": VIDEO["bvid"], "author": "Creator",
                "created": 1700000000, "length": "1:20",
            }]},
        })
        with patch.object(bilibili.user, "User", return_value=SimpleNamespace(get_videos=list_videos)):
            first = await fetcher.list_creator_videos(123)
            middle = await fetcher.list_creator_videos(123, page=2, page_size=2)
            last = await fetcher.list_creator_videos(123, page=3, page_size=2)
        self.assertEqual(first.page_size, 7)
        self.assertEqual(middle.next_page, 3)
        self.assertIsNone(last.next_page)
        self.assertEqual(middle.items[0].duration_seconds, 80)
        self.assertEqual(middle.items[0].published_ts, 1700000000)
        list_videos.assert_awaited_with(pn=3, ps=2)

    async def test_collection_formats_and_metadata(self):
        """验证新版合集、旧版系列和详情接口返回一致的视频元数据。"""
        get_videos = AsyncMock(side_effect=[
            {"archives": [VIDEO], "page": {"total": 10}},
            {"list": [VIDEO], "page": {"num": 1, "size": 2, "count": 1}},
        ])
        fetcher = bilibili.BilibiliFetcher()
        with patch.object(bilibili, "ChannelSeries") as series:
            series.return_value.get_videos = get_videos
            season = await fetcher.list_collection_videos(1, 2, page=2, page_size=3)
            self.assertEqual(series.call_args.kwargs["type_"], bilibili.ChannelSeriesType.SEASON)
            legacy = await fetcher.list_collection_videos(
                1, 2, kind=bilibili.CollectionKind.SERIES, page_size=2,
            )
            self.assertEqual(series.call_args.kwargs["type_"], bilibili.ChannelSeriesType.SERIES)
        self.assertEqual(season.next_page, 3)
        self.assertIsNone(legacy.next_page)
        with patch.object(bilibili.video, "Video") as video:
            video.return_value.get_info = AsyncMock(return_value=VIDEO)
            info = await fetcher.get_video(VIDEO["bvid"])
        self.assertEqual(info, legacy.items[0])
        self.assertEqual(info.author, "Creator")
        self.assertEqual(info.source_url, f"https://www.bilibili.com/video/{VIDEO['bvid']}")

    async def test_missing_audio(self):
        """验证平台未提供音轨时，下载接口报告错误且目标文件仍不存在。"""
        with tempfile.TemporaryDirectory() as directory, patch.object(bilibili.video, "Video") as video:
            destination = Path(directory) / "out.m4s"
            video.return_value.get_info = AsyncMock(return_value=VIDEO)
            video.return_value.get_download_url = AsyncMock(return_value={"dash": None})
            with self.assertRaises(bilibili.AudioUnavailableError):
                await bilibili.BilibiliFetcher().download_audio(VIDEO["bvid"], destination)
            self.assertFalse(destination.exists())

    async def test_download_replaces_only_complete_files(self):
        """验证完整的传输替换原文件，而失败时保留原文件并清理临时文件。"""
        original_client = httpx.AsyncClient
        # 分别模拟正常响应、长度不符和传输中断，覆盖不同的落盘结果。
        for length, interrupted in ((5, False), (6, False), (5, True)):
            with self.subTest(length=length, interrupted=interrupted):
                def respond(request):
                    """检查请求参数并构建模拟响应。

                    :param request: 模拟传输收到的 HTTP 请求。
                    :returns: 带指定内容长度和音频流的模拟响应。
                    """
                    self.assertEqual(request.url.path, "/high")
                    self.assertEqual(request.headers["accept-encoding"], "identity")
                    self.assertEqual(request.headers["origin"], "https://www.bilibili.com")
                    self.assertEqual(request.headers["referer"], f"https://www.bilibili.com/video/{VIDEO['bvid']}")
                    return httpx.Response(
                        200, headers={"Content-Length": str(length)},
                        stream=AudioStream(interrupted=interrupted),
                    )

                with tempfile.TemporaryDirectory() as directory, patch.object(bilibili.video, "Video") as video:
                    destination = Path(directory) / "out.m4s"
                    destination.write_bytes(b"original")
                    video.return_value.get_info = AsyncMock(return_value=VIDEO)
                    video.return_value.get_download_url = AsyncMock(return_value=TRACKS)
                    with patch.object(bilibili.httpx, "AsyncClient", side_effect=lambda **options: original_client(
                        transport=httpx.MockTransport(respond), **options,
                    )) as client:
                        fetcher = bilibili.BilibiliFetcher()
                        if length == 5 and not interrupted:
                            result = await fetcher.download_audio(VIDEO["bvid"], destination, timeout_seconds=9)
                            self.assertEqual(result.size_bytes, 5)
                            self.assertEqual(result.bvid, VIDEO["bvid"])
                            self.assertEqual(destination.read_bytes(), b"audio")
                            self.assertEqual(client.call_args.kwargs["timeout"], 9)
                        else:
                            with self.assertRaises(bilibili.AudioDownloadError) as error:
                                await fetcher.download_audio(VIDEO["bvid"], destination)
                            self.assertNotIn("private stream URL", str(error.exception))
                            self.assertEqual(destination.read_bytes(), b"original")
                        self.assertEqual(list(destination.parent.iterdir()), [destination])
                    video.return_value.get_download_url.assert_awaited_once_with(cid=42)
