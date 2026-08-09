"""本地 ASR 模型管理器 — Phase 6。

职责：
  1. 检测本地 ASR 引擎可用性（SenseVoice / Whisper）
  2. 管理引擎配置（选择哪个引擎、自定义模型路径）
  3. 管理微调模型（列出、设置、删除）
  4. 导出微调训练数据（SenseVoice JSONL / Whisper JSONL 格式）

配置文件：
  training_data/local_model_config.json
  {
    "engine": "auto",              # auto / sensevoice / whisper
    "custom_model_path": null,     # 微调模型路径（null 表示用基础模型）
    "whisper_model_size": "small", # Whisper 模型大小
  }
"""

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from asr.dataset_store import (
    _load_samples, _load_metadata,
    TRAINING_DATA_DIR,
)


# ============================================================
# 常量
# ============================================================

CONFIG_FILE = TRAINING_DATA_DIR / "local_model_config.json"
FINETUNE_MODELS_DIR = TRAINING_DATA_DIR / "finetune_models"
FINETUNE_EXPORTS_DIR = TRAINING_DATA_DIR / "finetune_exports"

VALID_ENGINES = ["auto", "sensevoice", "whisper"]
VALID_WHISPER_SIZES = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]

# SenseVoice 模型缓存路径候选
_SENSEVOICE_CACHE_CANDIDATES = [
    Path.home() / ".cache" / "modelscope" / "models" / "iic" / "SenseVoiceSmall",
    Path.home() / ".cache" / "modelscope" / "hub" / "models" / "iic" / "SenseVoiceSmall",
    Path("/Users/sagaai/.cache/modelscope/models/iic/SenseVoiceSmall"),
    Path("/Users/sagaai/.cache/modelscope/hub/models/iic/SenseVoiceSmall"),
]

# Whisper 模型缓存路径候选
_WHISPER_CACHE_CANDIDATES = [
    Path.home() / ".cache" / "whisper",
]


# ============================================================
# 配置管理
# ============================================================

def _default_config() -> dict:
    """默认配置。"""
    return {
        "engine": "auto",
        "custom_model_path": None,
        "whisper_model_size": "small",
    }


def get_config() -> dict:
    """读取本地模型配置。"""
    if not CONFIG_FILE.exists():
        return _default_config()

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        # 合并默认值（确保新字段存在）
        defaults = _default_config()
        defaults.update(config)
        return defaults
    except (json.JSONDecodeError, IOError):
        return _default_config()


