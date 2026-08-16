//! Vectorized CFR+ postflop solver in Rust — a fast, multithreaded port of
//! `pokerlab/solver/vector_cfr.py`. Same public-tree algorithm and card-removal
//! model, so results match the NumPy reference (validated by exploitability and
//! by reproducing the clairvoyant-river equilibrium).
//!
//! Parallelism: at the first chance node (the turn card, up to ~48 outcomes),
//! the subtrees are disjoint — no two share a decision node — so they are walked
//! in parallel with rayon, which auto-scales to all CPU cores. `SyncCell` gives
//! the per-node regret/strategy arrays interior mutability that is sound here
//! precisely because each node is touched by exactly one thread.

use std::cell::UnsafeCell;
use std::collections::HashMap;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

use crate::eval7::eval7_fast;

const EPS: f64 = 1e-9;

/// Interior mutability that is `Sync`. SOUND ONLY because parallel tree walks
/// touch disjoint nodes (disjoint chance-subtrees), so no cell is ever accessed
/// by two threads at once.
struct SyncCell<T>(UnsafeCell<T>);
unsafe impl<T> Sync for SyncCell<T> {}
impl<T> SyncCell<T> {
    fn new(v: T) -> Self {
        SyncCell(UnsafeCell::new(v))
    }
    #[allow(clippy::mut_from_ref)]
    fn get(&self) -> &mut T {
        unsafe { &mut *self.0.get() }
    }
    fn view(&self) -> &T {
        unsafe { &*self.0.get() }
    }
}

enum Node {
    Decision {
        player: usize,
        actions: Vec<String>,
        children: Vec<usize>,
        regret: SyncCell<Vec<f64>>,
        strat_sum: SyncCell<Vec<f64>>,
    },
    Chance {
        cards: Vec<u8>,
        children: Vec<usize>,
        weight: f64,
    },
    TermShow {
        board: [u8; 5],
        scalar: f64,
    },
    TermFold {
        folder: usize,
        scalar: f64,
    },
    /// Depth-limited leaf: instead of dealing the remaining community streets,
    /// stop on a 3- or 4-card frontier `board` and settle at all-in equity.
    /// Behaves exactly like `TermShow` but uses a precomputed equity matrix in
    /// [-1, 1] (see `equity_matrix`) rather than the {-1,0,1} showdown signs.
    TermEquity {
        board: Vec<u8>,
        scalar: f64,
    },
}

struct Solver {
    oop: Vec<(u8, u8)>,
    ip: Vec<(u8, u8)>,
    h0: usize,
    h1: usize,
    mask0: Vec<u64>,
    mask1: Vec<u64>,
    valid: Vec<f64>,
    live0: Vec<f64>,
    live1: Vec<f64>,
    nodes: Vec<Node>,
    root: usize,
    signs: HashMap<[u8; 5], Vec<f64>>,
    equities: HashMap<Vec<u8>, Vec<f64>>,
}

fn hand_mask(h: (u8, u8)) -> u64 {
    (1u64 << h.0) | (1u64 << h.1)
}

/// All-in equity matrix for a 3- or 4-card frontier `board`.
///
/// `E[i][j] = (2*eq - 1) * valid[i][j]`, where `eq` = P(oop hand `i` beats ip
/// hand `j`), counting ties as 0.5, averaged over EVERY runout that completes
/// the board to five cards (the remaining deck minus the board and both hole
/// cards). Colliding pairs stay 0, mirroring the `signs` matrices. Values live
/// in [-1, 1] so a `TermEquity` leaf plugs into `matvec`/`vecmat` unchanged.
fn equity_matrix(board: &[u8], oop: &[(u8, u8)], ip: &[(u8, u8)],
                 valid: &[f64], h0: usize, h1: usize) -> Vec<f64> {
    let need = 5 - board.len(); // community cards still to come: 1 (turn) or 2 (flop)
    let mut bmask = 0u64;
    for &c in board {
        bmask |= 1u64 << c;
    }
    let avail: Vec<u8> = (0..52u8).filter(|c| bmask & (1u64 << c) == 0).collect();
    let mut e = vec![0.0f64; h0 * h1];
    for i in 0..h0 {
        let (a0, b0) = oop[i];
        for j in 0..h1 {
            if valid[i * h1 + j] == 0.0 {
                continue; // colliding pair -> leave 0
            }
            let (a1, b1) = ip[j];
            let ex = bmask | (1u64 << a0) | (1u64 << b0) | (1u64 << a1) | (1u64 << b1);
            let mut win = 0.0f64; // ties count 0.5
            let mut tot = 0.0f64;
            if need == 1 {
                // 4-card frontier: one river card completes the board.
                for &r in &avail {
                    if ex & (1u64 << r) != 0 {
                        continue;
                    }
                    let so = eval7_fast(&[a0, b0, board[0], board[1], board[2], board[3], r]);
                    let si = eval7_fast(&[a1, b1, board[0], board[1], board[2], board[3], r]);
                    tot += 1.0;
                    win += if so > si { 1.0 } else if so == si { 0.5 } else { 0.0 };
                }
            } else {
                // 3-card frontier: two cards (turn + river) complete the board.
                for x in 0..avail.len() {
                    let r1 = avail[x];
                    if ex & (1u64 << r1) != 0 {
                        continue;
                    }
                    for r2 in avail.iter().skip(x + 1) {
                        let r2 = *r2;
                        if ex & (1u64 << r2) != 0 {
                            continue;
                        }
                        let so = eval7_fast(&[a0, b0, board[0], board[1], board[2], r1, r2]);
                        let si = eval7_fast(&[a1, b1, board[0], board[1], board[2], r1, r2]);
                        tot += 1.0;
                        win += if so > si { 1.0 } else if so == si { 0.5 } else { 0.0 };
                    }
                }
            }
            let eq = if tot > 0.0 { win / tot } else { 0.5 };
            e[i * h1 + j] = (2.0 * eq - 1.0) * valid[i * h1 + j];
        }
    }
    e
}

