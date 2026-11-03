"""Okno „🪟 Windows" — napojenie prehravaca na Windows a Firefox.

Prepinace sa zapisu do config.txt (POZADIE_PLOCHY, OVLADANIE_MEDII,
PANEL_ULOH), takze platia aj po restarte. Pri kazdej casti je jej stav —
na druhom notebooku je to jediny sposob, ako zistit, ci sa napr. kniznica
pre ovladanie medii naozaj doinstalovala.
"""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from music_player import firefox_rozsirenie
from music_player.integracia import farba_startu, farba_startu_popis

_STYL_POPIS = "color: #a08060; font-size: 11px;"
_STYL_STAV = "color: #d4b483; font-size: 12px;"


def _popis(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(_STYL_POPIS)
    return label


def _ciara() -> QFrame:
    ciara = QFrame()
    ciara.setFrameShape(QFrame.Shape.HLine)
    ciara.setStyleSheet("color: #3d3025;")
    return ciara


class WindowsOkno(QDialog):
    _firefox_hotovo = Signal(object, object)   # (baliky na NAS-e, nainstalovane)

    def __init__(self, integracia, parent=None) -> None:
        super().__init__(parent)
        self._i = integracia
        self.setWindowTitle("Napojenie na Windows a Firefox")
        self.resize(620, 640)
        layout = QVBoxLayout(self)

        # ── pozadie plochy ────────────────────────────────────────────────
        self._pozadie = QCheckBox("Pozadie plochy podľa albumu")
        self._pozadie.setChecked(integracia.pozadie_zapnute)
        self._pozadie.toggled.connect(integracia.nastav_pozadie)
        layout.addWidget(self._pozadie)
        layout.addWidget(_popis(
            "Keď hrá hudba, na ploche je obal albumu s interpretom, albumom a rokom. "
            "Tvoje pozadie sa vráti po zastavení, po pauze dlhšej ako 5 minút a pri "
            "ukončení prehrávača — aj keď prehrávač spadne, vráti ho pri ďalšom "
            "spustení. Pozadie, ktoré si medzitým zmeníš sám, nechá tak. Prezentáciu "
            "ani Windows Spotlight nemení."
        ))
        self._pozadie_stav = QLabel()
        self._pozadie_stav.setStyleSheet(_STYL_STAV)
        layout.addWidget(self._pozadie_stav)

        # ── farba Startu ──────────────────────────────────────────────────
        layout.addWidget(_ciara())
        layout.addWidget(QLabel("Farba Štartu a panela úloh podľa albumu"))
        layout.addWidget(_popis(
            "Toto robí Windows sám podľa pozadia plochy, prehrávač ti nastavenia "
            "nemení. V Nastaveniach → Prispôsobenie → Farby treba raz zapnúť: "
            "<b>Farba zvýraznenia: Automaticky</b> a <b>Zobraziť farbu zvýraznenia "
            "na Štarte a paneli úloh</b> (ide len pri tmavom režime Windows). "
            "Voliteľne aj <b>…na záhlaviach a okrajoch okien</b>."
        ))
        riadok = QHBoxLayout()
        self._farba_stav = QLabel()
        self._farba_stav.setStyleSheet(_STYL_STAV)
        self._farba_stav.setWordWrap(True)
        riadok.addWidget(self._farba_stav, 1)
        nastavenia = QPushButton("Otvoriť nastavenia farieb")
        nastavenia.clicked.connect(lambda: os.startfile("ms-settings:colors"))
        riadok.addWidget(nastavenia)
        layout.addLayout(riadok)

        # ── ovladanie medii ───────────────────────────────────────────────
        layout.addWidget(_ciara())
        self._media = QCheckBox("Ovládanie médií vo Windows")
        self._media.setChecked(integracia.media_zapnute)
        self._media.toggled.connect(integracia.nastav_media)
        layout.addWidget(self._media)
        layout.addWidget(_popis(
            "Okienko s obalom a tlačidlami pri zmene hlasitosti, prehrávač v Rýchlych "
            "nastaveniach (Win+A), mediálne klávesy ⏮ ⏯ ⏭ a tlačidlá na Bluetooth "
            "slúchadlách. Skratka Ctrl+Alt+Y funguje ďalej. Potrebuje knižnicu winrt — "
            "keď chýba, prehrávač si ju doinštaluje sám (raz, z internetu)."
        ))
        self._media_stav = QLabel()
        self._media_stav.setStyleSheet(_STYL_STAV)
        self._media_stav.setWordWrap(True)
        layout.addWidget(self._media_stav)

        # ── panel uloh ────────────────────────────────────────────────────
        layout.addWidget(_ciara())
        self._panel = QCheckBox("Tlačidlá ⏮ ⏯ ⏭ a priebeh skladby na paneli úloh")
        self._panel.setChecked(integracia.panel_zapnuty)
        self._panel.toggled.connect(integracia.nastav_panel)
        layout.addWidget(self._panel)
        layout.addWidget(_popis(
            "Keď je okno prehrávača otvorené, po prejdení myšou na jeho ikonu na paneli "
            "úloh sú pod náhľadom tlačidlá a ikona sa plní pásom priebehu skladby "
            "(pri pauze žltým). Zmena prepínača platí od ďalšieho spustenia."
        ))
        self._panel_stav = QLabel()
        self._panel_stav.setStyleSheet(_STYL_STAV)
        layout.addWidget(self._panel_stav)

        # ── Firefox ───────────────────────────────────────────────────────
        layout.addWidget(_ciara())
        layout.addWidget(QLabel("Firefox"))
        layout.addWidget(_popis(
            "Rozšírenie (pentagram v lište) od verzie 1.2 farbí Firefox podľa albumu "
            "a ukazuje obal. Firefox ho sám neaktualizuje — novú verziu treba raz "
            "potvrdiť tlačidlom „Pridať“ na každom notebooku."
        ))
        riadok = QHBoxLayout()
        self._firefox_stav = QLabel("Zisťujem, čo je vo Firefoxe…")
        self._firefox_stav.setStyleSheet(_STYL_STAV)
        self._firefox_stav.setWordWrap(True)
        riadok.addWidget(self._firefox_stav, 1)
        self._firefox_tlacidlo = QPushButton("Nainštalovať do Firefoxu")
        self._firefox_tlacidlo.setEnabled(False)
        self._firefox_tlacidlo.clicked.connect(self._instaluj_firefox)
        riadok.addWidget(self._firefox_tlacidlo)
        priecinok = QPushButton("Priečinok na NAS-e")
        priecinok.clicked.connect(self._otvor_priecinok)
        riadok.addWidget(priecinok)
        layout.addLayout(riadok)
        self._na_instalaciu: list = []

        layout.addStretch(1)
        tlacidla = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        tlacidla.rejected.connect(self.reject)
        layout.addWidget(tlacidla)

        self._firefox_hotovo.connect(self._ukaz_firefox)
        integracia.zmena.connect(self._obnov)
        self._casovac = QTimer(self)
        self._casovac.setInterval(1500)
        self._casovac.timeout.connect(self._obnov)
        self._casovac.start()
        self._obnov()
        self._zisti_firefox()

    def done(self, vysledok: int) -> None:
        try:
            self._i.zmena.disconnect(self._obnov)
        except (RuntimeError, TypeError):
            pass
        super().done(vysledok)

    # ── stav ──────────────────────────────────────────────────────────────
    def _obnov(self) -> None:
        stav = self._i.stav_pre_api()
        self._pozadie_stav.setText(f"Stav: {stav['pozadie']}")
        f = farba_startu()
        znak = "✓" if f["automaticka"] and f["naStarte"] and f["tmavy"] else "–"
        self._farba_stav.setText(f"{znak} {farba_startu_popis()}")
        media = stav["ovladanieMedii"]
        if stav["kniznica"] and stav["kniznica"] not in media:
            media = f"{media} ({stav['kniznica']})"
        self._media_stav.setText(f"Stav: {media}")
        self._panel_stav.setText(f"Stav: {stav['panelUloh']}")

    def _zisti_firefox(self) -> None:
        def zisti() -> None:
            na_nase = firefox_rozsirenie.na_nas()
            v_firefoxe = firefox_rozsirenie.nainstalovane()
            self._firefox_hotovo.emit(na_nase, v_firefoxe)

        threading.Thread(target=zisti, daemon=True, name="firefox-zisti").start()

    def _ukaz_firefox(self, na_nase, v_firefoxe) -> None:
        if v_firefoxe is None:
            self._firefox_stav.setText("Firefox (jeho profil) som na tomto počítači nenašiel.")
            return
        if not na_nase:
            self._firefox_stav.setText("NAS nie je dostupný — rozšírenia sa nedajú porovnať.")
            return
        hlavne = next((b for b in na_nase if b.id == firefox_rozsirenie.HLAVNE_ID), None)
        ma = v_firefoxe.get(firefox_rozsirenie.HLAVNE_ID)
        self._na_instalaciu = firefox_rozsirenie.treba_nainstalovat(na_nase, v_firefoxe)
        if hlavne is None:
            text = "Na NAS-e chýba hlavné rozšírenie."
        elif ma is None:
            text = f"Rozšírenie vo Firefoxe nie je. Na NAS-e je verzia {hlavne.verzia}."
        elif self._na_instalaciu:
            text = (f"Vo Firefoxe je {ma}, na NAS-e {hlavne.verzia}." if hlavne in self._na_instalaciu
                    else f"Hlavné rozšírenie {ma} je aktuálne, niektoré tlačidlá nie.")
        else:
            text = f"✓ Všetko aktuálne (hlavné rozšírenie {ma})."
        if self._na_instalaciu:
            text += " Chýba: " + ", ".join(b.nazov for b in self._na_instalaciu) + "."
        self._firefox_stav.setText(text)
        self._firefox_tlacidlo.setEnabled(bool(self._na_instalaciu))
        self._firefox_tlacidlo.setText(
            "Aktualizovať vo Firefoxe" if ma is not None else "Nainštalovať do Firefoxu")

    def _instaluj_firefox(self) -> None:
        chyba = firefox_rozsirenie.otvor_vo_firefoxe(self._na_instalaciu)
        if chyba:
            self._firefox_stav.setText(chyba)
            return
        self._firefox_stav.setText(
            f"Firefox sa otvoril s {len(self._na_instalaciu)} rozšíreniami — pri každom "
            "potvrď „Pridať“. Potom tu klikni znova na 🪟 Windows a over stav.")

    def _otvor_priecinok(self) -> None:
        from music_player.self_update import prihlas_na_share

        cesta = firefox_rozsirenie.NAS_PRIECINOK
        if not cesta.is_dir():
            prihlas_na_share(cesta)
        try:
            os.startfile(str(cesta))
        except OSError as exc:
            self._firefox_stav.setText(f"Priečinok sa nedá otvoriť: {exc}")
