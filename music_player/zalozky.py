"""Zalozky v playliste — skladby, od ktorych sa da jednym klikom zacat hrat.

Zalozka je obycajne miesto v playliste. Tlacidlo "Zalozky" na nu skoci, pusti
ju a prehravanie potom pokracuje normalne dalej, kym ho clovek nezastavi alebo
playlist nedohra (vtedy plati vypnutie/uspanie po skonceni ako vzdy). Na rozdiel
od "Spanku" sa do playlistu nic nepridava a zalozka po prehrati ostava tam, kde
bola — da sa na nu vratit hoci kazdy den.

Pamata si cestu k suboru AJ poziciu v playliste. Cesta sama nestaci, lebo ta ista
skladba moze byt v playliste viackrat; pozicia sama nestaci, lebo pridavanie
a presuvanie playlist posuva. Plati teda vyskyt cesty najblizsie k ulozenej
pozicii, a PlayerController poziciu po kazdej zmene playlistu dorovna.

Uklada sa do `state.json` vedla playlistu — playlist ma kazdy notebook svoj, takze
zalozky do neho tiez patria lokalne, nie na NAS.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Zalozka:
    path: str
    # Posledna znama pozicia v playliste. -1 = nevedno (skladba z playlistu
    # zmizla skor, nez sa pozicia stihla dorovnat).
    index: int = -1

    @classmethod
    def from_dict(cls, payload: dict) -> "Zalozka":
        path = str(payload.get("path", "")).strip()
        if not path:
            raise ValueError("Zalozka bez cesty")
        try:
            index = int(payload.get("index", -1))
        except (TypeError, ValueError):
            index = -1
        return cls(path=path, index=index)

    def to_dict(self) -> dict:
        return {"path": self.path, "index": self.index}


def najdi(paths: list[str], zalozka: Zalozka) -> int:
    """Index skladby zalozky v playliste, -1 ked tam uz nie je.

    Cesty sa porovnavaju bez ohladu na velkost pismen — Windows ich tak berie
    a zvysok prehravaca (spankove zoznamy, historia) tiez.
    """
    ciel = zalozka.path.lower()
    if 0 <= zalozka.index < len(paths) and paths[zalozka.index].lower() == ciel:
        return zalozka.index
    najblizsi = -1
    for i, path in enumerate(paths):
        if path.lower() != ciel:
            continue
        if najblizsi < 0 or abs(i - zalozka.index) < abs(najblizsi - zalozka.index):
            najblizsi = i
    return najblizsi
