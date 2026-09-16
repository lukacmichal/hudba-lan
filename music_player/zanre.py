r"""Filter zanrov — ktore vydania sa v Novinkach ukazu.

Toto je **kopia** logiky z `C:\NAS\metal-novinky\filtre.py`, nie import.
Projekty maju byt samostatne: presun alebo zmazanie jedneho nesmie umlcat
druhy. Rovnaky dovod, preco su `posta.py` a `uspavanie.py` v skenoch
skopirovane a nie zdielane.

**Preco filtruje aj prehravac.** Sken posle do zoznamu VSETKO, co posudil —
aj to, co podla zanru zahodil. Bez toho by sa filter nedal ladit: keby si
pridal „doom", nemalo by co ukazat, lebo doomove vydania by v subore neboli.
Takto sa zmena slov prejavi hned a bez cakania na nocny sken.

Slova su v `filtre.json` vedla zoznamu na NAS-e — teda v jedinom subore, ktory
cita aj sken. Co sa zmeni tu, plati aj pre mail.

Pravidlo je z povodneho zadania a rozhoduje slovo **„cisty"**: zakazane zanre
vyradia vydanie len vtedy, ked je styl vyhradne z nich. Len co sa v style
objavi povolene slovo, vydanie prejde — „Death Metal/Thrash Metal" je pre
tento ucel death metal, nie thrash. Opacne poradie (zakazane slovo vetuje) by
zahodilo vacsinu Melodic Death a Blackened Thrash kapiel, teda presne to, co
sa ma ukazat.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SUBOR = "filtre.json"

#: Predvolby. Platia, kym na NAS-e nie je `filtre.json` — ten tam sken zapise
#: pri prvom behu, takze v praxi je to len poistka pre uplne cerstvu instalaciu.
POVOLENE = ["death", "black", "grind", "grindcore", "atmospheric", "post metal"]
ZAKAZANE = ["power", "viking", "speed", "sludge", "heavy", "thrash", "crossover"]

PRESLO = "preslo"
ODMIETNUTE = "odmietnute"
NEZARADENE = "nezaradene"


def normalizuj(styl: str) -> str:
    """Zjednoti zapis, nech sa da hladat podretazcom.

    MA pise style rozne — „Post-Metal", „Post Metal", „Death Metal/Grindcore",
    „Black/Death Metal". Po nahradeni vsetkeho nepismenoveho medzerou staci
    hladat povolene slova ako podretazce.
    """
    return " " + re.sub(r"[^a-z0-9]+", " ", styl.casefold()).strip() + " "


def _najdene(styl_norm: str, slova: list[str]) -> list[str]:
    return [s for s in slova if s in styl_norm]


def posud(styl: str, povolene: list[str], zakazane: list[str]) -> tuple[str, str]:
    """(vysledok, ludsky dovod). Vysledok je PRESLO / ODMIETNUTE / NEZARADENE."""
    if not styl or not styl.strip():
        return NEZARADENE, "MA neuvádza štýl"

    n = normalizuj(styl)
    ano = _najdene(n, povolene)
    nie = _najdene(n, zakazane)

    if ano:
        dovod = "obsahuje " + ", ".join(sorted(set(ano)))
        if nie:
            dovod += f" (aj {', '.join(sorted(set(nie)))}, ale nie je to čistý {nie[0]})"
        return PRESLO, dovod
    if nie:
        return ODMIETNUTE, "čistý " + ", ".join(sorted(set(nie)))
    return NEZARADENE, "štýl nesedí ani na jeden zoznam"


# ── slova ─────────────────────────────────────────────────────────────────────
def _ocisti(hodnota, predvolba: list[str]) -> list[str]:
    """Zoznam slov zo suboru. Cokolvek pokazene = predvolba.

    Prazdny `povolene` by znamenal „neprejde nic" — teda prazdne okno bez
    vysvetlenia. Radsej predvolby nez ticho vypnuty filter.
    """
    if not isinstance(hodnota, list):
        return list(predvolba)
    ocistene = [str(x).strip().casefold() for x in hodnota if str(x).strip()]
    return ocistene or list(predvolba)


def rozober(text: str) -> tuple[list[str], list[str]]:
    """(povolene, zakazane) z obsahu `filtre.json`."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return list(POVOLENE), list(ZAKAZANE)
    if not isinstance(data, dict):
        return list(POVOLENE), list(ZAKAZANE)
    return (_ocisti(data.get("povolene"), POVOLENE),
            _ocisti(data.get("zakazane"), ZAKAZANE))


def zloz(povolene: list[str], zakazane: list[str]) -> str:
    """Obsah `filtre.json` — v tom istom tvare, v akom ho pise sken."""
    return json.dumps({"povolene": povolene, "zakazane": zakazane},
                      ensure_ascii=False, indent=1)


def zo_zoznamu(text: str) -> list[str]:
    """Slova z textoveho pola (jedno na riadok, aj ciarkami)."""
    slova = []
    for riadok in text.replace(",", "\n").splitlines():
        slovo = riadok.strip().casefold()
        if slovo and slovo not in slova:
            slova.append(slovo)
    return slova


def do_zoznamu(slova: list[str]) -> str:
    """Slova do textoveho pola — jedno na riadok, nech sa dobre edituju."""
    return "\n".join(slova)
