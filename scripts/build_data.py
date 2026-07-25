#!/usr/bin/env python3
"""
数検1級DBのQMD/YAMLを、ブラウザで利用する静的JSONへ変換する。

出力:
    _generated/<exam>/problems.json
    _generated/<exam>/papers.json
    _generated/<exam>/tags.json

既定では生成前に scripts/validate.py と同じ検証を実行し、
エラーがある場合はJSONを更新しない。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

try:
    import validate as validator
except ImportError as exc:  # pragma: no cover - 実行場所の誤りを明示するため
    raise SystemExit(
        "scripts/validate.py を読み込めません。"
        "リポジトリ内の scripts/build_data.py として実行してください。"
    ) from exc


SCHEMA_VERSION = 1
EXAM_NAMES = ("primary", "secondary")


class BuildDataError(Exception):
    """JSON生成を継続できない入力・出力エラー。"""


@dataclass(frozen=True)
class TagRecord:
    """taxonomy.yml内の1タグを平坦化した内部表現。"""

    tag_id: str
    label: str
    parent_id: str | None
    depth: int
    children: tuple[str, ...]
    order: int


@dataclass(frozen=True)
class ProblemRecord:
    """問題QMDから読み取った内部表現。"""

    problem_id: str
    title: str
    paper_id: str
    question_number: int
    cell_label: str
    direct_tags: tuple[str, ...]
    path: str
    source_path: str


def repository_root() -> Path:
    """scripts/build_data.py の位置からリポジトリルートを求める。"""
    return Path(__file__).resolve().parents[1]


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """YAMLファイルを辞書として読み込む。"""
    if not path.is_file():
        raise BuildDataError(f"ファイルが見つかりません: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BuildDataError(f"YAMLを読み込めません: {path}\n{exc}") from exc

    if not isinstance(data, dict):
        raise BuildDataError(f"YAMLの最上位は辞書形式にしてください: {path}")

    return data


def read_front_matter(path: Path) -> dict[str, Any]:
    """QMD先頭のYAML front matterを読み込む。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildDataError(f"ファイルを読み込めません: {path}\n{exc}") from exc

    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff") != "---":
        raise BuildDataError(f"front matterがありません: {path}")

    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise BuildDataError(f"front matterの終了記号がありません: {path}") from exc

    try:
        metadata = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise BuildDataError(f"front matterを解析できません: {path}\n{exc}") from exc

    if not isinstance(metadata, dict):
        raise BuildDataError(f"front matterは辞書形式にしてください: {path}")

    return metadata


def validate_before_build(
    root: Path,
    exams: Iterable[str],
    strict: bool,
) -> None:
    """
    validate.pyの検証関数を同一プロセス内で実行する。

    エラーが1件でもある場合、またはstrict時に警告がある場合は失敗する。
    """
    reporter = validator.Reporter(root)
    global_problem_ids: dict[str, Path] = {}
    stats: dict[str, validator.Stats] = {}

    for exam in exams:
        config = validator.EXAMS[exam]
        taxonomy = validator.validate_taxonomy(root, config, reporter)
        paper_ids = validator.validate_papers(root, config, reporter)
        problem_count = validator.validate_problems(
            root,
            config,
            taxonomy,
            paper_ids,
            reporter,
            global_problem_ids,
        )
        knowledge_count = validator.validate_knowledge(
            root,
            config,
            taxonomy,
            reporter,
        )
        stats[exam] = validator.Stats(
            papers=len(paper_ids),
            problems=problem_count,
            tags=len(taxonomy.labels),
            knowledge_pages=knowledge_count,
        )

    print("=== 生成前検証 ===")
    for exam, value in stats.items():
        print(
            f"{exam}: 試験用紙={value.papers}, 問題={value.problems}, "
            f"タグ={value.tags}, 知識ページ={value.knowledge_pages}"
        )

    if reporter.warnings:
        print("\n=== 警告 ===")
        for message in reporter.warnings:
            print(f"[WARN] {message}")

    if reporter.errors:
        print("\n=== エラー ===")
        for message in reporter.errors:
            print(f"[ERROR] {message}")
        raise BuildDataError(
            f"検証エラーが{len(reporter.errors)}件あるため生成を中止しました。"
        )

    if strict and reporter.warnings:
        raise BuildDataError(
            f"strictモードでは警告{len(reporter.warnings)}件も失敗として扱います。"
        )

    print("Validation passed.\n")


