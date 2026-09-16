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


def test_find_music_archives_skips_archives_without_audio(tmp_path):
    with_music = _make_zip(tmp_path / "album.zip", ["Album/01 - Song.mp3"])
    _make_zip(tmp_path / "docs.zip", ["readme.txt"])
    (tmp_path / "notes.txt").write_text("nie archiv", encoding="utf-8")

    assert di.find_music_archives(tmp_path) == [with_music]


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


def test_import_from_downloads_puts_albums_under_year(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    _make_zip(downloads / "album.zip", ["Album/01 - Song.mp3"])
    _make_zip(downloads / "docs.zip", ["readme.txt"])
    root = tmp_path / "mp3"

    messages: list[str] = []
    result = di.import_from_downloads(downloads, root=root, progress=messages.append)

    assert result.target == root / f"_{datetime.now().year}"
    assert [o.status for o in result.outcomes] == ["ok"]
    assert (result.target / "Album" / "01 - Song.mp3").exists()
    assert len(messages) == 1


@pytest.mark.parametrize(
    "raw, expected_suffix",
    [(r"C:\data\mp3", r"\\?\C:\data\mp3"), ("\\\\nas\\hudba", r"\\?\UNC\nas\hudba")],
)
def test_long_path_prefix(raw, expected_suffix):
    assert di._long(raw) == expected_suffix
