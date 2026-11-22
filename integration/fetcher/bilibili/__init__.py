"""B 站内容拉取与扫码登录的公开接口和数据类型。"""

from .auth import (
    BilibiliCredential,
    QrLoginChallenge,
    QrLoginResult,
    QrLoginSession,
    QrLoginStatus,
    load_credential_file,
    poll_qr_login,
    start_qr_login,
)
from .client import (
    AudioDownloadError,
    AudioUnavailableError,
    BilibiliConfig,
    BilibiliFetcher,
    CollectionKind,
    DownloadedAudio,
    VideoInfo,
    VideoPage,
)

__all__ = [
    "AudioDownloadError",
    "AudioUnavailableError",
    "BilibiliConfig",
    "BilibiliCredential",
    "BilibiliFetcher",
    "CollectionKind",
    "DownloadedAudio",
    "QrLoginChallenge",
    "QrLoginResult",
    "QrLoginSession",
    "QrLoginStatus",
    "VideoInfo",
    "VideoPage",
    "load_credential_file",
    "poll_qr_login",
    "start_qr_login",
]
