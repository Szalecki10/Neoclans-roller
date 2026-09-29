import { api, debounce, el, pct, showErrors, toast } from "/common.js";

const root = document.getElementById("admin");

let cfg = null; // edytowana konfiguracja
let savedJson = ""; // ostatnio zapisana wersja (do wykrywania zmian)
let savedAt = null;
let validation = { errors: [], warnings: [], preview: null, forJson: "" };
let versions = [];
let openGenes = new WeakSet();
const geneCards = new WeakMap(); // gen -> <details>
let maskInputs = []; // pola „maskuje geny” do odświeżenia po zmianie symbolu genu

let ui = {};

window.addEventListener("beforeunload", (e) => {
  if (cfg && isDirty()) {
    e.preventDefault();
    e.returnValue = "";
  }
});

init();

async function init() {
  try {
    const me = await api("/api/admin/me");
    if (me.admin) await loadEditor();
    else renderLogin();
  } catch (error) {
    showErrors(root, error);
  }
}

// ------------------------------------------------------------------ logowanie

function renderLogin() {
  cfg = null;
  const input = el("input", { type: "password", autocomplete: "current-password", required: true });
  const message = el("div");
  const form = el(
    "form",
    {
      onsubmit: async (e) => {
        e.preventDefault();
        try {
          await api("/api/admin/login", { method: "POST", body: { password: input.value } });
          await loadEditor();
        } catch (error) {
          showErrors(message, error);
          input.select();
        }
      },
    },
    el("label", { class: "field" }, el("span", {}, "Hasło admina"), input),
    el("button", { class: "primary", type: "submit" }, "Zaloguj"),
    message,
  );
  root.replaceChildren(el("div", { class: "panel login" }, el("h2", {}, "🔒 Logowanie"), form));
  input.focus();
}

async function logout() {
  if (isDirty() && !confirm("Masz niezapisane zmiany. Wylogować mimo to?")) return;
  await api("/api/admin/logout", { method: "POST" });
  renderLogin();
}

// ------------------------------------------------------------------ stan edytora

async function loadEditor() {
  const data = await api("/api/admin/config");
  savedAt = data.savedAt;
  setConfig(data.config, { saved: true });
  loadVersions();
}

function normalize(config) {
  config.tiers = Array.isArray(config.tiers) ? config.tiers : [];
  config.modes = Array.isArray(config.modes) ? config.modes : [];
  config.genes = Array.isArray(config.genes) ? config.genes : [];
  for (const mode of config.modes) mode.weights = mode.weights && typeof mode.weights === "object" ? mode.weights : {};
  for (const gene of config.genes) {
    gene.alleles = Array.isArray(gene.alleles) ? gene.alleles : [];
    gene.combos = Array.isArray(gene.combos) ? gene.combos : [];
    for (const combo of gene.combos) combo.alleles = Array.isArray(combo.alleles) ? combo.alleles : [];
    for (const item of [...gene.alleles, ...gene.combos]) item.masks = Array.isArray(item.masks) ? item.masks : [];
  }
  return config;
}

function setConfig(config, { saved = false, keepOpen = false } = {}) {
  const openIdx = keepOpen && cfg ? cfg.genes.flatMap((g, i) => (openGenes.has(g) ? [i] : [])) : [];
  cfg = normalize(structuredClone(config));
  if (saved) savedJson = JSON.stringify(cfg);
  openGenes = new WeakSet(openIdx.map((i) => cfg.genes[i]).filter(Boolean));
  renderEditor();
  changed();
}

function isDirty() {
  return JSON.stringify(cfg) !== savedJson;
}

const requestPreview = debounce(async () => {
  const sent = JSON.stringify(cfg);
  try {
    const res = await api("/api/admin/preview", { method: "POST", body: { config: cfg } });
    if (sent !== JSON.stringify(cfg)) return; // w międzyczasie coś zmieniono – przyjdzie nowszy podgląd
    validation = { ...res, forJson: sent };
  } catch (error) {
    if (error.status === 401) return renderLogin();
    validation = { errors: [error.message], warnings: [], preview: null, forJson: sent };
  }
  paintMessages();
  applyPreview();
}, 400);

function changed() {
  paintStatus();
  requestPreview();
}

