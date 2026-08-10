"""ASR Provider 抽象层 - 统一接口，多实现可切换。

层级关系：
    ASRProvider (ABC)
      ├─ MockASRProvider       — 阶段 1：离线 Mock，固定返回 "春草"
      ├─ ThirdPartyASRProvider — 阶段 2+：包裹 dialect_asr_dashscope.recognize()
      └─ LocalPuxianASRProvider — 阶段 6：本地莆仙话模型（占位）

工厂函数 get_provider(name) 按名称返回对应实例。
"""

import os
import wave
from abc import ABC, abstractmethod
from typing import Optional


# ============================================================
# 异常定义
# ============================================================

class ASRError(Exception):
    """ASR 处理过程中的结构化错误，携带错误码供上层转换。"""

    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"[{code}] {message}")


# ============================================================
# 音频格式校验工具
# ============================================================

# 支持的音频格式
_SUPPORTED_FORMATS = ["wav", "mp3", "webm", "m4a", "ogg"]

_MAX_DURATION_SECONDS = 30


def _check_magic_number(filepath: str) -> str:
    """
    读取文件头部字节，校验 magic number。

    Returns:
        格式名称字符串：wav / mp3 / webm / m4a / ogg

    Raises:
        ASRError: 文件不存在 (AUDIO_EMPTY)、文件为空 (AUDIO_EMPTY)、
                  格式不支持 (AUDIO_FORMAT_UNSUPPORTED)
    """
    if not os.path.exists(filepath):
        raise ASRError("AUDIO_EMPTY", "文件不存在", retryable=False)

    file_size = os.path.getsize(filepath)
    if file_size == 0:
        raise ASRError("AUDIO_EMPTY", "文件为空（0 字节）", retryable=False)

    # 读取前 12 字节（M4A 的 ftyp 在偏移 4-7）
    with open(filepath, "rb") as f:
        header = f.read(12)

    if len(header) < 4:
        raise ASRError("AUDIO_FORMAT_UNSUPPORTED", "文件过短，无法识别格式", retryable=False)

    first4 = header[:4]
    first2 = header[:2]
    first3 = header[:3]

    # WAV: RIFF
    if first4 == b"RIFF":
        return "wav"

    # MP3: ID3v2 标签
    if first3 == b"ID3":
        return "mp3"

    # MP3: 帧同步（无 ID3 标签）
    if first2 in (b"\xff\xfb", b"\xff\xf3", b"\xff\xfa", b"\xff\xf2", b"\xff\xe3"):
        return "mp3"

    # WebM / Matroska: EBML header
    if first4 == b"\x1a\x45\xdf\xa5":
        return "webm"

    # OGG
    if first4 == b"OggS":
        return "ogg"

    # M4A / MP4: ftyp box at offset 4
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return "m4a"

    raise ASRError(
        "AUDIO_FORMAT_UNSUPPORTED",
        f"不支持的音频格式（magic: {first4.hex()}）",
        retryable=False,
    )


def _estimate_duration_seconds(filepath: str, fmt: str) -> float:
    """
    尽力估算音频时长（秒）。

    WAV: 读取 header 精确计算
    其他: 按文件大小粗略估算（保守阈值，避免误拒）
    """
    # WAV 可以精确读取
    if fmt == "wav":
        try:
            with wave.open(filepath, "rb") as w:
                frames = w.getnframes()
                rate = w.getframerate()
                if rate > 0:
                    return frames / rate
        except Exception:
            pass
        # WAV header 读取失败时用文件大小估算（16kHz mono 16-bit = 32KB/s）
        return os.path.getsize(filepath) / 32000

    file_size = os.path.getsize(filepath)

    # 压缩格式粗略估算（偏保守，宁可放行也不误拒）
    if fmt == "webm":
        # Opus ~32kbps = 4KB/s
        return file_size / 4000
    elif fmt == "ogg":
        # Vorbis ~128kbps = 16KB/s
        return file_size / 16000
    else:
        # MP3 / M4A ~128kbps = 16KB/s
        return file_size / 16000


# ============================================================
# 抽象基类
# ============================================================

class ASRProvider(ABC):
    """ASR 提供方抽象基类，所有实现必须继承并实现 transcribe()。"""

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: str = "auto",
        accent: Optional[str] = None,
    ) -> dict:
        """
        对音频文件做语音识别。

        Args:
            audio_path: 本地音频文件路径
            language: 语言代码（auto/putian/mandarin 等）
            accent: 口音标注（可选）

        Returns:
            dict: {
                text: str,           # 识别文本
                confidence: float,   # 置信度 0.0-1.0
                duration_ms: int,    # 音频时长（毫秒）
                raw: dict,           # 原始返回（调试用）
                provider: str,       # 提供方名称
                model_version: str,  # 模型版本
            }

        Raises:
            ASRError: 文件校验或处理错误
        """
        ...


