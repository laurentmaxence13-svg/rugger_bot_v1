# Rugger Bot — representative LaunchLab P3/P4 economic cohort audit

**Date:** 2026-10-30. **Conclusion: NO-GO LIVE / Master edge NOT validated.**
This is the evidence state, not a successful financial certification.
No tokens were bought, sold or signed, and there is no privileged wallet access.

## Sources actually tested

1. **Raydium LaunchLab public 'new' index**:
   fixed `GET https://launch-mint-v1.raydium.io/get/list?sort=new`
   returned **HTTP 403** to GitHub Actions. The implementation and offline
   tests remain, but this inaccessible source cannot be presented as a
   prospective discovery universe. The associated workflow has been retired
   from automatic PR CI and retained as a manual diagnostic.
2. **Helius archival signatures**:
   bounded recent LaunchLab program page of 20 signatures and four signed
   finalized transactions, all four classified as non-creations. This does not
   disprove existence of other creations. Proof:
   https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41065729372
3. **Helius current program accounts**:
   unpaged `getProgramAccounts` overflowed the six-megabyte read cap.
   Paged `getProgramAccountsV2` produced a real **first page of 64
   filtered active SOL-quoted LaunchLab pool accounts** at slot `463311273`.
   Further pages exist. It is not the full universe and excludes failed,
   migrated and closed pools by design (survivorship bias). Proof:
   https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41068114735
4. **Prospective S1→S2 active-survivor experiment**:
   selected three distinct creator **claims** before fetching the exact
   seven-account S1 banks; held 12 seconds before S2. First successful
   capture registered `98741fb48253a3b52839b83cc6e5d301b7282b6b35a0c991a84d63d297498650`
   at root/S1 slot `463311988`, S2 slot `463312044`.
   All three S2 exit qualifications were refused. Two S1 exact-size
   hypothetical token quantities existed; none proves a funded lot,
   executable SELL or a positive P&L. Proof:
   https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41068501272
5. **Strict P4 completeness audit:** explicit 50-independent-creator
   held-out validation, verified signed creation, failed/closed launch
   inclusion, full-lot fees/exit proof, causal decision freezes, and fee/latency
   stress checks. Synthetic results and survivor-only scans remain NO-GO.
   The stored Master V2 archive report contains **4 mints, 8 banks,
   2 sessions, zero strict economic cycles**. See
   `bot/p3/master_oos_readiness.py` and
   `validation/master_v2/FINAL_VALIDATION.json`.

## Economic interpretation

A successful code test or SOL mainnet SELL simulation is NOT an observed
strategy edge. A market pool whose reserves remain unchanged after a second
slot does not show a trade. Multiple S1 entry sizes on the same pool are not
independent observations. Reading only surviving active pools introduces
survivorship bias. A token or wallet's public bank state does not authorize
trading from that wallet. Unqualified exits remain in denominator.

This study has:
- **0 independently verified new creator cycles** in this new cohort.
- **0 qualified actual BUY→SELL economic cycles**, so no net P&L estimate
  meeting the strict protocol.
- **No validated independent out-of-sample Master advantage**.
- `LIVE_READY_TO_ARM=false`, `ECONOMIC_EDGE_VALIDATED=false`,
  `LIVE_EXECUTION_VERIFIED=false`.

## Exact external data dependency

A source with historical **PoolCreateEvent** or signed
`initialize_v2` / `initialize_with_token2022` instructions **for all
creations, including unsuccessful or now-closed pools**, indexed by slot and
creator, plus point-in-time BUY/Sell prices, exact token quantities,
attempted failures, pool fee settings, slot timestamps, RPC or provider
quote latency, and transaction/network cost evidence.

Candidates for access verification (not guaranteed on the Free plan):
- **Helius Parsed Events / Parsed Streams** with server-side program
  instruction filtering. Verify coverage, historical retention, plan costs
  and authorization independently before upgrade.
- **Bitquery Solana Launchpad** `PoolCreateEvent` and trade/price
  history, with a supported API key and recorded source coverage.
No wallet private key or signing permission is required.

After obtaining it: freeze source universe and criteria, retain the entire
denominator, run development and temporal creator-disjoint holdout, require
>=50 independent verified validation creators, evaluate Master and reference
on identical available-at-decision tapes and exact sizes, reject unobserved
exits and unknown costs, and calculate net clustered uncertainty bounds.
Do not arm LIVE automatically, even if the economic experiment improves.

**No investment, fee payment or new subscription was authorized in this run.**
