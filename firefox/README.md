# Metal Music Player — rozsirenie pre Firefox

Dve casti:

**Tlacidla v liste** — `⏮ ⏯ ⏭ 🔇` priamo v liste Firefoxu, klik vykona akciu
hned, bez okienka. `⏯` ukazuje, ci hudba hra, `🔇` ci je stlmena (vrati
povodnu hlasitost). Nad kazdym tlacidlom je v bubline interpret, skladba
a cas. Ked prehravac nebezi alebo notebook spi, tlacidla zosedivie.
Nazov skladby priamo v liste byt nemoze — Firefox rozsireniam do listy
dovoli len tlacidlo (ikonu), nie text.

**Hlavne rozsirenie** (ikona s pentagramom) — okienko s celym ovladanim:

- co prave hra, cas a pas skladby (klik = posun)
- predchadzajuca / play-pauza / stop / dalsia
- hlasitost (posuvnik, reproduktor stlmi a vrati)
- `Spanok` a `Spanok 2` — rovnake ako tlacidla v prehravaci, na omyl chranene
  druhym klikom (Firefox v okienku rozsirenia `confirm()` neukaze)
- playlist s hladanim (bez diakritiky, `mgla` najde aj `Mgła`), klik pusti
  skladbu, `⏵` skoci na prave hrajucu

Hlavne rozsirenie je zaroven **mozog**: jeho pozadie (`pozadie.js`) drzi
prehravac najdeny a stav cerstvy (kazde 2 s, pri nedostupnom kazdych 10 s).
Okienko sa preto otvori hned s hotovymi udajmi a tlacidla sa pytaju jeho,
nie siete. Bez neho tlacidla nefunguju.

Vsetko ide cez existujuce HTTP API prehravaca na porte 8765
(`/api/now-playing`, `/api/playlist`, `POST /api/control`) — v prehravaci
netreba nic menit.

## Preco styri tlacidla = styri rozsirenia

Firefox da jednemu rozsireniu jedine tlacidlo v liste. Tlacidla su preto
styri male rozsirenia z jedneho skriptu (`tlacidla/tlacidlo.js`); ktore je
ktore, urcuje `tlacidla/varianty.json` a `zabal.ps1` z neho vyrobi manifesty
v `dist/tlacidla/<akcia>/`. Ikony kresli `tlacidla/kresli_ikony.py`.
Pozadie hlavneho rozsirenia prijima spravy len od tychto styroch ID.

## Kde hlada prehravac

Prehravac sa presuva medzi notebookmi a telefon ho najde UDP beaconom; ten
rozsirenie pocuvat nevie. Preto sa naraz skusia adresy zo zoznamu
(predvolene `127.0.0.1`, `192.168.1.50`, `192.168.1.51`) a vyhra:

1. adresa, ktoru si naposledy vybral klikom — kym hudba nehra inde,
2. inak ta, kde hudba prave hra,
3. inak prva, ktora odpoveda.

Ked odpovedaju dva prehravace, pod hlavickou okienka su obe adresy na
prepnutie (plati aj pre tlacidla). Zoznam sa meni cez ⚙; adresa mimo
predvolenych si vypyta povolenie.

## Instalacia

Vsetko je podpisane u Mozilly (kanal unlisted — nikde zverejnene nie je)
a lezi na `\\nas.local\Android\PlayerPC\firefox\`:

    metalmusic-firefox-<verzia>.xpi          hlavne (bez neho tlacidla nejdu)
    mmp-tlacidlo-prev-<verzia>.xpi           ⏮
    mmp-tlacidlo-playpause-<verzia>.xpi      ⏯
    mmp-tlacidlo-next-<verzia>.xpi           ⏭
    mmp-tlacidlo-mute-<verzia>.xpi           🔇

Navod pre cloveka (instalacia, presun tlacidiel, co ked nejde) je
`NAVOD.txt` — `zabal.ps1` ho pri kazdom vydani nahra na NAS vedla .xpi.

Firefox → Ctrl+O → subor → Pridat; po jednom, hlavne prve. Tlacidla sa
postavia rovno do listy. Na miesto vedla vyhladavania ich das tak, ze
klikes pravym na listu → **Prisposobit panel nastrojov** a pretiahnes ich
tam; vyhladavacie pole zuzis tahanim za jeho lavy okraj.

## Vydanie

- `.\zabal.ps1` — zabali nepodpisane `.xpi` do `dist\` (na skusku:
  `about:debugging` → Tento Firefox → Nacitat docasny doplnok; po restarte
  Firefoxu zmizne).
- `.\zabal.ps1 -Podpisat` — podpise u Mozilly a nahra na NAS. Kluce
  k addons.mozilla.org su v `C:\NAS\amo-credentials.local`
  (`AMO_JWT_ISSUER`, `AMO_JWT_SECRET`) — nikdy nie v tomto priecinku, ten
  ide cez `_github\export.py` na GitHub. Mozilla tu istu verziu druhy raz
  nepodpise: pri zmene hlavneho zvys `version` v `manifest.json`, pri zmene
  tlacidiel `verzia` vo `tlacidla/varianty.json`. Uz podpisane sa preskoci.
- Podpis trva u Mozilly okolo 5 minut na kazde rozsirenie — skript nespustaj
  s casovym limitom. Ked sa preto prerusi, verzia uz na AMO moze byt
  odoslana a druhy raz ju Mozilla nepodpise; `amo_stiahni.py` ju vtedy
  stiahne (zabal.ps1 ho skusa pred kazdym podpisom sam).

## Overenie (4. 10. 2026)

`web-ext lint` bez chyb a varovani na vsetkych piatich. V skutocnom Firefoxe
157 (headless, cez WebDriver BiDi) proti falosnemu prehravacu na 127.0.0.1:

- okienko: najdenie oboch prehravacov, playlist 1562 skladieb, oznacenie
  hrajucej, dalsia, pauza, posun, hlasitost, stlmenie a vratenie, klik
  v playliste, Spanok az po druhom kliku, hladanie
- okienko s playlistom hotove do ~250 ms od otvorenia (udaje z pozadia)
- tlacidla: ⏭ ⏮ poslali prikaz, ⏯ zmenilo bublinu Pauza → Hrat, 🔇 stlmilo
  a vratilo hlasitost 80, po zmiznuti prehravaca tlacidlo zosedivelo
  s bublinou „Prehravac nedostupny"

Skutocny prehravac na 88.3 sa pri testoch len citaval.
