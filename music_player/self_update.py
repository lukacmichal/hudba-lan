"""Aktualizacia prehravaca z NAS-u.

Appka nelezi stale na tom istom notebooku (pozri README) a nova verzia sa
donedavna kopirovala rucne — co znamenalo, ze na druhom stroji bola vzdy
starsia. Odtialto si ju appka vezme sama, rovnako, ako to robi androidovy
klient:

    \\\\nas.local\\Android\\PlayerPC\\
        latest.json                 manifest — verzia, meno ZIP-u, SHA-256
        metalmusic-pc-<verzia>.zip  cela appka

Postup je zamerne rovnaky ako v docs/shared-standard.md kap. 2.4:

1. Pri starte sa cita IBA `latest.json` (par stoviek bajtov). ZIP sa nesahuje.
2. Ked je na NAS-e vyssi `versionCode`, appka sa OPYTA. Nikdy neinstaluje sama.
3. Az po potvrdeni sa stiahne ZIP a overi sa jeho SHA-256. Nesediaci subor sa
   zahodi — polovicne stiahnuty archiv by rozbil instalaciu.
4. Nedostupny NAS = ticho. Mimo domu appka o NAS-e nesmie nadavat.

Share `Android` bez prihlasenia neda ani citanie, takze appka sa musi na NAS
dostat. Ziadne heslo ale v sebe nema — hlada ho v tomto poradi:

1. Priamo precita subor. Funguje vzdy, ked ma Windows k NAS-u ulozene
   poverenie (Spravca poverení / "zapamätať prihlasovacie údaje" v Prieskumnikovi)
   alebo ked na server uz existuje relacia.
2. Ked to nevyjde, skusi sa prihlasit udajmi z `nas-credentials.local` —
   vedla appky alebo v `C:\\NAS`. To je jediny subor s heslami v celom stroji
   a do gitu ani do balika na NAS nepatri.
3. Ked ani to nie, kontrola sa TICHO preskoci.

Na druhom notebooku, kde `nas-credentials.local` nie je, poverenie ulozi
instalator (`nas\\nainstaluj.ps1`) do Spravcu poverení — potom staci bod 1.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from music_player import __version__, __version_code__
from music_player.config_loader import load_config

# Korenovy priecinok instalacie — tam, kde lezi app.pyw a config.txt.
KOREN = Path(__file__).resolve().parent.parent

PREDVOLENY_ZDROJ = r"\\nas.local\Android\PlayerPC"
MANIFEST = "latest.json"
APLIKATOR = "aktualizuj.ps1"
LOG = Path(tempfile.gettempdir()) / "metalplayer-update.log"

# Subory, ktore sa pri aktualizacii NEPREPISU, ak uz v instalacii su.
#
# config.txt ma v sebe DeepL kluc a cestu k hudbe, spankove zoznamy su ciste
# osobne data. Keby ich update prepisal verziou z NAS-u, clovek by po kazdom
# vydani nastavoval appku odznova. Ked ale niektory z nich CHYBA (cerstva
# instalacia na novom notebooku), vezme sa ten z balika — vtedy je to vzor,
# nie prepisanie.
CHRANENE_MENA = {"config.txt", "spanok.m3u", "spanok2.m3u"}
# .lnk nesie absolutnu cestu (obnovi ho vytvor-skratku.cmd), .local su
# poverenia, ktore do balika nikdy nepatria.
CHRANENE_PRIPONY = {".lnk", ".local"}


class ChybaAktualizacie(RuntimeError):
    """Aktualizaciu sa nepodarilo dokoncit a clovek sa to ma dozvediet.

    Nedostupny NAS medzi tieto pripady NEPATRI — ten je ticho.
    """


@dataclass(frozen=True)
class Manifest:
    kod: int
    verzia: str
    zip: str
    sha256: str
    poznamka: str = ""
    datum: str = ""

    @property
    def popis(self) -> str:
        """Verzia sa vzdy uvadza ako `nazov (kod)` — bez kodu sa neda odhalit
        zabudnute zvysenie versionCode."""
        return f"{self.verzia} ({self.kod})"


def popis_lokalnej_verzie() -> str:
    return f"{__version__} ({__version_code__})"


# -- konfiguracia -------------------------------------------------------------
def zdroj() -> Path:
    """Priecinok na NAS-e, z ktoreho sa aktualizuje."""
    hodnota = load_config().get("UPDATE_ZDROJ", "").strip() or PREDVOLENY_ZDROJ
    return Path(os.path.expandvars(hodnota))


def kontrola_pri_starte() -> bool:
    hodnota = load_config().get("UPDATE_KONTROLA", "ano").strip().lower()
    return hodnota not in {"nie", "no", "0", "false", "vypnute"}


# -- pristup na NAS -----------------------------------------------------------
# Poradie hladania hesla. Prve miesto je pre pripad, ze by appka niekedy bezala
# na stroji bez C:\NAS; druhe je to jedine, kde heslo naozaj je.
SUBORY_S_POVERENIAMI = (
    KOREN / "nas-credentials.local",
    Path(r"nas-credentials.local"),
)


def _poverenia() -> tuple[str, str] | None:
    for subor in SUBORY_S_POVERENIAMI:
        try:
            text = subor.read_text(encoding="utf-8")
        except OSError:
            continue
        udaje: dict[str, str] = {}
        for riadok in text.splitlines():
            riadok = riadok.strip()
            if riadok.startswith("#") or "=" not in riadok:
                continue
            kluc, _, hodnota = riadok.partition("=")
            udaje[kluc.strip()] = hodnota.strip()
        if udaje.get("NAS_USER") and udaje.get("NAS_PASS"):
            return udaje["NAS_USER"], udaje["NAS_PASS"]
    return None


def _share(priecinok: Path) -> str:
    """Zo `\\\\server\\share\\podpriecinok` vytiahne `\\\\server\\share`.

    `net use` sa prihlasuje na share, nie na podpriecinok. Ked cesta nie je
    sietova (test na lokalnom priecinku), vrati prazdny retazec.
    """
    disk = PureWindowsPath(priecinok).drive
    return disk if disk.startswith("\\\\") else ""


def _je_citatelny(cesta: Path) -> bool:
    try:
        return cesta.exists()
    except OSError:
        return False


def prihlas_na_share(priecinok: Path) -> bool:
    """`net use` na share, do ktoreho `priecinok` patri. Nikdy nevyhodi vynimku.

    Vracia True, ked sa prihlasenie vobec dalo skusit (siet + heslo), nie ci
    sa podarilo — to sa pozna az tym, ze cesta zacne fungovat. Volajuci si
    preto po tomto MUSI cestu znova overit.

    Pouziva to aj zaloha playlistu (`zaloha_playlistu`), preto je to zvlast a
    nie zapichnute v `zabezpec_pristup`: ta overuje citatelnost manifestu,
    zaloha naopak potrebuje zapis do priecinka, ktory este nemusi existovat.
    """
    share = _share(priecinok)
    poverenia = _poverenia()
    if not share or not poverenia:
        return False
    meno, heslo = poverenia
    try:
        subprocess.run(
            ["net", "use", share, heslo, f"/user:{meno}", "/persistent:no"],
            capture_output=True,
            timeout=30,
            # Prehravac bezi bez konzoly; bez tohto by pri kazdej kontrole
            # bliklo cierne okno.
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    # Navratovy kod net.exe sa zamerne neposudzuje: chyba 1219 ("na server uz
    # existuje spojenie s inymi udajmi") znamena, ze pristup uz mame.
    return True


# Port, na ktorom pocuva SMB. Sluzi len na otazku "je server na dosah?" — na
# nic sa cez neho neposiela.
SMB_PORT = 445


def server_odpoveda(priecinok: Path, sekund: float = 1.5) -> bool:
    """Da sa vobec otvorit spojenie na server z tejto cesty?

    Rozlisuje dva pripady, ktore boli do 6. 9. 2026 jeden jediny — "nedostupny
    NAS" — a preto o tom druhom appka roky mlcala:

      * server NEODPOVEDA  = si mimo domu. Mlcat je spravne.
      * server ODPOVEDA, ale manifest sa neda precitat = share nepusti (chyba
        poverenie). Vtedy sa appka **uz nikdy sama neaktualizuje** a clovek sa
        to ma dozvediet, lebo inak mu druhy notebook ticho zostarne.

    Nikdy nevyhodi vynimku; ked cesta nie je sietova, vrati False.
    """
    share = _share(priecinok)
    if not share:
        return False
    # \\server\share -> server
    host = share.strip("\\").split("\\")[0]
    if not host:
        return False
    try:
        with socket.create_connection((host, SMB_PORT), timeout=sekund):
            return True
    except OSError:
        return False


def zabezpec_pristup(priecinok: Path) -> bool:
    """Zaruci, ze sa da citat z `priecinok`. Nikdy nevyhodi vynimku.

    Najprv skusi citat rovno — na stroji s ulozenym poverenim (Spravca
    poverení, alebo uz otvorena relacia) to staci a nic sa nedeje. Az ked to
    nevyjde, prihlasi sa udajmi z nas-credentials.local.
    """
    if _je_citatelny(priecinok / MANIFEST):
        return True
    if not prihlas_na_share(priecinok):
        return False
    return _je_citatelny(priecinok / MANIFEST)


# -- manifest -----------------------------------------------------------------
def nacitaj_manifest(text: str) -> Manifest | None:
    """Manifest z textu, alebo None ked je nepouzitelny.

    Prisne: chybajuce alebo nezmyselne pole znamena, ze sa neaktualizuje.
    Radsej neponuknut nic nez stiahnut nieco, co sa neda overit.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        kod = int(data["versionCode"])
    except (KeyError, TypeError, ValueError):
        return None
    verzia = str(data.get("versionName", "")).strip()
    subor = str(data.get("zip", "")).strip()
    sha = str(data.get("sha256", "")).strip().lower()
    if not verzia or not subor or len(sha) != 64:
        return None
    # Meno suboru z manifestu sa sklada s cestou k NAS-u, takze z toho
    # priecinka nesmie ukazovat von.
    if "/" in subor or "\\" in subor or subor.startswith("."):
        return None
    return Manifest(
        kod=kod,
        verzia=verzia,
        zip=subor,
        sha256=sha,
        poznamka=str(data.get("notes", "") or "").strip(),
        datum=str(data.get("date", "") or "").strip(),
    )


