const EXAMS = Object.freeze({
  primary: { label: "1次", tabId: "catalog-tab-primary" },
  secondary: { label: "2次", tabId: "catalog-tab-secondary" },
});

const VALID_EXAMS = new Set(Object.keys(EXAMS));
const VALID_VIEWS = new Set(["hierarchy", "list"]);
const cache = new Map();

const app = document.querySelector("#catalog-app");
if (!app) {
  throw new Error("catalog app が見つかりません。");
}

const mode = app.dataset.catalogMode || "knowledge";
const tabs = Array.from(app.querySelectorAll(".catalog-tab[data-exam]"));
const searchInput = app.querySelector("#catalog-search");
const summary = app.querySelector("#catalog-summary");
const status = app.querySelector("#catalog-status");
const content = app.querySelector("#catalog-content");
const viewButtons = Array.from(app.querySelectorAll(".catalog-view-button[data-view]"));
const siteRoot = new URL("../", window.location.href);

let activePayload = null;

function normalizeText(value) {
  return String(value ?? "").normalize("NFKC").toLocaleLowerCase("ja").trim();
}

function examFromUrl() {
  const value = new URL(window.location.href).searchParams.get("exam");
  return VALID_EXAMS.has(value) ? value : app.dataset.defaultExam || "primary";
}

function viewFromUrl() {
  if (mode !== "tags") return "hierarchy";
  const value = new URL(window.location.href).searchParams.get("view");
  return VALID_VIEWS.has(value) ? value : "hierarchy";
}

function updateUrl({ exam = examFromUrl(), view = viewFromUrl() }, historyMode = "push") {
  const url = new URL(window.location.href);
  url.searchParams.set("exam", exam);
  if (mode === "tags") {
    url.searchParams.set("view", view);
  } else {
    url.searchParams.delete("view");
  }
  const method = historyMode === "replace" ? "replaceState" : "pushState";
  window.history[method]({ exam, view }, "", url);
}

function setTabState(exam) {
  for (const tab of tabs) {
    const active = tab.dataset.exam === exam;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  }
}

