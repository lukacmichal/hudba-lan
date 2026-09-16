"""Zaloha aktualneho playlistu na NAS.

Playlist zije v jedinom subore na disku toho notebooku, na ktorom prehravac
prave bezi (`%APPDATA%\\LanMusicPlayer\\state.json`). Ked sa stroj pokazi,
preinstaluje, alebo sa subor poskodi, playlist skladany mesiace je prec — a
z hromady mp3-tiek na disku sa uz poradie ani vyber nezlozi spat.

Pri kazdom spusteni sa preto odklada kopia na NAS, vedla balikov appky:

    \\\\nas.local\\Android\\PlayerPC\\zalohy\\<POCITAC>\\
        playlist-2026-09-02-183012.m3u8
        playlist-2026-09-04-201455.m3u8
        ...
        README.txt          ako sa zaloha vracia spat

Styri veci, ktore z toho robia zalohu a nie balast:

1. **Zapisuje sa iba pri ZMENE.** Nova zaloha sa porovna s poslednou a ked
   sedi zoznam skladieb, nezapise sa nic. Porovnavaju sa vyhradne cesty —
   hlavicka s datumom a poznamkami sa ignoruje, inak by bol kazdy start
   "zmena". Vecer po veceri bez zasahu do playlistu teda na NAS-e nepribudne
   ani riadok.
2. **Kazdy pocitac ma vlastny podpriecinok.** Appka sa stahuje medzi dvoma
   notebookmi (pozri README) a kazdy ma svoj playlist; do spolocneho priecinka
   by si ich navzajom prepisovali a "posledna zaloha" by striedala stroje.
3. **Drzi sa poslednych N** (`ZALOHA_POCET`, predvolene 30). Bez toho by
   priecinok rastol donekonecna.
4. **Format je obycajny M3U8 s absolutnymi cestami.** Da sa pretiahnut mysou
   priamo do okna prehravaca (aj do ktoreholvek ineho playera) a da sa citat
   v poznamkovom bloku. Ziadny vlastny format, na ktory by clovek potreboval
   prave tento kod — zaloha ma prezit aj appku.

Prazdny playlist sa nezalohuje. Prve spustenie na cistom notebooku (alebo
stav po havarii) by inak prepisalo historiu prazdnym suborom — prave tym,
pred cim to ma chranit.

Nedostupny NAS = ticho, presne ako pri aktualizacii (`self_update`). Mimo
domu sa appka o NAS-e nesmie ozvat.
"""
from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from music_player.config_loader import load_config
from music_player.models import Track
from music_player.self_update import prihlas_na_share

PREDVOLENY_PRIECINOK = r"\\nas.local\Android\PlayerPC\zalohy"
PREDVOLENY_POCET = 30
VZOR_MENA = "playlist-*.m3u8"
_FORMAT_MENA = "playlist-%Y-%m-%d-%H%M%S.m3u8"
_NEPOVOLENE = '<>:"/\\|?*'

README = "README.txt"
_README_TEXT = """Zalohy playlistu z Metal Music Playera
======================================

Kazdy subor je playlist tak, ako vyzeral pri jednom spusteni prehravaca na
tomto pocitaci. Zapisuje sa len vtedy, ked sa oproti predchadzajucej zalohe
naozaj zmenil, takze datum v nazve je datum ZMENY, nie kazdeho spustenia.

Ako playlist vratit spat
------------------------
1. Otvor prehravac.
2. Ked ma byt playlist presne taky ako v zalohe, najprv stlac "Vymazat
   playlist" - skladby zo zalohy sa totiz PRIDAVAJU na koniec.
3. Pretiahni .m3u8 subor mysou do okna, alebo stlac "Nacitat M3U" a vyber ho.

Subor je obycajny textovy zoznam ciest, takze ho otvori aj poznamkovy blok
a prehra hociktory iny player.

Cesty su absolutne a plati ich ten pocitac, z ktoreho zaloha pochadza (preto
ma kazdy vlastny podpriecinok). Ked su skladby na druhom stroji inde, cesty
sa daju hromadne nahradit v poznamkovom bloku.

Vytvara to prehravac sam, priecinok netreba upratovat - drzi sa v nom
poslednych par zaloh a starsie maze.
"""


