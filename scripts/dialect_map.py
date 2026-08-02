#!/usr/bin/env python3
"""
方言 ↔ 中文映射库

存储您说的方言词汇和对应中文含义，自动累积学习。
"""
import json
import os
from pathlib import Path
from typing import Optional

MAP_PATH = Path(__file__).parent.parent / "dialect_map.json"

# 默认映射（内置常用方言词汇示例）
DEFAULT_MAP = {
    # 粤语
    "食咗饭未": "吃饭了吗",
    "唔该": "谢谢/麻烦你了",
    "早晨": "早上好",
    "几多钱": "多少钱",
    "边度": "哪里",
    "点解": "为什么",
    "好嘢": "好东西/好厉害",
    "得闲": "有空",
    "倾偈": "聊天",
    "返工": "上班",
    # 四川话
    "啥子": "什么",
    "巴适": "舒服/好",
    "要得": "好的/行",
    "雄起": "加油",
    "搞啥子": "干什么",
    # 闽南语
    "食饱未": "吃饱了吗",
    "多谢": "谢谢",
    "暗安": "晚安",
    "好勢": "好了/可以了",
    # 莆仙话（莆仙语）
    "食盲": "吃饭",
    "困盲": "睡觉",
    "我罩汝": "我喜欢你",
    "去住底": "去哪里",
    "几钱": "多少钱",
    "罩": "爱/喜欢",
    "行": "走",
    "汝": "你",
    "我": "我",
}


def load() -> dict:
    """加载方言映射库"""
    if MAP_PATH.exists():
        with open(MAP_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        # 首次使用：写入默认映射
        save(DEFAULT_MAP)
        return dict(DEFAULT_MAP)


def save(mapping: dict):
    """保存方言映射库"""
    MAP_PATH.parent.mkdir(exist_ok=True)
    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"💾 方言映射库已保存 ({len(mapping)} 条)")


def lookup(dialect_text: str) -> Optional[str]:
    """
    查方言 → 中文
    
    返回对应的中文含义，未找到返回 None
    """
    mapping = load()
    return mapping.get(dialect_text.strip())


def add(dialect_text: str, chinese_meaning: str):
    """
    新增方言映射
    
    参数:
        dialect_text: 方言原文
        chinese_meaning: 对应的中文含义
    """
    mapping = load()
    key = dialect_text.strip()
    if key in mapping and mapping[key] == chinese_meaning:
        print(f"  ✓ 已存在: {key} → {chinese_meaning}")
        return

    mapping[key] = chinese_meaning
    save(mapping)
    print(f"  ✚ 新增映射: {key} → {chinese_meaning}")


def search(keyword: str) -> list[tuple[str, str]]:
    """搜索方言或中文"""
    mapping = load()
    results = []
    for dialect, chinese in mapping.items():
        if keyword in dialect or keyword in chinese:
            results.append((dialect, chinese))
    return results


def stats() -> dict:
    """统计信息"""
    mapping = load()
    return {
        "total": len(mapping),
        "file": str(MAP_PATH),
    }


def translate(text: str) -> str:
    """
    尽可能翻译一段方言文本为中文
    
    逐词匹配映射库，未匹配的保留原文
    """
    mapping = load()
    # 先尝试整句匹配
    if text.strip() in mapping:
        return mapping[text.strip()]

    # 再逐词匹配
    words = text.split()
    translated_words = []
    for word in words:
        if word in mapping:
            translated_words.append(mapping[word])
        else:
            translated_words.append(word)

    return " ".join(translated_words)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(f"方言映射库: {MAP_PATH}")
        s = stats()
        print(f"总条目: {s['total']}")
        print("\n用法:")
        print("  查询: python3 dialect_map.py 查 <方言词>")
        print("  新增: python3 dialect_map.py 加 <方言> <中文>")
        print("  搜索: python3 dialect_map.py 搜 <关键词>")
        print("  翻译: python3 dialect_map.py 翻 <方言句子>")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "查" and len(sys.argv) > 2:
        result = lookup(sys.argv[2])
        if result:
            print(f"{sys.argv[2]} → {result}")
        else:
            print(f"未找到: {sys.argv[2]}")

    elif cmd == "加" and len(sys.argv) > 3:
        add(sys.argv[2], sys.argv[3])

    elif cmd == "搜" and len(sys.argv) > 2:
        results = search(sys.argv[2])
        for d, c in results:
            print(f"  {d} → {c}")
        if not results:
            print("无结果")

    elif cmd == "翻" and len(sys.argv) > 2:
        result = translate(" ".join(sys.argv[2:]))
        print(result)

    elif cmd == "统计":
        s = stats()
        print(f"总条目: {s['total']}")
        print(f"文件: {s['file']}")

    else:
        print(f"未知命令: {cmd}")
