import { actionName } from "./range_grid.js";

export function openQuiz(mount, config) {
  const item = config.items[Math.floor(Math.random() * config.items.length)];
  const strategy = config.strategy(item);
  const best = config.actions.reduce((winner, action) => (strategy[action] || 0) > (strategy[winner] || 0) ? action : winner, config.actions[0]);
  mount.innerHTML = `<div class="quiz-card"><div class="quiz-top"><div><p class="eyebrow">Frequency drill</p><h3 class="quiz-prompt">${config.prompt(item)}</h3></div><button class="quiz-close" type="button" aria-label="Close quiz">Close</button></div><div class="quiz-actions"></div><p class="quiz-result" aria-live="polite">Choose the action you would take. Grading uses equilibrium frequency, not EV loss.</p></div>`;
  const actions = mount.querySelector(".quiz-actions");
  const result = mount.querySelector(".quiz-result");
  config.actions.forEach((action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = actionName(action);
    button.addEventListener("click", () => {
      const frequency = strategy[action] || 0;
      const correct = action === best;
      result.className = `quiz-result${correct ? " correct" : ""}`;
      result.textContent = `${correct ? "Highest-frequency action." : `The highest-frequency action is ${actionName(best)}.`} ${actionName(action)} appears ${(frequency * 100).toFixed(1)}% in equilibrium; ${actionName(best)} appears ${((strategy[best] || 0) * 100).toFixed(1)}%.`;
      actions.querySelectorAll("button").forEach((candidate) => { candidate.disabled = true; });
      const next = document.createElement("button");
      next.type = "button";
      next.textContent = "Next hand";
      next.disabled = false;
      next.addEventListener("click", () => openQuiz(mount, config));
      actions.append(next);
    });
    actions.append(button);
  });
  mount.querySelector(".quiz-close").addEventListener("click", () => mount.replaceChildren());
}
