"""Testy pre spankove zoznamy (spanok.m3u / spanok2.m3u) a tlacidla za nimi.

Standalone (pytest v tomto prostredi je rozbity):
    python tests/test_spanky.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from music_player import spanky  # noqa: E402
from music_player.player_controller import PlayerController  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _TempList:
    """Presmeruje oba M3U zoznamy do docasneho priecinka a vyrobi fake skladby.

    `nechat_v_playliste` sa tu tiez prebija — inak by testy citali skutocny
    config.txt vyvojara a vysledok by zavisel od jeho nastavenia.
    """

    def __init__(self, track_count: int, nechat: dict[str, bool] | None = None) -> None:
        # ignore_cleanup_errors: QMediaPlayer moze mat fake .mp3 este otvoreny
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)
        self.paths = {
            spanky.SPANOK: self.dir / "spanok.m3u",
            spanky.SPANOK2: self.dir / "spanok2.m3u",
        }
        self.tracks = []
        for i in range(track_count):
            track = self.dir / f"skladba{i + 1}.mp3"
            track.write_bytes(b"")
            self.tracks.append(str(track.resolve()))

        self._nechat = nechat or {}
        self._orig_path = spanky.playlist_path
        self._orig_nechat = spanky.nechat_v_playliste
        spanky.playlist_path = lambda ktory: self.paths[ktory]
        spanky.nechat_v_playliste = lambda ktory: self._nechat.get(ktory, False)

    def other_track(self, name: str) -> str:
        """Skladba, ktora do spankoveho zoznamu nepatri (bezny playlist)."""
        path = self.dir / name
        path.write_bytes(b"")
        return str(path.resolve())

    def write(self, ktory: str, lines: list[str]) -> None:
        self.paths[ktory].write_text(
            "#EXTM3U\n" + "\n".join(lines) + "\n", encoding="utf-8"
        )

    def close(self) -> None:
        spanky.playlist_path = self._orig_path
        spanky.nechat_v_playliste = self._orig_nechat
        self._tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _finish_playlist(controller: PlayerController) -> None:
    """Simuluje dohratie poslednej skladby playlistu."""
    controller.current_index = len(controller.playlist) - 1
    controller._handle_end_of_track()


# ── zoznam v subore ───────────────────────────────────────────────────────────
def test_load_splits_found_and_missing():
    with _TempList(2) as t:
        t.write(spanky.SPANOK2, [t.tracks[0], str(t.dir / "neexistuje.mp3"), t.tracks[1]])
        z = spanky.load(spanky.SPANOK2)
        assert z.tracks == [t.tracks[0], t.tracks[1]], z.tracks
        assert len(z.missing) == 1 and z.missing[0].endswith("neexistuje.mp3"), z.missing


def test_save_and_load_roundtrip():
    with _TempList(3) as t:
        spanky.save(spanky.SPANOK, t.tracks)
        assert spanky.load(spanky.SPANOK).tracks == t.tracks


def test_append_skips_duplicates():
    with _TempList(3) as t:
        spanky.save(spanky.SPANOK2, t.tracks[:2])
        added, _ = spanky.append(spanky.SPANOK2, [t.tracks[0], t.tracks[2]])
        assert added == 1, added
        assert spanky.load(spanky.SPANOK2).tracks == t.tracks


def test_lists_are_independent():
    """Dva zoznamy, dva subory — zapis do jedneho druhy nezmeni."""
    with _TempList(4) as t:
        spanky.save(spanky.SPANOK, t.tracks[:2])
        spanky.save(spanky.SPANOK2, t.tracks[2:])
        assert spanky.load(spanky.SPANOK).tracks == t.tracks[:2]
        assert spanky.load(spanky.SPANOK2).tracks == t.tracks[2:]


def test_old_restore_marker_is_ignored():
    """Stara znacka #SPANOK2-VRATIT-PLAYLIST je uz len komentar."""
    with _TempList(1) as t:
        t.write(spanky.SPANOK2, ["#SPANOK2-VRATIT-PLAYLIST=nie", t.tracks[0]])
        z = spanky.load(spanky.SPANOK2)
        assert z.tracks == [t.tracks[0]], z.tracks
        assert z.missing == [], z.missing


