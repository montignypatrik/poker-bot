import { api } from "./api.js";
import { openQuiz } from "./quiz.js";
import { actionName, renderDetail, renderRangeGrid } from "./range_grid.js";
import { renderCommitPanel, renderPositionRow } from "./position_row.js";

const DEFAULT_POSITIONS = ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"];

const settingsForm = document.querySelector("#preflop-settings");
const status = document.querySelector("#preflop-status");
const positionsMount = document.querySelector("#preflop-positions");
const compareMount = document.querySelector("#preflop-compare");
const commitMount = document.querySelector("#preflop-commit");
const grid = document.querySelector("#preflop-grid");
const detail = document.querySelector("#preflop-detail");
const summary = document.querySelector("#preflop-summary");
const kicker = document.querySelector("#preflop-kicker");
const resetButton = document.querySelector("#preflop-reset");
const quizButton = document.querySelector("#preflop-quiz-button");
const quizMount = document.querySelector("#preflop-quiz");

let positions = DEFAULT_POSITIONS;
let stacks = {};
let history = [];
let activePosition = null;
let current = null;
let loadedHeroContext = null;

function settings() {
  return {
    payouts: String(settingsForm.elements.payouts.value).split(",").map(Number),
    anteBB: Number(settingsForm.elements.ante.value),
    iterations: Number(settingsForm.elements.iterations.value),
  };
}

function currentNode(result) {
  if (result.shape === "rfi") {
    const classes = Object.fromEntries(
      Object.entries(result.rfi.open_freq).map(([hand, freq]) => [hand, { fold: 1 - freq, raise: freq }])
    );
    return { classes, actions: ["fold", "raise"], commitActions: ["f", "r"], label: `Raise-first-in — ${result.rfi.open_pct.toFixed(1)}% open range` };
  }
  const level = result.levels[result.levels.length - 1];
  const classes = level.strategies;
  const sample = classes.AA || Object.values(classes)[0] || {};
  const actions = Object.keys(sample);
  return {
    classes,
    actions,
    commitActions: actions,
    label: `${result.shape.replaceAll("_", " ")} — ${level.role} facing ${level.betSizeBB}bb`,
  };
}

function clearStrategyPanels(message) {
  grid.className = "range-mount empty-state";
  grid.textContent = message;
  detail.replaceChildren();
  quizMount.replaceChildren();
  quizButton.disabled = true;
  commitMount.replaceChildren();
  compareMount.replaceChildren();
  current = null;
}

const ACTION_ALIASES = { fold: ["fold", "f"], call: ["call", "c"], raise: ["raise", "r", "bet"] };

function actionDescription(action) {
  if (action.action === "fold") return "folded";
  if (action.action === "call") return `called ${action.toBB}bb`;
  return `raised to ${action.toBB}bb`;
}

function renderCompare() {
  compareMount.replaceChildren();
  if (!loadedHeroContext || loadedHeroContext.position !== activePosition || !current) return;
  const { heroClass, heroCards, heroAction, label } = loadedHeroContext;
  const strategy = heroClass ? current.classes[heroClass] : null;
  const key = strategy ? (ACTION_ALIASES[heroAction.action] || []).find((k) => current.actions.includes(k)) : null;
  const cardsText = heroCards ? heroCards.join(" ") : heroClass || "your hand";
  const did = actionDescription(heroAction);

  const card = document.createElement("div");
  card.className = "compare-card";
  if (!strategy || key == null) {
    card.innerHTML = `<p class="eyebrow">What you did vs GTO${label ? ` — ${label}` : ""}</p>`
      + `<p>You had <strong>${cardsText}</strong> and <strong>${did}</strong>. GTO comparison isn't available for this decision shape yet.</p>`;
  } else {
    const best = current.actions.reduce((w, a) => (strategy[a] || 0) > (strategy[w] || 0) ? a : w, current.actions[0]);
    const correct = key === best;
    const pills = current.actions
      .map((a) => `<span class="freq-pill${a === key ? " chosen" : ""}">${actionName(a)} ${(100 * (strategy[a] || 0)).toFixed(1)}%</span>`)
      .join("");
    card.classList.add(correct ? "compare-good" : "compare-off");
    card.innerHTML = `<p class="eyebrow">What you did vs GTO${label ? ` — ${label}` : ""}</p>`
      + `<p>You had <strong>${cardsText}</strong> (${heroClass}) and <strong>${did}</strong> — the equilibrium plays that `
      + `<strong>${(100 * (strategy[key] || 0)).toFixed(1)}%</strong> of the time${correct ? " (its highest-frequency action)." : `; GTO prefers <strong>${actionName(best)}</strong> (${(100 * (strategy[best] || 0)).toFixed(1)}%).`}</p>`
      + `<div class="detail-row">${pills}</div>`;
  }
  compareMount.append(card);
}

