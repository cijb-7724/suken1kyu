#!/usr/bin/env python3
"""
taxonomy.yml に登録されているタグについて、
存在しない知識ページを knowledge/<exam>/ に自動生成する。

既存の知識ページは上書きしない。
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
TAG_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SyncKnowledgeError(Exception):
    """知識ページ同期処理の入力データに問題がある場合の例外。"""


@dataclass(frozen=True)
class Tag:
    """taxonomy.yml 内の1つのタグ。"""

    tag_id: str
    label: str
    parent_id: str | None
    depth: int


def get_repository_root() -> Path:
    """
    このスクリプトの位置からリポジトリのルートを取得する。

    想定:
        <repository>/scripts/sync_knowledge.py
    """
    return Path(__file__).resolve().parents[1]


def load_taxonomy(taxonomy_path: Path) -> dict[str, Any]:
    """taxonomy.ymlを読み込む。"""
    if not taxonomy_path.is_file():
        raise SyncKnowledgeError(
            f"taxonomy.yml が見つかりません: {taxonomy_path}"
        )

    try:
        with taxonomy_path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except yaml.YAMLError as exc:
        raise SyncKnowledgeError(
            f"YAMLの解析に失敗しました: {taxonomy_path}\n{exc}"
        ) from exc

    if data is None:
        raise SyncKnowledgeError(
            f"taxonomy.yml が空です: {taxonomy_path}"
        )

    if not isinstance(data, dict):
        raise SyncKnowledgeError(
            f"taxonomy.yml の最上位は辞書形式である必要があります: "
            f"{taxonomy_path}"
        )

    if "tags" not in data:
        raise SyncKnowledgeError(
            f"'tags' がありません: {taxonomy_path}"
        )

    if not isinstance(data["tags"], list):
        raise SyncKnowledgeError(
            f"'tags' はリストである必要があります: {taxonomy_path}"
        )

    return data


def flatten_tags(nodes: list[Any]) -> list[Tag]:
    """
    入れ子になったタグ階層を、親情報を持つ一次元リストへ変換する。
    """
    result: list[Tag] = []
    seen_ids: set[str] = set()

    def visit(
        current_nodes: list[Any],
        parent_id: str | None,
        depth: int,
    ) -> None:
        if not isinstance(current_nodes, list):
            raise SyncKnowledgeError(
                "'children' はリストである必要があります。"
            )

        for index, node in enumerate(current_nodes, start=1):
            if not isinstance(node, dict):
                raise SyncKnowledgeError(
                    f"タグは辞書形式である必要があります。"
                    f"位置: depth={depth}, index={index}"
                )

            tag_id = node.get("id")
            label = node.get("label")

            if not isinstance(tag_id, str) or not tag_id.strip():
                raise SyncKnowledgeError(
                    f"タグの 'id' が不正です: {node!r}"
                )

            if not TAG_ID_PATTERN.fullmatch(tag_id):
                raise SyncKnowledgeError(
                    f"タグIDは小文字英数字のケバブケースにしてください: "
                    f"{tag_id}"
                )

            if tag_id in seen_ids:
                raise SyncKnowledgeError(
                    f"タグIDが重複しています: {tag_id}"
                )

            if not isinstance(label, str) or not label.strip():
                raise SyncKnowledgeError(
                    f"タグ '{tag_id}' の 'label' が不正です。"
                )

            seen_ids.add(tag_id)

            result.append(
                Tag(
                    tag_id=tag_id,
                    label=label.strip(),
                    parent_id=parent_id,
                    depth=depth,
                )
            )

            children = node.get("children", [])

            if children is None:
                children = []

            if not isinstance(children, list):
                raise SyncKnowledgeError(
                    f"タグ '{tag_id}' の 'children' は"
                    f"リストである必要があります。"
                )

            visit(
                current_nodes=children,
                parent_id=tag_id,
                depth=depth + 1,
            )

    visit(nodes, parent_id=None, depth=0)
    return result


def render_knowledge_page(tag: Tag, exam: str) -> str:
    """新しい知識ページの初期内容を生成する。"""
    exam_label = "1次試験" if exam == "primary" else "2次試験"

    # json.dumps により、日本語や引用符を安全な二重引用形式にする。
    yaml_title = json.dumps(tag.label, ensure_ascii=False)

    return f"""---
title: {yaml_title}
id: {tag.tag_id}
---

{exam_label}における「{tag.label}」についてまとめます。

## 概要

未記入。

## 基本事項

未記入。

## 例題

未記入。

## 関連問題

後で自動表示します。
"""


def sync_exam(
    repository_root: Path,
    exam: str,
    dry_run: bool,
) -> tuple[int, int]:
    """
    指定した試験区分の知識ページを同期する。

    Returns:
        (作成対象数, 既存ページ数)
    """
    taxonomy_path = (
        repository_root
        / "database"
        / exam
        / "taxonomy.yml"
    )

    knowledge_directory = (
        repository_root
        / "knowledge"
        / exam
    )

    taxonomy = load_taxonomy(taxonomy_path)
    tags = flatten_tags(taxonomy["tags"])

    if not dry_run:
        knowledge_directory.mkdir(parents=True, exist_ok=True)

    created_count = 0
    skipped_count = 0

    print(f"\n=== {exam} ===")
    print(f"taxonomy: {taxonomy_path}")
    print(f"タグ数: {len(tags)}")

    for tag in tags:
        page_path = knowledge_directory / f"{tag.tag_id}.qmd"

        if page_path.exists():
            print(f"[SKIP]   {page_path.relative_to(repository_root)}")
            skipped_count += 1
            continue

        print(f"[CREATE] {page_path.relative_to(repository_root)}")
        created_count += 1

        if dry_run:
            continue

        page_content = render_knowledge_page(tag, exam)

        try:
            page_path.write_text(page_content, encoding="utf-8")
        except OSError as exc:
            raise SyncKnowledgeError(
                f"ファイルの作成に失敗しました: {page_path}\n{exc}"
            ) from exc

    return created_count, skipped_count


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description=(
            "taxonomy.yml に登録されたタグについて、"
            "存在しない知識ページを自動生成します。"
        )
    )

    parser.add_argument(
        "--exam",
        choices=("primary", "secondary", "all"),
        default="all",
        help=(
            "処理対象。primary、secondary、all のいずれか。"
            "既定値は all。"
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイルを作成せず、作成予定だけを表示します。",
    )

    return parser.parse_args()


def main() -> int:
    """エントリーポイント。"""
    arguments = parse_arguments()
    repository_root = get_repository_root()

    exams = (
        EXAMS
        if arguments.exam == "all"
        else (arguments.exam,)
    )

    total_created = 0
    total_skipped = 0

    try:
        for exam in exams:
            created, skipped = sync_exam(
                repository_root=repository_root,
                exam=exam,
                dry_run=arguments.dry_run,
            )

            total_created += created
            total_skipped += skipped

    except SyncKnowledgeError as exc:
        print(f"\nエラー: {exc}", file=sys.stderr)
        return 1

    mode = "作成予定" if arguments.dry_run else "作成完了"

    print("\n=== 結果 ===")
    print(f"{mode}: {total_created}件")
    print(f"既存のためスキップ: {total_skipped}件")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())