#!/usr/bin/env python3
"""
莆仙话语音训练系统 — FastAPI 后端 + 嵌入式前端

启动: python3 api_server.py
手机访问: http://<IP>:8520

v2.0 — 新增个人口音引擎（多用户 + 口音覆盖层 + 声纹注册）
"""
import sys
import json
import os
import uuid
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import uvicorn
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from dialect_map import load, save, add, lookup, search as map_search
from dialect_map import translate as map_translate
from dialect_asr import recognize as asr_recognize
from dialect_tts import synthesize as tts_synthesize
from user_manager import (
    create_user, get_user, list_users, get_overlay,
    add_user_dialect, get_user_progress, get_register_progress,
    update_user_profile, save_voice_sample, update_stats,
    REGISTER_SENTENCES, REGISTER_SENTENCES_COUNT,
    resolve_dialect, delete_user,
)

# JWT 认证
from auth import create_token, verify_token, set_password, verify_password

# ASR v1 API 路由
from api_v1 import router as v1_router

app = FastAPI(title="莆仙话语音训练系统")

# CORS 支持（允许前端跨域访问）
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)

AUDIO_DIR = SCRIPTS_DIR.parent / "audio_cache"
AUDIO_DIR.mkdir(exist_ok=True)
STATIC_DIR = SCRIPTS_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
FLUTTER_WEB_DIR = SCRIPTS_DIR.parent / "puxian_app" / "build" / "web"
if FLUTTER_WEB_DIR.exists():
    app.mount("/flutter", StaticFiles(directory=str(FLUTTER_WEB_DIR), html=True), name="flutter")