# ============================================================
# MockASRProvider
# ============================================================

class MockASRProvider(ASRProvider):
    """
    Mock ASR Provider — 阶段 1 离线模式。

    行为规范：
      - 有效音频文件 → 返回固定文本 "春草", confidence 0.95
      - 空文件 → ASRError(AUDIO_EMPTY)
      - 格式不支持 → ASRError(AUDIO_FORMAT_UNSUPPORTED)
      - 超过 30 秒 → ASRError(AUDIO_TOO_LONG)
      - 结果始终标注 provider="mock", model_version="mock-v1"
    """

    MOCK_TEXT = "春草"
    MOCK_CONFIDENCE = 0.95
    PROVIDER_NAME = "mock"
    MODEL_VERSION = "mock-v1"

    def transcribe(
        self,
        audio_path: str,
        language: str = "auto",
        accent: Optional[str] = None,
    ) -> dict:
        # 1. 校验文件存在性 + magic number
        fmt = _check_magic_number(audio_path)

        # 2. 校验时长
        duration_s = _estimate_duration_seconds(audio_path, fmt)
        if duration_s > _MAX_DURATION_SECONDS:
            raise ASRError(
                "AUDIO_TOO_LONG",
                f"音频时长 {duration_s:.1f}s 超过限制 {_MAX_DURATION_SECONDS}s",
                retryable=False,
            )

        duration_ms = int(duration_s * 1000)

        # 3. 返回固定 Mock 结果（不实际识别音频内容）
        return {
            "text": self.MOCK_TEXT,
            "confidence": self.MOCK_CONFIDENCE,
            "duration_ms": duration_ms,
            "raw": {"mock": True, "format": fmt, "language": language},
            "provider": self.PROVIDER_NAME,
            "model_version": self.MODEL_VERSION,
        }


# ============================================================
# ThirdPartyASRProvider
# ============================================================

class ThirdPartyASRProvider(ASRProvider):
    """
    第三方云端 ASR Provider — 包裹 dialect_asr_dashscope.recognize()。

    阶段 2+：配置 DASHSCOPE_API_KEY 后可用。
    使用阿里云 paraformer-realtime-v2 模型做语音识别。
    """

    def __init__(self, provider_name: str = "thirdparty", **kwargs):
        self.provider_name = provider_name
        self.kwargs = kwargs

    def transcribe(
        self,
        audio_path: str,
        language: str = "auto",
        accent: Optional[str] = None,
    ) -> dict:
        # 1. 校验文件格式
        fmt = _check_magic_number(audio_path)

        # 2. 校验时长
        duration_s = _estimate_duration_seconds(audio_path, fmt)
        if duration_s > _MAX_DURATION_SECONDS:
            raise ASRError(
                "AUDIO_TOO_LONG",
                f"音频时长 {duration_s:.1f}s 超过限制 {_MAX_DURATION_SECONDS}s",
                retryable=False,
            )

        duration_ms = int(duration_s * 1000)

        # 3. 调用 DashScope
        try:
            from dialect_asr_dashscope import recognize
        except ImportError:
            raise ASRError(
                "PROVIDER_ERROR",
                "dashscope SDK 未安装，请运行 pip install dashscope",
                retryable=False,
            )

        try:
            result = recognize(audio_path, language)
        except Exception as e:
            raise ASRError(
                "PROVIDER_ERROR",
                f"DashScope 调用异常: {e}",
                retryable=True,
            )

        text = result.get("text", "")
        engine = result.get("engine", "dashscope")
        error = result.get("error", "")

        # 4. 无识别结果
        if not text:
            # 检查是否是 API Key 问题
            if "API_KEY" in error.upper() or "key" in error.lower():
                raise ASRError(
                    "PROVIDER_ERROR",
                    "DASHSCOPE_API_KEY 未配置或无效",
                    retryable=False,
                )
            # 识别失败（静音/噪音/不支持的语言）
            return {
                "text": "",
                "confidence": 0.0,
                "duration_ms": duration_ms,
                "raw": result,
                "provider": self.provider_name,
                "model_version": engine,
            }

        # 5. 识别成功
        return {
            "text": text,
            "confidence": 0.9,
            "duration_ms": duration_ms,
            "raw": result,
            "provider": self.provider_name,
            "model_version": engine,
        }


# ============================================================
# LocalPuxianASRProvider
# ============================================================