def zisti(z: Path | None = None) -> Manifest | None:
    """Precita manifest z NAS-u. Nedostupny NAS vrati None, nie vynimku."""
    priecinok = z if z is not None else zdroj()
    if not zabezpec_pristup(priecinok):
        return None
    try:
        text = (priecinok / MANIFEST).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    return nacitaj_manifest(text)


def je_novsia(m: Manifest, lokalny_kod: int = __version_code__) -> bool:
    return m.kod > lokalny_kod


# -- stiahnutie a priprava ----------------------------------------------------
def _sha256(cesta: Path) -> str:
    h = hashlib.sha256()
    with cesta.open("rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def je_chraneny(meno: str) -> bool:
    return meno.lower() in CHRANENE_MENA or Path(meno).suffix.lower() in CHRANENE_PRIPONY


def _koren_rozbaleneho(kam: Path) -> Path:
    """ZIP sa robi bez vrchneho priecinka, ale keby ho niekto raz zabalil aj
    s nim, nech to nekonci instalaciou priecinka do priecinka."""
    polozky = list(kam.iterdir())
    if len(polozky) == 1 and polozky[0].is_dir():
        return polozky[0]
    return kam


def odstran_chranene(priprava: Path, ciel: Path) -> list[str]:
    """Z pripraveneho stromu vyhodi subory, ktore sa v instalacii nesmu prepisat.

    Vracia ich mena — appka ich vypise, nech clovek vie, ze jeho config.txt
    update nechal tak.
    """
    ponechane: list[str] = []
    for polozka in list(priprava.rglob("*")):
        if not polozka.is_file():
            continue
        if not je_chraneny(polozka.name):
            continue
        if (ciel / polozka.relative_to(priprava)).exists():
            polozka.unlink()
            ponechane.append(polozka.name)
    return sorted(ponechane)


def priprav(m: Manifest, z: Path | None = None, ciel: Path = KOREN) -> tuple[Path, list[str]]:
    """Stiahne ZIP, overi SHA-256 a rozbali ho do docasneho priecinka.

    Vracia (priecinok pripraveny na skopirovanie, ponechane osobne subory).
    Instalacie sa este nedotyka — to robi az `spusti_aplikator`.
    """
    priecinok = z if z is not None else zdroj()
    if not zabezpec_pristup(priecinok):
        raise ChybaAktualizacie(f"Na NAS sa nedostanem: {priecinok}")
    docasny = Path(tempfile.mkdtemp(prefix="metalplayer-update-"))
    lokalny_archiv = docasny / m.zip
    try:
        shutil.copy2(priecinok / m.zip, lokalny_archiv)
    except OSError as exc:
        shutil.rmtree(docasny, ignore_errors=True)
        raise ChybaAktualizacie(f"Balik sa nepodarilo stiahnut: {exc}") from exc

    skutocna = _sha256(lokalny_archiv)
    if skutocna != m.sha256:
        shutil.rmtree(docasny, ignore_errors=True)
        raise ChybaAktualizacie(
            "Kontrolny sucet nesedi - balik je poskodeny alebo neuplny.\n"
            f"cakal som {m.sha256}\nprisiel   {skutocna}"
        )

    rozbalene = docasny / "rozbalene"
    try:
        with zipfile.ZipFile(lokalny_archiv) as zf:
            zf.extractall(rozbalene)
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(docasny, ignore_errors=True)
        raise ChybaAktualizacie(f"Balik sa nepodarilo rozbalit: {exc}") from exc
    lokalny_archiv.unlink()

    koren = _koren_rozbaleneho(rozbalene)
    ponechane = odstran_chranene(koren, ciel)
    return koren, ponechane


def spusti_aplikator(priprava: Path, ciel: Path = KOREN) -> None:
    """Odovzda dokoncenie samostatnemu procesu a vrati sa.

    Prepisat vlastne .py subory za behu sa da, ale rozbehnuty proces uz bezi
    zo starych — a keby sa kopirovanie v polovici zaseklo, appka by ostala
    zmiesana z dvoch verzii. Skript preto pocka, kym sa appka ukonci, az potom
    kopiruje a nakoniec ju spusti spat.

    Aplikator sa kopiruje MIMO instalacneho priecinka — inak by prepisoval
    subor, z ktoreho prave bezi.
    """
    skript = ciel / APLIKATOR
    if not skript.exists():
        raise ChybaAktualizacie(f"Chyba {skript} - bez neho sa update nema ako dokoncit.")
    prenosny = priprava.parent / APLIKATOR
    shutil.copy2(skript, prenosny)

    powershell = shutil.which("powershell") or str(
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    prikaz = [
        powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden", "-File", str(prenosny),
        "-ProcesId", str(os.getpid()),
        "-Zdroj", str(priprava),
        "-Ciel", str(ciel),
        "-Spustit", str(ciel / "spustit.cmd"),
        "-Log", str(LOG),
    ]
    # CREATE_NO_WINDOW, nie DETACHED_PROCESS: prehravac bezi ako pythonw.exe
    # bez konzoly a s DETACHED_PROCESS by powershell.exe nemal ziadnu ani si ju
    # nesmel vytvorit — proces sa spusti a HNED zomrie, bez chyby a bez zaznamu
    # v logu (aktualizacia potom mlcky nespravi nic). Overene 2. 9. 2026.
    # CREATE_NO_WINDOW da procesu vlastnu skrytu konzolu, takze bezi; ukoncenie
    # rodica ho nezabije, Windows deti pri smrti rodica neuklada.
    priznaky = 0
    if sys.platform == "win32":
        priznaky = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        prikaz,
        cwd=str(priprava.parent),
        creationflags=priznaky,
        close_fds=True,
    )
