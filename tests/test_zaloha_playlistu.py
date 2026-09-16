"""Testy zalohy playlistu na NAS.

Kontroluju to, co sa da pokazit ticho: zaloha, ktora sa zapisuje pri kazdom
starte (a priecinok potom rastie), zaloha prazdnym playlistom (prepisala by
historiu prave vtedy, ked je najviac potrebna) a upratovanie, ktore by zmazalo
aj cudzie subory. Sietovy disk sa nahradza obycajnym priecinkom — appka na nom
robi to iste.

Standalone (bez pytestu):
    python tests/test_zaloha_playlistu.py
"""
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_player.models import Track  # noqa: E402
from music_player import zaloha_playlistu as zp  # noqa: E402

# Testy nesmu zavisiet od config.txt na tomto stroji: ked ma clovek zalohu
# vypnutu, zalohuj() by vratila "vypnute" a vsetko nizsie by "preslo"
# naprazdno. Samotne citanie konfiguraku sa testuje inde (zapnuta()).
zp.zapnuta = lambda: True


def _track(cesta: str, nazov: str = "", dlzka_ms: int = 0) -> Track:
    return Track(path=cesta, title=nazov or Path(cesta).stem, artist="Kapela",
                 duration_ms=dlzka_ms)


def _playlist(*mena: str) -> list[Track]:
    return [_track(rf"C:\hudba\{m}.mp3", m, 200_000) for m in mena]


def _cas(minuta: int) -> datetime:
    return datetime(2026, 9, 2, 18, 0, 0) + timedelta(minutes=minuta)


def _zalohy(kam: Path) -> list[Path]:
    return sorted(kam.glob(zp.VZOR_MENA))


def test_prva_zaloha_zapise_subor(tmp_path: Path) -> None:
    v = zp.zalohuj(_playlist("a", "b"), kam=tmp_path, teraz=_cas(0), nechat=5)
    assert v.stav == "zapisane", v
    assert v.pocet == 2
    assert v.subor is not None and v.subor.exists()
    assert v.subor.name == "playlist-2026-09-02-180000.m3u8"
    obsah = v.subor.read_text(encoding="utf-8")
    assert zp.cesty_z_textu(obsah) == [r"C:\hudba\a.mp3", r"C:\hudba\b.mp3"]
    # Vysvetlenie pre cloveka vznikne spolu s prvou zalohou.
    assert (tmp_path / zp.README).exists()


def test_nezmeneny_playlist_nezapisuje(tmp_path: Path) -> None:
    """Kazdovecerne spustenie bez zasahu do playlistu nesmie priecinok nafukovat."""
    zp.zalohuj(_playlist("a", "b"), kam=tmp_path, teraz=_cas(0), nechat=5)
    v = zp.zalohuj(_playlist("a", "b"), kam=tmp_path, teraz=_cas(1), nechat=5)
    assert v.stav == "nezmenene", v
    assert len(_zalohy(tmp_path)) == 1


def test_ina_hlavicka_nie_je_zmena(tmp_path: Path) -> None:
    """Rozdiel v case ani v prave hrajucej skladbe zalohu nespusti."""
    zp.zalohuj(_playlist("a"), kam=tmp_path, teraz=_cas(0), hraje=_track(r"C:\hudba\a.mp3"),
               nechat=5)
    v = zp.zalohuj(_playlist("a"), kam=tmp_path, teraz=_cas(30),
                   hraje=_track(r"C:\hudba\z.mp3"), nechat=5)
    assert v.stav == "nezmenene", v


def test_zmeneny_playlist_zapise_dalsi_subor(tmp_path: Path) -> None:
    zp.zalohuj(_playlist("a", "b"), kam=tmp_path, teraz=_cas(0), nechat=5)
    v = zp.zalohuj(_playlist("a", "b", "c"), kam=tmp_path, teraz=_cas(1), nechat=5)
    assert v.stav == "zapisane", v
    assert len(_zalohy(tmp_path)) == 2


def test_prehodene_poradie_je_zmena(tmp_path: Path) -> None:
    """Poradie je sucast playlistu, nie detail — inak by sa prehadzanie stratilo."""
    zp.zalohuj(_playlist("a", "b"), kam=tmp_path, teraz=_cas(0), nechat=5)
    v = zp.zalohuj(_playlist("b", "a"), kam=tmp_path, teraz=_cas(1), nechat=5)
    assert v.stav == "zapisane", v


