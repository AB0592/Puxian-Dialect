#!/usr/bin/env python3
"""
GLM-ASR-2512 引擎 — 智谱方言语音识别

方案: 智谱 GLM-ASR-2512 REST API
  - 支持方言: 粤语/闽南语/上海话/四川话 + 普通话/英语等
  - CER 0.0717, 支持自定义词汇字典
  - 成本: 按 tokens 计费

方言映射 (GLM-ASR):
  - canton   → yue   (粤语)
  - minnan   → nan   (闽南语) 
  - shanghai → wuu   (上海话/吴语)
  - sichuan  → zh    (四川话, 语音特征识别)
  - putian   → zh    (莆仙话, 不在原生支持列表, 降级为普通话语音特征)
  - mandarin → zh    (普通话)

Pre-requisites:
  - GLM_API_KEY / ZAI_API_KEY / Z_AI_API_KEY 之一必须在 .env 中
  - pip3 install requests
"""

import os
import json
import base64
from pathlib import Path
from typing import Optional

# ============================================================
# 配置
# ============================================================

# 国内智谱 API 地址
GLM_ASR_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
GLM_ASR_ENDPOINT = "/audio/transcriptions"  # OpenAI 兼容格式 (multipart file upload)

# 方言到 GLM ASR 语言代码映射
LANG_TO_GLM = {
    "canton":   "yue",
    "minnan":   "nan",
    "shanghai": "wuu",
    "sichuan":  "zh",
    "putian":   "zh",    # 无原生支持, 依赖语音特征
    "mandarin": "zh",
    "hakka":    "zh",    # 无原生支持
    "auto":     "auto",
}

# 全局缓存
_GLM_API_KEY: Optional[str] = None
_GLM_ASR_MODEL = "glm-asr-2512"


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


def _check_api_key() -> bool:
    """检查 API Key 是否可用"""
    return bool(_get_api_key())


# ============================================================
# GLM-ASR-2512 语音识别
# ============================================================

def _recognize_glm_asr(audio_path: str, lang: str = "auto") -> dict:
    """
    使用 GLM-ASR-2512 做语音识别。
    
    GLM-ASR API 接受 base64 编码的音频或音频 URL。
    这里用本地文件 base64 编码方式。
    """
    import requests

    api_key = _get_api_key()
    if not api_key:
        return {
            "text": "",
            "lang": "unknown",
            "engine": "glm-asr-2512",
            "error": "GLM_API_KEY 未配置, 请去 open.bigmodel.cn 注册获取"
        }

    if not os.path.exists(audio_path):
        return {
            "text": "",
            "lang": "unknown",
            "engine": "glm-asr-2512",
            "error": f"文件不存在: {audio_path}"
        }

    glm_lang = LANG_TO_GLM.get(lang, "auto")
    fname = os.path.basename(audio_path)

    # 检查文件大小

    try:
        # 使用 multipart file upload (OpenAI 兼容格式)
        ext = os.path.splitext(audio_path)[1].lstrip(".") or "wav"
        mime = "audio/wav" if ext == "wav" else f"audio/{ext}"
        
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"{GLM_ASR_BASE_URL}{GLM_ASR_ENDPOINT}",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (fname, f, mime)},
                data={
                    "model": _GLM_ASR_MODEL,
                    "language": glm_lang if glm_lang != "auto" else "zh",
                },
                timeout=60,
            )

        if resp.status_code == 200:
            data = resp.json()
            text = data.get("text", "")
            if text:
                print(f"  -> 结果: {text[:100]}")
                return {
                    "text": text.strip(),
                    "lang": glm_lang,
                    "engine": f"glm-asr-2512",
                    "raw": data,
                }
            return {
                "text": "",
                "lang": glm_lang,
                "engine": "glm-asr-2512",
                "error": "无识别结果"
            }
        else:
            err_text = resp.text[:300]
            print(f"  -> GLM-ASR 失败 ({resp.status_code}): {err_text}")
            return {
                "text": "",
                "lang": glm_lang,
                "engine": "glm-asr-2512",
                "error": f"HTTP {resp.status_code}: {err_text}"
            }

    except requests.exceptions.Timeout:
        print(f"  -> GLM-ASR 超时")
        return {
            "text": "",
            "lang": glm_lang,
            "engine": "glm-asr-2512",
            "error": "请求超时 (60s)"
        }
    except requests.exceptions.ConnectionError as e:
        print(f"  -> GLM-ASR 连接失败: {e}")
        return {
            "text": "",
            "lang": glm_lang,
            "engine": "glm-asr-2512",
            "error": f"网络连接失败: {str(e)[:200]}"
        }
    except Exception as e:
        print(f"  -> GLM-ASR 异常: {e}")
        return {
            "text": "",
            "lang": glm_lang,
            "engine": "glm-asr-2512",
            "error": str(e)[:300]
        }


# ============================================================
# 自定义词汇字典注入
# ============================================================

def build_custom_vocabulary(dialect_map_path: str = None) -> list:
    """
    从 dialect_map.json 构建自定义词汇列表，
    注入到 GLM-ASR 的自定义词典中，提升方言词识别准确率。
    """
    if dialect_map_path is None:
        dialect_map_path = str(
            Path(__file__).parent.parent / "dialect_map.json"
        )

    custom_words = []
    if not os.path.exists(dialect_map_path):
        return custom_words

    try:
        with open(dialect_map_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 取高频词 (超过 min_chars 的词作为关键词汇)
        for dialect_word, meaning in data.items():
            if len(dialect_word) >= 2:
                custom_words.append({
                    "word": dialect_word,
                    "weight": min(len(dialect_word), 5),  # 权重基于词长
                })

        # 限制数量 (API 可能有上限)
        if len(custom_words) > 500:
            custom_words = sorted(
                custom_words, key=lambda x: x["weight"], reverse=True
            )[:500]

    except (json.JSONDecodeError, IOError) as e:
        print(f"  -> 加载方言词汇失败: {e}")

    return custom_words


# ============================================================
# 统一入口
# ============================================================

def recognize_glm(audio_path: str, lang: str = "auto") -> dict:
    """
    GLM-ASR 语音识别统一入口。

    返回:
      {
        "text": str,         # 识别文本
        "lang": str,         # 语言代码
        "engine": str,       # 引擎名称
        "error": str or None # 错误信息
      }
    """
    # 检查 API Key
    if not _check_api_key():
        return {
            "text": "",
            "lang": "unknown",
            "engine": "glm-asr-2512",
            "error": "GLM_API_KEY 未配置"
        }

    return _recognize_glm_asr(audio_path, lang)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python3 dialect_asr_glm.py <音频文件> [方言代码]")
        print("方言: canton/minnan/sichuan/shanghai/mandarin/auto")
        print()
        print("API Key 状态:", "已配置" if _check_api_key() else "未配置")
        sys.exit(1)

    audio = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else "auto"

    result = recognize_glm(audio, lang)
    print(json.dumps(result, ensure_ascii=False, indent=2))
