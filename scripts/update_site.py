#!/usr/bin/env python3
"""
数検1級サイトの更新処理を1コマンドにまとめる。

既定:
  1. 知識ページ同期
  2. 問題ページのタグUI同期
  3. DB検証
  4. JSON生成

--check:
  ファイルを書き換えず、同期漏れ・JSON更新漏れを検出する。

--render:
  最後に quarto render を実行する。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run(command: list[str], root: Path) -> None:
    print("\n$ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=root, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="サイトの同期・検証・JSON生成を実行します。")
    parser.add_argument(
        "--exam", choices=("primary", "secondary", "all"), default="all"
    )
    parser.add_argument("--check", action="store_true", help="書き換えずに最新状態を確認します。")
    parser.add_argument("--strict", action="store_true", help="検証警告も失敗として扱います。")
    parser.add_argument("--render", action="store_true", help="最後に quarto render を実行します。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    python = sys.executable

    sync_mode = ["--check"] if args.check else []
    exam_args = ["--exam", args.exam]

    run([python, "scripts/sync_knowledge.py", *exam_args, *sync_mode], root)
    run([python, "scripts/sync_problem_ui.py", *exam_args, *sync_mode], root)

    validate_command = [python, "scripts/validate.py", *exam_args]
    if args.strict:
        validate_command.append("--strict")
    run(validate_command, root)

    build_command = [python, "scripts/build_data.py", *exam_args]
    if args.check:
        build_command.append("--check")
    if args.strict:
        build_command.append("--strict")
    run(build_command, root)

    if args.render:
        run(["quarto", "render"], root)

    print("\nSite update completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
