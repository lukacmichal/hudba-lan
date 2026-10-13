"""Testy pre zalozky v playliste (tlacidlo "Zalozky").

Standalone (pytest v tomto prostredi je rozbity):
    python tests/test_zalozky.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from music_player import persistence  # noqa: E402
from music_player.models import Track  # noqa: E402
from music_player.player_controller import PlayerController  # noqa: E402
from music_player.zalozky import Zalozka, najdi  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Skladby:
    """Docasny priecinok s prazdnymi .mp3 — add_paths chce skutocne subory."""

    def __init__(self, *mena: str) -> None:
        # ignore_cleanup_errors: QMediaPlayer moze mat fake .mp3 este otvoreny
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)
        self.cesty = {}
        for meno in mena:
            self.pridaj(meno)

    def pridaj(self, meno: str) -> str:
        path = self.dir / f"{meno}.mp3"
        path.write_bytes(b"")
        self.cesty[meno] = str(path.resolve())
        return self.cesty[meno]

    def controller(self, *poradie: str) -> PlayerController:
        """Controller s playlistom v danom poradi (mena sa smu opakovat)."""
        c = PlayerController()
        c.playlist = [Track(path=self.cesty[m], title=m) for m in poradie]
        c.current_index = 0
        return c

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()


def _mena(c: PlayerController) -> list[str]:
    return [t.title for t in c.playlist]


# ── hladanie v playliste ──────────────────────────────────────────────────────
def test_najdi_trafi_ulozenu_poziciu():
    assert najdi([r"C:\a.mp3", r"C:\b.mp3"], Zalozka(r"C:\b.mp3", 1)) == 1


def test_najdi_po_posune_berie_najblizsi_vyskyt():
    paths = [r"C:\a.mp3", r"C:\x.mp3", r"C:\a.mp3", r"C:\y.mp3", r"C:\a.mp3"]
    # ulozena pozicia 3 uz na "a" neukazuje; najblizsie je 2 aj 4, plati prvy
    assert najdi(paths, Zalozka(r"C:\a.mp3", 3)) == 2
    assert najdi(paths, Zalozka(r"C:\a.mp3", 4)) == 4


def test_najdi_ignoruje_velkost_pismen():
    assert najdi([r"C:\Hudba\A.mp3"], Zalozka(r"c:\hudba\a.MP3", 0)) == 0


def test_najdi_chybajucu_skladbu_vrati_minus_jedna():
    assert najdi([r"C:\a.mp3"], Zalozka(r"C:\b.mp3", 0)) == -1
    assert najdi([], Zalozka(r"C:\b.mp3", 0)) == -1


# ── pridanie, prehratie, odobratie ────────────────────────────────────────────
def test_pridaj_zalozku_a_druhy_raz_uz_nie():
    with _Skladby("a", "b", "c") as s:
        c = s.controller("a", "b", "c")
        assert c.pridaj_zalozku(1) is True
        assert c.pridaj_zalozku(1) is False
        assert [(Path(z.path).stem, z.index) for z in c.zalozky] == [("b", 1)]
        assert c.riadky_so_zalozkou() == {1}
        assert c.zalozka_na_riadku(1) == 0
        assert c.zalozka_na_riadku(0) == -1


def test_hraj_zalozku_pusti_skladbu_a_playlist_nemeni():
    with _Skladby("a", "b", "c") as s:
        c = s.controller("a", "b", "c")
        c.pridaj_zalozku(1)
        assert c.hraj_zalozku(0) == 1
        assert c.current_index == 1
        assert _mena(c) == ["a", "b", "c"]
        # zalozka po prehrati ostava, kde bola
        assert c.zalozky[0].index == 1
        assert c.hraj_zalozku(0) == 1


def test_hraj_zalozku_bez_skladby_nepusti_nic():
    with _Skladby("a", "b") as s:
        c = s.controller("a", "b")
        c.zalozky = [Zalozka(s.pridaj("inde"), 0)]
        spravy = []
        c.message_emitted.connect(spravy.append)
        assert c.hraj_zalozku(0) == -1
        assert c.current_index == 0
        assert "nie je" in spravy[-1], spravy


def test_hraj_zalozku_mimo_rozsahu():
    with _Skladby("a") as s:
        c = s.controller("a")
        assert c.hraj_zalozku(0) == -1
        assert c.hraj_zalozku(-1) == -1


def test_odober_zalozku():
    with _Skladby("a", "b") as s:
        c = s.controller("a", "b")
        c.pridaj_zalozku(0)
        c.pridaj_zalozku(1)
        c.odober_zalozku(0)
        assert [Path(z.path).stem for z in c.zalozky] == ["b"]
        c.odober_zalozku(5)  # mimo rozsahu nic nerobi
        assert len(c.zalozky) == 1


# ── zalozka ide so skladbou ───────────────────────────────────────────────────
def test_presun_skladby_s_duplicitou_drzi_spravny_vyskyt():
    with _Skladby("a", "b", "c") as s:
        c = s.controller("a", "b", "a", "c")
        druhe_a = c.playlist[2]
        c.pridaj_zalozku(2)
        c.move_indices([2], 0)
        assert c.playlist[0] is druhe_a
        # podla cesty by vysiel najblizsi vyskyt k 2 (index 1), co je ine "a"
        assert c.zalozky[0].index == 0
        assert c.riadky_so_zalozkou() == {0}


def test_vlozenie_nad_zalozku_ju_posunie():
    with _Skladby("a", "b", "c", "novy1", "novy2") as s:
        c = s.controller("a", "b", "c")
        c.pridaj_zalozku(2)
        c.add_paths([s.cesty["novy1"], s.cesty["novy2"]], insert_at=0)
        assert _mena(c)[4] == "c"
        assert c.zalozky[0].index == 4


def test_odstranenie_skladby_nad_zalozkou_ju_posunie():
    with _Skladby("a", "b", "c") as s:
        c = s.controller("a", "b", "c")
        c.pridaj_zalozku(2)
        c.remove_indices([0])
        assert c.zalozky[0].index == 1
        assert c.hraj_zalozku(0) == 1
        assert c.playlist[1].title == "c"


def test_odstranena_skladba_zalozku_nezmaze_a_po_navrate_sa_najde():
    with _Skladby("a", "b", "c") as s:
        c = s.controller("a", "b", "c")
        c.pridaj_zalozku(1)
        c.remove_indices([1])
        assert len(c.zalozky) == 1
        assert c.zalozka_index(c.zalozky[0]) == -1
        assert c.riadky_so_zalozkou() == set()
        c.add_paths([s.cesty["b"]])
        assert c.zalozka_index(c.zalozky[0]) == 2
        assert c.zalozky[0].index == 2


def test_signal_pri_posune_zalozky():
    with _Skladby("a", "b") as s:
        c = s.controller("a", "b")
        c.pridaj_zalozku(1)
        zmeny = []
        c.zalozky_changed.connect(lambda: zmeny.append(True))
        c.move_indices([1], 0)
        assert zmeny, "UI musi vediet prekreslit 🔖"


# ── ulozenie do state.json ────────────────────────────────────────────────────
class _Appdata:
    """Presmeruje %APPDATA% (a tym state.json) do docasneho priecinka."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        return persistence.StateStore()

    def __exit__(self, *exc):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()


