"""Testy pre hromadne rozbalenie archivov z Downloads."""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from music_player import downloads_import as di


def _make_zip(path: Path, names: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, b"x" * 16)
    return path


def test_target_dir_uses_year_with_underscore():
    assert di.target_dir(r"C:\data\mp3", 2027) == Path(r"C:\data\mp3\_2027")
    assert di.target_dir(r"C:\data\mp3", 2025) == Path(r"C:\data\mp3\_2025")
    assert di.target_dir(r"C:\data\mp3").name == f"_{datetime.now().year}"


def test_year_folder():
    assert di.year_folder(2026) == "_2026"
    assert di.year_folder() == f"_{datetime.now().year}"


def test_target_root_prefers_config(monkeypatch):
    monkeypatch.setattr("music_player.config_loader.load_config", lambda: {"MP3_TARGET": r"D:\hudba"})
    assert di.target_root() == Path(r"D:\hudba")
    assert di.target_dir(year=2030) == Path(r"D:\hudba\_2030")


def test_target_root_expands_environment_variables(monkeypatch):
    monkeypatch.setenv("HUDBA_KOREN", r"E:\zbierka")
    monkeypatch.setattr("music_player.config_loader.load_config", lambda: {"MP3_TARGET": "%HUDBA_KOREN%"})
    assert di.target_root() == Path(r"E:\zbierka")


@pytest.mark.parametrize("cfg", [{}, {"MP3_TARGET": ""}, {"MP3_TARGET": "   "}])
def test_target_root_falls_back_when_config_empty(monkeypatch, cfg):
    monkeypatch.setattr("music_player.config_loader.load_config", lambda: cfg)
    assert di.target_root() == di.DEFAULT_TARGET_ROOT


def test_has_audio():
    assert di.has_audio(["Album/01 - Song.MP3"])
    assert di.has_audio(["Album/track.flac"])
    assert not di.has_audio(["Album/cover.jpg", "Album/info.nfo"])


