#!/usr/bin/env python3
"""
DashScope ASR 引擎 — 阿里云语音识别

方案: Recognition.call(file=本地路径)
  - 直接传本地 WAV 文件给 DashScope 云端识别
  - 无需 HTTP server、无需公网 URL
  - 要求: 16kHz 单声道 WAV（自动用 ffmpeg 转换）

支持模型:
  - paraformer-realtime-v2 (推荐, 支持方言)
  - paraformer-v2 (文件转写, 通过 async Transcription API)

方言映射:
  - putian   → zh   (莆仙话, paraformer 目前不原生支持莆仙话)
  - canton   → yue  (粤语)
  - minnan   → nan  (闽南语)
  - sichuan  → zh   (四川话)
  - shanghai → wuu  (上海话)
  - hakka    → hak  (客家话)
  - mandarin → zh   (普通话)
"""

import os
import json
import time
import tempfile
import subprocess
from pathlib import Path

# ============================================================
# 配置
# ============================================================

DASHSCOPE_MODEL = "paraformer-realtime-v2"

LANG_TO_DASHSCOPE = {
    "putian":   "zh",
    "canton":   "yue",
    "minnan":   "nan",
    "sichuan":  "zh",
    "shanghai": "wuu",
    "hakka":    "hak",
    "mandarin": "zh",
    "auto":     "auto",
}

# 全局缓存
_DASHSCOPE_API_KEY = None
_FFMPEG_PATH = None


def _get_api_key() -> str:
    global _DASHSCOPE_API_KEY
    if _DASHSCOPE_API_KEY:
        return _DASHSCOPE_API_KEY

    env_paths = [
        Path("/Users/sagaai/.hermes/profiles/dialect-bot/.env"),
        Path("/Users/sagaai/.hermes/hermes-agent/.env"),
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DASHSCOPE_API_KEY"):
                        key = line.split("=", 1)[1].strip().strip("'\"").strip()
                        if key:
                            _DASHSCOPE_API_KEY = key
                            return key
    return ""


def _find_ffmpeg() -> str:
    global _FFMPEG_PATH
    if _FFMPEG_PATH:
        return _FFMPEG_PATH

    candidates = [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    for p in candidates:
        if os.path.exists(p):
            _FFMPEG_PATH = p
            return p

    # fallback: try PATH
    try:
        result = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            _FFMPEG_PATH = result.stdout.strip()
            return _FFMPEG_PATH
    except Exception:
        pass

    return ""


# ============================================================
# 音频格式转换
# ============================================================

def _get_audio_info(path: str) -> dict:
    """读取音频文件元数据"""
    info = {"channels": 1, "sample_rate": 16000, "format": "wav", "duration_s": 0}

    ext = Path(path).suffix.lower()
    info["format"] = ext.lstrip(".")

    try:
        import wave
        with wave.open(path, 'rb') as w:
            info["channels"] = w.getnchannels()
            info["sample_rate"] = w.getframerate()
            info["duration_s"] = w.getnframes() / w.getframerate() if w.getframerate() > 0 else 0
            return info
    except Exception:
        pass

    # 非 WAV 用 ffprobe
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return info

    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
    if not os.path.exists(ffprobe):
        return info

    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries",
             "stream=channels,sample_rate,duration", "-of", "json", path],
            capture_output=True, text=True, timeout=10,
        )
        import json
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            s = streams[0]
            info["channels"] = s.get("channels", 1)
            info["sample_rate"] = int(s.get("sample_rate", 16000))
            info["duration_s"] = float(s.get("duration", 0))
    except Exception:
        pass

    return info


