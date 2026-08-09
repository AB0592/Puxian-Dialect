"""节目名规范化与候选重排序。

当 scene == "program_search" 时，对 ASR 识别文本做节目名匹配：
  1. 加载 program_vocab.json
  2. 对 text 和每个 candidate.text 做模糊匹配
     a. 精确匹配（含大小写不敏感）
     b. 子串匹配
     c. 编辑距离 ≤ 2 的汉字模糊匹配
     d. 拼音模糊匹配（考虑莆仙方言发音特点）
  3. 匹配到 canonical → 作为 normalized_text 返回
  4. 重排序 candidates：匹配 canonical 的排前面
  5. needs_confirmation = (最高 confidence < 0.8) or (多个候选 confidence > 0.5)

当 scene != "program_search" 时，直接返回原 text，不做规范化。
"""

import json
from pathlib import Path
from typing import Optional

# ============================================================
# 词表缓存
# ============================================================

_VOCAB_CACHE: Optional[dict] = None
_VOCAB_PATH = Path(__file__).parent / "program_vocab.json"


def _load_vocab() -> dict:
    """加载 program_vocab.json，带缓存。"""
    global _VOCAB_CACHE
    if _VOCAB_CACHE is not None:
        return _VOCAB_CACHE

    if not _VOCAB_PATH.exists():
        _VOCAB_CACHE = {"entries": []}
        return _VOCAB_CACHE

    with open(_VOCAB_PATH, "r", encoding="utf-8") as f:
        _VOCAB_CACHE = json.load(f)

    return _VOCAB_CACHE


def _build_lookup_index(vocab: dict) -> dict:
    """
    构建查找索引：{alias_or_canonical_or_misrecognition -> canonical}

    用于 O(1) 精确匹配。
    """
    index = {}
    for entry in vocab.get("entries", []):
        canonical = entry["canonical"]
        # canonical 自身
        index[canonical] = canonical
        index[canonical.lower()] = canonical
        # aliases
        for alias in entry.get("aliases", []):
            index[alias] = canonical
            index[alias.lower()] = canonical
        # common_misrecognition（也能匹配到 canonical）
        for mis in entry.get("common_misrecognition", []):
            index[mis] = canonical
            index[mis.lower()] = canonical
    return index


def _edit_distance(s1: str, s2: str) -> int:
    """计算两个字符串的编辑距离（Levenshtein）。"""
    m, n = len(s1), len(s2)
    if m == 0:
        return n
    if n == 0:
        return m

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


# ============================================================
# 拼音模糊匹配（核心改进）
# ============================================================

# 拼音声母列表（长在前，确保 zh/ch/sh 优先于 z/c/s 匹配）
_PINYIN_INITIALS = [
    "zh", "ch", "sh",
    "b", "p", "m", "f", "d", "t", "n", "l",
    "g", "k", "h", "j", "q", "x", "r",
    "z", "c", "s", "y", "w",
]

# 莆仙方言发音合并规则（平翘舌不分、清浊不分等）
_DIALECT_MERGES = {
    "c": "ch",   # 平翘舌不分
    "z": "zh",   # 平翘舌不分
    "s": "sh",   # 平翘舌不分
    "d": "t",    # 清浊不分
    "b": "p",    # 清浊不分
    "g": "k",    # 清浊不分
    "f": "h",    # f/h 混淆
    "n": "l",    # n/l 混淆
}

# 相似韵母分组（同一组内的韵母视为相似）
_VOWEL_GROUPS = [
    {"an", "ang"},
    {"en", "eng"},
    {"in", "ing"},
    {"un", "ong"},
    {"ai", "ei"},
    {"ao", "ou"},
    {"ia", "ie"},
    {"ua", "uo"},
    {"ue", "ve"},
]


def _get_pinyin_initial(syllable: str) -> str:
    """从拼音音节中提取声母。"""
    for init in _PINYIN_INITIALS:
        if syllable.startswith(init):
            return init
    return ""  # 零声母


def _normalize_initial_dialect(initial: str) -> str:
    """应用方言合并规则，将声母归一化。"""
    return _DIALECT_MERGES.get(initial, initial)


def _get_vowel(syllable: str, initial: str) -> str:
    """从拼音音节中提取韵母（去掉声母后的部分）。"""
    if initial and syllable.startswith(initial):
        return syllable[len(initial):]
    return syllable


