"use strict";
// Pozadie hlavneho rozsirenia — jedine miesto, ktore hovori s prehravacom.
//
// Drzi prehravac najdeny a jeho stav cerstvy, aby:
//   * okienko (popup.js) nemuselo pri kazdom otvoreni hladat prehravac
//     a stahovat playlist — dostane ich hned odtialto,
//   * tlacidla v liste (tlacidla/tlacidlo.js, styri samostatne rozsirenia,
//     lebo Firefox da jednemu rozsireniu len jedno tlacidlo) mali stav bez
//     toho, aby kazde zvlast hladalo prehravac a pytalo sa ho kazde 2 s.
//
// API prehravaca (music_player/metadata_server.py):
//   GET  /api/now-playing   co hra, pozicia, hlasitost, playlistVersion
//   GET  /api/playlist      cely playlist (stahuje sa len pri zmene verzie)
//   POST /api/control       {"action": "playpause" | "next" | "seek" | ...}

const PORT = 8765;
const PREDVOLENI_HOSTIA = ["127.0.0.1", "192.168.1.50", "192.168.1.51"];
const TIMEOUT_MS = 1500;
const OBNOVA_MS = 2000;        // kym prehravac odpoveda
const HLADANIE_MS = 10000;     // ked nie je nikde (notebook spi)

// Tlacidla v liste — musi sediet s tlacidla/varianty.json (zabal.ps1 to overi).
const TLACIDLA = [
  "mmp-predosla@lukacmichal",
  "mmp-hraj@lukacmichal",
  "mmp-dalsia@lukacmichal",
  "mmp-stlmit@lukacmichal",
];

let hostia = PREDVOLENI_HOSTIA.slice();
let aktivny = null;
let stav = null;
let zive = [];
let playlist = null;
let playlistKluc = "";
let beziaceObnovenie = null;

// ── siet ─────────────────────────────────────────────────────────────────────
function adresa(host, cesta) {
  // "192.168.1.50" -> port sa doplni; "192.168.1.50:9000" sa necha tak.
  const sPortom = /:\d+$/.test(host) ? host : `${host}:${PORT}`;
  return `http://${sPortom}${cesta}`;
}

async function ziskaj(host, cesta) {
  const ac = new AbortController();
  const casovac = setTimeout(() => ac.abort(), TIMEOUT_MS);
  try {
    const odpoved = await fetch(adresa(host, cesta), { signal: ac.signal, cache: "no-store" });
    if (!odpoved.ok) throw new Error(`HTTP ${odpoved.status}`);
    return await odpoved.json();
  } finally {
    clearTimeout(casovac);
  }
}

async function posli(akcia, parametre = {}) {
  if (!aktivny) throw new Error("prehrávač nedostupný");
  const odpoved = await fetch(adresa(aktivny, "/api/control"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: akcia, ...parametre }),
    cache: "no-store",
  });
  if (!odpoved.ok) throw new Error(`HTTP ${odpoved.status}`);
}

// ── hladanie a obnova ────────────────────────────────────────────────────────
// Prehravac sa presuva medzi dvoma notebookmi a telefon ho hlada UDP
// beaconom — ten rozsirenie pocuvat nevie. Preto sa skusia vsetky adresy
// naraz a vyhra ta, kde hudba prave hra.
async function najdi() {
  const vysledky = await Promise.all(
    hostia.map((h) => ziskaj(h, "/api/now-playing").then((s) => ({ h, s }), () => null))
  );
  const odpovedaju = vysledky.filter(Boolean);
  zive = odpovedaju.map((z) => z.h);
  if (!odpovedaju.length) {
    aktivny = null;
    stav = null;
    return;
  }
  const { aktivnyUlozeny } = await browser.storage.local.get("aktivnyUlozeny");
  const ulozeny = odpovedaju.find((z) => z.h === aktivnyUlozeny);
  const hra = odpovedaju.find((z) => z.s.state === "playing");
  // Posledna volba plati, kym nehra niekde inde — ked hra druhy notebook,
  // chce clovek ovladat ten.
  const vyber = ulozeny && (ulozeny.s.state === "playing" || !hra) ? ulozeny : hra || odpovedaju[0];
  nastavAktivny(vyber.h, vyber.s);
}

function nastavAktivny(host, s) {
  if (host !== aktivny) {
    aktivny = host;
    playlist = null;
    playlistKluc = "";
  }
  stav = s;
}

