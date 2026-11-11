"""t22pol: Token-2022 extension policy and census (offline, descriptive).

The decision itself is the FROZEN reader ``bot.p3.token2022.decode_mint`` (mint extensions 18 and
19 only) plus the FROZEN safety rule (no mint authority, no freeze authority). This package names
every extension present, explains each refusal and checks that its table agrees with the frozen
reader; it never widens what the frozen code accepts.
"""
VERSION = '0.1'