function renderPositions() {
  renderPositionRow(positionsMount, { positions, stacks, history, activePosition }, (position, entry) => {
    if (entry) {
      const cut = history.indexOf(entry);
      history = history.slice(0, cut);
    }
    activePosition = position;
    clearStrategyPanels("Solving...");
    renderPositions();
    solveActive();
  });
}

function renderCommit() {
  const lastRaise = [...history].reverse().find((a) => a.action === "raise");
  renderCommitPanel(commitMount, {
    actions: current.commitActions,
    position: activePosition,
    facingBB: lastRaise ? lastRaise.toBB : 0,
    stack: stacks[activePosition],
    onCommit: (entry) => {
      history = [...history, entry];
      activePosition = null;
      clearStrategyPanels("Select an undecided seat to solve its node.");
      status.textContent = `${entry.position} is set to ${entry.action}${entry.action === "raise" ? ` ${entry.toBB}bb` : ""}. Select the next seat.`;
      renderPositions();
    },
  });
}

async function solveActive() {
  status.className = "status-line";
  status.innerHTML = '<span class="spinner"></span>Computing the ICM-aware strategy...';
  try {
    const result = await api.post("/mtt-preflop", {
      positions,
      startingStacks: stacks,
      heroPosition: activePosition,
      actions: history,
      ...settings(),
    });
    current = currentNode(result);
    kicker.textContent = result.shape.replaceAll("_", " ");
    summary.textContent = `${activePosition}: ${current.label}`;
    renderRangeGrid(grid, current.classes, current.actions, (hand, strategy) => renderDetail(detail, hand, strategy, current.actions));
    renderCompare();
    renderCommit();
    status.textContent = "Solution ready. Select any hand to inspect its exact mix, then lock in an action below.";
    quizButton.disabled = false;
  } catch (error) {
    status.className = "status-line error";
    status.textContent = error.message;
    activePosition = null;
    renderPositions();
  }
}

function uniformStacks(positionList) {
  const stack = Number(settingsForm.elements.stack.value);
  return Object.fromEntries(positionList.map((position) => [position, stack]));
}

function resetHand() {
  positions = DEFAULT_POSITIONS;
  stacks = uniformStacks(positions);
  history = [];
  activePosition = null;
  loadedHeroContext = null;
  clearStrategyPanels("Select a seat below to solve its node.");
  status.className = "status-line";
  status.textContent = "Select a seat below to begin.";
  renderPositions();
}

settingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  resetHand();
});

resetButton.addEventListener("click", resetHand);

quizButton.addEventListener("click", () => {
  if (!current || !activePosition) return;
  const items = Object.keys(current.classes);
  openQuiz(quizMount, {
    items,
    actions: current.actions,
    strategy: (hand) => current.classes[hand],
    prompt: (hand) => `${activePosition} — what is your action with ${hand}?`,
  });
});

export function loadSituation(situation, label) {
  positions = situation.positions;
  stacks = situation.startingStacks;
  history = situation.history;
  activePosition = situation.heroPosition;
  loadedHeroContext = situation.heroAction
    ? { position: situation.heroPosition, heroClass: situation.heroClass, heroCards: situation.heroCards, heroAction: situation.heroAction, label }
    : null;
  settingsForm.elements.ante.value = situation.anteBB;
  clearStrategyPanels("Solving...");
  status.className = "status-line";
  status.textContent = label ? `Loaded: ${label}` : "Loaded from hand history.";
  renderPositions();
  solveActive();
}

resetHand();
