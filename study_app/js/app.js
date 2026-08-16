import "./preflop_trainer.js";
import "./hand_history.js";

const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".tab-panel");

function activate(name) {
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  panels.forEach((panel) => {
    const active = panel.id === `${name}-panel`;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
  history.replaceState(null, "", `#${name}`);
}

tabs.forEach((tab) => tab.addEventListener("click", () => activate(tab.dataset.tab)));
const requested = location.hash.slice(1);
activate([...tabs].some((tab) => tab.dataset.tab === requested) ? requested : "preflop");