impl Solver {
    #[allow(clippy::too_many_arguments)]
    fn new(board0: Vec<u8>, oop: Vec<(u8, u8)>, ip: Vec<(u8, u8)>, pot: f64, stack: f64,
           bet_sizes: Vec<f64>, max_raises: usize, depth_limit: Option<usize>,
           leaf_values: Option<HashMap<Vec<u8>, Vec<f64>>>) -> Solver {
        let h0 = oop.len();
        let h1 = ip.len();
        let mask0: Vec<u64> = oop.iter().map(|&h| hand_mask(h)).collect();
        let mask1: Vec<u64> = ip.iter().map(|&h| hand_mask(h)).collect();
        let mut valid = vec![0.0f64; h0 * h1];
        for i in 0..h0 {
            for j in 0..h1 {
                valid[i * h1 + j] = if (mask0[i] & mask1[j]) == 0 { 1.0 } else { 0.0 };
            }
        }
        let mut bmask = 0u64;
        for &c in &board0 {
            bmask |= 1u64 << c;
        }
        let live0: Vec<f64> = mask0.iter().map(|&m| if m & bmask == 0 { 1.0 } else { 0.0 }).collect();
        let live1: Vec<f64> = mask1.iter().map(|&m| if m & bmask == 0 { 1.0 } else { 0.0 }).collect();

        let mut b = Builder { nodes: Vec::new(), pot, stack, bet_sizes: &bet_sizes, max_raises,
                              h0, h1, depth_limit };
        let root = b.build(board0, [0.0, 0.0], [0.0, 0.0], 0, 0, 0, true, 0);
        let nodes = b.nodes;

        // Precompute all showdown sign matrices in parallel (read-only thereafter).
        let mut boards: Vec<[u8; 5]> = nodes.iter().filter_map(|n| match n {
            Node::TermShow { board, .. } => Some(*board),
            _ => None,
        }).collect();
        boards.sort_unstable();
        boards.dedup();
        let signs: HashMap<[u8; 5], Vec<f64>> = boards.par_iter().map(|&board| {
            let so: Vec<u32> = oop.iter().map(|&(a, c)|
                eval7_fast(&[a, c, board[0], board[1], board[2], board[3], board[4]])).collect();
            let si: Vec<u32> = ip.iter().map(|&(a, c)|
                eval7_fast(&[a, c, board[0], board[1], board[2], board[3], board[4]])).collect();
            let mut s = vec![0.0f64; h0 * h1];
            for i in 0..h0 {
                for j in 0..h1 {
                    let v = if so[i] > si[j] { 1.0 } else if so[i] < si[j] { -1.0 } else { 0.0 };
                    s[i * h1 + j] = v * valid[i * h1 + j];
                }
            }
            (board, s)
        }).collect();

        // Precompute all depth-limited equity matrices in parallel (empty and
        // free when no depth limit is set, so the default path is untouched).
        let mut eboards: Vec<Vec<u8>> = nodes.iter().filter_map(|n| match n {
            Node::TermEquity { board, .. } => Some(board.clone()),
            _ => None,
        }).collect();
        eboards.sort_unstable();
        eboards.dedup();
        // Depth-limited leaf values: use a caller-injected matrix for a frontier
        // board when provided (a learned leaf, Track 2), else the analytic all-in-
        // equity matrix. Default (None) -> every leaf analytic, path unchanged.
        let injected = leaf_values.unwrap_or_default();
        let equities: HashMap<Vec<u8>, Vec<f64>> = eboards.par_iter().map(|board| {
            match injected.get(board) {
                Some(m) => (board.clone(), m.clone()),
                None => (board.clone(), equity_matrix(board, &oop, &ip, &valid, h0, h1)),
            }
        }).collect();

        Solver { oop, ip, h0, h1, mask0, mask1, valid, live0, live1, nodes, root, signs, equities }
    }

