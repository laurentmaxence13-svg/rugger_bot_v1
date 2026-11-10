"""Raydium CPMM (cp-swap) decoder and exact pool arithmetic for the MASTER research simulators.

EXPERIMENTAL, out of every frozen or anchored tree: it imports nothing from v4sim, v3lab, w1aux or
dayj, and nothing imports it. Offline, read-only, HISTORICAL_REPLAY research: never an order.

Pinned to the official program source raydium-io/raydium-cp-swap (branch master, fetched
2026-11-10), sha256 of the files the arithmetic and the layouts are transcribed from:
  states/events.rs               c81d5d9d75b1af21…  (SwapEvent, LpChangeEvent)
  curve/calculator.rs            aee16991f81d755a…  (swap_base_input, swap_base_output)
  curve/constant_product.rs      5a6ab835ba35e872…
  curve/fees.rs                  0d0b005123cd9e9e…
  instructions/swap_base_input.rs 5878ed09654745b5… (what the event fields mean, fee accounting)
  states/pool.rs                 e2a836869400bf3c…  (vault_amount_without_fee, update_fees)
STATUS: the layouts and the arithmetic are NOT yet checked against real mainnet swaps (criterion
A-12 of the V4 protocol: at least 99.9 % of observed swaps reproduced to the atomic unit).
"""
VERSION = '0.1'
