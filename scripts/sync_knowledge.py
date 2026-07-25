#!/usr/bin/env python3
"""
taxonomy.yml と knowledge/*.qmd を同期する。

- taxonomy にある全タグについて知識ページを保証する。
- 既存本文は保持する。
- taxonomy の label を front matter の title へ反映する。
- 自動UIブロックだけを安全に追加・更新する。
- 1次と2次は完全に別々に処理する。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

EXAMS = ("primary", "secondary")
TAG_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AUTO_START = "<!-- AUTO:KNOWLEDGE-UI:START -->"
AUTO_END = "<!-- AUTO:KNOWLEDGE-UI:END -->"


class SyncError(Exception):
    pass


@dataclass(frozen=True)
class Tag:
    tag_id: str
    label: str
    parent_id: str | None
    depth: int


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SyncError(f"ファイルが見つかりません: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SyncError(f"YAMLを読み込めません: {path}\n{exc}") from exc
    if not isinstance(data, dict):
        raise SyncError(f"YAMLの最上位は辞書形式にしてください: {path}")
    return data


def flatten_tags(nodes: Any) -> list[Tag]:
    if not isinstance(nodes, list):
        raise SyncError("taxonomy.yml の 'tags' はリストにしてください。")

    result: list[Tag] = []
    seen: set[str] = set()

    def visit(current: list[Any], parent_id: str | None, depth: int) -> None:
        for node in current:
            if not isinstance(node, dict):
                raise SyncError("taxonomy.yml のタグは辞書形式にしてください。")

            tag_id = node.get("id")
            label = node.get("label")
            if not isinstance(tag_id, str) or not TAG_ID_RE.fullmatch(tag_id):
                raise SyncError(f"不正なタグIDです: {tag_id!r}")
            if tag_id in seen:
                raise SyncError(f"タグIDが重複しています: {tag_id}")
            if not isinstance(label, str) or not label.strip():
                raise SyncError(f"タグ '{tag_id}' の label が不正です。")

            seen.add(tag_id)
            result.append(Tag(tag_id, label.strip(), parent_id, depth))

            children = node.get("children", [])
            if children is None:
                children = []
            if not isinstance(children, list):
                raise SyncError(f"タグ '{tag_id}' の children はリストにしてください。")
            visit(children, tag_id, depth + 1)

    visit(nodes, None, 0)
    return result


def auto_block() -> str:
    return "\n".join(
        [
            AUTO_START,
            '<div class="knowledge-detail-app" data-knowledge-page></div>',
            '<link rel="stylesheet" href="../../assets/css/knowledge-catalog.css">',
            '<script type="module" src="../../assets/js/knowledge-page.js"></script>',
            AUTO_END,
        ]
    )


def render_new_page(tag: Tag) -> str:
    title = json.dumps(tag.label, ensure_ascii=False)
    return f"""---
title: {title}
id: {tag.tag_id}
---

## 概要

未記入。

## 基本事項

未記入。

## 例題

未記入。

{auto_block()}
"""


def split_front_matter(text: str, path: Path) -> tuple[list[str], list[str]]:
    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff") != "---":
        raise SyncError(f"front matter がありません: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise SyncError(f"front matter の終了記号がありません: {path}") from exc
    return lines[: end + 1], lines[end + 1 :]


def update_title(front: list[str], label: str) -> list[str]:
    title_line = f"title: {json.dumps(label, ensure_ascii=False)}"
    updated = list(front)
    for index in range(1, len(updated) - 1):
        if re.match(r"^title\s*:", updated[index]):
            updated[index] = title_line
            return updated
    updated.insert(len(updated) - 1, title_line)
    return updated


def replace_auto_block(body_text: str) -> str:
    block = auto_block()
    start_count = body_text.count(AUTO_START)
    end_count = body_text.count(AUTO_END)

    if start_count != end_count:
        raise SyncError("知識ページの自動UIマーカーの開始・終了数が一致しません。")
    if start_count > 1:
        raise SyncError("知識ページの自動UIブロックが複数あります。")

    if start_count == 0:
        return body_text.rstrip() + "\n\n" + block + "\n"

    start = body_text.index(AUTO_START)
    end = body_text.index(AUTO_END, start) + len(AUTO_END)
    return body_text[:start].rstrip() + "\n\n" + block + body_text[end:].rstrip() + "\n"


def normalized_existing_page(path: Path, tag: Tag) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SyncError(f"ファイルを読み込めません: {path}\n{exc}") from exc

    front, body_lines = split_front_matter(text, path)
    front = update_title(front, tag.label)
    body = "\n".join(body_lines)
    body = replace_auto_block(body)
    return "\n".join(front).rstrip() + "\n\n" + body.lstrip("\n").rstrip() + "\n"


def process_exam(root: Path, exam: str, mode: str) -> tuple[int, int, int]:
    taxonomy_path = root / "database" / exam / "taxonomy.yml"
    knowledge_dir = root / "knowledge" / exam
    tags = flatten_tags(load_yaml(taxonomy_path).get("tags"))

    created = 0
    updated = 0
    unchanged = 0

    if mode == "write":
        knowledge_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {exam} ===")
    print(f"タグ数: {len(tags)}")

    for tag in tags:
        path = knowledge_dir / f"{tag.tag_id}.qmd"
        relative = path.relative_to(root)

        if not path.exists():
            status = "CREATE"
            content = render_new_page(tag)
            created += 1
        else:
            content = normalized_existing_page(path, tag)
            current = path.read_text(encoding="utf-8")
            if current == content:
                status = "SKIP"
                unchanged += 1
            else:
                status = "UPDATE"
                updated += 1

        print(f"[{status}] {relative}")

        if mode == "write" and status in {"CREATE", "UPDATE"}:
            path.write_text(content, encoding="utf-8")

    return created, updated, unchanged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="taxonomy と知識ページを同期し、自動UIブロックを更新します。"
    )
    parser.add_argument(
        "--exam", choices=("primary", "secondary", "all"), default="all"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="変更予定だけを表示します。")
    group.add_argument(
        "--check",
        action="store_true",
        help="同期が必要なら終了コード1を返し、ファイルは変更しません。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    exams = EXAMS if args.exam == "all" else (args.exam,)
    mode = "check" if args.check else "dry-run" if args.dry_run else "write"

    total_created = total_updated = total_unchanged = 0
    try:
        for exam in exams:
            created, updated, unchanged = process_exam(root, exam, mode)
            total_created += created
            total_updated += updated
            total_unchanged += unchanged
    except (SyncError, OSError) as exc:
        print(f"\nエラー: {exc}", file=sys.stderr)
        return 1

    print("\n=== 結果 ===")
    print(f"新規: {total_created}件")
    print(f"更新: {total_updated}件")
    print(f"変更なし: {total_unchanged}件")

    if args.check and (total_created or total_updated):
        print("Knowledge page synchronization is required.")
        return 1

    if args.dry_run:
        print("Dry run completed. Files were not changed.")
    elif args.check:
        print("Knowledge pages are up to date.")
    else:
        print("Knowledge pages synchronized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
