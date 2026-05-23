"""faster-whisper 转录 + SRT 字幕生成"""
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 引导模型输出简体中文的提示词（领域化：股票投资）
SIMPLIFIED_CHINESE_PROMPT = "以下是关于股票投资、价值投资和个人理财的普通话视频内容。涉及PE估值、PB估值、仓位管理、基本面分析、技术面分析等金融术语。"

# 金融投资领域热词：引导模型在解码时优先匹配这些词汇，减少同音错
# 以 list 为正模，调用 faster-whisper 时转为空格分隔字符串
DOMAIN_HOTWORDS: list[str] = [
    # 常见股票/公司名
    "横店影视", "万达电影", "中国电影", "长江电力", "TCL", "京东方",
    # 金融术语
    "PE", "PB", "ROE", "估值", "仓位", "风控", "分散度",
    "基本面", "技术面", "一季报", "年报", "扭亏为盈",
    # 投资常用词
    "持仓", "本金", "止损", "止盈", "分红", "股息", "市盈率",
    "市净率", "流动性", "大盘", "板块", "中长线", "短线",
    # UP 主常用词
    "韭菜", "炒股", "散户", "机构", "庄家", "拉升", "回调",
]


def srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class Transcriber:
    """Whisper 语音转录器"""

    def __init__(self, model_size: str = "small", device: str = "cpu",
                 compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._opencc = None

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            t0 = time.time()
            logger.info("加载 faster-whisper 模型: %s (device=%s)", self.model_size, self.device)
            self._model = WhisperModel(
                self.model_size, device=self.device, compute_type=self.compute_type
            )
            logger.info("模型加载完成 (%.1fs)", time.time() - t0)

    def _get_opencc(self):
        if self._opencc is None:
            from opencc import OpenCC
            self._opencc = OpenCC('t2s')  # Traditional → Simplified
        return self._opencc

    def transcribe(self, wav_path: Path, language: str = "zh",
                   hotwords: list[str] | None = None) -> list[dict]:
        """转录音频，返回 segment 列表 [{start, end, text}]"""
        self._load_model()
        logger.info("转录: %s", wav_path)

        if hotwords is None:
            hotwords = DOMAIN_HOTWORDS

        # faster-whisper 要求空格分隔字符串，list 是正模
        hotwords_str = " ".join(hotwords)

        segments_gen, info = self._model.transcribe(
            str(wav_path),
            language=language,
            initial_prompt=SIMPLIFIED_CHINESE_PROMPT,
            hotwords=hotwords_str,
            vad_filter=True,
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
        )
        segments = list(segments_gen)

        # 后处理：繁体→简体（兜底，initial_prompt 已引导大部分）
        cc = self._get_opencc()
        results = []
        for seg in segments:
            text = seg.text.strip()
            converted = cc.convert(text)
            if converted != text:
                logger.debug("繁简转换: %s -> %s", text[:30], converted[:30])
            results.append({
                "start": seg.start,
                "end": seg.end,
                "text": converted,
            })

        logger.info("语言: %s (%.2f), 识别 %d 段", info.language,
                     info.language_probability, len(results))
        return results

    def transcribe_to_srt(self, wav_path: Path, srt_path: Path,
                          overwrite: bool = False,
                          hotwords: list[str] | None = None) -> Path:
        """转录并直接输出 SRT 文件"""
        if srt_path.exists() and not overwrite:
            logger.info("字幕已存在，跳过: %s", srt_path)
            return srt_path

        segments = self.transcribe(wav_path, hotwords=hotwords)
        srt_path.parent.mkdir(parents=True, exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, start=1):
                f.write(f"{i}\n")
                f.write(f"{srt_time(seg['start'])} --> {srt_time(seg['end'])}\n")
                f.write(seg["text"] + "\n\n")

        logger.info("字幕生成: %s (%d 段)", srt_path, len(segments))
        return srt_path