def test_nacitaj_vynecha_archivy_bez_hudby_a_nic_nerozbali(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    with_music = _make_zip(downloads / "album.zip", ["Kapela - Album (2026)/01 - Song.mp3"])
    docs = _make_zip(downloads / "docs.zip", ["readme.txt"])
    (downloads / "notes.txt").write_text("nie archiv", encoding="utf-8")
    root = tmp_path / "mp3"

    nacitanie = di.nacitaj(downloads, root=root)

    assert [n.archive for n in nacitanie.navrhy] == [with_music]
    assert nacitanie.bez_hudby == [docs]
    assert not root.exists()  # nacitanie nic nerozbaluje


def test_nacitaj_navrhne_skupinu_album_a_rok(tmp_path):
    archive = _make_zip(
        tmp_path / "www.stiahnute_Kapela_-_Album_(2026).zip",
        ["Kapela - Album (2026)/01 - Song.mp3", "Kapela - Album (2026)/02 - Song.mp3",
         "Kapela - Album (2026)/cover.jpg"],
    )

    navrh, = di.nacitaj(tmp_path, root=tmp_path / "mp3").navrhy

    assert navrh.surovy == "Kapela - Album (2026)"
    assert (navrh.interpret, navrh.album, navrh.rok) == ("Kapela", "Album", 2026)
    assert navrh.zdroj == di.Z_NAZVU
    assert navrh.skladieb == 2
    assert navrh.velkost == archive.stat().st_size
    assert navrh.nazov == "Kapela - Album - 2026"


def test_nacitaj_plochy_archiv_berie_nazov_archivu(tmp_path):
    _make_zip(tmp_path / "Kapela - Singel.zip", ["01 - Song.mp3", "cover.jpg"])

    navrh, = di.nacitaj(tmp_path, root=tmp_path / "mp3").navrhy

    assert navrh.surovy == "Kapela - Singel"
    assert navrh.nazov == "Kapela - Singel"


#: Skutocna stavba `AVLSNEMBR26-By Samaritianin.rar` z 1. 11. 2026 — obal okolo
#: albumu, rar vypisuje priecinky bez lomky na konci.
_OBAL = [
    "AVLSNEMBR26-By Samaritianin/Avulsed - Nordic Embryogenesis (2026)/01 - Expunging Mortalities.mp3",
    "AVLSNEMBR26-By Samaritianin/Avulsed - Nordic Embryogenesis (2026)/02 - No Canonization.mp3",
    "AVLSNEMBR26-By Samaritianin/Avulsed - Nordic Embryogenesis (2026)/Cover.jpg",
    "AVLSNEMBR26-By Samaritianin/Avulsed - Nordic Embryogenesis (2026)",
    "AVLSNEMBR26-By Samaritianin",
]


def _cesty(mena: list[str]) -> list[tuple[str, ...]]:
    return [tuple(m.split("/")) for m in mena]


def test_subory_z_vypisu_vynecha_priecinky():
    assert di._subory_z_vypisu(_OBAL) == _cesty(_OBAL[:3])
    assert di._subory_z_vypisu(["Album/", "Album/01.mp3"]) == [("Album", "01.mp3")]


@pytest.mark.parametrize(
    "mena, cesta",
    [
        # obal okolo albumu
        (["Obal/Kapela - Album/01.mp3", "Obal/Kapela - Album/cover.jpg"],
         ("Obal", "Kapela - Album")),
        # dva obaly, pri vonkajsom smeti od uploadera
        (["Obal/info.nfo", "Obal/www.stranka.url", "Obal/Vnutri/Kapela - Album/01.mp3"],
         ("Obal", "Vnutri", "Kapela - Album")),
        # smeti v koreni archivu vedla albumu
        (["Kapela - Album/01.mp3", "Stiahnute z.txt"], ("Kapela - Album",)),
        # CD1/CD2 su cast albumu
        (["Kapela - Album/CD1/01.mp3", "Kapela - Album/CD2/01.mp3"], ("Kapela - Album",)),
        (["Kapela - Album/CD1/01.mp3"], ("Kapela - Album",)),
        (["CD1/01.mp3"], ()),
        # cover vedla podpriecinka = album je tu, nie nizsie
        (["Kapela - Album/Skladby/01.mp3", "Kapela - Album/cover.jpg"], ("Kapela - Album",)),
        # dva priecinky navrchu, alebo hudba priamo v koreni
        (["A/01.mp3", "B/01.mp3"], ()),
        (["01.mp3", "cover.jpg"], ()),
        # podpriecinok bez hudby sa neberie
        (["Kapela - Album/01.mp3", "Kapela - Album/Scans/a.jpg"], ("Kapela - Album",)),
        (["Scans/a.jpg", "01.mp3"], ()),
        # stopy z macu
        (["Kapela - Album/01.mp3", "__MACOSX/Kapela - Album/._01.mp3"], ("Kapela - Album",)),
    ],
)
def test_cesta_k_albumu(mena, cesta):
    assert di.cesta_k_albumu(_cesty(mena)) == cesta


def test_nacitaj_a_rozbal_album_v_obale(tmp_path):
    archive = _make_zip(tmp_path / "AVLSNEMBR26-By Samaritianin.zip",
                        _OBAL[:3] + ["AVLSNEMBR26-By Samaritianin/info.nfo"])

    navrh, = di.nacitaj(tmp_path, root=tmp_path / "mp3").navrhy
    outcome = di.extract_archive(archive, tmp_path / "out")

    assert navrh.surovy == "Avulsed - Nordic Embryogenesis (2026)"
    assert navrh.nazov == "Avulsed - Nordic Embryogenesis - 2026"
    assert navrh.skladieb == 2
    assert outcome.status == "ok"
    assert outcome.destination == tmp_path / "out" / "Avulsed - Nordic Embryogenesis - 2026"
    assert sorted(p.name for p in outcome.destination.iterdir()) == [
        "01 - Expunging Mortalities.mp3", "02 - No Canonization.mp3", "Cover.jpg"]
    assert outcome.tracks == 2
    assert not list((tmp_path / "out").glob(".tmp-*"))


def test_rozbalenie_v_obale_pod_nazvom_z_nahladu(tmp_path):
    archive = _make_zip(tmp_path / "x.zip", _OBAL[:3])

    outcome = di.extract_archive(archive, tmp_path / "out", "Avulsed - Nordic Embryogenesis - 2026")

    assert outcome.povodny == "Avulsed - Nordic Embryogenesis (2026)"
    assert (outcome.destination / "Cover.jpg").exists()


def test_nacitaj_nerozumie_nazvu_a_necha_ho_ako_album(tmp_path):
    _make_zip(tmp_path / "x.zip", ["Blind-Guardian-Somewhere-2026-GRP/01.mp3"])

    navrh, = di.nacitaj(tmp_path, root=tmp_path / "mp3").navrhy

    assert navrh.zdroj == di.POVODNY
    assert (navrh.interpret, navrh.album) == ("", "Blind-Guardian-Somewhere-2026-GRP")
    assert navrh.nazov == "Blind-Guardian-Somewhere-2026-GRP"


def test_nacitaj_dohladany_nazov_ma_prednost(tmp_path):
    from music_player.nazvy import Nazov

    _make_zip(tmp_path / "x.zip", ["Blind-Guardian-Somewhere-2026-GRP/01.mp3"])
    videne: list[str] = []

    def dohladat(surovy):
        videne.append(surovy)
        return Nazov("Blind Guardian", "Somewhere", 2026)

    navrh, = di.nacitaj(tmp_path, root=tmp_path / "mp3", dohladat=dohladat).navrhy

    assert videne == ["Blind-Guardian-Somewhere-2026-GRP"]
    assert navrh.zdroj == di.DOHLADANE
    assert navrh.nazov == "Blind Guardian - Somewhere - 2026"


def test_nacitaj_nepyta_sa_do_siete_na_uz_rozbalene(tmp_path):
    from music_player.nazvy import Nazov

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    _make_zip(downloads / "stary.zip", ["Kapela - Stary (2025)/01.mp3"])
    _make_zip(downloads / "povodny.zip", ["Kapela-Povodny-GRP/01.mp3"])
    _make_zip(downloads / "novy.zip", ["Kapela - Novy (2026)/01.mp3"])
    root = tmp_path / "mp3"
    (di.target_dir(root) / "Kapela - Stary - 2025").mkdir(parents=True)
    (di.target_dir(root) / "Kapela-Povodny-GRP").mkdir()
    videne: list[str] = []

    def dohladat(surovy):
        videne.append(surovy)
        return Nazov("Kapela", "Novy", 2026)

    navrhy = di.nacitaj(downloads, root=root, dohladat=dohladat).navrhy

    assert videne == ["Kapela - Novy (2026)"]
    assert [n.nazov for n in navrhy] == [
        "Kapela - Novy - 2026", "Kapela-Povodny-GRP", "Kapela - Stary - 2025"]


def test_nacitaj_prezije_padajuce_dohladanie(tmp_path):
    _make_zip(tmp_path / "x.zip", ["Kapela - Album - 2026/01.mp3"])

    def dohladat(_surovy):
        raise ConnectionError("MA nedostupne")

    navrh, = di.nacitaj(tmp_path, root=tmp_path / "mp3", dohladat=dohladat).navrhy

    assert navrh.zdroj == di.Z_NAZVU
    assert navrh.nazov == "Kapela - Album - 2026"


def test_nacitaj_ukaze_aj_necitatelny_archiv(tmp_path):
    (tmp_path / "rozbite.rar").write_bytes(b"toto nie je archiv")

    navrh, = di.nacitaj(tmp_path, root=tmp_path / "mp3").navrhy

    assert not navrh.citatelny
    assert navrh.chyba
    assert navrh.album == "rozbite"


@pytest.mark.parametrize(
    "vstup, vystup",
    [
        ("Sigh - Hangman's Hymn: Musikalische Exequien - 2007",
         "Sigh - Hangman's Hymn - Musikalische Exequien - 2007"),
        ("AC/DC - Back in Black", "AC-DC - Back in Black"),
        ('Kapela - "Album"? *', "Kapela - Album"),
        ("Kapela - Album...  ", "Kapela - Album"),
        ("Kapela  -  Album", "Kapela - Album"),
    ],
)
def test_bezpecny_nazov(vstup, vystup):
    assert di.bezpecny_nazov(vstup) == vystup


def test_nazov_priecinka_vynecha_prazdne_casti():
    assert di.nazov_priecinka("Kapela", "Album", 2026) == "Kapela - Album - 2026"
    assert di.nazov_priecinka("Kapela", "Album", "") == "Kapela - Album"
    assert di.nazov_priecinka("", "Neznamy priecinok", None) == "Neznamy priecinok"


def test_nazov_pre_rozbalenie():
    navrh = di.Navrh(Path("a.zip"), surovy="Kapela - Album (2026)", interpret="Kapela",
                     album="Album", rok=2026, zdroj=di.Z_NAZVU)
    # Neupraveny navrh z vypisu sa odvodi znova z mena na disku (diakritika).
    assert navrh.nazov_pre_rozbalenie("Kapela", "Album", "2026") is None
    # Rucna uprava plati doslova.
    assert navrh.nazov_pre_rozbalenie("Kapela", "Album: Iny", "2025") == "Kapela - Album - Iny - 2025"
    # Dohladany nazov tiez — MA pozna spravny zapis.
    navrh.zdroj = di.DOHLADANE
    assert navrh.nazov_pre_rozbalenie("Kapela", "Album", "2026") == "Kapela - Album - 2026"


def test_existujuci_najde_aj_stary_povodny_nazov(tmp_path):
    (tmp_path / "Kapela - Album (2026)").mkdir()

    assert di.existujuci(tmp_path, "Kapela - Album - 2026", "Kapela - Album (2026)") == \
        tmp_path / "Kapela - Album (2026)"
    assert di.existujuci(tmp_path, "Ina - Vec") is None


def test_extract_uses_root_folder_from_archive(tmp_path):
    archive = _make_zip(
        tmp_path / "www.stiahnute_Kapela_-_Album_(2026).zip",
        ["Kapela - Album (2026)/01 - Song.mp3", "Kapela - Album (2026)/02 - Song.mp3"],
    )
    destination = tmp_path / "out" / "2026"

    outcome = di.extract_archive(archive, destination)

    assert outcome.status == "ok"
    # Nazov sa berie z korenoveho priecinka archivu, nie z mena suboru — a este
    # sa uprace na "Interpret - Album - Rok".
    assert outcome.destination == destination / "Kapela - Album - 2026"
    assert outcome.povodny == "Kapela - Album (2026)"
    assert (outcome.destination / "01 - Song.mp3").exists()
    assert not list(destination.glob(".tmp-*"))


def test_extract_counts_tracks_and_names_album(tmp_path):
    archive = _make_zip(
        tmp_path / "album.zip",
        [
            "Kapela - Album/01 - Song.mp3",
            "Kapela - Album/02 - Song.flac",
            "Kapela - Album/CD2/03 - Song.mp3",
            "Kapela - Album/cover.jpg",
            "Kapela - Album/info.nfo",
        ],
    )

    outcome = di.extract_archive(archive, tmp_path / "out")

    assert outcome.tracks == 3  # obrazok ani nfo sa nepocitaju, CD2 ano
    assert outcome.album == "Kapela - Album"


def test_skipped_outcome_still_reports_track_count(tmp_path):
    archive = _make_zip(tmp_path / "album.zip", ["Album/01.mp3", "Album/02.mp3"])
    destination = tmp_path / "out"

    di.extract_archive(archive, destination)
    second = di.extract_archive(archive, destination)

    assert second.status == "skipped"
    assert second.tracks == 2
    assert second.album == "Album"


def test_album_falls_back_to_archive_name_on_error(tmp_path):
    archive = tmp_path / "rozbite.zip"
    archive.write_bytes(b"nie archiv")

    outcome = di.extract_archive(archive, tmp_path / "out")

    assert outcome.status == "error"
    assert outcome.album == "rozbite"


def test_extract_flat_archive_uses_archive_name(tmp_path):
    archive = _make_zip(tmp_path / "Kapela - Singel.zip", ["01 - Song.mp3", "cover.jpg"])
    destination = tmp_path / "out" / "2026"

    outcome = di.extract_archive(archive, destination)

    assert outcome.status == "ok"
    assert outcome.destination == destination / "Kapela - Singel"
    assert (outcome.destination / "01 - Song.mp3").exists()
    assert (outcome.destination / "cover.jpg").exists()


def test_extract_skips_existing_album(tmp_path):
    archive = _make_zip(tmp_path / "album.zip", ["Album/01 - Song.mp3"])
    destination = tmp_path / "out" / "2026"

    assert di.extract_archive(archive, destination).status == "ok"
    second = di.extract_archive(archive, destination)

    assert second.status == "skipped"
    assert second.detail == "uz existuje"
    assert not list(destination.glob(".tmp-*"))


def test_extract_broken_archive_reports_error(tmp_path):
    archive = tmp_path / "rozbite.zip"
    archive.write_bytes(b"toto nie je archiv")
    destination = tmp_path / "out" / "2026"

    outcome = di.extract_archive(archive, destination)

    assert outcome.status == "error"
    assert outcome.detail
    assert not list(destination.glob(".tmp-*"))


def test_nacitaj_a_vykonaj_dava_albumy_pod_rok(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    _make_zip(downloads / "album.zip", ["Album/01 - Song.mp3"])
    root = tmp_path / "mp3"

    nacitanie = di.nacitaj(downloads, root=root)
    result = di.vykonaj([di.Uloha(n.archive) for n in nacitanie.navrhy], nacitanie.target)

    assert result.target == root / f"_{datetime.now().year}"
    assert [o.status for o in result.outcomes] == ["ok"]
    assert (result.target / "Album" / "01 - Song.mp3").exists()


def test_extract_pouzije_nazov_z_nahladu(tmp_path):
    archive = _make_zip(tmp_path / "album.zip", ["Kapela - Album (2026)/01 - Song.mp3"])
    destination = tmp_path / "out"

    outcome = di.extract_archive(archive, destination, "Ina Kapela - Iny Album - 2025")

    assert outcome.status == "ok"
    assert outcome.destination == destination / "Ina Kapela - Iny Album - 2025"
    assert outcome.povodny == "Kapela - Album (2026)"
    assert (outcome.destination / "01 - Song.mp3").exists()


def test_extract_bez_nazvu_berie_diakritiku_z_disku(tmp_path):
    # tar.exe vo vypise prepise `ø` na `o`; na disk ho rozbali spravne.
    archive = _make_zip(tmp_path / "album.zip", ["Mørk Gryning - Album (2026)/01.mp3"])

    navrh, = di.nacitaj(tmp_path, root=tmp_path / "mp3").navrhy
    outcome = di.extract_archive(archive, tmp_path / "out")

    assert navrh.interpret == "Mork Gryning"
    assert outcome.album == "Mørk Gryning - Album - 2026"


def _kos_do(zoznam: list[Path]):
    def kos(path: Path) -> str:
        zoznam.append(path)
        path.unlink()
        return ""
    return kos


def test_vykonaj_rozbali_a_zmaze_oznacene(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    prvy = _make_zip(downloads / "prvy.zip", ["Kapela - Prvy/01.mp3"])
    druhy = _make_zip(downloads / "druhy.zip", ["Kapela - Druhy/01.mp3"])
    treti = _make_zip(downloads / "treti.zip", ["Kapela - Treti/01.mp3"])
    destination = tmp_path / "mp3" / "_2026"
    zmazane: list[Path] = []

    messages: list[str] = []
    result = di.vykonaj(
        [
            di.Uloha(prvy, rozbalit=True, zmazat=True, nazov="Kapela - Prvy - 2026"),
            di.Uloha(druhy, rozbalit=True, zmazat=False),
            di.Uloha(treti, rozbalit=False, zmazat=True),
        ],
        destination, progress=messages.append, kos=_kos_do(zmazane),
    )

    assert [o.album for o in result.extracted] == ["Kapela - Prvy - 2026", "Kapela - Druhy"]
    assert zmazane == [prvy, treti]
    assert result.zmazane == [prvy, treti]
    assert result.uvolnene > 0
    assert druhy.exists()
    assert not (destination / "Kapela - Treti").exists()  # len zmazat, nerozbalit
    assert len(messages) == 4


def test_vykonaj_nezmaze_archiv_ktory_sa_nerozbalil(tmp_path):
    rozbity = tmp_path / "rozbity.zip"
    rozbity.write_bytes(b"toto nie je archiv")
    zmazane: list[Path] = []

    result = di.vykonaj([di.Uloha(rozbity, rozbalit=True, zmazat=True)],
                        tmp_path / "out", kos=_kos_do(zmazane))

    assert zmazane == []
    assert rozbity.exists()
    assert [a for a, _dovod in result.nezmazane] == [rozbity]
    assert len(result.failed) == 1


def test_vykonaj_zmaze_aj_uz_rozbaleny(tmp_path):
    archive = _make_zip(tmp_path / "album.zip", ["Album/01.mp3"])
    destination = tmp_path / "out"
    di.extract_archive(archive, destination)
    zmazane: list[Path] = []

    result = di.vykonaj([di.Uloha(archive, rozbalit=True, zmazat=True)],
                        destination, kos=_kos_do(zmazane))

    assert [o.status for o in result.outcomes] == ["skipped"]
    assert zmazane == [archive]


def test_vykonaj_hlasi_chybu_kosa(tmp_path):
    archive = _make_zip(tmp_path / "album.zip", ["Album/01.mp3"])

    result = di.vykonaj([di.Uloha(archive, rozbalit=False, zmazat=True)],
                        tmp_path / "out", kos=lambda _p: "subor je otvoreny")

    assert result.zmazane == []
    assert result.nezmazane == [(archive, "subor je otvoreny")]


@pytest.mark.parametrize(
    "raw, expected_suffix",
    [(r"C:\data\mp3", r"\\?\C:\data\mp3"), ("\\\\nas\\hudba", r"\\?\UNC\nas\hudba")],
)
def test_long_path_prefix(raw, expected_suffix):
    assert di._long(raw) == expected_suffix
