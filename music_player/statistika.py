"""Statistika pocuvania — co sa kolkokrat prehralo.

Kazde prehratie je jeden riadok v SQLite (`%APPDATA%\\LanMusicPlayer\\statistika.db`).
Uklada sa udalost, nie len pocitadlo, takze sa da pytat aj "za posledny
tyzden" a kedy skladba hrala naposledy.

Prehratie sa pocita presne tak, ako celkove pocitadlo v PlayerControlleri:
skladba musi realne hrat aspon 30 s (pri kratkych 30 % dlzky). Preskocena
skladba sa teda nezapise.

Databaza je lokalna pre kazdy notebook — SQLite na sietovom disku s dvoma
zapisovatelmi by sa skor ci neskor poskodila. Chyba databazy prehravanie
nikdy nezastavi: zapis sa ticho preskoci.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from music_player.models import Track

DB_FILE_NAME = "statistika.db"

# Obdobia v okne statistiky: (popis, pocet dni; None = od zaciatku).
OBDOBIA: list[tuple[str, int | None]] = [
    ("Celkovo", None),
    ("Posledný rok", 365),
    ("Posledných 30 dní", 30),
    ("Posledných 7 dní", 7),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prehratia (
    id         INTEGER PRIMARY KEY,
    cas        REAL    NOT NULL,          -- unix cas zapocitania
    cesta      TEXT    NOT NULL,
    interpret  TEXT    NOT NULL DEFAULT '',
    album      TEXT    NOT NULL DEFAULT '',
    nazov      TEXT    NOT NULL DEFAULT '',
    dlzka_ms   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_prehratia_cas   ON prehratia(cas);
CREATE INDEX IF NOT EXISTS ix_prehratia_cesta ON prehratia(cesta);
"""


@dataclass(slots=True)
class Riadok:
    """Jeden riadok rebricka. Pri skladbach je `cesta` vyplnena."""
    popis: str
    pocet: int
    naposledy: float
    cesta: str = ""
    dlzka_ms: int = 0


