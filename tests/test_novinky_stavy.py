"""Novinky: stavy nove / zaujimave / skontrolovane, hladanie a okno.

Co tieto testy drzia:

  1. zaujimavy album nezmizne, ked ho sken prestane posielat (tyzden presiel),
  2. riadok bez `stav` (starsia verzia) plati podla `precitane`,
  3. zaujimavy ma v logu `precitane: true` — starsia verzia na druhom
     notebooku ho tak aspon neukaze medzi novymi,
  4. hladanie ignoruje diakritiku a povie, v ktorej zalozke album je,
  5. zmena stavu v okne presunie album medzi zalozkami a zapise snimku.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from music_player import novinky  # noqa: E402


@pytest.fixture(autouse=True)
def lokalna_kopia(tmp_path, monkeypatch):
    monkeypatch.setattr(novinky, "_app_state_dir", lambda: tmp_path / "appdata")


def album(kluc, **extra):
    kapela, nazov = kluc.split("|")
    return novinky.Album(kluc=kluc, kapela=kapela.title(), album=nazov.title(),
                         styl=extra.pop("styl", "Black Metal"), **extra)


def zoznam_na_nas(priecinok, albumy, zalozky):
    priecinok.mkdir(parents=True, exist_ok=True)
    (priecinok / novinky.SUBOR).write_text(json.dumps({
        "format": 1, "zalozky": zalozky,
        "albumy": [{"kluc": a.kluc, "kapela": a.kapela, "album": a.album,
                    "styl": a.styl, "krajina": a.krajina, "vydanie": a.vydanie}
                   for a in albumy],
    }), encoding="utf-8")
    return priecinok


# ── log ──────────────────────────────────────────────────────────────────────
def test_zaujimavy_prezije_vypadnutie_zo_zoznamu(tmp_path):
    nas = tmp_path / "nas"
    grievance = album("grievance|occult encryptions", krajina="Portugal", vydanie="2026-09-07")
    zoznam_na_nas(nas, [grievance], {"tyzden": [grievance.kluc]})
    novinky.oznac([grievance.kluc], p=nas, stav=novinky.ZAUJIMAVE,
                  albumy={grievance.kluc: grievance})

    # Novy tyzden: sken album v zozname uz nema.
    zoznam_na_nas(nas, [], {"tyzden": []})
    z = novinky.nacitaj(nas)

    assert z.stav(grievance.kluc) == novinky.ZAUJIMAVE
    assert [a.krajina for a in z.v_stave(novinky.ZAUJIMAVE)] == ["Portugal"]


def test_stary_riadok_bez_stavu_plati_podla_precitane():
    text = "\n".join([
        json.dumps({"kluc": "a|1", "precitane": True}),
        json.dumps({"kluc": "b|1", "precitane": False}),
        novinky.riadok_logu("c|1", stav=novinky.ZAUJIMAVE),
    ])
    stavy, _ = novinky.rozober_stavy(text)
    assert stavy == {"a|1": novinky.SKONTROLOVANE, "b|1": novinky.NOVE,
                     "c|1": novinky.ZAUJIMAVE}


def test_zaujimavy_starsia_verzia_neukaze_medzi_novymi():
    assert json.loads(novinky.riadok_logu("c|1", stav=novinky.ZAUJIMAVE))["precitane"] is True
    assert json.loads(novinky.riadok_logu("c|1", stav=novinky.NOVE))["precitane"] is False


def test_nove_nezahrna_zaujimave_ani_skontrolovane():
    z = novinky.Zoznam(albumy=[album("a|1"), album("b|1"), album("c|1")])
    z.nastav(["a|1"], novinky.ZAUJIMAVE)
    z.nastav(["b|1"], novinky.SKONTROLOVANE)
    assert [a.kluc for a in z.nove()] == ["c|1"]
    z.nastav(["a|1"], novinky.SKONTROLOVANE)
    assert z.zaujimave == set() and z.precitane == {"a|1", "b|1"}


# ── hladanie ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("dopyt", ["kjaerlighetarn", "KJÆRLIGHETARN", "kazorcshen kjaer",
                                   "hungary"])
def test_zhoda_bez_diakritiky(dopyt):
    a = novinky.Album(kluc="k|k", kapela="Kazorcshen", album="Kjærlighetarn", krajina="Hungary")
    assert novinky.zhoda(a, dopyt)


def test_zhoda_vsetky_slova():
    a = novinky.Album(kluc="k|k", kapela="Kazorcshen", album="Kjærlighetarn")
    assert not novinky.zhoda(a, "kazorcshen behemoth")


# ── okno ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def okno():
    from PySide6.QtWidgets import QApplication

    from music_player import ui

    app = QApplication.instance() or QApplication([])
    z = novinky.Zoznam(
        albumy=[album("grievance|occult encryptions", vydanie="2026-09-07"),
                album("draumur|from fading sun", vydanie="2026-09-08"),
                album("malefic|forgotten epitaph", vydanie="2026-09-07")],
        zalozky={"tyzden": ["grievance|occult encryptions", "malefic|forgotten epitaph"],
                 "uz_vydane": ["draumur|from fading sun"]},
        povolene=["black"], zakazane=[])
    z.nastav(["malefic|forgotten epitaph"], novinky.SKONTROLOVANE)
    zapisy = []
    dlg = ui._NovinkyDialog(None, z, lambda kluce, stav, albumy: zapisy.append((kluce, stav, albumy)))
    yield dlg, z, zapisy
    dlg.deleteLater()
    app.processEvents()


def pocty(dlg):
    return [dlg._zalozky.tabText(i) for i in range(dlg._zalozky.count())]


def test_okno_ma_styri_zalozky(okno):
    dlg, _z, _ = okno
    assert pocty(dlg) == ["Tento týždeň (1)", "Už vydané (1)", "Zaujímavé (0)",
                          "Skontrolované (1)"]


def test_hladanie_povie_zalozku_a_prepne_na_nu(okno):
    dlg, _z, _ = okno
    dlg._hladaj.setText("malefic")
    assert "Skontrolované" in dlg._nalez.text()
    assert dlg._zalozky.currentIndex() == 3
    assert pocty(dlg)[0] == "Tento týždeň (0)"


def test_hladanie_nenajdene(okno):
    dlg, _z, _ = okno
    dlg._hladaj.setText("behemoth")
    assert "nie je v žiadnej záložke" in dlg._nalez.text()


def test_pravy_klik_oznaci_riadok_a_ukaze_menu(okno, monkeypatch):
    """Lave tlacidlo len oznacuje; menu je na pravom a plati pre riadok pod mysou."""
    from music_player import ui

    dlg, _z, _ = okno
    ukazane = []

    # Podtrieda, nie zaplata `QMenu.exec`: tu Qt zaplatu na svojom type
    # nevidi, skutocne modalne menu sa otvori a test visi navzdy.
    class Menu(ui.QMenu):
        def exec(self, *a):
            ukazane.append([x.text() for x in self.actions()])

    monkeypatch.setattr(ui, "QMenu", Menu)
    zoznam = dlg._zoznamy["tyzden"]
    dlg._zalozky.setCurrentWidget(zoznam)
    riadok = next(zoznam.item(i) for i in range(zoznam.count())
                  if zoznam.item(i).data(dlg._ROLA) is not None)

    dlg._ukaz_menu(zoznam.visualItemRect(riadok).center())

    assert riadok.isSelected()
    assert "★ Zaujímavé" in ukazane[0] and "✓ Skontrolované" in ukazane[0]
    assert zoznam.contextMenuPolicy() == ui.Qt.ContextMenuPolicy.CustomContextMenu


def test_zaujimave_presunie_album_a_zapise_snimku(okno):
    dlg, z, zapisy = okno
    zoznam = dlg._zoznamy["tyzden"]
    riadok = next(zoznam.item(i) for i in range(zoznam.count())
                  if zoznam.item(i).data(dlg._ROLA) is not None)
    riadok.setSelected(True)

    dlg._nastav(novinky.ZAUJIMAVE)

    kluce, stav, albumy = zapisy[-1]
    assert (kluce, stav) == (["grievance|occult encryptions"], novinky.ZAUJIMAVE)
    assert albumy["grievance|occult encryptions"].kapela == "Grievance"
    assert z.stav("grievance|occult encryptions") == novinky.ZAUJIMAVE
    assert pocty(dlg)[0] == "Tento týždeň (0)" and pocty(dlg)[2] == "Zaujímavé (1)"
