"""数据集多格式导出工具 — Phase 5。

支持导出格式：
  1. jsonl   — 每行一个 JSON 对象（通用 SFT 格式）
  2. csv     — CSV 表格（audio_path, text, duration, confidence）
  3. manifest — DashScope 微调 manifest 格式
  4. kaldi   — Kaldi 风格（wav.scp + text 文件）

导出结构：
  training_data/exports/{dataset_id}/{export_id}/
    train.jsonl (或 train.csv / manifest.json / wav.scp + text)
    metadata.json          — 导出元信息
    audio/ (可选)          — 复制的音频文件（copy_audio=true 时）
"""

import csv
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from asr.dataset_store import (
    _load_samples, _load_metadata,
    TRAINING_DATA_DIR, DATASETS_DIR,
    STATUS_PENDING, STATUS_ANNOTATED, STATUS_VERIFIED,
)

# ============================================================
# 常量
# ============================================================

EXPORTS_DIR = TRAINING_DATA_DIR / "exports"

SUPPORTED_FORMATS = ["jsonl", "csv", "manifest", "kaldi"]


# ============================================================
# 导出主函数
# ============================================================

def export_dataset(
    dataset_id: str,
    format: str = "jsonl",
    copy_audio: bool = False,
    status_filter: Optional[str] = None,
    min_confidence: Optional[float] = None,
) -> dict:
    """
    导出数据集为指定格式。

    Args:
        dataset_id: 数据集 ID
        format: 导出格式（jsonl / csv / manifest / kaldi）
        copy_audio: 是否复制音频文件到导出目录
        status_filter: 按标注状态过滤
        min_confidence: 最低置信度过滤

    Returns:
        {
            "export_id": str,
            "format": str,
            "path": str,
            "sample_count": int,
            "audio_copied": int,
            "created_at": str,
        }
    """
    if format not in SUPPORTED_FORMATS:
        raise ValueError(f"不支持的格式: {format}，支持: {SUPPORTED_FORMATS}")

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
    export_id = f"exp-{uuid.uuid4().hex[:12]}"
    export_dir = EXPORTS_DIR / dataset_id / export_id
    export_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    audio_copied = 0

    # 复制音频文件（可选）
    if copy_audio:
        audio_dir = export_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        for s in samples:
            src = Path(s.get("audio_path", ""))
            if src.exists():
                dst = audio_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                    audio_copied += 1
                # 更新样本中的音频路径为相对路径
                s["audio_path"] = f"audio/{src.name}"

    # 按格式导出
    if format == "jsonl":
        _export_jsonl(export_dir, samples, metadata)
    elif format == "csv":
        _export_csv(export_dir, samples, metadata)
    elif format == "manifest":
        _export_manifest(export_dir, samples, metadata)
    elif format == "kaldi":
        _export_kaldi(export_dir, samples, metadata)

    # 写导出元信息
    export_meta = {
        "export_id": export_id,
        "dataset_id": dataset_id,
        "dataset_name": metadata.get("name", ""),
        "format": format,
        "sample_count": len(samples),
        "audio_copied": audio_copied,
        "copy_audio": copy_audio,
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
        "audio_copied": audio_copied,
        "created_at": now,
    }


# ============================================================
# 各格式导出实现
# ============================================================

def _export_jsonl(export_dir: Path, samples: list[dict], dataset_meta: dict):
    """
    JSONL 格式导出。

    每行一个 JSON 对象：
    {"audio": "audio/xxx.webm", "text": "春草闯堂", "duration": 4.0, "confidence": 0.9}
    """
    output_file = export_dir / "train.jsonl"
    with open(output_file, "w", encoding="utf-8") as f:
        for s in samples:
            entry = {
                "audio": s.get("audio_path", ""),
                "text": s.get("corrected_text") or s.get("normalized_text") or s.get("original_text", ""),
                "duration": round(s.get("duration_ms", 0) / 1000, 2),
                "confidence": s.get("confidence", 0.0),
                "annotation_status": s.get("annotation_status", "pending"),
                "provider": s.get("provider", ""),
                "accent": s.get("accent"),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _export_csv(export_dir: Path, samples: list[dict], dataset_meta: dict):
    """
    CSV 格式导出。

    列：audio_path, text, duration_ms, confidence, annotation_status, provider, accent
    """
    output_file = export_dir / "train.csv"
    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "audio_path", "text", "duration_ms", "confidence",
            "annotation_status", "provider", "accent"
        ])
        for s in samples:
            writer.writerow([
                s.get("audio_path", ""),
                s.get("corrected_text") or s.get("normalized_text") or s.get("original_text", ""),
                s.get("duration_ms", 0),
                s.get("confidence", 0.0),
                s.get("annotation_status", "pending"),
                s.get("provider", ""),
                s.get("accent", ""),
            ])


def _export_manifest(export_dir: Path, samples: list[dict], dataset_meta: dict):
    """
    DashScope 微调 manifest 格式。

    每行一个 JSON 对象：
    {"input_audio": "audio/xxx.webm", "output_text": "春草闯堂"}
    """
    output_file = export_dir / "manifest.jsonl"
    with open(output_file, "w", encoding="utf-8") as f:
        for s in samples:
            entry = {
                "input_audio": s.get("audio_path", ""),
                "output_text": s.get("corrected_text") or s.get("normalized_text") or s.get("original_text", ""),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _export_kaldi(export_dir: Path, samples: list[dict], dataset_meta: dict):
    """
    Kaldi 风格导出。

    生成两个文件：
    - wav.scp: recording_id audio_path
    - text: recording_id transcript
    """
    wav_scp_file = export_dir / "wav.scp"
    text_file = export_dir / "text"

    with open(wav_scp_file, "w", encoding="utf-8") as wf, \
         open(text_file, "w", encoding="utf-8") as tf:
        for s in samples:
            rec_id = s.get("sample_id", "")
            audio_path = s.get("audio_path", "")
            text = s.get("corrected_text") or s.get("normalized_text") or s.get("original_text", "")
            wf.write(f"{rec_id} {audio_path}\n")
            tf.write(f"{rec_id} {text}\n")


# ============================================================
# 导出列表与下载
# ============================================================

def list_exports(dataset_id: str) -> list[dict]:
    """列出数据集的所有导出记录。"""
    ds_export_dir = EXPORTS_DIR / dataset_id
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


def get_export_path(dataset_id: str, export_id: str) -> Optional[Path]:
    """获取导出目录路径。"""
    export_dir = EXPORTS_DIR / dataset_id / export_id
    if export_dir.exists():
        return export_dir
    return None