def _vowel_similarity(v1: str, v2: str) -> float:
    """计算两个韵母的相似度 [0, 1]。"""
    if v1 == v2:
        return 1.0
    for group in _VOWEL_GROUPS:
        if v1 in group and v2 in group:
            return 0.7
    return 0.0


def _to_pinyin_syllables(text: str) -> list[str]:
    """将中文文本转换为拼音音节列表。"""
    try:
        from pypinyin import pinyin, Style
        result = pinyin(text, style=Style.NORMAL, errors="default")
        return [p[0] for p in result]
    except ImportError:
        return []


def _pinyin_similarity(text: str, canonical: str) -> float:
    """
    计算两个中文文本的拼音相似度 [0, 1]。

    策略：
      1. 提取拼音声母，应用方言合并后比较（权重 65%）
      2. 提取韵母，比较相似度（权重 35%）
      3. 对音节数不匹配的情况做惩罚
    """
    text_syllables = _to_pinyin_syllables(text)
    canon_syllables = _to_pinyin_syllables(canonical)

    if not text_syllables or not canon_syllables:
        return 0.0

    # 提取声母和韵母
    text_initials = [_get_pinyin_initial(s) for s in text_syllables]
    canon_initials = [_get_pinyin_initial(s) for s in canon_syllables]

    text_initials_norm = [_normalize_initial_dialect(i) for i in text_initials]
    canon_initials_norm = [_normalize_initial_dialect(i) for i in canon_initials]

    text_vowels = [_get_vowel(text_syllables[i], text_initials[i]) for i in range(len(text_syllables))]
    canon_vowels = [_get_vowel(canon_syllables[i], canon_initials[i]) for i in range(len(canon_syllables))]

    # 比较声母（逐位比较，用最大长度归一化）
    max_len = max(len(text_initials_norm), len(canon_initials_norm))
    min_len = min(len(text_initials_norm), len(canon_initials_norm))

    initial_matches = 0
    for i in range(min_len):
        if text_initials_norm[i] == canon_initials_norm[i]:
            initial_matches += 1

    # 对长度不匹配做惩罚
    length_penalty = min_len / max_len if max_len > 0 else 0
    initial_score = (initial_matches / max_len) * length_penalty if max_len > 0 else 0

    # 比较韵母
    vowel_score_sum = 0.0
    for i in range(min_len):
        vowel_score_sum += _vowel_similarity(text_vowels[i], canon_vowels[i])
    vowel_score = (vowel_score_sum / max_len) * length_penalty if max_len > 0 else 0

    # 综合得分
    score = 0.65 * initial_score + 0.35 * vowel_score

    return score


def _pinyin_fuzzy_match(text: str, vocab: dict) -> tuple[Optional[str], float]:
    """
    使用拼音相似度匹配节目名。

    要求输入文本至少 3 个字，避免短文本误匹配。

    Returns:
        (canonical, score) — 匹配到的节目名和相似度分数
    """
    # 短文本（< 3 字）不做拼音匹配，太容易误匹配
    chinese_chars = [c for c in text if '\u4e00' <= c <= '\u9fff']
    if len(chinese_chars) < 3:
        return None, 0.0

    best_match = None
    best_score = 0.0

    for entry in vocab.get("entries", []):
        canonical = entry["canonical"]
        score = _pinyin_similarity(text, canonical)
        if score > best_score:
            best_score = score
            best_match = canonical

    # 阈值：0.5 以上才认为匹配
    if best_score >= 0.5:
        return best_match, best_score
    return None, 0.0


# ============================================================
# 综合模糊匹配
# ============================================================

