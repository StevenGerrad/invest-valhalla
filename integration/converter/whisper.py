"""将 faster-whisper 的识别结果转换为带时间戳的字幕。"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from ..config import load_config_section
from .subtitle import SubtitleSegment

if TYPE_CHECKING:
    from faster_whisper import WhisperModel
    from opencc import OpenCC


class TranscriptionError(RuntimeError):
    """表示依赖不可用、模型无法加载或语音识别未完整结束。"""


@dataclass(frozen=True)
class WhisperConfig:
    """描述 faster-whisper 的模型与执行设备，供转录器初始化使用。"""

    model_size: str
    device: str
    compute_type: str

    def __post_init__(self) -> None:
        """检查模型标识和运行参数是否已设置。

        :raises ValueError: 模型、设备或精度配置为空或不是字符串。
        """
        for name in ("model_size", "device", "compute_type"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 必须是非空字符串")

    @classmethod
    def load(cls, override: str | Path | None = None) -> "WhisperConfig":
        """加载统一配置中的 whisper 节，默认使用 turbo、CPU 和 int8。

        :param override: 本地 TOML 覆盖文件。为 None 时使用包内默认值。
        :returns: 合并并校验后的配置。
        :raises OSError: 无法读取覆盖文件。
        :raises ValueError: TOML 内容或配置值无效。
        :raises TypeError: 配置含有未知字段。
        """
        return cls(**load_config_section("whisper", override))


class WhisperTranscriber:
    """复用实例内的模型，将本地音频转为采集方可引用的字幕片段。"""

    def __init__(self, config: WhisperConfig | None = None) -> None:
        """初始化转录器，首次转录时再加载模型和可选依赖。

        :param config: 模型和设备配置。为 None 时使用包内默认值。
        """
        self._config = config if config is not None else WhisperConfig.load()
        self._model: WhisperModel | None = None
        self._opencc: OpenCC | None = None
        self._load_lock = Lock()

    def _get_model(self) -> "WhisperModel":
        """在首次识别时加载模型，后续识别沿用同一个实例。

        :returns: 已加载的 faster-whisper 模型。
        :raises ImportError: 未安装转录依赖。
        """
        # 模型初始化可能下载权重或分配显存，并发调用时只初始化一次。
        with self._load_lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self._config.model_size, device=self._config.device,
                                           compute_type=self._config.compute_type)
            return self._model

    def _get_opencc(self) -> "OpenCC":
        """按需加载繁体转简体词典。

        :returns: 可重复使用的 OpenCC 转换器。
        :raises ImportError: 未安装 OpenCC。
        """
        with self._load_lock:
            if self._opencc is None:
                from opencc import OpenCC

                self._opencc = OpenCC("t2s")
            return self._opencc

    def transcribe(self, audio_path: str | Path, *, language: str | None = None,
                   initial_prompt: str | None = None, hotwords: Sequence[str] | None = None,
                   simplify_chinese: bool = False) -> tuple[SubtitleSegment, ...]:
        """识别本地音频并返回完整的字幕片段，时间戳沿用输入音频的时间轴。

        :param audio_path: 本地音频文件路径。
        :param language: Whisper 语言代码，例如 zh。为 None 时自动识别。
        :param initial_prompt: 由调用方提供的识别提示。为 None 时不传入提示。
        :param hotwords: 由调用方提供的热词序列。为 None 或空序列时不使用热词。
        :param simplify_chinese: 是否用 OpenCC 将输出转为简体中文，默认为 False。
        :returns: 按模型输出顺序排列的片段。未识别到语音时返回空元组。
        :raises FileNotFoundError: 输入路径未指向本地文件。
        :raises TranscriptionError: 依赖缺失、模型加载或音频识别失败。
        """
        source = Path(audio_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"音频文件不存在或不是普通文件：{source}")

        try:
            model = self._get_model()
            normalizer = self._get_opencc() if simplify_chinese else None
            # SDK 接收空格分隔的热词和惰性片段。这里完成格式适配并读完整个结果再返回。
            segments, _ = model.transcribe(
                str(source), language=language, initial_prompt=initial_prompt,
                hotwords=" ".join(hotwords) if hotwords else None, vad_filter=True,
                beam_size=5, temperature=0.0, condition_on_previous_text=False,
            )
            result = []
            for segment in segments:
                text = segment.text.strip()
                if text:
                    text = normalizer.convert(text) if normalizer else text
                    result.append(SubtitleSegment(segment.start, segment.end, text))
        except ImportError as error:
            raise TranscriptionError("无法导入语音转录依赖，请安装 transcription 可选依赖") from error
        except Exception as error:
            # SDK 的模型加载、解码和惰性迭代异常统一留在接入边界内。
            raise TranscriptionError(f"语音转录失败：{source}") from error
        return tuple(result)
