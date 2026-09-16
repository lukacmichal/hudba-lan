"""Logika tlacidla "Prelozit text" v okne prehravaca.

`MainWindow` sa v testoch nestavia (chce controller, state store, server aj
system tray), preto sa metody volaju ako nezviazane, na podvrhnutom `self`.
Testuje sa presne to, co sa da rozbit bez toho, aby si to clovek vsimol:

  1. prepinac originalu a prekladu tam a spat,
  2. druhy klik na tu istu skladbu uz NEIDE na siet,
  3. preklad, ktory dorazi po preskoceni inam, sa nezobrazi, ale ULOZI
     (kvota je uz minuta — zahodit ho by znamenalo zaplatit ho dvakrat),
  4. pri zobrazenom preklade je hover nad slovom vypnuty (necha kvotu tak).

Standalone:
    python tests/test_translate_button.py
"""
import os
import sys
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_player import disk_cache, ui  # noqa: E402
from music_player.translator import Preklad  # noqa: E402


class _Tlacidlo:
    def __init__(self):
        self.text = ""
        self.enabled = False

    def setText(self, t):
        self.text = t

    def setEnabled(self, b):
        self.enabled = b


class _Text:
    def __init__(self):
        self.text = ""
        self.hover = True
        self._api_key = "test:fx"

    def setText(self, t):
        self.text = t

    def set_hover_enabled(self, b):
        self.hover = b


class _Skladba:
    def __init__(self, path="C:\\hudba\\kapela\\01.mp3", title="Song"):
        self.path = path
        self.title = title


class _Controller:
    def __init__(self, track):
        self._track = track

    def current_track(self):
        return self._track


class _Okno:
    """Duck-typed nahrada za MainWindow — len polia, ktore preklad pouziva."""

    def __init__(self, track):
        self.translate_button = _Tlacidlo()
        self.lyrics_edit = _Text()
        self.controller = _Controller(track)
        self._lyrics_track_path = track.path
        self._lyrics_original = ""
        self._lyrics_translation = ""
        self._showing_translation = False
        self._translation_running = False
        self.spustene_preklady = []

    # Metody z MainWindow pod ICH vlastnymi menami — volaju sa navzajom, takze
    # pod aliasom by sa nenasli.
    _reset_translation_state = ui.MainWindow._reset_translation_state
    _on_translate_clicked = ui.MainWindow._on_translate_clicked
    _show_translation = ui.MainWindow._show_translation
    _on_translation_loaded = ui.MainWindow._on_translation_loaded

    def _translate_lyrics_async(self, track, text):
        # Namiesto vlakna a siete si len zapisem, ze sa to spustilo.
        self.spustene_preklady.append((track.path, text))


@contextmanager
def bez_disku(monkey: dict):
    """Diskova cache nahradena slovnikom — test sa nedotkne realnych suborov.

    Restore je v `finally`: bez neho by pod pytestom ostala podvrhnuta cache
    aj pre ostatne testovacie moduly v tom istom behu.
    """
    povodne = (disk_cache.read_cached_translation, disk_cache.write_cached_translation)

    def _zapis(p, t, text):
        monkey[(p, t)] = text

    disk_cache.read_cached_translation = lambda p, t: monkey.get((p, t))
    disk_cache.write_cached_translation = _zapis
    try:
        yield monkey
    finally:
        disk_cache.read_cached_translation, disk_cache.write_cached_translation = povodne


def test_prepinac_original_a_preklad():
    monkey: dict = {}
    with bez_disku(monkey):
        track = _Skladba()
        w = _Okno(track)
        w._reset_translation_state()
        w._lyrics_original = "Original text"
        w._lyrics_translation = "Slovensky text"

        w._on_translate_clicked()  # preklad uz mame v pamati -> ukaze sa hned, bez siete
        assert w.lyrics_edit.text == "Slovensky text"
        assert w._showing_translation is True
        assert w.lyrics_edit.hover is False, "nad slovencinou sa nema prekladat po slovach"
        assert w.translate_button.text == "↩ Originál"
        assert w.spustene_preklady == [], "preklad v pamati nesmie ist na siet"

        w._on_translate_clicked()  # spat na original
        assert w.lyrics_edit.text == "Original text"
        assert w._showing_translation is False
        assert w.lyrics_edit.hover is True, "nad originalom ma hover zase fungovat"
        assert w.translate_button.text == "🌐 Preložiť text"
        print("OK  prepinac original <-> preklad")


