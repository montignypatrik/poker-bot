//! 7-card No-Limit Hold'em hand evaluator.
//!
//! Phase 1 uses a correct, straightforward approach: score every 5-card subset
//! and keep the best. A `u32` score is returned where **higher is better**, so
//! two hands compare with plain integer comparison. The layout is:
//!
//! ```text
//!   bits 20..23 : category  (0 = high card … 8 = straight flush)
//!   bits  0..19 : tiebreak
//! ```
//!
//! For non-straight categories the tiebreak is five 4-bit rank nibbles ordered
//! by (count desc, rank desc) — e.g. a full house expands to `[t,t,t,p,p]`. For
//! straights and straight flushes the tiebreak is just the straight's high-card
//! rank, which orders them correctly (the wheel A-2-3-4-5 is treated as 5-high).
//!
//! Category and tiebreak never overflow into each other: nibbles are <16 and the
//! category is at most 8, so the encoding is monotonic across all categories.

use crate::cards::{rank, suit};

// Hand categories (also mirrored as names in Python).
pub const HIGH_CARD: u32 = 0;
pub const PAIR: u32 = 1;
pub const TWO_PAIR: u32 = 2;
pub const TRIPS: u32 = 3;
pub const STRAIGHT: u32 = 4;
pub const FLUSH: u32 = 5;
pub const FULL_HOUSE: u32 = 6;
pub const QUADS: u32 = 7;
pub const STRAIGHT_FLUSH: u32 = 8;

#[inline(always)]
fn encode(category: u32, tiebreak: u32) -> u32 {
    (category << 20) | tiebreak
}

/// Best straight high-card rank within a rank bitmask, or None.
/// The wheel (A-2-3-4-5) is reported as 5-high (rank 3).
#[inline]
fn best_straight(mask: u16) -> Option<u8> {
    for high in (4..13u8).rev() {
        let window = 0b11111u16 << (high - 4);
        if mask & window == window {
            return Some(high);
        }
    }
    const WHEEL: u16 = (1 << 12) | 0b1111;
    if mask & WHEEL == WHEEL {
        return Some(3);
    }
    None
}

/// Append the top `n` set ranks of `mask` (excluding `exclude`), high to low,
/// as 4-bit nibbles onto `tb`.
#[inline]
fn push_kickers(mut tb: u32, mask: u16, exclude: u16, n: usize) -> u32 {
    let m = mask & !exclude;
    let mut taken = 0;
    for r in (0..13usize).rev() {
        if taken >= n {
            break;
        }
        if m & (1 << r) != 0 {
            tb = (tb << 4) | (r as u32);
            taken += 1;
        }
    }
    tb
}

#[inline]
fn push_n(mut tb: u32, rank_val: u32, times: usize) -> u32 {
    for _ in 0..times {
        tb = (tb << 4) | rank_val;
    }
    tb
}

/// Score exactly five cards. Higher is better. Allocation-free hot path.
fn score5(c: &[u8; 5]) -> u32 {
    // Rank multiplicity, rank bitmask, and per-suit membership.
    let mut counts = [0u8; 13];
    let mut suit_counts = [0u8; 4];
    let mut mask: u16 = 0;
    for &card in c.iter() {
        let r = rank(card);
        counts[r as usize] += 1;
        suit_counts[suit(card) as usize] += 1;
        mask |= 1 << r;
    }
    let is_flush = suit_counts.iter().any(|&s| s == 5);
    let straight_high = best_straight(mask);

    // Two largest multiplicities determine the made-hand pattern.
    let mut c1 = 0u8; // largest multiplicity
    let mut c2 = 0u8; // second largest
    for &cnt in counts.iter() {
        if cnt > c1 {
            c2 = c1;
            c1 = cnt;
        } else if cnt > c2 {
            c2 = cnt;
        }
    }

    // Tiebreak nibbles: ranks ordered by (count desc, rank desc), expanded to
    // exactly five nibbles — e.g. full house K over 3 -> [K,K,K,3,3]. Built by
    // sweeping multiplicity buckets 4..=1 from high rank to low. No allocation.
    let nibbles = || -> u32 {
        let mut tb: u32 = 0;
        for target in (1..=4u8).rev() {
            for r in (0..13usize).rev() {
                if counts[r] == target {
                    for _ in 0..target {
                        tb = (tb << 4) | (r as u32);
                    }
                }
            }
        }
        tb
    };

    if is_flush && straight_high.is_some() {
        encode(STRAIGHT_FLUSH, straight_high.unwrap() as u32)
    } else if c1 == 4 {
        encode(QUADS, nibbles())
    } else if c1 == 3 && c2 == 2 {
        encode(FULL_HOUSE, nibbles())
    } else if is_flush {
        encode(FLUSH, nibbles())
    } else if let Some(h) = straight_high {
        encode(STRAIGHT, h as u32)
    } else if c1 == 3 {
        encode(TRIPS, nibbles())
    } else if c1 == 2 && c2 == 2 {
        encode(TWO_PAIR, nibbles())
    } else if c1 == 2 {
        encode(PAIR, nibbles())
    } else {
        encode(HIGH_CARD, nibbles())
    }
}

