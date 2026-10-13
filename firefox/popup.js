"use strict";
// Okienko rozsirenia — ovladanie Metal Music Playera.
//
// Do siete samo nechodi: prehravac hlada, stav drzi a playlist si pamata
// pozadie rozsirenia (pozadie.js). Okienko sa ho len pyta, preto sa otvori
// hned s hotovymi udajmi a nehlada prehravac pri kazdom kliknuti.

const PREDVOLENI_HOSTIA = ["127.0.0.1", "192.168.1.50", "192.168.1.51"];
const OBNOVA_MS = 1000;
const POTVRDENIE_MS = 3000;

const $ = (id) => document.getElementById(id);

let hostia = PREDVOLENI_HOSTIA.slice();
let aktivny = null;          // adresa prehravaca, ktory ovladame
let stav = null;             // posledne /api/now-playing
let stavCas = 0;             // kedy prisiel (na plynuly posun casu medzi dotazmi)
let playlistKluc = "";       // host + playlistVersion zobrazeneho playlistu
let playlistDlzka = 0;
let tahamHlasitost = false;
let prvyPlaylist = true;

// ── rozhovor s pozadim ───────────────────────────────────────────────────────
function pozadie(sprava) {
  return browser.runtime.sendMessage(sprava);
}

async function posli(akcia, parametre = {}) {
  try {
    prijmi(await pozadie({ typ: "prikaz", akcia, parametre }));
  } catch (e) {
    ukazStav(`Príkaz sa nedostal k prehrávaču (${aktivny || "nenájdený"}).`);
  }
}

async function obnov(cerstvy = true) {
  try {
    prijmi(await pozadie({ typ: "stav", cerstvy }));
  } catch (e) {
    ukazStav("Pozadie rozšírenia neodpovedá.");
  }
}

