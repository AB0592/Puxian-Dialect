#!/usr/bin/env python3
"""
从 reference.json 提取首批语音库录制素材
输出: data/voice_collection/materials.json
"""
import json, os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROFILE_DIR = SCRIPT_DIR.parent
REF_PATH = PROFILE_DIR / "data" / "hinghwa" / "reference.json"
OUT_DIR = PROFILE_DIR / "data" / "voice_collection"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ref = json.load(open(REF_PATH, 'r', encoding='utf-8'))

# === 1. 单字提取 ===
single_chars = {}
for k, v in ref.items():
    if len(k) == 1:
        single_chars[k] = {
            "word": k,
            "pinyin": v.get("pinyin", ""),
            "ipa": v.get("ipa", ""),
            "definition": (v.get("definition", "") or "")[:80],
            "has_audio": bool(v.get("audio_variants"))
        }

# 常用汉字优先级列表（基于3500常用字）
common_chars = "的一是不了人我在有他到和我们大来上他这出会可她个们中为因所其得家去学地子小多天时行看发成过对下着生么没都好就还把又很让做爱开心起工作发来用得着会说好看父母想知正道然前后面门问活头身长手足口目耳鼻牙心肝肺肠胃肾脾胆眼舌脸额头颈肩膀胸背腰腿脚掌指臂肘腕膝踝肤毛发皮肤筋骨肉血脉泪汗涕唾沫尿屎屁话词语句文字笔墨纸砚书本册页篇章段落节行列点线面体方形圆角球盒包袋箱柜桌椅子板凳床铺被褥枕席帘帐幕屏蔽障隔墙壁门窗框锁钥匙链环钩针线绳带扣结纽扣袋包袱箱匣笼罐瓶碗盘碟杯筷刀叉勺铲锅壶炉灶台梯桥路街道巷弄村镇城国家省市区县乡山河湖海江溪泉瀑布渊池井渠沟坑洞谷岭峰崖岸滩沙石泥尘灰火烟云雾雨雪霜露冰雹电闪雷电鸣鼓钟铃一二三四五六七八九十百千万亿"

priority_chars = []
seen_words = set()

# 优先：常用汉字且存在于 reference.json
for c in common_chars:
    if c in single_chars and c not in seen_words:
        priority_chars.append(single_chars[c])
        seen_words.add(c)

# 其次：有音频的单字
for k, v in sorted(single_chars.items()):
    if k not in seen_words and v["has_audio"]:
        priority_chars.append(v)
        seen_words.add(k)

# 补满500
for k, v in sorted(single_chars.items()):
    if k not in seen_words and len(priority_chars) < 500:
        priority_chars.append(v)
        seen_words.add(k)

# === 2. 双字词提取 ===
two_char_words = {}
for k, v in ref.items():
    if len(k) == 2:
        two_char_words[k] = {
            "word": k,
            "pinyin": v.get("pinyin", ""),
            "ipa": v.get("ipa", ""),
            "definition": (v.get("definition", "") or "")[:80],
            "has_audio": bool(v.get("audio_variants"))
        }

# 优先有音频的词，补满400
priority_words = []
seen_words.clear()
for k, v in sorted(two_char_words.items(), key=lambda x: -x[1]["has_audio"]):
    if k not in seen_words and len(priority_words) < 400:
        priority_words.append(v)
        seen_words.add(k)

