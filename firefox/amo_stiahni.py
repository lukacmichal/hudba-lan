"""Stiahne uz podpisanu verziu rozsirenia z addons.mozilla.org.

zabal.ps1 ho vola PRED podpisovanim: Mozilla tu istu verziu druhy raz
nepodpise ("Version 1.0 already exists"), takze ked podpisovanie raz
prebehlo a len sa nestihlo stiahnut (prerusenie, vypadok siete), jedina cesta
k suboru je stiahnut ho. 4. 10. 2026 sa presne toto stalo tlacidlu 🔇.

    python amo_stiahni.py <gecko-id> <verzia> <ciel.xpi>

Navratovy kod: 0 = stiahnute (hash overeny), 2 = taka verzia na AMO nie je
(treba podpisat), 3 = je, ale este nie je podpisana, 1 = ina chyba.
Kluce cita z C:\\NAS\\amo-credentials.local a nikam ich nevypisuje.
"""
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

KLUCE = Path(__file__).resolve().parents[2] / "amo-credentials.local"


def nacitaj_kluce():
    hodnoty = {}
    for riadok in KLUCE.read_text(encoding="utf-8").splitlines():
        if "=" in riadok and not riadok.lstrip().startswith("#"):
            k, v = riadok.split("=", 1)
            hodnoty[k.strip()] = v.strip()
    return hodnoty["AMO_JWT_ISSUER"], hodnoty["AMO_JWT_SECRET"]


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(issuer: str, secret: str) -> str:
    # AMO chce kratko zijuci token (exp najviac 5 min) na kazdu poziadavku.
    teraz = int(time.time())
    hlavicka = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    obsah = b64(json.dumps({"iss": issuer, "jti": str(uuid.uuid4()), "iat": teraz, "exp": teraz + 60}).encode())
    podpis = b64(hmac.new(secret.encode(), f"{hlavicka}.{obsah}".encode(), hashlib.sha256).digest())
    return f"{hlavicka}.{obsah}.{podpis}"


def ziskaj(url: str, kluce, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": "JWT " + jwt(*kluce)})
    return urllib.request.urlopen(req, timeout=timeout).read()


def main() -> int:
    gecko_id, verzia, ciel = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    kluce = nacitaj_kluce()
    try:
        data = json.loads(ziskaj(f"https://addons.mozilla.org/api/v5/addons/addon/{gecko_id}/versions/v{verzia}/", kluce))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            # 404 = verzia (ci cele rozsirenie) neexistuje; 401/403 vrati AMO
            # aj pre rozsirenie, ktore este nikdy neodislo.
            print(f"  {gecko_id} {verzia}: na AMO nie je, treba podpisat")
            return 2
        print(f"  {gecko_id} {verzia}: AMO HTTP {e.code}")
        return 1
    subor = data.get("file") or {}
    if subor.get("status") != "public" or not subor.get("url"):
        print(f"  {gecko_id} {verzia}: na AMO je, ale este nie je podpisana ({subor.get('status')})")
        return 3
    obsah = ziskaj(subor["url"], kluce)
    ocakavany = (subor.get("hash") or "").split(":", 1)[-1]
    if ocakavany and hashlib.sha256(obsah).hexdigest() != ocakavany:
        print(f"  {gecko_id} {verzia}: stiahnuty subor nesedi s hashom z AMO")
        return 1
    ciel.write_bytes(obsah)
    print(f"  {gecko_id} {verzia}: podpisana verzia stiahnuta z AMO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
