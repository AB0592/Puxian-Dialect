#!/usr/bin/env python3
"""
方言语音识别模块 — SenseVoice（优先）+ Whisper（回退）

SenseVoice 对莆仙话等方言识别更准。模型文件已下载到本地缓存，
不再走 funasr AutoModel 自动下载（网络不稳定）。

Whisper 支持两种加载方式：
  1. openai-whisper 包（原版 Whisper）
  2. transformers 库（HuggingFace 格式模型）

注意：莆仙话场景使用 SenseVoice 原始模型（支持 cpx 方言），
不使用微调模型。SenseVoice 失败则返回空文本让前端降级。
"""
import os
import json
import time
from pathlib import Path
from typing import Optional

# Whisper (openai-whisper 包)
try:
    import whisper
    WHISPER_OPENAI_AVAILABLE = True
except ImportError:
    WHISPER_OPENAI_AVAILABLE = False

# Transformers（用于加载 Whisper 模型）
try:
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

# 综合判断 Whisper 是否可用
WHISPER_AVAILABLE = WHISPER_OPENAI_AVAILABLE or TRANSFORMERS_AVAILABLE

# SenseVoice 底层库
try:
    from funasr import AutoModel
    SENSEVOICE_AVAILABLE = True
except ImportError:
    SENSEVOICE_AVAILABLE = False

# modelscope 下载工具（用于获取本地路径）
try:
    from modelscope.hub.snapshot_download import snapshot_download
    MODELSCOPE_AVAILABLE = True
except ImportError:
    MODELSCOPE_AVAILABLE = False

MODEL_NAME = "iic/SenseVoiceSmall"
MODEL_CACHE = Path("/Users/sagaai/.cache/modelscope")

LANG_TAGS = {
    "canton":   "yue",
    "minnan":   "nan",
    "putian":   "cpx",
    "sichuan":  "zh",
    "shanghai": "wuu",
    "hakka":    "hak",
    "mandarin": "zh",
}

# 模型实例（全局缓存，只加载一次）
_sensevoice_model = None
_whisper_model = None


# ============================================================
# SenseVoice 本地加载
# ============================================================

def _sensevoice_model_path() -> Optional[Path]:
    """查找本地缓存的 SenseVoice 模型路径"""
    candidates = [
        MODEL_CACHE / "models" / "iic" / "SenseVoiceSmall",
        MODEL_CACHE / "hub" / "models" / "iic" / "SenseVoiceSmall",
        Path("/Users/sagaai/.hermes/profiles/dialect-bot/home/.cache")
        / "modelscope" / "hub" / "models" / "iic" / "SenseVoiceSmall",
    ]
    for path in candidates:
        model_pt = path / "model.pt"
        if model_pt.exists() and model_pt.stat().st_size > 800_000_000:
            print(f"  ✓ SenseVoice 模型: {path}")
            return path
    return None


def _get_sensevoice():
    """获取 SenseVoice 模型（本地加载，不触发网络下载）"""
    global _sensevoice_model

    if _sensevoice_model is not None:
        return _sensevoice_model

    if not SENSEVOICE_AVAILABLE:
        print("⚠ funasr 未安装")
        return None

    model_dir = _sensevoice_model_path()
    if model_dir is None:
        print("⚠ SenseVoice 模型文件未找到（需 893MB）")
        return None

    print(f"🔄 加载 SenseVoice...", flush=True)
    try:
        start = time.time()
        # 直接指定本地路径，不走 modelscope 下载
        _sensevoice_model = AutoModel(
            model=str(model_dir),
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device="cpu",
            disable_update=True,
        )
        elapsed = time.time() - start
        print(f"✅ SenseVoice 加载完成 ({elapsed:.1f}秒)", flush=True)
    except Exception as e:
        print(f"⚠ SenseVoice 加载失败: {e}", flush=True)
        return None

    return _sensevoice_model


def _sensevoice_recognize(audio_path: str, lang_hint: str) -> dict:
    model = _get_sensevoice()
    if model is None:
        return None

    try:
        result = model.generate(
            input=audio_path,
            language=lang_hint,
            use_itn=True,
            ban_emo_unk=False,
        )
        if isinstance(result, list) and len(result) > 0:
            text = result[0].get("text", "")
            detected_lang = result[0].get("language", lang_hint)
        elif isinstance(result, dict):
            text = result.get("text", "")
            detected_lang = result.get("language", lang_hint)
        else:
            text = str(result) if result else ""
            detected_lang = "unknown"
        return {"text": _clean_sensevoice(text), "lang": detected_lang, "engine": "sensevoice"}
    except Exception as e:
        print(f"⚠ SenseVoice 推理失败: {e}")
        return None


def _clean_sensevoice(text: str) -> str:
    """清理 SenseVoice 输出的特殊标记"""
    import re
    # 移除 <|xxx|> 格式的标记
    text = re.sub(r'<\|[^|]+\|>', '', text)
    return text.strip()


# ============================================================
# Whisper（回退）— 支持 openai-whisper 和 transformers 两种方式
# ============================================================

WHISPER_MODEL_SIZE = "small"


def _get_whisper():
    """加载 Whisper 模型（优先 openai-whisper，回退 transformers）。"""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    # 方式 1: openai-whisper 包
    if WHISPER_OPENAI_AVAILABLE:
        print(f"🔄 加载 Whisper {WHISPER_MODEL_SIZE} 模型 (openai-whisper)...")
        try:
            _whisper_model = {"type": "openai", "model": whisper.load_model(WHISPER_MODEL_SIZE)}
            print("✅ Whisper 加载完成 (openai-whisper)")
            return _whisper_model
        except Exception as e:
            print(f"⚠ openai-whisper 加载失败: {e}")

    # 方式 2: transformers
    if TRANSFORMERS_AVAILABLE:
        return _get_whisper_transformers()

    return None


