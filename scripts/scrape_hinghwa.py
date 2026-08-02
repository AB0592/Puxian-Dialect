#!/usr/bin/env python3
"""
hinghwa.cn 数据爬虫 v2
步骤:
  1. words.json — 快速抓全部词条 (6129条/页, ~7页)
  2. audio/ — 逐字抓取发音+下载音频
"""
import os, json, time, urllib.request, urllib.parse, sys
from pathlib import Path

API_BASE = "https://api.pxm.edialect.top"
OUTPUT_DIR = Path("/Users/sagaai/.hermes/profiles/dialect-bot/data/hinghwa")
AUDIO_DIR = OUTPUT_DIR / "audio"

def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PutianTrainer/1.0"})
            resp = urllib.request.urlopen(req, timeout=30)
            return json.loads(resp.read())
        except Exception as e:
            if i == retries - 1:
                print(f"  FAIL: {url[:80]} — {e}")
                return {}
            time.sleep(2)

def download(url, dest):
    if dest.exists():
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PutianTrainer/1.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(resp.read())
        return True
    except Exception as e:
        return False


def step1_fetch_words():
    """快速抓全部词条"""
    print("[1/2] 抓取全部词条...")
    all_words = []
    page = 1
    while True:
        data = fetch(f"{API_BASE}/words?page={page}&size=100")
        results = data.get("result", [])
        if not results:
            break
        all_words.extend(results)
        print(f"  第{page}页: {len(results)} 条 (累计 {len(all_words)})")
        if len(results) < 100:
            break
        page += 1
        time.sleep(0.2)

    with open(OUTPUT_DIR / "words.json", "w") as f:
        json.dump(all_words, f, ensure_ascii=False, indent=2)
    print(f"  保存: {len(all_words)} 条 → words.json")
    return all_words


def step2_fetch_audio(words):
    """逐字抓发音 + 下载音频"""
    print(f"\n[2/2] 抓取发音 ({len(words)} 词)...")

    char_data = {}
    total_audio = 0

    # 只处理前 N 个（太多了），或者全量
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(words)
    subset = words[:limit]

    for i, w in enumerate(subset):
        word = w["word"]
        word_id = w["id"]

        # 搜索单字发音
        try:
            q = urllib.parse.quote(word[0] if word else word)
            data = fetch(f"{API_BASE}/characters/words/v2?search={q}")
        except:
            continue

        characters = data.get("characters", [])
        entry = {
            "word": word,
            "id": word_id,
            "definition": w.get("definition", ""),
            "standard_ipa": w.get("standard_ipa", ""),
            "standard_pinyin": w.get("standard_pinyin", ""),
            "variants": [],
        }

        for cg in characters:
            county = cg.get("county", "")
            town = cg.get("town", "")
            for v in cg.get("characters", []):
                var = {
                    "county": county,
                    "town": town,
                    "pinyin": v.get("pinyin", ""),
                    "ipa": v.get("ipa", ""),
                    "shengmu": v.get("shengmu", ""),
                    "yunmu": v.get("yunmu", ""),
                    "shengdiao": v.get("shengdiao", ""),
                    "audio_url": v.get("source", ""),
                }
                if var["audio_url"]:
                    total_audio += 1
                    safe_name = f"{word_id}_{county}_{town}_{var['pinyin']}.mp3".replace("/", "_")
                    audio_path = AUDIO_DIR / safe_name
                    if download(var["audio_url"], audio_path):
                        var["local_audio"] = str(audio_path)

                entry["variants"].append(var)

        char_data[word] = entry

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(subset)} ({len(char_data)} 字, {total_audio} 音频)")
            # 定期保存
            with open(OUTPUT_DIR / "characters.json", "w") as f:
                json.dump(char_data, f, ensure_ascii=False, indent=2)

        time.sleep(0.15)

    # 最终保存
    with open(OUTPUT_DIR / "characters.json", "w") as f:
        json.dump(char_data, f, ensure_ascii=False, indent=2)

    audio_count = len(list(AUDIO_DIR.glob("*.mp3")))
    print(f"\n  [DONE] 单字: {len(char_data)}, 音频: {audio_count}")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)

    words = step1_fetch_words()
    if words:
        step2_fetch_audio(words)
    print("\n[DONE]")