class LocalPuxianASRProvider(ASRProvider):
    """
    本地莆仙话 ASR Provider — Phase 6 实现。

    引擎优先级：
      1. 自训练 Whisper LoRA 模型（PEFT 格式）— 优先引擎
      2. SenseVoice 原始模型 — 回退引擎
      3. 全部失败 → 返回空文本供前端降级

    LoRA 适配器搜索路径：
      - training_data/finetune_workspace/lora_output/
      - training_data/lora_output/
      - 环境变量 LORA_ADAPTER_PATH
      - training_data/local_model_config.json 的 custom_model_path

    当 LoRA 适配器不存在时，自动回退到 SenseVoice 原始模型。

    依赖：
      - peft + transformers（LoRA 加载，可选）
      - funasr + SenseVoiceSmall 模型（回退引擎）
    """

    PROVIDER_NAME = "local"
    MODEL_VERSION = "local-puxian-v1"

    # 语言代码映射：provider 接口 → dialect_asr 接口
    _LANG_MAP = {
        "auto": "auto",
        "putian": "putian",
        "xianyou": "putian",   # 仙游话归入莆仙话
        "mandarin": "mandarin",
    }

    def transcribe(
        self,
        audio_path: str,
        language: str = "auto",
        accent: Optional[str] = None,
    ) -> dict:
        # 1. 校验文件格式
        fmt = _check_magic_number(audio_path)

        # 2. 校验时长
        duration_s = _estimate_duration_seconds(audio_path, fmt)
        if duration_s > _MAX_DURATION_SECONDS:
            raise ASRError(
                "AUDIO_TOO_LONG",
                f"音频时长 {duration_s:.1f}s 超过限制 {_MAX_DURATION_SECONDS}s",
                retryable=False,
            )

        duration_ms = int(duration_s * 1000)

        # 3. 映射语言代码
        # accent 优先（如果提供了口音标注）
        lang_for_asr = self._LANG_MAP.get(accent or language, "auto")

        # 4. 调用 dialect_asr.recognize()
        # 莆仙话引擎：LoRA 优先，SenseVoice 回退
        # 至少需要一个引擎可用
        try:
            from dialect_asr import recognize, SENSEVOICE_AVAILABLE, PEFT_AVAILABLE
        except ImportError:
            raise ASRError(
                "PROVIDER_ERROR",
                "dialect_asr 模块未找到，请确保 scripts 目录在 Python 路径中",
                retryable=False,
            )

        if not SENSEVOICE_AVAILABLE and not PEFT_AVAILABLE:
            raise ASRError(
                "PROVIDER_ERROR",
                "本地 ASR 引擎未安装。请安装 funasr（SenseVoice）或 peft+transformers（LoRA）",
                retryable=False,
            )

        try:
            result = recognize(audio_path, lang_for_asr)
        except Exception as e:
            raise ASRError(
                "PROVIDER_ERROR",
                f"本地 ASR 识别异常: {e}",
                retryable=True,
            )

        # 5. 处理识别结果
        text = result.get("text", "")
        engine = result.get("engine", "unknown")
        detected_lang = result.get("lang", lang_for_asr)
        error = result.get("error", "")

        # 无识别结果 — 返回空文本供前端降级（不抛异常）
        if not text:
            return {
                "text": "",
                "confidence": 0.0,
                "duration_ms": duration_ms,
                "raw": result,
                "provider": self.PROVIDER_NAME,
                "model_version": f"{engine}-local",
            }

        # 6. 识别成功
        # 自训练模型置信度最高，SenseVoice 次之
        if engine == "finetuned-whisper":
            confidence = 0.92
        elif engine == "sensevoice":
            confidence = 0.88
        elif engine == "whisper":
            confidence = 0.80
        else:
            confidence = 0.75

        return {
            "text": text,
            "confidence": confidence,
            "duration_ms": duration_ms,
            "raw": result,
            "provider": self.PROVIDER_NAME,
            "model_version": f"{engine}-local",
        }


# ============================================================
# 工厂函数
# ============================================================

def get_provider(name: str = "mock") -> ASRProvider:
    """
    按名称获取 ASR Provider 实例。

    Args:
        name: 提供方名称
              "mock"       → MockASRProvider（默认）
              "thirdparty" → ThirdPartyASRProvider
              "local"      → LocalPuxianASRProvider

    Returns:
        ASRProvider 实例

    注意：
        未知名称不报错，回退到 MockASRProvider（安全降级）。
    """
    name = (name or "mock").lower().strip()

    if name == "mock":
        return MockASRProvider()
    elif name == "thirdparty":
        return ThirdPartyASRProvider()
    elif name == "local":
        return LocalPuxianASRProvider()
    else:
        # 未知 provider 名称 → 安全降级到 Mock
        return MockASRProvider()
