"""Nakresli ikony tlacidiel do listy Firefoxu (⏮ ⏯ ⏭ 🔊 🔇).

Kreslene vektorovo cez PySide6 (to iste, na com bezi prehravac), aby boli
ostre v 16 aj 32 px — emoji by sa v liste vykreslilo rozne podla systemu.
Farba je akcent prehravaca, citatelna na tmavej aj svetlej liste.

    python kresli_ikony.py        -> ikony/<meno>-<velkost>.png
"""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF

FARBA = QColor("#f0b44c")
VELKOSTI = (16, 32, 48, 96)
CIEL = Path(__file__).resolve().parent / "ikony"


def trojuholnik(p: QPainter, body):
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in body]))


def prev(p):
    p.drawRect(QRectF(6, 7, 3.5, 18))
    trojuholnik(p, [(26, 7), (26, 25), (10, 16)])


def next_(p):
    trojuholnik(p, [(6, 7), (6, 25), (22, 16)])
    p.drawRect(QRectF(22.5, 7, 3.5, 18))


def play(p):
    trojuholnik(p, [(9, 6), (9, 26), (26, 16)])


def pause(p):
    p.drawRect(QRectF(8, 7, 5.5, 18))
    p.drawRect(QRectF(18.5, 7, 5.5, 18))


def reproduktor(p):
    trojuholnik(p, [(4, 12), (9, 12), (16, 6), (16, 26), (9, 20), (4, 20)])


def zvuk(p):
    reproduktor(p)
    pero = QPen(FARBA, 2.4)
    pero.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pero)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for r in (5.5, 10):
        cesta = QPainterPath()
        cesta.arcMoveTo(QRectF(16 - r, 16 - r, 2 * r, 2 * r), -45)
        cesta.arcTo(QRectF(16 - r, 16 - r, 2 * r, 2 * r), -45, 90)
        p.drawPath(cesta)


def ticho(p):
    reproduktor(p)
    pero = QPen(FARBA, 2.6)
    pero.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pero)
    p.drawLine(QPointF(20, 12), QPointF(28, 20))
    p.drawLine(QPointF(28, 12), QPointF(20, 20))


IKONY = {"prev": prev, "next": next_, "play": play, "pause": pause, "zvuk": zvuk, "ticho": ticho}


def main():
    QGuiApplication.instance() or QGuiApplication([])
    CIEL.mkdir(exist_ok=True)
    for meno, kresli in IKONY.items():
        for velkost in VELKOSTI:
            obr = QImage(velkost, velkost, QImage.Format.Format_ARGB32)
            obr.fill(Qt.GlobalColor.transparent)
            p = QPainter(obr)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(velkost / 32, velkost / 32)   # kreslime v mriezke 32 x 32
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(FARBA)
            kresli(p)
            p.end()
            obr.save(str(CIEL / f"{meno}-{velkost}.png"))
    print(f"{len(IKONY) * len(VELKOSTI)} ikon v {CIEL}")


if __name__ == "__main__":
    main()
