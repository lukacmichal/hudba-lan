from __future__ import annotations

import json
import socket
import threading

BEACON_PORT = 8766
BEACON_INTERVAL = 2.0


class UdpBeaconSender:
    """Každé 2 sekundy broadcastuje JSON s IP a API portom na UDP port 8766."""

    def __init__(self, api_port: int = 8765) -> None:
        self._api_port = api_port
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ip = _local_ip_address()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _run(self) -> None:
        payload = self._build_payload(self._ip)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            while not self._stop_event.wait(BEACON_INTERVAL):
                # Re-resolve the IP each round: after autostart the app may be
                # up before the network, and DHCP can hand out a new address.
                current_ip = _local_ip_address()
                if current_ip != self._ip:
                    self._ip = current_ip
                    payload = self._build_payload(current_ip)
                try:
                    sock.sendto(payload, ("255.255.255.255", BEACON_PORT))
                except OSError:
                    pass

    def _build_payload(self, ip: str) -> bytes:
        return json.dumps({
            "service": "lan-music-player",
            "ip": ip,
            "apiPort": self._api_port,
        }).encode("utf-8")


def _local_ip_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return str(sock.getsockname()[0])
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