# === 3. 常用句子（固定编写，基于日常场景）===
sentences = [
    {"word": "汝好", "pinyin": "ly3 hor3", "ipa": "", "definition": "你好"},
    {"word": "食盲未", "pinyin": "sih6 mang5 mui5", "ipa": "", "definition": "吃饭了吗"},
    {"word": "困盲", "pinyin": "kong5 mang5", "ipa": "", "definition": "睡觉"},
    {"word": "去底位", "pinyin": "ky5 dai3 wei4", "ipa": "", "definition": "去哪里"},
    {"word": "几钱", "pinyin": "gui3 jing5", "ipa": "", "definition": "多少钱"},
    {"word": "好势", "pinyin": "ho3 se5", "ipa": "", "definition": "好了/可以了"},
    {"word": "多谢", "pinyin": "duo1 sia5", "ipa": "", "definition": "谢谢"},
    {"word": "无客气", "pinyin": "bo3 keh5 ki5", "ipa": "", "definition": "不客气"},
    {"word": "失礼", "pinyin": "sih6 le3", "ipa": "", "definition": "对不起/失礼了"},
    {"word": "是毋是", "pinyin": "si6 m5 si6", "ipa": "", "definition": "是不是"},
    {"word": "有毋有", "pinyin": "u3 m5 u3", "ipa": "", "definition": "有没有"},
    {"word": "做甚物", "pinyin": "zoh5 sim6 mue5", "ipa": "", "definition": "干什么"},
    {"word": "底时", "pinyin": "dai3 si6", "ipa": "", "definition": "什么时候"},
    {"word": "日安", "pinyin": "dih6 ang1", "ipa": "", "definition": "你好/日安"},
    {"word": "好毋好", "pinyin": "ho3 m5 ho3", "ipa": "", "definition": "好不好"},
    {"word": "我罩汝", "pinyin": "gua3 zio5 ly3", "ipa": "", "definition": "我喜欢你"},
    {"word": "食盲", "pinyin": "sih6 mang5", "ipa": "", "definition": "吃饭"},
    {"word": "好喫", "pinyin": "ho3 kih6", "ipa": "", "definition": "好吃"},
    {"word": "好睇", "pinyin": "ho3 tai3", "ipa": "", "definition": "好看"},
    {"word": "大聲", "pinyin": "dua5 siah1", "ipa": "", "definition": "大声"},
    {"word": "暗安", "pinyin": "am5 ang1", "ipa": "", "definition": "晚安"},
    {"word": "頭先", "pinyin": "tau5 seng1", "ipa": "", "definition": "刚才"},
    {"word": "今旦", "pinyin": "ging1 duah5", "ipa": "", "definition": "今天"},
    {"word": "明日", "pinyin": "ming5 dih6", "ipa": "", "definition": "明天"},
    {"word": "昨日", "pinyin": "zoh6 dih6", "ipa": "", "definition": "昨天"},
    {"word": "儂", "pinyin": "nang5", "ipa": "", "definition": "人"},
    {"word": "厝", "pinyin": "cou5", "ipa": "", "definition": "家/房子"},
    {"word": "轉厝", "pinyin": "dng5 cou5", "ipa": "", "definition": "回家"},
    {"word": "看戲", "pinyin": "kua3 hi5", "ipa": "", "definition": "看戏"},
    {"word": "聽曲", "pinyin": "tia1 keh6", "ipa": "", "definition": "听曲"},
    {"word": "真好", "pinyin": "jing1 ho3", "ipa": "", "definition": "很好"},
    {"word": "真𠢕", "pinyin": "jing1 gao5", "ipa": "", "definition": "很厉害"},
    {"word": "辛苦", "pinyin": "sing1 ko3", "ipa": "", "definition": "辛苦"},
    {"word": "加油", "pinyin": "ga1 yiu5", "ipa": "", "definition": "加油"},
    {"word": "等下", "pinyin": "dang3 ha4", "ipa": "", "definition": "等一下"},
    {"word": "行路", "pinyin": "gia5 lou4", "ipa": "", "definition": "走路"},
    {"word": "坐車", "pinyin": "so4 cia1", "ipa": "", "definition": "坐车"},
]

# === 输出 ===
materials = {
    "version": "1.0",
    "chars": priority_chars[:500],
    "words": priority_words[:400],
    "sentences": sentences,
    "total_chars": len(priority_chars[:500]),
    "total_words": len(priority_words[:400]),
    "total_sentences": len(sentences),
    "grand_total": len(priority_chars[:500]) + len(priority_words[:400]) + len(sentences)
}

out_path = OUT_DIR / "materials.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(materials, f, ensure_ascii=False, indent=2)

with_audio_chars = sum(1 for c in priority_chars[:500] if c["has_audio"])
with_audio_words = sum(1 for w in priority_words[:400] if w["has_audio"])

print(f"素材生成完成:")
print(f"  单字: {len(priority_chars[:500])} 个 (含音频 {with_audio_chars})")
print(f"  双字词: {len(priority_words[:400])} 个 (含音频 {with_audio_words})")
print(f"  句子: {len(sentences)} 句")
print(f"  总计: {materials['grand_total']} 条")
print(f"  输出: {out_path}")
