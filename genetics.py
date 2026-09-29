"""
Logika genetyki kotów: losowanie z tabeli, krzyżówki, fenotypy.

Same czyste funkcje bez I/O, więc łatwo je testować (tests/test_genetics.py).
Model danych jest opisany w README.md, w sekcji „Model danych”.
"""
from __future__ import annotations

import random
import re

FEMALE = "F"
MALE = "M"
Y_MARK = "Y"  # chromosom Y w zapisie genów sprzężonych z płcią, np. „OY”

_system_rng = random.SystemRandom()
_SYMBOL_RE = re.compile(r"^[^\s/,;|]{1,12}$")
_ID_RE = re.compile(r"^[\w-]{1,40}$")
_RESERVED_SEX_LINKED = {Y_MARK, "-"}


# --------------------------------------------------------------------------- pomocnicze

def _rank(gene):
    return {a["symbol"]: i for i, a in enumerate(gene["alleles"])}


def sort_alleles(gene, alleles):
    """Kanoniczna kolejność: najpierw allel dominujący (np. „Cc”, nie „cC”)."""
    rank = _rank(gene)
    return sorted(alleles, key=lambda s: rank[s])


def format_genotype(gene, alleles):
    """„Cc”, „CC”, „cb/cs” (gdy któryś symbol ma kilka znaków), „OY” dla kocura."""
    parts = list(sort_alleles(gene, alleles))
    if gene.get("sexLinked") and len(parts) == 1:
        parts.append(Y_MARK)
    if all(len(p) == 1 for p in parts):
        return "".join(parts)
    return "/".join(parts)


def phenotype_sort_key(gene):
    return (gene.get("order", 0), gene["symbol"].lower(), gene["symbol"])


def _mode(config, mode_id):
    for mode in config["modes"]:
        if mode["id"] == mode_id:
            return mode
    raise ValueError(f"Nieznany tryb losowania: {mode_id}")


# --------------------------------------------------------------------------- losowanie z tabeli

def allele_probabilities(config, gene, mode_id):
    """Szansa na każdy allel genu w danym trybie.

    waga allelu = waga jego rzadkości w trybie × mnożnik allelu,
    potem normalizacja do 100% w obrębie genu. Jeśli w tym trybie żaden allel
    nie ma szansy, losujemy po równo (panel admina ostrzega o takiej sytuacji).
    """
    tier_weights = _mode(config, mode_id)["weights"]
    raw = [tier_weights.get(a["tier"], 0) * a.get("weight", 1) for a in gene["alleles"]]
    total = sum(raw)
    if total <= 0:
        raw, total = [1] * len(raw), len(raw)
    return {a["symbol"]: w / total for a, w in zip(gene["alleles"], raw)}


def roll_cat(config, mode_id, sex=None, rng=_system_rng):
    """Losowy kot z tabeli: każdy allel losowany niezależnie wg szans trybu."""
    if sex not in (FEMALE, MALE):
        sex = rng.choice((FEMALE, MALE))
    genotype = {}
    for gene in config["genes"]:
        probs = allele_probabilities(config, gene, mode_id)
        copies = 1 if gene.get("sexLinked") and sex == MALE else 2
        picked = rng.choices(list(probs), weights=list(probs.values()), k=copies)
        genotype[gene["symbol"]] = sort_alleles(gene, picked)
    return {"sex": sex, "genotype": genotype}


# --------------------------------------------------------------------------- fenotyp

def _find_combo(gene, alleles):
    if len(alleles) != 2:
        return None
    key = sorted(alleles)
    for combo in gene.get("combos", []):
        if sorted(combo["alleles"]) == key:
            return combo
    return None