def _fuzzy_match(text: str, index: dict, vocab: dict) -> tuple[Optional[str], float]:
    """
    对输入文本做模糊匹配，返回匹配到的 canonical 名称和置信度。

    匹配策略（按优先级）：
      1. 精确匹配（含大小写不敏感）— 置信度 1.0
      2. 子串匹配 — 置信度 0.9
      3. 编辑距离 ≤ 2 的汉字模糊匹配 — 置信度 0.85
      4. 拼音模糊匹配（方言发音感知）— 置信度 = 拼音相似度分数

    Returns:
        (canonical, confidence) — 匹配结果和置信度
    """
    if not text or not text.strip():
        return None, 0.0

    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # 1. 精确匹配
    if text_stripped in index:
        return index[text_stripped], 1.0
    if text_lower in index:
        return index[text_lower], 1.0

    # 2. 子串匹配
    for entry in vocab.get("entries", []):
        canonical = entry["canonical"]
        if canonical in text_stripped or canonical.lower() in text_lower:
            return canonical, 0.9
        if text_stripped in canonical or text_lower in canonical.lower():
            return canonical, 0.9
        for alias in entry.get("aliases", []):
            if alias in text_stripped or alias.lower() in text_lower:
                return canonical, 0.9
            if text_stripped in alias or text_lower in alias.lower():
                return canonical, 0.9
        for mis in entry.get("common_misrecognition", []):
            if mis in text_stripped or mis.lower() in text_lower:
                return canonical, 0.9

    # 3. 编辑距离模糊匹配（仅对中文名称）
    #    要求字符串长度 ≥ 3，且编辑距离 ≤ 2，避免短字符串误匹配
    for entry in vocab.get("entries", []):
        canonical = entry["canonical"]
        if len(canonical) >= 3 and len(text_stripped) >= 3:
            dist = _edit_distance(text_stripped, canonical)
            if 0 < dist <= 2:
                return canonical, 0.85
        for alias in entry.get("aliases", []):
            if len(alias) < 3 or len(text_lower) < 3:
                continue
            dist = _edit_distance(text_lower, alias.lower())
            if 0 < dist <= 2:
                return canonical, 0.85

    # 4. 拼音模糊匹配（核心改进：即使汉字全错，发音相近也能匹配）
    pinyin_match, pinyin_score = _pinyin_fuzzy_match(text_stripped, vocab)
    if pinyin_match:
        return pinyin_match, pinyin_score

    return None, 0.0


def normalize(
    text: str,
    scene: Optional[str],
    candidates: list,
) -> dict:
    """
    节目名规范化与候选重排序。

    Args:
        text: ASR 识别出的原始文本
        scene: 场景标识（"program_search" 时启用规范化）
        candidates: 候选结果列表，每项为 {"text": str, "confidence": float}

    Returns:
        dict: {
            normalized_text: str|None,   # 规范化后的文本
            candidates: list,            # 重排序后的候选列表
            needs_confirmation: bool,    # 是否需要用户确认
        }
    """
    # 非 program_search 场景：不做规范化
    if scene != "program_search":
        return {
            "normalized_text": None,
            "candidates": candidates,
            "needs_confirmation": False,
        }

    # 加载词表和索引
    vocab = _load_vocab()
    index = _build_lookup_index(vocab)

    # 对原始 text 做匹配
    normalized_text, match_confidence = _fuzzy_match(text, index, vocab)

    # 对每个 candidate 做匹配，并标注匹配结果
    matched_candidates = []
    unmatched_candidates = []

    for cand in candidates:
        cand_text = cand.get("text", "")
        cand_conf = cand.get("confidence", 0.0)
        matched_canonical, cand_match_conf = _fuzzy_match(cand_text, index, vocab)

        enriched = {
            "text": cand_text,
            "confidence": cand_conf,
            "matched_canonical": matched_canonical,
            "match_confidence": cand_match_conf,
        }

        if matched_canonical:
            matched_candidates.append(enriched)
        else:
            unmatched_candidates.append(enriched)

    # 重排序：匹配到的排前面，按匹配置信度降序
    matched_candidates.sort(key=lambda x: x.get("match_confidence", 0), reverse=True)
    unmatched_candidates.sort(key=lambda x: x["confidence"], reverse=True)
    reranked = matched_candidates + unmatched_candidates

    # 如果原始 text 没匹配到，但 candidates 有匹配，用第一个匹配的 canonical
    if normalized_text is None and matched_candidates:
        normalized_text = matched_candidates[0]["matched_canonical"]
        match_confidence = matched_candidates[0].get("match_confidence", 0)

    # 判断 needs_confirmation
    # 条件 1：ASR confidence < 0.8
    # 条件 2：拼音匹配分数 < 0.7（说明是弱匹配，需要确认）
    all_confs = [c.get("confidence", 0.0) for c in candidates]
    max_conf = max(all_confs) if all_confs else 0.0

    needs_confirmation = (max_conf < 0.8) or (match_confidence < 0.7)

    # 如果精确匹配或子串匹配（高置信度），不需要确认
    if normalized_text and match_confidence >= 0.85:
        needs_confirmation = False

    return {
        "normalized_text": normalized_text,
        "candidates": reranked,
        "needs_confirmation": needs_confirmation,
    }
