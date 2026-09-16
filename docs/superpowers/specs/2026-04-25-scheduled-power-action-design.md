# Naplánované vypnutie/uspanie — Design Spec

**Dátum:** 2026-04-25  
**Stav:** Schválené

## Prehľad

Pridanie funkcie naplánovaného vypnutia alebo uspania PC v presne stanovenom čase. Funkcia je nezávislá od existujúcich checkboxov "vypnúť/uspať po skončení playlistu" — vykoná sa v nastavenom čase bez ohľadu na stav prehrávania.

## UI

### Nová ovládacia skupina vo footer riadku nastavení

```
[Žiadna akcia ▼]  [23:30 ▲▼]
```

- **`QComboBox`** s položkami:
  - `Žiadna akcia` (index 0) — predvolená hodnota
  - `Uspať` (index 1)
  - `Vypnúť` (index 2)
- **`QTimeEdit`** — zobrazený len keď je vybraté `Uspať` alebo `Vypnúť`; pri `Žiadna akcia` je skrytý
- Formát času: `HH:MM` (24-hodinový)
- Umiestnenie: v existujúcom footer riadku vedľa checkboxov pre "po skončení"

### Správanie UI

- Zmena ComboBoxu na `Žiadna akcia` → skryje `QTimeEdit`, zruší aktívny timer
- Zmena na `Uspať` alebo `Vypnúť` → zobrazí `QTimeEdit` s naposledy použitým časom; ak neexistuje, predvolená hodnota je **nasledujúca celá hodina kde `target_minutes > current_minutes`** (napr. o 14:47 → 15:00; ak je 14:59:45 → 15:00 keďže `900 > 899`; ak je presne 15:00:00 → 16:00 keďže `900 > 900` je False)
- Zmena času v `QTimeEdit`:
  - Ak nový čas je **v budúcnosti** (`target_minutes > current_minutes`): `QTimeEdit` má normálnu farbu, timer sa (re)štartuje
  - Ak nový čas je **v minulosti alebo rovnaký** (`target_minutes <= current_minutes`): `QTimeEdit` zobrazí červenú farbu textu, timer sa nespustí — nastavenie ostane uložené ale neaktívne
- **Cross-midnight scheduling nie je podporovaný.** Čas sa porovnáva výhradne voči aktuálnym minútam dňa. Ak nastavený čas je menší alebo rovný aktuálnemu, QTimeEdit zobrazí červenú.

### Vizuálna indikácia aktívneho timera

- `PlayerController` emituje signál `scheduled_status_changed = Signal(str)` vždy keď sa zmení stav timera
- `ui.py` sa napojí na tento signál a zobrazí správu v status bare:
  - Timer aktívny: `"Vypnutie naplánované o 23:30"` / `"Uspanie naplánované o 23:30"`
  - Timer zrušený / akcia vykonaná: prázdny reťazec `""` (status bar sa vyčistí)

### Validácia vstupu

- `QTimeEdit` natívne zabraňuje neplatnému vstupu — nie je potrebná ďalšia validácia na UI úrovni
- Pri načítaní z JSON: ak `scheduled_time` obsahuje neplatný reťazec (nie formát `HH:MM`), oba polia sa resetujú na `"none"` / `""` a stav sa okamžite uloží

## Logika (PlayerController)

### Nové stavové polia

```python
scheduled_action: str = "none"   # "none" | "sleep" | "shutdown"
scheduled_time: str = ""          # "HH:MM", napr. "23:30"
```

### Porovnanie času

```python
def _time_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def _current_minutes() -> int:
    now = QTime.currentTime()
    return now.hour() * 60 + now.minute()
```

Čas je "v budúcnosti" ak `_time_to_minutes(scheduled_time) > _current_minutes()`.

**Timer latencia:** akcia môže odísť až 90 sekúnd neskoro (60s čakanie na roll over minúty + 30s tick interval). Toto je akceptované správanie.

### Timer

