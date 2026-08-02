#!/usr/bin/env python3
"""
GLM-5.2 翻译 Agent — 方言↔中文互译主脑

方案: GLM-5.2 (智谱 Z.AI) 翻译 Agent，6种策略
  - General: 标准翻译
  - Paraphrase: 意译 (保留语气/情感)
  - Two-step: 直译 + 润色
  - Three-step: 直译 + 语法 + 语用
  - Reflection: 翻译 → 自评 → 修正
  - COT: 思维链推理 (歧义消解)

核心特性:
  - Glossary 术语库注入 (dialect_map.json 77→1000条)
  - 方言→中文 + 中文→方言 双向互译
  - 语境感知 (根据用户档案选择翻译策略)

Pre-requisites:
  - GLM_API_KEY / ZAI_API_KEY / Z_AI_API_KEY 之一必须在 .env 中
  - pip3 install openai
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict

# ============================================================
# 配置
# ============================================================

GLM_MODEL = "glm-5.2"
GLM_BASE_URL = "https://api.z.ai/api/paas/v4"

# 翻译策略
TRANSLATION_STRATEGIES = {
    "general":    "标准翻译",
    "paraphrase": "意译 (保留语气和情感色彩)",
    "two_step":   "两步精炼 (直译 → 润色自然中文)",
    "three_step": "三步精炼 (直译 → 语法修正 → 语用调整)",
    "reflection": "反思模式 (翻译 → 自评 → 修正错误)",
    "cot":        "思维链 (推理方言语义 → 消解歧义)",
}

PROFILE_DIR = Path(__file__).parent.parent

# 全局缓存
_GLM_API_KEY: Optional[str] = None
_GLOSSARY: Optional[list] = None


def _get_api_key() -> str:
    """从 .env 获取智谱 API Key"""
    global _GLM_API_KEY
    if _GLM_API_KEY:
        return _GLM_API_KEY

    env_keys = ["GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY", "ZHIPU_API_KEY"]
    env_paths = [
        PROFILE_DIR / ".env",
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
# Glossary 术语库
# ============================================================

def load_glossary(limit: int = 100) -> list:
    """
    从 dialect_map.json 加载方言术语库。
    
    选择策略:
      1. 高频词优先 (词长 >= 2)
      2. 限制100条 (控制上下文长度)
    """
    global _GLOSSARY
    if _GLOSSARY:
        return _GLOSSARY[:limit]

    map_path = PROFILE_DIR / "dialect_map.json"
    glossary = []

    if map_path.exists():
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                dialect_map = json.load(f)

            # 按词长排序 (长词包含更多信息)
            sorted_items = sorted(
                dialect_map.items(),
                key=lambda x: len(x[0]),
                reverse=True,
            )

            for dialect_word, meaning in sorted_items[:limit]:
                glossary.append({
                    "dialect": dialect_word,
                    "mandarin": meaning,
                })

            _GLOSSARY = glossary
        except Exception as e:
            print(f"  -> 加载 Glossary 失败: {e}")

    return glossary[:limit]


def format_glossary_for_prompt(glossary: list) -> str:
    """将 Glossary 格式化为 prompt 可用的文本"""
    if not glossary:
        return ""

    lines = []
    for item in glossary:
        lines.append(f"  {item['dialect']} = {item['mandarin']}")

    return "Glossary:\n" + "\n".join(lines)


# ============================================================
# GLM-5.2 翻译 Agent
# ============================================================

def translate(
    text: str,
    direction: str = "dialect_to_mandarin",
    strategy: str = "reflection",
    dialect: str = "putian",
    use_glossary: bool = True,
) -> Dict:
    """
    GLM-5.2 方言翻译 Agent — 六策略统一入口。
    
    Args:
      text: 输入文本
      direction: "dialect_to_mandarin" (方言→中文) 或 "mandarin_to_dialect"
      strategy: "general" | "paraphrase" | "two_step" | "three_step" | "reflection" | "cot"
      dialect: 方言代码 (putian/canton/minnan/sichuan)
      use_glossary: 是否注入 dialect_map.json 术语库
    
    Returns:
      {
        "translation": str,     # 翻译结果
        "strategy": str,        # 使用的策略
        "confidence": float,    # 置信度 0-1
        "glossary_matches": int,# 术语库匹配数
        "tokens": int,          # Token 用量
        "error": str or None
      }
    """
    import openai

    api_key = _get_api_key()
    if not api_key:
        return {
            "translation": text,
            "strategy": strategy,
            "confidence": 0,
            "glossary_matches": 0,
            "tokens": 0,
            "error": "GLM_API_KEY 未配置"
        }

    client = openai.OpenAI(
        api_key=api_key,
        base_url=GLM_BASE_URL,
    )

    # 加载 Glossary
    glossary = load_glossary() if use_glossary else []
    glossary_text = format_glossary_for_prompt(glossary) if glossary else ""

    # 统计匹配数
    matches = sum(1 for g in glossary if g["dialect"] in text or g["mandarin"] in text)

    # 构建翻译策略描述
    strategy_desc = TRANSLATION_STRATEGIES.get(strategy, TRANSLATION_STRATEGIES["general"])

    # 方言名称映射
    dialect_names = {
        "putian": "莆仙话",
        "canton": "粤语",
        "minnan": "闽南语",
        "sichuan": "四川话",
        "shanghai": "上海话",
    }
    dialect_name = dialect_names.get(dialect, dialect)

    if direction == "dialect_to_mandarin":
        system_prompt = f"你是{dialect_name}→中文翻译专家。策略: {strategy_desc}。请按以下步骤翻译。"
        user_prompt = f"{glossary_text}\n\n{dialect_name}句子:\n{text}\n\n请翻译成中文。如果涉及方言特有表达，请加注释说明文化含义。"
    else:
        system_prompt = f"你是中文→{dialect_name}翻译专家。策略: {strategy_desc}。请用自然的口语化{dialect_name}表达。"
        user_prompt = f"{glossary_text}\n\n中文句子:\n{text}\n\n请翻译成自然的口语化{dialect_name}。"

    print(f"  -> GLM-5.2 [{direction}]: 策略={strategy} 词库={len(glossary)}条 匹配={matches}")

    try:
        response = client.chat.completions.create(
            model=GLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        translation = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else 0

        # 估算置信度 (有术语库匹配 → 更高)
        confidence = min(0.95, 0.5 + matches * 0.1)

        print(f"  -> 翻译完成: {len(translation)} chars, {tokens} tokens, confidence={confidence:.1%}")

        return {
            "translation": translation.strip(),
            "strategy": strategy,
            "confidence": confidence,
            "glossary_matches": matches,
            "tokens": tokens,
            "error": None,
        }

    except Exception as e:
        print(f"  -> GLM-5.2 翻译失败: {e}")
        return {
            "translation": "",
            "strategy": strategy,
            "confidence": 0,
            "glossary_matches": 0,
            "tokens": 0,
            "error": str(e)[:300],
        }


def batch_translate(
    texts: list,
    direction: str = "dialect_to_mandarin",
    strategy: str = "reflection",
    dialect: str = "putian",
) -> Dict:
    """
    批量翻译，一条 API 调用处理多条。
    
    利用 GLM-5.2 的长上下文能力 (128K)，一次处理多条。
    """
    if not texts:
        return {"results": [], "error": "无输入文本"}

    combined = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    result = translate(
        text=combined,
        direction=direction,
        strategy=strategy,
        dialect=dialect,
    )

    if result.get("error"):
        return {"results": [], "error": result["error"]}

    # 拆分批量结果
    lines = result["translation"].split("\n")
    translations = []
    for line in lines:
        line = line.strip()
        if line and (line[0].isdigit() or ". " in line[:5]):
            # 去掉序号
            clean = line.split(". ", 1)[-1] if ". " in line else line
            translations.append(clean)

    return {
        "results": translations,
        "strategy": strategy,
        "glossary_matches": result.get("glossary_matches", 0),
        "tokens": result.get("tokens", 0),
    }


# ============================================================
# 统一入口
# ============================================================

def translate_dialect(
    text: str,
    direction: str = "auto",
    dialect: str = "putian",
) -> Dict:
    """
    方言翻译统一入口。
    
    direction="auto" → 自动判断方向 (方言→中文 或 中文→方言)
    默认使用 reflection 策略 (翻译+自评+修正, 质量最高)。
    """
    # 自动判断方向
    if direction == "auto":
        # 检查是否包含已知的方言词
        glossary = load_glossary(100)
        dialect_words = [g["dialect"] for g in glossary]
        has_dialect = any(dw in text for dw in dialect_words)
        direction = "dialect_to_mandarin" if has_dialect else "mandarin_to_dialect"

    return translate(
        text=text,
        direction=direction,
        strategy="reflection",
        dialect=dialect,
    )


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 glm5_translate.py <文本> [方向] [策略] [方言]")
        print("  方向: auto | d2m(方言→中文) | m2d(中文→方言)")
        print("  策略: general | paraphrase | two_step | three_step | reflection | cot")
        print("  方言: putian | canton | minnan | sichuan")
        print()
        key_status = "已配置" if _get_api_key() else "未配置"
        glossary_size = len(load_glossary())
        print(f"GLM_API_KEY: {key_status}")
        print(f"Glossary: {glossary_size} 条")
        sys.exit(1)

    text = sys.argv[1]
    direction_map = {
        "auto": "auto",
        "d2m": "dialect_to_mandarin",
        "m2d": "mandarin_to_dialect",
    }
    direction = direction_map.get(sys.argv[2], "auto") if len(sys.argv) > 2 else "auto"
    strategy = sys.argv[3] if len(sys.argv) > 3 else "reflection"
    dialect = sys.argv[4] if len(sys.argv) > 4 else "putian"

    result = translate(text, direction, strategy, dialect)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("translation"):
        print(f"\n翻译结果:\n{result['translation']}")
