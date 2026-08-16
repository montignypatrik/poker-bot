function lastActionFor(history, position) {
  for (let i = history.length - 1; i >= 0; i -= 1) {
    if (history[i].position === position) return history[i];
  }
  return null;
}

function cardLabel(entry) {
  if (!entry) return null;
  if (entry.action === "fold") return "Fold";
  if (entry.action === "call") return `Call ${entry.toBB}`;
  return `Raise ${entry.toBB}`;
}

export function renderPositionRow(mount, { positions, stacks, history, activePosition }, onSelect) {
  mount.replaceChildren();
  const row = document.createElement("div");
  row.className = "position-row";
  positions.forEach((position) => {
    const entry = lastActionFor(history, position);
    const label = cardLabel(entry);
    const card = document.createElement("button");
    card.type = "button";
    card.className = "seat-card";
    if (position === activePosition) card.classList.add("seat-card--active");
    else if (entry?.action === "fold") card.classList.add("seat-card--folded");
    else if (entry) card.classList.add("seat-card--live");
    else card.classList.add("seat-card--undecided");
    card.innerHTML = `<span class="seat-name">${position}</span><span class="seat-stack">${stacks[position]}bb</span><span class="seat-action">${label || "Undecided"}</span>`;
    card.addEventListener("click", () => onSelect(position, entry));
    row.append(card);
  });
  mount.append(row);
}

export function renderCommitPanel(mount, { actions, position, facingBB, stack, onCommit }) {
  mount.replaceChildren();
  const panel = document.createElement("div");
  panel.className = "commit-panel";
  const title = document.createElement("p");
  title.className = "commit-title";
  title.textContent = `Set ${position}'s action`;
  panel.append(title);
  const row = document.createElement("div");
  row.className = "commit-row";
  panel.append(row);

  if (actions.includes("f")) {
    const fold = document.createElement("button");
    fold.type = "button";
    fold.className = "action-button";
    fold.textContent = "Fold";
    fold.addEventListener("click", () => onCommit({ position, action: "fold", toBB: 0 }));
    row.append(fold);
  }
  if (actions.includes("c")) {
    const call = document.createElement("button");
    call.type = "button";
    call.className = "action-button";
    call.textContent = facingBB ? `Call ${facingBB}` : "Call";
    call.addEventListener("click", () => onCommit({ position, action: "call", toBB: facingBB || 0 }));
    row.append(call);
  }
  if (actions.includes("r")) {
    const size = document.createElement("input");
    size.type = "number";
    size.min = String((facingBB || 0) + 0.1);
    size.step = "0.1";
    size.value = facingBB ? Math.min(stack, Math.round((facingBB * 2.5) * 10) / 10) : 2.3;
    size.className = "commit-size";
    size.setAttribute("aria-label", `${position} raise size in big blinds`);
    const raise = document.createElement("button");
    raise.type = "button";
    raise.className = "action-button";
    raise.textContent = "Raise to";
    raise.addEventListener("click", () => onCommit({ position, action: "raise", toBB: Math.min(stack, Number(size.value)) }));
    const allin = document.createElement("button");
    allin.type = "button";
    allin.className = "action-button";
    allin.textContent = `All-in ${stack}`;
    allin.addEventListener("click", () => onCommit({ position, action: "raise", toBB: stack }));
    row.append(size, raise, allin);
  }
  mount.append(panel);
}
