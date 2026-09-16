"""Testy filtra zanrov na strane prehravaca.

Sken posiela do zoznamu aj to, co podla zanru zahodil — filtruje sa az tu.
Vdaka tomu sa pridanie zanru prejavi hned; keby prehravac dostaval len to, co
preslo, „pridaj doom" by nemalo co ukazat.
"""

from __future__ import annotations

from music_player import novinky, zanre


def a(kluc, styl="", **extra):
    return novinky.Album(kluc=kluc, kapela=kluc.split("|")[0],
                         album=kluc.split("|")[-1], styl=styl, **extra)


def zoznam(albumy):
    return novinky.Zoznam(albumy=albumy,
                          zalozky={"tyzden": [x.kluc for x in albumy]})


def test_ciste_zakazany_zaner_vypadne():
    z = zoznam([a("sabaton|p", "Power Metal"), a("morbid|c", "Death Metal")])
    assert [x.kapela for x in z.pre_zalozku("tyzden")] == ["morbid"]


def test_zmiesany_zaner_prejde():
    # Rozhoduje slovo „cisty": len co je v style povolene slovo, vydanie prejde.
    z = zoznam([a("x|y", "Death Metal/Thrash Metal")])
    assert len(z.pre_zalozku("tyzden")) == 1
    assert z.posudok(z.albumy[0])[0] == zanre.PRESLO


def test_pridanie_zanru_ho_hned_zviditelni():
    z = zoznam([a("doomer|g", "Funeral Doom")])
    assert z.posudok(z.albumy[0])[0] == zanre.NEZARADENE

    z.povolene = z.povolene + ["doom"]

    assert z.posudok(z.albumy[0])[0] == zanre.PRESLO


def test_odobranie_zanru_album_schova_medzi_nezaradene():
    # Nezmizne uplne: pod ciarou ostane aj s dovodom, nech je vidiet, co filter
    # spravil. Tichá eliminácia je to, comu sa projekt vyhýba.
    z = zoznam([a("morbid|c", "Death Metal")])
    z.povolene = [w for w in z.povolene if w != "death"]

    vysledok, dovod = z.posudok(z.albumy[0])

    assert vysledok == zanre.NEZARADENE
    assert "nesedí" in dovod
    assert len(z.pre_zalozku("tyzden")) == 1


def test_bez_stylu_je_vzdy_nezaradene():
    z = zoznam([a("tulip|f", "")])
    assert z.posudok(z.albumy[0]) == (zanre.NEZARADENE, "MA neuvádza štýl")


def test_rozober_vrati_predvolby_pri_rozbitom_subore():
    # Prazdny `povolene` by znamenal „neprejde nic" — teda prazdne okno bez
    # vysvetlenia. Radsej predvolby nez ticho vypnuty filter.
    for text in ("", "{", "[]", '{"povolene": []}', '{"povolene": "death"}'):
        povolene, zakazane = zanre.rozober(text)
        assert povolene == zanre.POVOLENE, text
        assert zakazane == zanre.ZAKAZANE, text


def test_rozober_prijme_vlastne_slova():
    povolene, zakazane = zanre.rozober('{"povolene": ["Doom", " sludge "], "zakazane": ["pop"]}')
    assert povolene == ["doom", "sludge"]
    assert zakazane == ["pop"]


def test_slova_z_textoveho_pola():
    assert zanre.zo_zoznamu("Death\n black ,grind\n\ndeath") == ["death", "black", "grind"]


def test_slova_do_textoveho_pola():
    assert zanre.do_zoznamu(["death", "black"]) == "death\nblack"


def test_zloz_a_rozober_sa_vratia_rovnake():
    povolene, zakazane = zanre.rozober(zanre.zloz(["doom"], ["pop"]))
    assert (povolene, zakazane) == (["doom"], ["pop"])
