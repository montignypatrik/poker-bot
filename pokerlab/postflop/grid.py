from __future__ import annotations

import numpy as np

from ..engine.bots import hand_class


def combos_to_class_grid(combos, actions, arr):
    combos = list(combos)
    actions = list(actions)
    values = np.asarray(arr, dtype=float)
    expected = (len(combos), len(actions))
    if values.shape != expected:
        raise ValueError(f"strategy shape {values.shape} does not match {expected}")

    totals = {}
    counts = {}
    for combo, row in zip(combos, values):
        label = hand_class(combo)
        totals.setdefault(label, np.zeros(len(actions), dtype=float))
        totals[label] += row
        counts[label] = counts.get(label, 0) + 1

    return {
        label: {action: float(value) for action, value in zip(actions, totals[label] / counts[label])}
        for label in totals
    }
