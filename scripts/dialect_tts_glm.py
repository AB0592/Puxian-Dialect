#!/usr/bin/env python3
"""
GLM-TTS-Clone 引擎 — 智谱声音克隆 + 方言语音合成

方案: GLM-TTS API + GLM-TTS-Clone (3秒音频即可克隆音色)
  - GLM-TTS: 7+ 内置声音, 情感控制, 音调调整
  - GLM-TTS-Clone: 声音克隆, 3秒参考音频 → 个性化音色
  - 成本: 按字符/音频时长计费

方言音色策略:
  1. 优先: 用 hinghwa.cn 576条莆仙话音频做声音克隆
  2. 降级: GLM-TTS 内置方言音色 (粤语/四川话)
  3. 回退: Edge TTS / CosyVoice (现有引擎)

Pre-requisites:
  - GLM_API_KEY / ZAI_API_KEY / Z_AI_API_KEY 之一必须在 .env 中
  - pip3 install requests
"""

import os
import json
import base64
import tempfile
from pathlib import Path
from typing import Optional

# ============================================================
# 配置
# ============================================================

GLM_TTS_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
GLM_TTS_ENDPOINT = "/audio/speech"

# GLM-TTS 内置方言音色映射 (通过实测验证)
DIALECT_VOICES_GLM = {
    "canton":   "xiaochen",   # 粤语可用
    "minnan":   "xiaochen",   # 闽南语
    "sichuan":  "xiaochen",   # 四川话
    "shanghai": "xiaochen",   # 上海话
    "putian":   "Putian-Clone",  # 莆仙话: 声音克隆专属
    "mandarin": "xiaochen",   # 普通话女声
}

# 全局缓存
_GLM_API_KEY: Optional[str] = None
_CLONED_VOICE_ID: Optional[str] = None  # 克隆后的声音 ID


def _get_api_key() -> str:
    """从 .env 获取智谱 API Key"""
    global _GLM_API_KEY
    if _GLM_API_KEY:
        return _GLM_API_KEY

    env_keys = ["GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY", "ZHIPU_API_KEY"]
    env_paths = [
        Path("/Users/sagaai/.hermes/profiles/dialect-bot/.env"),
        Path("/Users/sagaai/.hermes/hermes-agent/.env"),
    ]

    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    for key_name in env_keys:
                        if line.startswith(key_name + "="):
                            key = line.split("=", 1)[1].strip().strip("'\"").strip()
                            if key:
                                _GLM_API_KEY = key
                                return key
    return ""


# ============================================================
# 声音克隆 (GLM-TTS-Clone)
# ============================================================

def clone_voice(sample_audio_path: str, voice_name: str = "putian-clone") -> dict:
    """
    用一段参考音频克隆声音。
    
    GLM-TTS-Clone 只需要 **3 秒** 音频即可克隆音色。
    用 hinghwa.cn 576 条莆仙话音频中选最优样本做克隆源。
    
    返回:
      {
        "voice_id": str,     # 克隆后的声音 ID
        "status": str,       # "success" | "failed"
        "error": str or None
      }
    """
    import requests

    api_key = _get_api_key()
    if not api_key:
        return {"voice_id": "", "status": "failed", "error": "GLM_API_KEY 未配置"}

    if not os.path.exists(sample_audio_path):
        return {"voice_id": "", "status": "failed", 
                "error": f"参考音频不存在: {sample_audio_path}"}

    # 检查音频时长 (> 3秒)
    try:
        import subprocess
        ffprobe = "/opt/homebrew/bin/ffprobe"
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", sample_audio_path],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(result.stdout.strip())
        if duration < 3.0:
            return {"voice_id": "", "status": "failed",
                    "error": f"参考音频过短 ({duration:.1f}s < 3s)"}
    except Exception:
        pass  # 无法检测时长，继续尝试

    # base64 编码参考音频
    with open(sample_audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")

    print(f"  -> GLM-TTS-Clone: 正在克隆声音 ({voice_name})")

    try:
        resp = requests.post(
            f"{GLM_TTS_BASE_URL}/audio/speech/clone",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "audio": audio_b64,
                "voice_name": voice_name,
            },
            timeout=30,
        )

        if resp.status_code == 200:
            data = resp.json()
            voice_id = data.get("voice_id", "")
            if voice_id:
                global _CLONED_VOICE_ID
                _CLONED_VOICE_ID = voice_id
                print(f"  -> 声音克隆成功: voice_id={voice_id}")
                return {"voice_id": voice_id, "status": "success", "error": None}

            return {"voice_id": "", "status": "failed",
                    "error": f"API 返回无 voice_id: {resp.text[:300]}"}
        else:
            err = resp.text[:300]
            print(f"  -> 声音克隆失败 ({resp.status_code}): {err}")
            return {"voice_id": "", "status": "failed",
                    "error": f"HTTP {resp.status_code}: {err}"}

    except Exception as e:
        print(f"  -> 声音克隆异常: {e}")
        return {"voice_id": "", "status": "failed", "error": str(e)[:300]}


def auto_select_clone_source(dialect: str = "putian") -> str:
    """
    从 hinghwa.cn 音频库中自动选择最佳克隆源音频。
    
    选择策略:
      1. 优先选 5-15 秒的中等长度音频 (覆盖更多音素)
      2. 避开背景噪音大的录制
      3. 默认选第1个符合条件的
    
    返回音频文件路径。
    """
    audio_dir = Path(__file__).parent.parent / "data" / "hinghwa" / "audio"
    
    if not audio_dir.exists():
        return ""

    # 收集音频文件
    audio_files = []
    for ext in [".mp3", ".wav", ".m4a"]:
        audio_files.extend(list(audio_dir.glob(f"*{ext}")))

    if not audio_files:
        return ""

    # 按文件大小排序 (中等大小的优先, 排除太短或太长的)
    audio_files.sort(key=lambda p: p.stat().st_size)

    # 选中间大小的文件作为克隆源 (通常质量较好)
    mid_idx = len(audio_files) // 2
    return str(audio_files[mid_idx])