def gene_outcome(gene, alleles):
    """Co widać (fenotyp) przy danej parze alleli jednego genu.

    Najpierw sprawdzamy kombinacje zdefiniowane przez admina (niepełna dominacja,
    kodominacja, np. O/o = szylkret). W pozostałych przypadkach wygrywa allel
    wyżej na liście (lista alleli = kolejność dominacji), a reszta jest „noszona”.
    """
    alleles = sort_alleles(gene, alleles)
    by_symbol = {a["symbol"]: a for a in gene["alleles"]}
    if len(alleles) == 1:
        zygosity = "hemizygous"
    elif alleles[0] == alleles[1]:
        zygosity = "homozygous"
    else:
        zygosity = "heterozygous"

    combo = _find_combo(gene, alleles)
    if combo:
        return {
            "phenotype": combo["name"],
            "quiet": combo.get("quiet", False),
            "masks": combo.get("masks", []),
            "zygosity": zygosity,
            "relation": "combo",
            "dominant": None,
            "carriers": [],
        }

    top = by_symbol[alleles[0]]
    carriers = [
        {"symbol": s, "name": by_symbol[s]["name"]}
        for s in dict.fromkeys(alleles[1:])
        if s != top["symbol"]
    ]
    return {
        "phenotype": top["name"],
        "quiet": top.get("quiet", False),
        "masks": top.get("masks", []),
        "zygosity": zygosity,
        "relation": "dominance" if carriers else "same",
        "dominant": top["symbol"],
        "carriers": carriers,
    }


def describe(config, cat):
    """Pełny opis kota: dla każdego genu genotyp, fenotyp, nosicielstwo, maskowanie.

    Maskowanie (epistaza): geny wcześniej w kolejności fenotypu mają pierwszeństwo,
    a gen, który sam jest zamaskowany, nikogo już nie maskuje. Dzięki temu np. biel
    dominująca zasłania wszystko, a rudy zasłania agouti, więc pręgi są widoczne.
    """
    symbols = [g["symbol"] for g in config["genes"]]
    rows = {}
    masked_by = {}
    for gene in sorted(config["genes"], key=phenotype_sort_key):
        sym = gene["symbol"]
        alleles = sort_alleles(gene, cat["genotype"][sym])
        outcome = gene_outcome(gene, alleles)
        masks = outcome.pop("masks")
        rows[sym] = {
            "symbol": sym,
            "gene": gene["name"],
            "order": gene.get("order", 0),
            "sexLinked": bool(gene.get("sexLinked")),
            "alleles": alleles,
            "text": format_genotype(gene, alleles),
            **outcome,
        }
        if sym in masked_by:
            continue
        for target in (symbols if "*" in masks else masks):
            if target != sym:
                masked_by.setdefault(target, []).append(sym)
    for sym, row in rows.items():
        row["maskedBy"] = masked_by.get(sym, [])
    return {"sex": cat["sex"], "genes": [rows[s] for s in symbols]}


# --------------------------------------------------------------------------- krzyżówki

def roll_kitten(config, mother, father, sex=None, rng=_system_rng):
    """Jedno losowe kocię z pary + szansa na dokładnie taki genotyp (przy tej płci).

    Każdy rodzic przekazuje jeden losowy allel. Przy genach sprzężonych z płcią
    córka dostaje allel matki + jedyny allel ojca, a syn tylko allel matki.
    """
    if sex not in (FEMALE, MALE):
        sex = rng.choice((FEMALE, MALE))
    genotype = {}
    probability = 1.0
    for gene in config["genes"]:
        sym = gene["symbol"]
        m, f = mother[sym], father[sym]
        if gene.get("sexLinked"):
            options = [[x] if sex == MALE else [x, f[0]] for x in m]
        else:
            options = [[x, y] for x in m for y in f]
        alleles = sort_alleles(gene, rng.choice(options))
        probability *= sum(1 for o in options if sorted(o) == sorted(alleles)) / len(options)
        genotype[sym] = alleles
    return {"sex": sex, "genotype": genotype, "probability": probability}


# --------------------------------------------------------------------------- wklejanie genotypu

