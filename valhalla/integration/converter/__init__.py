"""提供媒体、语音和网页的转换接口及可引用位置。"""

from .audio import AudioConversionError, FFmpegConfig, extract_audio
from .subtitle import SubtitleSegment, render_srt
from .webpage import WebParagraph, extract_web_text
from .whisper import TranscriptionError, WhisperConfig, WhisperTranscriber

__all__ = [
    "AudioConversionError",
    "FFmpegConfig",
    "SubtitleSegment",
    "TranscriptionError",
    "WebParagraph",
    "WhisperConfig",
    "WhisperTranscriber",
    "extract_audio",
    "extract_web_text",
    "render_srt",
]
