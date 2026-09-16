"""Testy pre dohladanie nazvu na Metal Archives.

Do siete sa nechodi — `diskografia` sa podvrhne. Testuje sa to, co je na tom
skutocne rozhodovanie: ktore mena kapely sa skusaju a v akom poradi.
"""

from __future__ import annotations

import pytest

from music_player import nazvy_ma

DISKOGRAFIE = {
    "blind guardian": [("Blind Guardian", "Somewhere Far Beyond"),
                       ("Blind Guardian", "Nightfall in Middle-Earth")],
    "dysphorectomy": [("Dysphorectomy", "Dysphorectomy"),
                      ("Dysphorectomy", "Demo 2024"),
                      ("Dysphorectomy", "Forever")],
    "behemoth": [("Behemoth", "I, Scvlptor"), ("Behemoth", "Satanica")],
    # Kratsi prefix, ktory na MA tiez nieco vrati — nesmie prebit dlhsi.
    "blind": [("Blind Illusion", "The Sane Asylum")],
}


@pytest.fixture(autouse=True)
def bez_siete(monkeypatch):
    volania: list[str] = []

    def falosna(kapela: str):
        volania.append(kapela)
        return DISKOGRAFIE.get(kapela.strip().casefold(), [])

    monkeypatch.setattr(nazvy_ma, "diskografia", falosna)
    # Prazdna konfiguracia = predvolene zapnute; test vypnutia si ju prepise.
    monkeypatch.setattr("music_player.config_loader.load_config", lambda: {})
    return volania


def test_najde_album_aj_s_menom_skupiny_na_konci(bez_siete):
    najdene = nazvy_ma.dohladaj("Dysphorectomy-Forever-2026-GRP")
    assert najdene.text == "Dysphorectomy - Forever - 2026"


def test_vracia_zapis_z_ma_nie_zo_suboru(bez_siete):
    """MA pozna spravnu interpunkciu — `I-Scvlptor` je v priecinku, nie na MA."""
    assert nazvy_ma.dohladaj("Behemoth-I-Scvlptor-2026").text == "Behemoth - I, Scvlptor - 2026"


def test_dlhsie_meno_kapely_ma_prednost(bez_siete):
    """Skusa sa od najdlhsieho: `Blind Guardian` musi vyhrat nad `Blind`."""
    najdene = nazvy_ma.dohladaj("Blind-Guardian-Nightfall-in-Middle-Earth-1998")
    assert najdene.interpret == "Blind Guardian"
    assert bez_siete[0].startswith("blind guardian")


def test_ked_sa_nenajde_nic_vrati_none(bez_siete):
    """Rozbali sa to potom pod povodnym nazvom — tipovat sa nema."""
    assert nazvy_ma.dohladaj("Blind-Guardian-Somewhere-2026-GRP") is None
    assert nazvy_ma.dohladaj("uplne-vymysleny-nazov-2026-XYZ") is None


def test_kratky_nazov_sa_ani_neskusa(bez_siete):
    assert nazvy_ma.dohladaj("Album") is None
    assert nazvy_ma.dohladaj("") is None
    assert bez_siete == []


def test_pocet_hladani_je_ohraniceny(bez_siete):
    """Kazde hladanie je dopyt na MA s odstupom 1,5 s — nesmie ich byt lubovolne."""
    nazvy_ma.dohladaj("a-b-c-d-e-f-g-h-i-j-2026")
    assert len(bez_siete) <= nazvy_ma.MAX_KANDIDATOV


def test_da_sa_vypnut(monkeypatch):
    monkeypatch.setattr("music_player.config_loader.load_config",
                        lambda: {"NAZVY_MA": "nie"})
    assert nazvy_ma.zapnute() is False
    assert nazvy_ma.dohladaj("Dysphorectomy-Forever-2026-GRP") is None
