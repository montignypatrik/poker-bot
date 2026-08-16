//! poker_core — Rust hot-path core for the pokerbot lab.
//!
//! Exposes the 7-card hand evaluator to Python as `pokerlab.poker_core`.
//! The CFR regret loop lands here in Phase 3.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

mod cards;
mod eval7;
mod vsolver;

/// Liveness smoke test.
#[pyfunction]
fn ping() -> &'static str {
    "pong"
}

/// Evaluate a full 7-card hand. `cards` must be 7 distinct indices in 0..52.
/// Returns a u32 score where higher is a stronger hand.
#[pyfunction]
fn evaluate7(cards: Vec<u8>) -> PyResult<u32> {
    if cards.len() != 7 {
        return Err(PyValueError::new_err(format!(
            "evaluate7 expects 7 cards, got {}",
            cards.len()
        )));
    }
    if !cards::all_valid(&cards) {
        return Err(PyValueError::new_err("card indices must be in 0..52"));
    }
    let arr: [u8; 7] = cards.try_into().unwrap();
    Ok(eval7::eval7_fast(&arr))
}

/// Reference 7-card evaluation via exhaustive 5-subset search. Slower; used by
/// the test suite to cross-check the fast path.
#[pyfunction]
fn evaluate7_ref(cards: Vec<u8>) -> PyResult<u32> {
    if cards.len() != 7 {
        return Err(PyValueError::new_err(format!(
            "evaluate7_ref expects 7 cards, got {}",
            cards.len()
        )));
    }
    if !cards::all_valid(&cards) {
        return Err(PyValueError::new_err("card indices must be in 0..52"));
    }
    Ok(eval7::eval_best(&cards))
}

/// Evaluate the best hand from 5, 6, or 7 cards.
#[pyfunction]
fn evaluate_best(cards: Vec<u8>) -> PyResult<u32> {
    if !(5..=7).contains(&cards.len()) {
        return Err(PyValueError::new_err(format!(
            "evaluate_best expects 5..=7 cards, got {}",
            cards.len()
        )));
    }
    if !cards::all_valid(&cards) {
        return Err(PyValueError::new_err("card indices must be in 0..52"));
    }
    Ok(eval7::eval_best(&cards))
}

/// Best hand from hole cards + board (2 + 3..5 cards). Convenience wrapper.
#[pyfunction]
fn best_of(hole: Vec<u8>, board: Vec<u8>) -> PyResult<u32> {
    let mut all = hole;
    all.extend_from_slice(&board);
    evaluate_best(all)
}

/// Evaluate many 7-card hands at once. `flat` is `k * 7` card indices laid out
/// consecutively; returns `k` scores. Amortizes FFI overhead — used by the
/// Monte-Carlo equity engine and for throughput benchmarking.
#[pyfunction]
fn evaluate7_batch(flat: Vec<u8>) -> PyResult<Vec<u32>> {
    if flat.len() % 7 != 0 {
        return Err(PyValueError::new_err("flat length must be a multiple of 7"));
    }
    if !cards::all_valid(&flat) {
        return Err(PyValueError::new_err("card indices must be in 0..52"));
    }
    Ok(flat
        .chunks_exact(7)
        .map(|c| eval7::eval7_fast(c.try_into().unwrap()))
        .collect())
}

/// Category (0 = high card … 8 = straight flush) of an evaluator score.
#[pyfunction]
fn category(score: u32) -> u8 {
    (score >> 20) as u8
}

#[pymodule]
fn poker_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(ping, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate7, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate7_ref, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_best, m)?)?;
    m.add_function(wrap_pyfunction!(best_of, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate7_batch, m)?)?;
    m.add_function(wrap_pyfunction!(category, m)?)?;
    m.add_function(wrap_pyfunction!(vsolver::solve_postflop, m)?)?;
    m.add_function(wrap_pyfunction!(vsolver::equity_matrix_py, m)?)?;
    m.add_function(wrap_pyfunction!(vsolver::subgame_cfv, m)?)?;
    Ok(())
}
