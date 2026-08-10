"""莆仙话五层匹配管线。

严格顺序（不可打乱）：
  1. ASR 文字识别（SenseVoice 输出文本）— 由 dialect_asr.py 调用前完成
  2. 误识别映射（program_vocab.json 的 common_misrecognition 精确映射）
  3. 子串/编辑距离（aliases 子串包含，长度≥2；编辑距离 ≤2，手写 DP）
  4. 拼音模糊（program_pronunciation.json 的 char_pinyin + accent_rules.json 口音规则）
  5. DTW 音频匹配（audio_matcher.py MFCC DTW，最后一层兜底）

每层命中即返回节目名并终止；未命中进入下一层；全部失败返回空文本。
每层返回 (program_name, score, layer_name) 供前端使用。
"""

import json
import re
import os
from pathlib import Path
from typing import Optional

# ============================================================
# 路径配置
# ============================================================

_ASR_DIR = Path(__file__).parent
_VOCAB_PATH = _ASR_DIR / "program_vocab.json"
_PRON_PATH = _ASR_DIR / "program_pronunciation.json"
_ACCENT_RULES_PATH = _ASR_DIR / "accent_rules.json"
_WORDS_PATH = _ASR_DIR.parent.parent / "data" / "hinghwa" / "words.json"

# ============================================================
# 数据缓存
# ============================================================

_vocab_cache: Optional[dict] = None
_pron_cache: Optional[dict] = None
_accent_rules_cache: Optional[dict] = None
_char_pinyin_cache: Optional[dict] = None


def _load_vocab() -> dict:
    """加载 program_vocab.json。"""
    global _vocab_cache
    if _vocab_cache is not None:
        return _vocab_cache
    with open(_VOCAB_PATH, "r", encoding="utf-8") as f:
        _vocab_cache = json.load(f)
    return _vocab_cache


def _load_pronunciation() -> dict:
    """加载 program_pronunciation.json。"""
    global _pron_cache
    if _pron_cache is not None:
        return _pron_cache
    with open(_PRON_PATH, "r", encoding="utf-8") as f:
        _pron_cache = json.load(f)
    return _pron_cache


def _load_accent_rules() -> dict:
    """加载 accent_rules.json。"""
    global _accent_rules_cache
    if _accent_rules_cache is not None:
        return _accent_rules_cache
    with open(_ACCENT_RULES_PATH, "r", encoding="utf-8") as f:
        _accent_rules_cache = json.load(f)
    return _accent_rules_cache


def _build_char_pinyin_map() -> dict:
    """从 words.json 构建 字→[拼音] 映射（用于拼音层查询 ASR 文本的拼音）。"""
    global _char_pinyin_cache
    if _char_pinyin_cache is not None:
        return _char_pinyin_cache

    from collections import defaultdict
    char_map = defaultdict(list)

    if not _WORDS_PATH.exists():
        _char_pinyin_cache = {}
        return _char_pinyin_cache

    with open(_WORDS_PATH, "r", encoding="utf-8") as f:
        words = json.load(f)

    for entry in words:
        word = entry.get("word", "")
        pinyin = entry.get("standard_pinyin", "")
        if not word or not pinyin:
            continue
        if len(word) == 1:
            if pinyin not in char_map[word]:
                char_map[word].append(pinyin)
            continue
        pinyin_parts = pinyin.split()
        if len(pinyin_parts) == len(word):
            for char, py in zip(word, pinyin_parts):
                if py and py not in char_map[char]:
                    char_map[char].append(py)

    _char_pinyin_cache = dict(char_map)
    return _char_pinyin_cache


# ============================================================
# 工具函数
# ============================================================

def _clean_text(text: str) -> str:
    """清理文本：去除标点、书名号、空白。"""
    if not text:
        return ""
    text = re.sub(r'[，。！？,\.!?《》\s（）()【】\[\]{}「」""\'\'"\'`]+', '', text)
    return text.strip()


