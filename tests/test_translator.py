"""Preklad celeho textu piesne a strazca mesacnej kvoty DeepL.

Preco to stoji za test: DeepL API Free ma 500 000 znakov na zuctovacie obdobie
a po ich vycerpani nepreklada uz NIC — ani slovo pri prechode mysou. Jedna
skladba stoji ~2 000 znakov, takze niekolko desiatok kliknuti za vecer je este
v pohode, ale bez stropu sa da mesiac minut naraz. Tieto testy drzia, ze:

  1. cely text ide jednou poziadavkou (nie slovo po slove),
  2. tesne pred vycerpanim kvoty sa preklad NESPUSTI,
  3. blizko stropu sa prelozi, ale povie sa to,
  4. HTTP 456 (kvota prec) sa necita ako docasna chyba a neopakuje sa.

Ziadny z testov nemini realnu kvotu — sietova vrstva je podvrhnuta.

Standalone:
    python tests/test_translator.py
"""
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_player import translator  # noqa: E402

KLUC = "test-kluc:fx"


class _Odpoved:
    """Nahrada za requests.Response — len to, co translator naozaj cita."""

    def __init__(self, status_code: int, telo: dict | None = None):
        self.status_code = status_code
        self._telo = telo or {}

    def json(self) -> dict:
        return self._telo


@contextmanager
def podvrhnuta_siet(odpoved: _Odpoved, zostatok: int | None):
    """Odstrihne translator od siete a po teste vrati vsetko spat.

    Restore je v `finally` zamerne: bez neho by pod pytestom ostal `requests.post`
    podvrhnuty aj pre ostatne testovacie moduly v tom istom behu.

    Yielduje zoznam odoslanych tiel poziadaviek — testy na nom overuju, ci sa
    islo na siet a kolkokrat.
    """
    volania: list = []
    povodny_post = translator.requests.post
    povodny_zostatok = translator.zostatok_kvoty

    def _post(url, headers=None, json=None, timeout=None):
        volania.append(json)
        return odpoved

    translator.requests.post = _post
    translator.zostatok_kvoty = lambda k: zostatok
    try:
        yield volania
    finally:
        translator.requests.post = povodny_post
        translator.zostatok_kvoty = povodny_zostatok


def test_cely_text_ide_jednou_poziadavkou():
    odpoved = _Odpoved(200, {"translations": [{"text": "Prvý riadok\nDruhý riadok"}]})
    with podvrhnuta_siet(odpoved, zostatok=400_000) as volania:
        text = "First line\nSecond line"
        v = translator.translate_lyrics(text, KLUC)

    assert v.chyba == "", v.chyba
    assert v.text == "Prvý riadok\nDruhý riadok"
    assert len(volania) == 1, "text sa mal poslat naraz, nie po castiach"
    telo = volania[0]
    assert telo["text"] == [text], "posiela sa cely text, nie jednotlive slova"
    assert telo["target_lang"] == "SK"
    assert telo["preserve_formatting"] is True, "bez toho sa stratia zlomy riadkov"
    print("OK  cely text ide jednou poziadavkou")


def test_pred_vycerpanim_kvoty_sa_neprelozi():
    # Zostava menej, nez je rezerva — preklad by ju zjedol do nuly.
    zostatok = translator.REZERVA_ZNAKOV + 100
    with podvrhnuta_siet(_Odpoved(200, {}), zostatok=zostatok) as volania:
        v = translator.translate_lyrics("x" * 2000, KLUC)

    assert v.text == ""
    assert "kvóta" in v.chyba.lower()
    assert volania == [], "pri plnej kvote sa nesmie ist na siet vobec"
    print("OK  tesne pred stropom sa preklad nespusti")


def test_blizko_stropu_prelozi_ale_varuje():
    odpoved = _Odpoved(200, {"translations": [{"text": "preklad"}]})
    zostatok = translator.VAROVANIE_ZNAKOV + 500
    with podvrhnuta_siet(odpoved, zostatok=zostatok):
        v = translator.translate_lyrics("x" * 2000, KLUC)

    assert v.text == "preklad", "blizko stropu sa este prekladat MA"
    assert v.chyba == ""
    assert v.varovanie, "malo prist upozornenie, ze sa kvota mini"
    print("OK  blizko stropu prelozi a upozorni")


def test_vycerpana_kvota_sa_neopakuje():
    # Kvota sa nezisti (napr. vypadok), takze sa ide na siet a odpovie 456.
    with podvrhnuta_siet(_Odpoved(456), zostatok=None) as volania:
        v = translator.translate_lyrics("nieco", KLUC)

    assert v.text == ""
    assert "456" in v.chyba
    assert len(volania) == 1, "456 nie je docasna chyba, opakovat sa nema"
    print("OK  HTTP 456 sa neopakuje")


def test_docasna_chyba_sa_zopakuje():
    with podvrhnuta_siet(_Odpoved(429), zostatok=400_000) as volania:
        v = translator.translate_lyrics("nieco", KLUC)

    assert v.text == ""
    assert len(volania) == 2, "429 je docasna, ma sa skusit este raz"
    print("OK  HTTP 429 sa zopakuje")


def test_prazdny_text_a_chybajuci_kluc():
    # Ani jedno sa nema dostat na siet, takze podvrh netreba.
    assert translator.translate_lyrics("   ", KLUC).chyba
    assert "DEEPL_API_KEY" in translator.translate_lyrics("nieco", "").chyba
    print("OK  prazdny text aj chybajuci kluc maju zrozumitelnu hlasku")


if __name__ == "__main__":
    test_cely_text_ide_jednou_poziadavkou()
    test_pred_vycerpanim_kvoty_sa_neprelozi()
    test_blizko_stropu_prelozi_ale_varuje()
    test_vycerpana_kvota_sa_neopakuje()
    test_docasna_chyba_sa_zopakuje()
    test_prazdny_text_a_chybajuci_kluc()
    print("\nVsetky testy presli.")