def parse_genotype(config, text, sex):
    """Zamienia tekst typu „Aa Bbl cb/cs OY” na genotyp. Nierozpoznane kawałki trafiają do errors."""
    tokens = [t for t in re.split(r"[\s,;|]+", text or "") if t]
    genotype, errors = {}, []
    for token in tokens:
        matches = _match_token(config, token, sex)
        if not matches:
            errors.append(_sex_hint(config, token, sex) or f"Nie rozpoznano „{token}”.")
        elif len(matches) > 1:
            genes = ", ".join(sorted({sym for sym, _ in matches}))
            errors.append(f"„{token}” da się odczytać na kilka sposobów ({genes}) – spróbuj zapisu z ukośnikiem, np. a/b.")
        else:
            sym, alleles = matches[0]
            if sym in genotype:
                errors.append(f"Gen {sym} podano więcej niż raz („{token}”).")
            genotype[sym] = alleles
    missing = [g["symbol"] for g in config["genes"] if g["symbol"] not in genotype]
    return {"genotype": genotype, "errors": errors, "missing": missing}


def _sex_hint(config, token, sex):
    """Podpowiedź, gdy ktoś wpisał gen sprzężony z płcią jak dla drugiej płci (np. kocur „OO”)."""
    other = FEMALE if sex == MALE else MALE
    genes = {g["symbol"]: g for g in config["genes"]}
    for sym, alleles in _match_token(config, token, other):
        gene = genes[sym]
        if not gene.get("sexLinked"):
            continue
        if sex == MALE:
            example = format_genotype(gene, alleles[:1])
            return f"„{token}”: kocur ma tylko jeden allel genu {sym} – zapisz np. „{example}”."
        example = format_genotype(gene, alleles * 2)
        return f"„{token}”: kotka ma dwa allele genu {sym} – zapisz np. „{example}”."
    return None


def _match_token(config, token, sex):
    if "/" in token:
        splits = [token.split("/")]
    else:
        splits = [[token]] + [[token[:i], token[i:]] for i in range(1, len(token))]
    found = []
    for gene in config["genes"]:
        valid = {a["symbol"] for a in gene["alleles"]}
        hemizygous = gene.get("sexLinked") and sex == MALE
        hits = set()
        for parts in splits:
            if hemizygous:
                if len(parts) == 1 and parts[0] in valid:
                    hits.add((parts[0],))
                elif len(parts) == 2 and parts[0] in valid and parts[1] in _RESERVED_SEX_LINKED:
                    hits.add((parts[0],))
            elif len(parts) == 2 and all(p in valid for p in parts):
                hits.add(tuple(sort_alleles(gene, parts)))
        found.extend((gene["symbol"], list(h)) for h in hits)
    return found


# --------------------------------------------------------------------------- podgląd dla admina

def preview(config):
    """Szanse w losowaniu z tabeli (per tryb): allele i fenotypy. Bez maskowania przez inne geny."""
    out = []
    for gene in config["genes"]:
        modes = []
        for mode in config["modes"]:
            probs = allele_probabilities(config, gene, mode["id"])
            entry = {
                "mode": mode["id"],
                "alleles": [{"symbol": s, "p": p} for s, p in probs.items()],
                "phenotypes": _phenotypes_from_probs(gene, probs, 2),
            }
            if gene.get("sexLinked"):
                entry["phenotypesMale"] = _phenotypes_from_probs(gene, probs, 1)
            modes.append(entry)
        out.append({"symbol": gene["symbol"], "modes": modes})
    return out


def _phenotypes_from_probs(gene, probs, copies):
    symbols = list(probs)
    if copies == 1:
        pairs = [((s,), probs[s]) for s in symbols]
    else:
        pairs = [
            ((a, b), probs[a] * probs[b] * (1 if a == b else 2))
            for i, a in enumerate(symbols)
            for b in symbols[i:]
        ]
    phenotypes = {}
    for alleles, p in pairs:
        if p > 0:
            name = gene_outcome(gene, list(alleles))["phenotype"] or "—"
            phenotypes[name] = phenotypes.get(name, 0) + p
    return [{"phenotype": k, "p": v} for k, v in sorted(phenotypes.items(), key=lambda kv: -kv[1])]


