#!/usr/bin/env python3
"""
方言语音识别模块 — 五层匹配管线（莆仙话）+ SenseVoice + Whisper 回退

莆仙话（putian）识别管线（五层匹配，顺序锁定不可打乱）：
  1. ASR 文字识别（SenseVoice 输出文本）
  2. 误识别映射（program_vocab.json 的 common_misrecognition 精确映射）
  3. 子串/编辑距离（aliases 子串包含，长度≥2；编辑距离 ≤2，手写 DP）
  4. 拼音模糊（program_pronunciation.json 的 char_pinyin + accent_rules.json 口音规则）
  5. DTW 音频匹配（audio_matcher.py MFCC DTW，最后一层兜底）
  每层命中即返回节目名并终止；未命中进入下一层；全部失败返回空文本。

其他方言：SenseVoice 优先 → Whisper 回退。
"""
import os
import json
import time
from pathlib import Path
from typing import Optional

# ============================================================
# 离线模式 — 防止 transformers 尝试联网下载模型
# ============================================================
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

# Whisper (openai-whisper 包)
try:
    import whisper
    WHISPER_OPENAI_AVAILABLE = True
except ImportError:
    WHISPER_OPENAI_AVAILABLE = False

# Transformers（用于加载微调后的 Whisper 模型）
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
MODEL_CACHE = Path.home() / ".cache" / "modelscope"

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
    # 支持 MODELSCOPE_CACHE 环境变量自定义缓存位置
    env_cache = os.environ.get('MODELSCOPE_CACHE', '')
    candidates = [
        MODEL_CACHE / "models" / "iic" / "SenseVoiceSmall",
        MODEL_CACHE / "hub" / "models" / "iic" / "SenseVoiceSmall",
    ]
    if env_cache:
        candidates.append(
            Path(env_cache) / "models" / "iic--SenseVoiceSmall" / "snapshots" / "master"
        )
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

    # 方式 2: transformers（支持微调模型）
    if TRANSFORMERS_AVAILABLE:
        return _get_whisper_transformers()

    return None


def _get_whisper_transformers():
    """使用 transformers 加载 Whisper 基础模型。"""
    global _whisper_model

    import torch

    # 始终使用基础模型，不加载微调模型
    model_name = f"openai/whisper-{WHISPER_MODEL_SIZE}"

    print(f"🔄 加载 Whisper 模型 (transformers, 基础模型): {model_name}")

    try:
        start = time.time()
        device = "mps" if torch.backends.mps.is_available() else "cpu"

        model = WhisperForConditionalGeneration.from_pretrained(model_name)
        processor = WhisperProcessor.from_pretrained(model_name)

        model.to(device)
        model.eval()

        _whisper_model = {"type": "transformers", "model": model, "processor": processor, "device": device}
        elapsed = time.time() - start
        print(f"✅ Whisper 加载完成 (基础模型, {elapsed:.1f}秒, device={device})", flush=True)
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
    """使用 transformers 库识别（支持微调模型）。"""
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
            predicted_ids = model.generate(
                input_features,
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

    # ── 莆仙话：五层匹配管线（SenseVoice→误识→子串/编辑→拼音→DTW）──
    if lang == 'putian':
        # 第 1 层：SenseVoice 文字识别
        asr_text = ""
        if _sensevoice_model_path() is not None:
            result = _sensevoice_recognize(audio_path, lang_hint)
            if result and result["text"]:
                asr_text = result["text"]
                print(f"  → L1 SenseVoice: {asr_text}")
            else:
                print("  → L1 SenseVoice 未识别到内容")
        else:
            print("  → L1 SenseVoice 模型未加载")

        # 第 2-5 层：五层匹配管线
        try:
            from asr.five_layer_pipeline import match_layers
            match_result = match_layers(asr_text, audio_path)
            if match_result["program_name"]:
                print(f"  → {match_result['layer']} 匹配: {match_result['program_name']} (score={match_result['score']:.3f})")
                return {
                    "text": match_result["program_name"],
                    "lang": lang_hint,
                    "engine": match_result["layer"],
                    "score": match_result["score"],
                    "asr_text": asr_text,
                }
            else:
                print(f"  → 五层管线全部未匹配 (asr_text='{asr_text}')")
        except Exception as e:
            print(f"  → 五层管线异常: {e}")
            # 异常时回退到 SenseVoice 原始输出
            if asr_text:
                return {"text": asr_text, "lang": lang_hint, "engine": "sensevoice"}

        # 全部失败，返回空文本供前端降级
        print("  → 莆仙话所有层级未匹配，返回空文本")
        return {"text": "", "lang": lang_hint, "engine": "sensevoice"}

    # ── 其他方言：SenseVoice 优先 → Whisper 回退 ──
    # 1. 优先 SenseVoice（方言更准）
    if _sensevoice_model_path() is not None:
        result = _sensevoice_recognize(audio_path, lang_hint)
        if result and result["text"]:
            print(f"  → SenseVoice: {result['text']}")
            return result

    # 2. 其他方言回退 Whisper（原始基础模型，不加载微调模型）
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
