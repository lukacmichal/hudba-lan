r"""Poriadok v nazvoch albumovych priecinkov.

Archivy zo sceny prichadzaju pomenovane vselijako:

    Dark Plague`2026`Masquerade by necroscum
    Band_-_Album_-_2026
    Band-Album-2026-GROUP
    Band - Album (2026) [FLAC]

Rozbalene sa to potom v C:\data\mp3 neda ani zoradit, ani precitat. Preto sa
nazov pred rozbalenim prevedie na jeden tvar:

    Interpret - Album - Rok

Ked sa nazvu rozumiet neda, NECHAVA SA TAK. Zle uhadnuty interpret je horsi
nez povodny neporiadok — ten sa aspon da precitat a opravit rucne.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass

#: Rok musi byt aj hodnoverny. `1999` je rok, `2999` je cislo v nazve albumu.
_NAJSTARSI_ROK = 1950


def _najnovsi_rok() -> int:
    # Rok dopredu: albumy sa na scenu dostavaju aj pred oficialnym vydanim.
    return dt.date.today().year + 1


_ROK = re.compile(r"^(?:19|20)\d{2}$")
_ROK_V_ZATVORKE = re.compile(r"[\(\[\{]\s*((?:19|20)\d{2})\s*[\)\]\}]")
_ZATVORKA = re.compile(r"[\(\[\{]([^\(\)\[\]\{\}]*)[\)\]\}]")
_VIAC_MEDZIER = re.compile(r"\s{2,}")

#: Tokeny, ktore hovoria o balicku, nie o hudbe. V zatvorke sa zahadzuju.
#: Zamerne tu NIE su "reissue", "remaster", "deluxe", "live" ani "demo" — to
#: su rozne vydania toho isteho albumu a v nazve priecinka patria.
_BALIACE = {
    "flac", "mp3", "wav", "ape", "m4a", "aac", "ogg", "opus",
    "web", "webrip", "cd", "cdrip", "cda", "vinyl", "vinylrip", "scene",
    "lossless", "320", "320kbps", "256", "192", "v0", "v2", "vbr", "cbr",
    "16bit", "24bit", "24bit-96khz", "hi-res", "rip", "eac", "log", "cue",
}

#: Pripony archivov — ked sa nazov berie z mena suboru, nema tam ostat.
_PRIPONY = {".rar", ".zip", ".7z", ".tar", ".gz"}


@dataclass(frozen=True)
class Nazov:
    interpret: str
    album: str
    rok: int | None = None

    @property
    def text(self) -> str:
        zaklad = f"{self.interpret} - {self.album}"
        return f"{zaklad} - {self.rok}" if self.rok else zaklad


def bez_diakritiky(text: str) -> str:
    """`Boötes` -> `Bootes`. Nazov priecinka byva bez diakritiky, zoznam s nou.

    Rovnaky prevod robi aj `metal_archives._normalize_text` pred hladanim na MA
    — tam preto, ze MA na diakritiku v hladani nereaguje dobre.
    """
    rozlozene = unicodedata.normalize("NFKD", str(text or ""))
    holy = "".join(z for z in rozlozene if not unicodedata.combining(z))
    return holy.translate(str.maketrans("\u0167\u0166\u0111\u0110\u0142\u0141\u00f8\u00d8\u00e6\u00c6\u0153\u0152\u00df\u00fe\u00de",
                                        "tTdDlLoOaAoOstT"))


def slova(text: str) -> list[str]:
    """Nazov na porovnatelne slova: male pismena, bez diakritiky, bez interpunkcie."""
    return re.findall(r"[0-9a-z]+", bez_diakritiky(text).casefold())


def _je_rok(text: str) -> bool:
    if not _ROK.match(text.strip()):
        return False
    return _NAJSTARSI_ROK <= int(text) <= _najnovsi_rok()


def _upratat(text: str) -> str:
    """Zvysne medzery, bodky a pomlcky na krajoch."""
    return _VIAC_MEDZIER.sub(" ", text.replace("_", " ")).strip(" .-–—")


def _bez_pripony(text: str) -> str:
    for pripona in _PRIPONY:
        if text.lower().endswith(pripona):
            return text[: -len(pripona)]
    return text


def _bez_baliacich(text: str) -> str:
    """Vyhodi zatvorky, v ktorych je len rec o formate: [FLAC], (WEB), [320kbps]."""
    def posud(m: re.Match) -> str:
        vnutro = m.group(1).strip().lower()
        if not vnutro:
            return ""
        slova = re.split(r"[\s,;/|+-]+", vnutro)
        return "" if slova and all(s in _BALIACE for s in slova if s) else m.group(0)

    return _ZATVORKA.sub(posud, text)


def _bez_releasera(text: str) -> str:
    """Zahodi koncove `by necroscum` — meno toho, kto to nahral na forum.

    Len jedno slovo za `by`: album sa naozaj moze volat „Songs By The Dead"
    a taky nazov sa oklestit nesmie.
    """
    m = re.search(r"\s+by\s+([^\s]+)\s*$", text, flags=re.IGNORECASE)
    if not m:
        return text
    return text[: m.start()]


def _vyber_rok(casti: list[str]) -> tuple[list[str], int | None]:
    """Vytiahne rok - samostatnou castou aj zo zatvorky vnutri casti."""
    zvysok: list[str] = []
    rok: int | None = None
    for cast in casti:
        holy = cast.strip()
        if rok is None and _je_rok(holy):
            rok = int(holy)
            continue
        m = _ROK_V_ZATVORKE.search(holy)
        if m and rok is None and _je_rok(m.group(1)):
            rok = int(m.group(1))
            holy = (holy[: m.start()] + " " + holy[m.end():])
        zvysok.append(holy)
    return zvysok, rok


def _rozdel(text: str) -> tuple[list[str], bool]:
    """Rozdeli nazov na casti. Druha hodnota hovori, ci bol oddelovac spolahlivy.

    Spätny apostrof aj ` - ` su jednoznacne oddelovace. Holá pomlcka bez medzier
    nie je — `Blind-Guardian` je meno kapely, nie dve casti — preto sa pri nej
    vysledok berie len vtedy, ked z neho vyjde presne interpret a album.
    """
    if "`" in text:
        return [c for c in text.split("`") if c.strip()], True
    if " - " in text:
        return [c for c in text.split(" - ") if c.strip()], True
    if " – " in text:      # dlha pomlcka, chodi z web stranok
        return [c for c in text.split(" – ") if c.strip()], True
    if text.count("-") >= 2:
        return [c for c in text.split("-") if c.strip()], False
    return [text], True


def rozober(surovy: str) -> Nazov | None:
    """Interpret, album a rok z nazvu priecinka. `None` = nerozumiem tomu."""
    text = _bez_pripony(str(surovy or "").strip())
    if not text:
        return None
    # Podtrzitka namiesto medzier: `Band_-_Album_-_2026`. Prepisuju sa len ked
    # v nazve nie su medzery — inak by sa rozbil album s podtrzitkom v nazve.
    if " " not in text and "_" in text:
        text = text.replace("_", " ")
    text = _bez_releasera(_bez_baliacich(text))

    casti, spolahlivy = _rozdel(text)
    casti, rok = _vyber_rok(casti)
    casti = [c for c in (_upratat(c) for c in casti) if c]
    if len(casti) < 2:
        return None
    if len(casti) > 2 and not spolahlivy:
        # `A-B-C-2026-GROUP` — kde konci album a zacina meno skupiny sa uhadnut
        # neda. Radsej nechat povodny nazov.
        return None
    return Nazov(casti[0], " - ".join(casti[1:]), rok)


def rozlozenie(surovy: str) -> tuple[list[str], int | None]:
    """Slova nazvu (bez roku, pripony a baliacich ozdob) a rok, ked sa nasiel.

    Toto je to, s cim sa porovnava zoznam noviniek aj diskografia z MA:
    `Blind-Guardian-Somewhere-2026-GRP` -> (["blind","guardian","somewhere","grp"], 2026).
    Meno vydavajucej skupiny (`GRP`) sa nezahadzuje — nedá sa spolahlivo
    rozoznat od slova v nazve albumu. Pri porovnavani neprekaza: rozhoduje, ci
    su slova z MA obsiahnute TU, nie naopak.
    """
    text = _bez_pripony(str(surovy or "").strip())
    if " " not in text and "_" in text:
        text = text.replace("_", " ")
    text = _bez_releasera(_bez_baliacich(text))
    casti, _ = _rozdel(text)
    casti, rok = _vyber_rok(casti)
    return [s for cast in casti for s in slova(cast)], rok


def najdi_v_zozname(surovy: str, kandidati) -> Nazov | None:
    """Najde v `kandidati` dvojicu (kapela, album), ktora v nazve naozaj je.

    `kandidati` je cokolvek, co da dvojice mien — zoznam noviniek z NAS-u aj
    diskografia z Metal Archives. Uznava sa len zhoda, pri ktorej su VSETKY
    slova kapely aj albumu v nazve priecinka; trailing smeti (meno skupiny,
    `by necroscum`) tak neprekazaju. Z viacerych vyhrava tá, ktora pokryje
    najviac slov — `Forever` aj `Forever Blue` sedia, ale to druhé je urcitejsie.

    Vracia `None`, ked nesedi nic. Tipovat sa nema: povodny nazov je vzdy
    lepsi nez cudzia kapela v nazve priecinka.
    """
    v_nazve, rok = rozlozenie(surovy)
    if not v_nazve:
        return None
    zasoba = set(v_nazve)

    najlepsi, najlepsie_skore = None, (0, 0)
    for kapela, album in kandidati:
        k, a = slova(kapela), slova(album)
        if not k or not a:
            continue
        if not zasoba.issuperset(k) or not zasoba.issuperset(a):
            continue
        # ROZNE pokryte slova, nie ich sucet: kapela Dysphorectomy ma
        # samotitulny album a ten by inak dostal rovnake skore ako spravny
        # "Forever" (1+1) a vyhral by poradim v diskografii.
        skore = (len(set(k) | set(a)), len(a))
        if skore > najlepsie_skore:
            najlepsi, najlepsie_skore = Nazov(kapela, album, rok), skore
    return najlepsi


def uprav(surovy: str) -> str:
    """`Interpret - Album - Rok`, alebo povodny nazov, ked sa mu neda rozumiet."""
    rozobrany = rozober(surovy)
    if rozobrany is None:
        return str(surovy or "").strip() or str(surovy)
    return rozobrany.text


def kluc(interpret: str, album: str) -> str:
    """Identita albumu pre porovnanie s novinkami zo skenu.

    Musi sediet s `kluc` v `metal-novinky` (kapela|album, male pismena), ale
    navyse zahadzuje interpunkciu: v nazve priecinka sa `&` casto pise ako
    `and` a apostrofy vypadavaju uplne.
    """
    def bez_interpunkcie(text: str) -> str:
        return " ".join(slova(str(text or "").replace("&", " and ")))

    return f"{bez_interpunkcie(interpret)}|{bez_interpunkcie(album)}"