    fn matvec(&self, m: &[f64], r1: &[f64], scalar: f64) -> Vec<f64> {
        let mut out = vec![0.0f64; self.h0];
        for i in 0..self.h0 {
            let base = i * self.h1;
            let mut acc = 0.0;
            for j in 0..self.h1 {
                acc += m[base + j] * r1[j];
            }
            out[i] = scalar * acc;
        }
        out
    }

    fn vecmat(&self, r0: &[f64], m: &[f64], scalar: f64) -> Vec<f64> {
        let mut out = vec![0.0f64; self.h1];
        for i in 0..self.h0 {
            let ri = r0[i];
            if ri == 0.0 {
                continue;
            }
            let base = i * self.h1;
            for j in 0..self.h1 {
                out[j] += ri * m[base + j];
            }
        }
        for j in 0..self.h1 {
            out[j] *= scalar;
        }
        out
    }

    fn strategy(regret: &[f64], hp: usize, a: usize) -> Vec<f64> {
        let mut s = vec![0.0f64; hp * a];
        for h in 0..hp {
            let base = h * a;
            let mut sum = 0.0;
            for ai in 0..a {
                let r = regret[base + ai];
                if r > 0.0 {
                    sum += r;
                }
            }
            if sum > EPS {
                for ai in 0..a {
                    let r = regret[base + ai];
                    s[base + ai] = if r > 0.0 { r / sum } else { 0.0 };
                }
            } else {
                let u = 1.0 / a as f64;
                for ai in 0..a {
                    s[base + ai] = u;
                }
            }
        }
        s
    }

    fn add_pair(mut a: (Vec<f64>, Vec<f64>), b: (Vec<f64>, Vec<f64>)) -> (Vec<f64>, Vec<f64>) {
        for i in 0..a.0.len() {
            a.0[i] += b.0[i];
        }
        for j in 0..a.1.len() {
            a.1[j] += b.1[j];
        }
        a
    }

    fn walk(&self, idx: usize, reach0: &[f64], reach1: &[f64], t: f64, par_ok: bool) -> (Vec<f64>, Vec<f64>) {
        match &self.nodes[idx] {
            Node::TermShow { board, scalar } => {
                let s = &self.signs[board];
                (self.matvec(s, reach1, *scalar), self.vecmat(reach0, s, -*scalar))
            }
            Node::TermEquity { board, scalar } => {
                let s = &self.equities[board];
                (self.matvec(s, reach1, *scalar), self.vecmat(reach0, s, -*scalar))
            }
            Node::TermFold { folder, scalar } => {
                let sign = if *folder == 1 { 1.0 } else { -1.0 };
                (self.matvec(&self.valid, reach1, sign * scalar),
                 self.vecmat(reach0, &self.valid, -sign * scalar))
            }
            Node::Chance { cards, children, weight } => {
                let w = *weight;
                let per = |ci: u8, child: usize| -> (Vec<f64>, Vec<f64>) {
                    let cm = 1u64 << ci;
                    let r0: Vec<f64> = (0..self.h0).map(|i| if self.mask0[i] & cm == 0 { reach0[i] } else { 0.0 }).collect();
                    let r1: Vec<f64> = (0..self.h1).map(|j| if self.mask1[j] & cm == 0 { reach1[j] } else { 0.0 }).collect();
                    let (c0, c1) = self.walk(child, &r0, &r1, t, false);
                    let mut o0 = vec![0.0f64; self.h0];
                    let mut o1 = vec![0.0f64; self.h1];
                    for i in 0..self.h0 {
                        if self.mask0[i] & cm == 0 { o0[i] = w * c0[i]; }
                    }
                    for j in 0..self.h1 {
                        if self.mask1[j] & cm == 0 { o1[j] = w * c1[j]; }
                    }
                    (o0, o1)
                };
                let id = || (vec![0.0f64; self.h0], vec![0.0f64; self.h1]);
                if par_ok {
                    cards.par_iter().zip(children.par_iter())
                        .map(|(&ci, &child)| per(ci, child))
                        .reduce(id, Self::add_pair)
                } else {
                    let mut acc = id();
                    for (&ci, &child) in cards.iter().zip(children) {
                        acc = Self::add_pair(acc, per(ci, child));
                    }
                    acc
                }
            }
            Node::Decision { player, actions, children, regret, strat_sum } => {
                let a = actions.len();
                let hp = if *player == 0 { self.h0 } else { self.h1 };
                let strat = Self::strategy(regret.view(), hp, a);
                let mut cfv0 = vec![0.0f64; self.h0];
                let mut cfv1 = vec![0.0f64; self.h1];
                let mut action_val = vec![0.0f64; hp * a];
                for (ai, &child) in children.iter().enumerate() {
                    let (c0, c1) = if *player == 0 {
                        let r0: Vec<f64> = (0..self.h0).map(|i| reach0[i] * strat[i * a + ai]).collect();
                        self.walk(child, &r0, reach1, t, par_ok)
                    } else {
                        let r1: Vec<f64> = (0..self.h1).map(|j| reach1[j] * strat[j * a + ai]).collect();
                        self.walk(child, reach0, &r1, t, par_ok)
                    };
                    let src = if *player == 0 { &c0 } else { &c1 };
                    for h in 0..hp { action_val[h * a + ai] = src[h]; }
                    for i in 0..self.h0 { cfv0[i] += c0[i]; }
                    for j in 0..self.h1 { cfv1[j] += c1[j]; }
                }
                let mut node_val = vec![0.0f64; hp];
                for h in 0..hp {
                    let mut v = 0.0;
                    for ai in 0..a { v += strat[h * a + ai] * action_val[h * a + ai]; }
                    node_val[h] = v;
                }
                let reg = regret.get();
                for h in 0..hp {
                    for ai in 0..a {
                        let k = h * a + ai;
                        let nr = reg[k] + (action_val[k] - node_val[h]);
                        reg[k] = if nr > 0.0 { nr } else { 0.0 };
                    }
                }
                let ss = strat_sum.get();
                let reach_p = if *player == 0 { reach0 } else { reach1 };
                for h in 0..hp {
                    let wt = t * reach_p[h];
                    for ai in 0..a { ss[h * a + ai] += wt * strat[h * a + ai]; }
                }
                if *player == 0 { cfv0 = node_val; } else { cfv1 = node_val; }
                (cfv0, cfv1)
            }
        }
    }