// ── vykreslenie ──────────────────────────────────────────────────────────────
function cas(ms) {
  const s = Math.max(0, Math.floor((ms || 0) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function ukazStav(text) {
  $("stav").textContent = text;
}

function ukazNedostupny() {
  $("prehravac").hidden = true;
  $("nedostupny").hidden = false;
  $("nedostupny-text").textContent =
    `Prehrávač som nenašiel (${hostia.join(", ")}). ` +
    "Beží na notebooku a notebook nespí? Adresy zmeníš cez ⚙.";
  ukazStav("Prehrávač nedostupný");
}

const NAZVY_STAVOV = { playing: "hrá", paused: "pauza", stopped: "zastavené" };

// Odpoved pozadia: {dostupny, aktivny, zive, hostia, stav}.
function prijmi(odpoved) {
  if (!odpoved) return;
  hostia = odpoved.hostia || hostia;
  vykresliHostov(odpoved.zive || []);
  if (!odpoved.dostupny) {
    aktivny = null;
    stav = null;
    ukazNedostupny();
    return;
  }
  if (odpoved.aktivny !== aktivny) {
    aktivny = odpoved.aktivny;
    playlistKluc = "";
    prvyPlaylist = true;
  }
  prijmiStav(odpoved.stav);
}

function prijmiStav(s) {
  stav = s;
  stavCas = Date.now();
  $("nedostupny").hidden = true;
  $("prehravac").hidden = false;

  const stavText = NAZVY_STAVOV[s.state] || s.state || "";
  $("stav").replaceChildren(
    Object.assign(document.createElement("span"), { className: "bodka", textContent: "● " }),
    document.createTextNode(`${aktivny} · ${stavText}`)
  );
  $("titul").textContent = s.title || "—";
  $("interpret").textContent = s.artist || "";
  $("titul").title = s.title || "";
  $("playpause").textContent = s.state === "playing" ? "⏸" : "▶";
  $("dlzka").textContent = cas(s.durationMs);
  if (!tahamHlasitost) {
    $("hlasitost").value = s.volume;
    $("hlasitost-cislo").textContent = s.volume;
  }
  $("stlmit").textContent = s.volume > 0 ? "🔊" : "🔇";
  posunCas();

  if (`${aktivny}#${s.playlistVersion}` !== playlistKluc) {
    nacitajPlaylist();
  } else {
    oznacHrajucu();
  }
}

function aktualnaPozicia() {
  if (!stav) return 0;
  let pozicia = stav.positionMs || 0;
  if (stav.state === "playing") pozicia += Date.now() - stavCas;
  return Math.min(pozicia, stav.durationMs || pozicia);
}

function posunCas() {
  if (!stav) return;
  const pozicia = aktualnaPozicia();
  $("cas").textContent = cas(pozicia);
  const podiel = stav.durationMs > 0 ? pozicia / stav.durationMs : 0;
  $("pas-plny").style.width = `${Math.min(100, podiel * 100)}%`;
}

function vykresliHostov(zoznam) {
  const box = $("hostia");
  // Volba adresy ma zmysel len vtedy, ked prehravac bezi na viac miestach.
  if (zoznam.length < 2) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.replaceChildren(
    ...zoznam.map((h) => {
      const b = document.createElement("button");
      b.textContent = h;
      b.title = "Ovládať prehrávač na tejto adrese";
      if (h === aktivny) b.classList.add("vybrany");
      // Volba sa pamata: aj tlacidla v liste a dalsie otvorenie okienka
      // budu ovladat tuto adresu, kym hudba nehra inde.
      b.addEventListener("click", async () => prijmi(await pozadie({ typ: "prepni", host: h })));
      return b;
    })
  );
}

// ── playlist ─────────────────────────────────────────────────────────────────
let nacitavaSa = false;

async function nacitajPlaylist() {
  if (nacitavaSa) return;
  nacitavaSa = true;
  let data;
  try {
    data = await pozadie({ typ: "playlist" });
  } catch (e) {
    data = null;
  } finally {
    nacitavaSa = false;
  }
  if (!data) return;   // skusi sa pri dalsom obnoveni
  playlistKluc = data.kluc;
  const fragment = document.createDocumentFragment();
  for (const polozka of data.polozky) {
    const li = document.createElement("li");
    li.dataset.index = polozka.index;
    const meno = polozka.artist ? `${polozka.artist} – ${polozka.title}` : polozka.title;
    li.dataset.hladaj = normalizuj(meno);
    li.title = meno;
    const cislo = Object.assign(document.createElement("span"),
      { className: "cislo-riadku", textContent: `${polozka.index + 1}.` });
    const nazov = Object.assign(document.createElement("span"),
      { className: "nazov", textContent: meno });
    const dlzka = Object.assign(document.createElement("span"),
      { className: "dlzka", textContent: polozka.durationMs > 0 ? cas(polozka.durationMs) : "" });
    li.append(cislo, nazov, dlzka);
    fragment.append(li);
  }
  $("playlist").replaceChildren(fragment);
  playlistDlzka = data.polozky.length;
  filtruj();
  oznacHrajucu();
  if (prvyPlaylist) {
    prvyPlaylist = false;
    skocNaHrajucu();
  }
}

function oznacHrajucu() {
  const ol = $("playlist");
  const predtym = ol.querySelector("li.hra");
  const index = stav ? stav.currentIndex : -1;
  if (predtym && Number(predtym.dataset.index) === index) return;
  if (predtym) predtym.classList.remove("hra");
  const teraz = ol.children[index];
  if (teraz) teraz.classList.add("hra");
}

function skocNaHrajucu() {
  const li = $("playlist").querySelector("li.hra");
  if (li && !li.hidden) li.scrollIntoView({ block: "center" });
}

// Pismena, ktore NFD na zaklad s diakritikou nerozlozi — v metale caste
// (Mgła, Ødelagt), a "mgla" ich ma najst.
const ZVLASTNE_PISMENA = { "ł": "l", "ø": "o", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe", "þ": "th" };

function normalizuj(text) {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[łøđßæœþ]/g, (p) => ZVLASTNE_PISMENA[p]);
}

function filtruj() {
  const hladane = normalizuj($("hladaj").value.trim());
  let zobrazene = 0;
  for (const li of $("playlist").children) {
    const ukaz = !hladane || li.dataset.hladaj.includes(hladane);
    li.hidden = !ukaz;
    if (ukaz) zobrazene++;
  }
  $("pocet").textContent = hladane
    ? `${zobrazene} z ${playlistDlzka} skladieb`
    : `${playlistDlzka} skladieb`;
}

// ── nastavenia ───────────────────────────────────────────────────────────────
function bezPortu(host) {
  return host.replace(/:\d+$/, "");
}

async function ulozHostov() {
  const novy = $("hostia-pole").value
    .split(/[\s,;]+/)
    .map((h) => h.trim().replace(/^https?:\/\//, "").replace(/\/.*$/, ""))
    .filter(Boolean);
  if (!novy.length) {
    $("nastavenia-sprava").textContent = "Zoznam je prázdny — nechávam pôvodný.";
    return;
  }
  // Adresy mimo manifestu potrebuju povolenie. Ziadost musi ist hned
  // z kliknutia (bez await pred nou), inak ju Firefox zamietne.
  const origins = [...new Set(novy.map((h) => `http://${bezPortu(h)}/*`))];
  let povolene = true;
  try {
    povolene = await browser.permissions.request({ origins });
  } catch (e) {
    povolene = false;
  }
  if (!povolene) {
    $("nastavenia-sprava").textContent = "Bez povolenia sa na tie adresy rozšírenie nedostane.";
    return;
  }
  hostia = novy;
  // Pozadie zmenu zachyti cez storage.onChanged a prehravac hlada nanovo.
  await browser.storage.local.set({ hostia });
  $("nastavenia-sprava").textContent = "Uložené.";
  setTimeout(obnov, 300);
}

// ── udalosti ─────────────────────────────────────────────────────────────────
function dvojklik(tlacidlo) {
  // Spanok meni playlist a vecer konci uspanim PC — omylom kliknut sa nema.
  // Firefox v okienku rozsirenia confirm() neukaze, preto druhy klik.
  const povodny = tlacidlo.textContent;
  tlacidlo.addEventListener("click", () => {
    if (tlacidlo.classList.contains("potvrd")) {
      tlacidlo.classList.remove("potvrd");
      tlacidlo.textContent = povodny;
      posli(tlacidlo.dataset.akcia);
      return;
    }
    tlacidlo.classList.add("potvrd");
    tlacidlo.textContent = "Naozaj? Klikni znova";
    setTimeout(() => {
      tlacidlo.classList.remove("potvrd");
      tlacidlo.textContent = povodny;
    }, POTVRDENIE_MS);
  });
}

$("playpause").addEventListener("click", () => posli("playpause"));
$("stop").addEventListener("click", () => posli("stop"));
$("next").addEventListener("click", () => posli("next"));
$("prev").addEventListener("click", () => posli("prev"));
$("stlmit").addEventListener("click", () => posli("mute"));
dvojklik($("spanok"));
dvojklik($("spanok2"));

$("pas").addEventListener("click", (e) => {
  if (!stav || !(stav.durationMs > 0)) return;
  const r = e.currentTarget.getBoundingClientRect();
  const podiel = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  posli("seek", { positionMs: Math.round(podiel * stav.durationMs) });
});

const hlasitost = $("hlasitost");
hlasitost.addEventListener("pointerdown", () => { tahamHlasitost = true; });
hlasitost.addEventListener("input", () => { $("hlasitost-cislo").textContent = hlasitost.value; });
hlasitost.addEventListener("change", () => {
  tahamHlasitost = false;
  posli("setVolume", { value: Number(hlasitost.value) });
});

$("playlist").addEventListener("click", (e) => {
  const li = e.target.closest("li");
  if (li) posli("playIndex", { index: Number(li.dataset.index) });
});
$("hladaj").addEventListener("input", filtruj);
$("aktualna").addEventListener("click", () => {
  if ($("hladaj").value) {
    $("hladaj").value = "";
    filtruj();
  }
  skocNaHrajucu();
});

$("skusit").addEventListener("click", () => { ukazStav("Hľadám prehrávač…"); obnov(); });
$("nastavenia-btn").addEventListener("click", () => {
  const panel = $("nastavenia");
  panel.hidden = !panel.hidden;
  // Okienko rozsirenia je vysoke najviac ~600 px — pod playlistom by
  // nastavenia neboli vidno, preto prehravac na ten cas ustupi.
  document.body.classList.toggle("nastavenia-otvorene", !panel.hidden);
  if (!panel.hidden) {
    $("hostia-pole").value = hostia.join("\n");
    $("nastavenia-sprava").textContent = "";
  }
});
$("ulozit").addEventListener("click", ulozHostov);
$("predvolene").addEventListener("click", () => {
  $("hostia-pole").value = PREDVOLENI_HOSTIA.join("\n");
});

// ── start ────────────────────────────────────────────────────────────────────
(async () => {
  // Najprv to, co pozadie uz vie (okamzite), potom cerstvy stav. Ked pozadie
  // este nic nenaslo (Firefox sa prave zapol), ostane "Hladam prehravac…".
  try {
    const hned = await pozadie({ typ: "stav", cerstvy: false });
    if (hned && hned.dostupny) prijmi(hned);
  } catch (e) { /* pozadie sa este len rozbieha */ }
  obnov(true);
  setInterval(obnov, OBNOVA_MS);
  setInterval(posunCas, 250);
})();