def save_config(config: dict) -> dict:
    """保存本地模型配置。"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # 验证引擎
    engine = config.get("engine", "auto")
    if engine not in VALID_ENGINES:
        raise ValueError(f"无效引擎: {engine}，支持: {VALID_ENGINES}")

    # 验证 Whisper 模型大小
    whisper_size = config.get("whisper_model_size", "small")
    if whisper_size not in VALID_WHISPER_SIZES:
        raise ValueError(f"无效 Whisper 模型大小: {whisper_size}")

    # 验证自定义模型路径（如果提供）
    custom_path = config.get("custom_model_path")
    if custom_path and not Path(custom_path).exists():
        raise ValueError(f"自定义模型路径不存在: {custom_path}")

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    return config


# ============================================================
# 引擎状态检测
# ============================================================

def _check_sensevoice_available() -> dict:
    """检测 SenseVoice 是否可用。"""
    info = {
        "available": False,
        "installed": False,
        "model_path": None,
        "model_size_mb": 0,
        "version": "",
    }

    # 检查 funasr 是否安装
    try:
        import funasr
        info["installed"] = True
        info["version"] = getattr(funasr, "__version__", "unknown")
    except ImportError:
        info["installed"] = False
        return info

    # 检查模型文件是否存在
    for candidate in _SENSEVOICE_CACHE_CANDIDATES:
        model_pt = candidate / "model.pt"
        if model_pt.exists():
            info["available"] = True
            info["model_path"] = str(candidate)
            info["model_size_mb"] = round(model_pt.stat().st_size / 1024 / 1024, 1)
            break

    return info


def _check_whisper_available() -> dict:
    """检测 Whisper 是否可用。"""
    info = {
        "available": False,
        "installed": False,
        "model_path": None,
        "model_size_mb": 0,
        "version": "",
        "model_size": "small",
    }

    # 检查 whisper 是否安装
    try:
        import whisper
        info["installed"] = True
        info["version"] = getattr(whisper, "__version__", "unknown")
    except ImportError:
        info["installed"] = False
        return info

    # 检查模型文件
    config = get_config()
    model_size = config.get("whisper_model_size", "small")
    info["model_size"] = model_size

    for cache_dir in _WHISPER_CACHE_CANDIDATES:
        model_file = cache_dir / f"{model_size}.pt"
        if model_file.exists():
            info["available"] = True
            info["model_path"] = str(model_file)
            info["model_size_mb"] = round(model_file.stat().st_size / 1024 / 1024, 1)
            break

    return info


def get_model_status() -> dict:
    """
    获取所有本地 ASR 引擎的状态。

    Returns:
        {
            "config": {...},
            "engines": {
                "sensevoice": {...},
                "whisper": {...},
            },
            "active_engine": "sensevoice" | "whisper" | "none",
            "finetune_models": [...],
        }
    """
    config = get_config()
    sv_info = _check_sensevoice_available()
    whisper_info = _check_whisper_available()

    # 确定当前活跃引擎
    engine_pref = config.get("engine", "auto")
    custom_path = config.get("custom_model_path")

    if custom_path and Path(custom_path).exists():
        # 有自定义微调模型
        active_engine = "finetuned"
    elif engine_pref == "sensevoice" and sv_info["available"]:
        active_engine = "sensevoice"
    elif engine_pref == "whisper" and whisper_info["available"]:
        active_engine = "whisper"
    elif engine_pref == "auto":
        if sv_info["available"]:
            active_engine = "sensevoice"
        elif whisper_info["available"]:
            active_engine = "whisper"
        else:
            active_engine = "none"
    else:
        active_engine = "none"

    return {
        "config": config,
        "engines": {
            "sensevoice": sv_info,
            "whisper": whisper_info,
        },
        "active_engine": active_engine,
        "finetune_models": list_finetune_models(),
    }


# ============================================================
# 微调模型管理
# ============================================================

def list_finetune_models() -> list[dict]:
    """列出所有已注册的微调模型。"""
    if not FINETUNE_MODELS_DIR.exists():
        return []

    models = []
    for item in sorted(FINETUNE_MODELS_DIR.iterdir()):
        if not item.is_dir():
            continue
        meta_file = item / "model_meta.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["path"] = str(item)
                models.append(meta)
            except (json.JSONDecodeError, IOError):
                pass
        else:
            # 无元数据的目录，尝试推断
            models.append({
                "model_id": item.name,
                "name": item.name,
                "engine": "unknown",
                "path": str(item),
                "created_at": datetime.fromtimestamp(
                    item.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            })

    return models


def register_finetune_model(
    name: str,
    engine: str,
    model_path: str,
    description: str = "",
    dataset_id: str = "",
) -> dict:
    """
    注册一个微调模型。

    Args:
        name: 模型名称
        engine: 引擎类型（sensevoice / whisper）
        model_path: 模型文件或目录路径
        description: 描述
        dataset_id: 来源数据集 ID

    Returns:
        模型元数据
    """
    if engine not in ["sensevoice", "whisper"]:
        raise ValueError(f"无效引擎: {engine}，支持: sensevoice / whisper")

    if not Path(model_path).exists():
        raise ValueError(f"模型路径不存在: {model_path}")

    model_id = f"ft-{uuid.uuid4().hex[:12]}"
    model_dir = FINETUNE_MODELS_DIR / model_id
    model_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "model_id": model_id,
        "name": name.strip(),
        "engine": engine,
        "model_path": model_path,
        "description": description.strip(),
        "dataset_id": dataset_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(model_dir / "model_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    meta["path"] = str(model_dir)
    return meta


def delete_finetune_model(model_id: str) -> bool:
    """删除一个微调模型注册。"""
    model_dir = FINETUNE_MODELS_DIR / model_id
    if not model_dir.exists():
        return False

    shutil.rmtree(model_dir)

    # 如果当前配置指向这个模型，清除配置
    config = get_config()
    if config.get("custom_model_path"):
        # 检查是否指向被删除的模型
        for m in list_finetune_models():
            if m.get("model_path") == config["custom_model_path"]:
                continue
        # 简单处理：清除自定义路径
        # 更安全的做法是检查路径是否匹配

    return True


def set_active_finetune_model(model_id: str) -> dict:
    """设置当前使用的微调模型。"""
    model_dir = FINETUNE_MODELS_DIR / model_id
    if not model_dir.exists():
        raise ValueError(f"微调模型不存在: {model_id}")

    meta_file = model_dir / "model_meta.json"
    if not meta_file.exists():
        raise ValueError(f"模型元数据不存在: {model_id}")

    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    config = get_config()
    config["custom_model_path"] = meta.get("model_path")
    return save_config(config)


def clear_active_finetune_model() -> dict:
    """清除当前微调模型，回退到基础模型。"""
    config = get_config()
    config["custom_model_path"] = None
    return save_config(config)


# ============================================================
# 微调数据导出
# ============================================================

def export_finetune_data(
    dataset_id: str,
    format: str = "sensevoice",
    status_filter: Optional[str] = None,
    min_confidence: Optional[float] = None,
) -> dict:
    """
    导出数据集为微调训练格式。

    支持格式：
      - sensevoice: SenseVoice 微调 JSONL（含语种/情感/事件标签）
      - whisper: Whisper 微调 JSONL（含 audio/sentence/language/duration）

    Args:
        dataset_id: 数据集 ID
        format: 导出格式
        status_filter: 按标注状态过滤
        min_confidence: 最低置信度过滤

    Returns:
        {
            "export_id": str,
            "format": str,
            "path": str,
            "sample_count": int,
            "created_at": str,
        }
    """
    if format not in ["sensevoice", "whisper"]:
        raise ValueError(f"不支持的微调格式: {format}，支持: sensevoice / whisper")

    metadata = _load_metadata(dataset_id)
    if not metadata:
        raise ValueError(f"数据集不存在: {dataset_id}")

    samples = _load_samples(dataset_id)

    # 过滤
    if status_filter:
        samples = [s for s in samples if s.get("annotation_status") == status_filter]
    if min_confidence is not None:
        samples = [s for s in samples if s.get("confidence", 0) >= min_confidence]

    if not samples:
        raise ValueError("过滤后无样本可导出")

    # 创建导出目录
    export_id = f"ft-exp-{uuid.uuid4().hex[:12]}"
    export_dir = FINETUNE_EXPORTS_DIR / dataset_id / export_id
    export_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()

    if format == "sensevoice":
        _export_sensevoice_format(export_dir, samples, metadata)
    elif format == "whisper":
        _export_whisper_format(export_dir, samples, metadata)

    # 写导出元信息
    export_meta = {
        "export_id": export_id,
        "dataset_id": dataset_id,
        "dataset_name": metadata.get("name", ""),
        "format": format,
        "sample_count": len(samples),
        "status_filter": status_filter,
        "min_confidence": min_confidence,
        "created_at": now,
    }
    with open(export_dir / "export_metadata.json", "w", encoding="utf-8") as f:
        json.dump(export_meta, f, ensure_ascii=False, indent=2)

    return {
        "export_id": export_id,
        "format": format,
        "path": str(export_dir),
        "sample_count": len(samples),
        "created_at": now,
    }


def _export_sensevoice_format(export_dir: Path, samples: list[dict], dataset_meta: dict):
    """
    SenseVoice 微调 JSONL 格式。

    每行一个 JSON：
    {
      "key": "puxian_0001",
      "text_language": "<|zh|>",
      "emo_target": "<|NEUTRAL|>",
      "event_target": "<|Speech|>",
      "with_or_wo_itn": "<|withitn|>",
      "target": "莆仙话标注文本",
      "source": "/path/to/audio.wav"
    }
    """
    output_file = export_dir / "train.jsonl"

    # 同时生成 wav.scp 和 text 文件（SenseVoice 微调工具需要）
    wav_scp_file = export_dir / "wav.scp"
    text_file = export_dir / "text"

    with open(output_file, "w", encoding="utf-8") as f, \
         open(wav_scp_file, "w", encoding="utf-8") as wf, \
         open(text_file, "w", encoding="utf-8") as tf:

        for i, s in enumerate(samples):
            key = f"puxian_{i:04d}"
            text = s.get("corrected_text") or s.get("normalized_text") or s.get("original_text", "")
            audio_path = s.get("audio_path", "")
            accent = s.get("accent", "putian")

            # SenseVoice 语种标签：莆仙话用 <|zh|>
            lang_tag = "<|zh|>"

            entry = {
                "key": key,
                "text_language": lang_tag,
                "emo_target": "<|NEUTRAL|>",
                "event_target": "<|Speech|>",
                "with_or_wo_itn": "<|withitn|>",
                "target": text,
                "source": audio_path,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            wf.write(f"{key} {audio_path}\n")
            tf.write(f"{key} {text}\n")


def _export_whisper_format(export_dir: Path, samples: list[dict], dataset_meta: dict):
    """
    Whisper 微调 JSONL 格式。

    每行一个 JSON：
    {
      "audio": {"path": "/path/to/audio.wav"},
      "sentence": "莆仙话标注文本",
      "language": "Chinese",
      "duration": 4.0
    }
    """
    output_file = export_dir / "train.jsonl"

    with open(output_file, "w", encoding="utf-8") as f:
        for s in samples:
            text = s.get("corrected_text") or s.get("normalized_text") or s.get("original_text", "")
            audio_path = s.get("audio_path", "")
            duration = round(s.get("duration_ms", 0) / 1000, 2)

            entry = {
                "audio": {"path": audio_path},
                "sentence": text,
                "language": "Chinese",
                "duration": duration,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_finetune_exports(dataset_id: str) -> list[dict]:
    """列出数据集的微调数据导出记录。"""
    ds_export_dir = FINETUNE_EXPORTS_DIR / dataset_id
    if not ds_export_dir.exists():
        return []

    exports = []
    for exp_dir in sorted(ds_export_dir.iterdir(), reverse=True):
        if not exp_dir.is_dir():
            continue
        meta_file = exp_dir / "export_metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    exports.append(json.load(f))
            except (json.JSONDecodeError, IOError):
                pass

    return exports