    fn train(&self, iters: usize) {
        for it in 1..=iters {
            self.walk(self.root, &self.live0, &self.live1, it as f64, true);
        }
    }

    /// Train CFR seeded with explicit per-hand starting reaches (the players'
    /// ranges) instead of uniform. Used to generate DeepStack leaf-value targets
    /// over random range pairs.
    fn train_with(&self, r0: &[f64], r1: &[f64], iters: usize) {
        for it in 1..=iters {
            self.walk(self.root, r0, r1, it as f64, true);
        }
    }

    fn avg_strats(&self) -> Vec<Vec<f64>> {
        let mut out = Vec::with_capacity(self.nodes.len());
        for node in &self.nodes {
            match node {
                Node::Decision { player, actions, strat_sum, .. } => {
                    let a = actions.len();
                    let hp = if *player == 0 { self.h0 } else { self.h1 };
                    let ss = strat_sum.view();
                    let mut avg = vec![0.0f64; hp * a];
                    for h in 0..hp {
                        let base = h * a;
                        let mut tot = 0.0;
                        for ai in 0..a { tot += ss[base + ai]; }
                        if tot > EPS {
                            for ai in 0..a { avg[base + ai] = ss[base + ai] / tot; }
                        } else {
                            let u = 1.0 / a as f64;
                            for ai in 0..a { avg[base + ai] = u; }
                        }
                    }
                    out.push(avg);
                }
                _ => out.push(Vec::new()),
            }
        }
        out
    }