@dataclass(frozen=True)
class Vysledok:
    """Co sa pri zalohovani stalo. Nikdy nie vynimka — zaloha nesmie zhodit start."""

    stav: str          # zapisane | nezmenene | prazdny | vypnute | nedostupne | chyba
    subor: Path | None = None
    pocet: int = 0
    zmazane: int = 0
    detail: str = ""

    @property
    def sprava(self) -> str:
        """Veta do stavoveho riadku. Prazdny retazec = nehovor nic."""
        if self.stav == "zapisane":
            meno = self.subor.name if self.subor else ""
            return f"Playlist zazalohovany na NAS ({self.pocet} skladieb): {meno}"
        if self.stav == "nezmenene":
            return "Playlist sa od poslednej zalohy nezmenil."
        if self.stav == "chyba":
            return f"Zalohu playlistu sa nepodarilo zapisat: {self.detail}"
        # Vypnute, prazdny playlist a nedostupny NAS su ticho.
        return ""


# -- konfiguracia -------------------------------------------------------------
def zapnuta() -> bool:
    hodnota = load_config().get("ZALOHA_PLAYLISTU", "ano").strip().lower()
    return hodnota not in {"nie", "no", "0", "false", "vypnute"}


def koren() -> Path:
    hodnota = load_config().get("ZALOHA_PRIECINOK", "").strip() or PREDVOLENY_PRIECINOK
    return Path(os.path.expandvars(hodnota))


def pocet_zaloh() -> int:
    """Kolko zaloh sa v priecinku necha. Nezmysel v configu = predvolenych 30."""
    try:
        hodnota = int(load_config().get("ZALOHA_POCET", "").strip())
    except (TypeError, ValueError):
        return PREDVOLENY_POCET
    return max(hodnota, 1)


def meno_pocitaca() -> str:
    """Meno stroja pre podpriecinok, ocistene o znaky, ktore v ceste nesmu byt."""
    surove = (os.environ.get("COMPUTERNAME") or platform.node() or "").strip()
    ocistene = "".join("-" if znak in _NEPOVOLENE else znak for znak in surove).strip(". ")
    return ocistene or "pocitac"


def priecinok() -> Path:
    """Priecinok zaloh TOHTO pocitaca."""
    return koren() / meno_pocitaca()


# -- zapis --------------------------------------------------------------------
def _hlavicka(tracks: list[Track], teraz: datetime, hraje: Track | None) -> list[str]:
    riadky = [
        "#EXTM3U",
        f"# Zaloha playlistu z Metal Music Playera, {teraz:%d. %m. %Y %H:%M:%S}",
        f"# Pocitac: {meno_pocitaca()}",
        f"# Skladieb: {len(tracks)}",
    ]
    if hraje is not None:
        riadky.append(f"# Naposledy hralo: {hraje.display_text}")
    riadky += [
        "#",
        "# Ako to vratit spat: pretiahni tento subor mysou do okna prehravaca.",
        "# Riadky zacinajuce # su komentare, zvysok su cesty k skladbam.",
    ]
    return riadky


def text_zalohy(
    tracks: list[Track],
    *,
    teraz: datetime | None = None,
    hraje: Track | None = None,
) -> str:
    """Zloz obsah M3U8 suboru. Oddelene od zapisu, nech sa da testovat samo."""
    teraz = teraz or datetime.now()
    riadky = _hlavicka(tracks, teraz, hraje)
    for track in tracks:
        sekundy = track.duration_ms // 1000 if track.duration_ms > 0 else -1
        riadky.append(f"#EXTINF:{sekundy},{track.display_text}")
        riadky.append(track.path)
    return "\n".join(riadky) + "\n"


def cesty_z_textu(text: str) -> list[str]:
    """Zo zalohy vytiahne iba cesty. Podla toho sa pozna, ci sa playlist zmenil."""
    return [r.strip() for r in text.splitlines() if r.strip() and not r.startswith("#")]