# ── tlacidla ──────────────────────────────────────────────────────────────────
def test_start_appends_and_plays():
    with _TempList(6) as t:
        spanky.save(spanky.SPANOK2, t.tracks)
        c = PlayerController()
        c.add_paths([t.other_track("existujuca.mp3")])
        index, missing = c.start_spanok(spanky.SPANOK2)
        assert missing == [], missing
        assert index == 1, index
        assert c.current_index == 1, c.current_index
        assert len(c.playlist) == 7, len(c.playlist)
        assert [track.path for track in c.playlist[1:]] == t.tracks


def test_start_twice_does_not_duplicate():
    """Jadro poistky: druhe stlacenie uz nic nepridava."""
    with _TempList(4) as t:
        spanky.save(spanky.SPANOK, t.tracks)
        c = PlayerController()
        first, _ = c.start_spanok(spanky.SPANOK)
        second, _ = c.start_spanok(spanky.SPANOK)
        assert first == 0 and second == 0, (first, second)
        assert len(c.playlist) == 4, len(c.playlist)


def test_start_does_not_duplicate_leftover_from_previous_run():
    """Zvysok z minula (cistenie nedobehlo) sa tiez rozpozna a neprida znova."""
    with _TempList(3) as t:
        spanky.save(spanky.SPANOK, t.tracks)
        c = PlayerController()
        own = [t.other_track("moja1.mp3")]
        c.add_paths(own + t.tracks)          # taky playlist ostal z minula
        index, _ = c.start_spanok(spanky.SPANOK)
        assert index == 1, index
        assert len(c.playlist) == 4, len(c.playlist)


def test_spanok_without_list_falls_back_to_tail_jump():
    """Prazdny spanok.m3u = povodne spravanie, skok na tretiu od konca."""
    with _TempList(0) as t:
        c = PlayerController()
        c.add_paths([t.other_track(f"moja{i}.mp3") for i in range(5)])
        index, missing = c.start_spanok(spanky.SPANOK)
        assert index == 2, index
        assert missing == [], missing
        assert len(c.playlist) == 5, len(c.playlist)


def test_spanok2_without_list_reports_empty():
    """Spanok 2 zalohu nema — bez zoznamu nema co hrat."""
    with _TempList(0):
        messages = []
        c = PlayerController()
        c.message_emitted.connect(messages.append)
        index, missing = c.start_spanok(spanky.SPANOK2)
        assert index == -1, index
        assert missing == [], missing
        assert messages and "nie je zadefinovan" in messages[-1], messages


def test_plays_rest_when_some_files_missing():
    with _TempList(3) as t:
        t.write(spanky.SPANOK2, [t.tracks[0], str(t.dir / "prec.mp3"), t.tracks[1], t.tracks[2]])
        c = PlayerController()
        index, missing = c.start_spanok(spanky.SPANOK2)
        assert index == 0, index
        assert len(missing) == 1, missing
        assert len(c.playlist) == 3, len(c.playlist)


# ── cistenie pri ukonceni ─────────────────────────────────────────────────────
def test_playlist_returns_on_exit():
    with _TempList(3) as t:
        spanky.save(spanky.SPANOK2, t.tracks)
        c = PlayerController()
        own = [t.other_track("moja1.mp3"), t.other_track("moja2.mp3")]
        c.add_paths(own)
        c.navigate_to_track(1)
        restored = []
        c.playlist_restored.connect(lambda: restored.append(True))

        c.start_spanok(spanky.SPANOK2)
        assert len(c.playlist) == 5, len(c.playlist)

        c.restore_spanok_lists()
        assert [track.path for track in c.playlist] == own, c.playlist
        assert c.current_index == 1, c.current_index
        assert restored == [True], restored


def test_playlist_survives_end_of_playlist():
    """Dohratie playlistu uz playlist NEVRACIA — cisti sa az pri ukonceni."""
    with _TempList(2) as t:
        spanky.save(spanky.SPANOK2, t.tracks)
        c = PlayerController()
        c.add_paths([t.other_track("moja1.mp3")])
        c.start_spanok(spanky.SPANOK2)
        _finish_playlist(c)
        assert len(c.playlist) == 3, len(c.playlist)


