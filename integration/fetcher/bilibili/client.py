"""封装 B 站异步内容拉取，并将平台响应转换为项目自己的数据类型。"""

import math
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from bilibili_api import Credential, user, video
from bilibili_api.channel_series import ChannelSeries, ChannelSeriesType
from bilibili_api.exceptions import ApiException, CredentialNoSessdataException, ResponseCodeException

from ...config import load_config_section
from ..address import CollectionKind
from ..error import FetchError
from .auth import BilibiliCredential, BilibiliSessionError, load_session_credential


def _positive_int(value: int, name: str) -> int:
    """校验正整数配置项。

    :param value: 待校验的值，必须为正整数。
    :param name: 报错时显示的参数名。
    :returns: 校验通过的原值。
    :raises ValueError: 值的类型或范围无效。
    """
    # Python 将 bool 视作 int 的子类，这里要求实际的整数，避免把 True 当作页码 1。
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_timeout(value: float) -> float:
    """校验下载超时。

    :param value: 请求超时时间，单位为秒。
    :returns: 校验通过的原值。
    :raises ValueError: 值的类型无效，或值不是有限正数。
    """
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("download_timeout_seconds must be positive and finite")
    return value


@dataclass(frozen=True)
class BilibiliConfig:
    """保存并校验 B 站客户端的默认分页大小和下载超时。

    仅包含适配器的执行参数。配置文件的读取和覆盖由通用能力接入模块负责。
    """

    page_size: int
    download_timeout_seconds: float

    def __post_init__(self) -> None:
        """校验实例配置，确保直接构造和从文件加载遵循同一规则。

        :raises ValueError: 分页大小或下载超时无效。
        """
        _positive_int(self.page_size, "page_size")
        _positive_timeout(self.download_timeout_seconds)

    @classmethod
    def load(cls, override: str | Path | None = None) -> "BilibiliConfig":
        """从通用能力接入的统一配置加载 B 站参数。

        :param override: 覆盖文件路径，从中读取 bilibili 节。为 None 时仅使用包内默认配置。
        :returns: 合并默认值和覆盖值后校验通过的 B 站配置。
        :raises ValueError: 分页大小或下载超时无效。
        """
        return cls(**load_config_section("bilibili", override))


class AudioUnavailableError(FetchError):
    """平台未提供带可用下载地址的音轨时，由音频下载接口抛出。"""


class AudioDownloadError(OSError):
    """音频传输失败或响应无法形成完整文件时，由下载过程抛出。"""


class BilibiliRequestError(FetchError):
    """表示接入层无法完成 B 站请求，保留可安全展示的错误摘要。"""


@contextmanager
def _request_errors() -> Iterator[None]:
    """将平台 SDK 错误转换为接入层错误并过滤原始响应内容。

    :returns: 供 SDK 请求使用的上下文。
    :raises BilibiliSessionError: 平台要求登录。
    :raises BilibiliRequestError: 平台请求或响应解析失败。
    """
    try:
        yield
    except CredentialNoSessdataException:
        raise BilibiliSessionError("B 站接口要求登录，请更新 .sessions/bilibili.json") from None
    except ResponseCodeException as error:
        if error.code == -101:
            raise BilibiliSessionError("B 站接口要求登录，请更新 .sessions/bilibili.json") from None
        raise BilibiliRequestError(f"B 站拒绝请求（状态码 {error.code}）") from None
    except (ApiException, httpx.HTTPError, KeyError, TypeError, ValueError):
        raise BilibiliRequestError("B 站请求失败或返回格式无效") from None


@dataclass(frozen=True)
class VideoInfo:
    """描述已归一化的单条视频元数据，供采集调用方读取。

    发布时间是 Unix 秒级时间戳，时长以秒计。源响应缺少相应信息时为 None。
    """

    #: 平台的视频标识。
    bvid: str
    #: 视频标题，平台未提供时为空字符串。
    title: str
    #: 作者的公开显示名。
    author: str
    #: 平台发布时间，单位为 Unix 秒。
    published_ts: int | None
    #: 视频时长，单位为秒。
    duration_seconds: int | None
    #: 视频的公开页面地址。
    source_url: str
    #: 视频作者的 B 站账号 ID，平台未提供时为 None。
    author_mid: int | None = None