def test_druhy_klik_berie_preklad_z_disku():
    track = _Skladba()
    monkey = {(track.path, track.title): "Preklad z disku"}
    with bez_disku(monkey):
        w = _Okno(track)
        w._reset_translation_state()
        w._lyrics_original = "Original text"

        w._on_translate_clicked()

        assert w.lyrics_edit.text == "Preklad z disku"
        assert w.spustene_preklady == [], "co je na disku, sa uz z kvoty DeepL neplati"
        print("OK  preklad z disku nemini kvotu")


def test_prvy_klik_spusti_preklad():
    monkey: dict = {}
    with bez_disku(monkey):
        track = _Skladba()
        w = _Okno(track)
        w._reset_translation_state()
        w._lyrics_original = "Original text"

        w._on_translate_clicked()

        assert w.spustene_preklady == [(track.path, "Original text")]
        assert w._translation_running is True
        assert w.translate_button.enabled is False, "pocas prekladu sa neda klikat znova"
        assert w.translate_button.text == "Prekladám …"
        print("OK  prvy klik spusti preklad a zamkne tlacidlo")


def test_preklad_preskocenej_skladby_sa_nezobrazi_ale_ulozi():
    """Kvota je uz minuta, takze preklad sa ma ulozit aj tak.

    Zahodit ho preto, ze pouzivatel medzitym preskocil inam, by znamenalo
    zaplatit ho pri dalsom klepnuti druhykrat.
    """
    monkey: dict = {}
    with bez_disku(monkey):
        prva = _Skladba(path=r"C:\hudba\kapela\01.mp3", title="Song")
        w = _Okno(prva)
        w._reset_translation_state()
        w._lyrics_original = "Original text"
        w._translation_running = True

        # Medzitym pouzivatel preskocil na inu skladbu.
        w._lyrics_track_path = r"C:\hudba\kapela\02.mp3"
        w._on_translation_loaded(
            Preklad(text="Preklad prvej skladby"), prva.path, prva.title
        )

        assert w.lyrics_edit.text == "", "preklad inej skladby sa nesmie zobrazit"
        assert w._lyrics_translation == ""
        assert monkey[(prva.path, prva.title)] == "Preklad prvej skladby", (
            "zaplateny preklad sa ma ulozit aj ked uz hra ina skladba")
        print("OK  preklad preskocenej skladby sa nezobrazi, ale ulozi")


def test_uspesny_preklad_sa_ulozi_na_disk():
    monkey: dict = {}
    with bez_disku(monkey):
        track = _Skladba()
        w = _Okno(track)
        w._reset_translation_state()
        w._lyrics_original = "Original text"
        w._translation_running = True

        w._on_translation_loaded(Preklad(text="Hotovy preklad"), track.path, track.title)

        assert w.lyrics_edit.text == "Hotovy preklad"
        assert monkey[(track.path, track.title)] == "Hotovy preklad"
        assert w._translation_running is False
        print("OK  hotovy preklad sa zobrazi aj ulozi")


def test_reset_pri_prepnuti_skladby():
    monkey: dict = {}
    with bez_disku(monkey):
        w = _Okno(_Skladba())
        w._lyrics_original = "nieco"
        w._lyrics_translation = "nieco po slovensky"
        w._showing_translation = True
        w.lyrics_edit.hover = False

        w._reset_translation_state()

        assert w._lyrics_original == "" and w._lyrics_translation == ""
        assert w._showing_translation is False
        assert w.lyrics_edit.hover is True
        assert w.translate_button.enabled is False
        assert w.translate_button.text == "🌐 Preložiť text"
        print("OK  prepnutie skladby vycisti stav prekladu")


if __name__ == "__main__":
    test_prepinac_original_a_preklad()
    test_druhy_klik_berie_preklad_z_disku()
    test_prvy_klik_spusti_preklad()
    test_preklad_preskocenej_skladby_sa_nezobrazi_ale_ulozi()
    test_uspesny_preklad_sa_ulozi_na_disk()
    test_reset_pri_prepnuti_skladby()
    print("")
    print("Vsetky testy presli.")
