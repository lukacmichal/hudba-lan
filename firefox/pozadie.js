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
//   GET  /api/now-playing   co hra, pozicia, hlasitost, playlistVersion;
//                           od prehravaca 1.25 aj album, farby obalu a
//                           albumAktivny (music_player/integracia.py)
//   GET  /api/playlist      cely playlist (stahuje sa len pri zmene verzie)
//   GET  /api/cover?v=...   obal albumu (okienko)
//   POST /api/control       {"action": "playpause" | "next" | "seek" | ...}
//
// Od verzie 1.2 farbi aj Firefox podla albumu, ktory hra (tema).

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
  aktualizujTemu();
}

// ── tema podla albumu ────────────────────────────────────────────────────────
// Farby obalu pocita prehravac (pozadie_plochy.farby_z_obalu) — tie iste
// ma aj pozadie plochy. "albumAktivny" = hra, alebo pauza kratsia ako 5 min.
// Tema sa meni len pri zmene farieb, nie kazde 2 s. Ked hudba nehra alebo
// prehravac nie je, theme.reset() vrati temu, ktoru ma clovek vybratu.
let temaZapnuta = true;
let temaKluc = "";

function temaZFarieb(f) {
  return {
    colors: {
      frame: f.pozadie,
      frame_inactive: f.pozadie,
      tab_background_text: f.text,
      tab_selected: f.lista,
      tab_text: f.text,
      tab_line: f.akcent,
      tab_loading: f.akcent,
      toolbar: f.lista,
      toolbar_text: f.text,
      toolbar_field: f.pozadie,
      toolbar_field_text: f.text,
      toolbar_field_focus: f.pozadie,
      toolbar_field_text_focus: f.text,
      toolbar_field_border_focus: f.akcent,
      toolbar_bottom_separator: f.pozadie,
      icons: f.text,
      icons_attention: f.akcent,
      popup: f.lista,
      popup_text: f.text,
      popup_border: f.pozadie,
      popup_highlight: f.akcent,
      popup_highlight_text: f.pozadie,
      sidebar: f.pozadie,
      sidebar_text: f.text,
      sidebar_border: f.lista,
      // Nova karta (Firefox Home) — pozadie prehliadaca v doslovnom zmysle.
      ntp_background: f.pozadie,
      ntp_text: f.text,
      button_background_hover: "rgba(255, 255, 255, 0.10)",
      button_background_active: "rgba(255, 255, 255, 0.18)",
    },
  };
}

async function aktualizujTemu() {
  const f = stav && stav.albumAktivny && stav.farby;
  const chcem = temaZapnuta && aktivny && f ? JSON.stringify(f) : "";
  if (chcem === temaKluc) return;
  temaKluc = chcem;
  try {
    if (chcem) {
      await browser.theme.update(temaZFarieb(f));
    } else {
      await browser.theme.reset();
    }
  } catch (e) {
    temaKluc = "";   // skusi sa znova pri dalsom obnoveni
  }
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

// Okienko zmenilo zoznam adries alebo vypinac temy.
browser.storage.onChanged.addListener((zmeny, oblast) => {
  if (oblast !== "local") return;
  if (zmeny.temaZapnuta) {
    temaZapnuta = zmeny.temaZapnuta.newValue !== false;
    aktualizujTemu();
  }
  if (!zmeny.hostia) return;
  const novy = zmeny.hostia.newValue;
  hostia = Array.isArray(novy) && novy.length ? novy : PREDVOLENI_HOSTIA.slice();
  aktivny = null;
  obnov();
});

(async () => {
  const ulozene = await browser.storage.local.get(["hostia", "temaZapnuta"]);
  if (Array.isArray(ulozene.hostia) && ulozene.hostia.length) hostia = ulozene.hostia;
  temaZapnuta = ulozene.temaZapnuta !== false;
  // Tema z minuleho behu Firefoxu, ktora uz nemusi platit (hudba medzicasom
  // dohrala) — kym sa prehravac neozve, nech je tema cloveka.
  browser.theme.reset().catch(() => {});
  slucka();
})();
