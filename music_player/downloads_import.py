r"""Hromadne rozbalenie hudobnych archivov z Downloads do C:\data\mp3\<rok>.

Ide to na dva kroky. `nacitaj` archivy len precita (zoznam suborov, nic sa
nerozbaluje) a ku kazdemu navrhne nazov priecinka `Skupina - Album - Rok`.
Pouzivatel si navrhy v okne skontroluje a opravi, a az `vykonaj` rozbali, co
oznacil — pod nazvom, ktory videl — a archivy oznacene na zmazanie presunie
do Kosa.

Rozbaluje sa cez `bsdtar` (C:\Windows\System32\tar.exe), ktory je sucastou
Windows a vie citat rar, zip aj 7z — netreba teda WinRAR ani 7-Zip.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from music_player import nazvy
from music_player.models import AUDIO_EXTENSIONS

ARCHIVE_EXTENSIONS = {".rar", ".zip", ".7z"}
#: Pouzije sa, ked `MP3_TARGET` v config.txt nie je vyplneny.
DEFAULT_TARGET_ROOT = Path(r"C:\data\mp3")
#: Rocne priecinky sa volaju `_2026`, `_2027`, ... — teda s podtrzitkom.
YEAR_PREFIX = "_"

#: Odkial navrh nazvu prisiel. Rozhoduje aj o tom, ci sa nazov po rozbaleni
#: este odvodi zo skutocneho mena na disku (viac pri `Navrh.nazov_pre_rozbalenie`).
DOHLADANE = "dohladane"   # zoznam noviniek alebo Metal Archives
Z_NAZVU = "z nazvu"       # offline parser `nazvy.rozober`
POVODNY = "povodny"       # nazvu sa rozumiet neda, ostava, ako prisiel

_TAR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
#: Znaky, ktore Windows v nazve priecinka nepusti. Album z MA sa pokojne vola
#: "Hangman's Hymn: Musikalische Exequien" a os.rename by na dvojbodke padol.
_ZAKAZANE = re.compile(r'[<>"?*\x00-\x1f]')
#: Co uploader pribali k albumu a co sa pri obalovom priecinku smie zahodit.
_SMETI = {".nfo", ".url", ".txt", ".sfv", ".md5", ".diz", ".lnk", ".htm", ".html", ".ini", ".db"}
#: `CD1`, `Disc 2` — cast albumu, do takeho priecinka sa nevchadza.
_DISK = re.compile(r"^(?:cd|disc|disk)\s*\d+$", re.IGNORECASE)


def _long(path: Path | str) -> str:
    r"""Cesta s prefixom \?\, aby operacie nepadali na limite 260 znakov."""
    text = os.path.abspath(str(path))
    if text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):  # sietova cesta \\server\share
        return "\\\\?\\UNC" + text[1:]
    return "\\\\?\\" + text


def _rmtree(path: Path) -> None:
    shutil.rmtree(_long(path), ignore_errors=True)


def downloads_dir() -> Path:
    """Priecinok Downloads aktualneho pouzivatela."""
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"


def target_root() -> Path:
    """Korenovy priecinok z config.txt (`MP3_TARGET`), inak zabudovany default."""
    from music_player.config_loader import get_mp3_target

    configured = get_mp3_target()
    return Path(os.path.expandvars(configured)).expanduser() if configured else DEFAULT_TARGET_ROOT


def year_folder(year: int | None = None) -> str:
    """Nazov rocneho priecinka — pouzivatelova schema je `_2026`, `_2027`, ..."""
    return f"{YEAR_PREFIX}{year or datetime.now().year}"


def target_dir(root: Path | str | None = None, year: int | None = None) -> Path:
    r"""Cielovy priecinok pre aktualny rok, napr. C:\data\mp3\_2026."""
    return Path(root if root is not None else target_root()) / year_folder(year)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "cp1250"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _vypis(archive: Path) -> tuple[list[str] | None, str]:
    """Nazvy poloziek v archive, alebo `None` a dovod, preco sa necita.

    Pozor na kodovanie: tar.exe vypisuje mena v kodovej stranke systemu
    (cp1250), takze znak, ktory v nej nie je, prepise na najblizsi (`ø` -> `o`).
    Pri rozbalovani pise na disk spravne — preto sa navrh, ktory pouzivatel
    nemenil, po rozbaleni este raz odvodi z mena na disku.
    """
    try:
        proc = subprocess.run(
            [str(_TAR), "-tf", str(archive)],
            capture_output=True,
            creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        return None, str(exc)
    if proc.returncode != 0:
        chyba = _decode(proc.stderr).strip().splitlines() if proc.stderr else []
        return None, chyba[-1] if chyba else "tar zlyhal"
    return [line.strip() for line in _decode(proc.stdout).splitlines() if line.strip()], ""


def has_audio(names: list[str]) -> bool:
    return any(Path(name).suffix.lower() in AUDIO_EXTENSIONS for name in names)


def _je_smeti(meno: str) -> bool:
    return Path(meno).suffix.lower() in _SMETI or meno.lower() in {".ds_store", "thumbs.db"}


def cesta_k_albumu(subory: list[tuple[str, ...]]) -> tuple[str, ...]:
    """Priecinok, v ktorom album naozaj zacina — cesta od korena archivu.

    `subory` su cesty k suborom (nie priecinkom) rozlozene na casti. Archivy
    chodia aj s obalom navyse:

        AVLSNEMBR26-By Samaritianin/Avulsed - Nordic Embryogenesis (2026)/01.mp3

    Do priecinka sa vojde, ked je v nom jediny podpriecinok s hudbou a vedla
    neho nanajvys smeti od uploadera (.nfo, .url, .txt) — tie sa zahodia aj
    s obalom. Ked je vedla cokolvek ine (cover.jpg, druhy priecinok), album je
    tu. Do `CD1` sa nevojde nikdy, to je cast albumu. `__MACOSX` sa ignoruje.
    Prazdna cesta = album lezi priamo v koreni archivu.
    """
    subory = [s for s in subory if s and s[0] != "__MACOSX"]
    cesta: tuple[str, ...] = ()
    while True:
        tu = [s[len(cesta):] for s in subory if s[:len(cesta)] == cesta]
        if any(not _je_smeti(s[0]) for s in tu if len(s) == 1):
            return cesta
        podpriecinky = {s[0] for s in tu if len(s) > 1}
        if len(podpriecinky) != 1:
            return cesta
        jediny = podpriecinky.pop()
        if _DISK.match(jediny) or not has_audio([s[-1] for s in tu if len(s) > 1]):
            return cesta
        cesta += (jediny,)


def _subory_z_vypisu(names: list[str]) -> list[tuple[str, ...]]:
    """Cesty k suborom z vypisu `tar -tf`, bez poloziek pre priecinky.

    Priecinok tar vypise raz s lomkou na konci (zip), inokedy bez nej (rar)
    — spozna sa tak, ze je zaciatkom inej cesty.
    """
    cesty = []
    for name in names:
        casti = tuple(c for c in name.replace("\\", "/").split("/") if c not in ("", "."))
        if casti and not name.endswith(("/", "\\")):
            cesty.append(casti)
    priecinky = {c[:i] for c in cesty for i in range(1, len(c))}
    return [c for c in cesty if c not in priecinky]


def _subory_na_disku(folder: Path) -> list[tuple[str, ...]]:
    koren = _long(folder)
    subory = []
    for adresar, _dirs, files in os.walk(koren):
        rel = os.path.relpath(adresar, koren)
        zaklad = () if rel == "." else Path(rel).parts
        subory.extend(zaklad + (f,) for f in files)
    return subory


def bezpecny_nazov(text: str) -> str:
    """Nazov priecinka, ktory Windows naozaj vytvori.

    `Album: Podtitul` -> `Album - Podtitul`, lomky na pomlcky, zvysne zakazane
    znaky von. Bodky a medzery na konci Windows potichu zahodi — potom by
    priecinok nesedel s tym, co ukazal nahlad.
    """
    text = str(text or "").replace(":", " - ")
    text = re.sub(r"[/\\|]", "-", text)
    text = _ZAKAZANE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r" -(?: -)+ ", " - ", text)  # "Album: - B" po nahrade dvojbodky
    return text.strip(" .")


def nazov_priecinka(interpret: str, album: str, rok: str | int | None = None) -> str:
    """`Skupina - Album - Rok`; prazdne casti sa vynechaju."""
    casti = [str(c).strip() for c in (interpret, album, rok) if c is not None]
    return bezpecny_nazov(" - ".join(c for c in casti if c))


@dataclass
class Navrh:
    """Jeden archiv z Downloads — co v nom je a ako by sa rozbalil."""

    archive: Path
    velkost: int = 0           # bajty archivu
    surovy: str = ""           # korenovy priecinok v archive, inak nazov archivu
    skladieb: int = 0          # audio subory podla vypisu archivu
    interpret: str = ""
    album: str = ""
    rok: int | None = None
    zdroj: str = POVODNY
    chyba: str = ""            # archiv sa neda precitat

    @property
    def citatelny(self) -> bool:
        return not self.chyba

    @property
    def nazov(self) -> str:
        return nazov_priecinka(self.interpret, self.album, self.rok)

    def nazov_pre_rozbalenie(self, interpret: str, album: str, rok: str) -> str | None:
        """Nazov pre `extract_archive`; `None` = odvod ho z mena na disku.

        Neupraveny navrh, ktory nebol dohladany, vznikol z vypisu tar.exe — a ten
        ma mena v cp1250 (`Mørk` -> `Mork`). Na disku su spravne, takze sa
        nazov odvodi znova odtial; vysledok je ten isty, len s pravou
        diakritikou. Dohladany nazov (MA, novinky) aj rucna uprava platia doslova.
        """
        povodne = (self.interpret, self.album, str(self.rok or ""))
        if self.zdroj != DOHLADANE and (interpret, album, rok) == povodne:
            return None
        return nazov_priecinka(interpret, album, rok)


@dataclass
class Nacitanie:
    target: Path
    navrhy: list[Navrh] = field(default_factory=list)
    #: Archivy bez jedinej skladby (programy, dokumenty). V okne sa neukazuju
    #: a nic sa s nimi nerobi — hudobny prehravac ich nema co mazat.
    bez_hudby: list[Path] = field(default_factory=list)


def navrhni(surovy: str, dohladat=None) -> tuple[nazvy.Nazov | None, str]:
    """Skupina, album a rok pre nazov z archivu — a odkial to prislo.

    `dohladat` je nepovinna funkcia `nazov -> nazvy.Nazov | None`, ktora sa smie
    spytat aj do siete (zoznam noviniek, Metal Archives). Ma prednost pred
    offline parserom: pozna spravny zapis (`I, Scvlptor`, `Boötes Void`)
    a rozhodne aj tam, kde sa z nazvu uhadnut neda. Ked vrati `None`, plati
    offline parser; ked ani ten, ostane povodny nazov. Modul sam do siete
    nechodi — vdaka tomu je testovatelny bez nej.
    """
    if dohladat is not None:
        try:
            najdene = dohladat(surovy)
        except Exception:  # noqa: BLE001 - vypadok siete nesmie zhodit nacitanie
            najdene = None
        if najdene is not None:
            return najdene, DOHLADANE
    rozobrany = nazvy.rozober(surovy)
    if rozobrany is not None:
        return rozobrany, Z_NAZVU
    return None, POVODNY


def nacitaj(
    source: Path | str | None = None,
    root: Path | str | None = None,
    progress=None,
    dohladat=None,
) -> Nacitanie:
    """Precita archivy v Downloads a ku kazdemu s hudbou navrhne nazov priecinka.

    Nic sa nerozbaluje ani nemaze. Archiv, ktory sa neda precitat, v navrhoch
    ostane s vyplnenou `chyba` — ticho nezmizne, aby sa dal aspon zmazat.
    """
    folder = Path(source) if source is not None else downloads_dir()
    vysledok = Nacitanie(target_dir(root))
    if not folder.is_dir():
        return vysledok
    archivy = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ARCHIVE_EXTENSIONS),
        key=lambda p: p.name.casefold(),
    )
    for index, archive in enumerate(archivy, start=1):
        if progress:
            progress(f"Načítavam {index}/{len(archivy)}: {archive.name}")
        try:
            velkost = archive.stat().st_size
        except OSError:
            velkost = 0
        mena, chyba = _vypis(archive)
        if mena is None:
            vysledok.navrhy.append(Navrh(archive, velkost, archive.stem, album=archive.stem,
                                         chyba=chyba or "archív sa nedá prečítať"))
            continue
        if not has_audio(mena):
            vysledok.bez_hudby.append(archive)
            continue
        cesta = cesta_k_albumu(_subory_z_vypisu(mena))
        surovy = cesta[-1] if cesta else archive.stem
        skladieb = sum(1 for m in mena if Path(m).suffix.lower() in AUDIO_EXTENSIONS)
        # Album, ktory v cieli uz je pod offline nazvom (alebo povodnym), sa
        # do siete nepyta: rozbalovat sa nebude a Metal Archives stoji kazdym
        # dopytom 1,5 s. Prave takych sa v Downloads nazbiera najviac.
        offline = nazvy.rozober(surovy)
        if existujuci(vysledok.target, bezpecny_nazov(offline.text if offline else surovy),
                      surovy) is not None:
            rozobrany, zdroj = offline, Z_NAZVU if offline else POVODNY
        else:
            rozobrany, zdroj = navrhni(surovy, dohladat)
        if rozobrany is None:
            navrh = Navrh(archive, velkost, surovy, skladieb, album=surovy, zdroj=zdroj)
        else:
            navrh = Navrh(archive, velkost, surovy, skladieb, rozobrany.interpret,
                          rozobrany.album, rozobrany.rok, zdroj)
        vysledok.navrhy.append(navrh)
    return vysledok


def existujuci(destination: Path, nazov: str, surovy: str = "") -> Path | None:
    """Priecinok, pod ktorym uz album v cieli lezi — inak `None`.

    Kontroluje sa aj povodny nazov: albumy rozbalene pred zavedenim
    upratovania lezia v cieli este pod nim a druhy raz sa rozbalit nemaju.
    """
    for kandidat in (nazov, surovy):
        if kandidat and os.path.exists(_long(destination / kandidat)):
            return destination / kandidat
    return None


@dataclass
class ArchiveOutcome:
    archive: Path
    status: str  # "ok" | "skipped" | "error"
    destination: Path | None = None
    detail: str = ""
    tracks: int = 0  # kolko audio suborov album obsahuje
    #: Nazov, pod ktorym to prislo v archive — pred upratanim na
    #: "Interpret - Album - Rok". Prazdny, ked sa nemenil.
    povodny: str = ""

    @property
    def album(self) -> str:
        """Nazov albumu tak, ako sa vola vysledny priecinok."""
        return self.destination.name if self.destination else self.archive.stem

    @property
    def premenovany(self) -> bool:
        return bool(self.povodny) and self.povodny != self.album


@dataclass
class ImportResult:
    target: Path
    outcomes: list[ArchiveOutcome] = field(default_factory=list)
    #: Archivy presunute do Kosa a kolko miesta v Downloads uvolnili.
    zmazane: list[Path] = field(default_factory=list)
    uvolnene: int = 0
    #: (archiv, preco ostal) — neprepadne ticho ani jeden.
    nezmazane: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def extracted(self) -> list[ArchiveOutcome]:
        return [o for o in self.outcomes if o.status == "ok"]

    @property
    def skipped(self) -> list[ArchiveOutcome]:
        return [o for o in self.outcomes if o.status == "skipped"]

    @property
    def failed(self) -> list[ArchiveOutcome]:
        return [o for o in self.outcomes if o.status == "error"]


def count_tracks(folder: Path) -> int:
    """Kolko audio suborov album obsahuje (vratane podpriecinkov, napr. CD1/CD2)."""
    total = 0
    for _root, _dirs, files in os.walk(_long(folder)):
        total += sum(1 for f in files if Path(f).suffix.lower() in AUDIO_EXTENSIONS)
    return total


def extract_archive(archive: Path, destination: Path, nazov: str | None = None) -> ArchiveOutcome:
    """Rozbali jeden archiv do `destination` ako samostatny podpriecinok.

    `nazov` je meno vysledneho priecinka tak, ako ho pouzivatel videl v nahlade.
    Bez neho sa odvodi zo skutocnych suborov na disku: nazov priecinka, v ktorom
    album zacina (`cesta_k_albumu` — preskoci obalove priecinky), inak nazov
    archivu, a ten sa este uprace na "Interpret - Album - Rok" (`nazvy`).
    Do ciela ide len ten priecinok; obal a smeti vedla neho sa zahodia.
    Rozbaluje sa najprv do docasneho priecinka. Uz existujuci album sa
    preskoci, nic sa neprepisuje.
    """
    destination.mkdir(parents=True, exist_ok=True)
    # Kratky nazov, aby docasna cesta zbytocne nenafukovala dlzku ciest vnutri.
    tag = hashlib.sha1(archive.name.encode("utf-8", "replace")).hexdigest()[:8]
    staging = destination / f".tmp-{tag}"
    _rmtree(staging)
    staging.mkdir()

    try:
        proc = subprocess.run(
            [str(_TAR), "-xf", str(archive), "-C", str(staging)],
            capture_output=True,
            creationflags=_NO_WINDOW,
        )
        if proc.returncode != 0:
            return ArchiveOutcome(
                archive, "error",
                detail=_decode(proc.stderr).strip().splitlines()[-1] if proc.stderr else "tar zlyhal",
            )

        subory = _subory_na_disku(staging)
        if not subory:
            return ArchiveOutcome(archive, "error", detail="archiv je prazdny")

        cesta = cesta_k_albumu(subory)
        source = staging.joinpath(*cesta)
        surovy = cesta[-1] if cesta else archive.stem
        album_name = bezpecny_nazov(nazov) if nazov else bezpecny_nazov(nazvy.uprav(surovy))
        if not album_name:
            return ArchiveOutcome(archive, "error", detail="prazdny nazov priecinka")

        hotovy = existujuci(destination, album_name, surovy)
        if hotovy is not None:
            return ArchiveOutcome(archive, "skipped", hotovy, "uz existuje",
                                  count_tracks(hotovy), povodny=surovy)

        final = destination / album_name
        os.rename(_long(source), _long(final))
        return ArchiveOutcome(archive, "ok", final, tracks=count_tracks(final),
                              povodny=surovy)
    except OSError as exc:
        return ArchiveOutcome(archive, "error", detail=str(exc))
    finally:
        _rmtree(staging)


def do_kosa(path: Path) -> str:
    """Presunie subor do Kosa. Vrati prazdny retazec, alebo popis chyby.

    Kos, nie trvale zmazanie: ked sa omylom oznaci album, ktory sa este
    nerozbalil, da sa vratit. Downloads sa uprace rovnako — prehravac archivy
    v Kosi nevidi.
    """
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    fo_delete = 0x3
    # FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI — bezi
    # to vo vlakne bez okna, ziadny dialog sa ukazat nesmie.
    flags = 0x4 | 0x10 | 0x40 | 0x400
    # pFrom je zoznam ukonceny dvoma nulami; jednu prida ctypes sam.
    op = SHFILEOPSTRUCTW(None, fo_delete, os.path.abspath(str(path)) + "\0", None, flags,
                         False, None, None)
    try:
        kod = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except (AttributeError, OSError) as exc:
        return str(exc)
    if kod != 0 or op.fAnyOperationsAborted:
        return f"Windows odmietol presun do Koša (kód {kod:#x})"
    if os.path.exists(path):
        return "súbor ostal na mieste"
    return ""


@dataclass
class Uloha:
    """Co sa ma s jednym archivom stat — tak, ako to pouzivatel nastavil v okne."""

    archive: Path
    rozbalit: bool = True
    zmazat: bool = False
    nazov: str | None = None  # None = odvodit z mena na disku


def vykonaj(ulohy: list[Uloha], destination: Path, progress=None, kos=do_kosa) -> ImportResult:
    """Rozbali a zmaze, co pouzivatel oznacil.

    Archiv, ktory sa mal rozbalit a nepodarilo sa to, sa NEZMAZE ani vtedy,
    ked bol oznaceny — inak by album zmizol uplne. Preskoceny (uz rozbaleny)
    sa zmazat smie, v cieli uz je.
    """
    result = ImportResult(destination)
    na_rozbalenie = [u for u in ulohy if u.rozbalit]
    zlyhane: set[Path] = set()
    for index, uloha in enumerate(na_rozbalenie, start=1):
        if progress:
            progress(f"Rozbaľujem {index}/{len(na_rozbalenie)}: {uloha.archive.name}")
        outcome = extract_archive(uloha.archive, destination, uloha.nazov)
        result.outcomes.append(outcome)
        if outcome.status == "error":
            zlyhane.add(uloha.archive)

    na_zmazanie = [u.archive for u in ulohy if u.zmazat]
    for index, archive in enumerate(na_zmazanie, start=1):
        if archive in zlyhane:
            result.nezmazane.append((archive, "nepodarilo sa ho rozbaliť, nechal som ho"))
            continue
        if progress:
            progress(f"Do Koša {index}/{len(na_zmazanie)}: {archive.name}")
        try:
            velkost = archive.stat().st_size
        except OSError:
            velkost = 0
        chyba = kos(archive)
        if chyba:
            result.nezmazane.append((archive, chyba))
        else:
            result.zmazane.append(archive)
            result.uvolnene += velkost
    return result


def open_in_explorer(path: Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        subprocess.Popen(["explorer", str(path)], creationflags=_NO_WINDOW)
