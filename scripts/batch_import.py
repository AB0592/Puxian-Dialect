#!/usr/bin/env python3
"""
莆仙话对照读本批量导入工具

支持格式：
  1. CSV — 用 Excel/Numbers 编辑的对照表
  2. Markdown 读本 — 表格格式的对照读本

用法：
  # 导入 CSV
  python3 batch_import.py csv putianhua_对照表.csv putian

  # 导入 Markdown 读本
  python3 batch_import.py md putianhua_对照读本.md putian

  # 交互式逐个录入
  python3 batch_import.py interactive putian

  # 生成空模板
  python3 batch_import.py template putian
"""
import sys
import csv
import json
import re
from pathlib import Path
from typing import Optional

# 确保 dialects_map 在路径上
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))
from dialect_map import add, load, save, stats

# 方言名称对照
DIALECT_NAMES = {
    "putian": "莆仙话",
    "canton": "粤语",
    "minnan": "闽南语",
    "sichuan": "四川话",
    "shanghai": "上海话",
    "hakka": "客家语",
    "mandarin": "普通话",
}


def import_csv(csv_path: str, dialect_code: str = "putian", preview: bool = False) -> dict:
    """从 CSV 批量导入方言映射"""
    path = Path(csv_path)
    if not path.exists():
        return {"error": f"文件不存在: {csv_path}", "imported": 0}

    imported = 0
    skipped = 0
    errors = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            # 支持多种列名
            dialect = row.get("莆仙话") or row.get("方言") or row.get("dialect") or ""
            chinese = row.get("中文含义") or row.get("中文") or row.get("chinese") or ""
            note = row.get("备注") or row.get("note") or ""

            if not dialect or not chinese:
                errors.append(f"第{i}行: 缺少方言或中文列")
                continue

            dialect = dialect.strip()
            chinese = chinese.strip()

            if preview:
                print(f"  [{i}] {dialect} → {chinese}  {note}")
            else:
                add(dialect, chinese)
            imported += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "dialect": DIALECT_NAMES.get(dialect_code, dialect_code),
    }


def import_markdown(md_path: str, dialect_code: str = "putian") -> dict:
    """从 Markdown 对照读本批量导入"""
    path = Path(md_path)
    if not path.exists():
        return {"error": f"文件不存在: {md_path}", "imported": 0}

    content = path.read_text(encoding="utf-8")
    imported = 0
    errors = []

    # 提取所有 Markdown 表格行
    # | xxx | yyy | zzz |
    table_pattern = re.compile(r"^\|(.+?)\|(.+?)\|(.+?)\|", re.MULTILINE)

    for match in table_pattern.finditer(content):
        cols = [c.strip() for c in match.groups()]

        # 跳过表头行（包含 ---）
        if re.match(r"^-+$", cols[1]) or re.match(r"^-+$", cols[2]):
            continue

        dialect = cols[1] if len(cols) >= 2 else ""
        chinese = cols[2] if len(cols) >= 3 else ""

        if dialect and chinese and dialect != "莆仙话" and chinese != "中文":
            # 跳过注音列（注音通常含特殊字符）
            if re.search(r"[a-zA-Zʔⁿ]", dialect):
                continue  # 这可能是注音行，跳过
            add(dialect, chinese)
            imported += 1

    return {
        "imported": imported,
        "errors": errors,
        "dialect": DIALECT_NAMES.get(dialect_code, dialect_code),
    }


def interactive_mode(dialect_code: str = "putian"):
    """交互式逐个录入方言对照"""
    dialect_name = DIALECT_NAMES.get(dialect_code, dialect_code)
    print(f"\n{'='*50}")
    print(f"📝 交互式录入 — {dialect_name}")
    print(f"{'='*50}")
    print("输入方言词 → 中文含义，空行退出\n")

    count = 0
    while True:
        try:
            dialect = input("  🗣 方言词: ").strip()
            if not dialect:
                break
            chinese = input("  🀄 中文含义: ").strip()
            if not chinese:
                print("  ⚠ 跳过（中文含义不能为空）")
                continue

            # 确认
            confirm = input(f"  ✓ 确认录入「{dialect} → {chinese}」？(Y/n): ").strip().lower()
            if confirm in ("", "y", "yes"):
                add(dialect, chinese)
                count += 1
        except (EOFError, KeyboardInterrupt):
            break

    s = stats()
    print(f"\n✅ 本次录入 {count} 条，映射库共 {s['total']} 条")


def generate_template(dialect_code: str = "putian"):
    """生成空 CSV 模板"""
    dialect_name = DIALECT_NAMES.get(dialect_code, dialect_code)
    template_path = SCRIPTS_DIR / f"template_{dialect_code}.csv"

    with open(template_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([dialect_name, "中文含义", "备注"])
        writer.writerow(["", "", "类别: basic/idiom/question/phrase"])

    print(f"📄 模板已生成: {template_path}")
    print(f"用 Numbers 或 Excel 打开编辑后运行:")
    print(f"  python3 batch_import.py csv {template_path} {dialect_code}")


def print_help():
    print("""莆仙话对照读本 — 批量导入工具

用法:
  # 生成空 CSV 模板并手动填写
  python3 batch_import.py template putian

  # 导入 CSV 对照表
  python3 batch_import.py csv <文件.csv> [方言代码]

  # 导入 Markdown 读本
  python3 batch_import.py md <文件.md> [方言代码]

  # 交互式逐个录入
  python3 batch_import.py interactive [方言代码]

  # 预览 CSV（不实际导入）
  python3 batch_import.py preview <文件.csv>

方言代码: putian(莆仙话) canton(粤语) minnan(闽南语) sichuan(四川话)
默认: putian

例子:
  # 先在 Numbers 里填好对照表
  python3 batch_import.py template putian
  # 编辑 template_putian.csv 后导入
  python3 batch_import.py csv template_putian.csv putian
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_help()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "template":
        code = sys.argv[2] if len(sys.argv) > 2 else "putian"
        generate_template(code)

    elif cmd in ("csv", "preview"):
        if len(sys.argv) < 3:
            print("请指定 CSV 文件路径")
            sys.exit(1)
        csv_file = sys.argv[2]
        code = sys.argv[3] if len(sys.argv) > 3 else "putian"
        result = import_csv(csv_file, code, preview=(cmd == "preview"))
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(f"✅ 导入 {result['imported']} 条到 {result['dialect']} 映射库")
            if result.get("errors"):
                for e in result["errors"]:
                    print(f"  ⚠ {e}")

    elif cmd == "md":
        if len(sys.argv) < 3:
            print("请指定 Markdown 文件路径")
            sys.exit(1)
        md_file = sys.argv[2]
        code = sys.argv[3] if len(sys.argv) > 3 else "putian"
        result = import_markdown(md_file, code)
        print(f"✅ 导入 {result['imported']} 条到 {result['dialect']} 映射库")

    elif cmd == "interactive" or cmd == "i":
        code = sys.argv[2] if len(sys.argv) > 2 else "putian"
        interactive_mode(code)

    else:
        print_help()
