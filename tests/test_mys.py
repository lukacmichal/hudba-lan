"""Testy dialkovej mysi (telefon ako touchpad).

Standalone (pytest in this env is broken):
    python tests/test_mys.py

SendInput sa tu NEVOLA — namiesto neho sa zbieraju struktury, ktore by don
isli. Kurzor na stroji, kde test bezi, sa teda nepohne.
"""
import ctypes
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_player import mys as m  # noqa: E402
from music_player.metadata_server import NowPlayingServer  # noqa: E402


def _mys():
    poslane = []
    return m.DialkovaMys(posli=lambda vstupy: poslane.append(list(vstupy))), poslane


def test_struktura_ma_velkost_ako_vo_windows():
    # SendInput s nespravnou velkostou INPUT ticho nerobi nic (vrati 0).
    ocakavana = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    assert ctypes.sizeof(m._INPUT) == ocakavana


def test_posun():
    mys, poslane = _mys()
    assert mys.vykonaj("m 5 -3")
    (vstup,) = poslane[0]
    assert vstup.type == m._INPUT_MOUSE
    assert (vstup.u.mi.dx, vstup.u.mi.dy) == (5, -3)
    assert vstup.u.mi.dwFlags == m._MOUSEEVENTF_MOVE


def test_posun_sa_oreze():
    mys, poslane = _mys()
    assert mys.vykonaj("m 999999 -999999")
    assert (poslane[0][0].u.mi.dx, poslane[0][0].u.mi.dy) == (2000, -2000)


def test_klik_je_dole_a_hore():
    mys, poslane = _mys()
    assert mys.vykonaj("c r")
    assert [v.u.mi.dwFlags for v in poslane[0]] == [
        m._MOUSEEVENTF_RIGHTDOWN, m._MOUSEEVENTF_RIGHTUP]


def test_koliesko_nadol_je_zaporne():
    mys, poslane = _mys()
    assert mys.vykonaj("s -120")
    vstup = poslane[0][0]
    assert vstup.u.mi.dwFlags == m._MOUSEEVENTF_WHEEL
    assert ctypes.c_int32(vstup.u.mi.mouseData).value == -120


def test_tahanie_sa_pri_padnuti_spojenia_pusti():
    mys, poslane = _mys()
    mys.vykonaj("d l")
    mys.uvolni()
    assert poslane[-1][0].u.mi.dwFlags == m._MOUSEEVENTF_LEFTUP
    poslane.clear()
    mys.uvolni()          # nic drzane — nic sa neposle
    assert poslane == []


def test_text_ide_ako_unicode():
    mys, poslane = _mys()
    assert mys.vykonaj("t ľš")
    vstupy = poslane[0]
    assert [v.u.ki.wScan for v in vstupy] == [ord("ľ"), ord("ľ"), ord("š"), ord("š")]
    assert all(v.u.ki.dwFlags & m._KEYEVENTF_UNICODE for v in vstupy)


def test_kombinacia():
    mys, poslane = _mys()
    assert mys.vykonaj("k alt+f4")
    vstupy = poslane[0]
    assert [v.u.ki.wVk for v in vstupy] == [0xA4, 0x73, 0x73, 0xA4]
    assert [bool(v.u.ki.dwFlags & m._KEYEVENTF_KEYUP) for v in vstupy] == [
        False, False, True, True]


def test_sipka_je_rozsirena():
    mys, poslane = _mys()
    mys.vykonaj("k left")
    assert poslane[0][0].u.ki.dwFlags & m._KEYEVENTF_EXTENDEDKEY


def test_nezname_prikazy_nic_nerobia():
    mys, poslane = _mys()
    for riadok in ("", "x", "m 1", "m a b", "c q", "k nic", "k ctrl+nic"):
        assert not mys.vykonaj(riadok), riadok
    assert poslane == []


def test_trvale_spojenie_cez_server():
    mys, poslane = _mys()
    srv = NowPlayingServer(payload_provider=lambda: {}, preferred_port=0, mouse=mys)
    srv.start()
    try:
        with socket.create_connection(("127.0.0.1", srv.port), timeout=3) as s:
            s.sendall(b"POST /api/mouse HTTP/1.1\r\nHost: pc\r\n\r\n")
            odpoved = b""
            while b"ok\n" not in odpoved:
                kus = s.recv(1024)
                assert kus, odpoved
                odpoved += kus
            assert odpoved.startswith(b"HTTP/1.0 200"), odpoved
            # Riadky po jednom, s pauzou — tak ich posiela telefon.
            s.sendall(b"m 1 2\n")
            time.sleep(0.05)
            s.sendall(b"d l\nm 3 4\n")
            koniec = time.time() + 3
            while len(poslane) < 3 and time.time() < koniec:
                time.sleep(0.01)
            assert len(poslane) == 3, poslane
        # Po zavreti spojenia sa drzane lave tlacidlo pusti.
        koniec = time.time() + 3
        while len(poslane) < 4 and time.time() < koniec:
            time.sleep(0.01)
        assert poslane[-1][0].u.mi.dwFlags == m._MOUSEEVENTF_LEFTUP
    finally:
        srv.stop()


def test_bez_mysi_je_endpoint_404():
    srv = NowPlayingServer(payload_provider=lambda: {}, preferred_port=0)
    srv.start()
    try:
        with socket.create_connection(("127.0.0.1", srv.port), timeout=3) as s:
            s.sendall(b"POST /api/mouse HTTP/1.1\r\nHost: pc\r\nContent-Length: 0\r\n\r\n")
            assert s.recv(1024).startswith(b"HTTP/1.0 404")
    finally:
        srv.stop()


if __name__ == "__main__":
    zlyhali = 0
    for meno, fn in list(globals().items()):
        if meno.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK   {meno}")
            except Exception as exc:  # noqa: BLE001
                zlyhali += 1
                print(f"FAIL {meno}: {exc!r}")
    sys.exit(1 if zlyhali else 0)