- `QTimer` s intervalom **30 sekúnd**
- Aktívny len keď `scheduled_action != "none"` a `_time_to_minutes(scheduled_time) > _current_minutes()`
- **`_last_tick_minutes`:** ukladá hodnotu `_current_minutes()` z predchádzajúceho tiku. Inicializuje sa na `_current_minutes()` vždy keď sa timer spustí alebo reštartuje (vrátane zmeny času používateľom). Musí sa aktualizovať pri každom reštarte, nie len pri prvom štarte.
- **Midnight rollover detekcia:** ak na tiku `_current_minutes() < _last_tick_minutes - 1` (pokles > 1 minúta = prechod cez polnoc):
  - Ak `_last_tick_minutes >= _time_to_minutes(scheduled_time)`: akcia sa **vykoná** (bola naplánovaná pred polnocou ale tick nestihol zachytiť správnu minútu — nevynecháme ju)
  - Inak: timer sa zastaví a stav sa resetuje na `"none"` / `""` — cross-midnight nie je podporovaný
- Pri tiku kde `_current_minutes() >= _time_to_minutes(scheduled_time)`: vykoná akciu. Podmienka `>=` (nie `>`) je zámerná: keď čas dosiahne nastavenú minútu, akcia sa spustí. Timer štartuje len keď `target > current` (striktné), ale fire condition používa `>=` — toto je konzistentné a developer by ho nemal "opraviť" na `>`

### Inicializácia pri štarte aplikácie

Timer sa **nespúšťa v `__init__`**. `PlayerController` definuje metódu `start_scheduled_timer()`, ktorú volá `app.py` po dokončení inicializácie UI a napojení všetkých signálov. Tým sa zaručí, že `scheduled_status_changed` signál má príjemcu skôr ako sa emituje.

- Validácia formátu `scheduled_time`: ak neplatný → reset, uloží stav, koniec
- Ak `scheduled_action != "none"` a `scheduled_time` je platný:
  - Ak `_time_to_minutes(scheduled_time) > _current_minutes()` → spustí timer
  - Inak → resetuje oba polia, uloží stav

### Výkon akcie

1. Resetuje `scheduled_action` na `"none"`, `scheduled_time` na `""`
2. Uloží stav do JSON
3. Zastaví timer
4. Emituje `scheduled_status_changed("")` (vyčistí status bar)
5. Aktualizuje UI (`QComboBox` na `Žiadna akcia`, skryje `QTimeEdit`) — best-effort pred ukončením procesu
6. Volá `shutdown_windows()` alebo `sleep_windows()`

Krok 5 (UI update):
- Pri `sleep_windows()`: musí sa **dokončiť pred** volaním sleep (stroj suspenduje, ale proces prežije). Po resume je UI v správnom stave.
- Pri `shutdown_windows()`: je best-effort — Qt event loop môže byť ukončený pred spracovaním. Dáta sú bezpečne uložené v kroku 2, takže pri ďalšom štarte bude UI inicializované zo správneho stavu.

### Guard proti dvojitému spusteniu

Controller definuje privátny flag `_power_action_in_progress: bool = False`. Pred volaním akejkoľvek systémovej power funkcie (vrátane existujúcich "po skončení playlistu") sa nastaví na `True` a skontroluje; ak je už `True`, akcia sa preskočí. Toto zabraňuje dvojitému volaniu ak by oba mechanizmy spustili akciu súčasne.

### Interakcia s "po skončení playlistu" akciami

Obe funkcie sú nezávislé. Guard `_power_action_in_progress` zabraňuje dvojitému vykonaniu v tej istej relácii. Po reboote: naplánovaný čas v minulosti sa automaticky vyčistí pri inicializácii.

## Uloženie stavu (Persistence)

V `AppState` dataclass v `persistence.py` pribudnú dve polia:

```python
scheduled_action: str = "none"
scheduled_time: str = ""
```

Reset stavu sa vždy uloží **pred** volaním systémovej funkcie.

## Dotknuté súbory

| Súbor | Zmena |
|---|---|
| `music_player/persistence.py` | +2 polia v `AppState` |
| `music_player/player_controller.py` | +2 stavové polia, timer, `scheduled_status_changed` signál, `_power_action_in_progress` guard, pomocné funkcie |
| `music_player/ui.py` | +`QComboBox` + `QTimeEdit`, signály, show/hide logika, červená farba, napojenie na `scheduled_status_changed` |
| `music_player/system_integration.py` | Bez zmeny — reused `shutdown_windows()` a `sleep_windows()` |

## Mimo rozsahu

- Potvrdzovacie dialógy alebo odpočítavanie pred akciou
- Opakovanie (napr. každý deň o rovnakom čase)
- Cross-midnight scheduling