async function _obnov() {
  if (!aktivny) {
    await najdi();
  } else {
    try {
      stav = await ziskaj(aktivny, "/api/now-playing");
    } catch (e) {
      // Notebook zaspal alebo sa prehravac zavrel — skus ostatne adresy.
      aktivny = null;
      await najdi();
    }
  }
  rozposli();
}

// Naraz sa moze pytat casovac, okienko aj tlacidlo — do siete ide jedna otazka.
function obnov() {
  if (!beziaceObnovenie) {
    beziaceObnovenie = _obnov().finally(() => { beziaceObnovenie = null; });
  }
  return beziaceObnovenie;
}

async function slucka() {
  try {
    await obnov();
  } finally {
    setTimeout(slucka, aktivny ? OBNOVA_MS : HLADANIE_MS);
  }
}

function verejnyStav() {
  return { typ: "stav", dostupny: Boolean(aktivny && stav), aktivny, zive, hostia, stav };
}

function rozposli() {
  const s = verejnyStav();
  for (const id of TLACIDLA) {
    // Tlacidlo, ktore nie je nainstalovane, sa ozve chybou — to je v poriadku.
    browser.runtime.sendMessage(id, s).catch(() => {});
  }
}

async function dajPlaylist() {
  if (!aktivny || !stav) return null;
  const kluc = `${aktivny}#${stav.playlistVersion}`;
  if (kluc !== playlistKluc || !playlist) {
    const data = await ziskaj(aktivny, "/api/playlist");
    playlist = data.items;
    playlistKluc = kluc;
  }
  return { kluc: playlistKluc, polozky: playlist };
}

// ── prikazy (z okienka aj z tlacidiel) ───────────────────────────────────────
async function prikaz(akcia, parametre = {}) {
  if (!aktivny) await obnov();
  if (akcia === "mute") {
    // Stlmenie si pamata hlasitost, aby ju vedelo vratit — tu, nie v kazdom
    // tlacidle zvlast, nech okienko aj tlacidlo vratia tu istu.
    if (!stav) return verejnyStav();
    if (stav.volume > 0) {
      await browser.storage.local.set({ predStlmenim: stav.volume });
      await posli("setVolume", { value: 0 });
    } else {
      const { predStlmenim } = await browser.storage.local.get("predStlmenim");
      await posli("setVolume", { value: predStlmenim || 50 });
    }
  } else {
    await posli(akcia, parametre);
  }
  // Prehravac vykona prikaz na svojom hlavnom vlakne — chvilu pockaj.
  await new Promise((r) => setTimeout(r, 200));
  await obnov();
  return verejnyStav();
}

// ── spravy ───────────────────────────────────────────────────────────────────
// Z vlastneho okienka.
browser.runtime.onMessage.addListener((sprava) => {
  switch (sprava && sprava.typ) {
    case "stav":
      return (sprava.cerstvy ? obnov() : Promise.resolve()).then(verejnyStav);
    case "playlist":
      return dajPlaylist();
    case "prikaz":
      return prikaz(sprava.akcia, sprava.parametre);
    case "prepni":
      return browser.storage.local.set({ aktivnyUlozeny: sprava.host }).then(async () => {
        aktivny = sprava.host;
        playlist = null;
        playlistKluc = "";
        await obnov();
        return verejnyStav();
      });
    default:
      return undefined;
  }
});

// Z tlacidiel v liste — len od nasich styroch, nikoho ineho.
browser.runtime.onMessageExternal.addListener((sprava, odosielatel) => {
  if (!TLACIDLA.includes(odosielatel.id)) return undefined;
  if (sprava && sprava.typ === "stav") return Promise.resolve(verejnyStav());
  if (sprava && sprava.typ === "prikaz" && ["prev", "playpause", "next", "mute"].includes(sprava.akcia)) {
    return prikaz(sprava.akcia).catch(() => verejnyStav());
  }
  return undefined;
});

// Okienko zmenilo zoznam adries.
browser.storage.onChanged.addListener((zmeny, oblast) => {
  if (oblast !== "local" || !zmeny.hostia) return;
  const novy = zmeny.hostia.newValue;
  hostia = Array.isArray(novy) && novy.length ? novy : PREDVOLENI_HOSTIA.slice();
  aktivny = null;
  obnov();
});

(async () => {
  const ulozene = await browser.storage.local.get("hostia");
  if (Array.isArray(ulozene.hostia) && ulozene.hostia.length) hostia = ulozene.hostia;
  slucka();
})();
