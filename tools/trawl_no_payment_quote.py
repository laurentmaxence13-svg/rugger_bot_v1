"""CLI compatibility shim for the audited no-payment Trawl quote module."""
from bot.p3.trawl_no_payment_quote import main

if __name__=="__main__":
    raise SystemExit(main())
