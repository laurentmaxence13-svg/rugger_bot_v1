# Rugger Bot — first preregistered CPMM S1/S2 economic probe

**Date:** 2026-10-30. **Financial status: NO-GO; PAPER/READ-ONLY only.**
No transaction was submitted, no inventory acquired or sold, no wallet
credential was used and no advantage of Master Trader was established.

## Fixed protocol

Source: preverified LaunchLab→CPMM migration, classic SPL/WSOL pair
\`DeUJRynHqYre7qDvsv2X7ohH4nCm32xB8AHJ8hs4m4Ck\`.
Program: \`CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C\`.
Three independently quoted but **not independent market trials**: fixed
\`0.01\`, \`0.05\`, \`0.10 SOL\` hypothetical entrance sizes.
After S1 is obtained, the runner emits a registration hash **before** the
12-second delay and S2 request. The later S2 quote never changes which pool
was selected or what S1 quantity was modeled.

RPC and paired evidence:
[First successful two-bank observation, GitHub Actions #41063227272](https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions/runs/41063227272).

- S1 slot: \`463301497\`, S2 slot: \`463301555\`.
- Preregistration hash: \`1a098753d9261ba345e5c8aceb4b6d2af16dce9276ce700c4d81c60ad845c632\`.
- S1 bank facts SHA256 = S2 bank facts SHA256:
  \`27d53bd6b9e28c0723e06e1b86e18510d8dea606a1c25e153ecf56a647421514\`.
- **No observed change in those CPMM bank facts.** Different slots alone
  do not show a market trade or measurable price movement.

| Hypothetical entry | S1 modeled token units | S2 modeled SOL return | Gross conditional markout | Conditional with assumed 10,000 lamports |
|---:|---:|---:|---:|---:|
| 0.01 SOL | 556,208,623,488 | 0.009929021 SOL | −70,979 lamports | −80,979 lamports |
| 0.05 SOL | 2,774,845,142,143 | 0.049424711 SOL | −575,289 lamports | −585,289 lamports |
| 0.10 SOL | 5,534,272,829,016 | 0.098303911 SOL | −1,696,089 lamports | −1,706,089 lamports |

The table demonstrates model friction under the observed bank values.
A hypothetical S1 purchase was **not injected** into the observed S2
reserves. The two independently calculated curves are thus a conditional
sensitivity, **not an executable same-market round trip**. The additional
10,000 lamports are an *assumption*, not a measured BUY+SELL network cost.
The estimates are not realized profit or loss. No future price/entry
recommendation follows from them.

## Evidentiary safety correction

The follow-up code distinguishes
\`UNCHANGED_BANK_FRICTION_ONLY\` from
\`DESCRIPTIVE_TWO_BANK_HYPOTHETICAL_MARKOUT\`. A later slot and a successful
test cannot count as an independent price transition when the bank facts are
identical. Even a changed bank remains one conditional observation and does
not establish a trade fill or economic edge.

## Conditions before P4 Master vs reference can be judged

- Independently gathered, prospectively registered observations of **many**
  actual LaunchLab candidates, not repeated quotes on one token.
- At-decision features for *both* engines, including creator, concentration,
  verified mint restrictions, liquidity, latency and missing-data vetoes.
- Each arm's exact BUY lot and sell-route availability at later times, quoted
  for that lot, including fees, slippage, price impact and failed routes.
- Genuine out-of-sample evaluation separated by creator and time; report
  skips, zero trades, unavailable exits and unliquidated inventory.
- The preexisting P4 frozen policy requires a validation target of at least
  50 independent creators. This first observation contributes **zero
  independent qualified economic cycles** to that threshold.
- Only once a robust net advantage is observed can a separately approved
  microtrade be considered, after operational security and risk sign-off.

**Flags:** \`MASTER_EDGE_VALIDATED=false\`, \`LIVE_READY_TO_ARM=false\`,
\`ACTUAL_BUY_SELL_EXECUTED=false\`.
