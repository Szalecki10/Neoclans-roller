import {
  api,
  catCard,
  debounce,
  el,
  genotypeString,
  getSortMode,
  pct,
  phenotypeString,
  setSortMode,
  SEX_LABEL,
  showErrors,
  sortGenes,
  toast,
} from "/common.js";

const $ = (sel) => document.querySelector(sel);

const state = {
  config: null, // publiczna tabela genów (bez szans)
  mode: null,
  rolled: [],
  parentText: { mother: "", father: "" },
  breed: null,
};

const ROLES = {
  mother: { sex: "F", title: "Matka ♀" },
  father: { sex: "M", title: "Ojciec ♂" },
};

const store = {
  get(key) {
    try {
      return JSON.parse(localStorage.getItem(key));
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* brak dostępu do localStorage – trudno */
    }
  },
};

init();

async function init() {
  setupTabs();
  setupSort();
  const wakeTimer = setTimeout(() => ($("#wake").hidden = false), 2500);
  try {
    state.config = await api("/api/config");
  } catch (error) {
    $("#fatal").textContent = `Nie udało się połączyć z serwerem (${error.message}). Odśwież stronę za chwilę.`;
    $("#fatal").hidden = false;
    return;
  } finally {
    clearTimeout(wakeTimer);
    $("#wake").hidden = true;
  }
  setupRoll();
  setupBreed();
}

// ------------------------------------------------------------------ zakładki i sortowanie

function setupTabs() {
  const show = (tab) => {
    for (const btn of document.querySelectorAll("[data-tab]")) {
      const active = btn.dataset.tab === tab;
      btn.setAttribute("aria-selected", String(active));
      $(`#tab-${btn.dataset.tab}`).hidden = !active;
    }
  };
  for (const btn of document.querySelectorAll("[data-tab]")) {
    btn.addEventListener("click", () => {
      show(btn.dataset.tab);
      history.replaceState(null, "", btn.dataset.tab === "breed" ? "#krzyzowka" : "#losowanie");
    });
  }
  show(location.hash === "#krzyzowka" ? "breed" : "roll");
  window.showTab = show;
}

function setupSort() {
  const buttons = document.querySelectorAll("[data-sort]");
  const paint = () => buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sort === getSortMode())));
  buttons.forEach((b) =>
    b.addEventListener("click", () => {
      setSortMode(b.dataset.sort);
      paint();
      if (!state.config) return;
      renderRolled();
      renderParent("mother");
      renderParent("father");
      renderBreed();
    }),
  );
  paint();
}

// ------------------------------------------------------------------ losowanie z tabeli

function setupRoll() {
  const modes = state.config.modes;
  const saved = store.get("neoclans.mode");
  state.mode = modes.some((m) => m.id === saved) ? saved : modes[0]?.id;
  const seg = $("#mode-seg");
  const paint = () => seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode)));
  seg.replaceChildren(
    ...modes.map((m) =>
      el(
        "button",
        {
          type: "button",
          "data-mode": m.id,
          onclick: () => {
            state.mode = m.id;
            store.set("neoclans.mode", m.id);
            paint();
          },
        },
        m.name,
      ),
    ),
  );
  paint();
  $("#mode-hint").textContent =
    "Tryb zmienia szanse na rzadsze cechy – w najniższym trybie rzadkie cechy w ogóle nie wypadają. Każdy allel losowany jest osobno, więc kot może nosić ukrytą cechę recesywną.";
  $("#roll-btn").addEventListener("click", doRoll);
}

async function doRoll() {
  const btn = $("#roll-btn");
  btn.disabled = true;
  $("#roll-error").replaceChildren();
  try {
    const { cats } = await api("/api/roll", {
      method: "POST",
      body: { mode: state.mode, sex: $("#roll-sex").value || null, count: Number($("#roll-count").value) || 1 },
    });
    state.rolled = cats;
    renderRolled();
  } catch (error) {
    showErrors($("#roll-error"), error);
  } finally {
    btn.disabled = false;
  }
}

function renderRolled() {
  const many = state.rolled.length > 1;
  $("#roll-results").replaceChildren(
    ...state.rolled.map((cat, i) =>
      catCard(cat, {
        title: `${SEX_LABEL[cat.sex]}${many ? ` · #${i + 1}` : ""}`,
        actions: [useAsParentButton(cat)],
      }),
    ),
  );
}

function useAsParentButton(cat) {
  return el(
    "button",
    { type: "button", onclick: () => useAsParent(cat) },
    cat.sex === "F" ? "→ użyj jako matkę" : "→ użyj jako ojca",
  );
}

function useAsParent(cat) {
  const role = cat.sex === "F" ? "mother" : "father";
  state.parentText[role] = genotypeString(sortGenes(cat.genes));
  saveParents();
  renderParent(role);
  window.showTab("breed");
  history.replaceState(null, "", "#krzyzowka");
  toast(role === "mother" ? "Ustawiono jako matkę 🐱" : "Ustawiono jako ojca 🐱");
}

