# LAN Music Player MVP

Toto je zaklad Windows prehravaca postaveneho na `Python + PySide6`.

Aktualne obsahuje:

- lokalne prehravanie cez `QMediaPlayer`
- playlist, ktory sa uklada medzi spusteniami
- historiu prehranych skladieb
- seek slider pre posuv v skladbe
- rekurzivne nacitanie celeho priecinka s hudbou
- drag-and-drop suborov aj priecinkov priamo do okna
- tlacidlo `Z Downloads` — rozbali vsetky rar/zip/7z archivy s hudbou z Downloads do `MP3_TARGET\_<rok>` (default `C:\data\mp3\_2026`), vypise prehlad pridanych albumov a priecinok otvori
- rozbaleny album dostane nazov `Interpret - Album - Rok`; nazvy typu
  ``Dark Plague`2026`Masquerade by necroscum`` sa upracu samy. Ked sa z nazvu
  neda vycitat, kde konci kapela a zacina album, appka sa opyta zoznamu noviniek
  a potom Metal Archives (`nazvy.py` + `nazvy_ma.py`). Bez zhody sa necha povodny
  nazov — netipuje sa
- tlacidlo `Novinky` — nove metalove albumy z piatkoveho skenu
  `C:\NAS\metal-novinky`, s odkazmi na YouTube, Bandcamp a Metal Archives.
  Vypocuty album sa odskrtne a zo zoznamu zmizne; odskrtnutie sa uklada na
  NAS, takze plati na oboch notebookoch
- tlacidlo `Statistika` — co si kolkokrat pocuval: skladby, interpreti,
  albumy a historia, za celkovo / rok / 30 dni / 7 dni. Kazde prehratie je
  riadok v SQLite `%APPDATA%\LanMusicPlayer\statistika.db` (lokalne pre kazdy
  notebook — SQLite na NAS-e s dvoma zapisovatelmi by sa poskodila). Prehratie
  sa rata az po 30 s realneho hrania (kratka skladba 30 %), preskocene nie.
  Dvojklik na skladbu ju prida do playlistu. Pocita sa od verzie 1.18 (28),
  starsie pocuvanie v databaze nie je
- vyber audio vystupu a tlacidlo `Obnovit audio`
- automaticky low-latency LAN stream cez `ffmpeg` pri prehravani
- multicast stream URL `udp://@239.255.12.42:5004?fifo_size=1000000&overrun_nonfatal=1`
- system tray spravanie
- autostart cez Windows registry
- tlacidla `Spanok` a `Spanok 2` — dve tlacidla, ktore robia to iste, len kazde
  zo svojho zoznamu (`spanok.m3u` / `spanok2.m3u` vedla `config.txt`): skladby
  z neho pridaju na koniec playlistu a hned ich pustia. `Spanok` je vlastny
  zoznam, `Spanok 2` spolocny
- ked playlist UZ konci presne tymi skladbami, neprida sa NIC — len sa na ne
  skoci a playlist ostane, aky bol. Tlacidlo sa teda da stlacit hoci kazdy
  vecer a playlist z toho nenarastie
- pridane skladby sa pri UKONCENI prehravaca z playlistu zase vyhodia. Uspanie
  ani vypnutie PC ukoncenie nie je — po zobudeni su stale tam. Meni sa to
  klucmi `SPANOK_NECHAT_V_PLAYLISTE` / `SPANOK2_NECHAT_V_PLAYLISTE` v
  `config.txt` (`ano` = ostanu aj na dalsi den)
- ked je `spanok.m3u` prazdny, tlacidlo `Spanok` sa sprava po starom: skoci
  na tretiu skladbu od konca playlistu
- zoznamy sa edituju pravym klikom na tlacidlo, alebo pravym klikom na skladbu
  v playliste; cesty k nim prepisu `SPANOK_PLAYLIST` / `SPANOK2_PLAYLIST`
- obe sa daju spustit aj z telefonu — API akcie `spanok` a `sleep2`
- widget na ploche telefonu ma vpravo hore vsetky styri uspavacie tlacidla:
  `Spanok` / uspat PC / `Spanok 2` / vypnut PC —
  kazde cez potvrdzovaciu otazku