def _edit_distance(s1: str, s2: str) -> int:
    """手写编辑距离（Levenshtein DP）。"""
    m, n = len(s1), len(s2)
    if m == 0:
        return n
    if n == 0:
        return m
    # 滚动数组 DP
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if s1[i - 1] == s2[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(dp[j - 1], dp[j], prev)
            prev = temp
    return dp[n]


def _apply_accent_corrections(text: str, accent: str = "putian") -> str:
    """应用口音纠错规则（accent_rules.json）。"""
    rules = _load_accent_rules()
    accent_data = rules.get("accents", {}).get(accent, {})
    corrections = accent_data.get("corrections", [])

    result = text
    for rule in corrections:
        pattern = rule.get("pattern", "")
        replacement = rule.get("replacement", "")
        if pattern and pattern in result:
            result = result.replace(pattern, replacement)

    # 同时应用仙游口音规则（莆仙话用户可能来自仙游）
    xianyou_data = rules.get("accents", {}).get("xianyou", {})
    xianyou_corrections = xianyou_data.get("corrections", [])
    for rule in xianyou_corrections:
        pattern = rule.get("pattern", "")
        replacement = rule.get("replacement", "")
        if pattern and pattern in result:
            result = result.replace(pattern, replacement)

    return result


def _get_hinghwa_pinyin(text: str) -> list[str]:
    """获取文本的莆仙话拼音音节列表（从 words.json 查询）。"""
    char_map = _build_char_pinyin_map()
    result = []
    for char in text:
        if char in char_map:
            result.append(char_map[char][0])  # 取第一个读音
        else:
            result.append(None)
    return result


def _pinyin_syllable_similarity(s1: str, s2: str) -> float:
    """
    比较两个莆仙话拼音音节的相似度 [0, 1]。

    莆仙话拼音格式如 "sor1", "ce1", "dorng2" 等。
    比较策略：声母模糊 + 韵母相似 + 声调忽略。
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    # 去除声调数字
    s1_base = re.sub(r'\d+$', '', s1)
    s2_base = re.sub(r'\d+$', '', s2)

    if s1_base == s2_base:
        return 0.95  # 声母韵母相同，仅声调不同

    # 莆仙话声母模糊对
    fuzzy_pairs = [
        ("c", "ch"), ("z", "zh"), ("s", "sh"),
        ("d", "t"), ("b", "p"), ("g", "k"),
        ("f", "h"), ("n", "l"),
        ("j", "q"), ("r", "l"),
    ]

    # 提取声母（尝试 2 字母和 1 字母）
    def _get_initial(s: str) -> tuple[str, str]:
        for init in ["zh", "ch", "sh", "ng"]:
            if s.startswith(init):
                return init, s[len(init):]
        if s and s[0] in "bpmfdtnlgkhjqxrzcsyw":
            return s[0], s[1:]
        return "", s

    init1, rest1 = _get_initial(s1_base)
    init2, rest2 = _get_initial(s2_base)

    # 声母匹配（含模糊）
    initial_match = False
    if init1 == init2:
        initial_match = True
    else:
        for a, b in fuzzy_pairs:
            if (init1 == a and init2 == b) or (init1 == b and init2 == a):
                initial_match = True
                break

    if not initial_match:
        return 0.0

    # 韵母相似
    if rest1 == rest2:
        return 0.85

    # 韵母模糊组
    vowel_groups = [
        {"an", "ang", "ang2"},
        {"en", "eng"},
        {"in", "ing"},
        {"on", "ong"},
        {"ai", "ei"},
        {"ao", "ou"},
        {"ia", "ie"},
        {"ua", "uo"},
        {"ue", "ve"},
        {"or", "o"},
        {"orng", "ong"},
        {"dorng", "dung"},
    ]
    for group in vowel_groups:
        if rest1 in group and rest2 in group:
            return 0.75

    return 0.0


def _pinyin_fuzzy_match(text_pinyin: list, canonical_pinyin: list) -> float:
    """
    比较两个拼音音节列表的模糊匹配分数 [0, 1]。

    允许长度差 1（多/少一个音节），要求对应音节都匹配。
    """
    # 过滤掉 None
    t_py = [p for p in text_pinyin if p is not None]
    c_py = [p for p in canonical_pinyin if p is not None]

    if not t_py or not c_py:
        return 0.0

    n1, n2 = len(t_py), len(c_py)

    # 长度差超过 1，不匹配
    if abs(n1 - n2) > 1:
        return 0.0

    # 长度相同：逐音节匹配
    if n1 == n2:
        scores = [_pinyin_syllable_similarity(t_py[i], c_py[i]) for i in range(n1)]
        avg = sum(scores) / n1
        # 至少 n-1 个音节匹配（分数 >= 0.7）
        good_matches = sum(1 for s in scores if s >= 0.7)
        if good_matches >= max(1, n1 - 1):
            return avg
        return 0.0

    # 长度差 1：在较长的列表中跳过一个音节来匹配
    shorter = t_py if n1 < n2 else c_py
    longer = c_py if n1 < n2 else t_py

    best_avg = 0.0
    for skip_pos in range(len(longer)):
        adjusted = longer[:skip_pos] + longer[skip_pos + 1:]
        scores = [_pinyin_syllable_similarity(shorter[i], adjusted[i]) for i in range(len(shorter))]
        avg = sum(scores) / len(shorter)
        good_matches = sum(1 for s in scores if s >= 0.7)
        if good_matches >= max(1, len(shorter) - 1) and avg > best_avg:
            best_avg = avg

    return best_avg


# ============================================================
# 五层匹配主函数
# ============================================================

def match_layers(text: str, audio_path: str = None) -> dict:
    """
    莆仙话五层匹配管线。

    Args:
        text: ASR 识别出的文本（SenseVoice 输出）
        audio_path: 音频文件路径（用于第 5 层 DTW 匹配）

    Returns:
        {
            "program_name": str|None,   # 匹配到的节目名
            "score": float,             # 匹配置信度 [0, 1]
            "layer": str,               # 命中的层级名称
            "text": str,                # 原始文本（匹配后保留）
        }
    """
    text_clean = _clean_text(text)

    # ── 第 2 层：误识别映射（common_misrecognition 精确映射）──
    vocab = _load_vocab()
    for entry in vocab.get("entries", []):
        canonical = entry["canonical"]
        for mis in entry.get("common_misrecognition", []):
            if mis == text_clean or mis == text:
                return {
                    "program_name": canonical,
                    "score": 1.0,
                    "layer": "L2_misrecognition",
                    "text": text,
                }

    # ── 第 3 层：子串/编辑距离 ──
    # 3a. 子串包含（长度≥2）— 两遍扫描：先匹配 canonical，再匹配 alias
    if text_clean and len(text_clean) >= 2:
        # 第一遍：canonical 子串匹配（优先级最高）
        for entry in vocab.get("entries", []):
            canonical = entry["canonical"]
            # canonical 子串包含在 text 中
            if len(canonical) >= 2 and canonical in text_clean:
                return {
                    "program_name": canonical,
                    "score": 0.9,
                    "layer": "L3_substring",
                    "text": text,
                }
            # text 子串包含在 canonical 中
            if len(text_clean) >= 2 and text_clean in canonical:
                return {
                    "program_name": canonical,
                    "score": 0.85,
                    "layer": "L3_substring",
                    "text": text,
                }

        # 第二遍：别名子串匹配（优先级低于 canonical）
        for entry in vocab.get("entries", []):
            canonical = entry["canonical"]
            for alias in entry.get("aliases", []):
                # 只对中文别名做子串匹配
                if not all('\u4e00' <= c <= '\u9fff' for c in alias):
                    continue
                if len(alias) >= 2 and (alias in text_clean or text_clean in alias):
                    return {
                        "program_name": canonical,
                        "score": 0.88,
                        "layer": "L3_substring",
                        "text": text,
                    }

    # 3b. 编辑距离 ≤2（手写 DP）
    if text_clean and len(text_clean) >= 2:
        best_edit_match = None
        best_edit_dist = 3
        for entry in vocab.get("entries", []):
            canonical = entry["canonical"]
            if len(canonical) < 2:
                continue
            # 长度差超过 2 不可能编辑距离 ≤2
            if abs(len(text_clean) - len(canonical)) > 2:
                continue
            dist = _edit_distance(text_clean, canonical)
            if dist <= 2 and dist < best_edit_dist:
                best_edit_dist = dist
                best_edit_match = canonical
            # 也检查别名
            for alias in entry.get("aliases", []):
                if not all('\u4e00' <= c <= '\u9fff' for c in alias):
                    continue
                if len(alias) < 2:
                    continue
                if abs(len(text_clean) - len(alias)) > 2:
                    continue
                dist = _edit_distance(text_clean, alias)
                if dist <= 2 and dist < best_edit_dist:
                    best_edit_dist = dist
                    best_edit_match = canonical

        if best_edit_match:
            # 编辑距离 1 → 0.85, 编辑距离 2 → 0.75
            score = 0.85 if best_edit_dist == 1 else 0.75
            return {
                "program_name": best_edit_match,
                "score": score,
                "layer": "L3_edit_distance",
                "text": text,
            }

    # ── 第 4 层：拼音模糊（program_pronunciation.json + accent_rules.json）──
    # 先应用口音纠错
    corrected_text = _apply_accent_corrections(text_clean, "putian")
    if corrected_text != text_clean:
        # 纠错后重新尝试子串匹配
        for entry in vocab.get("entries", []):
            canonical = entry["canonical"]
            if len(canonical) >= 2 and canonical in corrected_text:
                return {
                    "program_name": canonical,
                    "score": 0.88,
                    "layer": "L4_accent_correction",
                    "text": text,
                }

    # 拼音模糊匹配
    if corrected_text and len(corrected_text) >= 2:
        text_pinyin = _get_hinghwa_pinyin(corrected_text)
        pron = _load_pronunciation()

        # 如果文本中有字符能查到拼音，进行匹配
        if any(p is not None for p in text_pinyin):
            best_pinyin_match = None
            best_pinyin_score = 0.0

            for program_name, pron_data in pron.get("programs", {}).items():
                canonical_pinyin = pron_data.get("char_pinyin", [])
                # 跳过全 null 的节目名
                if not any(p is not None for p in canonical_pinyin):
                    continue

                score = _pinyin_fuzzy_match(text_pinyin, canonical_pinyin)
                if score > best_pinyin_score:
                    best_pinyin_score = score
                    best_pinyin_match = program_name

            # 拼音匹配阈值 0.6
            if best_pinyin_match and best_pinyin_score >= 0.6:
                return {
                    "program_name": best_pinyin_match,
                    "score": best_pinyin_score,
                    "layer": "L4_pinyin_fuzzy",
                    "text": text,
                }

    # ── 第 5 层：DTW 音频匹配（最后一层兜底）──
    if audio_path and os.path.exists(audio_path):
        try:
            from asr.audio_matcher import match as dtw_match
            dtw_name, dtw_score = dtw_match(audio_path)
            if dtw_name and dtw_score > 0:
                return {
                    "program_name": dtw_name,
                    "score": dtw_score,
                    "layer": "L5_dtw_audio",
                    "text": text,
                }
        except Exception as e:
            print(f"  ⚠️ DTW 匹配异常: {e}")

    # 全部失败
    return {
        "program_name": None,
        "score": 0.0,
        "layer": "none",
        "text": text,
    }


def match_text_only(text: str) -> dict:
    """仅执行文字匹配（第 2-4 层），不调用 DTW。用于纯文字场景。"""
    return match_layers(text, audio_path=None)


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    import sys

    test_cases = [
        # 误识层
        ("春操", "春草闯堂"),
        ("请回与客气啊", "状元与乞丐"),
        ("红搂", "红楼梦"),
        ("三锅", "三国演义"),
        ("乾杯", "江梅妃"),
        # 子串/编辑距离
        ("春草", "春草闯堂"),
        ("状元与乞", "状元与乞丐"),
        ("新亭类", "新亭泪"),
        # 拼音层（口音变体：h/f, d/t 混淆）
        ("江梅飞", "江梅妃"),
        ("绿蒙正", "吕蒙正"),
    ]

    print("=" * 60)
    print("莆仙话五层匹配管线 — 单元测试")
    print("=" * 60)

    passed = 0
    for text, expected in test_cases:
        result = match_text_only(text)
        status = "✅" if result["program_name"] == expected else "❌"
        if result["program_name"] == expected:
            passed += 1
        print(f"  {status} '{text}' → {result['program_name']} (score={result['score']:.2f}, layer={result['layer']})  期望: {expected}")

    print(f"\n结果: {passed}/{len(test_cases)} 通过")
