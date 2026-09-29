import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import genetics  # noqa: E402

SEED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed_config.json")


def load_seed():
    with open(SEED, encoding="utf-8") as fh:
        config, errors, _ = genetics.clean_config(json.load(fh))
    assert not errors, errors
    return config


def gene(symbol, alleles, combos=(), sex_linked=False, order=0):
    return {
        "symbol": symbol,
        "name": symbol,
        "order": order,
        "sexLinked": sex_linked,
        "alleles": [
            {"symbol": s, "name": n, "tier": "common", "weight": 1, "quiet": False, "masks": m}
            for s, n, m in alleles
        ],
        "combos": [{"alleles": list(p), "name": n, "quiet": False, "masks": []} for p, n in combos],
    }


def simple_config(*genes):
    return {
        "tiers": [{"id": "common", "name": "Common"}],
        "modes": [{"id": "common", "name": "Common", "weights": {"common": 100}}],
        "genes": list(genes),
    }


def litter(config, mother, father, sex=None, n=300):
    rng = random.Random(7)
    return [genetics.roll_kitten(config, mother, father, sex=sex, rng=rng) for _ in range(n)]


def outcomes(kittens, symbol):
    """{genotyp: szansa} dla jednego genu, zebrane z wylosowanych kociąt."""
    return {tuple(k["genotype"][symbol]): k["probability"] for k in kittens}


C_GENE = gene("C", [("C", "Pełny kolor", []), ("c", "Syjamski", [])])


class SeedTest(unittest.TestCase):
    def test_seed_is_valid(self):
        load_seed()

    def test_common_mode_never_gives_rare_or_uncommon_alleles(self):
        config = load_seed()
        rng = random.Random(1)
        allowed = {
            a["symbol"] for g in config["genes"] for a in g["alleles"] if a["tier"] == "common"
        }
        for _ in range(300):
            cat = genetics.roll_cat(config, "common", rng=rng)
            for alleles in cat["genotype"].values():
                self.assertTrue(set(alleles) <= allowed, alleles)

    def test_probabilities_sum_to_one_and_respect_tiers(self):
        config = load_seed()
        c = next(g for g in config["genes"] if g["symbol"] == "C")
        probs = genetics.allele_probabilities(config, c, "rare")
        self.assertAlmostEqual(sum(probs.values()), 1.0)
        # rare: common 50, uncommon 30 (×2 allele), rare 20 (×2 allele) -> suma wag 150
        self.assertAlmostEqual(probs["C"], 50 / 150)
        self.assertAlmostEqual(probs["cb"], 30 / 150)
        self.assertAlmostEqual(probs["c"], 20 / 150)

    def test_male_has_one_allele_of_sex_linked_gene(self):
        config = load_seed()
        cat = genetics.roll_cat(config, "rare", sex="M", rng=random.Random(3))
        self.assertEqual(len(cat["genotype"]["O"]), 1)
        self.assertEqual(len(cat["genotype"]["B"]), 2)


class CrossTest(unittest.TestCase):
    def test_Cc_x_CC(self):
        config = simple_config(C_GENE)
        kittens = litter(config, {"C": ["C", "c"]}, {"C": ["C", "C"]})
        self.assertEqual(outcomes(kittens, "C"), {("C", "C"): 0.5, ("C", "c"): 0.5})

    def test_Cc_x_Cc(self):
        config = simple_config(C_GENE)
        kittens = litter(config, {"C": ["c", "C"]}, {"C": ["C", "c"]})
        self.assertEqual(outcomes(kittens, "C"), {("C", "C"): 0.25, ("C", "c"): 0.5, ("c", "c"): 0.25})

    def test_sex_linked_orange(self):
        o = gene("O", [("O", "Rudy", []), ("o", "Nie-rudy", [])], combos=[(("O", "o"), "Szylkret")],
                 sex_linked=True)
        config = simple_config(o)
        mother, father = {"O": ["O", "o"]}, {"O": ["o"]}
        # córka: allel matki + allel ojca; syn: tylko allel matki
        self.assertEqual(outcomes(litter(config, mother, father, sex="F"), "O"), {("O", "o"): 0.5, ("o", "o"): 0.5})
        self.assertEqual(outcomes(litter(config, mother, father, sex="M"), "O"), {("O",): 0.5, ("o",): 0.5})
        tortie = genetics.describe(config, {"sex": "F", "genotype": {"O": ["o", "O"]}})
        self.assertEqual(tortie["genes"][0]["phenotype"], "Szylkret")
        self.assertEqual(genetics.format_genotype(o, ["O"]), "OY")

    def test_multi_letter_alleles_use_slash(self):
        config = load_seed()
        c = next(g for g in config["genes"] if g["symbol"] == "C")
        self.assertEqual(genetics.format_genotype(c, ["cs", "cb"]), "cb/cs")
        self.assertEqual(genetics.format_genotype(c, ["c", "C"]), "Cc")

    def test_kitten_probability(self):
        config = simple_config(C_GENE, gene("D", [("D", "Pełny", []), ("d", "Rozjaśniony", [])]))
        kitten = genetics.roll_kitten(
            config, {"C": ["C", "c"], "D": ["D", "d"]}, {"C": ["C", "c"], "D": ["d", "d"]},
            rng=random.Random(5),
        )
        c_p = {("C", "C"): 0.25, ("C", "c"): 0.5, ("c", "c"): 0.25}[tuple(kitten["genotype"]["C"])]
        d_p = 0.5
        self.assertAlmostEqual(kitten["probability"], c_p * d_p)


