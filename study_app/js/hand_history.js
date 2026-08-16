import { api } from "./api.js";
import { loadSituation } from "./preflop_trainer.js";

const fileSelect = document.querySelector("#history-file");
const status = document.querySelector("#history-status");
const handsMount = document.querySelector("#history-hands");
const viewer = document.querySelector("#history-viewer");
const kicker = document.querySelector("#history-kicker");
const summary = document.querySelector("#history-summary");
const studyButton = document.querySelector("#history-study-button");

let currentSituation = null;
let currentLabel = "";

function resultLabel(result) {
  if (!result) return "";
  if (result.outcome === "won") return result.amount != null ? `won ${result.amount}` : "won";
  if (result.outcome === "folded") return "folded";
  return "";
}

async function loadHand(file, handId) {
  kicker.textContent = "Loading...";
  studyButton.disabled = true;
  try {
    const hand = await api.get("/hand-history/hand", { file, id: handId });
    viewer.classList.remove("empty-state");
    viewer.textContent = hand.raw_text;
    kicker.textContent = `${hand.game_type} · ${hand.datetime}`;
    summary.textContent = `Hand #${hand.hand_id}`;
    currentLabel = `Hand #${hand.hand_id} (${hand.datetime})`;
    const situation = hand.situation;
    if (situation.note) {
      currentSituation = null;
      studyButton.disabled = true;
      studyButton.title = situation.note;
    } else {
      currentSituation = situation;
      studyButton.disabled = false;
      studyButton.title = "";
    }
  } catch (error) {
    viewer.className = "hand-viewer empty-state";
    viewer.textContent = error.message;
  }
}

async function loadHands(file) {
  if (!file) return;
  handsMount.className = "hand-list empty-state";
  handsMount.textContent = "Loading hands...";
  try {
    const result = await api.get("/hand-history/hands", { file });
    handsMount.classList.remove("empty-state");
    handsMount.replaceChildren();
    if (!result.hands.length) {
      handsMount.classList.add("empty-state");
      handsMount.textContent = "No hands found in this file.";
      return;
    }
    result.hands.forEach((hand) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "hand-item";
      const cards = hand.heroCards ? hand.heroCards.join(" ") : "--";
      const position = hand.heroPosition || "?";
      item.innerHTML = `<span class="hand-item-main">${cards} · ${position}</span><span class="hand-item-meta">${hand.datetime} · ${resultLabel(hand.result)}</span>`;
      item.addEventListener("click", () => loadHand(file, hand.handId));
      handsMount.append(item);
    });
  } catch (error) {
    handsMount.className = "hand-list empty-state";
    handsMount.textContent = error.message;
  }
}

async function loadFiles() {
  status.className = "status-line";
  status.textContent = "Loading files...";
  try {
    const result = await api.get("/hand-history/files");
    fileSelect.replaceChildren();
    if (!result.files.length) {
      status.className = "status-line error";
      status.textContent = result.note || "No hand history files found.";
      return;
    }
    result.files.forEach((file) => fileSelect.add(new Option(file.name, file.name)));
    status.textContent = "";
    loadHands(fileSelect.value);
  } catch (error) {
    status.className = "status-line error";
    status.textContent = error.message;
  }
}

fileSelect.addEventListener("change", () => loadHands(fileSelect.value));

studyButton.addEventListener("click", () => {
  if (!currentSituation) return;
  loadSituation(currentSituation, currentLabel);
  document.querySelector('.tab[data-tab="preflop"]').click();
});

loadFiles();
