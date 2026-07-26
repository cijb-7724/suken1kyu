const EXAMS = Object.freeze({
  primary: {
    label: "1次",
    tabId: "exam-tab-primary",
    headerGroups: [],
  },
  secondary: {
    label: "2次",
    tabId: "exam-tab-secondary",
    headerGroups: [
      { label: "選択問題", start: 1, end: 5, kind: "elective" },
      { label: "必須問題", start: 6, end: 7, kind: "required" },
    ],
  },
});

const QUESTION_COUNT = 7;
const VALID_EXAMS = new Set(Object.keys(EXAMS));
const dataCache = new Map();

const app = document.querySelector("#problem-table-app");
const tabs = Array.from(document.querySelectorAll(".exam-tab[data-exam]"));
const panel = document.querySelector("#problem-table-panel");
const statusElement = document.querySelector("#problem-table-status");
const container = document.querySelector("#problem-table-container");

if (!app || !panel || !statusElement || !container || tabs.length !== 2) {
  throw new Error("過去問一覧のHTML構造が不正です。");
}

// problems/index.html から一つ上をサイトのルートとして扱う。
// GitHub Pagesのサブディレクトリ公開でも相対URLのまま動作する。
const siteRoot = new URL("../", window.location.href);

function examFromUrl() {
  const value = new URL(window.location.href).searchParams.get("exam");
  return VALID_EXAMS.has(value) ? value : app.dataset.defaultExam || "primary";
}

function updateUrl(exam, mode = "push") {
  const url = new URL(window.location.href);
  url.searchParams.set("exam", exam);
  const state = { exam };

  if (mode === "replace") {
    window.history.replaceState(state, "", url);
  } else {
    window.history.pushState(state, "", url);
  }
}

function setTabState(exam) {
  for (const tab of tabs) {
    const isActive = tab.dataset.exam === exam;
    tab.setAttribute("aria-selected", String(isActive));
    tab.tabIndex = isActive ? 0 : -1;
    tab.classList.toggle("is-active", isActive);
  }

  panel.setAttribute("aria-labelledby", EXAMS[exam].tabId);
}

function setStatus(message, kind = "loading") {
  statusElement.hidden = false;
  statusElement.textContent = message;
  statusElement.className = `problem-table-status is-${kind}`;
}

function hideStatus() {
  statusElement.hidden = true;
}

function dataUrl(exam) {
  return new URL(`_generated/${exam}/papers.json`, siteRoot);
}

function problemUrl(path) {
  return new URL(path, siteRoot).href;
}

async function loadPapers(exam, forceReload = false) {
  if (forceReload) {
    dataCache.delete(exam);
  }

  if (!dataCache.has(exam)) {
    const request = fetch(dataUrl(exam), {
      headers: { Accept: "application/json" },
      cache: "no-cache",
    }).then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const payload = await response.json();
      if (!payload || !Array.isArray(payload.papers)) {
        throw new Error("papers.json の形式が不正です。");
      }
      return payload;
    });

    dataCache.set(exam, request);
  }

  try {
    return await dataCache.get(exam);
  } catch (error) {
    dataCache.delete(exam);
    throw error;
  }
}

function numericSortOrder(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : Number.NEGATIVE_INFINITY;
}

function sortNewestFirst(papers) {
  return [...papers].sort((left, right) => {
    const orderDifference =
      numericSortOrder(right.sort_order) - numericSortOrder(left.sort_order);

    if (orderDifference !== 0) {
      return orderDifference;
    }

    return String(right.id).localeCompare(String(left.id), "ja");
  });
}

function makeElement(tagName, options = {}) {
  const element = document.createElement(tagName);

  if (options.className) {
    element.className = options.className;
  }
  if (options.text !== undefined) {
    element.textContent = options.text;
  }
  if (options.attributes) {
    for (const [name, value] of Object.entries(options.attributes)) {
      element.setAttribute(name, String(value));
    }
  }

  return element;
}

function buildTableHead(exam) {
  const thead = document.createElement("thead");
  const questionRow = makeElement("tr", {
    className: `problem-table-question-row${exam === "primary" ? " is-single-row" : ""}`,
  });

  if (exam === "primary") {
    const paperHeader = makeElement("th", {
      className: "paper-heading",
      text: "実施回",
      attributes: { scope: "col" },
    });
    questionRow.append(paperHeader);
  } else {
    const groupRow = makeElement("tr", { className: "problem-table-group-row" });
    const paperHeader = makeElement("th", {
      className: "paper-heading",
      text: "実施回",
      attributes: { scope: "col", rowspan: "2" },
    });
    groupRow.append(paperHeader);

    for (const group of EXAMS[exam].headerGroups) {
      const groupHeader = makeElement("th", {
        className: `question-group question-group-${group.kind}`,
        text: group.label,
        attributes: {
          scope: "colgroup",
          colspan: group.end - group.start + 1,
        },
      });

      if (group.start === 6) {
        groupHeader.classList.add("mandatory-boundary");
      }
      groupRow.append(groupHeader);
    }

    thead.append(groupRow);
  }

  for (let questionNumber = 1; questionNumber <= QUESTION_COUNT; questionNumber += 1) {
    const header = makeElement("th", {
      className: "question-heading",
      text: `問${questionNumber}`,
      attributes: { scope: "col" },
    });

    if (exam === "secondary" && questionNumber === 6) {
      header.classList.add("mandatory-boundary");
    }
    questionRow.append(header);
  }

  thead.append(questionRow);
  return thead;
}