class PhenotypeTest(unittest.TestCase):
    def test_carrier_and_zygosity(self):
        config = simple_config(C_GENE)
        cat = genetics.describe(config, {"sex": "F", "genotype": {"C": ["c", "C"]}})
        [row] = cat["genes"]
        self.assertEqual(row["text"], "Cc")
        self.assertEqual(row["phenotype"], "Pełny kolor")
        self.assertEqual(row["zygosity"], "heterozygous")
        self.assertEqual(row["carriers"], [{"symbol": "c", "name": "Syjamski"}])

    def test_combo_overrides_dominance(self):
        config = load_seed()
        s = next(g for g in config["genes"] if g["symbol"] == "S")
        self.assertEqual(genetics.gene_outcome(s, ["S", "s"])["phenotype"], "Trochę bieli (bicolor)")
        self.assertEqual(genetics.gene_outcome(s, ["s", "s"])["phenotype"], "Bez białych łat")

    def test_masking_respects_priority(self):
        config = load_seed()
        base = {g["symbol"]: [g["alleles"][0]["symbol"]] * 2 for g in config["genes"]}
        # Rudy kocur, non-agouti: rudy maskuje A i B, więc A nie maskuje wzoru T.
        genotype = dict(base, W=["w", "w"], O=["O"], A=["a", "a"])
        cat = genetics.describe(config, {"sex": "M", "genotype": genotype})
        rows = {r["symbol"]: r for r in cat["genes"]}
        self.assertEqual(rows["B"]["maskedBy"], ["O"])
        self.assertEqual(rows["A"]["maskedBy"], ["O"])
        self.assertEqual(rows["T"]["maskedBy"], [])
        # Biel dominująca zasłania wszystko.
        white = genetics.describe(config, {"sex": "F", "genotype": dict(base, O=["o", "o"])})
        self.assertTrue(all(r["maskedBy"] == ["W"] for r in white["genes"] if r["symbol"] != "W"))


class ParseTest(unittest.TestCase):
    def test_parse_mixed_notation(self):
        config = load_seed()
        result = genetics.parse_genotype(config, "ww Bbl OY dd Ii ss Aa Tatb cb/cs Ll", "M")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["missing"], [])
        g = result["genotype"]
        self.assertEqual(g["B"], ["B", "bl"])
        self.assertEqual(g["O"], ["O"])
        self.assertEqual(g["T"], ["Ta", "tb"])
        self.assertEqual(g["C"], ["cb", "cs"])

    def test_parse_reports_problems(self):
        config = load_seed()
        result = genetics.parse_genotype(config, "Oo xyz", "M")
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn("kocur ma tylko jeden allel genu O – zapisz np. „OY”", result["errors"][0])
        self.assertIn("B", result["missing"])
        female = genetics.parse_genotype(config, "oY", "F")
        self.assertIn("kotka ma dwa allele genu O – zapisz np. „oo”", female["errors"][0])


class ValidationTest(unittest.TestCase):
    def test_detects_errors(self):
        config = simple_config(
            gene("C", [("C", "a", ["X"]), ("C", "b", [])]),
            gene("C", [("c", "c", [])]),
        )
        config["genes"][0]["alleles"][0]["tier"] = "nope"
        _, errors, _ = genetics.clean_config(config)
        text = " ".join(errors)
        self.assertIn("nieistniejący gen „X”", text)
        self.assertIn("taki symbol allelu już jest", text)
        self.assertIn("taki symbol genu już istnieje", text)
        self.assertIn("wybierz rzadkość", text)

    def test_warns_when_mode_has_no_allowed_allele(self):
        config = load_seed()
        for a in config["genes"][0]["alleles"]:
            a["tier"] = "rare"
        _, errors, warnings = genetics.clean_config(config)
        self.assertEqual(errors, [])
        self.assertTrue(any("Common" in w for w in warnings))

    def test_public_config_hides_weights(self):
        public = json.dumps(genetics.public_config(load_seed()))
        self.assertNotIn("weight", public)
        self.assertNotIn("tier", public)
        self.assertNotIn("combos", public)


if __name__ == "__main__":
    unittest.main()
