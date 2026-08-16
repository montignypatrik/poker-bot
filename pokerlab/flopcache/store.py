from __future__ import annotations

import gzip
import json
from pathlib import Path

SCHEMA_VERSION = 1

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_TABLE_PATH = DATA_DIR / "flop_table.json.gz"

_ROUND = 5


def node_key(path):
    return "|".join(path)


def hero_node_paths(bet_sizes):
    paths = [(), ("x",)]
    for i in range(len(bet_sizes)):
        paths.append((f"b{i}",))
    for i in range(len(bet_sizes)):
        paths.append(("x", f"b{i}"))
    return paths


def new_table(params):
    return {"version": SCHEMA_VERSION, "params": dict(params), "flops": {}}


def _round_rows(rows):
    return [[round(float(p), _ROUND) for p in row] for row in rows]


def add_flop(table, key, nodes):
    stored = {}
    for node_key, node in nodes.items():
        stored[node_key] = {
            "player": int(node["player"]),
            "actions": list(node["actions"]),
            "strategy": _round_rows(node["strategy"]),
        }
    table["flops"][key] = {"nodes": stored}


def save_table(table, path=DEFAULT_TABLE_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(table, separators=(",", ":"))
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(payload)
    else:
        path.write_text(payload, encoding="utf-8")
    return path


def load_table(path=DEFAULT_TABLE_PATH):
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            table = json.load(fh)
    else:
        table = json.loads(path.read_text(encoding="utf-8"))
    if table.get("version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported flop-table schema version: {table.get('version')!r}")
    return table
