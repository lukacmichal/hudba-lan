"""Okno so statistikou pocuvania (tlacidlo "Statistika")."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from music_player.statistika import OBDOBIA, Riadok

_ROLA_CESTA = Qt.ItemDataRole.UserRole + 1


def _cas(ms: int) -> str:
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min {s:02d} s"


def _datum(kedy: float) -> str:
    return datetime.fromtimestamp(kedy).strftime("%d. %m. %Y %H:%M") if kedy else ""


class StatistikaOkno(QDialog):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._stat = controller.statistika
        self.setWindowTitle("Štatistika počúvania")
        self.resize(820, 600)

        layout = QVBoxLayout(self)
        horna = QHBoxLayout()
        horna.addWidget(QLabel("Obdobie:"))
        self._obdobie = QComboBox()
        for popis, dni in OBDOBIA:
            self._obdobie.addItem(popis, dni)
        self._obdobie.currentIndexChanged.connect(self._obnov)
        horna.addWidget(self._obdobie)
        horna.addStretch(1)
        self._suhrn = QLabel("")
        horna.addWidget(self._suhrn)
        layout.addLayout(horna)

        self._zalozky = QTabWidget()
        self._skladby = self._tabulka(["#", "Skladba", "Prehraté", "Naposledy"])
        self._interpreti = self._tabulka(["#", "Interpret", "Prehraté", "Naposledy"])
        self._albumy = self._tabulka(["#", "Album", "Prehraté", "Naposledy"])
        self._historia = self._tabulka(["Kedy", "Skladba", "Spolu", ""])
        self._zalozky.addTab(self._skladby, "Skladby")
        self._zalozky.addTab(self._interpreti, "Interpreti")
        self._zalozky.addTab(self._albumy, "Albumy")
        self._zalozky.addTab(self._historia, "História")
        layout.addWidget(self._zalozky)

        pomoc = QLabel(
            "Dvojklik na skladbu ju pridá na koniec playlistu. Prehratie sa počíta, "
            "keď skladba reálne hrala 30 s (krátka 30 % dĺžky) — preskočené sa "
            f"nerátajú. Každý notebook má vlastnú databázu: {self._stat.cesta}"
        )
        pomoc.setWordWrap(True)
        pomoc.setStyleSheet("color: #a08060; font-size: 11px;")
        layout.addWidget(pomoc)

        tlacidla = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        tlacidla.rejected.connect(self.reject)
        layout.addWidget(tlacidla)

        for t in (self._skladby, self._historia):
            t.itemDoubleClicked.connect(self._pridaj_do_playlistu)
        self._obnov()

    def _tabulka(self, hlavicky: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(hlavicky))
        t.setHorizontalHeaderLabels(hlavicky)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        return t

    def _napln(self, t: QTableWidget, riadky: list[Riadok], *, historia: bool = False) -> None:
        t.setRowCount(len(riadky))
        for i, r in enumerate(riadky):
            if historia:
                bunky = [_datum(r.naposledy), r.popis, "", ""]
            else:
                bunky = [str(i + 1), r.popis, str(r.pocet), _datum(r.naposledy)]
            for j, text in enumerate(bunky):
                item = QTableWidgetItem(text)
                if j in (0, 2) and not historia:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if r.cesta:
                    item.setData(_ROLA_CESTA, r.cesta)
                    item.setToolTip(r.cesta)
                t.setItem(i, j, item)
        if historia:
            # "Spolu" = kolkokrat skladba hrala celkovo, aby bolo vidiet, ci je
            # to stala klasika alebo jednorazovka.
            for i, r in enumerate(riadky):
                t.item(i, 2).setText(str(self._stat.pocet(r.cesta)))

    def _obnov(self) -> None:
        dni = self._obdobie.currentData()
        self._napln(self._skladby, self._stat.skladby(dni))
        self._napln(self._interpreti, self._stat.interpreti(dni))
        self._napln(self._albumy, self._stat.albumy(dni))
        self._napln(self._historia, self._stat.historia(), historia=True)
        n, rozne, ms = self._stat.suhrn(dni)
        self._suhrn.setText(f"{n} prehratí · {rozne} rôznych skladieb · {_cas(ms)}")

    def _pridaj_do_playlistu(self, item: QTableWidgetItem) -> None:
        cesta = item.data(_ROLA_CESTA)
        if not cesta:
            return
        pridane, _ = self._controller.add_paths([cesta])
        if not pridane:
            self._suhrn.setText("Súbor už na disku nie je — nepridal som nič.")
        else:
            self._suhrn.setText(f"Pridané do playlistu: {item.tableWidget().item(item.row(), 1).text()}")