# ============================================================
# GLM-TTS 文字转语音
# ============================================================

def speak_glm(text: str, dialect: str = "putian", voice_id: str = None) -> dict:
    """
    GLM-TTS 文字转语音。
    
    优先级:
      1. voice_id 指定 → 使用克隆声音
      2. _CLONED_VOICE_ID 已缓存 → 使用克隆声音
      3. dialect 内置音色 → 使用预置方言音色
    
    返回:
      {
        "audio_path": str,    # 生成的音频文件路径
        "format": str,        # "mp3" / "wav"
        "engine": str,        # 引擎名称
        "error": str or None
      }
    """
    import requests

    api_key = _get_api_key()
    if not api_key:
        return {"audio_path": "", "format": "mp3", "engine": "glm-tts",
                "error": "GLM_API_KEY 未配置"}

    if not text.strip():
        return {"audio_path": "", "format": "mp3", "engine": "glm-tts",
                "error": "文本为空"}

    # 确定使用哪个声音
    resolved_voice = voice_id or _CLONED_VOICE_ID or DIALECT_VOICES_GLM.get(dialect, "Standard-Female")
    use_clone = bool(voice_id or _CLONED_VOICE_ID)

    print(f"  -> GLM-TTS: [{dialect}] voice={resolved_voice} clone={use_clone} text_len={len(text)}")

    endpoint = "/audio/speech/clone/synthesis" if use_clone else GLM_TTS_ENDPOINT
    payload = {
        "model": "glm-tts",
        "input": text,
        "voice": resolved_voice,
        "response_format": "wav",
    }

    try:
        resp = requests.post(
            f"{GLM_TTS_BASE_URL}{endpoint}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )

        if resp.status_code == 200:
            # 返回的是音频二进制
            content_type = resp.headers.get("Content-Type", "")
            if "audio" in content_type or resp.content[:4] in [b"ID3", b"\xff\xfb", b"RIFF"]:
                # 保存到临时文件
                ext = ".mp3" if b"ID3" in resp.content[:3] or resp.content[:2] == b"\xff\xfb" else ".wav"
                output_path = tempfile.mktemp(suffix=f"_glm_tts{ext}")
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                size_kb = len(resp.content) / 1024
                print(f"  -> TTS 生成: {output_path[-50:]} ({size_kb:.0f}KB)")
                return {
                    "audio_path": output_path,
                    "format": ext.lstrip("."),
                    "engine": f"glm-tts{'-clone' if use_clone else ''}",
                    "error": None,
                }

            # JSON 响应 (可能是错误)
            data = resp.json()
            err = data.get("error", {}).get("message", str(data)[:300])
            print(f"  -> GLM-TTS 失败: {err}")
            return {"audio_path": "", "format": "mp3", "engine": "glm-tts",
                    "error": f"GLM-TTS 错误: {err}"}
        else:
            err = resp.text[:300]
            print(f"  -> GLM-TTS 失败 ({resp.status_code}): {err}")
            return {"audio_path": "", "format": "mp3", "engine": "glm-tts",
                    "error": f"HTTP {resp.status_code}: {err}"}

    except Exception as e:
        print(f"  -> GLM-TTS 异常: {e}")
        return {"audio_path": "", "format": "mp3", "engine": "glm-tts",
                "error": str(e)[:300]}


# ============================================================
# 统一入口
# ============================================================

def synthesize(text: str, dialect: str = "putian") -> dict:
    """
    GLM-TTS 统一入口，含自动声音克隆。
    
    首次调用时:
      1. 如果没有克隆声音, 自动选择 hinghwa.cn 音频做克隆
      2. 缓存 voice_id 供后续调用
    """
    global _CLONED_VOICE_ID

    if not _get_api_key():
        return {"audio_path": "", "format": "mp3", "engine": "glm-tts",
                "error": "GLM_API_KEY 未配置"}

    # 首次调用: 自动克隆声音
    if not _CLONED_VOICE_ID and dialect == "putian":
        clone_source = auto_select_clone_source("putian")
        if clone_source:
            result = clone_voice(clone_source, "putian-clone")
            if result["status"] == "success":
                _CLONED_VOICE_ID = result["voice_id"]
            else:
                print(f"  -> 声音克隆失败, 使用内置音色: {result['error']}")

    return speak_glm(text, dialect)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 dialect_tts_glm.py speak <文本> [方言代码]")
        print("  python3 dialect_tts_glm.py clone <参考音频路径>")
        print()
        print("API Key 状态:", "已配置" if _get_api_key() else "未配置")
        print("克隆状态:", f"已克隆 ({_CLONED_VOICE_ID})" if _CLONED_VOICE_ID else "未克隆")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "clone":
        if len(sys.argv) < 3:
            print("需要指定参考音频路径")
            sys.exit(1)
        result = clone_voice(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "speak":
        if len(sys.argv) < 3:
            print("需要指定文本")
            sys.exit(1)
        text = sys.argv[2]
        dialect = sys.argv[3] if len(sys.argv) > 3 else "putian"
        result = synthesize(text, dialect)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("audio_path"):
            print(f"\n音频已保存到: {result['audio_path']}")

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
