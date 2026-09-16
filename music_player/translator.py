from __future__ import annotations

import threading
from dataclasses import dataclass

import requests

_cache_lock = threading.Lock()
_cache: dict[str, str] = {}  # word_lower -> slovak translation

# DeepL API Free dava 500 000 znakov na zuctovacie obdobie a po ich vycerpani
# preklada az od dalsieho mesiaca (HTTP 456). Denny limit nie je, takze cely
# mesiac sa da minut za jeden vecer — preto tie dve hranice nizsie.
#
# Hover nad slovom stoji ~6 znakov, cely text piesne ~2 000. Pri strope teda
# vyjde okolo 250 skladieb mesacne a hover je oproti tomu sum.
REZERVA_ZNAKOV = 5_000       # pod tymto sa cely text uz neprelozi
VAROVANIE_ZNAKOV = 50_000    # pod tymto sa prelozi, ale povie sa to

_TIMEOUT_SLOVO_S = 5
_TIMEOUT_TEXT_S = 30


@dataclass(frozen=True)
class Preklad:
    """Vysledok prekladu celeho textu.

    Chyba a varovanie su oddelene zamerne: varovanie sprevadza HOTOVY preklad
    (kvota sa michne ku koncu), chyba znamena, ze preklad neexistuje.
    """

    text: str = ""
    chyba: str = ""
    varovanie: str = ""


def _cislo(n: int) -> str:
    """1234567 -> "1 234 567". Medzera, nie ciarka: v slovenskej vete by sa
    ciarka z oddelovaca tisicov citala ako interpunkcia. Nezlomitelna
    (U+00A0), aby sa cislo nezalomilo uprostred na dva riadky."""
    return f"{n:,}".replace(",", " ")


def _base(api_key: str) -> str:
    return "https://api-free.deepl.com" if api_key.endswith(":fx") else "https://api.deepl.com"


def _hlavicky(api_key: str) -> dict[str, str]:
    return {"Authorization": f"DeepL-Auth-Key {api_key}"}


def translate_word(word: str, api_key: str) -> str:
    """Translate a single word to Slovak using DeepL. Returns empty string on failure."""
    key = word.lower()
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    try:
        resp = requests.post(
            f"{_base(api_key)}/v2/translate",
            headers=_hlavicky(api_key),
            json={"text": [word], "target_lang": "SK"},
            timeout=_TIMEOUT_SLOVO_S,
        )
        if resp.status_code == 200:
            translation = resp.json()["translations"][0]["text"]
            with _cache_lock:
                _cache[key] = translation
            return translation
    except Exception:
        pass
    return ""


def zostatok_kvoty(api_key: str) -> int | None:
    """Kolko znakov v tomto zuctovacom obdobi este zostava. None = nezistene.

    `None` nie je nula — ked sa na kvotu nedovolame (sietovy vypadok), preklad
    sa tym nema blokovat. Blokuje az odpoved, ktora naozaj povie, ze je po nej.
    """
    try:
        resp = requests.get(
            f"{_base(api_key)}/v2/usage",
            headers=_hlavicky(api_key),
            timeout=_TIMEOUT_SLOVO_S,
        )
        if resp.status_code != 200:
            return None
        telo = resp.json()
        return int(telo["character_limit"]) - int(telo["character_count"])
    except Exception:
        return None


def translate_lyrics(text: str, api_key: str) -> Preklad:
    """Prelozi CELY text jednou poziadavkou, nie slovo po slove.

    Rozdiel oproti `translate_word` nie je v API, ale v tom, co sa posiela:
    DeepL vidi cely text naraz, takze vetu roztiahnutu cez dva riadky prelozi
    ako vetu a nazvy drzi konzistentne. Hover nad slovom zostava po starom —
    tam je jedno slovo spravne, lebo sa pyta prave nan.

    `preserve_formatting` drzi zlomy riadkov, aby sa preklad dal citat vedla
    originalu vers po versi.
    """
    text = text.strip()
    if not text:
        return Preklad(chyba="Nie je čo prekladať.")
    if not api_key:
        return Preklad(chyba="Chýba DEEPL_API_KEY v config.txt.")

    zostatok = zostatok_kvoty(api_key)
    if zostatok is not None and zostatok - len(text) < REZERVA_ZNAKOV:
        return Preklad(chyba=(
            f"Mesačná kvóta DeepL je takmer minutá — zostáva {_cislo(zostatok)} znakov "
            f"a tento text ich má {_cislo(len(text))}. Preklad sa nespustil, aby ostala "
            "rezerva na preklad slov pri prechode myšou. Kvóta sa obnoví "
            "začiatkom ďalšieho zúčtovacieho obdobia."
        ))

    varovanie = ""
    if zostatok is not None and zostatok - len(text) < VAROVANIE_ZNAKOV:
        po_preklade = zostatok - len(text)
        varovanie = (
            f"Po tomto preklade zostane v mesačnej kvóte DeepL približne "
            f"{_cislo(po_preklade)} znakov z 500 000 — asi "
            f"{max(0, po_preklade // 2000)} skladieb."
        )

    posledna_chyba = "Preklad sa nepodaril."
    for pokus in range(2):
        try:
            resp = requests.post(
                f"{_base(api_key)}/v2/translate",
                headers=_hlavicky(api_key),
                json={
                    "text": [text],
                    "target_lang": "SK",
                    "preserve_formatting": True,
                },
                timeout=_TIMEOUT_TEXT_S,
            )
        except Exception as e:
            posledna_chyba = f"DeepL sa nedá dovolať: {e}"
            continue

        if resp.status_code == 200:
            preklad = resp.json()["translations"][0]["text"].strip()
            if not preklad:
                return Preklad(chyba="DeepL vrátil prázdny preklad.")
            return Preklad(text=preklad, varovanie=varovanie)

        if resp.status_code == 456:
            return Preklad(chyba=(
                "Mesačná kvóta DeepL je vyčerpaná (HTTP 456). Preklady sa "
                "obnovia začiatkom ďalšieho zúčtovacieho obdobia."
            ))
        if resp.status_code == 429:
            posledna_chyba = "DeepL hlási príliš veľa požiadaviek (HTTP 429), skús o chvíľu."
            continue
        if resp.status_code >= 500:
            posledna_chyba = f"DeepL má dočasný výpadok (HTTP {resp.status_code})."
            continue

        return Preklad(chyba=f"DeepL odmietol požiadavku (HTTP {resp.status_code}).")

    return Preklad(chyba=posledna_chyba)
