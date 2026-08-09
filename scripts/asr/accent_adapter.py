"""口音适配层 — Phase 4。

职责：
  1. 加载全局口音纠错规则（accent_rules.json）
  2. 管理用户口音档案（accent_profile.json）
  3. 对 ASR 识别文本做口音纠错：
     a. 全局规则修正（根据用户口音类型）
     b. 用户自定义纠错规则
  4. 返回纠错后的文本 + 纠错详情

适配管线位置：
  ASR Provider 输出 → ★ 口音适配 ★ → 节目名规范化 → 返回

用户口音档案存储：
  user_data/{user_id}/accent_profile.json
  {
    "user_id": "user123",
    "accent": "putian",
    "custom_corrections": [
      {"original": "春操", "corrected": "春草", "count": 3, "last_used": "2026-08-09T12:00:00"}
    ],
    "stats": {
      "total_corrections_added": 5,
      "corrections_applied": 12
    }
  }
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ============================================================
# 常量
# ============================================================

# 复用 user_manager 的 USER_DATA_DIR
USER_DATA_DIR = Path(__file__).parent.parent.parent / "user_data"
ACCENT_RULES_PATH = Path(__file__).parent / "accent_rules.json"
ACCENT_PROFILE_FILE = "accent_profile.json"
ANONYMOUS_USER_ID = "anonymous"

# 支持的口音类型
SUPPORTED_ACCENTS = ["auto", "putian", "xianyou", "mandarin"]


# ============================================================
# 全局规则加载（带缓存）
# ============================================================

_rules_cache: Optional[dict] = None


def _load_rules() -> dict:
    """加载 accent_rules.json，带缓存。"""
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache

    if not ACCENT_RULES_PATH.exists():
        _rules_cache = {"version": "v1", "accents": {}}
        return _rules_cache

    with open(ACCENT_RULES_PATH, "r", encoding="utf-8") as f:
        _rules_cache = json.load(f)

    return _rules_cache


def get_available_accents() -> list[dict]:
    """
    获取可用的口音类型列表。

    Returns:
        [{"code": "putian", "description": "莆田口音"}, ...]
    """
    rules = _load_rules()
    accents = rules.get("accents", {})
    return [
        {"code": code, "description": data.get("description", code)}
        for code, data in accents.items()
    ]


def get_accent_description(accent: str) -> str:
    """获取口音类型的描述文字。"""
    rules = _load_rules()
    accent_data = rules.get("accents", {}).get(accent, {})
    return accent_data.get("description", accent)


# ============================================================
# 用户口音档案读写
# ============================================================

def _profile_path(user_id: str) -> Path:
    """获取用户口音档案文件路径。"""
    uid = user_id if user_id else ANONYMOUS_USER_ID
    return USER_DATA_DIR / uid / ACCENT_PROFILE_FILE


def get_accent_profile(user_id: str) -> dict:
    """
    获取用户口音档案。

    如果用户还没有档案，返回默认档案（accent="auto"，无自定义纠错）。
    """
    path = _profile_path(user_id)
    if not path.exists():
        return {
            "user_id": user_id if user_id else ANONYMOUS_USER_ID,
            "accent": "auto",
            "custom_corrections": [],
            "stats": {
                "total_corrections_added": 0,
                "corrections_applied": 0,
            },
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {
            "user_id": user_id if user_id else ANONYMOUS_USER_ID,
            "accent": "auto",
            "custom_corrections": [],
            "stats": {
                "total_corrections_added": 0,
                "corrections_applied": 0,
            },
        }


def _save_profile(user_id: str, profile: dict):
    """保存用户口音档案。"""
    path = _profile_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def set_user_accent(user_id: str, accent: str) -> dict:
    """
    设置用户的口音类型。

    Args:
        user_id: 用户 ID
        accent: 口音代码（auto/putian/xianyou/mandarin）

    Returns:
        更新后的口音档案
    """
    if accent not in SUPPORTED_ACCENTS:
        raise ValueError(f"不支持的口音类型: {accent}，支持: {SUPPORTED_ACCENTS}")

    profile = get_accent_profile(user_id)
    profile["accent"] = accent
    _save_profile(user_id, profile)
    return profile


# ============================================================
# 用户自定义纠错规则管理
# ============================================================

def add_user_correction(user_id: str, original: str, corrected: str) -> dict:
    """
    添加一条用户自定义纠错规则。

    如果已存在相同 original 的规则，则更新 corrected 和 count。

    Args:
        user_id: 用户 ID
        original: ASR 识别出的错误文本
        corrected: 正确文本

    Returns:
        更新后的口音档案
    """
    original = original.strip()
    corrected = corrected.strip()

    if not original or not corrected:
        raise ValueError("original 和 corrected 不能为空")

    profile = get_accent_profile(user_id)
    corrections = profile.get("custom_corrections", [])

    # 查找是否已存在
    found = False
    for c in corrections:
        if c["original"] == original:
            c["corrected"] = corrected
            c["count"] = c.get("count", 0) + 1
            c["last_used"] = datetime.now(timezone.utc).isoformat()
            found = True
            break

    if not found:
        corrections.append({
            "original": original,
            "corrected": corrected,
            "count": 1,
            "last_used": datetime.now(timezone.utc).isoformat(),
        })
        profile["stats"]["total_corrections_added"] = profile["stats"].get("total_corrections_added", 0) + 1

    profile["custom_corrections"] = corrections
    _save_profile(user_id, profile)
    return profile


def delete_user_correction(user_id: str, original: str) -> bool:
    """
    删除一条用户自定义纠错规则。

    Returns:
        删除成功返回 True，不存在返回 False
    """
    profile = get_accent_profile(user_id)
    corrections = profile.get("custom_corrections", [])

    original = original.strip()
    new_corrections = [c for c in corrections if c["original"] != original]

    if len(new_corrections) == len(corrections):
        return False

    profile["custom_corrections"] = new_corrections
    _save_profile(user_id, profile)
    return True


def list_user_corrections(user_id: str) -> list[dict]:
    """获取用户所有自定义纠错规则。"""
    profile = get_accent_profile(user_id)
    return profile.get("custom_corrections", [])


# ============================================================
# 核心：口音适配（文本纠错）
# ============================================================

def adapt_text(text: str, accent: Optional[str], user_id: Optional[str]) -> dict:
    """
    对 ASR 识别文本做口音纠错。

    适配流程：
      1. 如果 accent 为 None，尝试从用户档案读取
      2. 应用全局口音规则（根据 accent 类型）
      3. 应用用户自定义纠错规则
      4. 返回纠错后的文本 + 纠错详情

    Args:
        text: ASR 识别出的原始文本
        accent: 口音代码（None 时从用户档案读取）
        user_id: 用户 ID（用于读取口音类型和自定义纠错）

    Returns:
        {
            "original_text": str,       # 原始文本
            "adapted_text": str,        # 纠错后的文本
            "accent": str,              # 使用的口音类型
            "corrections_applied": [   # 应用了的纠错列表
                {
                    "original": str,    # 匹配到的错误文本
                    "corrected": str,   # 修正后的文本
                    "source": str,      # "global" 或 "user"
                    "reason": str,      # 纠错原因（仅全局规则有）
                }
            ],
            "was_adapted": bool,        # 是否做了任何纠错
        }
    """
    if not text or not text.strip():
        return {
            "original_text": text or "",
            "adapted_text": text or "",
            "accent": accent or "auto",
            "corrections_applied": [],
            "was_adapted": False,
        }

    original_text = text.strip()
    adapted_text = original_text
    corrections_applied = []

    # 1. 确定口音类型
    effective_accent = accent
    profile = None
    if user_id:
        profile = get_accent_profile(user_id)
        if not effective_accent or effective_accent == "auto":
            effective_accent = profile.get("accent", "auto")

    if not effective_accent:
        effective_accent = "auto"

    # 2. 应用全局口音规则
    if effective_accent and effective_accent != "auto":
        rules = _load_rules()
        accent_data = rules.get("accents", {}).get(effective_accent, {})
        global_corrections = accent_data.get("corrections", [])

        for rule in global_corrections:
            pattern = rule.get("pattern", "")
            replacement = rule.get("replacement", "")
            if pattern and pattern in adapted_text:
                adapted_text = adapted_text.replace(pattern, replacement)
                corrections_applied.append({
                    "original": pattern,
                    "corrected": replacement,
                    "source": "global",
                    "reason": rule.get("reason", ""),
                })

    # 3. 应用用户自定义纠错
    if profile and profile.get("custom_corrections"):
        for c in profile["custom_corrections"]:
            orig = c.get("original", "")
            corr = c.get("corrected", "")
            if orig and orig in adapted_text:
                adapted_text = adapted_text.replace(orig, corr)
                corrections_applied.append({
                    "original": orig,
                    "corrected": corr,
                    "source": "user",
                    "reason": "用户自定义纠错",
                })

        # 如果有纠错被应用，更新统计
        if corrections_applied:
            profile["stats"]["corrections_applied"] = profile["stats"].get("corrections_applied", 0) + len(corrections_applied)
            _save_profile(user_id, profile)

    was_adapted = adapted_text != original_text

    return {
        "original_text": original_text,
        "adapted_text": adapted_text,
        "accent": effective_accent,
        "corrections_applied": corrections_applied,
        "was_adapted": was_adapted,
    }