/// Direct 7-card evaluation — computes the best 5-card score without iterating
/// all 21 subsets. Returns exactly the same value as `eval_best` on 7 cards
/// (verified by an exhaustive random cross-check in the test suite), but ~10x
/// faster. This is the hot path used by `evaluate7`/`evaluate7_batch`.
pub fn eval7_fast(cards: &[u8; 7]) -> u32 {
    let mut counts = [0u8; 13];
    let mut suit_masks = [0u16; 4];
    let mut rank_mask = 0u16;
    for &c in cards.iter() {
        let r = rank(c);
        counts[r as usize] += 1;
        suit_masks[suit(c) as usize] |= 1 << r;
        rank_mask |= 1 << r;
    }

    // At most one suit can hold >= 5 of 7 cards, so the flush suit is unique.
    let mut flush_mask = 0u16;
    for &sm in suit_masks.iter() {
        if sm.count_ones() >= 5 {
            flush_mask = sm;
            break;
        }
    }
    if flush_mask != 0 {
        if let Some(h) = best_straight(flush_mask) {
            return encode(STRAIGHT_FLUSH, h as u32);
        }
    }

    // Bucket ranks by multiplicity, high rank to low.
    let mut quad = -1i32;
    let mut trips = [-1i32; 2];
    let mut n_trips = 0usize;
    let mut pairs = [-1i32; 3];
    let mut n_pairs = 0usize;
    for r in (0..13usize).rev() {
        match counts[r] {
            4 => quad = r as i32,
            3 => {
                if n_trips < 2 {
                    trips[n_trips] = r as i32;
                    n_trips += 1;
                }
            }
            2 => {
                if n_pairs < 3 {
                    pairs[n_pairs] = r as i32;
                    n_pairs += 1;
                }
            }
            _ => {}
        }
    }

    // Categories in descending strength; first match wins.
    if quad >= 0 {
        let q = quad as u32;
        let tb = push_kickers(push_n(0, q, 4), rank_mask, 1 << quad, 1);
        return encode(QUADS, tb);
    }
    if n_trips >= 1 && (n_pairs >= 1 || n_trips >= 2) {
        let t = trips[0] as u32;
        // Best pair rank: highest of the remaining pair(s) / leftover trip.
        let pair_rank = if n_trips >= 2 {
            trips[1].max(if n_pairs >= 1 { pairs[0] } else { -1 })
        } else {
            pairs[0]
        } as u32;
        let tb = push_n(push_n(0, t, 3), pair_rank, 2);
        return encode(FULL_HOUSE, tb);
    }
    if flush_mask != 0 {
        return encode(FLUSH, push_kickers(0, flush_mask, 0, 5));
    }
    if let Some(h) = best_straight(rank_mask) {
        return encode(STRAIGHT, h as u32);
    }
    if n_trips >= 1 {
        let t = trips[0] as u32;
        let tb = push_kickers(push_n(0, t, 3), rank_mask, 1 << trips[0], 2);
        return encode(TRIPS, tb);
    }
    if n_pairs >= 2 {
        let p1 = pairs[0] as u32;
        let p2 = pairs[1] as u32;
        let excl = (1u16 << pairs[0]) | (1u16 << pairs[1]);
        let tb = push_kickers(push_n(push_n(0, p1, 2), p2, 2), rank_mask, excl, 1);
        return encode(TWO_PAIR, tb);
    }
    if n_pairs == 1 {
        let p = pairs[0] as u32;
        let tb = push_kickers(push_n(0, p, 2), rank_mask, 1 << pairs[0], 3);
        return encode(PAIR, tb);
    }
    encode(HIGH_CARD, push_kickers(0, rank_mask, 0, 5))
}

/// Evaluate the best 5-card hand from 5, 6, or 7 cards. Higher is better.
/// Panics if `cards.len()` is outside 5..=7. Reference implementation
/// (exhaustive over 5-subsets); the 7-card hot path uses `eval7_fast`.
pub fn eval_best(cards: &[u8]) -> u32 {
    let n = cards.len();
    assert!((5..=7).contains(&n), "eval_best needs 5..=7 cards, got {n}");
    let mut best = 0u32;
    // All 5-subsets via ordered indices a<b<c<d<e.
    for a in 0..n - 4 {
        for b in a + 1..n - 3 {
            for c in b + 1..n - 2 {
                for d in c + 1..n - 1 {
                    for e in d + 1..n {
                        let five = [cards[a], cards[b], cards[c], cards[d], cards[e]];
                        let s = score5(&five);
                        if s > best {
                            best = s;
                        }
                    }
                }
            }
        }
    }
    best
}
