#!/usr/bin/env python3
"""
方言语音识别模块 — SenseVoice（优先）+ Whisper（回退，莆仙话除外）

SenseVoice 对莆仙话等方言识别更准。模型文件已下载到本地缓存，
不再走 funasr AutoModel 自动下载（网络不稳定）。

莆仙话（putian）禁用 Whisper 回退：SenseVoice 失败时返回空文本，
供前端降级到下一层 ASR。

Whisper 支持两种加载方式：
  1. openai-whisper 包（原版 Whisper）
  2. transformers 库（仅加载基础模型，不加载微调模型）
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

# PEFT（LoRA 适配器加载）
try:
    from peft import PeftConfig, PeftModel
    PEFT_AVAILABLE = True
except ImportError:
    PEFT_AVAILABLE = False

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
_finetuned_model = None  # 自训练 Whisper LoRA 模型


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


def _get_finetune_model_path() -> Optional[str]:
    """从 local_model_config.json 获取微调模型路径。"""
    config_path = Path(__file__).parent.parent / "training_data" / "local_model_config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        path = config.get("custom_model_path")
        if path and Path(path).exists():
            return path
    except (json.JSONDecodeError, IOError):
        pass
    return None


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
# 自训练 Whisper LoRA 模型（莆仙话优先引擎）
# ============================================================

# 保存原始 forward 方法（仅修补一次）
_original_whisper_forward = None


def patch_whisper_for_peft():
    """修补 WhisperForConditionalGeneration.forward 以兼容 PEFT。

    PEFT 的 PeftModelForSeq2SeqLM.forward() 使用 'input_ids' 作为参数名，
    但 Whisper 模型使用 'input_features'。此函数将 input_ids 从 **kwargs 中
    提取出来，作为 input_features 使用，避免参数冲突。

    必须在加载 LoRA 模型前调用。
    """
    global _original_whisper_forward

    if _original_whisper_forward is not None:
        return  # 已修补过

    if not TRANSFORMERS_AVAILABLE:
        return

    _original_whisper_forward = WhisperForConditionalGeneration.forward

    def patched_forward(
        self,
        input_features=None,
        attention_mask=None,
        decoder_input_ids=None,
        decoder_attention_mask=None,
        encoder_outputs=None,
        past_key_values=None,
        decoder_inputs_embeds=None,
        decoder_position_ids=None,
        labels=None,
        use_cache=None,
        **kwargs,
    ):
        # PEFT 通过 input_ids 传递 Whisper 的 input_features
        if input_features is None and "input_ids" in kwargs:
            input_features = kwargs.pop("input_ids")

        # 移除 PEFT 传递的但 Whisper 不需要的参数
        for drop_key in ("inputs_embeds", "task_ids"):
            kwargs.pop(drop_key, None)

        return _original_whisper_forward(
            self,
            input_features=input_features,
            attention_mask=attention_mask,
            decoder_input_ids=decoder_input_ids,
            decoder_attention_mask=decoder_attention_mask,
            encoder_outputs=encoder_outputs,
            past_key_values=past_key_values,
            decoder_inputs_embeds=decoder_inputs_embeds,
            decoder_position_ids=decoder_position_ids,
            labels=labels,
            use_cache=use_cache,
            **kwargs,
        )

    WhisperForConditionalGeneration.forward = patched_forward
    print("✅ 已修补 Whisper forward 以兼容 PEFT (input_ids → input_features)", flush=True)


def _find_lora_adapter() -> Optional[str]:
    """查找自训练 LoRA 适配器路径。

    搜索顺序：
      1. training_data/lora_output_v2/  （v2: r=32, 早停优化）
      2. training_data/finetune_workspace/lora_output/
      3. training_data/lora_output/    （v1: r=16, 原始训练）
      4. 环境变量 LORA_ADAPTER_PATH
      5. training_data/local_model_config.json 中的 custom_model_path
    """
    # 候选路径
    project_root = Path(__file__).parent.parent
    candidates = [
        project_root / "training_data" / "lora_output_v2",
        project_root / "training_data" / "finetune_workspace" / "lora_output",
        project_root / "training_data" / "lora_output",
    ]

    # 环境变量
    env_path = os.environ.get("LORA_ADAPTER_PATH", "")
    if env_path:
        candidates.append(Path(env_path))

    # local_model_config.json
    config_path = project_root / "training_data" / "local_model_config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            custom_path = config.get("custom_model_path", "")
            if custom_path:
                candidates.append(Path(custom_path))
        except (json.JSONDecodeError, IOError):
            pass

    for path in candidates:
        adapter_config = path / "adapter_config.json"
        adapter_model = path / "adapter_model.safetensors"
        if adapter_config.exists() and adapter_model.exists():
            print(f"  ✓ LoRA 适配器: {path}", flush=True)
            return str(path)

    return None


def _get_finetuned_whisper():
    """加载自训练 Whisper LoRA 模型。

    引擎优先级：LoRA 适配器 > 无（返回 None 回退 SenseVoice）

    Returns:
        dict: {"model": PeftModel, "processor": WhisperProcessor, "device": str}
        None: 如果 LoRA 不可用
    """
    global _finetuned_model

    if _finetuned_model is not None:
        return _finetuned_model

    if not PEFT_AVAILABLE:
        print("⚠ peft 未安装，无法加载 LoRA 适配器", flush=True)
        return None

    if not TRANSFORMERS_AVAILABLE:
        print("⚠ transformers 未安装，无法加载 LoRA 适配器", flush=True)
        return None

    adapter_path = _find_lora_adapter()
    if adapter_path is None:
        print("ℹ 未找到 LoRA 适配器，莆仙话将使用 SenseVoice 回退", flush=True)
        return None

    print(f"🔄 加载自训练 Whisper LoRA 模型...", flush=True)
    try:
        import torch
        start = time.time()

        # 必须先 patch，否则 PEFT generate 会报错
        patch_whisper_for_peft()

        # 从 adapter_config.json 读取基础模型名
        peft_config = PeftConfig.from_pretrained(adapter_path)
        base_model_name = peft_config.base_model_name_or_path
        print(f"  基础模型: {base_model_name}", flush=True)

        # 加载基础模型
        base = WhisperForConditionalGeneration.from_pretrained(base_model_name)

        # 加载 LoRA 适配器
        model = PeftModel.from_pretrained(base, adapter_path)
        model.eval()

        # 加载处理器
        processor = WhisperProcessor.from_pretrained(base_model_name)

        # 设备选择
        device = "cpu"
        try:
            if torch.backends.mps.is_available():
                device = "mps"
        except (AttributeError, RuntimeError):
            pass
        model.to(device)

        _finetuned_model = {
            "model": model,
            "processor": processor,
            "device": device,
        }
        elapsed = time.time() - start
        print(f"✅ 自训练 Whisper LoRA 加载完成 ({elapsed:.1f}秒, device={device})", flush=True)

    except Exception as e:
        print(f"⚠ 自训练 Whisper LoRA 加载失败: {e}", flush=True)
        return None

    return _finetuned_model


def _finetuned_whisper_recognize(audio_path: str) -> dict:
    """使用自训练 Whisper LoRA 模型识别音频。

    Returns:
        dict: {"text": str, "lang": "zh", "engine": "finetuned-whisper"}
        None: 如果模型不可用
    """
    model_info = _get_finetuned_whisper()
    if model_info is None:
        return None

    try:
        import librosa
        import torch

        model = model_info["model"]
        processor = model_info["processor"]
        device = model_info["device"]

        # 加载音频（16kHz 单声道）
        audio, sr = librosa.load(audio_path, sr=16000)

        # 转换为 mel 特征
        input_features = processor(audio, sampling_rate=16000, return_tensors="pt").input_features
        input_features = input_features.to(device)

        # 强制语言和任务
        forced_decoder_ids = processor.get_decoder_prompt_ids(language="zh", task="transcribe")

        with torch.no_grad():
            predicted_ids = model.generate(
                input_features=input_features,
                forced_decoder_ids=forced_decoder_ids,
                max_new_tokens=440,
            )

        text = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0].strip()
        return {"text": text, "lang": "zh", "engine": "finetuned-whisper"}

    except Exception as e:
        print(f"⚠ 自训练 Whisper LoRA 推理失败: {e}", flush=True)
        return None


def _is_lora_output_quality(text: str) -> bool:
    """检查 LoRA 输出质量是否可接受。

    过滤以下低质量输出：
    - 空文本或过短（< 2 字符）
    - 重复字符（同一字符连续出现 3 次以上，如 "旋旋旋旋..."）
    - 中英文混杂（如 "几乎已 cut"）
    - 纯英文/数字（莆仙话识别应输出中文）
    """
    if not text or len(text.strip()) < 2:
        return False

    text = text.strip()

    # 检查重复字符（同一字符连续 3 次以上）
    for i in range(len(text) - 2):
        if text[i] == text[i + 1] == text[i + 2]:
            return False

    # 检查中英文混杂
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in text)
    has_latin = any(c.isalpha() and ord(c) < 128 for c in text)
    if has_chinese and has_latin:
        return False

    # 纯英文/数字（无中文字符）
    if not has_chinese:
        return False

    return True


# ============================================================
# 统一入口
# ============================================================

def recognize(audio_path: str, lang: str = "auto") -> dict:
    if not os.path.exists(audio_path):
        return {"text": "", "lang": "unknown", "error": f"文件不存在: {audio_path}"}

    lang_hint = LANG_TAGS.get(lang, "auto")
    print(f"🎤 识别音频: {os.path.basename(audio_path)}  方言: {lang}")

    # ── 莆仙话：LoRA 优先 → SenseVoice 回退 → 空文本降级 ──
    if lang == 'putian':
        # 1. 优先使用自训练 Whisper LoRA 模型
        lora_result = _finetuned_whisper_recognize(audio_path)
        if lora_result and lora_result["text"] and _is_lora_output_quality(lora_result["text"]):
            print(f"  → LoRA: {lora_result['text']}")
            return lora_result
        elif lora_result and lora_result["text"]:
            print(f"  → LoRA 输出质量不佳（重复/混杂），回退 SenseVoice: {lora_result['text']}")
        else:
            print("  → LoRA 不可用或无输出，回退 SenseVoice")

        # 2. 回退 SenseVoice 原始模型
        if _sensevoice_model_path() is not None:
            result = _sensevoice_recognize(audio_path, lang_hint)
            if result and result["text"]:
                print(f"  → SenseVoice: {result['text']}")
                return result

        # 3. 全部失败，返回空文本供前端降级
        print("  → 莆仙话所有引擎未识别到内容，返回空文本")
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
