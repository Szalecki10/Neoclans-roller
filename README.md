# 🐾 Neoclans Roller

Prosta strona do genetyki kotów:

1. **Losowanie z tabeli** – losowy kot w trybie *Common / Uncommon / Rare*. Tryb zmienia szanse na rzadsze cechy (w Common rzadkie cechy w ogóle nie wypadają).
2. **Krzyżówka rodziców** – wpisujesz genotyp matki i ojca (albo losujesz rodzica z tabeli), a strona losuje kocięta.

Każdy wynik ma **genotyp** (np. `ww Bb Oo dd Cc`) i **fenotyp** (np. „Czarny, Szylkret, Rozjaśniony”).

Tabelę genów (cechy, allele, dominację, rzadkość, szanse) edytuje tylko admin w `/admin`. Wszyscy korzystają z tej samej bazy.

---

## Jak to działa

### Losowanie z tabeli
- Każdy allel ma **rzadkość** (Common/Uncommon/Rare – lista do edycji).
- Każdy **tryb** ma wagę dla każdej rzadkości, np. Common = `100 / 0 / 0`, Rare = `50 / 30 / 20`.
- Szansa allelu = `waga rzadkości w trybie × mnożnik allelu`, przeliczona na % w obrębie genu.
- Kot dostaje **dwa allele każdego genu, losowane osobno** (kocur jeden allel przy genach sprzężonych z płcią). Dzięki temu koty mogą nosić ukryte cechy recesywne, a cecha recesywna wychodzi rzadziej niż sam allel. W panelu admina widać dokładne szanse na każdy fenotyp w każdym trybie.

### Krzyżówka
- Genotyp rodzica wpisuje się tekstem, np. `ww Bb Oo dd Cc` (allele wieloznakowe z ukośnikiem: `cb/cs`, kocur przy genie sprzężonym z płcią: `OY`). Trzeba podać wszystkie geny z tabeli, bo inaczej strona wypisze, których brakuje.
- Każdy rodzic przekazuje jeden losowy allel z pary, np. z `Cc × CC` wychodzi `CC` albo `Cc`, po 50%.
- **Geny sprzężone z płcią** (jak rudy `O`): kotka ma dwa allele, kocur jeden (`OY` / `oY`). Córki dostają allel matki + allel ojca, synowie tylko allel matki. Dlatego szylkret (`Oo`) jest prawie zawsze kotką.
- Przy każdym kocięciu jest też szansa na wylosowanie dokładnie takiego genotypu.

### Fenotyp: dominacja, kombinacje, maskowanie
- **Kolejność alleli w genie = dominacja.** Allel wyżej na liście zasłania te niżej (`C > cb > cs > ca > c`).
- **Kombinacje** nadpisują zwykłą dominację: niepełna dominacja (`S/s` = trochę bieli, `S/S` = dużo bieli) albo kodominacja (`O/o` = szylkret, `cb/cs` = mink).
- **Maskowanie (epistaza):** cecha może zasłaniać inne geny, np. biel dominująca `W` zasłania wszystko (`*`), rudy zasłania kolor bazowy i agouti. Geny wcześniej w kolejności fenotypu mają pierwszeństwo, a zamaskowany gen sam już nic nie maskuje.
- **„Ukryj w opisie”:** cecha nie trafia do opisu fenotypu (np. „bez srebra”).

