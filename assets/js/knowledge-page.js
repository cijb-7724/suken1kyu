const EXAM_LABELS = Object.freeze({ primary: "1次", secondary: "2次" });

const app = document.querySelector("[data-knowledge-page]");
if (!app) {
  throw new Error("knowledge page app が見つかりません。");
}

const pathParts = window.location.pathname.split("/").filter(Boolean);
const examIndex = pathParts.findIndex((part) => part === "primary" || part === "secondary");
const exam = examIndex >= 0 ? pathParts[examIndex] : null;
const filename = pathParts.at(-1) || "";
const tagId = decodeURIComponent(filename.replace(/\.html$/, ""));
const siteRoot = new URL("../../", window.location.href);

function makeElement(tagName, options = {}) {
  const element = document.createElement(tagName);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = options.text;
  if (options.attributes) {
    for (const [name, value] of Object.entries(options.attributes)) {
      element.setAttribute(name, String(value));
    }
  }
  return element;
}

function rootUrl(path) {
  return new URL(path, siteRoot).href;
}

async function fetchJson(path) {
  const response = await fetch(rootUrl(path), {
    headers: { Accept: "application/json" },
    cache: "no-cache",
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${path}`);
  return response.json();
}

function paperMap(payload) {
  return new Map(payload.papers.map((paper) => [paper.id, paper]));
}

function problemMap(payload) {
  return new Map(payload.problems.map((problem) => [problem.id, problem]));
}

function sortedProblemIds(tag, problemById, paperById) {
  return [...tag.problem_ids].sort((leftId, rightId) => {
    const left = problemById.get(leftId);
    const right = problemById.get(rightId);
    if (!left || !right) return String(leftId).localeCompare(String(rightId));
    const leftPaper = paperById.get(left.paper_id);
    const rightPaper = paperById.get(right.paper_id);
    const order = Number(rightPaper?.sort_order || 0) - Number(leftPaper?.sort_order || 0);
    if (order !== 0) return order;
    return left.question_number - right.question_number;
  });
}

function insertHeader(tag, tagsById) {
  const title = document.querySelector("main h1, h1.title");
  if (!title || document.querySelector(".knowledge-page-header")) return;

  const header = makeElement("div", { className: "knowledge-page-header" });
  const breadcrumb = makeElement("nav", {
    className: "knowledge-breadcrumb",
    attributes: { "aria-label": "知識階層" },
  });

  const crumbs = [
    { label: "知識", href: rootUrl(`knowledge/?exam=${exam}`) },
    { label: `${EXAM_LABELS[exam]}試験`, href: rootUrl(`knowledge/?exam=${exam}`) },
    ...tag.ancestors.map((id) => ({
      label: tagsById[id]?.label || id,
      href: rootUrl(tagsById[id]?.knowledge_path || `knowledge/${exam}/${id}.html`),
    })),
    { label: tag.label, href: null },
  ];

  crumbs.forEach((crumb, index) => {
    if (index > 0) {
      breadcrumb.append(
        makeElement("span", { className: "knowledge-breadcrumb-separator", text: "›" }),
      );
    }
    if (crumb.href) {
      breadcrumb.append(
        makeElement("a", {
          className: "knowledge-link",
          text: crumb.label,
          attributes: { href: crumb.href },
        }),
      );
    } else {
      breadcrumb.append(makeElement("span", { text: crumb.label }));
    }
  });

  const meta = makeElement("div", { className: "knowledge-header-meta" });
  meta.append(
    makeElement("span", {
      className: "knowledge-chip is-exam",
      text: `${EXAM_LABELS[exam]}試験`,
    }),
    makeElement("span", {
      className: "knowledge-chip",
      text: `関連問題 ${tag.problem_count}問`,
    }),
    makeElement("span", {
      className: "knowledge-chip",
      text: `直接使用 ${tag.direct_problem_count}問`,
    }),
  );

  header.append(breadcrumb, meta);
  title.insertAdjacentElement("afterend", header);
}

function relationCard(tag, relationLabel) {
  const card = makeElement("a", {
    className: "knowledge-relation-card",
    attributes: { href: rootUrl(tag.knowledge_path) },
  });
  card.append(
    makeElement("span", { className: "knowledge-relation-label", text: tag.label }),
    makeElement("span", {
      className: "knowledge-relation-meta",
      text: `${relationLabel}・関連 ${tag.problem_count}問`,
    }),
  );
  return card;
}

function renderRelations(tag, tagsById) {
  const section = makeElement("section", { className: "knowledge-auto-section" });
  section.append(makeElement("h2", { text: "知識体系での位置" }));
  const grid = makeElement("div", { className: "knowledge-relation-grid" });

  if (tag.parent_id && tagsById[tag.parent_id]) {
    grid.append(relationCard(tagsById[tag.parent_id], "上位概念"));
  }
  for (const childId of tag.children) {
    const child = tagsById[childId];
    if (child) grid.append(relationCard(child, "下位概念"));
  }

  if (!grid.childElementCount) {
    section.append(
      makeElement("p", {
        className: "catalog-status",
        text: "現在、この知識に登録された上位・下位概念はありません。",
      }),
    );
  } else {
    section.append(grid);
  }
  return section;
}

function renderSiblings(tag, tagsById) {
  if (!tag.parent_id) return null;
  const parent = tagsById[tag.parent_id];
  if (!parent) return null;
  const siblings = parent.children
    .filter((id) => id !== tag.id)
    .map((id) => tagsById[id])
    .filter(Boolean);
  if (!siblings.length) return null;

  const section = makeElement("section", { className: "knowledge-auto-section" });
  section.append(makeElement("h2", { text: "同じ階層の知識" }));
  const grid = makeElement("div", { className: "knowledge-relation-grid" });
  siblings.forEach((sibling) => grid.append(relationCard(sibling, parent.label)));
  section.append(grid);
  return section;
}

function renderProblems(tag, problemById, paperById) {
  const section = makeElement("section", { className: "knowledge-auto-section" });
  section.append(makeElement("h2", { text: "関連問題" }));

  const ids = sortedProblemIds(tag, problemById, paperById);
  if (!ids.length) {
    section.append(
      makeElement("p", {
        className: "catalog-status",
        text: "この知識に関連する問題はまだ登録されていません。",
      }),
    );
    return section;
  }

  const list = makeElement("div", { className: "knowledge-problem-list" });
  for (const problemId of ids) {
    const problem = problemById.get(problemId);
    if (!problem) continue;
    const paper = paperById.get(problem.paper_id);
    const direct = tag.direct_problem_ids.includes(problemId);
    const card = makeElement("a", {
      className: "knowledge-problem-card",
      attributes: { href: rootUrl(problem.path) },
    });
    const text = makeElement("div");
    text.append(
      makeElement("span", {
        className: "knowledge-problem-title",
        text: `${paper?.label || problem.paper_id} 問${problem.question_number}：${problem.cell_label}`,
      }),
      makeElement("span", {
        className: "knowledge-problem-meta",
        text: problem.title,
      }),
    );
    card.append(
      text,
      makeElement("span", {
        className: "knowledge-problem-badge",
        text: direct ? "直接タグ" : "下位概念経由",
      }),
    );
    list.append(card);
  }
  section.append(list);
  return section;
}

async function main() {
  if (!exam || !EXAM_LABELS[exam] || !tagId) return;

  try {
    const [tagsPayload, problemsPayload, papersPayload] = await Promise.all([
      fetchJson(`_generated/${exam}/tags.json`),
      fetchJson(`_generated/${exam}/problems.json`),
      fetchJson(`_generated/${exam}/papers.json`),
    ]);
    const tag = tagsPayload.by_id?.[tagId];
    if (!tag) throw new Error(`タグ '${tagId}' が tags.json にありません。`);

    insertHeader(tag, tagsPayload.by_id);
    app.replaceChildren();
    app.append(renderRelations(tag, tagsPayload.by_id));
    const siblings = renderSiblings(tag, tagsPayload.by_id);
    if (siblings) app.append(siblings);
    app.append(renderProblems(tag, problemMap(problemsPayload), paperMap(papersPayload)));
  } catch (error) {
    console.error(error);
    app.replaceChildren(
      makeElement("p", {
        className: "catalog-status is-error",
        text: "知識ページの関連データを読み込めませんでした。",
      }),
    );
  }
}

main();
