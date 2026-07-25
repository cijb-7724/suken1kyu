#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TAG_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ExamConfig:
    name: str
    problem_prefix: str
    paper_prefix: str
    other_name: str
    other_problem_prefix: str
    other_paper_prefix: str


EXAMS = {
    "primary": ExamConfig(
        "primary", "pri-problem-", "pri-paper-",
        "secondary", "sec-problem-", "sec-paper-",
    ),
    "secondary": ExamConfig(
        "secondary", "sec-problem-", "sec-paper-",
        "primary", "pri-problem-", "pri-paper-",
    ),
}


@dataclass
class Reporter:
    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def _rel(self, path: Path | None) -> str:
        if path is None:
            return ""
        try:
            return str(path.resolve().relative_to(self.root.resolve()))
        except ValueError:
            return str(path)

    def error(self, message: str, path: Path | None = None) -> None:
        prefix = f"{self._rel(path)}: " if path else ""
        self.errors.append(prefix + message)

    def warning(self, message: str, path: Path | None = None) -> None:
        prefix = f"{self._rel(path)}: " if path else ""
        self.warnings.append(prefix + message)


@dataclass
class Taxonomy:
    labels: dict[str, str]
    parents: dict[str, str | None]

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        current = self.parents.get(descendant)
        visited: set[str] = set()
        while current is not None and current not in visited:
            if current == ancestor:
                return True
            visited.add(current)
            current = self.parents.get(current)
        return False


@dataclass
class Stats:
    papers: int
    problems: int
    tags: int
    knowledge_pages: int


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_yaml(path: Path, reporter: Reporter) -> dict[str, Any] | None:
    if not path.is_file():
        reporter.error("ファイルが見つかりません。", path)
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        reporter.error(f"YAMLを読み込めません: {exc}", path)
        return None
    if not isinstance(data, dict):
        reporter.error("YAMLの最上位は辞書形式にしてください。", path)
        return None
    return data