function paintStatus() {
  if (!ui.status) return;
  const dirty = isDirty();
  ui.status.className = `status${dirty ? " dirty" : ""}`;
  ui.status.textContent = dirty ? "● Niezapisane zmiany" : `✔ Zapisano${savedAt ? ` · ${fmtDate(savedAt)}` : ""}`;
  ui.save.disabled = !dirty;
  ui.revert.disabled = !dirty;
}

function paintMessages() {
  const { errors, warnings } = validation;
  ui.messages.replaceChildren(
    el(
      "div",
      {},
      errors.length
        ? el("div", { class: "notice error" }, "Popraw przed zapisem:", el("ul", { class: "errors" }, errors.map((e) => el("li", {}, e))))
        : null,
      warnings.length ? el("div", { class: "notice" }, el("ul", { class: "warnings" }, warnings.map((w) => el("li", {}, w)))) : null,
    ),
  );
}

async function save() {
  ui.save.disabled = true;
  try {
    const res = await api("/api/admin/config", { method: "PUT", body: { config: cfg } });
    savedAt = new Date().toISOString();
    setConfig(res.config, { saved: true, keepOpen: true });
    toast("Zapisano ✔ – zmiany są już na stronie");
    loadVersions();
  } catch (error) {
    if (error.status === 401) return renderLogin();
    showErrors(ui.messages, error);
    ui.save.disabled = false;
  }
}

function revert() {
  if (!confirm("Odrzucić wszystkie niezapisane zmiany?")) return;
  setConfig(JSON.parse(savedJson), { keepOpen: true });
}

// ------------------------------------------------------------------ układ strony

function renderEditor() {
  maskInputs = [];
  ui = {
    status: el("span", { class: "status" }),
    save: el("button", { class: "primary", type: "button", onclick: save }, "💾 Zapisz"),
    revert: el("button", { type: "button", onclick: revert }, "Cofnij zmiany"),
    messages: el("div"),
    modes: el("div"),
    genes: el("div"),
    versions: el("div"),
  };
  const fileInput = el("input", {
    type: "file",
    accept: "application/json,.json",
    hidden: true,
    onchange: (e) => e.target.files[0] && importJson(e.target.files[0]),
  });
  root.replaceChildren(
    el(
      "div",
      { class: "toolbar" },
      ui.status,
      ui.revert,
      ui.save,
      el("button", { type: "button", onclick: logout }, "Wyloguj"),
    ),
    ui.messages,
    el(
      "section",
      { class: "admin-section" },
      el("h2", {}, "🎲 Tryby losowania i rzadkość"),
      el(
        "p",
        { class: "muted small" },
        "Każdy allel ma rzadkość. Szansa allelu w trybie = waga jego rzadkości w tym trybie × mnożnik allelu, przeliczona na % w obrębie genu. " +
          "Waga 0 = w tym trybie cechy tej rzadkości w ogóle nie wypadają. Kot dostaje dwa allele każdego genu losowane osobno " +
          "(kocur jeden przy genach sprzężonych z płcią), więc cecha recesywna wychodzi rzadziej niż sam allel – dokładne szanse widać w podglądzie każdego genu.",
      ),
      ui.modes,
    ),
    el(
      "section",
      { class: "admin-section" },
      el("h2", {}, "🧬 Geny"),
      el(
        "p",
        { class: "muted small" },
        "Kolejność alleli = dominacja: allel wyżej zasłania te niżej. Wyjątki (niepełna dominacja, kodominacja) dopisz w „Kombinacjach”. " +
          "„Kolejność w fenotypie” ustala porządek przy sortowaniu wg fenotypu i pierwszeństwo przy maskowaniu (mniejsza liczba = wcześniej). " +
          "Zmiany trafiają na stronę dopiero po kliknięciu „Zapisz”.",
      ),
      ui.genes,
      el("button", { type: "button", onclick: addGene }, "+ Dodaj gen"),
    ),
    el(
      "section",
      { class: "admin-section" },
      el("h2", {}, "🗂️ Kopia zapasowa i historia"),
      el(
        "p",
        { class: "muted small" },
        "Każdy zapis to nowa wersja (trzymamy 200 ostatnich). Starszą wersję można wczytać do edytora i zapisać ponownie. Tabelę można też pobrać jako plik JSON.",
      ),
      el(
        "div",
        { class: "row" },
        el("button", { type: "button", onclick: exportJson }, "⬇ Pobierz JSON"),
        el("button", { type: "button", onclick: () => fileInput.click() }, "⬆ Wczytaj JSON"),
        fileInput,
      ),
      ui.versions,
    ),
  );
  renderModes();
  renderGenes();
  renderVersions();
}

