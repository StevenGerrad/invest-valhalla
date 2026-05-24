"""音频下载 + FFmpeg 转 WAV"""
import logging
import os
import subprocess
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# 探测 FFmpeg 路径
_FFMPEG_PATHS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
    "ffmpeg",
    "ffmpeg.exe",
]


def _find_ffmpeg() -> str:
    for path in _FFMPEG_PATHS:
        if os.path.exists(path) or _is_on_path(path):
            return path if os.path.exists(path) else path
    raise FileNotFoundError(
        "找不到 FFmpeg，请安装: winget install Gyan.FFmpeg\n"
        f"已搜索路径: {_FFMPEG_PATHS}"
    )


def _is_on_path(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None


DL_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}


def download_audio(audio_url: str, output_path: Path, overwrite: bool = False) -> Path:
    """下载 DASH 音频流到指定路径"""
    if output_path.exists() and not overwrite:
        logger.info("音频已存在，跳过: %s", output_path)
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("下载音频: %s", output_path)

    with httpx.stream("GET", audio_url, headers=DL_HEADERS, timeout=300) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(output_path, "wb") as f:
            for chunk in resp.iter_bytes(8192):
                f.write(chunk)
                downloaded += len(chunk)

        if total and downloaded != total:
            logger.warning("下载不完整: %d/%d bytes", downloaded, total)

    logger.info("下载完成: %s (%dKB)", output_path, downloaded // 1024)
    return output_path


def convert_to_wav(input_path: Path, output_path: Path | None = None,
                   sample_rate: int = 16000, overwrite: bool = False) -> Path:
    """用 FFmpeg 将音频转为 16kHz mono 16-bit WAV"""
    if output_path is None:
        output_path = input_path.with_suffix(".wav")

    if output_path.exists() and not overwrite:
        logger.info("WAV 已存在，跳过: %s", output_path)
        return output_path

    ffmpeg = _find_ffmpeg()
    cmd = [
        ffmpeg,
        "-i", str(input_path),
        "-ar", str(sample_rate),
        "-ac", "1",
        "-sample_fmt", "s16",
        "-y",
        str(output_path),
    ]
    logger.info("FFmpeg 转换: %s -> %s", input_path.name, output_path.name)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 转换失败:\n{result.stderr[-500:]}")

    logger.info("WAV 生成: %s (%dKB)", output_path,
                output_path.stat().st_size // 1024)
    return output_path
