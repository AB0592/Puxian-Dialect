#!/usr/bin/env python3
"""
个人口音引擎 — 用户管理系统

每个用户拥有：
  1. profile.json       — 用户档案（注册时间、声纹样本数、偏好）
  2. overlay.json       — 个人口音覆盖层（方言→中文，覆盖基础词库）
  3. stats.json         — 训练统计（已录词数、准确率、平均匹配度）
  4. voice_samples/     — 声纹注册音频样本

所有用户存储在 ~/user_data/ 下（在 dialect-bot profile 内）
"""
import json
import os
import uuid
import time
from pathlib import Path
from typing import Optional

USER_DATA_DIR = Path(__file__).parent.parent / "user_data"
VOICE_SAMPLES_DIR_NAME = "voice_samples"
VOICE_SAMPLE_MAX_SEC = 8
REGISTER_SENTENCES_COUNT = 10

# ============================================================
# 注册引导句子（每个新用户需朗读次数）
# ============================================================
REGISTER_SENTENCES = [
    {"text": "我罩汝", "meaning": "我喜欢你"},
    {"text": "食盲",   "meaning": "吃饭"},
    {"text": "困盲",   "meaning": "睡觉"},
    {"text": "去住底", "meaning": "去哪里"},
    {"text": "几钱",   "meaning": "多少钱"},
    {"text": "行",     "meaning": "走"},
    {"text": "汝",     "meaning": "你"},
    {"text": "好勢",   "meaning": "好了/可以了"},
    {"text": "多谢",   "meaning": "谢谢"},
    {"text": "得闲",   "meaning": "有空"},
]

# ============================================================
# 用户 CRUD
# ============================================================

def _users_path() -> Path:
    return USER_DATA_DIR / "users.json"


def _user_dir(user_id: str) -> Path:
    return USER_DATA_DIR / user_id


