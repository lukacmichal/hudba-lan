r"""Metalove novinky z NAS-u — zoznam albumov, ktore este treba vypocut.

Piatkovy sken `C:\NAS\metal-novinky` uz nekonci len mailom: co presiel filtrom,
zapisuje aj do

    \\nas.local\Android\PlayerPC\novinky\novinky.json

Prehravac ten subor CITA a nikdy do neho nezapisuje. Odskrtnutie ("uz som to
pocul") ide do samostatneho suboru vedla neho:

    \\nas.local\Android\PlayerPC\novinky\precitane.log

Preco dva subory a nie jeden: zoznam pise sken na jednom stroji, odskrtavanie
prehravac na dvoch. Keby to bol jeden subor, dva notebooky by si zapisy
navzajom prepisali. `precitane.log` sa preto len DOPLNA po riadkoch (jeden
riadok = jeden JSON) a nikdy sa neprepisuje cely — dva zapisy naraz tak
nemaju o co bojovat. Posledny riadok o danom albume plati, takze sa da aj
vratit spat, ked clovek odklikne vedla.

Zo `novinky.json` sa nemaze nic. Album ma jeden z troch stavov — nove,
zaujimave, skontrolovane (od 1.16; dovtedy len "precitane" ano/nie) — a podla
neho sa ukaze v zalozke. Riadok logu nesie aj udaje albumu: sken ho po tyzdni
zo `novinky.json` vyhodi, a zaujimavy album nesmie zmiznut len preto.
Starsi prehravac pole `stav` nepozna, cita `precitane` — zaujimave ma
`precitane: true`, takze ho aspon neukaze medzi novymi.

Ked NAS nie je dostupny (som mimo domu), pouzije sa posledna stiahnuta kopia
a odskrtnutia pockaju v `novinky-neodoslane.log` na najblizsie spojenie.
Ticho — rovnako ako kontrola aktualizacii a zaloha playlistu.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import unicodedata
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path

from music_player import config_loader, zanre
from music_player.persistence import _app_state_dir
from music_player.self_update import prihlas_na_share

PREDVOLENY_PRIECINOK = r"\\nas.local\Android\PlayerPC\novinky"
SUBOR = "novinky.json"
LOG = "precitane.log"
#: Verzia formatu, ktoru pise sken. Novsiu appka odmietne citat — radsej
#: nic nez zle pochopeny zoznam.
FORMAT = 1

_CACHE_SUBOR = "novinky-kopia.json"
_CACHE_ZANRE = "novinky-zanre-kopia.json"
_CACHE_LOG = "novinky-precitane-kopia.log"
_NEODOSLANE = "novinky-neodoslane.log"

#: Stavy albumu. Hodnoty su zaroven mena zaloziek v okne.
NOVE = "nove"
ZAUJIMAVE = "zaujimave"
SKONTROLOVANE = "skontrolovane"
STAVY = (NOVE, ZAUJIMAVE, SKONTROLOVANE)


# ── konfiguracia ──────────────────────────────────────────────────────────────
def priecinok() -> Path:
    hodnota = config_loader.load_config().get("NOVINKY_PRIECINOK", "").strip() or PREDVOLENY_PRIECINOK
    return Path(os.path.expandvars(hodnota))


def zapnute() -> bool:
    hodnota = config_loader.load_config().get("NOVINKY", "ano").strip().lower()
    return hodnota not in {"nie", "no", "0", "false", "vypnute"}


# ── jeden album ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Album:
    kluc: str
    kapela: str = ""
    album: str = ""
    styl: str = ""
    krajina: str = ""
    typ: str = ""
    vydane: str = ""
    #: Den vydania strojovo (ISO). Sluzi na zoskupenie po dnoch; `vydane` je
    #: ten isty udaj tak, ako ho pise MA ("September 4th, 2026").
    vydanie: str = ""
    ma: str = ""
    bandcamp: str = ""
    youtube: str = ""
    url: str = ""
    kategoria: str = "preslo"
    pribudlo: str = ""
    dovod: str = ""

    @property
    def den(self) -> str:
        """Deň vydania na zoskupenie — `4. 9. 2026`, alebo prázdno."""
        return _datum(self.vydanie) if self.vydanie else ""

    @property
    def nezaradeny(self) -> bool:
        """Filter si s nim nevedel rady — v okne patri pod ciaru."""
        return self.kategoria == "nezaradene"

    @property
    def nadpis(self) -> str:
        kapela = f"{self.kapela} ({self.krajina})" if self.krajina else self.kapela
        nazov = f"{kapela} — {self.album}" if self.album else kapela
        return f"{nazov}  [{self.typ}]" if self.typ else nazov

    @property
    def popis(self) -> str:
        """Druhy riadok — styl, datum vydania a odkedy je v zozname.

        Datum je pri KAZDOM albume, aj ked ho ma nad sebou deliaci riadok dna:
        pri rolovani dlhym zoznamom nadpis skupiny odide hore a bez datumu
        v riadku sa neda povedat, na co sa clovek prave pozera. Ked MA pozna len
        mesiac, je tam mesiac („august 2026") — predstierat den by znamenalo
        tvrdit nieco, co o vydani nikto nevie.

        Format zjednocuje sken (`databaza.datum_ludsky`); MA ma v tej bunke raz
        „September 4th, 2026" a raz hole „2026-09-04".
        """
        casti = [c for c in (self.styl, self.vydane) if c]
        if self.nezaradeny and self.dovod:
            casti.append(self.dovod)
        if self.pribudlo:
            casti.append(f"v zozname od {_datum(self.pribudlo)}")
        return " · ".join(casti)

    @property
    def youtube_odkaz(self) -> str:
        """Vlastny odkaz, inak vyhladavanie — to funguje vzdy.

        Nezaradene polozky odkaz zo skenu nemaju (sken ho hlada az tomu, co
        preslo filtrom), a prave pri nich je vypocutie to jedine, podla coho
        sa da rozhodnut.
        """
        if self.youtube:
            return self.youtube
        dopyt = f"{self.kapela} {self.album} full album".strip()
        return ("https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(dopyt))


def _bez_diakritiky(text: str) -> str:
    rozlozene = unicodedata.normalize("NFKD", text)
    return "".join(c for c in rozlozene if not unicodedata.combining(c)).casefold()


def zhoda(album: Album, dopyt: str) -> bool:
    """Hladanie v okne (Ctrl+F): kazde slovo dopytu niekde v albume.

    Bez ohladu na velkost pismen a diakritiku — „kjaerlighetarn" najde
    „Kjærlighetarn" rovnako ako „Kjaerlighetarn".
    """
    kde = _bez_diakritiky(" ".join((album.kapela, album.album, album.styl,
                                    album.krajina, album.typ, album.vydane)))
    kde = kde.replace("æ", "ae").replace("ø", "o")
    slova = _bez_diakritiky(dopyt).replace("æ", "ae").replace("ø", "o").split()
    return all(slovo in kde for slovo in slova)


def _datum(iso: str) -> str:
    """`2026-09-04` -> `4. 9. 2026`. Nezname sa necha tak."""
    try:
        d = dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day}. {d.month}. {d.year}"


def _album_zo_slovnika(data: dict) -> Album | None:
    kluc = str(data.get("kluc", "")).strip()
    if not kluc:
        return None
    return Album(
        kluc=kluc,
        kapela=str(data.get("kapela", "")),
        album=str(data.get("album", "")),
        styl=str(data.get("styl", "")),
        krajina=str(data.get("krajina", "")),
        typ=str(data.get("typ", "")),
        vydane=str(data.get("vydane", "")),
        vydanie=str(data.get("vydanie", "")),
        ma=str(data.get("ma", "")),
        bandcamp=str(data.get("bandcamp", "")),
        youtube=str(data.get("youtube", "")),
        url=str(data.get("url", "")),
        kategoria=str(data.get("kategoria", "preslo")),
        pribudlo=str(data.get("pribudlo", "")),
        dovod=str(data.get("dovod", "")),
    )


def rozober_zoznam(text: str) -> list[Album]:
    """Albumy z obsahu `novinky.json`. Nezrozumitelny subor = prazdny zoznam."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("albumy"), list):
        return []
    if int(data.get("format", FORMAT) or FORMAT) > FORMAT:
        return []
    albumy = [_album_zo_slovnika(p) for p in data["albumy"] if isinstance(p, dict)]
    return [a for a in albumy if a is not None]


# ── odskrtnute ────────────────────────────────────────────────────────────────
def riadok_logu(kluc: str, precitane: bool = True, stav: str | None = None,
                album: Album | None = None) -> str:
    """Jeden zapis do `precitane.log` — cely JSON na jednom riadku.

    JSON preto, ze `kluc` sam obsahuje `|` (kapela|album) a pri oddelovacoch
    by sa to skor ci neskor rozislo. Meno pocitaca je tam kvoli tomu, aby sa
    dalo dohladat, na ktorom stroji sa co odskrtlo.
    """
    stav = stav if stav in STAVY else (SKONTROLOVANE if precitane else NOVE)
    zaznam = {
        "kedy": dt.datetime.now().isoformat(timespec="seconds"),
        "kluc": kluc,
        "precitane": stav != NOVE,
        "stav": stav,
        "pocitac": socket.gethostname(),
    }
    if album is not None:
        zaznam["album"] = asdict(album)
    return json.dumps(zaznam, ensure_ascii=False)


def rozober_stavy(text: str) -> tuple[dict[str, str], dict[str, Album]]:
    """({kluc: stav}, {kluc: album}) z logu. Posledny riadok o albume plati.

    Polovicny riadok (dva stroje zapisali naraz) sa preskoci — album vtedy
    ostane novy, co je spravnejsie nez ho ticho schovat. Riadok bez `stav`
    je zo starsej verzie a plati podla `precitane`.
    """
    stavy: dict[str, str] = {}
    snimky: dict[str, Album] = {}
    for riadok in text.splitlines():
        riadok = riadok.strip()
        if not riadok:
            continue
        try:
            zaznam = json.loads(riadok)
        except ValueError:
            continue
        kluc = str(zaznam.get("kluc", "")).strip() if isinstance(zaznam, dict) else ""
        if not kluc:
            continue
        stav = str(zaznam.get("stav") or "")
        if stav not in STAVY:
            stav = SKONTROLOVANE if bool(zaznam.get("precitane", True)) else NOVE
        stavy[kluc] = stav
        if isinstance(zaznam.get("album"), dict):
            album = _album_zo_slovnika({**zaznam["album"], "kluc": kluc})
            if album is not None:
                snimky[kluc] = album
    return stavy, snimky


def rozober_log(text: str) -> set[str]:
    """Kluce oznacene za skontrolovane."""
    stavy, _ = rozober_stavy(text)
    return {k for k, v in stavy.items() if v == SKONTROLOVANE}


def _stavy(text: str) -> dict:
    """Polia `Zoznam`-u, ktore pochadzaju z logu."""
    stavy, snimky = rozober_stavy(text)
    return {
        "precitane": {k for k, v in stavy.items() if v == SKONTROLOVANE},
        "zaujimave": {k for k, v in stavy.items() if v == ZAUJIMAVE},
        "snimky": snimky,
    }


# ── pristup na NAS a lokalna kopia ────────────────────────────────────────────
def _kopia(meno: str) -> Path:
    return _app_state_dir() / meno


def _precitaj(cesta: Path) -> str | None:
    try:
        return cesta.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _uloz_kopiu(meno: str, text: str) -> None:
    try:
        cesta = _kopia(meno)
        cesta.parent.mkdir(parents=True, exist_ok=True)
        cesta.write_text(text, encoding="utf-8")
    except OSError:
        # Kopia je pohodlie pre beh mimo domu, nie povinnost.
        pass


def _pripoj(cesta: Path, riadky: list[str]) -> bool:
    """Doplni riadky na koniec suboru. `True` = zapisalo sa."""
    if not riadky:
        return True
    try:
        cesta.parent.mkdir(parents=True, exist_ok=True)
        with cesta.open("a", encoding="utf-8") as f:
            f.write("".join(r.rstrip("\n") + "\n" for r in riadky))
        return True
    except OSError:
        return False


def _zabezpec_pristup(p: Path) -> bool:
    """Cestu treba vediet precitat. Nikdy nevyhodi vynimku."""
    try:
        if (p / SUBOR).exists():
            return True
    except OSError:
        pass
    if not prihlas_na_share(p):
        return False
    try:
        return (p / SUBOR).exists()
    except OSError:
        return False


# ── nacitanie ─────────────────────────────────────────────────────────────────
@dataclass
class Zoznam:
    albumy: list[Album] = field(default_factory=list)
    precitane: set[str] = field(default_factory=set)
    #: Ktore kluce patria do ktorej zalozky. Prazdne = starsi subor bez
    #: zalaziek; vtedy je zoznam jeden a prehravac ho ukaze v jednej zalozke.
    zalozky: dict = field(default_factory=dict)
    #: Slova filtra zanrov (z `filtre.json` vedla zoznamu). Filtruje sa AZ TU,
    #: lebo sken posiela aj to, co podla zanru zahodil — inak by sa pridanie
    #: zanru nemalo na com prejavit.
    povolene: list = field(default_factory=lambda: list(zanre.POVOLENE))
    zakazane: list = field(default_factory=lambda: list(zanre.ZAKAZANE))
    #: `False` = NAS neodpovedal a toto je posledna stiahnuta kopia.
    z_nasu: bool = True
    #: Kolko odskrtnuti caka na spojenie s NAS-om.
    caka: int = 0
    zaujimave: set[str] = field(default_factory=set)
    #: Posledne zname udaje albumov z logu. Vdaka nim zaujimave a skontrolovane
    #: albumy nezmiznu, ked ich sken prestane posielat v `novinky.json`.
    snimky: dict = field(default_factory=dict)

    def stav(self, kluc: str) -> str:
        if kluc in self.zaujimave:
            return ZAUJIMAVE
        if kluc in self.precitane:
            return SKONTROLOVANE
        return NOVE

    def nastav(self, kluce, stav: str) -> None:
        for kluc in kluce:
            self.zaujimave.discard(kluc)
            self.precitane.discard(kluc)
            if stav == ZAUJIMAVE:
                self.zaujimave.add(kluc)
            elif stav == SKONTROLOVANE:
                self.precitane.add(kluc)

    def vsetky(self) -> list[Album]:
        """Albumy zo zoznamu + tie, ktore z neho uz vypadli, ale su v logu."""
        zname = {a.kluc for a in self.albumy}
        return list(self.albumy) + [a for k, a in self.snimky.items() if k not in zname]

    def v_stave(self, stav: str) -> list[Album]:
        """Zaujimave alebo skontrolovane — najnovsie vydania navrchu."""
        kluce = self.zaujimave if stav == ZAUJIMAVE else self.precitane
        vybrane = [a for a in self.vsetky() if a.kluc in kluce]
        vybrane.sort(key=lambda a: (a.kapela.casefold(), a.album.casefold()))
        vybrane.sort(key=lambda a: a.vydanie or "", reverse=True)
        return vybrane

    def nove(self) -> list[Album]:
        return [a for a in self.albumy if self.stav(a.kluc) == NOVE]

    @property
    def pocet_novych(self) -> int:
        return len(self.nove())

    def posudok(self, album: Album) -> tuple[str, str]:
        """(vysledok filtra, dovod) pre jeden album podla aktualnych slov."""
        return zanre.posud(album.styl, self.povolene, self.zakazane)

    def pre_zalozku(self, nazov: str) -> list[Album]:
        """Albumy jednej zalozky v poradi, v akom su v subore.

        Poradie sa TU nemeni. Zoradenie (podla dna vydania, potom podla abecedy)
        robi sken, ktory jediny pozna presne datumy — prehravac ma o vydani len
        to, co mu prislo, a druhe zoradenie na jeho strane by sa s tym prvym
        skor ci neskor rozislo.
        """
        kluce = self.zalozky.get(nazov) or []
        if not kluce:
            return []
        poradie = {k: i for i, k in enumerate(kluce)}
        vybrane = [a for a in self.albumy
                   if a.kluc in poradie and self.posudok(a)[0] != zanre.ODMIETNUTE]
        return sorted(vybrane, key=lambda a: poradie[a.kluc])


def rozober_zalozky(text: str) -> dict:
    """`zalozky` zo suboru — {meno: [kluc, ...]}. Chybajuce = prazdny slovnik.

    Starsi subor toto pole nema a to nie je chyba: vtedy je zoznam jeden.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    zalozky = data.get("zalozky") if isinstance(data, dict) else None
    if not isinstance(zalozky, dict):
        return {}
    return {str(meno): [str(k) for k in kluce if isinstance(k, str)]
            for meno, kluce in zalozky.items() if isinstance(kluce, list)}


def nacitaj(p: Path | None = None) -> Zoznam:
    """Zoznam noviniek. Nedostupny NAS vrati poslednu kopiu, nie chybu."""
    ciel = p if p is not None else priecinok()
    neodoslane = _precitaj(_kopia(_NEODOSLANE)) or ""

    if _zabezpec_pristup(ciel):
        # Cakajuce odskrtnutia patria na NAS skor, nez sa odtial cita stav —
        # inak by sa album na chvilu vratil medzi neprecitane.
        cakajuce = [r for r in neodoslane.splitlines() if r.strip()]
        if cakajuce and _pripoj(ciel / LOG, cakajuce):
            _uloz_kopiu(_NEODOSLANE, "")
            neodoslane = ""
        zoznam_text = _precitaj(ciel / SUBOR)
        log_text = _precitaj(ciel / LOG) or ""
        if zoznam_text is not None:
            _uloz_kopiu(_CACHE_SUBOR, zoznam_text)
            _uloz_kopiu(_CACHE_LOG, log_text)
            zanre_text = _precitaj(ciel / zanre.SUBOR)
            if zanre_text is not None:
                _uloz_kopiu(_CACHE_ZANRE, zanre_text)
            else:
                zanre_text = _precitaj(_kopia(_CACHE_ZANRE)) or ""
            povolene, zakazane = zanre.rozober(zanre_text)
            return Zoznam(
                albumy=rozober_zoznam(zoznam_text),
                zalozky=rozober_zalozky(zoznam_text),
                **_stavy(log_text + neodoslane),
                povolene=povolene, zakazane=zakazane,
                z_nasu=True,
                caka=len([r for r in neodoslane.splitlines() if r.strip()]),
            )

    zoznam_text = _precitaj(_kopia(_CACHE_SUBOR))
    log_text = _precitaj(_kopia(_CACHE_LOG)) or ""
    if zoznam_text is None:
        return Zoznam(z_nasu=False)
    povolene, zakazane = zanre.rozober(_precitaj(_kopia(_CACHE_ZANRE)) or "")
    return Zoznam(
        albumy=rozober_zoznam(zoznam_text),
        zalozky=rozober_zalozky(zoznam_text),
        **_stavy(log_text + neodoslane),
        povolene=povolene, zakazane=zakazane,
        z_nasu=False,
        caka=len([r for r in neodoslane.splitlines() if r.strip()]),
    )


def oznac(kluce: list[str], precitane: bool = True, p: Path | None = None,
          stav: str | None = None, albumy: dict | None = None) -> bool:
    """Zmeni stav albumov. `True` = zapisalo sa rovno na NAS.

    `stav` ma prednost pred `precitane` (to ostava kvoli starsim volaniam).
    `albumy` ({kluc: Album}) sa zapisu do logu ako snimka — viď `Zoznam.snimky`.

    Ked NAS neodpovie, zapis pocka v lokalnom subore a odide pri najblizsom
    nacitani zoznamu. Volajuci sa preto nemusi pytat, ci to vyslo — album
    zmizne zo zoznamu tak ci tak.
    """
    riadky = [riadok_logu(k, precitane, stav, (albumy or {}).get(k)) for k in kluce if k]
    if not riadky:
        return True
    ciel = p if p is not None else priecinok()
    if _zabezpec_pristup(ciel) and _pripoj(ciel / LOG, riadky):
        # Nech sa to isté neposiela druhy raz po navrate domov.
        _uloz_kopiu(_CACHE_LOG, (_precitaj(ciel / LOG) or ""))
        return True
    _pripoj(_kopia(_NEODOSLANE), riadky)
    return False


def uloz_zanre(povolene: list[str], zakazane: list[str],
               p: Path | None = None) -> bool:
    """Zapise slova filtra na NAS. `True` = podarilo sa.

    Lokalna kopia sa ulozi vzdy, aj ked NAS neodpovie — inak by sa uprava
    stratila a okno by po zatvoreni ukazovalo zase to stare. Na NAS sa to ale
    samo nedoposiela: na rozdiel od odskrtnuti je toto nastavenie, ktore ma
    platit aj pre sken, a ticho odlozena zmena filtra by znamenala, ze mail
    a prehravac filtruju kazdy podla ineho.
    """
    text = zanre.zloz(povolene, zakazane)
    _uloz_kopiu(_CACHE_ZANRE, text)
    ciel = p if p is not None else priecinok()
    if not _zabezpec_pristup(ciel):
        return False
    try:
        (ciel / zanre.SUBOR).write_text(text, encoding="utf-8")
        return True
    except OSError:
        return False
