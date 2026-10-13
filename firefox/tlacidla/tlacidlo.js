"use strict";
// Jedno tlacidlo do listy Firefoxu (⏮ ⏯ ⏭ alebo 🔇). Firefox da jednemu
// rozsireniu len jedno tlacidlo, preto su to styri male rozsirenia z tohto
// jedneho skriptu; ktore je ktore, urcuje konfig.js (vyraba ho zabal.ps1
// z varianty.json).
//
// Samo do siete nechodi. Stav aj prikazy idu cez hlavne rozsirenie
// (pozadie.js) — prehravac sa hlada na jednom mieste a adresy sa nastavuju
// len v jeho okienku.

const HLAVNE = "metal-music-player@lukacmichal";
const NOVY_POKUS_MS = 10000;

let aktualnaIkona = "";

function cas(ms) {
  const s = Math.max(0, Math.floor((ms || 0) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function nastavIkonu(meno) {
  if (meno === aktualnaIkona) return;
  aktualnaIkona = meno;
  browser.browserAction.setIcon({ path: { 16: `ikony/${meno}-16.png`, 32: `ikony/${meno}-32.png` } });
}

// odpoved = stav z pozadia hlavneho rozsirenia, alebo null, ked nie je.
function vykresli(odpoved) {
  if (!odpoved) {
    browser.browserAction.disable();
    browser.browserAction.setTitle({
      title: `${TLACIDLO.titul}\nChýba hlavné rozšírenie Metal Music Player (alebo je vypnuté).`,
    });
    return;
  }
  if (!odpoved.dostupny) {
    // Firefox zasedi vypnute tlacidlo sam — vidno na prvy pohlad, ze
    // prehravac nebezi alebo notebook spi.
    browser.browserAction.disable();
    browser.browserAction.setTitle({ title: `${TLACIDLO.titul}\nPrehrávač nedostupný (notebook spí?)` });
    return;
  }
  browser.browserAction.enable();
  const s = odpoved.stav;
  const skladba = s.artist ? `${s.artist} – ${s.title}` : s.title || "—";
  let titul = TLACIDLO.titul;
  let ikona = TLACIDLO.ikony[0];
  if (TLACIDLO.akcia === "playpause") {
    const hra = s.state === "playing";
    ikona = hra ? "pause" : "play";
    titul = hra ? "Pauza" : "Hrať";
  } else if (TLACIDLO.akcia === "mute") {
    const ticho = s.volume === 0;
    ikona = ticho ? "ticho" : "zvuk";
    titul = ticho ? "Vrátiť zvuk" : `Stlmiť (hlasitosť ${s.volume})`;
  }
  nastavIkonu(ikona);
  browser.browserAction.setTitle({
    title: `${titul}\n${skladba}\n${cas(s.positionMs)} / ${cas(s.durationMs)} · ${odpoved.aktivny}`,
  });
}

async function klik() {
  try {
    vykresli(await browser.runtime.sendMessage(HLAVNE, { typ: "prikaz", akcia: TLACIDLO.akcia }));
  } catch (e) {
    vykresli(null);
  }
}

async function prihlas() {
  try {
    vykresli(await browser.runtime.sendMessage(HLAVNE, { typ: "stav" }));
  } catch (e) {
    // Hlavne rozsirenie este nebezi (Firefox sa zapina) alebo chyba.
    vykresli(null);
    setTimeout(prihlas, NOVY_POKUS_MS);
  }
}

// Hlavne rozsirenie posiela stav samo pri kazdej obnove (kazde 2 s).
browser.runtime.onMessageExternal.addListener((sprava, odosielatel) => {
  if (odosielatel.id === HLAVNE && sprava && sprava.typ === "stav") vykresli(sprava);
});
browser.browserAction.onClicked.addListener(klik);
prihlas();