def _default_profile(name: str) -> dict:
    return {
        "user_id": "",
        "name": name,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "voice_samples_count": 0,
        "register_sentences_done": 0,
        "register_complete": False,
        "preferred_lang": "putian",
        "last_active": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def list_users() -> list[dict]:
    """获取所有用户列表"""
    path = _users_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_users(users: list[dict]):
    path = _users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def create_user(name: str) -> dict:
    """创建新用户"""
    users = list_users()
    user_id = str(uuid.uuid4())[:8]

    profile = _default_profile(name)
    profile["user_id"] = user_id

    # 写用户目录
    udir = _user_dir(user_id)
    udir.mkdir(parents=True, exist_ok=True)

    with open(udir / "profile.json", "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    # 空覆盖层
    with open(udir / "overlay.json", "w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

    # 空统计
    with open(udir / "stats.json", "w", encoding="utf-8") as f:
        json.dump({
            "total_recorded": 0,
            "total_confirmed": 0,
            "total_corrected": 0,
            "total_skipped": 0,
            "accuracy_pct": 0,
            "coverage_pct": 0,
            "by_category": {},
        }, f, ensure_ascii=False, indent=2)

    # 声纹目录
    (udir / VOICE_SAMPLES_DIR_NAME).mkdir(exist_ok=True)

    users.append({
        "user_id": user_id,
        "name": name,
        "register_complete": False,
        "voice_samples_done": 0,
    })
    _save_users(users)

    return profile


def get_user(user_id: str) -> Optional[dict]:
    """获取用户档案"""
    path = _user_dir(user_id) / "profile.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_user_profile(user_id: str, updates: dict):
    """更新用户档案字段"""
    profile = get_user(user_id)
    if profile is None:
        return None
    for k, v in updates.items():
        profile[k] = v
    path = _user_dir(user_id) / "profile.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    # 同步更新 users.json 中的 register_complete
    profile["last_active"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _sync_user_summary(user_id, profile)
    return profile


def _sync_user_summary(user_id: str, profile: dict):
    """同步 users.json 中的摘要字段"""
    users = list_users()
    for u in users:
        if u["user_id"] == user_id:
            u["register_complete"] = profile.get("register_complete", False)
            u["voice_samples_done"] = profile.get("register_sentences_done", 0)
            break
    _save_users(users)


def delete_user(user_id: str) -> bool:
    """删除用户"""
    users = list_users()
    users = [u for u in users if u["user_id"] != user_id]
    _save_users(users)
    import shutil
    udir = _user_dir(user_id)
    if udir.exists():
        shutil.rmtree(udir)
    return True


# ============================================================
# 个人口音覆盖层
# ============================================================

def get_overlay(user_id: str) -> dict:
    """获取用户的个人口音覆盖层"""
    path = _user_dir(user_id) / "overlay.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_overlay(user_id: str, overlay: dict):
    """保存覆盖层"""
    path = _user_dir(user_id) / "overlay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(overlay, f, ensure_ascii=False, indent=2)


def add_user_dialect(user_id: str, dialect_text: str, chinese_meaning: str):
    """用户在个人覆盖层新增/修正一条映射"""
    overlay = get_overlay(user_id)
    overlay[dialect_text.strip()] = chinese_meaning.strip()
    save_overlay(user_id, overlay)
    return overlay


# ============================================================
# 声纹注册
# ============================================================

def save_voice_sample(user_id: str, sentence_index: int, audio_content: bytes) -> str:
    """保存一条声纹注册语音样本"""
    udir = _user_dir(user_id)
    samples_dir = udir / VOICE_SAMPLES_DIR_NAME
    samples_dir.mkdir(parents=True, exist_ok=True)

    sentence = REGISTER_SENTENCES[sentence_index]
    filename = f"register_{sentence_index:02d}_{sentence['text']}.webm"
    filepath = samples_dir / filename

    with open(filepath, "wb") as f:
        f.write(audio_content)

    return str(filepath)


def get_register_progress(user_id: str) -> dict:
    """获取用户的注册进度"""
    profile = get_user(user_id)
    if profile is None:
        return {"error": "用户不存在"}

    done = profile.get("register_sentences_done", 0)
    return {
        "done": done,
        "total": REGISTER_SENTENCES_COUNT,
        "complete": profile.get("register_complete", False),
        "sentences": REGISTER_SENTENCES,
        "current_sentence_index": min(done, REGISTER_SENTENCES_COUNT - 1),
    }


# ============================================================
# 训练统计
# ============================================================

def get_stats(user_id: str) -> dict:
    """获取用户训练统计"""
    path = _user_dir(user_id) / "stats.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_stats(user_id: str, action: str = "recorded", category: str = ""):
    """
    更新训练统计
    action: recorded / confirmed / corrected / skipped
    """
    stats = get_stats(user_id)
    if not stats:
        stats = {
            "total_recorded": 0,
            "total_confirmed": 0,
            "total_corrected": 0,
            "total_skipped": 0,
            "accuracy_pct": 0,
            "coverage_pct": 0,
            "by_category": {},
        }

    if action == "recorded":
        stats["total_recorded"] = stats.get("total_recorded", 0) + 1
    elif action == "confirmed":
        stats["total_confirmed"] = stats.get("total_confirmed", 0) + 1
    elif action == "corrected":
        stats["total_corrected"] = stats.get("total_corrected", 0) + 1
    elif action == "skipped":
        stats["total_skipped"] = stats.get("total_skipped", 0) + 1

    # 计算准确率
    total_decisions = stats["total_confirmed"] + stats["total_corrected"] + stats["total_skipped"]
    if total_decisions > 0:
        stats["accuracy_pct"] = round(
            (stats["total_confirmed"] / total_decisions) * 100, 1
        )

    # 分类统计
    if category:
        cat = stats["by_category"].get(category, {"recorded": 0, "confirmed": 0})
        cat["recorded"] = cat.get("recorded", 0) + 1
        if action == "confirmed":
            cat["confirmed"] = cat.get("confirmed", 0) + 1
        stats["by_category"][category] = cat

    path = _user_dir(user_id) / "stats.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    return stats


# ============================================================
# 用户感知的方言查询（基础词库 + 个人覆盖层）
# ============================================================

def resolve_dialect(user_id: str, dialect_text: str, base_map: dict) -> str:
    """
    解析方言：
    1. 先在个人覆盖层查（覆盖层优先级最高）
    2. 再查基础词库
    """
    overlay = get_overlay(user_id)
    key = dialect_text.strip()

    # 优先个人覆盖层
    if key in overlay:
        return overlay[key]

    # 再基础词库
    if key in base_map:
        return base_map[key]

    return key


def get_user_progress(user_id: str, base_map: dict, target: int = 1000) -> dict:
    """获取用户训练进度（个人 + 基础的总覆盖）"""
    overlay = get_overlay(user_id)
    stats = get_stats(user_id)

    # 基础词库 + 个人覆盖 = 用户可见总词库
    merged = dict(base_map)
    merged.update(overlay)

    covered = len(overlay)
    total = len(merged)

    return {
        "user_id": user_id,
        "total": total,
        "covered": covered,
        "personal": len(overlay),
        "base_total": len(base_map),
        "target": target,
        "stats": {
            "recorded": stats.get("total_recorded", 0),
            "confirmed": stats.get("total_confirmed", 0),
            "corrected": stats.get("total_corrected", 0),
            "accuracy_pct": stats.get("accuracy_pct", 0),
        },
    }


# ============================================================
# CLI 测试
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用户管理系统 — user_manager.py")
        print("\n命令:")
        print("  list             列出所有用户")
        print("  create <name>    创建用户")
        print("  get <user_id>    查看用户")
        print("  delete <user_id> 删除用户")
        print("  add-dialect <user_id> <dialect> <meaning>  添加个人映射")
        print("  progress <user_id> 查看进度")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "list":
        users = list_users()
        if not users:
            print("暂无用户")
        for u in users:
            status = "✅已注册" if u.get("register_complete") else "⏳未完成"
            print(f"  {u['user_id']}  {u['name']}  {status}  声纹: {u.get('voice_samples_done', 0)}/10")

    elif cmd == "create" and len(sys.argv) > 2:
        profile = create_user(sys.argv[2])
        print(f"✅ 用户创建成功")
        print(f"  ID:   {profile['user_id']}")
        print(f"  名字: {profile['name']}")

    elif cmd == "get" and len(sys.argv) > 2:
        profile = get_user(sys.argv[2])
        if profile:
            print(json.dumps(profile, ensure_ascii=False, indent=2))
        else:
            print("用户不存在")

    elif cmd == "delete" and len(sys.argv) > 2:
        delete_user(sys.argv[2])
        print("已删除")

    elif cmd == "add-dialect" and len(sys.argv) > 4:
        add_user_dialect(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"已添加: {sys.argv[3]} → {sys.argv[4]}")

    elif cmd == "progress" and len(sys.argv) > 2:
        from dialect_map import load as base_load
        base = base_load()
        p = get_user_progress(sys.argv[2], base)
        print(json.dumps(p, ensure_ascii=False, indent=2))

    else:
        print("参数错误")
