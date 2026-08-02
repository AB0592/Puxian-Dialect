#!/usr/bin/env python3
"""
方言语音合成模块 — 多引擎支持

引擎优先级（自动降级）:
  1. DashScope CosyVoice API（阿里云，方言支持好）
  2. Edge TTS（已配置，普通话 fallback）
"""
import os
import json
import requests
import tempfile
from pathlib import Path

# 加载 .env
ENV_PATH = Path(__file__).parent.parent / ".env"
if ENV_PATH.exists():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# 方言 → CosyVoice 可用音色
DIALECT_VOICES = {
    "粤语":   "cosyvoice-v1",
    "闽南语": "cosyvoice-v1",
    "莆仙话": "cosyvoice-v1",
    "四川话": "cosyvoice-v1",
    "上海话": "cosyvoice-v1",
    "普通话": "cosyvoice-v1",
    "auto":   "cosyvoice-v1",
}


def cosyvoice_tts(text: str, lang_hint: str = "auto") -> str | None:
    """
    DashScope CosyVoice API 语音合成
    
    参数:
        text: 要朗读的文字
        lang_hint: 方言提示
    
    返回:
        音频文件路径，或 None（失败）
    """
    if not DASHSCOPE_API_KEY:
        print("⚠ 无 DASHSCOPE_API_KEY，跳过 CosyVoice")
        return None

    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2audio/voicesynthesis"
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }

    body = {
        "model": "cosyvoice-v1",
        "input": {
            "text": text,
        },
        "parameters": {
            "text_type": "PlainText",
        }
    }

    # 方言优化 — CosyVoice 支持用粤语 prompt 优化发音
    if lang_hint in ("粤语", "canton"):
        body["parameters"]["prompt"] = "请用粤语朗读，发音准确"
    elif lang_hint in ("四川话", "sichuan"):
        body["parameters"]["prompt"] = "请用四川方言朗读"

    print(f"🔊 CosyVoice TTS: [{lang_hint}] {text[:50]}...")

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=60)
        if resp.status_code == 200:
            # 保存音频
            out_dir = Path(__file__).parent.parent / "audio_output"
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"tts_{hash(text)}.mp3"
            with open(out_path, "wb") as f:
                f.write(resp.content)
            print(f"  ✅ 音频已保存: {out_path}")
            return str(out_path)
        else:
            print(f"  ⚠ CosyVoice API 返回 {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"  ⚠ CosyVoice 请求失败: {e}")
        return None


def edge_tts_fallback(text: str, lang: str = "zh-CN") -> str | None:
    """
    Edge TTS fallback（普通话）
    """
    print(f"🔊 Edge TTS fallback: {text[:50]}...")
    try:
        import subprocess
        out_dir = Path(__file__).parent.parent / "audio_output"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"edge_tts_{hash(text)}.mp3"

        # 使用 edge-tts CLI（Hermes 内置配置）
        cmd = [
            "edge-tts",
            "--voice", "zh-CN-XiaoxiaoNeural",
            "--text", text,
            "--write-media", str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print(f"  ✅ Edge TTS 音频: {out_path}")
            return str(out_path)
        else:
            print(f"  ⚠ Edge TTS 失败: {result.stderr[:200]}")
            return None
    except Exception as e:
        print(f"  ⚠ Edge TTS 异常: {e}")
        return None


def synthesize(text: str, dialect_hint: str = "auto") -> str | None:
    """
    多引擎语音合成（自动降级）
    
    返回音频文件路径，全部失败返回 None
    """
    # 1. CosyVoice（支持方言）
    audio = cosyvoice_tts(text, dialect_hint)
    if audio:
        return audio

    # 2. Edge TTS fallback
    audio = edge_tts_fallback(text)
    if audio:
        return audio

    print("❌ 所有 TTS 引擎均失败")
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 dialect_tts.py <文本> [方言代码]")
        print("方言: canton(粤语) sichuan(四川话) auto(自动)")
        sys.exit(1)

    text = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else "auto"
    result = synthesize(text, lang)
    if result:
        print(f"✅ 输出音频: {result}")
    else:
        print("❌ 合成失败")