function setViewState(view) {
  for (const button of viewButtons) {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function setStatus(message, kind = "loading") {
  status.hidden = false;
  status.className = `catalog-status is-${kind}`;
  status.textContent = message;
}

function hideStatus() {
  status.hidden = true;
}

function makeElement(tagName, options = {}) {
  const element = document.createElement(tagName);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = options.text;
  if (options.attributes) {
    for (const [key, value] of Object.entries(options.attributes)) {
      element.setAttribute(key, String(value));
    }
  }
  return element;
}

function dataUrl(exam, filename) {
  return new URL(`_generated/${exam}/${filename}`, siteRoot);
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: { Accept: "application/json" },
    cache: "no-cache",
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  return response.json();
}

async function loadData(exam, force = false) {
  if (force) cache.delete(exam);
  if (!cache.has(exam)) {
    cache.set(
      exam,
      Promise.all([
        fetchJson(dataUrl(exam, "tags.json")),
        fetchJson(dataUrl(exam, "problems.json")),
      ]).then(([tags, problems]) => ({ tags, problems })),
    );
  }
  try {
    return await cache.get(exam);
  } catch (error) {
    cache.delete(exam);
    throw error;
  }
}

function knowledgeHref(tag) {
  return new URL(tag.knowledge_path, siteRoot).href;
}

function tagPath(tag, byId) {
  return [...tag.ancestors, tag.id]
    .map((tagId) => byId[tagId]?.label || tagId)
    .join(" › ");
}

function searchableText(tag, byId) {
  return normalizeText(`${tag.label} ${tag.id} ${tagPath(tag, byId)}`);
}

function renderSummary(exam, payload) {
  summary.replaceChildren();
  const cards = [
    [payload.tags.count, "知識・タグ"],
    [payload.problems.count, "登録問題"],
    [payload.tags.root_ids.length, "大分類"],
  ];

  for (const [value, label] of cards) {
    const card = makeElement("div", { className: "catalog-summary-card" });
    card.append(
      makeElement("span", { className: "catalog-summary-value", text: value }),
      makeElement("span", {
        className: "catalog-summary-label",
        text: `${EXAMS[exam].label}試験の${label}`,
      }),
    );
    summary.append(card);
  }
}

function tagMatches(tag, query, byId) {
  return !query || searchableText(tag, byId).includes(query);
}

function branchMatches(node, query, byId) {
  if (!query) return true;
  const tag = byId[node.id];
  if (tag && tagMatches(tag, query, byId)) return true;
  return (node.children || []).some((child) => branchMatches(child, query, byId));
}

function renderTreeItems(nodes, query, byId, { omitRoot = false } = {}) {
  const list = makeElement("ul", { className: "catalog-tree" });

  for (const node of nodes) {
    if (!branchMatches(node, query, byId)) continue;
    const tag = byId[node.id];
    if (!tag) continue;

    const item = makeElement("li", { className: "catalog-tree-item" });
    const row = makeElement("div", { className: "catalog-tree-row" });
    const link = makeElement("a", {
      className: "catalog-link",
      text: tag.label,
      attributes: { href: knowledgeHref(tag) },
    });
    const count = makeElement("span", {
      className: "catalog-count",
      text: `${tag.problem_count}問`,
      attributes: { title: `この概念と下位概念に関連する問題数: ${tag.problem_count}` },
    });
    row.append(link, count);
    item.append(row);

    if (node.children?.length) {
      const childList = renderTreeItems(node.children, query, byId);
      if (childList.childElementCount) item.append(childList);
    }
    list.append(item);
  }

  return list;
}

function renderKnowledgeHierarchy(payload, query) {
  const fragment = document.createDocumentFragment();
  const grid = makeElement("div", { className: "catalog-category-grid" });
  const byId = payload.tags.by_id;

  for (const rootNode of payload.tags.tree) {
    if (!branchMatches(rootNode, query, byId)) continue;
    const rootTag = byId[rootNode.id];
    if (!rootTag) continue;

    const card = makeElement("section", { className: "catalog-category-card" });
    const header = makeElement("div", { className: "catalog-category-header" });
    const title = makeElement("h2", { className: "catalog-category-title" });
    title.append(
      makeElement("a", {
        className: "catalog-link",
        text: rootTag.label,
        attributes: { href: knowledgeHref(rootTag) },
      }),
    );
    header.append(
      title,
      makeElement("span", { className: "catalog-count", text: `${rootTag.problem_count}問` }),
    );
    card.append(header);

    if (rootNode.children?.length) {
      card.append(renderTreeItems(rootNode.children, query, byId));
    } else {
      const solo = makeElement("div", { className: "catalog-tree" });
      solo.append(
        makeElement("p", {
          className: "catalog-tag-path",
          text: "この分類には現在、下位概念がありません。",
        }),
      );
      card.append(solo);
    }
    grid.append(card);
  }

  if (!grid.childElementCount) {
    fragment.append(
      makeElement("div", {
        className: "catalog-empty",
        text: "一致する知識項目がありません。",
      }),
    );
  } else {
    fragment.append(grid);
  }
  return fragment;
}

function renderFlatList(payload, query) {
  const byId = payload.tags.by_id;
  const tags = Object.values(byId)
    .filter((tag) => tagMatches(tag, query, byId))
    .sort((left, right) => {
      const depth = left.depth - right.depth;
      if (depth !== 0) return depth;
      return left.label.localeCompare(right.label, "ja");
    });

  if (!tags.length) {
    return makeElement("div", {
      className: "catalog-empty",
      text: "一致するタグがありません。",
    });
  }

  const list = makeElement("div", { className: "catalog-flat-list" });
  for (const tag of tags) {
    const card = makeElement("a", {
      className: "catalog-tag-card catalog-link",
      attributes: { href: knowledgeHref(tag) },
    });
    card.append(
      makeElement("h2", { className: "catalog-tag-title", text: tag.label }),
      makeElement("div", { className: "catalog-tag-id", text: tag.id }),
      makeElement("p", { className: "catalog-tag-path", text: tagPath(tag, byId) }),
    );

    const stats = makeElement("div", { className: "catalog-tag-stats" });
    stats.append(
      makeElement("span", {
        className: "catalog-stat-chip",
        text: `関連 ${tag.problem_count}問`,
      }),
      makeElement("span", {
        className: "catalog-stat-chip",
        text: `直接 ${tag.direct_problem_count}問`,
      }),
    );
    card.append(stats);
    list.append(card);
  }
  return list;
}

function renderContent() {
  if (!activePayload) return;
  const query = normalizeText(searchInput?.value || "");
  const view = viewFromUrl();
  content.replaceChildren();

  if (mode === "knowledge") {
    content.append(renderKnowledgeHierarchy(activePayload, query));
    return;
  }

  if (view === "list") {
    content.append(renderFlatList(activePayload, query));
  } else {
    content.append(renderKnowledgeHierarchy(activePayload, query));
  }
}

function renderError(exam, error) {
  console.error(error);
  activePayload = null;
  summary.replaceChildren();
  content.replaceChildren();
  status.replaceChildren();
  status.hidden = false;
  status.className = "catalog-status is-error";
  status.append(document.createTextNode("知識データを読み込めませんでした。"));
  const retry = makeElement("button", {
    className: "catalog-retry",
    text: "再読み込み",
    attributes: { type: "button" },
  });
  retry.addEventListener("click", () => renderExam(exam, true));
  status.append(document.createElement("br"), retry);
}

async function renderExam(exam, force = false) {
  setTabState(exam);
  setViewState(viewFromUrl());
  activePayload = null;
  summary.replaceChildren();
  content.replaceChildren();
  setStatus(`${EXAMS[exam].label}試験の知識データを読み込んでいます…`);

  try {
    const payload = await loadData(exam, force);
    if (exam !== examFromUrl()) return;
    activePayload = payload;
    renderSummary(exam, payload);
    hideStatus();
    renderContent();
  } catch (error) {
    if (exam === examFromUrl()) renderError(exam, error);
  }
}

function selectExam(exam, historyMode = "push") {
  if (!VALID_EXAMS.has(exam)) return;
  updateUrl({ exam, view: viewFromUrl() }, historyMode);
  if (searchInput) searchInput.value = "";
  renderExam(exam);
}

for (const tab of tabs) {
  tab.addEventListener("click", () => selectExam(tab.dataset.exam));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = tabs.indexOf(tab);
    let next = current;
    if (event.key === "ArrowLeft") next = (current - 1 + tabs.length) % tabs.length;
    if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    tabs[next].focus();
    selectExam(tabs[next].dataset.exam);
  });
}

for (const button of viewButtons) {
  button.addEventListener("click", () => {
    const view = button.dataset.view;
    if (!VALID_VIEWS.has(view)) return;
    updateUrl({ exam: examFromUrl(), view });
    setViewState(view);
    renderContent();
  });
}

searchInput?.addEventListener("input", renderContent);

window.addEventListener("popstate", () => {
  setViewState(viewFromUrl());
  renderExam(examFromUrl());
});

const initialExam = examFromUrl();
const initialView = viewFromUrl();
const initialUrl = new URL(window.location.href);
if (
  initialUrl.searchParams.get("exam") !== initialExam ||
  (mode === "tags" && initialUrl.searchParams.get("view") !== initialView)
) {
  updateUrl({ exam: initialExam, view: initialView }, "replace");
}
renderExam(initialExam);