def test_zalozky_prezinu_ulozenie_a_nacitanie():
    with _Skladby("a", "b", "c") as s, _Appdata() as store:
        c = s.controller("a", "b", "c")
        c.pridaj_zalozku(2)
        store.save(c.build_state(start_with_windows=False, window_width=800, window_height=600))
        c2 = PlayerController()
        c2.load_state(store.load())
        assert [(z.path, z.index) for z in c2.zalozky] == [(s.cesty["c"], 2)]
        assert c2.riadky_so_zalozkou() == {2}


def test_stary_state_json_bez_zaloziek():
    with _Appdata() as store:
        store.state_file.parent.mkdir(parents=True, exist_ok=True)
        store.state_file.write_text(json.dumps({"playlist": []}), encoding="utf-8")
        assert store.load().zalozky == []


def test_poskodene_zalozky_sa_preskocia():
    with _Appdata() as store:
        store.state_file.parent.mkdir(parents=True, exist_ok=True)
        store.state_file.write_text(json.dumps({
            "playlist": [],
            "zalozky": [{"path": ""}, "nezmysel", {"path": r"C:\a.mp3", "index": "x"},
                        {"path": r"C:\b.mp3", "index": 3}],
        }), encoding="utf-8")
        zalozky = store.load().zalozky
        assert [(z.path, z.index) for z in zalozky] == [(r"C:\a.mp3", -1), (r"C:\b.mp3", 3)]


def test_zalozky_ako_nie_zoznam_sa_ignoruju():
    with _Appdata() as store:
        store.state_file.parent.mkdir(parents=True, exist_ok=True)
        store.state_file.write_text(json.dumps({"zalozky": {"path": "x"}}), encoding="utf-8")
        assert store.load().zalozky == []


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {type(exc).__name__}: {exc}")
    sys.exit(1 if failures else 0)