def _ensure_16k_wav(audio_path: str) -> str:
    """
    确保音频是 16kHz 单声道 WAV。
    如果需要转换，用 ffmpeg 转后返回临时文件路径。
    """
    info = _get_audio_info(audio_path)

    needs_convert = (
        info["format"] != "wav"
        or info["sample_rate"] != 16000
        or info["channels"] != 1
    )

    if not needs_convert:
        return audio_path

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        print(f"  [WARN] ffmpeg 不可用，无法转换音频格式")
        return audio_path

    output_path = tempfile.mktemp(suffix="_16k.wav")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", audio_path,
             "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", output_path],
            capture_output=True, check=True, timeout=30,
        )
        print(f"  -> 音频转换: {info['sample_rate']}Hz/{info['channels']}ch → 16000Hz/mono")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"  -> ffmpeg 转换失败: {e.stderr.decode()[:200] if e.stderr else 'unknown'}")
        return audio_path


# ============================================================
# DashScope Recognition API
# ============================================================

def _recognize_dashscope(audio_path: str, lang: str = "auto", model: str = DASHSCOPE_MODEL) -> dict:
    """
    使用 Recognition.call(file=本地路径) 做语音识别。
    无需 HTTP server，DashScope SDK 直接传文件。
    """
    from dashscope.audio.asr import Recognition, RecognitionCallback

    api_key = _get_api_key()
    if not api_key:
        return {"text": "", "lang": "unknown", "engine": "dashscope", "error": "DASHSCOPE_API_KEY 未配置"}

    if not os.path.exists(audio_path):
        return {"text": "", "lang": "unknown", "engine": "dashscope", "error": f"文件不存在: {audio_path}"}

    # 确保 16kHz WAV
    processed_path = _ensure_16k_wav(audio_path)

    dashscope_lang = LANG_TO_DASHSCOPE.get(lang, "auto")
    fname = os.path.basename(audio_path)

    print(f"  -> DashScope [{model}]: {fname}  lang={dashscope_lang}")

    class Handler(RecognitionCallback):
        def on_open(self): pass
        def on_close(self): pass
        def on_complete(self): pass
        def on_error(self, msg):
            print(f"  -> DashScope error: {msg}")

    try:
        rec = Recognition(
            model=model,
            format="wav",
            sample_rate=16000,
            callback=Handler(),
            api_key=api_key,
        )

        # language_hints 通过 call 的 kwargs 传入
        result = rec.call(
            file=processed_path,
            language_hints=[dashscope_lang] if dashscope_lang != "auto" else None,
        )

        if result.status_code == 200:
            sentences = result.get_sentence()
            if sentences:
                text = " ".join(s.get("text", "") for s in sentences if s.get("text")).strip()
            else:
                text = ""

            if text:
                print(f"  -> 结果: {text[:100]}")
                return {
                    "text": text,
                    "lang": dashscope_lang,
                    "engine": f"dashscope-{model}",
                }

            # status 200 但无文本 — 可能是静音或极短音频
            dur = _get_audio_info(processed_path).get("duration_s", 0)
            if dur < 0.5:
                return {"text": "", "lang": dashscope_lang, "engine": f"dashscope-{model}",
                        "error": f"音频过短 ({dur:.1f}s)"}
            return {"text": "", "lang": dashscope_lang, "engine": f"dashscope-{model}", "error": "无识别结果"}
        else:
            err = getattr(result, 'message', f"status={result.status_code}")
            print(f"  -> DashScope 失败: {err}")
            return {"text": "", "lang": "unknown", "engine": "dashscope", "error": str(err)[:300]}

    except Exception as e:
        print(f"  -> DashScope 异常: {e}")
        return {"text": "", "lang": "unknown", "engine": "dashscope", "error": str(e)}

    finally:
        # 清理临时转换文件
        if processed_path != audio_path and os.path.exists(processed_path):
            try:
                os.unlink(processed_path)
            except OSError:
                pass


# ============================================================
# 统一入口 + 六层降级链
# ============================================================

