from __future__ import annotations

from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config.txt"


def load_config() -> dict[str, str]:
    cfg: dict[str, str] = {}
    if not _CONFIG_PATH.exists():
        return cfg
    for line in _CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip()
    return cfg


def set_value(key: str, value: str) -> None:
    """Prepise (alebo doplni) jeden kluc v config.txt.

    Komentare a poradie ostatnych riadkov ostavaju — subor si clovek edituje
    rucne a prepisat mu ho cely by znamenalo prist o jeho poznamky.

    Zakomentovany riadok sa za nastaveny NEPOVAZUJE: `#KLUC=nieco` je navod,
    nie hodnota. Ked aktivny riadok chyba, kluc sa doplni na koniec.
    """
    riadky: list[str] = []
    if _CONFIG_PATH.exists():
        riadky = _CONFIG_PATH.read_text(encoding="utf-8").splitlines()

    novy = f"{key}={value}"
    for i, line in enumerate(riadky):
        holy = line.strip()
        if not holy or holy.startswith("#") or "=" not in holy:
            continue
        if holy.partition("=")[0].strip() == key:
            riadky[i] = novy
            break
    else:
        if riadky and riadky[-1].strip():
            riadky.append("")
        riadky.append(novy)

    tmp = _CONFIG_PATH.with_name(_CONFIG_PATH.name + ".tmp")
    tmp.write_text("\n".join(riadky) + "\n", encoding="utf-8")
    tmp.replace(_CONFIG_PATH)


def get_deepl_api_key() -> str:
    return load_config().get("DEEPL_API_KEY", "")


def get_mp3_target() -> str:
    """Korenovy priecinok pre rozbalenu hudbu; podpriecinok roka sa dopĺňa sam."""
    return load_config().get("MP3_TARGET", "").strip()