def escape_html(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _resolve(user_id: str, dialect_text: str) -> str:
    """用户感知的方言解析"""
    base = load()
    return resolve_dialect(user_id, dialect_text, base)


# ============================================================
# 认证 API
# ============================================================

@app.post("/api/auth/register")
async def auth_register(data: dict):
    """注册新用户（带密码）"""
    name = data.get("name", "").strip()
    password = data.get("password", "").strip()
    if not name:
        raise HTTPException(400, "需要用户名")
    if not password or len(password) < 4:
        raise HTTPException(400, "密码至少 4 位")

    profile = create_user(name)
    set_password(profile["user_id"], password)
    token = create_token(profile["user_id"], name)
    return {
        "ok": True,
        "user": profile,
        "token": token,
    }


@app.post("/api/auth/login")
async def auth_login(data: dict):
    """用户登录"""
    name = data.get("name", "").strip()
    password = data.get("password", "").strip()
    if not name or not password:
        raise HTTPException(400, "需要用户名和密码")

    # 通过名字找用户
    users = list_users()
    matched = None
    for u in users:
        if u["name"] == name:
            matched = u
            break
    if not matched:
        raise HTTPException(401, "用户不存在或密码错误")

    user_id = matched["user_id"]
    if not verify_password(user_id, password):
        raise HTTPException(401, "用户不存在或密码错误")

    profile = get_user(user_id)
    token = create_token(user_id, name)
    return {
        "ok": True,
        "user": profile,
        "token": token,
    }


@app.post("/api/auth/verify")
async def auth_verify(data: dict):
    """验证 token 有效性"""
    token = data.get("token", "")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(401, "无效或已过期")
    return {"ok": True, "payload": payload}


# ============================================================
# 用户系统 API

@app.get("/api/users")
async def get_users():
    """获取所有用户列表"""
    return {"users": list_users()}


@app.post("/api/user/create")
async def api_create_user(data: dict):
    """创建新用户"""
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(400, "需要用户名")
    profile = create_user(name)
    return {"ok": True, "user": profile}


@app.get("/api/user/{user_id}")
async def api_get_user(user_id: str):
    """获取用户信息"""
    profile = get_user(user_id)
    if not profile:
        raise HTTPException(404, "用户不存在")
    return profile


@app.get("/api/user/{user_id}/progress")
async def api_user_progress(user_id: str):
    """获取用户训练进度"""
    base = load()
    p = get_user_progress(user_id, base)
    return p


@app.get("/api/user/{user_id}/register-status")
async def api_register_status(user_id: str):
    """获取声纹注册状态"""
    status = get_register_progress(user_id)
    return status


@app.post("/api/user/{user_id}/register-sample")
async def api_register_sample(user_id: str, audio: UploadFile = File(...), index: str = Form("0")):
    """提交一条声纹注册语音样本"""
    try:
        idx = int(index)
    except ValueError:
        raise HTTPException(400, "index 必须是数字")

    if idx < 0 or idx >= REGISTER_SENTENCES_COUNT:
        raise HTTPException(400, f"index 范围 0-{REGISTER_SENTENCES_COUNT - 1}")

    content = await audio.read()
    filepath = save_voice_sample(user_id, idx, content)

    # 更新用户注册进度
    profile = get_user(user_id)
    current = profile.get("register_sentences_done", 0)
    if idx >= current:
        done = idx + 1
        complete = done >= REGISTER_SENTENCES_COUNT
        update_user_profile(user_id, {
            "register_sentences_done": done if not complete else REGISTER_SENTENCES_COUNT,
            "register_complete": complete,
        })

    status = get_register_progress(user_id)
    return {"ok": True, "filepath": filepath, "status": status}


@app.post("/api/user/{user_id}/dialect/add")
async def api_user_add_dialect(user_id: str, data: dict):
    """用户新增个人映射"""
    dialect = data.get("dialect", "").strip()
    meaning = data.get("meaning", "").strip()
    if not dialect or not meaning:
        raise HTTPException(400, "需要 dialect 和 meaning")
    overlay = add_user_dialect(user_id, dialect, meaning)
    update_stats(user_id, "confirmed")
    return {"ok": True, "overlay_count": len(overlay)}


@app.delete("/api/user/{user_id}")
async def api_delete_user(user_id: str):
    """删除用户"""
    delete_user(user_id)
    return {"ok": True}


@app.get("/api/user/{user_id}/overlay")
async def api_user_overlay(user_id: str):
    """获取用户的个人覆盖层"""
    overlay = get_overlay(user_id)
    items = sorted(overlay.items(), key=lambda x: x[0])
    return {"items": items, "total": len(overlay)}


@app.get("/api/user/{user_id}/stats")
async def api_user_stats(user_id: str):
    """获取用户训练统计"""
    from user_manager import get_stats
    return get_stats(user_id)


@app.post("/api/user/{user_id}/stats/update")
async def api_user_stats_update(user_id: str, data: dict):
    """更新用户训练统计"""
    action = data.get("action", "recorded")
    category = data.get("category", "")
    stats = update_stats(user_id, action, category)
    return {"ok": True, "stats": stats}

# ============================================================
# 基础方言 API（带用户上下文）
# ============================================================

class ConfirmRequest(BaseModel):
    audio_id: Optional[str] = None
    word: Optional[str] = None
    action: str = "confirm"
    correct_meaning: Optional[str] = None
    dialect_text: Optional[str] = None
    user_id: Optional[str] = None  # 可选：多用户确认


@app.get("/api/progress")
async def get_progress(user_id: str = ""):
    """获取进度（如提供 user_id 则返回个人进度）"""
    base = load()
    if user_id:
        p = get_user_progress(user_id, base)
        return {
            "user_id": user_id,
            "total": p["total"],
            "covered": p["covered"],
            "personal": p["personal"],
            "target": p["target"],
            "stats": p["stats"],
            "total_base": p["base_total"],
        }

    from dialect_words import CHINESE_WORDS
    known_values = set(base.values())
    known_keys = set(base.keys())
    covered = sum(1 for w, _, _ in CHINESE_WORDS if w in known_values or w in known_keys)
    return {"total": len(base), "covered": covered, "target": 1000,
            "total_words": len(CHINESE_WORDS)}


@app.get("/api/next-word")
async def next_word(user_id: str = ""):
    """获取下一个待录词（带用户感知）"""
    base = load()
    from dialect_words import CHINESE_WORDS, CAT_NAMES

    # 如果提供了 user_id，用用户的已覆盖列表
    covered_set = set()
    if user_id:
        overlay = get_overlay(user_id)
        covered_set = set(overlay.keys()) | set(overlay.values())
    else:
        covered_set = set(base.values()) | set(base.keys())

    for i, (word, cat, level) in enumerate(CHINESE_WORDS):
        if word not in covered_set:
            return {"word": word, "category": CAT_NAMES.get(cat, cat), "level": level,
                    "index": i, "total": len(CHINESE_WORDS)}
    return {"done": True, "message": "全部录完！"}


@app.post("/api/recognize")
async def recognize(audio: UploadFile = File(...), word: str = Form(""),
                    lang: str = Form("auto"), user_id: str = Form("")):
    """语音识别（带用户感知）"""
    audio_id = str(uuid.uuid4())[:8]
    ext = Path(audio.filename).suffix if audio.filename else ".webm"
    if ext.lower() not in (".webm", ".mp3", ".mp4", ".m4a", ".wav", ".ogg"):
        ext = ".webm"
    audio_path = AUDIO_DIR / f"{audio_id}{ext}"
    content = await audio.read()
    with open(audio_path, "wb") as f:
        f.write(content)

    try:
        asr_result = asr_recognize(str(audio_path), lang)
        dialect = asr_result.get("text", "").strip()
    except Exception as e:
        print(f"ASR error: {e}")
        dialect = ""

    # 用户感知解析
    meaning = word
    if dialect:
        if user_id:
            meaning = _resolve(user_id, dialect)
        else:
            trans = map_translate(dialect)
            if trans != dialect:
                meaning = trans

    return {"dialect": dialect or "(未识别)", "meaning": meaning,
            "audio_id": audio_id, "audio_path": str(audio_path)}


@app.post("/api/confirm")
async def confirm(req: ConfirmRequest):
    """确认/修正录音结果"""
    base = load()
    if req.action == "confirm" and req.word and req.dialect_text and req.dialect_text != "(未识别)":
        if req.user_id:
            # 存入个人覆盖层
            add_user_dialect(req.user_id, req.dialect_text, req.word)
            update_stats(req.user_id, "confirmed")
        else:
            add(req.dialect_text, req.word)
    elif req.action == "correct" and req.correct_meaning and req.dialect_text and req.dialect_text != "(未识别)":
        if req.user_id:
            add_user_dialect(req.user_id, req.dialect_text, req.correct_meaning)
            update_stats(req.user_id, "corrected")
        else:
            add(req.dialect_text, req.correct_meaning)
    return {"ok": True}


@app.post("/api/add-text")
async def add_text(data: dict):
    """手动添加文本映射（支持 user_id）"""
    dialect = data.get("dialect", "").strip()
    meaning = data.get("meaning", "").strip()
    user_id = data.get("user_id", "")
    if not dialect or not meaning:
        raise HTTPException(400, "需要 dialect 和 meaning")

    if user_id:
        add_user_dialect(user_id, dialect, meaning)
        update_stats(user_id, "confirmed")
    else:
        add(dialect, meaning)
    return {"ok": True}


@app.post("/api/translate-text")
async def translate_text(data: dict):
    """文本方言翻译（带用户感知）"""
    text = data.get("text", "").strip()
    lang = data.get("lang", "putian")
    user_id = data.get("user_id", "")
    if not text:
        raise HTTPException(400, "需要 text")

    if user_id:
        meaning = _resolve(user_id, text)
    else:
        meaning = map_translate(text)

    if meaning == text:
        meaning = f"(未匹配到 '{text}' 的映射)"
    return {"dialect": text, "meaning": meaning, "lang": lang}


@app.post("/api/free-speech")
async def free_speech(audio: UploadFile = File(...), lang: str = Form("auto"),
                      user_id: str = Form("")):
    """自由对话识别（带用户感知）"""
    audio_id = str(uuid.uuid4())[:8]
    ext = Path(audio.filename).suffix if audio.filename else ".webm"
    if ext.lower() not in (".webm", ".mp3", ".mp4", ".m4a", ".wav", ".ogg"):
        ext = ".webm"
    audio_path = AUDIO_DIR / f"free_{audio_id}{ext}"
    content = await audio.read()
    with open(audio_path, "wb") as f:
        f.write(content)

    try:
        asr_result = asr_recognize(str(audio_path), lang)
        dialect = asr_result.get("text", "").strip()
    except Exception as e:
        print(f"ASR error: {e}")
        dialect = ""

    translation = dialect
    if dialect:
        if user_id:
            translation = _resolve(user_id, dialect)
        else:
            trans = map_translate(dialect)
            if trans != dialect:
                translation = trans

    return {"dialect": dialect or "(未识别)", "translation": translation, "audio_id": audio_id}


@app.post("/api/tts")
async def text_to_speech(data: dict):
    """文字转方言语音 — 中文输入 → 方言 MP3 输出"""
    text = data.get("text", "").strip()
    lang = data.get("lang", "putian")
    if not text:
        raise HTTPException(400, "需要 text")

    try:
        audio_path = tts_synthesize(text, lang)
        if audio_path and os.path.exists(audio_path):
            from fastapi.responses import Response
            return Response(content=Path(audio_path).read_bytes(), media_type="audio/mpeg")
        else:
            raise HTTPException(500, "TTS 合成失败")
    except Exception as e:
        raise HTTPException(500, f"TTS 错误: {e}")


@app.get("/api/kb")
async def get_kb(user_id: str = ""):
    """获取词库（可指定 user_id 获取个人覆盖层）"""
    if user_id:
        overlay = get_overlay(user_id)
        items = sorted(overlay.items(), key=lambda x: x[0])
        return {"items": items, "total": len(overlay), "scope": "personal"}

    base = load()
    items = sorted(base.items(), key=lambda x: x[0])
    return {"items": items, "total": len(base), "scope": "base"}


@app.get("/api/search")
async def search_kb(q: str = "", user_id: str = ""):
    """搜索词库（可指定 user_id 搜索个人覆盖层）"""
    if user_id:
        overlay = get_overlay(user_id)
        items = [(d, c) for d, c in overlay.items() if q in d or q in c]
        items = sorted(items, key=lambda x: x[0])
        return {"items": items, "total": len(items), "scope": "personal"}

    items = map_search(q)
    return {"items": items, "total": len(items), "scope": "base"}


@app.post("/api/delete")
async def delete_entry(data: dict):
    """删除词条"""
    dialect = data.get("dialect", "")
    user_id = data.get("user_id", "")
    if not dialect:
        raise HTTPException(400, "缺少 dialect 参数")

    if user_id:
        overlay = get_overlay(user_id)
        if dialect in overlay:
            del overlay[dialect]
            from user_manager import save_overlay
            save_overlay(user_id, overlay)
        return {"ok": True, "scope": "personal"}

    mapping = load()
    if dialect in mapping:
        del mapping[dialect]
        save(mapping)
    return {"ok": True, "scope": "base"}


# ============================================================
# 语音库采集系统 API
# ============================================================

import hashlib
COLLECT_DATA_DIR = SCRIPTS_DIR.parent / "data" / "voice_collection"
COLLECT_AUDIO_DIR = SCRIPTS_DIR.parent / "data" / "voice_collection" / "recordings"
COLLECT_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
COLLECT_USERS_FILE = COLLECT_DATA_DIR / "collect_users.json"
COLLECT_PROGRESS_FILE = COLLECT_DATA_DIR / "collect_progress.json"

# 加载素材和任务分配
_collect_materials = None
_collect_tasks = None

def _get_collect_materials():
    global _collect_materials
    if _collect_materials is None:
        path = COLLECT_DATA_DIR / "materials.json"
        if path.exists():
            _collect_materials = json.loads(path.read_text(encoding="utf-8"))
        else:
            _collect_materials = {"chars": [], "words": [], "sentences": [], "grand_total": 0}
    return _collect_materials

def _get_collect_tasks():
    global _collect_tasks
    if _collect_tasks is None:
        path = COLLECT_DATA_DIR / "tasks.json"
        if path.exists():
            _collect_tasks = json.loads(path.read_text(encoding="utf-8"))
        else:
            _collect_tasks = {}
    return _collect_tasks

def _load_collect_users():
    if COLLECT_USERS_FILE.exists():
        return json.loads(COLLECT_USERS_FILE.read_text(encoding="utf-8"))
    return {}

def _save_collect_users(users):
    COLLECT_USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_collect_progress():
    if COLLECT_PROGRESS_FILE.exists():
        return json.loads(COLLECT_PROGRESS_FILE.read_text(encoding="utf-8"))
    return {}

def _save_collect_progress(progress):
    COLLECT_PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/collect/materials")
async def get_collect_materials():
    """获取素材统计"""
    m = _get_collect_materials()
    return {
        "char_count": len(m.get("chars", [])),
        "word_count": len(m.get("words", [])),
        "sentence_count": len(m.get("sentences", [])),
        "grand_total": m.get("grand_total", 0),
    }


@app.get("/api/collect/assignments")
async def get_collect_assignments():
    """获取8人分派信息（公开）"""
    from pathlib import Path as _P
    ap = COLLECT_DATA_DIR / "assignment.json"
    if ap.exists():
        return json.loads(ap.read_text(encoding="utf-8"))
    return {"people": {}, "tasks": {}}


@app.post("/api/collect/register")
async def collect_register(data: dict):
    """注册采集员"""
    name = data.get("name", "").strip()
    password = data.get("password", "").strip()
    real_name = data.get("real_name", name)
    role = data.get("role", "").strip()

    if not name or not password:
        raise HTTPException(400, "需要用户名和密码")
    if len(password) < 4:
        raise HTTPException(400, "密码至少4位")

    users = _load_collect_users()
    if name in users:
        raise HTTPException(409, "用户名已存在")

    # 分配 speaker_id (查任务表是否有未分配的角色)
    tasks = _get_collect_tasks()
    assigned_ids = set(u.get("speaker_id") for u in users.values() if u.get("speaker_id"))
    available = [pid for pid in tasks.keys() if pid not in assigned_ids]

    speaker_id = available[0] if available else f"custom_{len(users)+1}"
    speaker_info = tasks.get(speaker_id, {}).get("profile", {"name": name, "role": role or "自定义"})

    user = {
        "speaker_id": speaker_id,
        "name": name,
        "real_name": real_name or name,
        "role": role or speaker_info.get("role", ""),
        "password": hashlib.sha256(password.encode()).hexdigest()[:16],
        "registered_at": int(time.time()),
    }
    users[name] = user
    _save_collect_users(users)

    return {"ok": True, "user": {
        "speaker_id": speaker_id,
        "name": name,
        "real_name": real_name or name,
        "role": role or speaker_info.get("role", ""),
    }}


@app.post("/api/collect/login")
async def collect_login(data: dict):
    """采集员登录"""
    name = data.get("name", "").strip()
    password = data.get("password", "").strip()

    users = _load_collect_users()
    if name not in users:
        raise HTTPException(401, "用户名或密码错误")

    user = users[name]
    expected_hash = hashlib.sha256(password.encode()).hexdigest()[:16]
    if user["password"] != expected_hash:
        raise HTTPException(401, "用户名或密码错误")

    return {"ok": True, "user": {
        "speaker_id": user["speaker_id"],
        "name": user["name"],
        "real_name": user.get("real_name", user["name"]),
        "role": user.get("role", ""),
    }}


@app.get("/api/collect/tasks/{speaker_id}")
async def get_collect_tasks(speaker_id: str):
    """获取某个采集员的任务列表"""
    tasks = _get_collect_tasks()
    if speaker_id not in tasks:
        raise HTTPException(404, f"未找到 speaker_id: {speaker_id}")

    task_data = tasks[speaker_id]
    # Return only the word text + pinyin + IPA, not the full definition (save bandwidth)
    items = []
    for c in task_data.get("chars", []):
        items.append({"type": "char", "text": c["word"], "pinyin": c["pinyin"], "ipa": c.get("ipa", "")})
    for w in task_data.get("words", []):
        items.append({"type": "word", "text": w["word"], "pinyin": w["pinyin"], "ipa": w.get("ipa", "")})
    for s in task_data.get("sentences", []):
        items.append({"type": "sentence", "text": s["word"], "pinyin": s["pinyin"], "ipa": s.get("ipa", ""), "definition": s.get("definition", "")})

    return {
        "speaker_id": speaker_id,
        "profile": task_data.get("profile", {}),
        "total_items": len(items),
        "items": items,
    }


@app.post("/api/collect/upload")
async def collect_upload(audio: UploadFile = File(...), speaker_id: str = Form(""),
                         item_index: str = Form("0"), text: str = Form(""),
                         item_type: str = Form("char"), take: str = Form("1")):
    """上传一条录音"""
    if not speaker_id:
        raise HTTPException(400, "缺少 speaker_id")

    # Save audio file
    audio_id = str(uuid.uuid4())[:8]
    ext = Path(audio.filename).suffix if audio.filename else ".webm"
    if ext.lower() not in (".webm", ".mp3", ".mp4", ".m4a", ".wav", ".ogg"):
        ext = ".webm"

    speaker_dir = COLLECT_AUDIO_DIR / speaker_id / item_type
    speaker_dir.mkdir(parents=True, exist_ok=True)

    # Naming: {text}_{take}.webm  (e.g. "一_1.webm")
    safe_text = "".join(c for c in text if c.isalnum() or c in ('-', '_'))[:40]
    filename = f"{safe_text}_{take}{ext}"
    filepath = speaker_dir / filename

    content = await audio.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # Update progress
    progress = _load_collect_progress()
    if speaker_id not in progress:
        progress[speaker_id] = {"done": 0, "items": {}}

    progress[speaker_id]["items"][f"{item_type}:{item_index}"] = {
        "text": text,
        "type": item_type,
        "file": str(filepath),
        "take": int(take),
        "size": len(content),
    }
    progress[speaker_id]["done"] = len(progress[speaker_id]["items"])
    _save_collect_progress(progress)

    return {"ok": True, "filename": filename, "done": progress[speaker_id]["done"]}


@app.get("/api/collect/progress/{speaker_id}")
async def get_collect_progress(speaker_id: str):
    """获取采集员进度"""
    progress = _load_collect_progress()
    p = progress.get(speaker_id, {"done": 0, "items": {}})

    # Get total from tasks
    tasks = _get_collect_tasks()
    task_data = tasks.get(speaker_id, {})
    total = len(task_data.get("chars", [])) + len(task_data.get("words", [])) + len(task_data.get("sentences", []))

    return {
        "speaker_id": speaker_id,
        "done": p["done"],
        "total": total,
        "percentage": round(p["done"] / max(total, 1) * 100),
    }


@app.get("/api/collect/stats")
async def get_collect_stats():
    """采集系统总统计"""
    progress = _load_collect_progress()
    tasks = _get_collect_tasks()

    total_done = sum(p.get("done", 0) for p in progress.values())
    total_items = sum(
        len(t.get("chars", [])) + len(t.get("words", [])) + len(t.get("sentences", []))
        for t in tasks.values()
    )

    speakers_done = sum(1 for p in progress.values() if p.get("done", 0) >= 0)

    return {
        "registered_speakers": len(progress),
        "total_recordings": total_done,
        "total_items_needed": total_items,
        "overall_percentage": round(total_done / max(total_items, 1) * 100),
        "speakers": {
            pid: {"done": progress.get(pid, {}).get("done", 0),
                  "name": tasks.get(pid, {}).get("profile", {}).get("name", pid)}
            for pid in tasks.keys()
        }
    }


# ============================================================
# 前端页面（嵌入式 HTML）
# ============================================================

# 语音库采集页面
_COLLECT_HTML = None

@app.get("/collect")
async def collect_page():
    global _COLLECT_HTML
    if _COLLECT_HTML is None:
        html_path = SCRIPTS_DIR / "templates" / "collect.html"
        if html_path.exists():
            _COLLECT_HTML = html_path.read_text(encoding="utf-8")
    if _COLLECT_HTML:
        return HTMLResponse(_COLLECT_HTML)
    return HTMLResponse("<h1>采集页面开发中</h1><p>请等待模板就绪</p>")

@app.get("/")
async def index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/flutter/")


# 嵌入式 HTML（与原来一致，不重复编写—太长）
HTML_INDEX = """..."""
# 读取已有 HTML（保持兼容）
_HERE = Path(__file__).parent
_INDEX_HTML = _HERE / "static" / "index.html"
if _INDEX_HTML.exists():
    HTML_INDEX = _INDEX_HTML.read_text(encoding="utf-8")
else:
    # 写一份副本
    pass

# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    import ssl
    import argparse

    parser = argparse.ArgumentParser(description="方言训练服务器")
    parser.add_argument("--port", type=int, default=8520)
    parser.add_argument("--https-port", type=int, default=8521)
    args = parser.parse_args()

    print("=" * 50)
    print("  莆仙话语音训练系统 v2.0 🎤")
    print("  个人口音引擎已启动")
    print("=" * 50)

    # 同步预热 ASR 模型（确保第一次请求不超时）
    print("🔄 加载 ASR 模型...", flush=True)
    warmup_path = AUDIO_DIR / "_warmup_silence.wav"
    if not warmup_path.exists():
        import struct
        sample_rate = 16000
        duration = 0.1
        num_samples = int(sample_rate * duration)
        with open(warmup_path, "wb") as f:
            f.write(b"RIFF")
            f.write(struct.pack("<I", 36 + num_samples * 2))
            f.write(b"WAVEfmt ")
            f.write(struct.pack("<I", 16))
            f.write(struct.pack("<H", 1))
            f.write(struct.pack("<H", 1))
            f.write(struct.pack("<I", sample_rate))
            f.write(struct.pack("<I", sample_rate * 2))
            f.write(struct.pack("<H", 2))
            f.write(struct.pack("<H", 16))
            f.write(b"data")
            f.write(struct.pack("<I", num_samples * 2))
            for _ in range(num_samples):
                f.write(struct.pack("<h", 0))
    try:
        result = asr_recognize(str(warmup_path), "putian")
        engine = result.get("engine", "?")
        print(f"  ✅ ASR 加载完成 (引擎: {engine})", flush=True)
    except Exception as e:
        print(f"  ⚠ ASR 加载失败: {e}", flush=True)
    finally:
        if warmup_path.exists():
            warmup_path.unlink()
    print("服务器启动中...", flush=True)

    # HTTP 服务器
    http_config = uvicorn.Config(
        app, host="0.0.0.0", port=args.port,
        log_level="info"
    )
    http_server = uvicorn.Server(http_config)

    # HTTPS 服务器（用于手机录音）
    ssl_cert = SCRIPTS_DIR / "cert.pem"
    ssl_key = SCRIPTS_DIR / "key.pem"
    if ssl_cert.exists() and ssl_key.exists():
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(str(ssl_cert), str(ssl_key))
        https_config = uvicorn.Config(
            app, host="0.0.0.0", port=args.https_port,
            ssl_certfile=str(ssl_cert), ssl_keyfile=str(ssl_key),
            log_level="info"
        )
        https_server = uvicorn.Server(https_config)

        import asyncio
        async def run_both():
            await asyncio.gather(
                http_server.serve(),
                https_server.serve(),
            )
        asyncio.run(run_both())
    else:
        http_server.run()