def _rovnake(a: list[str], b: list[str]) -> bool:
    # Poradie je sucast playlistu, takze sa NEtriedi. Velkost pismen naopak
    # rozdiel nie je — Windows tu istu cestu vrati raz s C:\ a raz s c:\.
    return [x.lower() for x in a] == [y.lower() for y in b]


def posledna_zaloha(kam: Path) -> Path | None:
    """Najnovsia zaloha v priecinku, alebo None.

    Radi sa podla MENA, nie podla casu zmeny: meno nesie datum aj cas a je to
    jedina vec, ktora prezije kopirovanie priecinka inam.
    """
    try:
        subory = sorted(kam.glob(VZOR_MENA))
    except OSError:
        return None
    return subory[-1] if subory else None


def _zabezpec_priecinok(kam: Path) -> bool:
    """Da sa do `kam` pisat? Ked treba, prihlasi sa na NAS. Nikdy nevyhodi vynimku."""
    try:
        kam.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        pass
    if not prihlas_na_share(kam):
        return False
    try:
        kam.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _zapis_readme(kam: Path) -> None:
    """Vysvetlenie do priecinka. Ked uz tam je, nechava sa tak."""
    cesta = kam / README
    try:
        if cesta.exists():
            return
        cesta.write_text(_README_TEXT, encoding="utf-8")
    except OSError:
        # Zaloha samotna je dolezitejsia nez jej navod — chyba sa preskoci.
        pass


def uprac(kam: Path, nechat: int) -> int:
    """Zmaze najstarsie zalohy nad ramec `nechat`. Vracia, kolko ich zmizlo.

    Maze vyhradne subory podla `VZOR_MENA` — co si do priecinka odlozi clovek,
    sa nedotkne.
    """
    try:
        subory = sorted(kam.glob(VZOR_MENA))
    except OSError:
        return 0
    # nechat >= 1, takze pri kratsom zozname je vyrez prazdny a nemaze sa nic.
    zmazane = 0
    for stara in subory[:-nechat]:
        try:
            stara.unlink()
            zmazane += 1
        except OSError:
            continue
    return zmazane


def zalohuj(
    tracks: list[Track],
    *,
    kam: Path | None = None,
    teraz: datetime | None = None,
    hraje: Track | None = None,
    nechat: int | None = None,
) -> Vysledok:
    """Odlozi playlist na NAS, ak sa od poslednej zalohy zmenil.

    Nikdy nevyhodi vynimku — vracia `Vysledok`, ktory appka bud ukaze
    v stavovom riadku, alebo (pri nedostupnom NAS-e) mlcky zahodi.
    """
    if not zapnuta():
        return Vysledok("vypnute")
    if not tracks:
        # Prazdny playlist by prepisal historiu prazdnym suborom.
        return Vysledok("prazdny")

    kam = kam if kam is not None else priecinok()
    nechat = pocet_zaloh() if nechat is None else max(nechat, 1)
    teraz = teraz or datetime.now()

    if not _zabezpec_priecinok(kam):
        return Vysledok("nedostupne", detail=str(kam))

    novy = text_zalohy(tracks, teraz=teraz, hraje=hraje)
    posledna = posledna_zaloha(kam)
    if posledna is not None:
        try:
            stary_text = posledna.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stary_text = ""
        if stary_text and _rovnake(cesty_z_textu(stary_text), cesty_z_textu(novy)):
            return Vysledok("nezmenene", subor=posledna, pocet=len(tracks))

    cesta = kam / teraz.strftime(_FORMAT_MENA)
    docasny = cesta.with_name(cesta.name + ".tmp")
    try:
        docasny.write_text(novy, encoding="utf-8")
        docasny.replace(cesta)
    except OSError as exc:
        try:
            docasny.unlink()
        except OSError:
            pass
        return Vysledok("chyba", detail=str(exc))

    _zapis_readme(kam)
    return Vysledok("zapisane", subor=cesta, pocet=len(tracks), zmazane=uprac(kam, nechat))