    fn ev_walk(&self, idx: usize, reach0: &[f64], reach1: &[f64], avg: &[Vec<f64>]) -> (Vec<f64>, Vec<f64>) {
        match &self.nodes[idx] {
            Node::TermShow { board, scalar } => {
                let s = &self.signs[board];
                (self.matvec(s, reach1, *scalar), self.vecmat(reach0, s, -*scalar))
            }
            Node::TermEquity { board, scalar } => {
                let s = &self.equities[board];
                (self.matvec(s, reach1, *scalar), self.vecmat(reach0, s, -*scalar))
            }
            Node::TermFold { folder, scalar } => {
                let sign = if *folder == 1 { 1.0 } else { -1.0 };
                (self.matvec(&self.valid, reach1, sign * scalar),
                 self.vecmat(reach0, &self.valid, -sign * scalar))
            }
            Node::Chance { cards, children, weight } => {
                let mut cfv0 = vec![0.0f64; self.h0];
                let mut cfv1 = vec![0.0f64; self.h1];
                for (&ci, &child) in cards.iter().zip(children) {
                    let cm = 1u64 << ci;
                    let r0: Vec<f64> = (0..self.h0).map(|i| if self.mask0[i] & cm == 0 { reach0[i] } else { 0.0 }).collect();
                    let r1: Vec<f64> = (0..self.h1).map(|j| if self.mask1[j] & cm == 0 { reach1[j] } else { 0.0 }).collect();
                    let (c0, c1) = self.ev_walk(child, &r0, &r1, avg);
                    for i in 0..self.h0 {
                        if self.mask0[i] & cm == 0 { cfv0[i] += weight * c0[i]; }
                    }
                    for j in 0..self.h1 {
                        if self.mask1[j] & cm == 0 { cfv1[j] += weight * c1[j]; }
                    }
                }
                (cfv0, cfv1)
            }
            Node::Decision { player, actions, children, .. } => {
                let a = actions.len();
                let hp = if *player == 0 { self.h0 } else { self.h1 };
                let strat = &avg[idx];
                let mut cfv0 = vec![0.0f64; self.h0];
                let mut cfv1 = vec![0.0f64; self.h1];
                let mut action_val = vec![0.0f64; hp * a];
                for (ai, &child) in children.iter().enumerate() {
                    let (c0, c1) = if *player == 0 {
                        let r0: Vec<f64> = (0..self.h0).map(|i| reach0[i] * strat[i * a + ai]).collect();
                        self.ev_walk(child, &r0, reach1, avg)
                    } else {
                        let r1: Vec<f64> = (0..self.h1).map(|j| reach1[j] * strat[j * a + ai]).collect();
                        self.ev_walk(child, reach0, &r1, avg)
                    };
                    let src = if *player == 0 { &c0 } else { &c1 };
                    for h in 0..hp { action_val[h * a + ai] = src[h]; }
                    for i in 0..self.h0 { cfv0[i] += c0[i]; }
                    for j in 0..self.h1 { cfv1[j] += c1[j]; }
                }
                let mut node_val = vec![0.0f64; hp];
                for h in 0..hp {
                    let mut v = 0.0;
                    for ai in 0..a { v += strat[h * a + ai] * action_val[h * a + ai]; }
                    node_val[h] = v;
                }
                if *player == 0 { cfv0 = node_val; } else { cfv1 = node_val; }
                (cfv0, cfv1)
            }
        }
    }

    fn br_walk(&self, idx: usize, reach_opp: &[f64], br: usize, avg: &[Vec<f64>]) -> Vec<f64> {
        let opp = 1 - br;
        match &self.nodes[idx] {
            Node::TermShow { board, scalar } => {
                let s = &self.signs[board];
                if br == 0 { self.matvec(s, reach_opp, *scalar) } else { self.vecmat(reach_opp, s, -*scalar) }
            }
            Node::TermEquity { board, scalar } => {
                let s = &self.equities[board];
                if br == 0 { self.matvec(s, reach_opp, *scalar) } else { self.vecmat(reach_opp, s, -*scalar) }
            }
            Node::TermFold { folder, scalar } => {
                let sign = if *folder == 1 { 1.0 } else { -1.0 };
                if br == 0 { self.matvec(&self.valid, reach_opp, sign * scalar) }
                else { self.vecmat(reach_opp, &self.valid, -sign * scalar) }
            }
            Node::Chance { cards, children, weight } => {
                let nb = if br == 0 { self.h0 } else { self.h1 };
                let mut acc = vec![0.0f64; nb];
                let (mask_br, mask_opp) = if br == 0 { (&self.mask0, &self.mask1) } else { (&self.mask1, &self.mask0) };
                for (&ci, &child) in cards.iter().zip(children) {
                    let cm = 1u64 << ci;
                    let ro: Vec<f64> = (0..reach_opp.len()).map(|k| if mask_opp[k] & cm == 0 { reach_opp[k] } else { 0.0 }).collect();
                    let c = self.br_walk(child, &ro, br, avg);
                    for k in 0..nb {
                        if mask_br[k] & cm == 0 { acc[k] += weight * c[k]; }
                    }
                }
                acc
            }
            Node::Decision { player, actions, children, .. } => {
                let a = actions.len();
                let nb = if br == 0 { self.h0 } else { self.h1 };
                if *player == br {
                    let mut best = vec![f64::NEG_INFINITY; nb];
                    for &child in children {
                        let c = self.br_walk(child, reach_opp, br, avg);
                        for k in 0..nb { if c[k] > best[k] { best[k] = c[k]; } }
                    }
                    best
                } else {
                    let strat = &avg[idx];
                    let mut acc = vec![0.0f64; nb];
                    for (ai, &child) in children.iter().enumerate() {
                        let ro: Vec<f64> = (0..reach_opp.len()).map(|k| reach_opp[k] * strat[k * a + ai]).collect();
                        let c = self.br_walk(child, &ro, br, avg);
                        for k in 0..nb { acc[k] += c[k]; }
                    }
                    acc
                }
            }
        }
    }