def test_ina_velkost_pismen_nie_je_zmena(tmp_path: Path) -> None:
    zp.zalohuj([_track(r"C:\hudba\a.mp3")], kam=tmp_path, teraz=_cas(0), nechat=5)
    v = zp.zalohuj([_track(r"c:\HUDBA\A.mp3")], kam=tmp_path, teraz=_cas(1), nechat=5)
    assert v.stav == "nezmenene", v


def test_prazdny_playlist_sa_nezalohuje(tmp_path: Path) -> None:
    """Cerstva instalacia (alebo havaria) nesmie prepisat historiu prazdnom."""
    zp.zalohuj(_playlist("a"), kam=tmp_path, teraz=_cas(0), nechat=5)
    v = zp.zalohuj([], kam=tmp_path, teraz=_cas(1), nechat=5)
    assert v.stav == "prazdny", v
    assert len(_zalohy(tmp_path)) == 1


def test_drzi_len_poslednych_n(tmp_path: Path) -> None:
    for i in range(5):
        v = zp.zalohuj(_playlist(*[str(x) for x in range(i + 1)]),
                       kam=tmp_path, teraz=_cas(i), nechat=3)
        assert v.stav == "zapisane", v
    zostali = [p.name for p in _zalohy(tmp_path)]
    assert len(zostali) == 3
    assert zostali == sorted(zostali)[-3:]
    assert "playlist-2026-09-02-180000.m3u8" not in zostali


def test_upratovanie_sa_nedotkne_cudzich_suborov(tmp_path: Path) -> None:
    (tmp_path / "moje-poznamky.txt").write_text("nemazat", encoding="utf-8")
    (tmp_path / "playlist-rucna-kopia.m3u").write_text("nemazat", encoding="utf-8")
    for i in range(4):
        zp.zalohuj(_playlist(*[str(x) for x in range(i + 1)]),
                   kam=tmp_path, teraz=_cas(i), nechat=1)
    assert (tmp_path / "moje-poznamky.txt").exists()
    assert (tmp_path / "playlist-rucna-kopia.m3u").exists()
    assert len(_zalohy(tmp_path)) == 1


def test_nedostupny_ciel_je_ticho(tmp_path: Path) -> None:
    """Mimo domu sa appka o NAS-e nesmie ozvat — a uz vobec nie vynimkou."""
    # Subor namiesto priecinka: mkdir na nom zlyha rovnako ako nedostupny share.
    prekazka = tmp_path / "nie-je-priecinok"
    prekazka.write_text("x", encoding="utf-8")
    v = zp.zalohuj(_playlist("a"), kam=prekazka / "zalohy", teraz=_cas(0), nechat=5)
    assert v.stav == "nedostupne", v
    assert v.sprava == ""


def test_m3u_sa_da_precitat_spat(tmp_path: Path) -> None:
    """Zaloha musi ist pretiahnut do okna — teda ju musi zobrat parser appky."""
    from music_player.models import collect_audio_paths

    hudba = tmp_path / "hudba"
    hudba.mkdir()
    skladby = []
    for meno in ("prva", "druha"):
        subor = hudba / f"{meno}.mp3"
        subor.write_bytes(b"nie je to naozaj mp3, staci pripona")
        skladby.append(_track(str(subor), meno, 123_000))

    kam = tmp_path / "zalohy"
    v = zp.zalohuj(skladby, kam=kam, teraz=_cas(0), nechat=5)
    assert v.stav == "zapisane", v
    nacitane = collect_audio_paths([str(v.subor)])
    assert nacitane == [str(s.path) for s in skladby]


def test_meno_pocitaca_je_pouzitelne_ako_priecinok() -> None:
    meno = zp.meno_pocitaca()
    assert meno
    assert not set(meno) & set('<>:"/\\|?*')


def _spusti() -> int:
    testy = [(m, f) for m, f in sorted(globals().items())
             if m.startswith("test_") and callable(f)]
    zlyhalo = 0
    for meno, funkcia in testy:
        docasny = Path(tempfile.mkdtemp(prefix="zaloha-test-"))
        try:
            if funkcia.__code__.co_argcount:
                funkcia(docasny)
            else:
                funkcia()
            print(f"  [OK] {meno}")
        except AssertionError as exc:
            print(f"  [ZLE] {meno}: {exc}")
            zlyhalo += 1
        finally:
            shutil.rmtree(docasny, ignore_errors=True)
    print(f"\n{len(testy) - zlyhalo}/{len(testy)} preslo.")
    return 1 if zlyhalo else 0


if __name__ == "__main__":
    raise SystemExit(_spusti())
