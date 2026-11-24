"""管理 B 站登录凭据及扫码状态，二维码展示和轮询节奏由调用方控制。"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from bilibili_api import Credential
from bilibili_api.login_v2 import QrCodeLogin, QrCodeLoginEvents

from ..error import FetchError


class BilibiliSessionError(FetchError):
    """表示本地会话不可用或平台要求登录，消息可直接展示给用户。"""


@dataclass(frozen=True)
class BilibiliCredential:
    """保存 B 站访问所需的凭据字段。

    供接入层与调用方传递凭据。由调用方决定持久化位置，具体 SDK 对象只在接入边界创建。
    """

    #: 登录会话 Cookie。
    sessdata: str | None = field(default=None, repr=False)
    #: 平台的请求校验 Cookie。
    bili_jct: str | None = field(default=None, repr=False)
    #: 平台提供的第一类设备标识。
    buvid3: str | None = field(default=None, repr=False)
    #: 平台提供的第二类设备标识。
    buvid4: str | None = field(default=None, repr=False)
    #: 登录账号的用户标识。
    dedeuserid: str | None = field(default=None, repr=False)
    #: 平台提供的会话刷新凭据。
    ac_time_value: str | None = field(default=None, repr=False)

    def _to_sdk(self) -> Credential:
        """将当前凭据转换为平台 SDK 使用的格式。

        :returns: 供接入层发起请求的 B 站 SDK 凭据对象。
        """
        return Credential(
            sessdata=self.sessdata,
            bili_jct=self.bili_jct,
            buvid3=self.buvid3,
            buvid4=self.buvid4,
            dedeuserid=self.dedeuserid,
            ac_time_value=self.ac_time_value,
        )


def load_credential_file(path: str | Path) -> BilibiliCredential:
    """从旧版键值文件读取 B 站凭据，读取过程只访问本地文件。

    :param path: 调用方指定的本地凭据文件路径，内容使用 UTF-8 编码。
    :returns: 从文件解析出的 B 站凭据。
    :raises ValueError: 文件缺少有效 SESSDATA。
    """
    keys = {"sessdata", "bili_jct", "buvid3", "buvid4", "dedeuserid", "ac_time_value"}
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        # Cookie 值本身可能包含等号。只按第一个等号拆分，并只接收已知的凭据字段。
        key, separator, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        if separator and key in keys and value and value != "None":
            values[key] = value
    if "sessdata" not in values:
        raise ValueError("Bilibili credential file must contain SESSDATA")
    return BilibiliCredential(**values)


def load_session_credential(session_dir: str | Path) -> BilibiliCredential | None:
    """读取指定目录中的 B 站临时登录会话。

    :param session_dir: 项目级会话目录。
    :returns: 有效的登录凭据。会话文件不存在时返回 None。
    :raises BilibiliSessionError: 会话文件无法读取、格式不完整或已过期。
    """
    try:
        data = json.loads((Path(session_dir) / "bilibili.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # 解析器的原始错误可能含文件内容，只提供固定的错误说明。
        raise BilibiliSessionError("无法读取 .sessions/bilibili.json，请重新登录 B 站") from None

    try:
        saved_at = datetime.fromisoformat(data["saved_at"])
        expires_at = datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") is not None else None
        fields = {
            key: data["credential"].get(key)
            for key in ("sessdata", "bili_jct", "buvid3", "buvid4", "dedeuserid", "ac_time_value")
        }
        if saved_at.tzinfo is None or (expires_at is not None and expires_at.tzinfo is None):
            raise ValueError("会话时间缺少时区")
        if any(value is not None and not isinstance(value, str) for value in fields.values()):
            raise ValueError("会话字段须为字符串")
        if not (fields["sessdata"] or "").strip():
            raise ValueError("缺少会话")
    except (AttributeError, KeyError, TypeError, ValueError):
        raise BilibiliSessionError("B 站会话文件格式无效，请重新登录 B 站") from None

    if expires_at is not None and expires_at <= datetime.now(expires_at.tzinfo):
        raise BilibiliSessionError("B 站会话已过期，请重新登录 B 站")
    return BilibiliCredential(**fields)


class QrLoginStatus(StrEnum):
    """定义调用方可见的四种扫码状态，隔离 B 站 SDK 的事件枚举。"""

    WAITING_FOR_SCAN = "waiting_for_scan"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    EXPIRED = "expired"
    AUTHENTICATED = "authenticated"


@dataclass(frozen=True)
class QrLoginResult:
    """表示一次扫码查询的状态。凭据仅在认证成功后可用，由调用方保管。"""

    status: QrLoginStatus
    credential: BilibiliCredential | None = field(default=None, repr=False)


@dataclass
class QrLoginSession:
    """保存进程内扫码会话、轮询锁和终态结果。

    该句柄归发起登录的进程管理。通过 API 提供扫码登录时，服务端保管句柄，
    客户端只接收二维码和可公开的状态。
    """

    _login: QrCodeLogin = field(repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _terminal: QrLoginResult | None = field(default=None, init=False, repr=False)


@dataclass(frozen=True)
class QrLoginChallenge:
    """将待展示的 PNG 和后续轮询句柄交给调用方。展示渠道和轮询时机由调用方决定。"""

    image_png: bytes = field(repr=False)
    session: QrLoginSession


async def start_qr_login() -> QrLoginChallenge:
    """创建一次扫码登录会话。

    :returns: 包含 PNG 图像字节和轮询句柄的登录请求。
    """
    login = QrCodeLogin()
    await login.generate_qrcode()
    return QrLoginChallenge(login.get_qrcode_picture().content, QrLoginSession(login))


async def poll_qr_login(session: QrLoginSession) -> QrLoginResult:
    """查询一次扫码进度。

    认证成功和二维码过期都是终态，后续查询直接返回已保存的结果。

    :param session: start_qr_login 创建的进程内句柄，同一二维码应沿用同一句柄。
    :returns: 当前扫码状态及认证成功后取得的凭据。
    """
    # 扫码状态和凭据都由 SDK 更新，锁保证并发轮询按顺序读取同一会话。
    async with session._lock:
        if session._terminal is not None:
            return session._terminal

        event = await session._login.check_state()
        # 将 SDK 事件映射为公开状态，调用方可直接依据状态更新界面。
        status = {
            QrCodeLoginEvents.SCAN: QrLoginStatus.WAITING_FOR_SCAN,
            QrCodeLoginEvents.CONF: QrLoginStatus.WAITING_FOR_CONFIRMATION,
            QrCodeLoginEvents.TIMEOUT: QrLoginStatus.EXPIRED,
            QrCodeLoginEvents.DONE: QrLoginStatus.AUTHENTICATED,
        }[event]
        if status == QrLoginStatus.AUTHENTICATED:
            # 成功时保存项目自己的凭据对象，后续查询仍可取得同一结果。
            sdk = session._login.get_credential()
            session._terminal = QrLoginResult(status, BilibiliCredential(
                sessdata=sdk.sessdata,
                bili_jct=sdk.bili_jct,
                buvid3=sdk.buvid3,
                buvid4=sdk.buvid4,
                dedeuserid=sdk.dedeuserid,
                ac_time_value=sdk.ac_time_value,
            ))
        elif status == QrLoginStatus.EXPIRED:
            # 过期后结果固定，重复查询无需再访问平台。
            session._terminal = QrLoginResult(status)
        return session._terminal or QrLoginResult(status)
