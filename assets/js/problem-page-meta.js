const EXAM_LABELS = Object.freeze({ primary: "1次", secondary: "2次" });

const app = document.querySelector("[data-problem-page]");
if (!app) {
  throw new Error("problem page app が見つかりません。");
}

const pathParts = window.location.pathname.split("/").filter(Boolean);
const examIndex = pathParts.findIndex((part) => part === "primary" || part === "secondary");
const exam = examIndex >= 0 ? pathParts[examIndex] : null;
const filename = pathParts.at(-1) || "";
const problemId = decodeURIComponent(filename.replace(/\.html$/, ""));
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

function insertMeta(problem, tagsById, paper) {
  const title = document.querySelector("main h1, h1.title");
  if (!title || document.querySelector(".problem-page-meta-bar")) return;

  const bar = makeElement("div", { className: "problem-page-meta-bar" });
  const back = makeElement("div", { className: "problem-page-back" });
  back.append(
    makeElement("a", {
      className: "problem-meta-link",
      text: "← 過去問一覧",
      attributes: { href: rootUrl(`problems/?exam=${exam}`) },
    }),
  );

  const main = makeElement("div", { className: "problem-page-meta-main" });
  main.append(
    makeElement("span", {
      className: "problem-meta-chip is-exam",
      text: `${EXAM_LABELS[exam]}試験`,
    }),
    makeElement("span", {
      className: "problem-meta-chip",
      text: `${paper?.label || problem.paper_id}・問${problem.question_number}`,
    }),
  );

  const tags = makeElement("div", {
    className: "problem-tag-list",
    attributes: { "aria-label": "この問題のタグ" },
  });
  for (const tagId of problem.direct_tags || []) {
    const tag = tagsById[tagId];
    if (!tag) continue;
    tags.append(
      makeElement("a", {
        className: "problem-tag-chip",
        text: tag.label,
        attributes: {
          href: rootUrl(tag.knowledge_path),
          title: `知識ページ「${tag.label}」を開く`,
        },
      }),
    );
  }

  bar.append(back, main);
  if (tags.childElementCount) bar.append(tags);
  title.insertAdjacentElement("afterend", bar);
}

async function main() {
  if (!exam || !EXAM_LABELS[exam] || !problemId) return;

  try {
    const [problemsPayload, tagsPayload, papersPayload] = await Promise.all([
      fetchJson(`_generated/${exam}/problems.json`),
      fetchJson(`_generated/${exam}/tags.json`),
      fetchJson(`_generated/${exam}/papers.json`),
    ]);
    const problem = problemsPayload.problems.find((item) => item.id === problemId);
    if (!problem) throw new Error(`問題 '${problemId}' が problems.json にありません。`);
    const paper = papersPayload.papers.find((item) => item.id === problem.paper_id);
    insertMeta(problem, tagsPayload.by_id || {}, paper);
    app.hidden = true;
  } catch (error) {
    console.error(error);
    app.hidden = true;
  }
}

main();