def read_front_matter(
    path: Path,
    reporter: Reporter,
) -> tuple[dict[str, Any] | None, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        reporter.error(f"ファイルを読み込めません: {exc}", path)
        return None, ""

    lines = text.splitlines()
    if not lines or lines[0].lstrip("\ufeff") != "---":
        reporter.error("ファイル先頭にYAML front matterがありません。", path)
        return None, text

    try:
        end = lines.index("---", 1)
    except ValueError:
        reporter.error("front matterの終了記号 '---' がありません。", path)
        return None, text

    try:
        metadata = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        reporter.error(f"front matterを解析できません: {exc}", path)
        return None, text

    if not isinstance(metadata, dict):
        reporter.error("front matterは辞書形式にしてください。", path)
        return None, text

    return metadata, "\n".join(lines[end + 1 :])


def validate_taxonomy(
    root: Path,
    config: ExamConfig,
    reporter: Reporter,
) -> Taxonomy:
    path = root / "database" / config.name / "taxonomy.yml"
    data = load_yaml(path, reporter)
    labels: dict[str, str] = {}
    parents: dict[str, str | None] = {}
    if data is None:
        return Taxonomy(labels, parents)

    nodes = data.get("tags")
    if not isinstance(nodes, list):
        reporter.error("'tags' はリストにしてください。", path)
        return Taxonomy(labels, parents)

    active_objects: set[int] = set()

    def visit(items: Any, parent: str | None, location: str) -> None:
        if not isinstance(items, list):
            reporter.error(f"{location} はリストにしてください。", path)
            return

        for index, node in enumerate(items, start=1):
            here = f"{location}[{index}]"
            if not isinstance(node, dict):
                reporter.error(f"{here} は辞書形式にしてください。", path)
                continue

            object_id = id(node)
            if object_id in active_objects:
                reporter.error(f"{here} に循環参照があります。", path)
                continue
            active_objects.add(object_id)

            tag_id = node.get("id")
            label = node.get("label")
            valid_id = isinstance(tag_id, str) and bool(tag_id.strip())

            if not valid_id:
                reporter.error(f"{here} の 'id' が不正です。", path)
                clean_id = None
            else:
                clean_id = tag_id.strip()
                if not TAG_ID_RE.fullmatch(clean_id):
                    reporter.error(
                        f"タグID '{clean_id}' は小文字英数字の"
                        "ケバブケースにしてください。",
                        path,
                    )
                if clean_id in labels:
                    reporter.error(f"タグID '{clean_id}' が重複しています。", path)
                else:
                    clean_label = label.strip() if isinstance(label, str) else ""
                    if not clean_label:
                        reporter.error(
                            f"タグ '{clean_id}' の 'label' が不正です。",
                            path,
                        )
                    labels[clean_id] = clean_label
                    parents[clean_id] = parent

            children = node.get("children", [])
            if children is None:
                children = []
            visit(children, clean_id if clean_id else parent, f"{here}.children")
            active_objects.remove(object_id)

    visit(nodes, None, "tags")

    state: dict[str, int] = {}

    def visit_parent(tag_id: str) -> None:
        if state.get(tag_id) == 1:
            reporter.error(f"タグ '{tag_id}' の親関係に循環があります。", path)
            return
        if state.get(tag_id) == 2:
            return
        state[tag_id] = 1
        parent = parents.get(tag_id)
        if parent in parents:
            visit_parent(parent)
        state[tag_id] = 2

    for tag_id in parents:
        visit_parent(tag_id)

    return Taxonomy(labels, parents)


def validate_papers(
    root: Path,
    config: ExamConfig,
    reporter: Reporter,
) -> set[str]:
    path = root / "database" / config.name / "papers.yml"
    data = load_yaml(path, reporter)
    ids: set[str] = set()
    sort_orders: set[int] = set()
    if data is None:
        return ids

    papers = data.get("papers")
    if not isinstance(papers, list):
        reporter.error("'papers' はリストにしてください。", path)
        return ids

    paper_id_re = re.compile(
        rf"^{re.escape(config.paper_prefix)}[a-z0-9]+(?:-[a-z0-9]+)*$"
    )

    for index, paper in enumerate(papers, start=1):
        if not isinstance(paper, dict):
            reporter.error(f"papers[{index}] は辞書形式にしてください。", path)
            continue

        paper_id = paper.get("id")
        label = paper.get("label")
        sort_order = paper.get("sort_order")

        if not isinstance(paper_id, str) or not paper_id.strip():
            reporter.error(f"papers[{index}] の 'id' が不正です。", path)
            continue
        paper_id = paper_id.strip()

        if not paper_id_re.fullmatch(paper_id):
            reporter.error(f"paper_id '{paper_id}' の形式が不正です。", path)
        if paper_id in ids:
            reporter.error(f"paper_id '{paper_id}' が重複しています。", path)
        ids.add(paper_id)

        if not isinstance(label, str) or not label.strip():
            reporter.error(f"'{paper_id}' の 'label' が不正です。", path)

        if isinstance(sort_order, bool) or not isinstance(sort_order, int):
            reporter.error(f"'{paper_id}' の 'sort_order' は整数にしてください。", path)
        elif sort_order in sort_orders:
            reporter.error(f"sort_order '{sort_order}' が重複しています。", path)
        else:
            sort_orders.add(sort_order)

        year = paper.get("year")
        if year is not None and (
            isinstance(year, bool) or not isinstance(year, int) or year <= 0
        ):
            reporter.error(f"'{paper_id}' の 'year' が不正です。", path)

        round_value = paper.get("round")
        if round_value is not None and not isinstance(round_value, (str, int)):
            reporter.error(f"'{paper_id}' の 'round' が不正です。", path)

    return ids


def validate_no_cross_reference(
    path: Path,
    text: str,
    config: ExamConfig,
    reporter: Reporter,
) -> None:
    forbidden = (
        f"problems/{config.other_name}/",
        f"knowledge/{config.other_name}/",
        config.other_problem_prefix,
        config.other_paper_prefix,
    )
    for token in forbidden:
        if token in text:
            reporter.error(
                f"{config.other_name} 側への参照 '{token}' が含まれています。",
                path,
            )


def validate_problems(
    root: Path,
    config: ExamConfig,
    taxonomy: Taxonomy,
    paper_ids: set[str],
    reporter: Reporter,
    global_ids: dict[str, Path],
) -> int:
    directory = root / "problems" / config.name
    if not directory.is_dir():
        reporter.error("問題ディレクトリが見つかりません。", directory)
        return 0

    id_re = re.compile(rf"^{re.escape(config.problem_prefix)}\d{{6}}$")
    question_keys: dict[tuple[str, int], Path] = {}
    count = 0

    for path in sorted(directory.glob("*.qmd")):
        if path.name == "index.qmd":
            continue
        count += 1
        metadata, _ = read_front_matter(path, reporter)
        if metadata is None:
            continue

        text = path.read_text(encoding="utf-8")
        validate_no_cross_reference(path, text, config, reporter)

        title = metadata.get("title")
        problem_id = metadata.get("id")
        paper_id = metadata.get("paper_id")
        question_number = metadata.get("question_number")
        cell_label = metadata.get("cell_label")
        tags = metadata.get("tags")

        if not isinstance(title, str) or not title.strip():
            reporter.error("'title' は空でない文字列にしてください。", path)

        clean_problem_id: str | None = None
        if not isinstance(problem_id, str) or not problem_id.strip():
            reporter.error("'id' は空でない文字列にしてください。", path)
        else:
            clean_problem_id = problem_id.strip()
            if not id_re.fullmatch(clean_problem_id):
                reporter.error(f"問題ID '{clean_problem_id}' の形式が不正です。", path)
            if path.stem != clean_problem_id:
                reporter.error(
                    f"ファイル名 '{path.stem}' とID '{clean_problem_id}' が一致しません。",
                    path,
                )
            if clean_problem_id in global_ids:
                previous = global_ids[clean_problem_id].relative_to(root)
                reporter.error(
                    f"問題ID '{clean_problem_id}' が '{previous}' と重複しています。",
                    path,
                )
            else:
                global_ids[clean_problem_id] = path

        clean_paper_id: str | None = None
        if not isinstance(paper_id, str) or not paper_id.strip():
            reporter.error("'paper_id' は空でない文字列にしてください。", path)
        else:
            clean_paper_id = paper_id.strip()
            if not clean_paper_id.startswith(config.paper_prefix):
                reporter.error(
                    f"paper_id '{clean_paper_id}' は '{config.paper_prefix}' で始めてください。",
                    path,
                )
            if clean_paper_id not in paper_ids:
                reporter.error(
                    f"paper_id '{clean_paper_id}' がpapers.ymlに存在しません。",
                    path,
                )

        clean_question: int | None = None
        if (
            isinstance(question_number, bool)
            or not isinstance(question_number, int)
            or question_number <= 0
        ):
            reporter.error("'question_number' は正の整数にしてください。", path)
        else:
            clean_question = question_number

        if clean_paper_id is not None and clean_question is not None:
            key = (clean_paper_id, clean_question)
            if key in question_keys:
                previous = question_keys[key].relative_to(root)
                reporter.error(
                    f"同一paper_id内の問{clean_question}が '{previous}' と重複しています。",
                    path,
                )
            else:
                question_keys[key] = path

        if not isinstance(cell_label, str) or not cell_label.strip():
            reporter.error("'cell_label' は空でない文字列にしてください。", path)

        clean_tags: list[str] = []
        if not isinstance(tags, list):
            reporter.error("'tags' はリストにしてください。", path)
        else:
            seen: set[str] = set()
            for index, tag_id in enumerate(tags, start=1):
                if not isinstance(tag_id, str) or not tag_id.strip():
                    reporter.error(f"tags[{index}] が不正です。", path)
                    continue
                tag_id = tag_id.strip()
                if tag_id in seen:
                    reporter.error(f"タグ '{tag_id}' が重複しています。", path)
                    continue
                seen.add(tag_id)
                clean_tags.append(tag_id)
                if tag_id not in taxonomy.labels:
                    reporter.error(
                        f"タグ '{tag_id}' がtaxonomy.ymlに存在しません。",
                        path,
                    )
            if not clean_tags:
                reporter.warning("タグが1つも設定されていません。", path)

        for i, left in enumerate(clean_tags):
            for right in clean_tags[i + 1 :]:
                if taxonomy.is_ancestor(left, right):
                    reporter.error(
                        f"親タグ '{left}' と子タグ '{right}' を同時指定しています。",
                        path,
                    )
                elif taxonomy.is_ancestor(right, left):
                    reporter.error(
                        f"親タグ '{right}' と子タグ '{left}' を同時指定しています。",
                        path,
                    )

    return count


def validate_knowledge(
    root: Path,
    config: ExamConfig,
    taxonomy: Taxonomy,
    reporter: Reporter,
) -> int:
    directory = root / "knowledge" / config.name
    if not directory.is_dir():
        reporter.error("知識ページディレクトリが見つかりません。", directory)
        return 0

    pages: dict[str, Path] = {}
    for path in sorted(directory.glob("*.qmd")):
        if path.name == "index.qmd":
            continue
        page_id = path.stem
        pages[page_id] = path
        metadata, _ = read_front_matter(path, reporter)
        if metadata is None:
            continue

        text = path.read_text(encoding="utf-8")
        validate_no_cross_reference(path, text, config, reporter)

        if not TAG_ID_RE.fullmatch(page_id):
            reporter.error(f"ファイル名 '{page_id}' の形式が不正です。", path)
        if page_id not in taxonomy.labels:
            reporter.error(
                f"'{page_id}' に対応するタグがtaxonomy.ymlにありません。",
                path,
            )
        if metadata.get("id") != page_id:
            reporter.error(
                f"front matterのid '{metadata.get('id')}' とファイル名が一致しません。",
                path,
            )

        title = metadata.get("title")
        if not isinstance(title, str) or not title.strip():
            reporter.error("'title' は空でない文字列にしてください。", path)
        elif page_id in taxonomy.labels and title.strip() != taxonomy.labels[page_id]:
            reporter.warning(
                f"title '{title.strip()}' とtaxonomyのlabel "
                f"'{taxonomy.labels[page_id]}' が一致しません。",
                path,
            )

    for tag_id in sorted(taxonomy.labels):
        if tag_id not in pages:
            reporter.error(
                f"knowledge/{config.name}/{tag_id}.qmd がありません。"
            )

    return len(pages)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="数検1級DBの整合性を検証します。")
    parser.add_argument(
        "--exam",
        choices=("primary", "secondary", "all"),
        default="all",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="警告も失敗として扱います。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    reporter = Reporter(root)
    global_ids: dict[str, Path] = {}
    names = tuple(EXAMS) if args.exam == "all" else (args.exam,)
    stats: dict[str, Stats] = {}

    for name in names:
        config = EXAMS[name]
        taxonomy = validate_taxonomy(root, config, reporter)
        paper_ids = validate_papers(root, config, reporter)
        problems = validate_problems(
            root, config, taxonomy, paper_ids, reporter, global_ids
        )
        knowledge_pages = validate_knowledge(root, config, taxonomy, reporter)
        stats[name] = Stats(
            len(paper_ids), problems, len(taxonomy.labels), knowledge_pages
        )

    print("=== 検証対象 ===")
    for name, value in stats.items():
        print(
            f"{name}: 試験用紙={value.papers}, 問題={value.problems}, "
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

    print("\n=== 結果 ===")
    print(f"エラー: {len(reporter.errors)}件")
    print(f"警告: {len(reporter.warnings)}件")

    if reporter.errors:
        print("Validation failed.")
        return 1
    if args.strict and reporter.warnings:
        print("Validation failed in strict mode.")
        return 1

    print("Validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
