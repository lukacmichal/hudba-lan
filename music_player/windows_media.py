"""Ovladanie medii vo Windows (System Media Transport Controls).

Vdaka tomu prehravac vidi Windows ako kazdy iny prehravac hudby:

* pri stlaceni hlasitosti alebo medialnej klavesy vyskoci okienko s obalom,
  nazvom a tlacidlami ⏮ ⏯ ⏭ (aj s posuvnikom vo Windows 11),
* je v Rychlych nastaveniach (Win+A) a na zamknutej obrazovke,
* funguju medialne klavesy Play/Pause, Dalsia, Predosla a tlacidla na
  Bluetooth sluchadlach,
* kazdy program, ktory sa pyta Windowsu "co hra" (napr. Wallpaper Engine,
  widgety), to vidi.

Potrebuje kniznicu `winrt` (pywinrt). Ked chyba, doinstaluje ju
`kniznice.py` a dovtedy tato cast jednoducho nebezi — prehravac sam o sebe
funguje rovnako ako predtym.

WinRT objekty sa vytvaraju a volaju vo vlastnom vlakne (MTA). Hlavne vlakno
Qt je STA a blokujuce `.get()` na asynchronnej operacii by v nom nemohlo
cakat. Udalosti z Windowsu (stlacene tlacidlo, posun) idu do appky Qt
signalmi, takze ovladanie prehravaca sa deje vzdy na hlavnom vlakne.
"""
from __future__ import annotations

import os
import queue
import threading
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Signal


def _priecinok() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "LanMusicPlayer"


