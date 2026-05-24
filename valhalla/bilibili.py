"""B站 API 交互：视频列表 + DASH 音频流 URL"""
import time
import logging
import os
from pathlib import Path
from typing import Iterator

from bilibili_api import select_client, sync, get_buvid, Credential, user, video
from bilibili_api.exceptions import NetworkException

select_client("httpx")

logger = logging.getLogger(__name__)


def load_credential_from_file(filepath: str | Path) -> Credential:
    """从 .env 文件加载登录凭据"""
    cred_env = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if v and v != "None":
                    cred_env[k] = v

    buvid3, buvid4 = sync(get_buvid())
    return Credential(
        sessdata=cred_env.get("SESSDATA", ""),
        bili_jct=cred_env.get("BILI_JCT", ""),
        buvid3=buvid3,
        buvid4=buvid4,
        dedeuserid=cred_env.get("DEDEUSERID", ""),
        ac_time_value=cred_env.get("AC_TIME_VALUE"),
    )


def login_with_qrcode() -> Credential:
    """二维码登录，返回凭据"""
    from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents
    qr = QrCodeLogin()
    sync(qr.generate_qrcode())

    # 保存图片
    import tempfile
    img = qr.get_qrcode_picture()
    img_path = Path(tempfile.gettempdir()) / "bilibili_qr_login.png"
    img.to_file(str(img_path))
    logger.info("二维码已保存: %s", img_path)

    # 尝试打开图片
    try:
        os.startfile(img_path)
    except Exception:
        pass

    # 终端备用
    qr.get_qrcode_terminal()

    print("\n请用 B站 APP 扫码并点击确认登录...")
    last_event = None
    for _ in range(120):  # 4 分钟
        event = sync(qr.check_state())
        if event != last_event:
            labels = {
                QrCodeLoginEvents.SCAN: "已扫码，等待确认...",
                QrCodeLoginEvents.CONF: "已确认，获取凭据...",
                QrCodeLoginEvents.DONE: "登录完成!",
                QrCodeLoginEvents.TIMEOUT: "二维码已过期",
            }
            print(f"  {labels.get(event, str(event))}")
            last_event = event
        if event == QrCodeLoginEvents.DONE:
            return qr.get_credential()
        elif event == QrCodeLoginEvents.TIMEOUT:
            raise RuntimeError("二维码已过期")
        time.sleep(2)
    raise RuntimeError("登录超时")


class BiliClient:
    """B站 API 客户端，封装视频列表和 DASH 流获取"""

    def __init__(self, credential: Credential | None = None):
        if credential is None:
            buvid3, buvid4 = sync(get_buvid())
            credential = Credential(buvid3=buvid3, buvid4=buvid4)
        self.credential = credential

    def get_video_list(self, mid: int, page: int = 1, page_size: int = 30,
                       max_retries: int = 3) -> list[dict]:
        """获取 UP 主视频列表，返回视频条目列表 [{bvid, title, length, ...}]"""
        u = user.User(uid=mid, credential=self.credential)

        for attempt in range(max_retries):
            try:
                result = sync(u.get_videos(ps=page_size, pn=page))
                return result["list"]["vlist"]
            except NetworkException as e:
                if e.status == 412:
                    wait = (attempt + 1) * 30
                    logger.warning("触发 B 站风控 (412)，等待 %ds...", wait)
                    time.sleep(wait)
                    # 刷新 buvid
                    buvid3, buvid4 = sync(get_buvid())
                    self.credential = Credential(buvid3=buvid3, buvid4=buvid4)
                    u = user.User(uid=mid, credential=self.credential)
                elif e.status == -799:
                    wait = (attempt + 1) * 5
                    logger.warning("触发限频 (-799)，等待 %ds...", wait)
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError(f"多次重试后仍无法获取视频列表 (mid={mid})")

    def iter_all_videos(self, mid: int, page_size: int = 30,
                        max_pages: int | None = None) -> Iterator[dict]:
        """迭代获取 UP 主全部视频"""
        u = user.User(uid=mid, credential=self.credential)
        result = sync(u.get_videos(ps=page_size, pn=1))
        total = result["page"]["count"]
        total_pages = (total + page_size - 1) // page_size
        if max_pages:
            total_pages = min(total_pages, max_pages)

        logger.info("UP 主 mid=%d 共 %d 个视频，%d 页", mid, total, total_pages)

        # 第一页已经拿到
        for item in result["list"]["vlist"]:
            yield item

        # 后续页
        for page in range(2, total_pages + 1):
            time.sleep(2)  # 避免限频
            vlist = self.get_video_list(mid, page=page, page_size=page_size)
            if not vlist:
                break
            for item in vlist:
                yield item

    def iter_series_videos(self, mid: int, series_id: int) -> Iterator[dict]:
        """迭代获取 UP 主某个系列/合集的全部视频"""
        from bilibili_api.channel_series import ChannelSeries, ChannelSeriesType

        # 先尝试 SEASON（新版合集），再尝试 SERIES（旧版系列）
        for stype in [ChannelSeriesType.SEASON, ChannelSeriesType.SERIES]:
            try:
                cs = ChannelSeries(uid=mid, type_=stype, id_=series_id,
                                   credential=self.credential)
                meta = sync(cs.get_meta())
                name = meta.get("title") or meta.get("name") or f"series_{series_id}"
                total = meta.get("total", 0)
                logger.info("系列「%s」共 %d 个视频", name, total)

                all_videos = sync(cs.get_videos())
                # SEASON 返回不同结构
                if "archives" in all_videos:
                    videos = all_videos["archives"]
                elif "list" in all_videos:
                    videos = all_videos["list"]
                else:
                    videos = []

                logger.info("系列模式: 获取到 %d 个视频", len(videos))
                for v in videos:
                    # 归一化字段名（系列 API 返回 duration/stat/cid 等不同字段）
                    duration = v.get("duration", 0)
                    length = v.get("length", "")
                    if not length and duration:
                        m, s = divmod(duration, 60)
                        length = f"{m:02d}:{s:02d}"
                    play = v.get("play", 0)
                    if not play and "stat" in v:
                        play = v["stat"].get("view", 0)
                    yield {
                        "bvid": v["bvid"],
                        "title": v.get("title", ""),
                        "author": v.get("author", "") or v.get("owner", {}).get("name", ""),
                        "length": length,
                        "created": v.get("ctime", 0) or v.get("pubdate", 0) or v.get("created", 0),
                        "play": play,
                        "description": v.get("description", ""),
                    }
                return  # 成功即退出
            except Exception as e:
                logger.debug("尝试 %s 失败: %s", stype, e)
                continue

        raise RuntimeError(f"无法获取系列视频 (mid={mid}, series_id={series_id})")

    def get_audio_streams(self, bvid: str) -> list[dict]:
        """获取视频的 DASH 音频流列表，按码率降序排列"""
        v = video.Video(bvid=bvid, credential=self.credential)
        info = sync(v.get_info())
        cid = info["cid"]
        duration = info["duration"]

        time.sleep(1)
        play_url = sync(v.get_download_url(cid=cid))
        audio_list = play_url["dash"]["audio"]
        audio_list.sort(key=lambda a: a.get("bandwidth", 0), reverse=True)

        logger.info("视频 [%s] cid=%s duration=%ds %d 个音频流",
                     bvid, cid, duration, len(audio_list))
        return audio_list

    def get_best_audio_url(self, bvid: str) -> tuple[str, int]:
        """返回最佳音频流的 URL 和时长，格式: (url, duration_seconds)"""
        streams = self.get_audio_streams(bvid)
        best = streams[0]
        return best["base_url"], best.get("duration", 0)