- pripraveny prepinac pre `vypnut PC po poslednej skladbe`
- lokalne `now playing` API na `http://<ip>:8765/api/now-playing`

Zatial neobsahuje:

- Android klienta
- automaticky discovery protokol
- fallback stream rezim pre siete, kde multicast nefunguje dobre

## Spustenie

Dvojklik na `spustit.cmd` v tomto priecinku. Skript si sam najde Python (`pyw`,
`pythonw`, alebo instalaciu v `%LOCALAPPDATA%\Programs\Python`) a nespoliha sa na
ziadnu absolutnu cestu, takze priecinok sa da lubovolne presunut aj skopirovat na
iny pocitac.

Rucne to iste:

```powershell
python app.pyw
```

Stav sa uklada do `%APPDATA%\LanMusicPlayer\state.json`.

### Skratka

`Metal Music Player.lnk` musi z principu obsahovat absolutnu cestu, takze presun
priecinka ju rozbije. Po presune (alebo pri nasadeni na dalsi pocitac) staci
spustit `vytvor-skratku.cmd`, ktory ju prepise podla aktualneho umiestnenia.
S parametrom `plocha` prida skratku aj na plochu:

```powershell
.\vytvor-skratku.cmd plocha
```

### Nasadenie na dalsi pocitac

Otvor `\\nas.local\Android\PlayerPC` a dvojklikni `nainstaluj.cmd`.
Instalator overi kontrolny sucet balika, rozbali appku, spravi skratku na
plochu, ulozi prihlasenie na NAS (kvoli buducim aktualizaciam) a doinstaluje
chybajuce Python kniznice. Prava spravcu netreba.

Rucne to iste:

1. Skopiruj cely priecinok kamkolvek.
2. `python -m pip install PySide6 mutagen requests`
3. V `config.txt` skontroluj `MP3_TARGET` (kam sa rozbaluje hudba).
4. `vytvor-skratku.cmd plocha`

### Aktualizacie z NAS-u

Appka sa aktualizuje sama — rovnakym sposobom ako androidovy klient. Na NAS-e
ma vlastny priecinok vedla neho:

```
\\nas.local\Android\
├── Player\      metalmusic-<verzia>.apk + latest.json   (Android)
└── PlayerPC\    metalmusic-pc-<verzia>.zip + latest.json (Windows)
    ├── nainstaluj.cmd     prva instalacia na novom pocitaci
    ├── README.txt
    └── konfiguracia\      config.txt, spanok.m3u, spanok2.m3u
```

Pri kazdom spusteni sa precita **iba** `latest.json` (par stoviek bajtov). Ked
je tam vyssi `versionCode`, appka sa opyta; az po potvrdeni stiahne balik, overi
jeho SHA-256, ukonci sa, prekopiruje subory a spusti sa spat. Rucne to ide cez
`?` → **Skontrolovat aktualizaciu teraz**.

**Ticho je len vtedy, ked NAS naozaj nie je na dosah.** Od 1.9 (19) sa
rozlisuju dva stavy, ktore predtym vyzerali rovnako:

* **server neodpoveda** — si mimo domu, alebo po zobudeni notebooku este
  nenabehla siet. Kontrola sa **zopakuje** o 1, 5 a 15 minut. Dovtedy bezala
  raz, 5 sekund po starte, a viac nikdy — na notebooku, ktory prehravac spusta
  hned po zobudeni (`hudba-po-zobudeni.ps1`), teda takmer vzdy do prazdna.
* **server odpoveda, ale manifest sa neda precitat** — chyba poverenie na
  share. V tomto stave sa appka uz nikdy sama neaktualizuje, takze to odteraz
  **povie**, aj pri tichej kontrole, aj s prikazom na opravu.

Ktory z tych dvoch stavov nastal na druhom notebooku, sa zvonku zistit nedalo —
a to je samo o sebe cast problemu: oba boli ticho a stara verzia sa naslo az
nahodou. Odkedy ma prehravac self-update (1.3 (13), 2. 9. 2026), stihlo na NAS
prist pat vydani.

**Ktora verzia kde bezi** sa da zistit zvonku, bez sadania si k tomu pocitacu:

