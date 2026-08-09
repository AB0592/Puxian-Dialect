"""模型微调数据集存储与管理 — Phase 5。

职责：
  1. 创建/删除数据集（命名的训练样本集合）
  2. 从录音添加训练样本（音频路径 + 标注文本 + 元数据）
  3. 标注状态管理（待标注 / 已标注 / 已验证）
  4. 数据集统计与质量指标
  5. 样本查询与过滤

存储结构：
  training_data/
    datasets/
      {dataset_id}/
        metadata.json     — 数据集元数据
        samples.json      — 样本列表
    index.json            — 所有数据集索引（快速列表）

样本来源：
  Phase 3 录音存储中的录音 → 标注文本 → 加入数据集
  每个样本引用原始录音（user_id + recording_id），避免音频文件重复存储

样本格式（samples.json 中每条）：
  {
    "sample_id": "smp-xxx",
    "recording_id": "rec-xxx",
    "user_id": "user123",
    "audio_path": "user_data/user123/recordings/rec-xxx.webm",
    "audio_format": "webm",
    "audio_size": 12345,
    "duration_ms": 4000,
    "original_text": "春操",            — ASR 原始识别
    "normalized_text": "春草闯堂",       — 规范化结果
    "corrected_text": "春草闯堂",        — 人工标注/修正文本
    "annotation_status": "verified",    — pending / annotated / verified
    "confidence": 0.9,
    "provider": "thirdparty",
    "model_version": "paraformer-realtime-v2",
    "accent": "putian",
    "added_at": "2026-08-09T12:00:00+00:00",
    "annotated_at": null
  }
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ============================================================
# 常量
# ============================================================

# training_data 目录位于项目根目录
TRAINING_DATA_DIR = Path(__file__).parent.parent.parent / "training_data"
DATASETS_DIR = TRAINING_DATA_DIR / "datasets"
INDEX_FILE = TRAINING_DATA_DIR / "index.json"

# 标注状态
STATUS_PENDING = "pending"      # 待标注
STATUS_ANNOTATED = "annotated"  # 已标注
STATUS_VERIFIED = "verified"    # 已验证

VALID_STATUSES = [STATUS_PENDING, STATUS_ANNOTATED, STATUS_VERIFIED]

# 数据集状态
DATASET_STATUS_DRAFT = "draft"        # 草稿（可继续添加样本）
DATASET_STATUS_LOCKED = "locked"      # 锁定（不再添加，准备导出）
DATASET_STATUS_EXPORTED = "exported"  # 已导出

VALID_DATASET_STATUSES = [DATASET_STATUS_DRAFT, DATASET_STATUS_LOCKED, DATASET_STATUS_EXPORTED]


# ============================================================
# 路径工具
# ============================================================

def _dataset_dir(dataset_id: str) -> Path:
    """获取数据集目录路径。"""
    return DATASETS_DIR / dataset_id


def _metadata_path(dataset_id: str) -> Path:
    """获取数据集元数据文件路径。"""
    return _dataset_dir(dataset_id) / "metadata.json"


def _samples_path(dataset_id: str) -> Path:
    """获取数据集样本文件路径。"""
    return _dataset_dir(dataset_id) / "samples.json"


# ============================================================
# 索引管理
# ============================================================

def _load_index() -> list[dict]:
    """加载数据集索引。"""
    if not INDEX_FILE.exists():
        return []
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_index(index: list[dict]):
    """保存数据集索引。"""
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _update_index_entry(dataset_id: str, name: str, status: str,
                         sample_count: int, updated_at: str):
    """更新索引中的数据集条目。"""
    index = _load_index()
    found = False
    for entry in index:
        if entry["dataset_id"] == dataset_id:
            entry["name"] = name
            entry["status"] = status
            entry["sample_count"] = sample_count
            entry["updated_at"] = updated_at
            found = True
            break
    if not found:
        index.append({
            "dataset_id": dataset_id,
            "name": name,
            "status": status,
            "sample_count": sample_count,
            "updated_at": updated_at,
        })
    _save_index(index)


def _remove_index_entry(dataset_id: str):
    """从索引中移除数据集条目。"""
    index = _load_index()
    index = [e for e in index if e["dataset_id"] != dataset_id]
    _save_index(index)


# ============================================================
# 元数据读写
# ============================================================

def _load_metadata(dataset_id: str) -> Optional[dict]:
    """加载数据集元数据。"""
    path = _metadata_path(dataset_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _save_metadata(dataset_id: str, metadata: dict):
    """保存数据集元数据。"""
    path = _metadata_path(dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def _load_samples(dataset_id: str) -> list[dict]:
    """加载数据集样本列表。"""
    path = _samples_path(dataset_id)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_samples(dataset_id: str, samples: list[dict]):
    """保存数据集样本列表。"""
    path = _samples_path(dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)


# ============================================================
# 数据集 CRUD
# ============================================================

def create_dataset(name: str, description: str = "") -> dict:
    """
    创建一个新的数据集。

    Args:
        name: 数据集名称（如 "莆仙话节目名识别-初始集"）
        description: 数据集描述

    Returns:
        数据集元数据 dict
    """
    dataset_id = f"ds-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    metadata = {
        "dataset_id": dataset_id,
        "name": name.strip(),
        "description": description.strip(),
        "status": DATASET_STATUS_DRAFT,
        "created_at": now,
        "updated_at": now,
        "sample_count": 0,
    }

    _save_metadata(dataset_id, metadata)
    _save_samples(dataset_id, [])
    _update_index_entry(dataset_id, name, DATASET_STATUS_DRAFT, 0, now)

    return metadata


def get_dataset(dataset_id: str) -> Optional[dict]:
    """获取数据集元数据。"""
    return _load_metadata(dataset_id)


def list_datasets() -> list[dict]:
    """
    列出所有数据集（索引级别，不含样本详情）。

    Returns:
        数据集索引列表，按更新时间倒序
    """
    index = _load_index()
    # 按更新时间倒序
    index.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return index


def delete_dataset(dataset_id: str) -> bool:
    """
    删除一个数据集（元数据 + 样本）。

    Returns:
        删除成功返回 True，不存在返回 False
    """
    ddir = _dataset_dir(dataset_id)
    if not ddir.exists():
        return False

    import shutil
    shutil.rmtree(ddir)
    _remove_index_entry(dataset_id)
    return True


def update_dataset_status(dataset_id: str, status: str) -> Optional[dict]:
    """
    更新数据集状态。

    Args:
        dataset_id: 数据集 ID
        status: 新状态（draft / locked / exported）

    Returns:
        更新后的元数据，不存在返回 None
    """
    if status not in VALID_DATASET_STATUSES:
        raise ValueError(f"无效状态: {status}，支持: {VALID_DATASET_STATUSES}")

    metadata = _load_metadata(dataset_id)
    if not metadata:
        return None

    metadata["status"] = status
    metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_metadata(dataset_id, metadata)

    # 更新索引
    samples = _load_samples(dataset_id)
    _update_index_entry(
        dataset_id, metadata["name"], status,
        len(samples), metadata["updated_at"]
    )

    return metadata


# ============================================================
# 样本管理
# ============================================================

def add_sample(
    dataset_id: str,
    recording_id: str,
    user_id: str,
    audio_path: str,
    audio_format: str,
    audio_size: int,
    duration_ms: int,
    original_text: str,
    normalized_text: Optional[str],
    corrected_text: Optional[str] = None,
    confidence: float = 0.0,
    provider: str = "",
    model_version: str = "",
    accent: Optional[str] = None,
) -> Optional[dict]:
    """
    向数据集添加一个训练样本。

    如果 corrected_text 为 None，则使用 normalized_text 或 original_text，
    标注状态设为 pending。如果提供了 corrected_text，状态设为 annotated。

    Returns:
        添加的样本 dict，数据集不存在返回 None
    """
    metadata = _load_metadata(dataset_id)
    if not metadata:
        return None

    # 锁定的数据集不允许添加
    if metadata["status"] != DATASET_STATUS_DRAFT:
        raise ValueError(f"数据集状态为 {metadata['status']}，不允许添加样本")

    # 检查是否已存在相同 recording_id
    samples = _load_samples(dataset_id)
    for s in samples:
        if s.get("recording_id") == recording_id and s.get("user_id") == user_id:
            # 已存在，返回现有样本
            return s

    sample_id = f"smp-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # 确定标注状态
    if corrected_text and corrected_text.strip():
        annotation_status = STATUS_ANNOTATED
        annotated_at = now
    else:
        corrected_text = normalized_text or original_text
        annotation_status = STATUS_PENDING
        annotated_at = None

    sample = {
        "sample_id": sample_id,
        "recording_id": recording_id,
        "user_id": user_id,
        "audio_path": audio_path,
        "audio_format": audio_format,
        "audio_size": audio_size,
        "duration_ms": duration_ms,
        "original_text": original_text,
        "normalized_text": normalized_text,
        "corrected_text": corrected_text,
        "annotation_status": annotation_status,
        "confidence": confidence,
        "provider": provider,
        "model_version": model_version,
        "accent": accent,
        "added_at": now,
        "annotated_at": annotated_at,
    }

    samples.append(sample)
    _save_samples(dataset_id, samples)

    # 更新元数据和索引
    metadata["sample_count"] = len(samples)
    metadata["updated_at"] = now
    _save_metadata(dataset_id, metadata)
    _update_index_entry(
        dataset_id, metadata["name"], metadata["status"],
        len(samples), now
    )

    return sample


def update_sample_annotation(
    dataset_id: str,
    sample_id: str,
    corrected_text: str,
    annotation_status: str = STATUS_ANNOTATED,
) -> Optional[dict]:
    """
    更新样本的标注文本和状态。

    Returns:
        更新后的样本 dict，不存在返回 None
    """
    if annotation_status not in VALID_STATUSES:
        raise ValueError(f"无效标注状态: {annotation_status}")

    samples = _load_samples(dataset_id)
    for s in samples:
        if s["sample_id"] == sample_id:
            s["corrected_text"] = corrected_text.strip()
            s["annotation_status"] = annotation_status
            s["annotated_at"] = datetime.now(timezone.utc).isoformat()
            _save_samples(dataset_id, samples)

            # 更新元数据时间戳
            metadata = _load_metadata(dataset_id)
            if metadata:
                metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
                _save_metadata(dataset_id, metadata)
                _update_index_entry(
                    dataset_id, metadata["name"], metadata["status"],
                    len(samples), metadata["updated_at"]
                )

            return s

    return None


def remove_sample(dataset_id: str, sample_id: str) -> bool:
    """
    从数据集移除一个样本。

    Returns:
        移除成功返回 True，不存在返回 False
    """
    samples = _load_samples(dataset_id)
    new_samples = [s for s in samples if s["sample_id"] != sample_id]

    if len(new_samples) == len(samples):
        return False

    _save_samples(dataset_id, new_samples)

    # 更新元数据和索引
    metadata = _load_metadata(dataset_id)
    if metadata:
        now = datetime.now(timezone.utc).isoformat()
        metadata["sample_count"] = len(new_samples)
        metadata["updated_at"] = now
        _save_metadata(dataset_id, metadata)
        _update_index_entry(
            dataset_id, metadata["name"], metadata["status"],
            len(new_samples), now
        )

    return True


def list_samples(
    dataset_id: str,
    page: int = 1,
    page_size: int = 50,
    status_filter: Optional[str] = None,
    min_confidence: Optional[float] = None,
) -> dict:
    """
    获取数据集样本列表（分页 + 过滤）。

    Args:
        dataset_id: 数据集 ID
        page: 页码（从 1 开始）
        page_size: 每页数量
        status_filter: 按标注状态过滤（pending/annotated/verified）
        min_confidence: 最低置信度过滤

    Returns:
        {
            "samples": [...],
            "total": int,
            "page": int,
            "page_size": int,
            "total_pages": int,
        }
    """
    samples = _load_samples(dataset_id)

    # 过滤
    if status_filter:
        samples = [s for s in samples if s.get("annotation_status") == status_filter]
    if min_confidence is not None:
        samples = [s for s in samples if s.get("confidence", 0) >= min_confidence]

    total = len(samples)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    start = (page - 1) * page_size
    end = start + page_size
    items = samples[start:end]

    return {
        "samples": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_sample(dataset_id: str, sample_id: str) -> Optional[dict]:
    """获取单个样本详情。"""
    samples = _load_samples(dataset_id)
    for s in samples:
        if s["sample_id"] == sample_id:
            return s
    return None


# ============================================================
# 统计与质量指标
# ============================================================

def get_dataset_stats(dataset_id: str) -> dict:
    """
    获取数据集统计信息。

    Returns:
        {
            "total_samples": int,
            "pending": int,
            "annotated": int,
            "verified": int,
            "total_duration_ms": int,
            "total_audio_size": int,
            "avg_confidence": float,
            "providers": {...},
            "accents": {...},
        }
    """
    samples = _load_samples(dataset_id)

    if not samples:
        return {
            "total_samples": 0,
            "pending": 0,
            "annotated": 0,
            "verified": 0,
            "total_duration_ms": 0,
            "total_audio_size": 0,
            "avg_confidence": 0.0,
            "providers": {},
            "accents": {},
        }

    status_counts = {"pending": 0, "annotated": 0, "verified": 0}
    total_duration = 0
    total_size = 0
    total_confidence = 0.0
    providers = {}
    accents = {}

    for s in samples:
        status = s.get("annotation_status", "pending")
        if status in status_counts:
            status_counts[status] += 1

        total_duration += s.get("duration_ms", 0)
        total_size += s.get("audio_size", 0)
        total_confidence += s.get("confidence", 0.0)

        provider = s.get("provider", "unknown")
        providers[provider] = providers.get(provider, 0) + 1

        accent = s.get("accent") or "unknown"
        accents[accent] = accents.get(accent, 0) + 1

    return {
        "total_samples": len(samples),
        "pending": status_counts["pending"],
        "annotated": status_counts["annotated"],
        "verified": status_counts["verified"],
        "total_duration_ms": total_duration,
        "total_audio_size": total_size,
        "avg_confidence": round(total_confidence / len(samples), 3),
        "providers": providers,
        "accents": accents,
    }


# ============================================================
# 批量操作
# ============================================================

def add_samples_from_recordings(
    dataset_id: str,
    recordings: list[dict],
    user_id: str,
) -> dict:
    """
    批量从录音列表添加样本到数据集。

    Args:
        dataset_id: 数据集 ID
        recordings: 录音元数据列表（来自 recording_store）
        user_id: 录音所属用户 ID

    Returns:
        {"added": int, "skipped": int, "errors": int}
    """
    added = 0
    skipped = 0
    errors = 0

    # 预加载已有样本，用于去重检查
    existing_samples = _load_samples(dataset_id)
    existing_keys = {
        (s.get("recording_id"), s.get("user_id"))
        for s in existing_samples
    }

    for rec in recordings:
        try:
            # 构建音频路径
            from asr.recording_store import get_audio_path, USER_DATA_DIR, ANONYMOUS_USER_ID
            uid = user_id if user_id else ANONYMOUS_USER_ID
            rec_id = rec.get("recording_id", "")

            # 去重检查
            if (rec_id, uid) in existing_keys:
                skipped += 1
                continue

            audio_filename = rec.get("audio_filename", "")
            audio_path = str(USER_DATA_DIR / uid / "recordings" / audio_filename)

            result = add_sample(
                dataset_id=dataset_id,
                recording_id=rec_id,
                user_id=uid,
                audio_path=audio_path,
                audio_format=rec.get("audio_format", "webm"),
                audio_size=rec.get("audio_size", 0),
                duration_ms=rec.get("duration_ms", 0),
                original_text=rec.get("text", ""),
                normalized_text=rec.get("normalized_text"),
                confidence=0.9 if rec.get("needs_confirmation") is False else 0.7,
                provider=rec.get("provider", ""),
                model_version=rec.get("model_version", ""),
            )
            if result:
                added += 1
                existing_keys.add((rec_id, uid))
            else:
                errors += 1
        except Exception:
            errors += 1

    return {"added": added, "skipped": skipped, "errors": errors}
