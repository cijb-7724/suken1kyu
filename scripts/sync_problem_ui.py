#!/usr/bin/env python3
"""
問題QMDへ、自動タグ表示用のUIブロックを追加・更新する。
本文とfront matterは変更しない。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXAMS = {
    "primary": "pri-problem-*.qmd",
    "secondary": "sec-problem-*.qmd",
}
AUTO_START = "<!-- AUTO:PROBLEM-UI:START -->"
AUTO_END = "<!-- AUTO:PROBLEM-UI:END -->"


class SyncError(Exception):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def auto_block() -> str:
    return "\n".join(
        [
            AUTO_START,
            '<div class="problem-meta-app" data-problem-page></div>',
            '<link rel="stylesheet" href="../../assets/css/knowledge-catalog.css">',
            '<script type="module" src="../../assets/js/problem-page-meta.js"></script>',
            AUTO_END,
        ]
    )


def normalized(text: str, path: Path) -> str:
    start_count = text.count(AUTO_START)
    end_count = text.count(AUTO_END)
    if start_count != end_count:
        raise SyncError(f"自動UIマーカーの開始・終了数が一致しません: {path}")
    if start_count > 1:
        raise SyncError(f"自動UIブロックが複数あります: {path}")

    block = auto_block()
    if start_count == 0:
        return text.rstrip() + "\n\n" + block + "\n"

    start = text.index(AUTO_START)
    end = text.index(AUTO_END, start) + len(AUTO_END)
    return text[:start].rstrip() + "\n\n" + block + text[end:]


def process_exam(root: Path, exam: str, mode: str) -> tuple[int, int]:
    directory = root / "problems" / exam
    if not directory.is_dir():
        raise SyncError(f"問題ディレクトリがありません: {directory}")

    updated = unchanged = 0
    print(f"\n=== {exam} ===")

    for path in sorted(directory.glob(EXAMS[exam])):
        current = path.read_text(encoding="utf-8")
        content = normalized(current, path)
        relative = path.relative_to(root)
        if current == content:
            print(f"[SKIP] {relative}")
            unchanged += 1
        else:
            print(f"[UPDATE] {relative}")
            updated += 1
            if mode == "write":
                path.write_text(content, encoding="utf-8")

    return updated, unchanged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="問題ページの自動タグUIを同期します。")
    parser.add_argument(
        "--exam", choices=("primary", "secondary", "all"), default="all"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    exams = tuple(EXAMS) if args.exam == "all" else (args.exam,)
    mode = "check" if args.check else "dry-run" if args.dry_run else "write"
    total_updated = total_unchanged = 0

    try:
        for exam in exams:
            updated, unchanged = process_exam(root, exam, mode)
            total_updated += updated
            total_unchanged += unchanged
    except (SyncError, OSError) as exc:
        print(f"\nエラー: {exc}", file=sys.stderr)
        return 1

    print("\n=== 結果 ===")
    print(f"更新: {total_updated}件")
    print(f"変更なし: {total_unchanged}件")

    if args.check and total_updated:
        print("Problem page UI synchronization is required.")
        return 1
    if args.dry_run:
        print("Dry run completed. Files were not changed.")
    elif args.check:
        print("Problem page UI is up to date.")
    else:
        print("Problem page UI synchronized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
