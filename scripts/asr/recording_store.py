"""录音数据存储与回放 — Phase 3。

职责：
  1. 保存录音音频文件到 user_data/{user_id}/recordings/
  2. 保存录音元数据到 user_data/{user_id}/recordings.json
  3. 查询录音列表（分页）
  4. 获取单条录音详情
  5. 获取音频文件路径（供回放）
  6. 删除录音（音频 + 元数据）

存储结构：
  user_data/
    {user_id}/                     # 用户目录（匿名用户用 "anonymous"）
      recordings/                   # 录音音频文件目录
        rec-abc123.webm
        rec-def456.mp3
      recordings.json               # 录音元数据列表

元数据格式（recordings.json 中每条记录）：
  {
    "recording_id": "rec-abc123",
    "user_id": "user123",
    "timestamp": "2026-08-09T12:00:00",
    "audio_filename": "rec-abc123.webm",
    "audio_format": "webm",
    "audio_size": 12345,
    "duration_ms": 4000,
    "text": "春草",
    "normalized_text": "春草闯堂",
    "provider": "thirdparty",
    "processing_ms": 1500,
    "needs_confirmation": false,
    "request_id": "req-xyz",
    "model_version": "paraformer-realtime-v2"
  }
"""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ============================================================
# 常量
# ============================================================

# 复用 user_manager 的 USER_DATA_DIR
# 避免循环导入，直接计算路径
USER_DATA_DIR = Path(__file__).parent.parent.parent / "user_data"
RECORDINGS_DIR_NAME = "recordings"
RECORDINGS_META_FILE = "recordings.json"
ANONYMOUS_USER_ID = "anonymous"

# 每页最多返回的录音数量
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 单用户最多保存的录音数量（防止无限增长）
MAX_RECORDINGS_PER_USER = 500


# ============================================================
# 路径工具
# ============================================================

def _user_dir(user_id: str) -> Path:
    """获取用户目录路径。"""
    uid = user_id if user_id else ANONYMOUS_USER_ID
    return USER_DATA_DIR / uid


def _recordings_dir(user_id: str) -> Path:
    """获取用户录音目录路径。"""
    return _user_dir(user_id) / RECORDINGS_DIR_NAME


def _recordings_meta_path(user_id: str) -> Path:
    """获取用户录音元数据文件路径。"""
    return _user_dir(user_id) / RECORDINGS_META_FILE


# ============================================================
# 元数据读写
# ============================================================

def _load_metadata(user_id: str) -> list[dict]:
    """加载用户录音元数据列表。"""
    path = _recordings_meta_path(user_id)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_metadata(user_id: str, recordings: list[dict]):
    """保存用户录音元数据列表。"""
    path = _recordings_meta_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recordings, f, ensure_ascii=False, indent=2)


# ============================================================
# 核心功能
# ============================================================

def save_recording(
    user_id: str,
    audio_bytes: bytes,
    audio_format: str,
    transcribe_result: dict,
) -> Optional[dict]:
    """
    保存一条录音（音频文件 + 元数据）。

    Args:
        user_id: 用户 ID（空字符串表示匿名用户）
        audio_bytes: 音频文件字节
        audio_format: 音频格式（webm/wav/mp3/m4a/ogg）
        transcribe_result: transcribe 服务返回的结果字典，需包含：
            - request_id, text, normalized_text, duration_ms,
              processing_ms, provider, model_version, needs_confirmation

    Returns:
        保存成功返回录音元数据 dict，失败返回 None
    """
    uid = user_id if user_id else ANONYMOUS_USER_ID

    # 生成录音 ID
    recording_id = f"rec-{uuid.uuid4().hex[:12]}"
    timestamp = datetime.now(timezone.utc).isoformat()

    # 确保目录存在
    rec_dir = _recordings_dir(uid)
    rec_dir.mkdir(parents=True, exist_ok=True)

    # 保存音频文件
    audio_filename = f"{recording_id}.{audio_format}"
    audio_path = rec_dir / audio_filename

    try:
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
    except IOError:
        return None

    # 构建元数据
    metadata = {
        "recording_id": recording_id,
        "user_id": uid,
        "timestamp": timestamp,
        "audio_filename": audio_filename,
        "audio_format": audio_format,
        "audio_size": len(audio_bytes),
        "duration_ms": transcribe_result.get("duration_ms", 0),
        "text": transcribe_result.get("text", ""),
        "normalized_text": transcribe_result.get("normalized_text"),
        "provider": transcribe_result.get("provider", ""),
        "processing_ms": transcribe_result.get("processing_ms", 0),
        "needs_confirmation": transcribe_result.get("needs_confirmation", False),
        "request_id": transcribe_result.get("request_id", ""),
        "model_version": transcribe_result.get("model_version", ""),
    }

    # 加载现有元数据
    recordings = _load_metadata(uid)

    # 新录音插到最前面（最新的在前）
    recordings.insert(0, metadata)

    # 超出上限时删除最旧的录音
    while len(recordings) > MAX_RECORDINGS_PER_USER:
        old = recordings.pop()
        _delete_audio_file(uid, old.get("audio_filename"))

    # 保存元数据
    _save_metadata(uid, recordings)

    return metadata