```
curl http://192.168.1.50:8765/health
{"status": "ok", "version": "1.10", "versionCode": 20}
```

**Tvoje subory sa neprepisu** — `config.txt`, `spanok.m3u` ani `spanok2.m3u`.
Ked niektory chyba (cerstva instalacia), doplni sa vzor z balika. Skratka `.lnk`
sa tiez nedotyka, nesie absolutnu cestu k tomuto pocitacu. Naopak: subor, ktory
v novej verzii uz nie je, na disku ostane — kopiruje sa cez, nie zrkadli sa.

Priebeh poslednej aktualizacie je v `%TEMP%\metalplayer-update.log`.

#### Vydanie novej verzie

1. V `music_player\__init__.py` zvys **obe** cisla (`__version__` aj
   `__version_code__`). Appka porovnava vyhradne `__version_code__`.
2. `.\nahraj-pc-na-nas.ps1 -Skus` — ukaze, co by nahral.
3. `.\nahraj-pc-na-nas.ps1 -Poznamka "co je nove"` — nahra.

Bez zvysenia `__version_code__` skript nahravanie odmietne. Poverenia na zapis
berie z `nas-credentials.local`.

#### Prihlasenie na NAS

Share `Android` bez prihlasenia neda ani citanie, appka ale ziadne heslo v sebe
nema. Skusi citat rovno (funguje, ked ma Windows poverenie ulozene v Spravcovi
poverení), a ked to nevyjde, prihlasi sa udajmi z `nas-credentials.local` —
vedla appky alebo v `C:\NAS`. Ked ani jedno, kontrola sa ticho preskoci.

Na notebooku bez `C:\NAS` poverenie uklada instalator; rucne:

```powershell
cmdkey /add:nas.local /user:nasuser /pass
```

### Zaloha playlistu na NAS

Playlist zije v jedinom subore na tom notebooku, kde appka prave bezi
(`%APPDATA%\LanMusicPlayer\state.json`). Pri kazdom spusteni sa preto odklada
kopia na NAS, vedla balikov appky:

```
\\nas.local\Android\PlayerPC\zalohy\<MENO-POCITACA>\
    playlist-2026-09-02-183012.m3u8
    README.txt        ako sa zaloha vracia spat
```

**Zapisuje sa iba pri zmene.** Nova zaloha sa porovna s poslednou a ked sedi
zoznam ciest, nezapise sa nic — datum v nazve je teda datum zmeny, nie kazdeho
spustenia. Porovnava sa vyhradne zoznam skladieb, hlavicka s casom sa ignoruje.
Zalohuje sa playlist tak, ako ho appka mala pri **poslednom behu**; zmeny
z prebiehajuceho vecera sa odlozia az pri dalsom spusteni.

Kazdy pocitac ma vlastny podpriecinok (playlist ma kazdy svoj), drzi sa
poslednych 30 zaloh a nedostupny NAS je ticho — rovnako ako pri aktualizacii.
Rucne to ide cez `?` → **Zalohovat playlist teraz**.

Zaloha je obycajny `.m3u8` s celymi cestami: vratis ju pretiahnutim myšou do
okna alebo tlacidlom **Nacitat M3U**. Skladby sa pridavaju na koniec, takze na
presnu obnovu najprv **Vymazat playlist**.

Vypina sa `ZALOHA_PLAYLISTU=nie`, iny priecinok (hoci USB kluc) nastavi
`ZALOHA_PRIECINOK`, pocet zaloh `ZALOHA_POCET` — vsetko v `config.txt`.

### Nazvy rozbalenych albumov

Archivy zo sceny chodia pomenovane vselijako a v `C:\data\mp3` sa to potom neda
ani zoradit. Nazov priecinka sa preto pred rozbalenim uprace na
`Interpret - Album - Rok`. Rozhoduje sa v troch krokoch a kazdy dalsi je drahsi:

1. **`nazvy.py` — offline.** Rozdeli nazov podla spatneho apostrofu, ` - `,
   podtrzitok, vytiahne rok a zahodi formatove zatvorky (`[FLAC]`, `(WEB)`)
   aj koncove `by necroscum`. Ked je vysledok jednoznacny, hotovo — bez siete.