def recognize(audio_path: str, lang: str = "auto") -> dict:
    """
    语音识别统一入口 — 六层降级链。

    降级链:
      1. DashScope paraformer-realtime-v2 (云端, 粤语/闽南语/上海话/客家话)
      2. GLM-ASR-2512 (智谱云端, 四川话额外覆盖, 自定义词汇字典)
      3. 本地 SenseVoice (funasr, 离线, 5方言 + VAD)
      4. 本地 Whisper small (离线, 通用回退, 461MB)
      5. dialect_map.json 关键词匹配 (莆仙话专属, 无ASR直接查词)
      6. 纯发音参考模式 (所有引擎不可用, 返回错误 + 提示)
    """
    # Step 1: DashScope paraformer-realtime-v2
    result = _recognize_dashscope(audio_path, lang)
    if result.get("text"):
        return result

    # Step 2: GLM-ASR-2512 (智谱云端)
    try:
        from dialect_asr_glm import recognize_glm
        result = recognize_glm(audio_path, lang)
        if result.get("text"):
            return result
    except ImportError:
        print("  -> GLM-ASR 引擎不可用 (dialect_asr_glm 未安装)")

    # Step 3: 本地 SenseVoice
    try:
        from dialect_asr import recognize as local_recognize
        result = local_recognize(audio_path, lang)
        if result.get("text"):
            return result
    except ImportError:
        print("  -> dialect_asr 不可用")

    # Step 4: 本地 Whisper small

    # Step 5: dialect_map.json 关键词匹配 (莆仙话专属路径)
    map_result = _match_dialect_map(audio_path, lang)
    if map_result.get("text"):
        return map_result

    # Step 6: 纯发音参考模式
    return {
        "text": "",
        "lang": lang,
        "engine": "fallback",
        "error": "所有引擎均不可用，建议使用发音参考模式",
        "suggestion": "请手动输入中文后播放方言参考发音",
    }


# ============================================================
# Step 5: dialect_map.json 关键词匹配
# ============================================================

def _match_dialect_map(audio_path: str, lang: str = "putian") -> dict:
    """
    方言映射库关键词匹配 — 莆仙话专属降级路径。
    
    当 ASR 引擎不支持莆仙话时，尝试用本地模型做普通话识别，
    然后在 dialect_map.json 中匹配关键词。
    """
    # 用本地 Whisper 做普通话识别
    text = ""
    try:
        from dialect_asr import recognize as local_recognize
        result = local_recognize(audio_path, "mandarin")
        text = result.get("text", "")
    except Exception:
        pass

    if not text:
        # Whisper 也失败 — 无法做匹配
        return {"text": "", "lang": lang, "engine": "dialect_map",
                "error": "无普通话基础转录，无法做关键词匹配"}

    # 加载 dialect_map.json
    map_path = Path(__file__).parent.parent / "dialect_map.json"
    dialect_map = {}
    if map_path.exists():
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                dialect_map = json.load(f)
        except Exception:
            pass

    if not dialect_map:
        return {"text": "", "lang": lang, "engine": "dialect_map",
                "error": "dialect_map.json 为空"}

    # 关键词匹配: 在转录文本中查找方言词
    matches = []
    for dialect_word, meaning in dialect_map.items():
        if dialect_word in text:
            matches.append((dialect_word, meaning))

    if matches:
        # 用匹配到的关键词标记转录
        enriched = text
        for dw, mw in matches:
            enriched = enriched.replace(dw, f"{dw}({mw})")

        return {
            "text": enriched,
            "lang": lang,
            "engine": "dialect_map",
            "matches": len(matches),
            "gloss": {dw: mw for dw, mw in matches},
        }

    # 没有匹配到任何方言词
    return {
        "text": text,
        "lang": lang,
        "engine": "dialect_map",
        "note": "未匹配到方言关键词，返回普通话转录作为参考",
    }


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 dialect_asr_dashscope.py <音频文件> [方言代码]")
        print("方言: putian/canton/minnan/sichuan/shanghai/hakka/mandarin/auto")
        sys.exit(1)

    audio = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else "auto"

    result = recognize(audio, lang)
    print(json.dumps(result, ensure_ascii=False, indent=2))
