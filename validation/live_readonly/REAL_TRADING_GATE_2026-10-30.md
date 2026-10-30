# Rugger Bot — real-trading GO / NO-GO evidence, 2026-10-30

**Decision: NO-GO for financial execution.** PAPER / read-only observation only.
This report distinguishes *demonstrated evidence* from pending requirements; it is
not a credential, transaction permission, strategy recommendation or profit claim.

## Verified

- Two independently indexed public LaunchLab \`migrate_to_cpswap\` signatures
  fetched from Solana mainnet public RPC as finalized, with exact compiled
  Solana message Ed25519 signature verification and canonical role/PDA graph:
  - \`59W98YE2XhgmVj2wXgpMFrGmypcyQL4iZMx9wJjGVBB3h3Db4cgjGAzGBrewNS6cB7YmLweat74CcnWZPhRgRXtR\`,
    slot 458935475, LaunchLab pool \`Fxj7t7JChDM5egFW5HWoUATHkosqnwhxUZVA4vCxXyoa\`,
    CPMM pool \`GkfmzPpzPiYM8kxXCfo88z8t9vqh1NECbFLG814SSLcx\`,
    mint \`7vtE5SpwBWhXgBrW7AjHikBatSvbYLdvD4qHuRMQkids\`.
  - \`mw3hepwWEb2z1ZnnQPuqisjojFTCuEoQ8BfYLEMtxauJZkxdTg8tL9Byr2CHenpRgyFxwafvM7PyRR7m3RaYQZh\`,
    slot 458932584, LaunchLab pool \`Dm4iEV2P3G4qsUNZq8tgHLwRyXmsJAZRhPrqtUZWAjoD\`,
    CPMM pool \`DeUJRynHqYre7qDvsv2X7ohH4nCm32xB8AHJ8hs4m4Ck\`,
    mint \`56RC8gxeW2m8gDWZz3MXGjF9DikgP6DTo1PyBox5rray\`.
  - Public primary-RPC proof: https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41036119453
- A separately queried real **classic SPL/WSOL CPMM pool** was observed
  at a finalized public mainnet bank:
  - pool \`DeUJRynHqYre7qDvsv2X7ohH4nCm32xB8AHJ8hs4m4Ck\`;
    bank slot \`463243101\`; WSOL effective reserve \`17,844,380,642\`
    lamports; base token effective reserve \`996,062,567,088,223\` atomic;
    trade fee \`2500\` ppm (0.25%); on-chain pool status 0.
  - The second migrated pool was intentionally **not** qualified as
    classic SPL/WSOL by the existing builder (\`1110\` account/program flags).
    Do not disable its token-program protection merely to pass validation.
  - Pool-bank proof: https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41037311698
- Financial send, signing, wallet loading and LIVE activation were not used.

## Unresolved trust boundaries and blockers

1. **Independent history:** the second pre-registered public provider returned
   null for all four requested historical transaction signatures. Cross-provider
   history verification therefore failed, not passed. A read-only archival
   mainnet RPC provider with these exact transaction signatures available is
   needed. Do not paste private RPC API keys in chat; store service secrets in
   GitHub Actions Secrets only after review.
2. **Wallet inventory:** the public \`getTokenLargestAccounts\` probe was blocked
   by HTTP 429 on the primary public RPC. No eligible system wallet/ATA and
   spendable public token position have been verified. An adequately
   provisioned *read-only* RPC or an independently verified public wallet+ATA
   candidate is required. No seed phrase or private key is needed for probing.
3. **Unsigned SELL:** no exact current bank + wallet ATA + fee receipt +
   unsigned \`simulateTransaction(sigVerify=false)\` has succeeded on mainnet.
   Existing \`tools/run_readonly_cpmm_preflight.py\` remains the required
   bounded strict path; no shortcuts to production execution.
4. **Code identity and operator pins:** program hashes agreed between two
   public RPCs during earlier observation, but this is neither an independent
   source build nor operator-approved deployment provenance. A separate
   review/approval of the actual on-chain code pins remains necessary.
5. **Economic edge:** Master vs baseline has no sufficient qualified
   real-market completed entry/exit cycles, out-of-sample evaluation or robust
   net-of-all-cost P&L evidence. Positive synthetic tests are not profit.
6. **Financial go-live:** require completed independent security/integration
   review, persistent journal restart/crash reconciliation, caps and kill
   switch, a separately isolated small wallet under user control, and explicit
   user authorization of the precise first real trial (amount, fees, risk,
   expiry). An unsigned preflight success would still not be a LIVE sign-off.

## Next read-only work

- Obtain historical getTransaction evidence from an actual archival second
  provider and compare the two verified signatures at exact slot/hash.
- Observe spendable public wallet token ATA at a coherent bank; select a
  strictly bounded *hypothetical*, unsent SELL amount.
- Supply reviewed program bytecode pin values and conduct the 18-call
  bounded unsigned CPMM SELL preflight; retain failed phases instead of
  suppressing failures.
- Collect enough real trades and follow-up sell states to compare policies
  without look-ahead, including network fees, pool fees, price impact,
  slippage, failed exits and capital reservations. Do not call any strategy
  profitable until empirical evidence warrants that statement.

**Safety:** \`LIVE_READY_TO_ARM=false\`, \`LIVE_EXECUTION_VERIFIED=false\`,
\`ECONOMIC_EDGE_VALIDATED=false\`. Do not place real orders automatically.


## Addendum — validated after Helius secret installation

The older unresolved provider/holder sections above describe **the initial
state before Helius was configured**; the observations below supersede those
specific archival lookup and public ATA access blockers. Financial GO remains
**NO-GO**.

1. **Two real migrations verified on two independent RPC providers.**
   Solana public RPC and Helius returned the same signatures, slots, LaunchLab
   and CPMM identities, canonical account graphs and exact Ed25519 compiled
   message digests. Independent cryptographic chain consensus or an audited
   program source build is still NOT proven.
   [Provider comparison](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41059267573)
2. **A public holder's token ATA and system wallet were found through Helius**,
   without importing any wallet secret or asserting user ownership.
   [Public ATA inspection](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41059267565).
3. **A strictly unsigned mainnet CPMM SELL simulation succeeded** on the
   classic SPL pool `DeUJRynHqYre7qDvsv2X7ohH4nCm32xB8AHJ8hs4m4Ck`:
   - bank and simulation slot: `463294996`;
   - hypothetical input: `100000000000` base-token atomic units;
   - expected output: `1785940` lamports; minimum output:
     `1768080` lamports;
   - estimated fee-inclusive shortfall to fee-free spot: 31 basis points
     (pool fee **plus** curve impact, not pure impact alone);
   - reported simulation compute units: `25895`;
   - capped network fee: `5000` lamports;
   - signed bytes: **none**; simulated signature bytes: **all zero**;
     RPC transport forbids transaction sending.
   - [Unsigned SELL simulation](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41060052471).

**Still required for LIVE:** Independent code/source/pin review;
current bank, executable route and owner-specific authorization; credible
prospectively observed BUY→SELL cycles with complete costs; rigorous
Master-vs-baseline out-of-sample and loss scenarios; operational crash/restart
reconciliation and independently approved bounded microtrade. The SELL
simulation is hypothetical and cannot establish profit or permission.

**Current flags:** `LIVE_READY_TO_ARM=false`,
`ECONOMIC_EDGE_VALIDATED=false`, `LIVE_EXECUTION_VERIFIED=false`.
