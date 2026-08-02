#!/usr/bin/env python3
"""注入 hinghwa 126 词到 putian_trainer.py WORDS"""
from pathlib import Path
import json

TRAINER = Path('/Users/sagaai/.hermes/profiles/dialect-bot/scripts/putian_trainer.py')
REF = Path('/Users/sagaai/.hermes/profiles/dialect-bot/data/hinghwa/reference.json')

# Read current file
content = TRAINER.read_text(encoding='utf-8')

# Find WORDS list end marker: ("脱衣服", "日常", 2),\n]  then # --- 句
old_lines = '    ("脱衣服", "日常", 2),\n]'
new_lines = '''    ("脱衣服", "日常", 2),
]

# --- 动态注入 hinghwa.cn 莆仙话发音词 ---
try:
    _hw_ref = json.loads((PROFILE_DIR / "data" / "hinghwa" / "reference.json").read_text(encoding="utf-8"))
    _hw_words = [(k, "莆仙话", 3) for k, v in _hw_ref.items() if v.get("audio_variants")]
    WORDS.extend(_hw_words)
except Exception:
    pass
'''

if old_lines in content:
    content = content.replace(old_lines, new_lines)
    TRAINER.write_text(content, encoding='utf-8')
    print("Injected hinghwa words into WORDS list")
else:
    print("Marker not found — checking alternatives...")
    # Try with single quotes
    alt = '    ("脱衣服", "日常", 2),\n]'
    if alt in content:
        content = content.replace(alt, new_lines.replace('"脱衣服"', "'脱衣服'").replace('"日常"', "'日常'"))
        TRAINER.write_text(content, encoding='utf-8')
        print("Injected (alt format)")
    else:
        # Show context around line 117
        lines = content.split('\n')
        for i in range(115, 125):
            print(f"  {i}: {lines[i]}")
