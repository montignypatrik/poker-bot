//! Card primitives shared across the Rust core.
//!
//! A card is a `u8` in `0..52` encoded as `rank * 4 + suit`:
//!   - rank: 0..=12  (0 = deuce, 8 = ten, 12 = ace)
//!   - suit: 0..=3   (0 = clubs, 1 = diamonds, 2 = hearts, 3 = spades)
//! The Python side (`pokerlab/cards.py`) mirrors this exact encoding.

/// Rank of a card, 0..=12.
#[inline(always)]
pub fn rank(card: u8) -> u8 {
    card >> 2 // card / 4
}

/// Suit of a card, 0..=3.
#[inline(always)]
pub fn suit(card: u8) -> u8 {
    card & 0b11 // card % 4
}

/// True if every card index is a valid 0..52 value.
#[inline]
pub fn all_valid(cards: &[u8]) -> bool {
    cards.iter().all(|&c| c < 52)
}