### Sortowanie: wg genotypu / wg fenotypu
- **Wg genotypu:** geny alfabetycznie po symbolu locus (`A, B, C, D, I, L, O, S, T, W`). Tak zwykle zapisuje się genotyp.
- **Wg fenotypu:** w kolejności, w jakiej opisuje się ubarwienie kota. Bazą jest system kodów **EMS** federacji FIFe: najpierw kolor, potem srebro/złoto, ilość bieli (01–09), wzór pręgowania (21–25), pointy (31–33), a na koniec długość sierści. Kolejność ustawia admin w polu „Kolejność w fenotypie” (mniejsza liczba = wcześniej).
  Źródło: [FIFe – EMS system](https://fifeweb.org/cats/ems-system/).

Wybrana kolejność dotyczy zarówno zapisu genotypu, jak i opisu fenotypu. Przeglądarka ją zapamiętuje.

---

## Model danych

Konfiguracja to jeden dokument JSON. Każdy zapis admina tworzy w bazie nową wersję w tabeli `config_versions (id, created_at, note, data JSONB)`, więc da się wrócić do starszej.

```jsonc
{
  "tiers": [ { "id": "common", "name": "Common" }, ... ],          // poziomy rzadkości
  "modes": [                                                       // tryby losowania
    { "id": "rare", "name": "Rare", "weights": { "common": 50, "uncommon": 30, "rare": 20 } }
  ],
  "genes": [
    {
      "symbol": "O",                 // symbol genu (locus)
      "name": "Rudy",
      "order": 20,                   // kolejność w fenotypie + pierwszeństwo maskowania
      "sexLinked": true,             // na chromosomie X – kocur ma 1 allel
      "alleles": [                   // KOLEJNOŚĆ = DOMINACJA (pierwszy dominuje)
        { "symbol": "O", "name": "Rudy", "tier": "common", "weight": 1, "quiet": false, "masks": ["B", "A"] },
        { "symbol": "o", "name": "Nie-rudy", "tier": "common", "weight": 3, "quiet": true, "masks": [] }
      ],
      "combos": [                    // wyjątki od dominacji
        { "alleles": ["O", "o"], "name": "Szylkret (tortie)", "quiet": false, "masks": [] }
      ]
    }
  ]
}
```

Dane startowe są w [`seed_config.json`](seed_config.json): 10 prawdziwych genów kotów (W, B, O, D, I, S, A, T, C, L). Wczytują się tylko przy pierwszym uruchomieniu z pustą bazą. Potem wszystko zmienia się w panelu admina.

Zwykli użytkownicy dostają z API tylko symbole i nazwy alleli. Wagi, rzadkości, kombinacje i maskowanie zostają na serwerze, a losowanie odbywa się po stronie serwera.

---

## Uruchomienie lokalne

Wymagany Python 3.11+.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements.txt
```

```bash
.venv/Scripts/python app.py
```

Strona będzie pod http://localhost:5000, a panel pod http://localhost:5000/admin. Bez `DATABASE_URL` dane trafiają do lokalnego pliku SQLite `data/neoclans.db`. Bez `ADMIN_PASSWORD` serwer wypisze w konsoli tymczasowe hasło.

Testy:

```bash
python -m unittest discover -s tests -v
```

(Na Linuksie/macOS zamiast `.venv/Scripts/python` jest `.venv/bin/python`.)

---

## Wdrożenie za darmo: GitHub + Render + Neon

Darmowa baza Postgres na Renderze znika po 30 dniach, więc baza stoi na **Neon** (darmowy Postgres bez terminu ważności, 0,5 GB – dla tej strony to więcej niż trzeba). Sama strona stoi na **Renderze** i aktualizuje się automatycznie po każdym `git push`.

1. **GitHub** – wrzuć to repozytorium (może być prywatne).
2. **Neon** – załóż konto na [neon.com](https://neon.com), utwórz projekt (region np. Frankfurt), skopiuj *connection string* (`postgresql://…?sslmode=require…`).
3. **Render** – na [render.com](https://render.com): **New → Blueprint** → wybierz repo. Render przeczyta `render.yaml` i zapyta o:
   - `ADMIN_PASSWORD` – hasło do panelu admina,
   - `DATABASE_URL` – connection string z Neona.
4. Po buildzie strona działa pod `https://neoclans-roller.onrender.com` (albo podobnym adresem). Link wysyłasz znajomym, a hasło dajesz tylko adminowi.

Bez Blueprinta: **New → Web Service**, runtime Python, build `pip install -r requirements.txt`, start `gunicorn app:app --workers 1 --threads 4 --timeout 60`, plan Free, plus te same dwie zmienne środowiskowe.

**Uśpienie:** darmowy Render usypia stronę po 15 minutach bez ruchu. Pierwsze wejście potem trwa ok. 30–60 s (strona pokazuje wtedy komunikat „Budzę serwer…”). Neon też usypia bazę, ale budzi się w ułamku sekundy.

### Hasło admina
Hasło jest w zmiennej środowiskowej `ADMIN_PASSWORD` na Renderze, a **nie w kodzie**. Kod leży na GitHubie, więc hasło wpisane w plik zobaczyłby każdy, kto ma dostęp do repo. Zmiana hasła w Renderze wylogowuje wszystkie sesje. Po 10 błędnych próbach z jednego adresu logowanie jest blokowane na 15 minut.

### Kopie zapasowe
- Panel admina → **Kopia zapasowa i historia**: ostatnie 200 zapisów, każdy można wczytać i przywrócić.
- **Pobierz JSON** – cała tabela do pliku. Warto to robić po większych zmianach.

---

## Struktura

```
app.py              serwer Flask: API, logowanie admina
genetics.py         cała logika: losowanie, krzyżówki, fenotypy, walidacja
storage.py          zapis wersji konfiguracji (Postgres albo SQLite)
seed_config.json    dane startowe
static/             strona (czysty HTML/CSS/JS, bez builda)
  index.html, app.js      losowanie i krzyżówka
  admin.html, admin.js    panel admina
  common.js, style.css    wspólne
tests/              testy logiki genetyki
render.yaml         konfiguracja Rendera
```