def public_config(config):
    """To, co widzą zwykli użytkownicy: bez wag, rzadkości, kombinacji i maskowania."""
    return {
        "modes": [{"id": m["id"], "name": m["name"]} for m in config["modes"]],
        "genes": [
            {
                "symbol": g["symbol"],
                "name": g["name"],
                "order": g.get("order", 0),
                "sexLinked": bool(g.get("sexLinked")),
                "alleles": [{"symbol": a["symbol"], "name": a["name"]} for a in g["alleles"]],
            }
            for g in config["genes"]
        ],
    }


# --------------------------------------------------------------------------- walidacja danych od admina

def _as_list(value):
    return value if isinstance(value, list) else []


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _text(value, limit=120):
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            n = float(value.strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return int(n) if n.is_integer() else n


def _clean_masks(value, own, gene_symbols, label, errors):
    if isinstance(value, str):
        items = re.split(r"[\s,;]+", value)
    else:
        items = _as_list(value)
    masks = []
    for item in items:
        s = _text(item, 12)
        if not s or s == own or s in masks:
            continue
        if s != "*" and s not in gene_symbols:
            errors.append(f"{label}: maskuje nieistniejący gen „{s}”.")
            continue
        masks.append(s)
    return masks


def clean_config(raw):
    """Sprawdza i porządkuje konfigurację z panelu admina.

    Zwraca (config, errors, warnings). Geny wracają w tej samej kolejności co na
    wejściu (1:1), żeby panel mógł dopasować podgląd do kart genów.
    """
    errors, warnings = [], []
    if not isinstance(raw, dict):
        return None, ["Konfiguracja musi być obiektem JSON."], []

    tiers, tier_ids = [], set()
    for i, t in enumerate(_as_list(raw.get("tiers")), 1):
        t = _as_dict(t)
        tid, name = _text(t.get("id"), 40), _text(t.get("name"), 40)
        if not _ID_RE.match(tid):
            errors.append(f"Rzadkość nr {i}: nieprawidłowy identyfikator.")
            continue
        if tid in tier_ids:
            errors.append(f"Rzadkość „{name or tid}” występuje dwa razy.")
            continue
        tier_ids.add(tid)
        tiers.append({"id": tid, "name": name or tid})
    if not tiers:
        errors.append("Musi istnieć przynajmniej jeden poziom rzadkości.")

    modes, mode_ids = [], set()
    for i, m in enumerate(_as_list(raw.get("modes")), 1):
        m = _as_dict(m)
        mid, name = _text(m.get("id"), 40), _text(m.get("name"), 40)
        label = f"Tryb „{name or i}”"
        if not _ID_RE.match(mid):
            errors.append(f"{label}: nieprawidłowy identyfikator.")
            continue
        if mid in mode_ids:
            errors.append(f"{label}: występuje dwa razy.")
            continue
        mode_ids.add(mid)
        raw_weights = _as_dict(m.get("weights"))
        weights = {}
        for t in tiers:
            w = _number(raw_weights.get(t["id"], 0))
            if w is None or w < 0:
                errors.append(f"{label}: waga dla „{t['name']}” musi być liczbą ≥ 0.")
                w = 0
            weights[t["id"]] = w
        if tiers and sum(weights.values()) <= 0:
            errors.append(f"{label}: wszystkie wagi są zerowe – nic by nie wypadło.")
        modes.append({"id": mid, "name": name or mid, "weights": weights})
    if not modes:
        errors.append("Musi istnieć przynajmniej jeden tryb losowania.")

    raw_genes = [_as_dict(g) for g in _as_list(raw.get("genes"))]
    gene_symbols = {_text(g.get("symbol"), 12) for g in raw_genes}
    genes, seen_genes = [], set()
    for i, g in enumerate(raw_genes, 1):
        sym, name = _text(g.get("symbol"), 12), _text(g.get("name"))
        label = f"Gen „{sym}”" if sym else f"Gen nr {i}"
        if not _SYMBOL_RE.match(sym):
            errors.append(f"Gen nr {i}: symbol jest pusty albo zawiera spację, ukośnik lub przecinek.")
        elif sym in seen_genes:
            errors.append(f"{label}: taki symbol genu już istnieje.")
        seen_genes.add(sym)
        order = _number(g.get("order", 0))
        if order is None:
            errors.append(f"{label}: kolejność w fenotypie musi być liczbą.")
            order = 0
        sex_linked = bool(g.get("sexLinked"))

        alleles, allele_symbols = [], set()
        for j, a in enumerate(_as_list(g.get("alleles")), 1):
            a = _as_dict(a)
            asym = _text(a.get("symbol"), 12)
            alabel = f"{label}, allel „{asym}”" if asym else f"{label}, allel nr {j}"
            if not _SYMBOL_RE.match(asym):
                errors.append(f"{label}: allel nr {j} ma pusty symbol albo spację, ukośnik lub przecinek.")
            elif asym in allele_symbols:
                errors.append(f"{alabel}: taki symbol allelu już jest w tym genie.")
            elif sex_linked and asym in _RESERVED_SEX_LINKED:
                errors.append(f"{alabel}: „{asym}” jest zarezerwowane dla chromosomu Y.")
            allele_symbols.add(asym)
            tier = _text(a.get("tier"), 40)
            if tier not in tier_ids:
                errors.append(f"{alabel}: wybierz rzadkość.")
            weight = _number(a.get("weight", 1))
            if weight is None or weight < 0:
                errors.append(f"{alabel}: mnożnik musi być liczbą ≥ 0.")
                weight = 0
            alleles.append({
                "symbol": asym,
                "name": _text(a.get("name")),
                "tier": tier,
                "weight": weight,
                "quiet": bool(a.get("quiet")),
                "masks": _clean_masks(a.get("masks"), sym, gene_symbols, alabel, errors),
            })
        if not alleles:
            errors.append(f"{label}: gen musi mieć przynajmniej jeden allel.")

        combos, seen_pairs = [], set()
        for c in _as_list(g.get("combos")):
            c = _as_dict(c)
            pair = [_text(x, 12) for x in _as_list(c.get("alleles"))]
            shown = "/".join(pair) or "?"
            if len(pair) != 2 or any(p not in allele_symbols for p in pair):
                errors.append(f"{label}: kombinacja {shown} wskazuje nieistniejący allel.")
                continue
            key = tuple(sorted(pair))
            if key in seen_pairs:
                errors.append(f"{label}: kombinacja {shown} jest zdefiniowana dwa razy.")
                continue
            seen_pairs.add(key)
            clabel = f"{label}, kombinacja {shown}"
            combo_name = _text(c.get("name"))
            if not combo_name:
                errors.append(f"{clabel}: podaj nazwę fenotypu.")
            combos.append({
                "alleles": pair,
                "name": combo_name,
                "quiet": bool(c.get("quiet")),
                "masks": _clean_masks(c.get("masks"), sym, gene_symbols, clabel, errors),
            })

        for m in modes:
            if alleles and sum(m["weights"].get(a["tier"], 0) * a["weight"] for a in alleles) <= 0:
                warnings.append(
                    f"{label}: w trybie „{m['name']}” żaden allel nie ma szansy – losowanie weźmie allele po równo."
                )
        genes.append({
            "symbol": sym,
            "name": name,
            "order": order,
            "sexLinked": sex_linked,
            "alleles": alleles,
            "combos": combos,
        })
    if not genes:
        errors.append("Dodaj przynajmniej jeden gen.")

    return {"tiers": tiers, "modes": modes, "genes": genes}, errors, warnings