// ------------------------------------------------------------------ tryby i rzadkości

function uid(prefix) {
  return `${prefix}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
}

function renderModes() {
  ui.modes.replaceChildren(
    el(
      "div",
      { class: "table-wrap" },
      el(
        "table",
        { class: "matrix edit-table" },
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            el("th", {}, "Tryb ↓ / rzadkość →"),
            cfg.tiers.map((tier, i) =>
              el(
                "th",
                {},
                el("input", {
                  type: "text",
                  value: tier.name,
                  "aria-label": "Nazwa rzadkości",
                  oninput: (e) => {
                    tier.name = e.target.value;
                    refreshTierSelects();
                    changed();
                  },
                }),
                " ",
                el("button", { type: "button", class: "icon danger", title: "Usuń rzadkość", onclick: () => removeTier(i) }, "✕"),
              ),
            ),
            el("th"),
          ),
        ),
        el(
          "tbody",
          {},
          cfg.modes.map((mode, i) =>
            el(
              "tr",
              {},
              el("td", {}, textInput(mode, "name", { label: "Nazwa trybu" })),
              cfg.tiers.map((tier) => el("td", {}, numberInput(mode.weights, tier.id, { label: `Waga: ${tier.name}` }))),
              el("td", {}, el("button", { type: "button", class: "icon danger", title: "Usuń tryb", onclick: () => removeMode(i) }, "✕")),
            ),
          ),
        ),
      ),
    ),
    el(
      "div",
      { class: "row", style: "margin-top:8px" },
      el("button", { type: "button", onclick: addMode }, "+ tryb"),
      el("button", { type: "button", onclick: addTier }, "+ rzadkość"),
    ),
  );
}

function addTier() {
  const id = uid("t");
  cfg.tiers.push({ id, name: "Nowa rzadkość" });
  for (const mode of cfg.modes) mode.weights[id] = 0;
  renderModes();
  refreshTierSelects();
  changed();
}

function removeTier(index) {
  if (cfg.tiers.length === 1) return toast("Musi zostać przynajmniej jedna rzadkość.");
  const tier = cfg.tiers[index];
  const fallback = cfg.tiers[index === 0 ? 1 : 0];
  const used = cfg.genes.flatMap((g) => g.alleles).filter((a) => a.tier === tier.id);
  const note = used.length ? ` ${used.length} allel(e/i) dostanie rzadkość „${fallback.name}”.` : "";
  if (!confirm(`Usunąć rzadkość „${tier.name}”?${note}`)) return;
  cfg.tiers.splice(index, 1);
  for (const mode of cfg.modes) delete mode.weights[tier.id];
  for (const allele of used) allele.tier = fallback.id;
  renderModes();
  refreshTierSelects();
  changed();
}

function addMode() {
  const weights = Object.fromEntries(cfg.tiers.map((t, i) => [t.id, i === 0 ? 100 : 0]));
  cfg.modes.push({ id: uid("m"), name: "Nowy tryb", weights });
  renderModes();
  changed();
}

function removeMode(index) {
  if (cfg.modes.length === 1) return toast("Musi zostać przynajmniej jeden tryb.");
  if (!confirm(`Usunąć tryb „${cfg.modes[index].name}”?`)) return;
  cfg.modes.splice(index, 1);
  renderModes();
  changed();
}

// ------------------------------------------------------------------ pola formularza

function textInput(obj, key, { label, cls, placeholder, maxlength, onInput, onCommit } = {}) {
  let before = obj[key];
  return el("input", {
    type: "text",
    class: cls,
    placeholder,
    maxlength,
    "aria-label": label,
    value: obj[key] ?? "",
    onfocus: () => (before = obj[key]),
    oninput: (e) => {
      obj[key] = e.target.value;
      onInput?.();
      changed();
    },
    onchange: () => {
      if (before !== obj[key]) onCommit?.(before, obj[key]);
      before = obj[key];
    },
  });
}

function numberInput(obj, key, { label, min = 0 } = {}) {
  return el("input", {
    type: "number",
    step: "any",
    min,
    "aria-label": label,
    value: obj[key] ?? 0,
    oninput: (e) => {
      const raw = e.target.value.trim();
      obj[key] = raw === "" ? 0 : Number.isFinite(e.target.valueAsNumber) ? e.target.valueAsNumber : raw;
      changed();
    },
  });
}

function checkbox(obj, key, { label, onInput } = {}) {
  return el("input", {
    type: "checkbox",
    "aria-label": label,
    checked: obj[key],
    onchange: (e) => {
      obj[key] = e.target.checked;
      onInput?.();
      changed();
    },
  });
}

function masksInput(owner) {
  const input = el("input", {
    type: "text",
    placeholder: "np. B, A  albo  *",
    "aria-label": "Maskuje geny",
    value: owner.masks.join(", "),
    oninput: (e) => {
      owner.masks = e.target.value.split(/[\s,;]+/).filter(Boolean);
      changed();
    },
  });
  maskInputs.push({ input, owner });
  return input;
}

function field(label, input, hint) {
  return el("label", { class: "field" }, el("span", {}, label), input, hint ? el("small", { class: "muted" }, hint) : null);
}

function thead(columns) {
  return el(
    "thead",
    {},
    el(
      "tr",
      {},
      columns.filter((c) => c !== null).map((c) => (Array.isArray(c) ? el("th", { title: c[1] }, c[0], " ⓘ") : el("th", {}, c))),
    ),
  );
}

function tierSelect(allele) {
  const select = el("select", {
    "data-kind": "tier",
    "aria-label": "Rzadkość",
    onchange: (e) => {
      allele.tier = e.target.value;
      changed();
    },
  });
  select._owner = allele;
  fillTierSelect(select);
  return select;
}

function fillTierSelect(select) {
  const current = select._owner.tier;
  const known = cfg.tiers.some((t) => t.id === current);
  const options = cfg.tiers.map((t) => el("option", { value: t.id }, t.name || t.id));
  if (!known) options.unshift(el("option", { value: current }, "— wybierz —"));
  select.replaceChildren(...options);
  select.value = current;
}

function refreshTierSelects() {
  document.querySelectorAll('select[data-kind="tier"]').forEach(fillTierSelect);
}

function alleleSelect(gene, combo, index) {
  const select = el("select", {
    "data-kind": "allele",
    class: "mono",
    "aria-label": `Allel ${index + 1}`,
    onchange: (e) => {
      combo.alleles[index] = e.target.value;
      changed();
    },
  });
  Object.assign(select, { _gene: gene, _combo: combo, _index: index });
  fillAlleleSelect(select);
  return select;
}

function fillAlleleSelect(select) {
  const symbols = select._gene.alleles.map((a) => a.symbol);
  const current = select._combo.alleles[select._index] ?? "";
  const options = symbols.includes(current) ? symbols : [current, ...symbols];
  select.replaceChildren(...options.map((s) => el("option", { value: s }, s || "?")));
  select.value = current;
}

// ------------------------------------------------------------------ geny

function renderGenes() {
  ui.genes.replaceChildren(...cfg.genes.map(renderGeneCard));
  applyPreview();
}

function plural(n, one, few, many) {
  if (n === 1) return one;
  const d = n % 10;
  const t = n % 100;
  return d >= 2 && d <= 4 && (t < 12 || t > 14) ? few : many;
}

function renderGeneCard(gene) {
  const title = el("span", { style: "display:contents" });
  const updateTitle = () =>
    title.replaceChildren(
      el("span", { class: "sym" }, gene.symbol || "?"),
      el("span", {}, gene.name || el("i", { class: "muted" }, "bez nazwy")),
      el(
        "span",
        { class: "muted small" },
        `${gene.alleles.length} ${plural(gene.alleles.length, "allel", "allele", "alleli")}` +
          (gene.combos.length ? ` · ${gene.combos.length} komb.` : "") +
          (gene.sexLinked ? " · sprzężony z płcią" : ""),
      ),
    );
  updateTitle();

  const rerender = () => {
    const old = geneCards.get(gene);
    old?.replaceWith(renderGeneCard(gene));
    applyPreview();
  };

  const preview = el("div");
  const details = el(
    "details",
    {
      class: "gene",
      open: openGenes.has(gene),
      ontoggle: (e) => (e.target.open ? openGenes.add(gene) : openGenes.delete(gene)),
    },
    el("summary", {}, title),
    el(
      "div",
      { class: "gene-body" },
      el(
        "div",
        { class: "gene-fields" },
        field(
          "Symbol genu",
          textInput(gene, "symbol", {
            cls: "mono",
            maxlength: 12,
            onInput: updateTitle,
            onCommit: renameGeneRefs,
          }),
        ),
        field("Nazwa genu", textInput(gene, "name", { onInput: updateTitle })),
        field("Kolejność w fenotypie", numberInput(gene, "order", { min: null })),
        el(
          "label",
          { class: "check", title: "Gen na chromosomie X (jak rudy u kotów): kotka ma dwa allele, kocur jeden." },
          checkbox(gene, "sexLinked", { onInput: updateTitle }),
          "Sprzężony z płcią (kocur ma 1 allel)",
        ),
      ),
      allelesEditor(gene, rerender),
      combosEditor(gene, rerender),
      preview,
      el(
        "div",
        {},
        el("button", { type: "button", class: "danger", onclick: () => removeGene(gene) }, "Usuń gen"),
      ),
    ),
  );
  details._preview = preview;
  geneCards.set(gene, details);
  return details;
}

function allelesEditor(gene, rerender) {
  const move = (i, delta) => {
    const [item] = gene.alleles.splice(i, 1);
    gene.alleles.splice(i + delta, 0, item);
    rerender();
    changed();
  };
  const remove = (i) => {
    if (gene.alleles.length === 1) return toast("Gen musi mieć przynajmniej jeden allel.");
    const [removed] = gene.alleles.splice(i, 1);
    gene.combos = gene.combos.filter((c) => !c.alleles.includes(removed.symbol));
    rerender();
    changed();
  };
  return el(
    "div",
    {},
    el("h3", {}, "Allele ", el("span", { class: "muted small" }, "– wyżej = bardziej dominujący")),
    el(
      "div",
      { class: "table-wrap" },
      el(
        "table",
        { class: "edit-table" },
        thead([
          "Dominacja",
          "Symbol",
          "Nazwa / fenotyp",
          "Rzadkość",
          ["Mnożnik", "Dodatkowa waga w obrębie rzadkości: 1 = normalnie, 2 = dwa razy częściej, 0 = nigdy."],
          ["Ukryj w opisie", "Nie wypisuj tej cechy w opisie fenotypu (np. „bez srebra”)."],
          ["Maskuje geny", "Gdy ta cecha jest widoczna, zasłania podane geny (epistaza), np. biel dominująca: *. Symbole genów po przecinku, * = wszystkie."],
          "",
        ]),
        el(
          "tbody",
          {},
          gene.alleles.map((allele, i) =>
            el(
              "tr",
              {},
              el(
                "td",
                { class: "moves" },
                el("button", { type: "button", class: "icon", title: "Wyżej", disabled: i === 0, onclick: () => move(i, -1) }, "↑"),
                el(
                  "button",
                  { type: "button", class: "icon", title: "Niżej", disabled: i === gene.alleles.length - 1, onclick: () => move(i, 1) },
                  "↓",
                ),
                el("span", { class: "muted small" }, ` ${i + 1}.`),
              ),
              el(
                "td",
                {},
                textInput(allele, "symbol", {
                  label: "Symbol allelu",
                  cls: "sym-input",
                  maxlength: 12,
                  onCommit: (before, after) => renameAlleleRefs(gene, before, after),
                }),
              ),
              el("td", {}, textInput(allele, "name", { label: "Nazwa allelu", placeholder: "np. Czarny" })),
              el("td", {}, tierSelect(allele)),
              el("td", {}, numberInput(allele, "weight", { label: "Mnożnik" })),
              el("td", {}, checkbox(allele, "quiet", { label: "Ukryj w opisie" })),
              el("td", {}, masksInput(allele)),
              el("td", {}, el("button", { type: "button", class: "icon danger", title: "Usuń allel", onclick: () => remove(i) }, "✕")),
            ),
          ),
        ),
      ),
    ),
    el(
      "button",
      {
        type: "button",
        onclick: () => {
          gene.alleles.push(newAllele());
          rerender();
          changed();
        },
      },
      "+ allel",
    ),
  );
}

function combosEditor(gene, rerender) {
  const add = () => {
    const symbols = gene.alleles.map((a) => a.symbol);
    gene.combos.push({ alleles: [symbols[0] ?? "", symbols[1] ?? symbols[0] ?? ""], name: "", quiet: false, masks: [] });
    rerender();
    changed();
  };
  const remove = (i) => {
    gene.combos.splice(i, 1);
    rerender();
    changed();
  };
  return el(
    "div",
    {},
    el(
      "h3",
      {},
      "Kombinacje ",
      el("span", { class: "muted small" }, "– wyjątki od dominacji, np. S/s = trochę bieli, O/o = szylkret, cb/cs = mink"),
    ),
    gene.combos.length
      ? el(
          "div",
          { class: "table-wrap" },
          el(
            "table",
            { class: "edit-table" },
            thead(["Allel 1", "Allel 2", "Fenotyp", "Ukryj w opisie", "Maskuje geny", ""]),
            el(
              "tbody",
              {},
              gene.combos.map((combo, i) =>
                el(
                  "tr",
                  {},
                  el("td", {}, alleleSelect(gene, combo, 0)),
                  el("td", {}, alleleSelect(gene, combo, 1)),
                  el("td", {}, textInput(combo, "name", { label: "Fenotyp kombinacji", placeholder: "np. Szylkret" })),
                  el("td", {}, checkbox(combo, "quiet", { label: "Ukryj w opisie" })),
                  el("td", {}, masksInput(combo)),
                  el("td", {}, el("button", { type: "button", class: "icon danger", title: "Usuń", onclick: () => remove(i) }, "✕")),
                ),
              ),
            ),
          ),
        )
      : el("p", { class: "muted small", style: "margin:0 0 8px" }, "Brak – działa zwykła dominacja."),
    el("button", { type: "button", onclick: add }, "+ kombinacja"),
  );
}

function newAllele() {
  return { symbol: "", name: "", tier: cfg.tiers[0]?.id ?? "", weight: 1, quiet: false, masks: [] };
}

function addGene() {
  const order = Math.max(0, ...cfg.genes.map((g) => Number(g.order) || 0)) + 10;
  const gene = { symbol: "", name: "", order, sexLinked: false, alleles: [newAllele(), newAllele()], combos: [] };
  cfg.genes.push(gene);
  openGenes.add(gene);
  const card = renderGeneCard(gene);
  ui.genes.append(card);
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.querySelector(".gene-body input")?.focus({ preventScroll: true });
  changed();
}

function removeGene(gene) {
  if (!confirm(`Usunąć gen ${gene.symbol || "(bez symbolu)"} razem z allelami?`)) return;
  cfg.genes.splice(cfg.genes.indexOf(gene), 1);
  geneCards.get(gene)?.remove();
  if (gene.symbol) {
    for (const g of cfg.genes) for (const item of [...g.alleles, ...g.combos]) item.masks = item.masks.filter((m) => m !== gene.symbol);
    repaintMaskInputs();
  }
  changed();
}

function renameGeneRefs(before, after) {
  if (!before || !after) return;
  for (const g of cfg.genes) {
    for (const item of [...g.alleles, ...g.combos]) item.masks = item.masks.map((m) => (m === before ? after : m));
  }
  repaintMaskInputs();
  changed();
}

function repaintMaskInputs() {
  maskInputs = maskInputs.filter(({ input }) => input.isConnected);
  for (const { input, owner } of maskInputs) {
    if (document.activeElement !== input) input.value = owner.masks.join(", ");
  }
}

function renameAlleleRefs(gene, before, after) {
  if (before && after) {
    for (const combo of gene.combos) combo.alleles = combo.alleles.map((a) => (a === before ? after : a));
  }
  geneCards.get(gene)?.querySelectorAll('select[data-kind="allele"]').forEach(fillAlleleSelect);
  changed();
}

// ------------------------------------------------------------------ podgląd szans

function modeName(id) {
  return cfg.modes.find((m) => m.id === id)?.name || id;
}

function distList(items, mono = false) {
  return el(
    "div",
    { class: "dist" },
    items.map(([label, p]) =>
      el("span", { class: p === 0 ? "muted" : "" }, mono ? el("code", {}, label) : label, " ", el("b", {}, pct(p))),
    ),
  );
}

function applyPreview() {
  const current = validation.forJson === JSON.stringify(cfg) ? validation : null;
  cfg.genes.forEach((gene, i) => {
    const box = geneCards.get(gene)?._preview;
    if (!box) return;
    const heading = el(
      "h3",
      {},
      "Szanse w losowaniu z tabeli ",
      el("span", { class: "muted small" }, "– dla tego genu, bez maskowania przez inne geny"),
    );
    const data = current?.preview?.[i];
    if (!data) {
      const text = current?.errors.length ? "Popraw błędy (u góry strony), żeby zobaczyć szanse." : "Liczę…";
      box.replaceChildren(heading, el("p", { class: "muted small", style: "margin:0" }, text));
      return;
    }
    box.replaceChildren(
      heading,
      el(
        "div",
        { class: "table-wrap" },
        el(
          "table",
          { class: "preview-table" },
          thead(["Tryb", "Allele", gene.sexLinked ? "Fenotyp kotki" : "Fenotyp", gene.sexLinked ? "Fenotyp kocura" : null]),
          el(
            "tbody",
            {},
            data.modes.map((m) =>
              el(
                "tr",
                {},
                el("td", {}, modeName(m.mode)),
                el("td", {}, distList(m.alleles.map((a) => [a.symbol, a.p]), true)),
                el("td", {}, distList(m.phenotypes.map((p) => [p.phenotype, p.p]))),
                gene.sexLinked ? el("td", {}, distList(m.phenotypesMale.map((p) => [p.phenotype, p.p]))) : null,
              ),
            ),
          ),
        ),
      ),
    );
  });
}

// ------------------------------------------------------------------ kopie i historia

function fmtDate(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" });
}

async function loadVersions() {
  try {
    ({ versions } = await api("/api/admin/versions"));
    renderVersions();
  } catch {
    /* historia nie jest krytyczna */
  }
}

function renderVersions() {
  if (!ui.versions) return;
  ui.versions.replaceChildren(
    versions.length
      ? el(
          "ul",
          { class: "versions" },
          versions.map((v, i) =>
            el(
              "li",
              {},
              el("code", {}, `#${v.id}`),
              el("span", {}, fmtDate(v.createdAt)),
              el("span", { class: "muted" }, v.note),
              i === 0
                ? el("span", { class: "tag" }, "aktualna")
                : el("button", { type: "button", class: "icon", onclick: () => loadVersion(v.id) }, "wczytaj do edytora"),
            ),
          ),
        )
      : el("p", { class: "muted small" }, "Brak historii."),
  );
}

async function loadVersion(id) {
  if (isDirty() && !confirm("Masz niezapisane zmiany. Wczytać mimo to?")) return;
  try {
    const version = await api(`/api/admin/versions/${id}`);
    setConfig(version.data);
    toast(`Wczytano wersję #${id} – kliknij „Zapisz”, żeby ją przywrócić`);
  } catch (error) {
    showErrors(ui.messages, error);
  }
}

function exportJson() {
  const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" });
  const link = el("a", { href: URL.createObjectURL(blob), download: `neoclans-geny-${new Date().toISOString().slice(0, 10)}.json` });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function importJson(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result);
      if (!data || !Array.isArray(data.genes)) throw new Error("To nie wygląda na plik z tabelą genów.");
      if (isDirty() && !confirm("Masz niezapisane zmiany. Zastąpić je plikiem?")) return;
      setConfig(data);
      toast("Wczytano plik – sprawdź i kliknij „Zapisz”");
    } catch (error) {
      toast(error.message);
    }
  };
  reader.readAsText(file);
}