@dataclass(frozen=True)
class VideoPage:
    """封装一次视频列表请求的结果，便于调用方自行控制分页。

    total 为平台提供的总条数，缺失时为 None。next_page 为后续页码提示，
    缺失时调用方可以停止翻页。
    """

    items: tuple[VideoInfo, ...]
    page: int
    page_size: int
    total: int | None
    next_page: int | None


@dataclass(frozen=True)
class DownloadedAudio:
    """表示已完整写入的音频文件，并保留其来源视频和本地字节数。

    source_url 指向公开视频页面，可长期用来定位来源。
    """

    path: Path
    bvid: str
    source_url: str
    size_bytes: int


class BilibiliContentSource(Protocol):
    """声明调用方使用的 B 站浏览与音频拉取能力。"""

    async def list_creator_videos(
        self, mid: int, *, page: int = 1, page_size: int | None = None,
    ) -> VideoPage:
        """读取作者的一页投稿。

        :param mid: B 站作者账号 ID。
        :param page: 从 1 开始的页码。
        :param page_size: 页大小。为 None 时采用接入层默认值。
        :returns: 归一化的投稿分页。
        """
        ...

    async def list_collection_videos(
        self, mid: int, collection_id: int, *,
        kind: CollectionKind = CollectionKind.SEASON, page: int = 1, page_size: int | None = None,
    ) -> VideoPage:
        """读取作者所登记合集的一页资料。

        :param mid: B 站作者账号 ID。
        :param collection_id: 平台合集或系列 ID。
        :param kind: 合集类型，默认使用新版合集。
        :param page: 从 1 开始的页码。
        :param page_size: 页大小。为 None 时采用接入层默认值。
        :returns: 归一化的合集分页。
        """
        ...

    async def get_video(self, bvid: str) -> VideoInfo:
        """读取视频详情及来源作者。

        :param bvid: 视频的 BV 号。
        :returns: 归一化的视频详情。
        """
        ...

    async def download_audio(self, bvid: str, destination: str | Path) -> DownloadedAudio:
        """下载视频音轨到指定文件。

        :param bvid: 视频的 BV 号。
        :param destination: 完整下载后的目标路径。
        :returns: 下载结果与来源信息。
        """
        ...


def _source_url(bvid: str) -> str:
    """构造视频的公开页面地址。

    :param bvid: 视频的 BV 号。
    :returns: 可作为资料引用的页面 URL。
    """
    return f"https://www.bilibili.com/video/{bvid}"


def _duration_seconds(value: int | str | None) -> int | None:
    """将不同格式的时长统一换算为秒。

    :param value: 秒数、分秒或时分秒字符串。允许 None 或空字符串。
    :returns: 时长秒数。输入缺失或为空时返回 None。
    :raises ValueError: 时长中包含无法解析为整数的部分。
    """
    if value is None or value == "":
        return None
    seconds = 0
    # 按从高到低的时间单位累乘 60，同一逻辑可解析分秒与时分秒格式。
    for part in str(value).split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def _video_info(raw: dict) -> VideoInfo:
    """归一化投稿、合集和详情接口返回的视频字段。

    :param raw: 平台返回的单条视频数据，须包含 bvid。
    :returns: 含公开来源地址的 VideoInfo。
    """
    bvid = raw["bvid"]
    # 发布时间字段因接口而异，依次尝试 pubdate、ctime 和 created。
    published = raw.get("pubdate") or raw.get("ctime") or raw.get("created")
    owner = raw.get("owner") or {}
    author_mid = owner.get("mid") or raw.get("mid")
    return VideoInfo(
        bvid=bvid,
        title=raw.get("title") or "",
        author=raw.get("author") or owner.get("name") or "",
        published_ts=int(published) if published else None,
        duration_seconds=_duration_seconds(raw.get("duration") or raw.get("length")),
        source_url=_source_url(bvid),
        author_mid=int(author_mid) if author_mid else None,
    )