def _get_whisper_transformers():
    """使用 transformers 加载 Whisper 基础模型。"""
    global _whisper_model

    import torch

    model_name = f"openai/whisper-{WHISPER_MODEL_SIZE}"
    print(f"🔄 加载 Whisper 模型 (transformers): {model_name}")

    try:
        start = time.time()
        device = "mps" if torch.backends.mps.is_available() else "cpu"

        model = WhisperForConditionalGeneration.from_pretrained(model_name)
        processor = WhisperProcessor.from_pretrained(model_name)

        model.to(device)
        model.eval()

        _whisper_model = {"type": "transformers", "model": model, "processor": processor, "device": device}
        elapsed = time.time() - start
        print(f"✅ Whisper 加载完成 ({elapsed:.1f}秒, device={device})", flush=True)
    except Exception as e:
        print(f"⚠ Whisper (transformers) 加载失败: {e}", flush=True)
        return None

    return _whisper_model


def _whisper_recognize(audio_path: str, lang_hint: str) -> dict:
    model_info = _get_whisper()
    if model_info is None:
        return {"text": "", "lang": "unknown", "engine": "whisper", "error": "Whisper 未安装"}

    lang_map = {"zh": "zh", "yue": "zh", "nan": "zh", "cpx": "zh",
                "wuu": "zh", "hak": "zh"}
    whisper_lang = lang_map.get(lang_hint, "zh")

    # 分派到对应的识别函数
    if model_info["type"] == "openai":
        return _whisper_recognize_openai(model_info["model"], audio_path, whisper_lang)
    else:
        return _whisper_recognize_transformers(model_info, audio_path, whisper_lang)


def _whisper_recognize_openai(model, audio_path: str, whisper_lang: str) -> dict:
    """使用 openai-whisper 包识别。"""
    result = model.transcribe(audio_path, language=whisper_lang,
                              task="transcribe", fp16=False)
    text = result.get("text", "").strip()
    detected = result.get("language", whisper_lang)
    return {"text": text, "lang": detected, "engine": "whisper"}


def _whisper_recognize_transformers(model_info: dict, audio_path: str, whisper_lang: str) -> dict:
    """使用 transformers 库识别。"""
    import librosa
    import torch

    model = model_info["model"]
    processor = model_info["processor"]
    device = model_info["device"]

    try:
        # 加载音频（16kHz 单声道）
        audio, sr = librosa.load(audio_path, sr=16000)

        # 转换为 mel 特征
        input_features = processor(audio, sampling_rate=16000, return_tensors="pt").input_features
        input_features = input_features.to(device)

        # 强制语言和任务
        forced_decoder_ids = processor.get_decoder_prompt_ids(language=whisper_lang, task="transcribe")

        with torch.no_grad():
            # 使用 input_features= 关键字传参
            try:
                predicted_ids = model.generate(
                    input_features=input_features,
                    forced_decoder_ids=forced_decoder_ids,
                    max_new_tokens=440,
                )
            except TypeError:
                predicted_ids = model.generate(
                    inputs=input_features,
                    forced_decoder_ids=forced_decoder_ids,
                    max_new_tokens=440,
                )

        text = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0].strip()
        return {"text": text, "lang": whisper_lang, "engine": "whisper"}
    except Exception as e:
        print(f"⚠ Whisper (transformers) 推理失败: {e}")
        return {"text": "", "lang": whisper_lang, "engine": "whisper", "error": str(e)}


# ============================================================
# 统一入口
# ============================================================

def recognize(audio_path: str, lang: str = "auto") -> dict:
    if not os.path.exists(audio_path):
        return {"text": "", "lang": "unknown", "error": f"文件不存在: {audio_path}"}

    lang_hint = LANG_TAGS.get(lang, "auto")
    print(f"🎤 识别音频: {os.path.basename(audio_path)}  方言: {lang}")

    # 0. 莆仙话：使用 SenseVoice 原始模型（支持 cpx 方言），不使用微调模型
    is_puxian = lang in ("putian", "cpx") or lang_hint == "cpx"
    if is_puxian:
        if _sensevoice_model_path() is not None:
            result = _sensevoice_recognize(audio_path, "cpx")
            if result and result["text"]:
                print(f"  → SenseVoice (莆仙话): {result['text']}")
                return result
            print(f"  → SenseVoice 未识别到莆仙话，返回空文本让前端降级")
        else:
            print(f"  → SenseVoice 模型未找到，返回空文本让前端降级")
        # Whisper 不支持莆仙话方言，返回空文本让前端降级到第 1 层 FC
        return {"text": "", "lang": "unknown", "engine": "none"}

    # 1. 优先 SenseVoice（方言更准）
    if _sensevoice_model_path() is not None:
        result = _sensevoice_recognize(audio_path, lang_hint)
        if result and result["text"]:
            print(f"  → SenseVoice: {result['text']}")
            return result

    # 2. Whisper 回退（普通话及其他语言）
    print("  → 使用 Whisper")
    result = _whisper_recognize(audio_path, lang_hint)
    print(f"  → Whisper: {result['text']}")
    return result


def recognize_file(audio_path: str, lang: str = "auto") -> str:
    result = recognize(audio_path, lang)
    return result["text"]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 dialect_asr.py <音频文件> [方言代码]")
        print("方言代码: canton/minnan/putian/sichuan/shanghai/hakka/mandarin/auto")
        sys.exit(1)

    audio = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else "auto"
    result = recognize(audio, lang)
    print(json.dumps(result, ensure_ascii=False, indent=2))