    fn exploitability(&self, avg: &[Vec<f64>]) -> f64 {
        let (cfv0, cfv1) = self.ev_walk(self.root, &self.live0, &self.live1, avg);
        let ev0: f64 = (0..self.h0).map(|i| self.live0[i] * cfv0[i]).sum();
        let ev1: f64 = (0..self.h1).map(|j| self.live1[j] * cfv1[j]).sum();
        let b0v = self.br_walk(self.root, &self.live1, 0, avg);
        let b1v = self.br_walk(self.root, &self.live0, 1, avg);
        let br0: f64 = (0..self.h0).map(|i| self.live0[i] * b0v[i]).sum();
        let br1: f64 = (0..self.h1).map(|j| self.live1[j] * b1v[j]).sum();
        let mut n_pairs = 0.0;
        for i in 0..self.h0 {
            for j in 0..self.h1 {
                n_pairs += self.live0[i] * self.live1[j] * self.valid[i * self.h1 + j];
            }
        }
        if n_pairs <= 0.0 { 0.0 } else { ((br0 - ev0) + (br1 - ev1)) / (2.0 * n_pairs) }
    }
}

struct Builder<'a> {
    nodes: Vec<Node>,
    pot: f64,
    stack: f64,
    bet_sizes: &'a [f64],
    max_raises: usize,
    h0: usize,
    h1: usize,
    /// When `Some(dl)`, deal at most `dl` community streets before replacing the
    /// next chance node with a `TermEquity` all-in-equity leaf. `None` = full
    /// solve (the default, byte-for-byte identical to the pre-depth-limit path).
    depth_limit: Option<usize>,
}

impl<'a> Builder<'a> {
    /// `depth` = number of community streets already dealt from the start board.
    fn build(&mut self, board: Vec<u8>, total: [f64; 2], rc: [f64; 2],
             actor: usize, n_actions: usize, n_raises: usize, street_open: bool,
             depth: usize) -> usize {
        if !street_open {
            if board.len() >= 5 {
                return self.term_show(&board, total, rc);
            }
            // Depth-limited: stop dealing here and settle at all-in equity.
            if let Some(dl) = self.depth_limit {
                if depth >= dl {
                    return self.term_equity(&board, total, rc);
                }
            }
            return self.chance(board, total, rc, depth);
        }
        let max_commit = rc[0].max(rc[1]);
        let committed = total[actor] + rc[actor];
        let can_bet = n_raises < self.max_raises && committed < self.stack - EPS;
        let facing = max_commit - rc[actor] > EPS;
        let mut actions: Vec<String> = Vec::new();
        if facing {
            actions.push("f".into());
            actions.push("c".into());
        } else {
            actions.push("x".into());
        }
        if can_bet {
            for i in 0..self.bet_sizes.len() {
                actions.push(format!("b{}", i));
            }
        }
        let idx = self.nodes.len();
        self.nodes.push(Node::TermFold { folder: 0, scalar: 0.0 }); // placeholder
        let mut children = Vec::with_capacity(actions.len());
        for act in &actions {
            children.push(self.apply(act, &board, total, rc, actor, n_actions, n_raises, depth));
        }
        let hp = if actor == 0 { self.h0 } else { self.h1 };
        self.nodes[idx] = Node::Decision {
            player: actor,
            children,
            regret: SyncCell::new(vec![0.0; hp * actions.len()]),
            strat_sum: SyncCell::new(vec![0.0; hp * actions.len()]),
            actions,
        };
        idx
    }

    fn apply(&mut self, act: &str, board: &[u8], total: [f64; 2], rc: [f64; 2],
             actor: usize, n_actions: usize, n_raises: usize, depth: usize) -> usize {
        let max_commit = rc[0].max(rc[1]);
        let mut rc = rc;
        if act == "f" {
            return self.term_fold(board, total, rc, actor);
        }
        if act == "c" {
            rc[actor] = max_commit;
            return self.build(board.to_vec(), total, rc, actor, n_actions + 1, n_raises, false, depth);
        }
        if act == "x" {
            if n_actions >= 1 {
                return self.build(board.to_vec(), total, rc, actor, n_actions + 1, n_raises, false, depth);
            }
            return self.build(board.to_vec(), total, rc, 1 - actor, n_actions + 1, n_raises, true, depth);
        }
        let bi: usize = act[1..].parse().unwrap();
        let pot_now = self.pot + total[0] + total[1] + rc[0] + rc[1];
        let target = max_commit + self.bet_sizes[bi] * pot_now;
        rc[actor] = target.min(self.stack - total[actor]);
        self.build(board.to_vec(), total, rc, 1 - actor, n_actions + 1, n_raises + 1, true, depth)
    }