def test_keeps_tracks_when_config_says_so():
    with _TempList(3, nechat={spanky.SPANOK2: True}) as t:
        spanky.save(spanky.SPANOK2, t.tracks)
        c = PlayerController()
        own = [t.other_track("moja1.mp3")]
        c.add_paths(own)
        c.start_spanok(spanky.SPANOK2)
        c.restore_spanok_lists()
        assert len(c.playlist) == 4, len(c.playlist)
        assert [track.path for track in c.playlist[1:]] == t.tracks


def test_restore_leaves_playlist_alone_when_tail_changed():
    with _TempList(2) as t:
        spanky.save(spanky.SPANOK2, t.tracks)
        c = PlayerController()
        c.add_paths([t.other_track("moja1.mp3")])
        c.start_spanok(spanky.SPANOK2)
        # Pouzivatel medzitym nieco pridal na koniec — chvost uz nesedi.
        c.add_paths([t.other_track("pribudla.mp3")])
        c.restore_spanok_lists()
        assert len(c.playlist) == 4, len(c.playlist)


def test_both_lists_unwind_in_reverse_order():
    """Stlacene obe tlacidla za sebou — pri ukonceni musia zmiznut obe."""
    with _TempList(4) as t:
        spanky.save(spanky.SPANOK, t.tracks[:2])
        spanky.save(spanky.SPANOK2, t.tracks[2:])
        c = PlayerController()
        own = [t.other_track("moja1.mp3")]
        c.add_paths(own)
        c.start_spanok(spanky.SPANOK)
        c.start_spanok(spanky.SPANOK2)
        assert len(c.playlist) == 5, len(c.playlist)
        c.restore_spanok_lists()
        assert [track.path for track in c.playlist] == own, c.playlist


def test_restore_is_idempotent():
    """Druhe zavolanie uz nema co robit a playlist nesmie okresat."""
    with _TempList(2) as t:
        spanky.save(spanky.SPANOK, t.tracks)
        c = PlayerController()
        own = [t.other_track("moja1.mp3")]
        c.add_paths(own)
        c.start_spanok(spanky.SPANOK)
        c.restore_spanok_lists()
        c.restore_spanok_lists()
        assert [track.path for track in c.playlist] == own, c.playlist


# ── uspanie po skonceni ───────────────────────────────────────────────────────
def test_power_action_still_fires_with_full_playlist():
    """Uspanie sa deje po dohrati — a playlist je vtedy este cely."""
    with _TempList(2) as t:
        spanky.save(spanky.SPANOK2, t.tracks)
        from music_player import player_controller as pc

        fired = []
        orig = pc.sleep_windows
        pc.sleep_windows = lambda: fired.append(len(c.playlist))
        try:
            c = PlayerController()
            c.sleep_when_playlist_ends = True
            c.add_paths([t.other_track("moja1.mp3")])
            c.start_spanok(spanky.SPANOK2)
            _finish_playlist(c)
        finally:
            pc.sleep_windows = orig
        assert fired == [3], fired


def test_empty_playlist_before_spanok_still_sleeps():
    with _TempList(2) as t:
        spanky.save(spanky.SPANOK2, t.tracks)
        from music_player import player_controller as pc

        fired = []
        orig = pc.sleep_windows
        pc.sleep_windows = lambda: fired.append(True)
        try:
            c = PlayerController()
            c.sleep_when_playlist_ends = True
            c.start_spanok(spanky.SPANOK2)
            _finish_playlist(c)
        finally:
            pc.sleep_windows = orig
        assert fired == [True], fired


# ── dialkove ovladanie ────────────────────────────────────────────────────────
def test_remote_sleep2_action_starts_the_list():
    with _TempList(2) as t:
        spanky.save(spanky.SPANOK2, t.tracks)
        c = PlayerController()
        c.handle_remote_command("sleep2", {})
        assert [track.path for track in c.playlist] == t.tracks, c.playlist


def test_remote_spanok_action_starts_the_other_list():
    with _TempList(2) as t:
        spanky.save(spanky.SPANOK, t.tracks)
        c = PlayerController()
        c.handle_remote_command("spanok", {})
        assert [track.path for track in c.playlist] == t.tracks, c.playlist


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
