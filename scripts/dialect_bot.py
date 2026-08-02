#!/usr/bin/env python3
"""
方言助手主程序 — 方言语音 → 中文指令 → 执行 → 方言语音回复

工作流程:
  1. 接收方言语音文件 (.wav/.mp3/.m4a)
  2. SenseVoice ASR → 方言文字
  3. 查方言映射库 → 中文指令
  4. Hermes Agent / LLM 执行
  5. CosyVoice TTS → 方言语音输出
"""
import sys
import json
import os
from pathlib import Path

# 加入脚本目录
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from dialect_asr import recognize as asr_recognize
from dialect_tts import synthesize as tts_synthesize
from dialect_map import lookup as map_lookup, add as map_add, translate as map_translate, stats as map_stats


# ============ 语言标签映射 ============
LANG_NAMES = {
    "canton":  "粤语",
    "minnan":  "闽南语",
    "putian":  "莆仙话",
    "sichuan": "四川话",
    "shanghai": "上海话",
    "hakka":   "客家语",
    "mandarin": "普通话",
    "auto":    "自动",
}


def process_voice(audio_path: str, lang_hint: str = "auto", verbose: bool = True) -> dict:
    """
    处理一条方言语音指令
    
    返回:
        {
            "dialect_text": 识别的方言文字,
            "language": 检测到的语言,
            "chinese": 翻译后的中文,
            "audio_output": 回复音频路径(可选),
            "new_mappings": 新增的映射数量,
        }
    """
    result = {
        "dialect_text": "",
        "language": "unknown",
        "chinese": "",
        "audio_output": None,
        "new_mappings": 0,
        "steps": [],
    }

    # === Step 1: ASR 识别 ===
    if verbose:
        print(f"\n{'='*50}")
        print(f"🎤 Step 1: 方言语音识别")
        print(f"{'='*50}")

    asr_result = asr_recognize(audio_path, lang_hint)
    dialect_text = asr_result.get("text", "")
    detected_lang = asr_result.get("lang", "unknown")

    result["dialect_text"] = dialect_text
    result["language"] = detected_lang
    result["steps"].append({
        "step": "ASR",
        "input": audio_path,
        "output": dialect_text,
        "lang": detected_lang,
    })

    if not dialect_text:
        print("⚠ 未能识别出语音内容")
        return result

    # === Step 2: 方言 → 中文翻译 ===
    if verbose:
        print(f"\n{'='*50}")
        print(f"📖 Step 2: 方言 → 中文翻译")
        print(f"{'='*50}")

    chinese = map_translate(dialect_text)
    if chinese == dialect_text:
        # 没翻译出差异，询问用户是否要新增映射
        result["chinese"] = dialect_text
        result["needs_mapping"] = True
        if verbose:
            print(f"  ⚠ 未找到匹配的方言映射")
            print(f"  原文: {dialect_text}")
    else:
        result["chinese"] = chinese
        if verbose:
            print(f"  方言: {dialect_text}")
            print(f"  中文: {chinese}")

    result["steps"].append({
        "step": "translate",
        "dialect_text": dialect_text,
        "chinese": chinese,
    })

    return result


def process_text(dialect_text: str, chinese_meaning: str = None) -> dict:
    """
    处理一条文字方言指令（用于直接输入文字而非语音）
    
    参数:
        dialect_text: 方言文字
        chinese_meaning: 对应的中文（可选，如果没有则尝试查映射库）
    """
    result = {
        "dialect_text": dialect_text,
        "chinese": chinese_meaning or map_translate(dialect_text),
        "needs_mapping": not chinese_meaning and map_lookup(dialect_text) is None,
    }

    # 如果用户提供了中文含义，存入映射库
    if chinese_meaning and chinese_meaning != dialect_text:
        map_add(dialect_text, chinese_meaning)

    return result


def generate_reply(chinese_text: str, dialect_lang: str = "auto") -> dict:
    """
    生成回复并合成方言语音
    
    返回:
        {
            "text": 中文回复,
            "audio": 方言语音音频路径,
            "engine": 使用的 TTS 引擎,
        }
    """
    # 实际使用时，这里会调用 Hermes Agent / LLM
    # 目前返回一个占位回复
    reply_text = f"已收到您的指令: {chinese_text}"

    audio = tts_synthesize(reply_text, dialect_lang)
    engine = "cosyvoice" if audio and "cosy" in str(audio).lower() else "edge"

    return {
        "text": reply_text,
        "audio": audio,
        "engine": engine,
    }


def print_help():
    print("""方言助手 — Dialect Bot

用法:
  # 处理语音文件
  python3 dialect_bot.py voice <音频文件> [方言代码]

  # 处理文字（方言→中文）
  python3 dialect_bot.py text <方言文字> [中文含义]

  # 新增方言映射
  python3 dialect_bot.py learn <方言> <中文含义>

  # 查看统计
  python3 dialect_bot.py stats

方言代码: canton(粤语) minnan(闽南语) sichuan(四川话) auto(自动)
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_help()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "voice" and len(sys.argv) >= 3:
        audio = sys.argv[2]
        lang = sys.argv[3] if len(sys.argv) > 3 else "auto"
        result = process_voice(audio, lang)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        # 如果找到了中文，试一下 TTS 回复
        if result.get("chinese") and result["chinese"] != result["dialect_text"]:
            print(f"\n{'='*50}")
            print("🔊 生成语音回复...")
            reply = generate_reply(result["chinese"], result.get("language", "auto"))
            print(f"  回复: {reply['text']}")
            if reply["audio"]:
                print(f"  音频: {reply['audio']}")
                print(f"  引擎: {reply['engine']}")
        elif result.get("needs_mapping"):
            print(f"\n💡 提示: 这条方言还没录入映射库")
            print(f"  可以用以下命令录入:")
            print(f"  python3 dialect_bot.py learn \"{result['dialect_text']}\" \"对应的中文意思\"")

    elif cmd == "text" and len(sys.argv) >= 3:
        dialect = sys.argv[2]
        meaning = sys.argv[3] if len(sys.argv) > 3 else None
        result = process_text(dialect, meaning)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "learn" and len(sys.argv) >= 4:
        map_add(sys.argv[2], sys.argv[3])

    elif cmd == "stats":
        s = map_stats()
        print(json.dumps(s, ensure_ascii=False, indent=2))

    else:
        print_help()