def _video_page(rows: list[dict], page: int, size: int, total: int | None) -> VideoPage:
    """归一化单页结果并推算后续页码。

    :param rows: 平台返回的视频列表。
    :param page: 从 1 开始的当前页码。
    :param size: 请求的单页大小。
    :param total: 平台返回的总条数，未知时为 None。
    :returns: 包含视频条目、分页信息和下一页提示的 VideoPage。
    """
    # 有总数就按总数判断。总数缺失时，满页只代表可能还有后续页，空页直接停止。
    has_more = bool(rows) and (page * size < total if total is not None else len(rows) >= size)
    return VideoPage(tuple(map(_video_info, rows)), page, size, total, page + 1 if has_more else None)


class BilibiliFetcher:
    """负责一次 B 站投稿、合集、详情查询或音频下载。

    类内封装请求、平台字段归一化和音频传输检查。调用方决定采集目标、
    翻页范围、执行频率及输出位置。
    """

    def __init__(
        self,
        credential: BilibiliCredential | None = None,
        *,
        config: BilibiliConfig | None = None,
        session_dir: str | Path | None = None,
    ) -> None:
        """使用提供的凭据与配置初始化 B 站拉取客户端。

        :param credential: 显式凭据，优先于会话目录。
        :param config: 已校验的适配器配置。为 None 时从模块默认配置加载。
        :param session_dir: 会话目录。未指定或文件不存在时可匿名访问。
        :raises BilibiliSessionError: 已提供的会话文件无效或过期。
        """
        if credential is None and session_dir is not None:
            credential = load_session_credential(session_dir)
        self._credential = credential._to_sdk() if credential is not None else Credential()
        self._config = config if config is not None else BilibiliConfig.load()

    def _page_size(self, page: int, page_size: int | None) -> int:
        """校验分页参数并确定实际请求的单页大小。

        :param page: 从 1 开始的页码。
        :param page_size: 单页大小。为 None 时采用模块配置的默认值。
        :returns: 用于本次请求的单页大小。
        :raises ValueError: 页码或提供的页大小不是正整数。
        """
        _positive_int(page, "page")
        return self._config.page_size if page_size is None else _positive_int(page_size, "page_size")

    async def list_creator_videos(
        self, mid: int, *, page: int = 1, page_size: int | None = None,
    ) -> VideoPage:
        """按发布时间获取指定 UP 主的一页投稿。

        :param mid: UP 主用户 ID。
        :param page: 从 1 开始的页码，默认第 1 页。
        :param page_size: 单页条数，省略时采用配置默认值。
        :returns: 标准化的分页结果。
        :raises ValueError: 页码或提供的页大小不是正整数。
        """
        size = self._page_size(page, page_size)
        creator = user.User(uid=mid, credential=self._credential)
        with _request_errors():
            result = await creator.get_videos(pn=page, ps=size)
            return _video_page(result["list"]["vlist"], page, size, result["page"]["count"])

    async def list_collection_videos(
        self,
        mid: int,
        collection_id: int,
        *,
        kind: CollectionKind = CollectionKind.SEASON,
        page: int = 1,
        page_size: int | None = None,
    ) -> VideoPage:
        """获取新版合集或旧版系列中的一页视频。

        :param mid: 合集所有者的用户 ID。
        :param collection_id: 合集或系列 ID。
        :param kind: 合集类型，默认使用新版合集接口。
        :param page: 从 1 开始的页码，默认第 1 页。
        :param page_size: 单页条数，省略时采用配置默认值。
        :returns: 标准化的分页结果。
        :raises ValueError: 页码或提供的页大小不是正整数。
        """
        size = self._page_size(page, page_size)
        series_type = {
            CollectionKind.SEASON: ChannelSeriesType.SEASON,
            CollectionKind.SERIES: ChannelSeriesType.SERIES,
        }[kind]
        collection = ChannelSeries(
            uid=mid, type_=series_type, id_=collection_id, credential=self._credential,
        )
        with _request_errors():
            result = await collection.get_videos(pn=page, ps=size)
            # 新版合集使用 archives，旧版系列使用 list，统一后再生成分页结果。
            rows = result["archives"] if "archives" in result else result["list"]
            pagination = result.get("page") or result.get("pagination") or {}
            total = pagination.get("total", pagination.get("count"))
            return _video_page(rows, page, size, total)

    async def get_video(self, bvid: str) -> VideoInfo:
        """查询视频详情。

        :param bvid: 目标视频的 BV 号。
        :returns: 含公开来源链接的 VideoInfo。
        """
        target = video.Video(bvid=bvid, credential=self._credential)
        with _request_errors():
            return _video_info(await target.get_info())

    async def download_audio(
        self,
        bvid: str,
        destination: str | Path,
        *,
        timeout_seconds: float | None = None,
    ) -> DownloadedAudio:
        """下载视频首个分 P 中码率最高的可用 DASH 音轨。

        音频完整下载后才替换目标文件。

        :param bvid: 目标视频的 BV 号。
        :param destination: 调用方指定的本地目标文件路径。
        :param timeout_seconds: HTTP 请求超时秒数。省略时使用配置值。
        :returns: 已下载文件的路径、来源信息及字节数。
        :raises ValueError: 指定的超时时间无效。
        :raises AudioUnavailableError: 平台未给出可用音轨。
        :raises AudioDownloadError: 传输失败或收到的音频不完整。
        """
        timeout = (
            self._config.download_timeout_seconds
            if timeout_seconds is None
            else _positive_timeout(timeout_seconds)
        )
        target = video.Video(bvid=bvid, credential=self._credential)
        with _request_errors():
            metadata = await target.get_info()
            playback = await target.get_download_url(cid=metadata["cid"])
        # 平台可能返回驼峰或下划线字段。先排除没有下载地址的音轨，再按码率选择。
        tracks = (playback.get("dash") or {}).get("audio") or []
        usable_tracks = [track for track in tracks if track.get("baseUrl") or track.get("base_url")]
        if not usable_tracks:
            raise AudioUnavailableError(f"No DASH audio available for {bvid}")
        track = max(usable_tracks, key=lambda item: item.get("bandwidth") or 0)
        stream_url = track.get("baseUrl") or track["base_url"]
        source_url = _source_url(bvid)
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        size = await _download_file(stream_url, path, source_url, timeout)
        return DownloadedAudio(path, bvid, source_url, size)