def load_papers(root: Path, exam: str) -> list[dict[str, Any]]:
    """papers.ymlをsort_order順に読み込む。"""
    path = root / "database" / exam / "papers.yml"
    data = load_yaml_mapping(path)
    papers = data.get("papers")

    if not isinstance(papers, list):
        raise BuildDataError(f"'papers' はリストにしてください: {path}")

    normalized: list[dict[str, Any]] = []
    for paper in papers:
        if not isinstance(paper, dict):
            raise BuildDataError(f"試験用紙データが辞書ではありません: {path}")

        normalized.append(
            {
                "id": paper["id"],
                "label": paper["label"],
                "year": paper.get("year"),
                "round": paper.get("round"),
                "sort_order": paper["sort_order"],
            }
        )

    return sorted(normalized, key=lambda item: (item["sort_order"], item["id"]))


def load_taxonomy(
    root: Path,
    exam: str,
) -> tuple[list[str], dict[str, TagRecord], list[dict[str, Any]]]:
    """
    taxonomy.ymlを読み、ルートID・平坦辞書・表示用ツリーを返す。
    """
    path = root / "database" / exam / "taxonomy.yml"
    data = load_yaml_mapping(path)
    nodes = data.get("tags")

    if not isinstance(nodes, list):
        raise BuildDataError(f"'tags' はリストにしてください: {path}")

    records: dict[str, TagRecord] = {}
    root_ids: list[str] = []
    order_counter = 0

    def visit(
        current_nodes: list[Any],
        parent_id: str | None,
        depth: int,
    ) -> list[dict[str, Any]]:
        nonlocal order_counter
        tree_nodes: list[dict[str, Any]] = []

        for node in current_nodes:
            if not isinstance(node, dict):
                raise BuildDataError(f"タグデータが辞書ではありません: {path}")

            tag_id = node["id"]
            label = node["label"]
            raw_children = node.get("children", [])
            if raw_children is None:
                raw_children = []
            if not isinstance(raw_children, list):
                raise BuildDataError(
                    f"タグ '{tag_id}' のchildrenはリストにしてください: {path}"
                )

            child_ids = tuple(child["id"] for child in raw_children)
            current_order = order_counter
            order_counter += 1

            records[tag_id] = TagRecord(
                tag_id=tag_id,
                label=label,
                parent_id=parent_id,
                depth=depth,
                children=child_ids,
                order=current_order,
            )

            if parent_id is None:
                root_ids.append(tag_id)

            children_tree = visit(raw_children, tag_id, depth + 1)
            tree_nodes.append(
                {
                    "id": tag_id,
                    "label": label,
                    "children": children_tree,
                }
            )

        return tree_nodes

    tree = visit(nodes, None, 0)
    return root_ids, records, tree


def load_problems(root: Path, exam: str) -> list[ProblemRecord]:
    """問題QMDのfront matterを読み込む。"""
    config = validator.EXAMS[exam]
    directory = root / "problems" / exam
    pattern = f"{config.problem_prefix}*.qmd"
    problems: list[ProblemRecord] = []

    for path in sorted(directory.glob(pattern)):
        metadata = read_front_matter(path)
        problem_id = metadata["id"]
        problems.append(
            ProblemRecord(
                problem_id=problem_id,
                title=metadata["title"],
                paper_id=metadata["paper_id"],
                question_number=metadata["question_number"],
                cell_label=metadata["cell_label"],
                direct_tags=tuple(metadata["tags"]),
                path=f"problems/{exam}/{problem_id}.html",
                source_path=str(path.relative_to(root)),
            )
        )

    return problems


