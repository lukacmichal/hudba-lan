METAL MUSIC PLAYER - windowsovy prehravac
=========================================

Toto je priecinok, z ktoreho sa windowsova appka instaluje a sama aktualizuje.
Androidovy klient je vedla v priecinku Player (metalmusic-<verzia>.apk).


CO JE TU
--------

latest.json                 Verzia, meno balika a jeho SHA-256. Toto cita appka
                            pri kazdom spusteni - je to jediny zdroj pravdy
                            o tom, ktora verzia je aktualna.

metalmusic-pc-<verzia>.zip  Cela appka. Starsie baliky sa pri vydani mazu,
                            vzdy tu je len ten, na ktory ukazuje latest.json.

nainstaluj.cmd              PRVA instalacia na novom pocitaci. Dvojklik.
nainstaluj.ps1              Logika instalatora (spusta ho .cmd).

konfiguracia\               Konfiguracne subory tak, ako vyzeraju na "domacom"
                            pocitaci - na nahliadnutie a skopirovanie bez
                            rozbalovania balika:
                              config.txt    nastavenia appky
                              spanok.m3u    zoznam pre tlacidlo Spanok
                              spanok2.m3u   zoznam pre tlacidlo Spanok 2

zalohy\<MENO-POCITACA>\     Zalohy playlistu. Odklada ich sem appka sama pri
                            kazdom spusteni, a to iba vtedy, ked sa playlist
                            od poslednej zalohy zmenil. Kazdy pocitac ma
                            vlastny podpriecinok, drzi sa poslednych 30 zaloh
                            a je v nom aj README.txt s navodom, ako sa
                            playlist vracia spat. Sem NIC nekopiruje vydanie
                            novej verzie - je to jediny priecinok s osobnymi
                            datami, nie s appkou.


NOVY POCITAC
------------

1. Otvor \\nas.local\Android\PlayerPC
2. Dvojklik na nainstaluj.cmd
3. Enter (alebo napis vlastny priecinok)

Skript overi kontrolny sucet balika, rozbali appku, spravi skratku na plochu
a doinstaluje chybajuce Python kniznice. Prava spravcu netreba.


DALSIE VERZIE
-------------

Uz nic. Prehravac sa po spusteni sam pozrie sem a ked je tu novsia verzia,
opyta sa:

    "Na NAS-e je verzia 1.4 (14), mas 1.3 (13). Nainstalovat teraz?"

Az po potvrdeni stiahne balik, overi jeho SHA-256, ukonci sa, prekopiruje
subory a spusti sa spat. Ked NAS nie je dostupny (si mimo domu), nepovie nic.

Rucne: v appke tlacidlo "?" -> "Skontrolovat aktualizaciu teraz".

TVOJE SUBORY SA NEPREPISU. config.txt, spanok.m3u ani spanok2.m3u aktualizacia
nikdy neprepise - ostanu take, ake su. Ked niektory chyba (cerstva instalacia),
doplni sa vzor z balika. Skratka .lnk sa tiez nedotyka, nesie absolutnu cestu
k tomuto pocitacu.


VYDANIE NOVEJ VERZIE
--------------------

Robi sa na pocitaci so zdrojakmi (C:\NAS\hudba-lan):

1. V music_player\__init__.py zvys OBE cisla:
       __version__ = "1.4"
       __version_code__ = 14
2. .\nahraj-pc-na-nas.ps1 -Skus                     (ukaze, co by nahral)
3. .\nahraj-pc-na-nas.ps1 -Poznamka "co je nove"    (nahra)

Skript zabali appku, spocita SHA-256, prepise latest.json, obnovi tu instalator
aj konfiguraciu a zmaze starsi balik. Bez zvysenia __version_code__ nahravanie
odmietne - druhy notebook by novu verziu nikdy nevypytal.

Poverenia na zapis berie z nas-credentials.local.


PRIHLASENIE NA NAS
------------------

Share Android bez prihlasenia neda ani citanie, takze sa naň appka musi dostat.
Ziadne heslo v sebe ale nema - hlada ho v tomto poradi:

1. Skusi citat rovno. Funguje, ked ma Windows k NAS-u ulozene poverenie
   (Spravca poverení, alebo zaskrtnute "zapamatat prihlasovacie udaje"
   v Prieskumnikovi) alebo ked na server uz existuje relacia.
2. Ked to nevyjde, prihlasi sa udajmi z nas-credentials.local - vedla appky
   alebo v C:\NAS. Ten subor je len na pocitaci so zdrojakmi.
3. Ked ani to nie, kontrola sa TICHO preskoci.

Na druhom notebooku teda staci bod 1 - poverenie tam ulozi nainstaluj.cmd
(opyta sa na to). Rucne:

    cmdkey /add:nas.local /user:nasuser /pass

Ked appka o novych verziach mlci a si doma, toto je prva vec na overenie.


KED SA NIECO POKAZI
-------------------

Priebeh poslednej aktualizacie je v %TEMP%\metalplayer-update.log na tom
pocitaci, kde sa aktualizovalo.

Ked update spadol v polovici, staci znova spustit nainstaluj.cmd - prepise
kod a nastavenia necha tak.