class Statistika:
    def __init__(self, cesta: Path | str) -> None:
        self._cesta = Path(cesta)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def cesta(self) -> Path:
        return self._cesta

    def _spojenie(self) -> sqlite3.Connection:
        if self._conn is None:
            self._cesta.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._cesta), check_same_thread=False)
            conn.executescript(_SCHEMA)
            self._conn = conn
        return self._conn

    def zavri(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ── zapis ──────────────────────────────────────────────────────────────────
    def zaznamenaj(self, track: Track, cas: float | None = None) -> bool:
        """Zapise jedno prehratie. Vrati False, ked sa zapis nepodaril."""
        if not track or not track.path:
            return False
        kedy = time.time() if cas is None else float(cas)
        try:
            with self._lock:
                conn = self._spojenie()
                with conn:
                    conn.execute(
                        "INSERT INTO prehratia (cas, cesta, interpret, album, nazov, dlzka_ms)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (kedy, track.path, track.artist or "", track.album or "",
                         track.title or Path(track.path).stem, int(track.duration_ms or 0)),
                    )
            return True
        except sqlite3.Error:
            return False

    # ── citanie ────────────────────────────────────────────────────────────────
    def _od(self, dni: int | None, teraz: float | None) -> float:
        if dni is None:
            return 0.0
        return (time.time() if teraz is None else teraz) - dni * 86_400

    def _dopyt(self, sql: str, parametre: tuple) -> list[tuple]:
        try:
            with self._lock:
                return self._spojenie().execute(sql, parametre).fetchall()
        except sqlite3.Error:
            return []

    def skladby(self, dni: int | None = None, *, teraz: float | None = None,
                limit: int | None = None) -> list[Riadok]:
        """Skladby podla poctu prehrati. Metadata su z posledneho prehratia
        (tagy sa medzicasom mohli opravit)."""
        sql = (
            "SELECT p.cesta, COUNT(*) AS n, MAX(p.cas) AS posl,"
            " (SELECT interpret FROM prehratia q WHERE q.cesta = p.cesta ORDER BY q.cas DESC LIMIT 1),"
            " (SELECT nazov     FROM prehratia q WHERE q.cesta = p.cesta ORDER BY q.cas DESC LIMIT 1),"
            " (SELECT dlzka_ms  FROM prehratia q WHERE q.cesta = p.cesta ORDER BY q.cas DESC LIMIT 1)"
            " FROM prehratia p WHERE p.cas >= ?"
            " GROUP BY p.cesta ORDER BY n DESC, posl DESC"
        )
        parametre: tuple = (self._od(dni, teraz),)
        if limit:
            sql += " LIMIT ?"
            parametre += (int(limit),)
        vysledok = []
        for cesta, n, posl, interpret, nazov, dlzka in self._dopyt(sql, parametre):
            nazov = nazov or Path(cesta).stem
            popis = f"{interpret} – {nazov}" if interpret else nazov
            vysledok.append(Riadok(popis, int(n), float(posl), cesta, int(dlzka or 0)))
        return vysledok

    def interpreti(self, dni: int | None = None, *, teraz: float | None = None) -> list[Riadok]:
        rows = self._dopyt(
            "SELECT interpret, COUNT(*) AS n, MAX(cas) AS posl FROM prehratia"
            " WHERE cas >= ? AND interpret != ''"
            " GROUP BY interpret COLLATE NOCASE ORDER BY n DESC, posl DESC",
            (self._od(dni, teraz),),
        )
        return [Riadok(i, int(n), float(p)) for i, n, p in rows]

    def albumy(self, dni: int | None = None, *, teraz: float | None = None) -> list[Riadok]:
        rows = self._dopyt(
            "SELECT interpret, album, COUNT(*) AS n, MAX(cas) AS posl FROM prehratia"
            " WHERE cas >= ? AND album != ''"
            " GROUP BY interpret COLLATE NOCASE, album COLLATE NOCASE"
            " ORDER BY n DESC, posl DESC",
            (self._od(dni, teraz),),
        )
        return [Riadok(f"{i} – {a}" if i else a, int(n), float(p)) for i, a, n, p in rows]

    def historia(self, limit: int = 500) -> list[Riadok]:
        """Posledne prehratia, najnovsie prve (pocet = 1 na riadok)."""
        rows = self._dopyt(
            "SELECT cesta, interpret, nazov, cas, dlzka_ms FROM prehratia"
            " ORDER BY cas DESC LIMIT ?",
            (int(limit),),
        )
        vysledok = []
        for cesta, interpret, nazov, cas, dlzka in rows:
            nazov = nazov or Path(cesta).stem
            popis = f"{interpret} – {nazov}" if interpret else nazov
            vysledok.append(Riadok(popis, 1, float(cas), cesta, int(dlzka or 0)))
        return vysledok

    def suhrn(self, dni: int | None = None, *, teraz: float | None = None) -> tuple[int, int, int]:
        """(pocet prehrati, roznych skladieb, sucet dlzok v ms)."""
        rows = self._dopyt(
            "SELECT COUNT(*), COUNT(DISTINCT cesta), COALESCE(SUM(dlzka_ms), 0)"
            " FROM prehratia WHERE cas >= ?",
            (self._od(dni, teraz),),
        )
        if not rows:
            return 0, 0, 0
        n, rozne, ms = rows[0]
        return int(n), int(rozne), int(ms)

    def pocet(self, cesta: str) -> int:
        rows = self._dopyt("SELECT COUNT(*) FROM prehratia WHERE cesta = ?", (cesta,))
        return int(rows[0][0]) if rows else 0


def predvolena_cesta() -> Path:
    from music_player.persistence import _app_state_dir
    return _app_state_dir() / DB_FILE_NAME