function buildColumnGroup() {
  const colgroup = document.createElement("colgroup");
  const paperColumn = makeElement("col", { className: "paper-column" });
  colgroup.append(paperColumn);

  for (let questionNumber = 1; questionNumber <= QUESTION_COUNT; questionNumber += 1) {
    const questionColumn = makeElement("col", { className: "question-column" });
    colgroup.append(questionColumn);
  }

  return colgroup;
}

function buildTableBody(exam, papers) {
  const tbody = document.createElement("tbody");

  for (const paper of papers) {
    const row = document.createElement("tr");

    const paperCell = makeElement("th", {
      className: "paper-label",
      text: paper.label,
      attributes: { scope: "row" },
    });
    row.append(paperCell);

    for (let questionNumber = 1; questionNumber <= QUESTION_COUNT; questionNumber += 1) {
      const question = paper.questions?.[String(questionNumber)];
      const cell = makeElement("td", { className: "problem-cell" });

      if (exam === "secondary" && questionNumber === 6) {
        cell.classList.add("mandatory-boundary");
      }

      if (!question) {
        cell.classList.add("is-empty");
        cell.textContent = "—";
        cell.setAttribute("aria-label", `${paper.label} 問${questionNumber}：未登録`);
      } else {
        const label = String(question.cell_label || `問${questionNumber}`);
        const link = makeElement("a", {
          className: "problem-link",
          text: label,
          attributes: {
            href: problemUrl(question.path),
            title: `${paper.label} 問${questionNumber}：${label}`,
            "aria-label": `${paper.label} 問${questionNumber} ${label}`,
          },
        });
        cell.append(link);
      }

      row.append(cell);
    }

    tbody.append(row);
  }

  return tbody;
}

function renderTable(exam, payload) {
  const papers = sortNewestFirst(payload.papers);
  container.replaceChildren();

  if (papers.length === 0) {
    setStatus(`${EXAMS[exam].label}試験の過去問はまだ登録されていません。`, "empty");
    return;
  }

  const scrollArea = makeElement("div", {
    className: "problem-table-scroll",
    attributes: {
      tabindex: "0",
      "aria-label": `${EXAMS[exam].label}試験の過去問一覧。横方向にもスクロールできます。`,
    },
  });

  const table = makeElement("table", { className: "problem-table" });
  const caption = makeElement("caption", {
    className: "visually-hidden",
    text: `${EXAMS[exam].label}試験の過去問一覧。新しい実施回から順に表示しています。`,
  });

  table.append(caption, buildColumnGroup(), buildTableHead(exam), buildTableBody(exam, papers));
  scrollArea.append(table);
  container.append(scrollArea);
  hideStatus();
}

function renderError(exam, error) {
  console.error(error);
  container.replaceChildren();
  setStatus("過去問データを読み込めませんでした。", "error");

  const errorBox = makeElement("div", {
    className: "problem-table-error",
    attributes: { role: "alert" },
  });
  const retryButton = makeElement("button", {
    className: "problem-table-retry",
    text: "再読み込み",
    attributes: { type: "button" },
  });

  retryButton.addEventListener("click", () => renderExam(exam, true));
  errorBox.append(retryButton);
  container.append(errorBox);
}

async function renderExam(exam, forceReload = false) {
  setTabState(exam);
  container.replaceChildren();
  setStatus(`${EXAMS[exam].label}試験の過去問データを読み込んでいます…`, "loading");

  try {
    const payload = await loadPapers(exam, forceReload);
    // 読み込み中に別タブへ移った場合、古い結果で上書きしない。
    if (exam !== examFromUrl()) {
      return;
    }
    renderTable(exam, payload);
  } catch (error) {
    if (exam === examFromUrl()) {
      renderError(exam, error);
    }
  }
}

function selectExam(exam, { historyMode = "push" } = {}) {
  if (!VALID_EXAMS.has(exam)) {
    return;
  }

  const currentExam = examFromUrl();
  if (historyMode && currentExam !== exam) {
    updateUrl(exam, historyMode);
  }

  renderExam(exam);
}

for (const tab of tabs) {
  tab.addEventListener("click", () => {
    selectExam(tab.dataset.exam, { historyMode: "push" });
  });

  tab.addEventListener("keydown", (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      return;
    }

    event.preventDefault();
    const currentIndex = tabs.indexOf(tab);
    let nextIndex = currentIndex;

    if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;

    tabs[nextIndex].focus();
    selectExam(tabs[nextIndex].dataset.exam, { historyMode: "push" });
  });
}

window.addEventListener("popstate", () => {
  renderExam(examFromUrl());
});

const initialExam = examFromUrl();
const initialUrlValue = new URL(window.location.href).searchParams.get("exam");
if (initialUrlValue !== initialExam) {
  updateUrl(initialExam, "replace");
}
renderExam(initialExam);