async def _download_file(url: str, path: Path, referer: str, timeout: float) -> int:
    """将音频流写入同目录临时文件，校验后替换目标。

    失败时清理临时文件，保留已有目标文件。

    :param url: 平台返回的临时音频地址。
    :param path: 最终写入路径，父目录由调用方创建。
    :param referer: 请求头使用的来源视频页面地址。
    :param timeout: HTTP 客户端超时设置，单位为秒。
    :returns: 实际写入的音频字节数。
    :raises AudioDownloadError: HTTP 传输失败、响应为空或实际长度与 Content-Length 不符。
    """
    partial_path = None
    # 请求不压缩响应内容，使 Content-Length 能与写入字节数直接比较。
    headers = {
        "Accept-Encoding": "identity",
        "Referer": referer,
        "Origin": "https://www.bilibili.com",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                length = response.headers.get("Content-Length")
                expected = int(length) if length is not None else None
                size = 0
                # 临时文件放在目标目录内，保证校验通过后可以在同一文件系统完成替换。
                with tempfile.NamedTemporaryFile(
                    dir=path.parent, prefix=f".{path.name}.", suffix=".part", delete=False,
                ) as partial:
                    partial_path = Path(partial.name)
                    async for chunk in response.aiter_raw():
                        size += partial.write(chunk)
        # 服务端可能省略长度，此时仍要求实际写入内容。已知长度时必须核对相等。
        if not size or (expected is not None and size != expected):
            raise AudioDownloadError("Incomplete Bilibili audio download")
        partial_path.replace(path)
        return size
    except httpx.HTTPStatusError as error:
        # 对外只保留 HTTP 状态，避免原始异常中的临时签名地址进入调用方日志。
        raise AudioDownloadError(f"Bilibili audio server returned HTTP {error.response.status_code}") from None
    except (httpx.HTTPError, ValueError):
        raise AudioDownloadError("Bilibili audio transfer failed") from None
    finally:
        if partial_path is not None:
            partial_path.unlink(missing_ok=True)
