// Wspólne pomocniki dla strony głównej i panelu admina.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  let value;
  for (const [key, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (key === "class") node.className = v;
    else if (key === "value") value = v;
    else if (key === "checked") node.checked = Boolean(v);
    else if (key.startsWith("on") && typeof v === "function") node.addEventListener(key.slice(2), v);
    else if (v === true) node.setAttribute(key, "");
    else node.setAttribute(key, v);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  if (value !== undefined) node.value = value; // po opcjach, żeby <select> trafił w wartość
  return node;
}

export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* odpowiedź bez JSON-a */
  }
  if (!res.ok) {
    const error = new Error(data?.error || `Błąd serwera (${res.status})`);
    error.status = res.status;
    error.details = data?.errors || [];
    throw error;
  }
  return data;
}

export function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function pct(p) {
  const v = p * 100;
  if (v === 0) return "0%";
  if (v < 0.001) return "<0,001%";
  const text = v >= 1 ? String(+v.toFixed(1)) : String(+v.toPrecision(2));
  return `${text.replace(".", ",")}%`;
}

let toastTimer;
export function toast(message) {
  let node = document.querySelector(".toast");
  if (!node) {
    node = el("div", { class: "toast", role: "status" });
    document.body.append(node);
  }
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), 2200);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Skopiowano 📋");
  } catch {
    window.prompt("Skopiuj ręcznie:", text);
  }
}

export function showErrors(container, error) {
  container.replaceChildren(
    el(
      "div",
      { class: "notice error" },
      error.message,
      error.details?.length ? el("ul", { class: "errors" }, error.details.map((d) => el("li", {}, d))) : null,
    ),
  );
}

// ------------------------------------------------------------------ sortowanie genów

const SORT_KEY = "neoclans.sort";

export function getSortMode() {
  try {
    return localStorage.getItem(SORT_KEY) === "phenotype" ? "phenotype" : "genotype";
  } catch {
    return "genotype";
  }
}

export function setSortMode(mode) {
  try {
    localStorage.setItem(SORT_KEY, mode);
  } catch {
    /* tryb prywatny itp. */
  }
}

const bySymbol = (a, b) =>
  a.symbol.localeCompare(b.symbol, "pl", { sensitivity: "base" }) || (a.symbol < b.symbol ? -1 : a.symbol > b.symbol ? 1 : 0);

// Genotyp: alfabetycznie po symbolu genu. Fenotyp: kolejność opisu ustalona przez admina
// (domyślnie jak w kodach EMS: kolor → srebro → biel → wzór → pointy → sierść).
export function sortGenes(items, mode = getSortMode()) {
  const copy = [...items];
  if (mode === "phenotype") copy.sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || bySymbol(a, b));
  else copy.sort(bySymbol);
  return copy;
}

// ------------------------------------------------------------------ karta kota

export const SEX_LABEL = { F: "Kotka ♀", M: "Kocur ♂" };

export function genotypeString(rows) {
  return rows.map((r) => r.text).join(" ");
}

export function phenotypeString(rows) {
  const visible = rows.filter((r) => !r.maskedBy.length && !r.quiet && r.phenotype).map((r) => r.phenotype);
  return visible.join(", ") || "—";
}

export function catCard(cat, { title, extra, actions = [] } = {}) {
  const rows = sortGenes(cat.genes);
  const genotype = genotypeString(rows);
  const phenotype = phenotypeString(rows);
  return el(
    "article",
    { class: "cat" },
    el(
      "div",
      { class: "cat-head" },
      el("h3", { class: `sex-${cat.sex}` }, title || SEX_LABEL[cat.sex]),
      extra ? el("span", { class: "muted small" }, extra) : null,
    ),
    el(
      "div",
      { class: "line" },
      el("span", { class: "label" }, "Genotyp"),
      el("code", {}, genotype),
      el("button", { class: "copy", type: "button", onclick: () => copyText(genotype) }, "kopiuj"),
    ),
    el(
      "div",
      { class: "line" },
      el("span", { class: "label" }, "Fenotyp"),
      el("span", {}, phenotype),
      el("button", { class: "copy", type: "button", onclick: () => copyText(phenotype) }, "kopiuj"),
    ),
    actions.length ? el("div", { class: "actions" }, actions) : null,
  );
}
