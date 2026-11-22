"""通过 FFmpeg 从本地媒体提取标准 WAV 音频。"""

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from ..config import load_config_section


class AudioConversionError(RuntimeError):
    """表示 FFmpeg 无法启动、超时或未能完成音频提取。"""


@dataclass(frozen=True)
class FFmpegConfig:
    """描述 FFmpeg 可执行文件和 WAV 输出参数，由转换调用方选用。"""

    executable: str
    sample_rate: int
    timeout_seconds: float

    def __post_init__(self) -> None:
        """校验命令、采样率和超时。

        :raises ValueError: 可执行文件为空、采样率非正整数或超时不是有限正数。
        """
        if not isinstance(self.executable, str) or not self.executable.strip():
            raise ValueError("executable 必须是非空的 FFmpeg 命令或路径")
        if type(self.sample_rate) is not int or self.sample_rate <= 0:
            raise ValueError("sample_rate 必须是正整数")
        if (type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise ValueError("timeout_seconds 必须是有限正数")

    @classmethod
    def load(cls, override: str | Path | None = None) -> "FFmpegConfig":
        """加载统一配置中的 ffmpeg 节，默认输出 16 kHz WAV，超时为 600 秒。

        :param override: 本地 TOML 覆盖文件。为 None 时使用包内默认值。
        :returns: 合并并校验后的配置。
        :raises OSError: 无法读取覆盖文件。
        :raises ValueError: TOML 内容或配置值无效。
        :raises TypeError: 配置含有未知字段。
        """
        return cls(**load_config_section("ffmpeg", override))


def extract_audio(media_path: str | Path, wav_path: str | Path, *,
                  config: FFmpegConfig | None = None) -> Path:
    """提取第一条音轨，输出单声道、16 位 PCM WAV。

    :param media_path: 本地视频或音频文件路径。
    :param wav_path: 输出文件路径，成功时原子替换同名文件。
    :param config: FFmpeg 执行配置。为 None 时使用包内默认值。
    :returns: 完整的 WAV 文件路径。
    :raises FileNotFoundError: 输入路径未指向可读取的本地文件。
    :raises ValueError: 输入路径与输出路径指向同一个文件路径。
    :raises AudioConversionError: FFmpeg 无法运行、超时或提取失败。
    :raises OSError: 无法创建输出目录或提交输出文件。
    """
    source = Path(media_path).resolve()
    target = Path(wav_path)
    if not source.is_file():
        raise FileNotFoundError(f"媒体文件不存在或不是普通文件：{source}")
    if source == target.resolve():
        raise ValueError("WAV 输出路径必须与输入媒体路径不同")

    config = config if config is not None else FFmpegConfig.load()
    target.parent.mkdir(parents=True, exist_ok=True)
    # 临时产物与目标位于同一文件系统。每次调用使用独立目录，失败时清理部分产物。
    with TemporaryDirectory(dir=target.parent) as directory:
        temporary_wav = Path(directory) / "audio.wav"
        # 按媒体时间轴补齐音轨开头和中间的空白，使后续字幕可按原播放时间引用。
        command = [
            config.executable, "-nostdin", "-v", "error", "-xerror",
            "-protocol_whitelist", "file", "-i", str(source),
            "-map", "0:a:0", "-vn", "-af", "aresample=async=1:first_pts=0",
            "-ac", "1", "-ar", str(config.sample_rate), "-c:a", "pcm_s16le",
            str(temporary_wav.resolve()),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=config.timeout_seconds)
        except subprocess.TimeoutExpired as error:
            raise AudioConversionError(f"FFmpeg 提取音频超过 {config.timeout_seconds:g} 秒") from error
        except subprocess.CalledProcessError as error:
            detail = error.stderr.strip()
            raise AudioConversionError(f"FFmpeg 提取音频失败（退出码 {error.returncode}）：{detail}") from error
        except OSError as error:
            raise AudioConversionError(f"无法启动 FFmpeg：{config.executable}") from error
        temporary_wav.replace(target)
    return target