def list_recordings(
    user_id: str,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict:
    """
    获取用户录音列表（分页）。

    Args:
        user_id: 用户 ID
        page: 页码（从 1 开始）
        page_size: 每页数量

    Returns:
        {
            "recordings": [...],
            "total": int,
            "page": int,
            "page_size": int,
            "total_pages": int,
        }
    """
    uid = user_id if user_id else ANONYMOUS_USER_ID
    recordings = _load_metadata(uid)

    total = len(recordings)
    page = max(1, page)
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    start = (page - 1) * page_size
    end = start + page_size
    items = recordings[start:end]

    return {
        "recordings": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_recording(user_id: str, recording_id: str) -> Optional[dict]:
    """
    获取单条录音详情。

    Args:
        user_id: 用户 ID
        recording_id: 录音 ID

    Returns:
        录音元数据 dict，不存在返回 None
    """
    uid = user_id if user_id else ANONYMOUS_USER_ID
    recordings = _load_metadata(uid)

    for rec in recordings:
        if rec.get("recording_id") == recording_id:
            return rec

    return None


def get_audio_path(user_id: str, recording_id: str) -> Optional[Path]:
    """
    获取录音音频文件路径。

    Args:
        user_id: 用户 ID
        recording_id: 录音 ID

    Returns:
        Path 对象，文件不存在返回 None
    """
    metadata = get_recording(user_id, recording_id)
    if not metadata:
        return None

    uid = user_id if user_id else ANONYMOUS_USER_ID
    audio_filename = metadata.get("audio_filename", "")
    if not audio_filename:
        return None

    audio_path = _recordings_dir(uid) / audio_filename
    if audio_path.exists():
        return audio_path

    return None


def delete_recording(user_id: str, recording_id: str) -> bool:
    """
    删除一条录音（音频文件 + 元数据）。

    Args:
        user_id: 用户 ID
        recording_id: 录音 ID

    Returns:
        删除成功返回 True，不存在返回 False
    """
    uid = user_id if user_id else ANONYMOUS_USER_ID
    recordings = _load_metadata(uid)

    target = None
    remaining = []
    for rec in recordings:
        if rec.get("recording_id") == recording_id:
            target = rec
        else:
            remaining.append(rec)

    if target is None:
        return False

    # 删除音频文件
    _delete_audio_file(uid, target.get("audio_filename", ""))

    # 更新元数据
    _save_metadata(uid, remaining)

    return True


def label_recording(user_id: str, recording_id: str, normalized_text: str) -> Optional[dict]:
    """
    标注一条录音的规范化文本（节目名）。

    用于用户手动纠正 ASR 匹配结果，标注后的录音会被音频匹配器
    动态参考库自动收录，提升后续匹配准确率。

    Args:
        user_id: 用户 ID
        recording_id: 录音 ID
        normalized_text: 正确的节目名（canonical）

    Returns:
        更新后的录音元数据，不存在返回 None
    """
    uid = user_id if user_id else ANONYMOUS_USER_ID
    recordings = _load_metadata(uid)

    for rec in recordings:
        if rec.get("recording_id") == recording_id:
            rec["normalized_text"] = normalized_text
            rec["needs_confirmation"] = False
            _save_metadata(uid, recordings)
            return rec

    return None


def get_recording_stats(user_id: str) -> dict:
    """
    获取用户录音统计信息。

    Returns:
        {
            "total": int,
            "total_size_bytes": int,
            "oldest_timestamp": str|None,
            "newest_timestamp": str|None,
        }
    """
    uid = user_id if user_id else ANONYMOUS_USER_ID
    recordings = _load_metadata(uid)

    if not recordings:
        return {
            "total": 0,
            "total_size_bytes": 0,
            "oldest_timestamp": None,
            "newest_timestamp": None,
        }

    total_size = sum(r.get("audio_size", 0) for r in recordings)
    timestamps = [r.get("timestamp", "") for r in recordings if r.get("timestamp")]
    timestamps.sort()

    return {
        "total": len(recordings),
        "total_size_bytes": total_size,
        "oldest_timestamp": timestamps[0] if timestamps else None,
        "newest_timestamp": timestamps[-1] if timestamps else None,
    }


# ============================================================
# 内部工具
# ============================================================

def _delete_audio_file(user_id: str, audio_filename: str):
    """安全删除音频文件。"""
    if not audio_filename:
        return
    uid = user_id if user_id else ANONYMOUS_USER_ID
    audio_path = _recordings_dir(uid) / audio_filename
    if audio_path.exists():
        try:
            audio_path.unlink()
        except OSError:
            pass