2. **Zoznam noviniek** (uz stiahnuty z NAS-u). Odtial albumy chodia, takze
   zhoda je casta a okamzita.
3. **Metal Archives** (`nazvy_ma.py`). Hlada sa VYHRADNE podla mena kapely,
   od najdlhsieho mozneho mena k najkratsiemu; album sa potom paruje uz offline
   proti diskografii. Preto neprekaza, ze za albumom byva este meno vydavajucej
   skupiny — pyta sa opacne: su slova albumu z MA obsiahnute v nazve priecinka?

```
Blind-Guardian-Somewhere-2026-GRP
  -> kapela "Blind Guardian Somewhere"?  MA: nic
  -> kapela "Blind Guardian"?            MA: diskografia
  -> je v nej album, ktoreho slova su vsetky v nazve? nie -> povodny nazov
```

MA pozna aj spravny zapis, takze `Behemoth-I-Scvlptor` skonci ako
`Behemoth - I, Scvlptor` a `Bootes-Void` ako `Boötes Void`.

**Ked sa zhoda nenajde, nazov sa necha tak, ako prisiel.** Zle uhadnuty
interpret je horsi nez povodny neporiadok — ten sa aspon da precitat a opravit
rucne. Kontroluje sa aj povodny nazov: album rozbaleny pred touto zmenou lezi
v cieli este pod nim a druhy raz sa rozbalit nema.

Siet sa da vypnut `NAZVY_MA=nie` v `config.txt`; kroky 1 a 2 bezia dalej.
`downloads_import` do siete nechodi sam — dostava funkciu zvonka, takze sa da
testovat bez nej.

### Metalove novinky z NAS-u

Sken `C:\NAS\metal-novinky` (od 6. 9. 2026 bezi kazdu noc) uz nekonci len
mailom. Co presiel filtrom zanrov, zapisuje aj na NAS a prehravac to ukazuje
pod tlacidlom `Novinky` (cislo v tlacidle = kolko si ich este neodskrtol).

**Okno ma dve zalozky.** Su to dve rozne otazky, nie jeden zoznam:

* **Tento tyzden** — vydania s datumom v aktualnom pondelok–nedela. Aj tie,
  ktore sken nasiel o tyzden skor: MA pozna vydania dopredu, takze album najdeny
  30. 8. a vydany 4. 9. sa objavi az v tyzdni, kedy naozaj vysiel.
* **Uz vydane** — albumy, ktore na Metal Archives pribudli **az po svojom
  vydani**. Ich tyzden uz presiel, takze by ich prva zalozka nikdy neukazala.

V oboch su albumy zoradene **podla dna vydania a v ramci dna podla abecedy**,
s deliacim riadkom pri kazdom dni. Datum je aj pri kazdom albume zvlast (pri
rolovani odide nadpis dna hore) — a ked MA pozna len mesiac, je tam mesiac.
Poradie robi sken; prehravac ho neprehadzuje.

**Zanre sa daju menit z appky.** Tlacidlo `Zanre...` ukaze dva zoznamy slov:
ktore vydanie pustia a ktore ho vyhodia. Rozhoduje slovo *cisty* — zakazany
zaner vyhodi vydanie len vtedy, ked v style nie je ziadne povolene slovo, takze
"Death Metal/Thrash Metal" je death, nie thrash.

Zmena plati **hned**: sken posiela do zoznamu aj to, co podla zanru zahodil,
takze pridanie zanru ma co ukazat. Uklada sa do `filtre.json` vedla zoznamu na
NAS-e — z toho isteho suboru cita aj nocny sken, takze sa okno a mail nerozidu.

Subory na NAS-e su tie iste ako predtym:

```
\\nas.local\Android\PlayerPC\novinky\
    novinky.json      zoznam albumov — pise sken, prehravac len cita
    precitane.log     co uz mas odskrtnute — pise prehravac
    README.txt        ktory subor je co
```