    fn chance(&mut self, board: Vec<u8>, total: [f64; 2], rc: [f64; 2], depth: usize) -> usize {
        let total = [total[0] + rc[0], total[1] + rc[1]];
        let mut bmask = 0u64;
        for &c in &board {
            bmask |= 1u64 << c;
        }
        let cards: Vec<u8> = (0..52u8).filter(|c| bmask & (1u64 << c) == 0).collect();
        let weight = 1.0 / (cards.len() as f64 - 2.0);
        let idx = self.nodes.len();
        self.nodes.push(Node::TermFold { folder: 0, scalar: 0.0 }); // placeholder
        let mut children = Vec::with_capacity(cards.len());
        for &c in &cards {
            let mut nb = board.clone();
            nb.push(c);
            children.push(self.build(nb, total, [0.0, 0.0], 0, 0, 0, true, depth + 1));
        }
        self.nodes[idx] = Node::Chance { cards, children, weight };
        idx
    }

    /// Depth-limited all-in-equity leaf on a 3- or 4-card frontier `board`.
    /// Uses the same pot/stake convention as `term_show`; both contributions are
    /// equal here because betting has just closed, so `contrib[1]` is the stake.
    fn term_equity(&mut self, board: &[u8], total: [f64; 2], rc: [f64; 2]) -> usize {
        let contrib1 = total[1] + rc[1];
        let mut b = board.to_vec();
        b.sort_unstable();
        let idx = self.nodes.len();
        self.nodes.push(Node::TermEquity { board: b, scalar: self.pot / 2.0 + contrib1 });
        idx
    }

    fn term_show(&mut self, board: &[u8], total: [f64; 2], rc: [f64; 2]) -> usize {
        let contrib1 = total[1] + rc[1];
        let mut b = [board[0], board[1], board[2], board[3], board[4]];
        b.sort_unstable();
        let idx = self.nodes.len();
        self.nodes.push(Node::TermShow { board: b, scalar: self.pot / 2.0 + contrib1 });
        idx
    }

    fn term_fold(&mut self, _board: &[u8], total: [f64; 2], rc: [f64; 2], folder: usize) -> usize {
        let contrib = [total[0] + rc[0], total[1] + rc[1]];
        let idx = self.nodes.len();
        self.nodes.push(Node::TermFold { folder, scalar: self.pot / 2.0 + contrib[folder] });
        idx
    }
}

/// The analytic all-in-equity leaf matrix (flat, row-major `h0*h1`, values in
/// [-1, 1]) for a 3- or 4-card frontier `board` and the given ranges -- the Track 2
/// baseline / training reference. Row/column ordering matches `oop`/`ip` as passed,
/// so the result can be injected verbatim as `solve_postflop(..., leaf_values=...)`.
#[pyfunction]
pub fn equity_matrix_py(board: Vec<u8>, oop: Vec<(u8, u8)>, ip: Vec<(u8, u8)>)
    -> PyResult<Vec<f64>> {
    if !(3..=4).contains(&board.len()) {
        return Err(PyValueError::new_err("frontier board must have 3 or 4 cards"));
    }
    if oop.is_empty() || ip.is_empty() {
        return Err(PyValueError::new_err("empty range"));
    }
    let (h0, h1) = (oop.len(), ip.len());
    let mask0: Vec<u64> = oop.iter().map(|&h| hand_mask(h)).collect();
    let mask1: Vec<u64> = ip.iter().map(|&h| hand_mask(h)).collect();
    let mut valid = vec![0.0f64; h0 * h1];
    for i in 0..h0 {
        for j in 0..h1 {
            valid[i * h1 + j] = if (mask0[i] & mask1[j]) == 0 { 1.0 } else { 0.0 };
        }
    }
    Ok(equity_matrix(&board, &oop, &ip, &valid, h0, h1))
}

/// Full-solve a subgame under given starting ranges and return the per-hand ROOT
/// counterfactual values at equilibrium: `(cfv0, cfv1)`, lengths `h0`/`h1`. These
/// are the DeepStack leaf-value net's regression targets (Track 2). `reach0`/
/// `reach1` are per-hand range reach weights (default = uniform over hands that
/// don't collide with the board); board-colliding hands are always zeroed. The
/// solve is always full-depth (`depth_limit=None`) so the CFVs reflect true
/// continuation play, not the analytic all-in-equity approximation.
#[pyfunction]
#[pyo3(signature = (board, oop, ip, pot, stack, bet_sizes, max_raises, iters, reach0=None, reach1=None))]
#[allow(clippy::too_many_arguments)]
pub fn subgame_cfv(
    board: Vec<u8>,
    oop: Vec<(u8, u8)>,
    ip: Vec<(u8, u8)>,
    pot: f64,
    stack: f64,
    bet_sizes: Vec<f64>,
    max_raises: usize,
    iters: usize,
    reach0: Option<Vec<f64>>,
    reach1: Option<Vec<f64>>,
) -> PyResult<(Vec<f64>, Vec<f64>)> {
    if !(3..=5).contains(&board.len()) {
        return Err(PyValueError::new_err("board must have 3..5 cards"));
    }
    if oop.is_empty() || ip.is_empty() {
        return Err(PyValueError::new_err("empty range"));
    }
    let sol = Solver::new(board, oop, ip, pot, stack, bet_sizes, max_raises, None, None);
    if let Some(r) = &reach0 {
        if r.len() != sol.h0 {
            return Err(PyValueError::new_err("reach0 length must equal len(oop)"));
        }
    }
    if let Some(r) = &reach1 {
        if r.len() != sol.h1 {
            return Err(PyValueError::new_err("reach1 length must equal len(ip)"));
        }
    }
    // Default to uniform (live) reach; always zero out board-colliding hands.
    let r0: Vec<f64> = (0..sol.h0)
        .map(|i| reach0.as_ref().map_or(1.0, |r| r[i]) * sol.live0[i]).collect();
    let r1: Vec<f64> = (0..sol.h1)
        .map(|j| reach1.as_ref().map_or(1.0, |r| r[j]) * sol.live1[j]).collect();
    sol.train_with(&r0, &r1, iters);
    let avg = sol.avg_strats();
    Ok(sol.ev_walk(sol.root, &r0, &r1, &avg))
}

