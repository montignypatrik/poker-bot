const RANKS = "AKQJT98765432".split("");
const COLORS = {
  fold: "#b84f49", f: "#b84f49", call: "#3978b7", c: "#3978b7",
  check: "#56655f", x: "#56655f", raise: "#168b62", r: "#168b62",
  b0: "#20a570", b1: "#df9f31", b2: "#a86bd5",
};

export function actionName(action) {
  return ({ f: "Fold", c: "Call", r: "Raise", x: "Check", b0: "Bet small", b1: "Bet large", b2: "Bet 3", raise: "Raise", fold: "Fold" })[action] || action;
}

function handAt(row, col) {
  if (row === col) return RANKS[row] + RANKS[col];
  if (row < col) return RANKS[row] + RANKS[col] + "s";
  return RANKS[col] + RANKS[row] + "o";
}

function background(strategy, actions) {
  let cursor = 0;
  const stops = [];
  actions.forEach((action) => {
    const start = cursor;
    cursor += Math.max(0, Number(strategy[action] || 0)) * 100;
    const color = COLORS[action] || "#7357a6";
    stops.push(`${color} ${start}%`, `${color} ${cursor}%`);
  });
  if (cursor < 99.9) stops.push(`#26312e ${cursor}%`, "#26312e 100%");
  return `linear-gradient(90deg, ${stops.join(",")})`;
}

export function renderRangeGrid(mount, classes, actions, onSelect) {
  mount.classList.remove("empty-state");
  mount.replaceChildren();
  const scroll = document.createElement("div");
  scroll.className = "grid-scroll";
  const grid = document.createElement("div");
  grid.className = "range-grid";
  RANKS.forEach((_, row) => RANKS.forEach((__, col) => {
    const hand = handAt(row, col);
    const strategy = classes[hand] || {};
    const best = actions.reduce((winner, action) => (strategy[action] || 0) > (strategy[winner] || 0) ? action : winner, actions[0]);
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "range-cell";
    cell.style.background = background(strategy, actions);
    cell.innerHTML = `<strong>${hand}</strong><small>${strategy[best] == null ? "--" : `${Math.round(strategy[best] * 100)}% ${actionName(best)}`}</small>`;
    cell.setAttribute("aria-label", `${hand}: ${actions.map((a) => `${actionName(a)} ${Math.round((strategy[a] || 0) * 100)} percent`).join(", ")}`);
    cell.addEventListener("click", () => onSelect?.(hand, strategy));
    grid.append(cell);
  }));
  scroll.append(grid);
  const legend = document.createElement("div");
  legend.className = "grid-legend";
  actions.forEach((action) => {
    const item = document.createElement("span");
    item.className = "legend-item";
    item.innerHTML = `<i class="legend-swatch" style="background:${COLORS[action] || "#7357a6"}"></i>${actionName(action)}`;
    legend.append(item);
  });
  mount.append(scroll, legend);
}

export function renderDetail(mount, label, strategy, actions) {
  mount.innerHTML = `<div class="detail-row"><strong>${label}</strong>${actions.map((action) => `<span class="freq-pill">${actionName(action)} ${(100 * (strategy[action] || 0)).toFixed(1)}%</span>`).join("")}</div>`;
}