def ancestor_ids(tag_id: str, tags: dict[str, TagRecord]) -> list[str]:
    """親からルートへではなく、ルートから直親の順で祖先IDを返す。"""
    ancestors: list[str] = []
    current = tags[tag_id].parent_id

    while current is not None:
        ancestors.append(current)
        current = tags[current].parent_id

    ancestors.reverse()
    return ancestors


def descendant_ids(tag_id: str, tags: dict[str, TagRecord]) -> list[str]:
    """taxonomy上の表示順を保って全子孫IDを返す。"""
    descendants: list[str] = []

    def visit(current_id: str) -> None:
        for child_id in tags[current_id].children:
            descendants.append(child_id)
            visit(child_id)

    visit(tag_id)
    return descendants


def build_problem_payload(
    exam: str,
    papers: list[dict[str, Any]],
    tags: dict[str, TagRecord],
    problems: list[ProblemRecord],
) -> dict[str, Any]:
    """problems.jsonの内容を構築する。"""
    paper_order = {paper["id"]: paper["sort_order"] for paper in papers}
    tag_order = {tag_id: tag.order for tag_id, tag in tags.items()}

    sorted_problems = sorted(
        problems,
        key=lambda problem: (
            paper_order[problem.paper_id],
            problem.question_number,
            problem.problem_id,
        ),
    )

    payload: list[dict[str, Any]] = []
    for problem in sorted_problems:
        all_tag_set: set[str] = set(problem.direct_tags)
        for tag_id in problem.direct_tags:
            all_tag_set.update(ancestor_ids(tag_id, tags))

        all_tags = sorted(all_tag_set, key=lambda tag_id: tag_order[tag_id])

        payload.append(
            {
                "id": problem.problem_id,
                "title": problem.title,
                "paper_id": problem.paper_id,
                "question_number": problem.question_number,
                "cell_label": problem.cell_label,
                "direct_tags": list(problem.direct_tags),
                "all_tags": all_tags,
                "path": problem.path,
                "source_path": problem.source_path,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "exam": exam,
        "count": len(payload),
        "problems": payload,
    }


def build_paper_payload(
    exam: str,
    papers: list[dict[str, Any]],
    problems: list[ProblemRecord],
) -> dict[str, Any]:
    """AtCoder Problems風一覧表で使いやすいpapers.jsonを構築する。"""
    by_paper: dict[str, list[ProblemRecord]] = {paper["id"]: [] for paper in papers}
    for problem in problems:
        by_paper[problem.paper_id].append(problem)

    max_question_number = max(
        (problem.question_number for problem in problems),
        default=0,
    )

    paper_payload: list[dict[str, Any]] = []
    for paper in papers:
        paper_problems = sorted(
            by_paper[paper["id"]],
            key=lambda problem: (problem.question_number, problem.problem_id),
        )

        questions = {
            str(problem.question_number): {
                "problem_id": problem.problem_id,
                "cell_label": problem.cell_label,
                "path": problem.path,
                "direct_tags": list(problem.direct_tags),
            }
            for problem in paper_problems
        }

        paper_payload.append(
            {
                **paper,
                "problem_count": len(paper_problems),
                "question_numbers": [
                    problem.question_number for problem in paper_problems
                ],
                "questions": questions,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "exam": exam,
        "count": len(paper_payload),
        "max_question_number": max_question_number,
        "papers": paper_payload,
    }


def build_tag_payload(
    exam: str,
    root_ids: list[str],
    tags: dict[str, TagRecord],
    tree: list[dict[str, Any]],
    problems: list[ProblemRecord],
) -> dict[str, Any]:
    """階層フィルタと知識ページ一覧で使うtags.jsonを構築する。"""
    direct_problem_ids: dict[str, set[str]] = {tag_id: set() for tag_id in tags}
    for problem in problems:
        for tag_id in problem.direct_tags:
            direct_problem_ids[tag_id].add(problem.problem_id)

    by_id: dict[str, dict[str, Any]] = {}
    ordered_tags = sorted(tags.values(), key=lambda tag: tag.order)

    for tag in ordered_tags:
        ancestors = ancestor_ids(tag.tag_id, tags)
        descendants = descendant_ids(tag.tag_id, tags)

        matched_problem_ids = set(direct_problem_ids[tag.tag_id])
        for descendant_id in descendants:
            matched_problem_ids.update(direct_problem_ids[descendant_id])

        by_id[tag.tag_id] = {
            "id": tag.tag_id,
            "label": tag.label,
            "parent_id": tag.parent_id,
            "depth": tag.depth,
            "children": list(tag.children),
            "ancestors": ancestors,
            "descendants": descendants,
            "direct_problem_ids": sorted(direct_problem_ids[tag.tag_id]),
            "problem_ids": sorted(matched_problem_ids),
            "direct_problem_count": len(direct_problem_ids[tag.tag_id]),
            "problem_count": len(matched_problem_ids),
            "knowledge_path": f"knowledge/{exam}/{tag.tag_id}.html",
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "exam": exam,
        "count": len(by_id),
        "root_ids": root_ids,
        "tree": tree,
        "by_id": by_id,
    }


def serialize_json(data: dict[str, Any]) -> str:
    """日本語をエスケープせず、決定的な形式でJSON化する。"""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write_or_check(
    path: Path,
    content: str,
    check_only: bool,
) -> str:
    """
    JSONを書き込む、または既存内容が最新か確認する。

    Returns:
        WRITE / UNCHANGED / OK / MISSING / OUTDATED
    """
    existing: str | None = None
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BuildDataError(f"既存JSONを読み込めません: {path}\n{exc}") from exc

    if check_only:
        if existing is None:
            return "MISSING"
        return "OK" if existing == content else "OUTDATED"

    if existing == content:
        return "UNCHANGED"

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")

    try:
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(path)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise BuildDataError(f"JSONを書き込めません: {path}\n{exc}") from exc

    return "WRITE"


def build_exam(root: Path, exam: str) -> dict[str, str]:
    """1試験区分分の3種類のJSON文字列を構築する。"""
    papers = load_papers(root, exam)
    root_ids, tags, tree = load_taxonomy(root, exam)
    problems = load_problems(root, exam)

    return {
        "problems.json": serialize_json(
            build_problem_payload(exam, papers, tags, problems)
        ),
        "papers.json": serialize_json(
            build_paper_payload(exam, papers, problems)
        ),
        "tags.json": serialize_json(
            build_tag_payload(exam, root_ids, tags, tree, problems)
        ),
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "問題QMD・papers.yml・taxonomy.ymlから、"
            "サイト用の静的JSONを生成します。"
        )
    )
    parser.add_argument(
        "--exam",
        choices=("primary", "secondary", "all"),
        default="all",
        help="生成対象。既定値はall。",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="書き込まず、生成済みJSONが最新か確認します。",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="生成前検証で警告も失敗として扱います。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    root = repository_root()
    exams = EXAM_NAMES if args.exam == "all" else (args.exam,)

    try:
        validate_before_build(root, exams, strict=args.strict)

        status_counts: dict[str, int] = {}
        failed_check = False

        for exam in exams:
            print(f"=== {exam} ===")
            outputs = build_exam(root, exam)
            output_directory = root / "_generated" / exam

            for filename, content in outputs.items():
                output_path = output_directory / filename
                status = write_or_check(output_path, content, args.check)
                relative_path = output_path.relative_to(root)
                print(f"[{status}] {relative_path}")
                status_counts[status] = status_counts.get(status, 0) + 1

                if status in {"MISSING", "OUTDATED"}:
                    failed_check = True

            print()

        print("=== 結果 ===")
        if args.check:
            print(f"最新: {status_counts.get('OK', 0)}件")
            print(f"未生成: {status_counts.get('MISSING', 0)}件")
            print(f"要更新: {status_counts.get('OUTDATED', 0)}件")
            if failed_check:
                print("Generated data check failed.")
                return 1
            print("Generated data is up to date.")
            return 0

        print(f"更新: {status_counts.get('WRITE', 0)}件")
        print(f"変更なし: {status_counts.get('UNCHANGED', 0)}件")
        print("Build completed.")
        return 0

    except BuildDataError as exc:
        print(f"\nエラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