class WindowsMedia(QObject):
    """Most medzi prehravacom a SMTC. Metody sa vracaju hned."""

    # "play" | "pause" | "stop" | "next" | "prev"
    tlacidlo = Signal(str)
    # Windows 11 ma v okienku posuvnik — ziadany cas v ms.
    posun = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fronta: "queue.Queue[tuple]" = queue.Queue()
        self._vlakno: threading.Thread | None = None
        self.stav = "nespustené"
        self.aktivne = False
        self._strana = 0

    # -- verejne ---------------------------------------------------------------
    def spusti(self) -> None:
        if self._vlakno is not None and self._vlakno.is_alive():
            return
        self._vlakno = threading.Thread(target=self._beh, daemon=True, name="windows-media")
        self._vlakno.start()

    def skladba(self, titul: str, interpret: str, album: str = "", interpret_albumu: str = "") -> None:
        self._fronta.put(("skladba", titul, interpret, album, interpret_albumu))

    def obal(self, data: bytes | None) -> None:
        self._fronta.put(("obal", data))

    def stav_prehravania(self, stav: str) -> None:
        self._fronta.put(("stav", stav))

    def cas(self, pozicia_ms: int, dlzka_ms: int) -> None:
        self._fronta.put(("cas", max(int(pozicia_ms), 0), max(int(dlzka_ms), 0)))

    def zastav(self) -> None:
        self._fronta.put(("koniec",))

    # -- vlakno ----------------------------------------------------------------
    def _beh(self) -> None:
        try:
            import winrt.runtime as rt
            try:
                rt.init_apartment(rt.MTA)
            except Exception:
                # Uz inicializovane (napr. ten isty mod) — staci.
                pass
            from winrt.windows.media import (
                MediaPlaybackStatus,
                MediaPlaybackType,
                SystemMediaTransportControlsButton,
                SystemMediaTransportControlsTimelineProperties,
            )
            from winrt.windows.media.playback import MediaPlayer
            from winrt.windows.storage import StorageFile
            from winrt.windows.storage.streams import RandomAccessStreamReference
        except Exception as exc:
            self.stav = f"chýba knižnica winrt ({exc.__class__.__name__})"
            return

        try:
            # MediaPlayer sa tu nepouziva na prehravanie — je to najjednoduchsi
            # sposob, ako desktopova appka dostane vlastne SMTC. Jeho vlastne
            # napojenie na tlacidla sa vypne, inak by Windows posielal prikazy
            # jemu, nie prehravacu.
            prehravac = MediaPlayer()
            prehravac.command_manager.is_enabled = False
            smtc = prehravac.system_media_transport_controls
            smtc.is_enabled = True
            smtc.is_play_enabled = True
            smtc.is_pause_enabled = True
            smtc.is_stop_enabled = True
            smtc.is_next_enabled = True
            smtc.is_previous_enabled = True
            aktualizator = smtc.display_updater
            aktualizator.type = MediaPlaybackType.MUSIC
            aktualizator.update()
        except Exception as exc:
            self.stav = f"Windows odmietol ovládanie médií: {exc}"
            return

        mapa = {
            SystemMediaTransportControlsButton.PLAY: "play",
            SystemMediaTransportControlsButton.PAUSE: "pause",
            SystemMediaTransportControlsButton.STOP: "stop",
            SystemMediaTransportControlsButton.NEXT: "next",
            SystemMediaTransportControlsButton.PREVIOUS: "prev",
        }

        def na_tlacidlo(_odosielatel, argumenty) -> None:
            try:
                akcia = mapa.get(argumenty.button)
            except Exception:
                return
            if akcia:
                self.tlacidlo.emit(akcia)

        def na_posun(_odosielatel, argumenty) -> None:
            try:
                cas = argumenty.requested_playback_position
                self.posun.emit(int(cas.total_seconds() * 1000))
            except Exception:
                pass

        tokeny = []
        try:
            tokeny.append(("button_pressed", smtc.add_button_pressed(na_tlacidlo)))
            tokeny.append(("posun", smtc.add_playback_position_change_requested(na_posun)))
        except Exception as exc:
            self.stav = f"udalosti z Windows nejdú: {exc}"
            return

        stavy = {
            "playing": MediaPlaybackStatus.PLAYING,
            "paused": MediaPlaybackStatus.PAUSED,
            "stopped": MediaPlaybackStatus.STOPPED,
        }
        self.aktivne = True
        self.stav = "zapnuté"

        while True:
            prikaz = self._fronta.get()
            # Cas chodi castejsie nez treba — plati posledny v rade.
            if prikaz[0] == "cas":
                while True:
                    try:
                        dalsi = self._fronta.get_nowait()
                    except queue.Empty:
                        break
                    if dalsi[0] != "cas":
                        self._fronta.put(dalsi)
                        break
                    prikaz = dalsi
            if prikaz[0] == "koniec":
                break
            try:
                if prikaz[0] == "skladba":
                    _, titul, interpret, album, interpret_albumu = prikaz
                    hudba = aktualizator.music_properties
                    hudba.title = titul or ""
                    hudba.artist = interpret or ""
                    hudba.album_title = album or ""
                    hudba.album_artist = interpret_albumu or interpret or ""
                    aktualizator.update()
                elif prikaz[0] == "obal":
                    data = prikaz[1]
                    if data:
                        # Windows si obal nacita zo suboru az ked ho ukazuje,
                        # preto sa strieda a/b — prepisat subor, ktory prave
                        # cita, by mohlo dat polovicny obrazok.
                        self._strana ^= 1
                        cesta = _priecinok() / f"smtc-obal-{'ab'[self._strana]}.jpg"
                        cesta.parent.mkdir(parents=True, exist_ok=True)
                        cesta.write_bytes(data)
                        subor = StorageFile.get_file_from_path_async(str(cesta)).get()
                        aktualizator.thumbnail = RandomAccessStreamReference.create_from_file(subor)
                    else:
                        aktualizator.thumbnail = None
                    aktualizator.update()
                elif prikaz[0] == "stav":
                    smtc.playback_status = stavy.get(prikaz[1], MediaPlaybackStatus.STOPPED)
                elif prikaz[0] == "cas":
                    _, pozicia, dlzka = prikaz
                    casova_os = SystemMediaTransportControlsTimelineProperties()
                    casova_os.start_time = timedelta(0)
                    casova_os.min_seek_time = timedelta(0)
                    casova_os.end_time = timedelta(milliseconds=dlzka)
                    casova_os.max_seek_time = timedelta(milliseconds=dlzka)
                    casova_os.position = timedelta(milliseconds=min(pozicia, dlzka) if dlzka else pozicia)
                    smtc.update_timeline_properties(casova_os)
            except Exception as exc:
                self.stav = f"chyba: {exc}"

        try:
            for meno, token in tokeny:
                if meno == "button_pressed":
                    smtc.remove_button_pressed(token)
                else:
                    smtc.remove_playback_position_change_requested(token)
            aktualizator.clear_all()
            aktualizator.update()
            smtc.is_enabled = False
        except Exception:
            pass
        self.aktivne = False
        self.stav = "vypnuté"