/// Solve a postflop subgame. Returns (exploitability, node_types, node_players,
/// node_children, node_actions, node_chance_cards, avg_strats, h0, h1, root).
/// Node type codes: 0 decision, 1 chance, 2 showdown, 3 fold, 4 depth-limited
/// equity leaf (terminal). `depth_limit` (default None = full solve) caps how
/// many community streets are dealt before the tree settles at all-in equity.
#[pyfunction]
#[pyo3(signature = (board, oop, ip, pot, stack, bet_sizes, max_raises, iters, depth_limit=None, leaf_values=None))]
#[allow(clippy::type_complexity, clippy::too_many_arguments)]
pub fn solve_postflop(
    board: Vec<u8>,
    oop: Vec<(u8, u8)>,
    ip: Vec<(u8, u8)>,
    pot: f64,
    stack: f64,
    bet_sizes: Vec<f64>,
    max_raises: usize,
    iters: usize,
    depth_limit: Option<usize>,
    leaf_values: Option<Vec<(Vec<u8>, Vec<f64>)>>,
) -> PyResult<(f64, Vec<u8>, Vec<i64>, Vec<Vec<usize>>, Vec<Vec<String>>, Vec<Vec<u8>>, Vec<Vec<f64>>, usize, usize, usize)> {
    if !(3..=5).contains(&board.len()) {
        return Err(PyValueError::new_err("board must have 3..5 cards"));
    }
    if oop.is_empty() || ip.is_empty() {
        return Err(PyValueError::new_err("empty range"));
    }
    // Optional learned-leaf injection (Track 2): a list of (frontier_board, flat
    // h0*h1 matrix in [-1,1]). Keys are sorted to match the solver's leaf boards.
    let leaf_map = match leaf_values {
        None => None,
        Some(pairs) => {
            let (h0, h1) = (oop.len(), ip.len());
            let mut m: HashMap<Vec<u8>, Vec<f64>> = HashMap::new();
            for (b, mat) in pairs {
                if mat.len() != h0 * h1 {
                    return Err(PyValueError::new_err(
                        "leaf_values matrix must be len oop*ip (row-major h0*h1)"));
                }
                let mut key = b;
                key.sort_unstable();
                m.insert(key, mat);
            }
            Some(m)
        }
    };
    let sol = Solver::new(board, oop, ip, pot, stack, bet_sizes, max_raises, depth_limit, leaf_map);
    sol.train(iters);
    let avg = sol.avg_strats();
    let expl = sol.exploitability(&avg);

    let n = sol.nodes.len();
    let mut types = vec![0u8; n];
    let mut players = vec![-1i64; n];
    let mut children: Vec<Vec<usize>> = vec![Vec::new(); n];
    let mut actions: Vec<Vec<String>> = vec![Vec::new(); n];
    let mut chance_cards: Vec<Vec<u8>> = vec![Vec::new(); n];
    for (i, node) in sol.nodes.iter().enumerate() {
        match node {
            Node::Decision { player, actions: acts, children: ch, .. } => {
                types[i] = 0;
                players[i] = *player as i64;
                children[i] = ch.clone();
                actions[i] = acts.clone();
            }
            Node::Chance { cards, children: ch, .. } => {
                types[i] = 1;
                children[i] = ch.clone();
                chance_cards[i] = cards.clone();
            }
            Node::TermShow { .. } => types[i] = 2,
            Node::TermFold { .. } => types[i] = 3,
            Node::TermEquity { .. } => types[i] = 4,
        }
    }
    Ok((expl, types, players, children, actions, chance_cards, avg, sol.h0, sol.h1, sol.root))
}