// ------------------------------------------------------------------ krzyżówka

function setupBreed() {
  const saved = store.get("neoclans.parentText") || {};
  for (const role of Object.keys(ROLES)) {
    state.parentText[role] = typeof saved[role] === "string" ? saved[role] : "";
    renderParent(role);
  }
  $("#breed-btn").addEventListener("click", doBreed);
}

function saveParents() {
  store.set("neoclans.parentText", state.parentText);
}

// Przykład w polu: najbardziej dominujący allel każdego genu, np. „WW BB OO…” / „OY” u kocura.
function exampleGenotype(sex) {
  return sortGenes(state.config.genes)
    .map((gene) => {
      const top = gene.alleles[0].symbol;
      const parts = gene.sexLinked && sex === "M" ? [top, "Y"] : [top, top];
      return parts.every((p) => p.length === 1) ? parts.join("") : parts.join("/");
    })
    .join(" ");
}

function renderParent(role) {
  if (!state.config) return;
  const { sex, title } = ROLES[role];
  const status = el("div", { class: "parent-summary" });

  const check = debounce(async () => {
    const text = state.parentText[role].trim();
    if (!text) {
      status.replaceChildren(el("span", { class: "muted small" }, "Wpisz genotyp albo wylosuj."));
      return;
    }
    try {
      const res = await api("/api/parse", { method: "POST", body: { text, sex } });
      if (text !== state.parentText[role].trim()) return; // w międzyczasie wpisano coś nowego
      if (res.cat) {
        status.replaceChildren(
          el("div", { class: "line" }, el("span", { class: "label" }, "Fenotyp"), el("span", {}, phenotypeString(sortGenes(res.cat.genes))), el("span")),
        );
        return;
      }
      const notes = [...res.errors];
      if (res.missing.length) notes.push(`Brakuje genów: ${res.missing.join(", ")}.`);
      status.replaceChildren(el("ul", { class: "errors" }, notes.map((n) => el("li", {}, n))));
    } catch (error) {
      showErrors(status, error);
    }
  }, 300);

  const input = el("input", {
    type: "text",
    class: "genotype-input",
    placeholder: `np. ${exampleGenotype(sex)}`,
    "aria-label": `${title}: genotyp`,
    autocomplete: "off",
    spellcheck: "false",
    value: state.parentText[role],
    oninput: (e) => {
      state.parentText[role] = e.target.value;
      saveParents();
      check();
    },
  });

  const setText = (text) => {
    state.parentText[role] = text;
    input.value = text;
    saveParents();
    check();
  };

  const modeSelect = el(
    "select",
    { "aria-label": "Tryb losowania rodzica", value: state.mode },
    state.config.modes.map((m) => el("option", { value: m.id }, m.name)),
  );

  const rollParent = async () => {
    try {
      const { cats } = await api("/api/roll", { method: "POST", body: { mode: modeSelect.value, sex, count: 1 } });
      setText(genotypeString(sortGenes(cats[0].genes)));
    } catch (error) {
      showErrors(status, error);
    }
  };

  $(`#parent-${role}`).replaceChildren(
    el("h2", { class: `sex-${sex}` }, title),
    el("div", { class: "row" }, input),
    el(
      "div",
      { class: "row" },
      el("span", { class: "muted small" }, "albo"),
      modeSelect,
      el("button", { type: "button", onclick: rollParent }, "🎲 losuj"),
      el("button", { type: "button", class: "link", onclick: () => setText("") }, "wyczyść"),
    ),
    status,
  );
  check();
}

async function doBreed() {
  const btn = $("#breed-btn");
  btn.disabled = true;
  $("#breed-error").replaceChildren();
  try {
    state.breed = await api("/api/breed", {
      method: "POST",
      body: { mother: state.parentText.mother, father: state.parentText.father, count: Number($("#litter").value) || 1 },
    });
    renderBreed();
    $("#breed-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showErrors($("#breed-error"), error);
  } finally {
    btn.disabled = false;
  }
}

function renderBreed() {
  const res = state.breed;
  if (!res) return;
  const parents = `${genotypeString(sortGenes(res.mother.genes))}  ×  ${genotypeString(sortGenes(res.father.genes))}`;
  $("#breed-results").replaceChildren(
    el(
      "div",
      { class: "section-title" },
      el("h2", {}, res.kittens.length > 1 ? "Wylosowane kocięta" : "Wylosowane kocię"),
      el("p", { class: "muted small" }, el("code", {}, parents)),
    ),
    el(
      "div",
      { class: "cards" },
      res.kittens.map((kitten, i) =>
        catCard(kitten, {
          title: `${res.kittens.length > 1 ? `${i + 1}. ` : ""}${SEX_LABEL[kitten.sex]}`,
          extra: `szansa na taki genotyp (u ${kitten.sex === "F" ? "kotki" : "kocura"}): ${pct(kitten.probability)}`,
          actions: [useAsParentButton(kitten)],
        }),
      ),
    ),
  );
}