**Dva subory zamerne.** Zoznam pise sken na jednom stroji, odskrtava sa na
dvoch. Keby to bol jeden subor, notebooky by si zapisy prepisali. `precitane.log`
sa preto len **doplna po riadkoch** (jeden riadok = jeden JSON = jeden klik)
a nikdy neprepisuje cely — dva zapisy naraz tak nemaju o co bojovat. O albume
plati posledny riadok, takze sa odskrtnutie da aj vratit spat.

**Zo zoznamu sa nikdy nic nemaze.** Odskrtnuty album sa v okne len skryje;
zaskrtavadlo `Zobrazit aj skontrolovane` ho vrati a tlacidlo `Vratit medzi nove`
ho odznaci. Vdaka tomu odklik vedla nic nestoji.

Pod ciarou su polozky, s ktorymi si filter zanrov nevedel rady (MA nevie styl,
alebo styl nesedi ani na jeden zoznam). Su tam preto, ze filter sa na nich este
ladi — nie preto, ze by sa mali pocuvat prve.

Album stiahnuty a rozbaleny cez `Z Downloads` sa odskrtne sam: nazov priecinka
sa naparuje s novinkou cez `nazvy.kluc`, ktory zahadzuje interpunkciu (priecinok
`Augurium - Faith and Death - 2026` sedi so skenom `Augurium — Faith & Death`).

Nedostupny NAS je ticho: pouzije sa posledna stiahnuta kopia
(`%APPDATA%\LanMusicPlayer\novinky-kopia.json`) a odskrtnutia pockaju
v `novinky-neodoslane.log` na najblizsie spojenie. Vypina sa `NOVINKY=nie`,
iny priecinok nastavi `NOVINKY_PRIECINOK` — oboje v `config.txt`.

### Ked appka po zobudeni nebezi alebo ju telefon nenajde

Dva skripty na to, co sa lame po zmene IP alebo po prechode Wi-Fi -> kabel.
Oba sa spustaju **na tom pocitaci, kde bezi prehravac**, nie na druhom.

`oprava-lan-pristupu.cmd` (vypyta si prava spravcu)
: Beacon je odchadzajuci UDP a chodi vzdy, ale `http://<ip>:8765/health` je uz
  prichodzie spojenie. Ked Windows po zmene IP vyhodnoti siet ako novu, da jej
  profil *Verejna* a vynimka spravena kedysi pre *Sukromnu* Wi-Fi siet na nu
  neplati - appka teda server v beacone vidi, ale nedovola sa mu. Skript oznaci
  aktivnu siet ako Sukromnu a zaroven spravi vynimky pre `profile=any`, takze
  dalsia zmena profilu ani prechod medzi kablom a Wi-Fi uz nic nerozbije.
  Pri tom vypne aj vyzadovanie hesla pri zobudeni zo spanku.

`hudba-po-zobudeni.cmd`
: Zalozi naplanovanu ulohu, ktora po zobudeni (udalost 1 od Power-Troubleshooter)
  a po prihlaseni spusti prehravac, ak este nebezi. Autostart cez `Run` kluc na to
  nestaci - ten sa spusta iba pri prihlaseni, a zobudenie zo spanku prihlasenie
  nie je. Uloha bezi v relacii prihlaseneho uzivatela, takze appka nabehne aj ked
  na obrazovke ostane prihlasovacia tabulka; audio hra aj cez zamknutu plochu.

Pozor na dva bezice prehravace naraz: kazdy vysiela vlastny beacon a telefon si
vezme ten, ktory pride prv. Ked hudba "hra niekam inam", najprv skontroluj, ci
appka nebezi aj na druhom notebooku.

## Poznamky

Ak pri prehravani zlyha konkretny subor, aplikacia to vypise do spodneho stavoveho riadku spolu s nazvom suboru. Ak je audio vystup blokovany inou aplikaciou, skus `Obnovit audio` alebo prepni audio vystup.

LAN stream sa spusta automaticky pri `Play` a vypina pri `Pause` alebo `Stop`. Aktualny stream URL je viditelny priamo v hlavnom okne aj v API.

## Dalsi krok

Dalsim krokom je jednoduchy Android prijimac, idealne nad `LibVLC`, ktory sa po spusteni pripoji na multicast stream a cez API zobrazi nazov skladby a interpreta.
