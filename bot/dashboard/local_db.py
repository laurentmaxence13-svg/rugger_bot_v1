"""Safe, strictly read-only view of the EXISTING local Rugger PAPER SQLite DB.

Unlike Helius signed-S1 research, the legacy paper_engine uses USD prices and
a separate local simulation. It is never relabelled as a Master-policy fill.
No database initialization, schema migration, or network activity is allowed.
"""
from __future__ import annotations

from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote

MAX_DECISIONS=350
MAX_TRADES=350
MAX_PRICES=2500


def _finite(value):
    return (type(value) in (int,float) and math.isfinite(value))


def _table(con,name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (name,)).fetchone() is not None


def read_paper_db(path):
    """Snapshot from existing DB; missing file or schema gives empty results."""
    result=dict(cycles=[],decisions=[],positions=[],prices=[],summary=[],sources=[])
    source=Path(path)
    if (not source.is_file() or source.is_symlink()
            or source.suffix.lower() not in (".db",".sqlite",".sqlite3")):
        return result
    uri="file:"+quote(source.resolve().as_posix(),safe="/:")+"?mode=ro"
    # SQLite allows concurrent reads while the existing PAPER engine writes.
    # closing(): sqlite3's own context manager commits but never closes, which
    # keeps the PAPER DB file open on Windows until garbage collection.
    with closing(sqlite3.connect(uri,uri=True,timeout=1)) as con:
        con.execute("PRAGMA query_only=ON")
        name=str(source.name)
        result["sources"].append(dict(fichier=name,
            schema="local_sqlite_paper_engine_read_only",
            statut="Fichier local observé",trading_live="NON",
            donnees_verifiees="PAPER legacy, USD non-exécutable"))
        if _table(con,"paper_portfolio"):
            row=con.execute("SELECT initial_capital_sol,realized_capital_sol "
                            "FROM paper_portfolio WHERE id=1").fetchone()
            if row:
                for title,value in (("Capital PAPER initial du moteur",row[0]),
                                    ("Capital PAPER réalisé du moteur",row[1])):
                    if _finite(value):
                        result["summary"].append(dict(source=name,
                            information=title,valeur=f"{value:.9f} SOL (PAPER)"))
        if _table(con,"paper_decisions"):
            for mint,mode,enter,allowed,decision_at,score,reasons in con.execute(
                "SELECT mint,strategy_mode,enter,entry_allowed,decision_time,"
                "score,reasons_json FROM paper_decisions ORDER BY id DESC "
                "LIMIT ?",(MAX_DECISIONS,)):
                action=("WAIT" if not enter else "ENTER" if allowed else "REJECT")
                reason=""
                try:
                    flags=json.loads(reasons or "[]")
                    if type(flags) is list:
                        reason="; ".join(str(x)[:60] for x in flags[:4])
                except (ValueError,TypeError):
                    pass
                result["decisions"].append(dict(source=name,mint=mint or "inconnu",
                    strategie="PAPER_ENGINE" if mode!="shadow_baseline" else "SHADOW_BASELINE",
                    decision=action,slot=None,
                    horodatage_ms=decision_at*1000 if type(decision_at) is int else None,
                    preuve="Scoreur PAPER legacy; "+reason))
        if _table(con,"paper_trades"):
            for row in con.execute(
                "SELECT mint,creator,entry_time,exit_time,status,strategy_mode,"
                "position_sol,pnl_sol,entry_price,exit_price,exit_reason "
                "FROM paper_trades ORDER BY entry_time DESC LIMIT ?",
                (MAX_TRADES,)):
                (mint,creator,entry,exit_at,status,mode,
                 position,pnl,entry_usd,exit_usd,reason)=row
                arm="SHADOW_BASELINE" if mode=="shadow_baseline" else "PAPER_ENGINE"
                if status=="open":
                    result["positions"].append(dict(source=name,
                        mint=mint,strategie=arm,capital_sol=position if _finite(position) else None,
                        entree_usd=entry_usd if _finite(entry_usd) else None,
                        entree_ms=entry*1000 if type(entry) is int else None,
                        statut="POSITION SIMULÉE OUVERTE"))
                elif status=="closed" and _finite(position) and _finite(pnl):
                    result["cycles"].append(dict(source=name,strategie=arm,mint=mint,
                        id=mint,entree_sol=round(position,9),
                        sortie_sol=None,frais_sol=None,
                        resultat_net_sol=round(pnl,9),
                        qualification="PAPER LEGACY : PRIX USD / CONVERSION SOL NON VÉRIFIÉE",
                        ordre_reel=False))
        if _table(con,"paper_prices"):
            for mint,at,price,pair,liquidity in con.execute(
                "SELECT mint,timestamp,price_usd,pair_address,liquidity_usd "
                "FROM paper_prices ORDER BY timestamp DESC LIMIT ?",(MAX_PRICES,)):
                if (_finite(price) and price>0 and type(at) is int):
                    result["prices"].append(dict(
                        source=name,mint=mint,utc_timestamp=at,
                        prix_usd=price,
                        liquidite_usd=liquidity if _finite(liquidity) else None,
                        paire=pair))
    return result
