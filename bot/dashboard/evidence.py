"""Read-only normalization of Rugger Bot PAPER evidence for a local terminal.

Only supported, explicitly typed evidence may produce a trade row. LaunchLab
counterfactuals never become Master fills. No RPC, credentials, wallets or orders.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import re
import zipfile

LAMP=1_000_000_000
MAX_JSON_BYTES=4_000_000
MAX_ZIP_BYTES=16_000_000
MAX_FILES=300
LEDGER="rugger-dual-arm-live-like-paper-ledger-v1"
PROBE="rugger-real-sol-prospective-conditional-paper-cycle-v1"
SIGNED="rugger-signed-creator-asof-paired-paper-v1"
INTEGRATED="rugger-helius-signed-master-paper-integration-v1"
ENGINE="paper-engine-report-v1"

SUPPORTED={LEDGER,PROBE,SIGNED,INTEGRATED,ENGINE}
SAFE_NAME=re.compile(r"^[a-zA-Z0-9_./-]{1,220}$")


def _lamports(value):
    if type(value) is int:
        return value
    if type(value) is str and re.fullmatch(r"-?[0-9]{1,22}",value):
        return int(value)
    return None


def _sol(value):
    amount=_lamports(value)
    return round(amount/LAMP,9) if amount is not None else None


def _address(value):
    return value if type(value) is str and 1<=len(value)<=128 else "inconnu"


def _source(name):
    if type(name) is not str:
        return "source"
    return name[-220:] if SAFE_NAME.fullmatch(name) else "source"


def load_local(root,limit=MAX_FILES):
    """Recursively read bounded JSON, without symlinks or filesystem escapes."""
    root=Path(root)
    if not root.is_dir() or root.is_symlink():
        return []
    documents=[]
    for path in sorted(root.rglob("*.json"),key=lambda p:str(p),reverse=True):
        if len(documents)>=limit:
            break
        if path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_size>MAX_JSON_BYTES:
                continue
            with path.open("rb") as f:
                doc=json.load(f)
            if type(doc) is dict and doc.get("schema") in SUPPORTED:
                documents.append((str(path.relative_to(root)),doc))
        except (OSError,ValueError,UnicodeError,RecursionError):
            continue
    return documents


def load_uploaded(filename,content):
    """Read a downloaded GitHub Actions artifact ZIP or individual JSON in RAM."""
    if type(content) is not bytes or len(content)>MAX_ZIP_BYTES:
        raise ValueError("Fichier trop volumineux (16 Mo maximum).")
    if filename.lower().endswith(".json"):
        if len(content)>MAX_JSON_BYTES:
            raise ValueError("JSON trop volumineux.")
        doc=json.loads(content)
        return [(_source(filename),doc)] if type(doc) is dict and doc.get("schema") in SUPPORTED else []
    if not filename.lower().endswith(".zip"):
        raise ValueError("Importer un fichier .json ou .zip.")
    documents=[]
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        infos=bundle.infolist()
        if len(infos)>MAX_FILES:
            raise ValueError("Archive comportant trop de fichiers.")
        if sum(i.file_size for i in infos)>MAX_ZIP_BYTES:
            raise ValueError("Archive décompressée trop volumineuse.")
        for info in infos:
            if not info.filename.endswith(".json") or info.is_dir():
                continue
            if (info.file_size>MAX_JSON_BYTES or info.filename.startswith("/")
                    or ".." in Path(info.filename).parts
                    or not SAFE_NAME.fullmatch(info.filename)):
                continue
            try:
                doc=json.loads(bundle.read(info))
            except (ValueError,UnicodeError,RuntimeError):
                continue
            if type(doc) is dict and doc.get("schema") in SUPPORTED:
                documents.append((_source(filename+"/"+info.filename),doc))
    return documents


def parse_documents(documents):
    """Return normalized, explicitly labelled trades, decisions, projections."""
    out=dict(cycles=[],decisions=[],projections=[],sources=[],summary=[],positions=[],prices=[])
    seen=set()
    for original_name,doc in documents[:MAX_FILES]:
        if type(doc) is not dict:
            continue
        schema=doc.get("schema")
        if schema not in SUPPORTED:
            continue
        name=_source(original_name)
        # A refresh, repeat upload, or local+upload should not duplicate rows.
        key=(name,json.dumps(doc,sort_keys=True,ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        status=doc.get("status")
        if schema==PROBE and type(doc.get("paper_model_report")) is dict:
            status=doc["paper_model_report"].get("status",status)
        out["sources"].append(dict(fichier=name,schema=schema,
            statut=str(status or "SOURCE_VALIDEE"),
            trading_live="NON",donnees_verifiees="selon source"))
        if schema==LEDGER:
            _ledger(doc,name,out)
        elif schema==PROBE:
            _probe(doc,name,out)
        elif schema==SIGNED:
            _signed(doc,name,out)
        elif schema==INTEGRATED:
            _integrated(doc,name,out)
        elif schema==ENGINE:
            _engine_report(doc,name,out)
    return out


def _ledger(doc,name,out):
    accounts=doc.get("accounts")
    if type(accounts) is not dict:
        return
    for arm in ("master","reference"):
        state=accounts.get(arm,{})
        if type(state) is not dict:
            continue
        for item in state.get("closed_trades",[]):
            if type(item) is not dict or type(item.get("paper_only")) is not bool:
                continue
            net=_sol(item.get("net_pnl_lamports"))
            spend=_sol(item.get("gross_entry_spend_lamports"))
            exit_amount=_sol(item.get("market_exit_lamports"))
            fees_buy=_sol(item.get("entry_cost_lamports"))
            fees_sell=_sol(item.get("exit_cost_lamports"))
            if None in (net,spend,exit_amount,fees_buy,fees_sell):
                continue
            # This is a *modeled PAPER cycle*, not a live order or actual fill.
            out["cycles"].append(dict(
                source=name,strategie=arm.upper(),
                mint=_address(item.get("mint")),
                id=str(item.get("case_id","")),
                entree_sol=spend,sortie_sol=exit_amount,
                frais_sol=round(fees_buy+fees_sell,9),
                resultat_net_sol=net,
                qualification=("MODÈLE CONDITIONNEL" if item.get("model_conditioned_price")
                               else "QUOTE PAPER NON EXÉCUTÉE"),
                ordre_reel=False))
        for pos in state.get("open_inventory",[]):
            if type(pos) is not dict:
                continue
            out["decisions"].append(dict(source=name,
                mint=_address(pos.get("mint")),strategie=arm.upper(),
                decision="POSITION PAPER OUVERTE",
                slot=pos.get("entry_slot"),horodatage_ms=pos.get("entry_at_ms"),
                preuve="Position simulée; valorisation non vérifiée"))
            out["positions"].append(dict(source=name,mint=_address(pos.get("mint")),
                strategie=arm.upper(),capital_sol=_sol(pos.get("entry_spend_lamports")),
                entree_usd=None,entree_ms=pos.get("entry_at_ms"),
                statut="POSITION PAPER OUVERTE — LOT NON VALORISÉ"))
    for event in doc.get("events",[]):
        if type(event) is not dict or event.get("type")!="PRECOMMITTED_DECISION":
            continue
        decisions=event.get("decisions")
        if type(decisions) is not dict:
            continue
        for arm in ("master","reference"):
            if decisions.get(arm) in ("ENTER","WAIT","REJECT"):
                out["decisions"].append(dict(
                    source=name,mint=str(event.get("case_id","")),
                    strategie=arm.upper(),decision=decisions[arm],
                    slot=None,horodatage_ms=event.get("at_ms"),
                    preuve="Décision gelée avant cotation; PAPER seulement"))
    out["summary"].append(dict(source=name,
        information="P&L comparatif Master/référence",
        valeur=("Indisponible" if doc.get("policy_paired_model_net_edge_lamports") is None
                else str(_sol(doc["policy_paired_model_net_edge_lamports"]))+" SOL (PAPER)")))


def _probe(doc,name,out):
    # The network runner wraps the actual probe report in paper_model_report.
    # Reading only the top level would silently hide every real S1/S2 sample.
    report=doc.get("paper_model_report",doc)
    if type(report) is not dict:
        return
    cases=report.get("cases",[])
    if type(cases) is not list:
        return
    for c in cases:
        if type(c) is not dict:
            continue
        mint=_address(c.get("mint"))
        for arm,field in (("MASTER","actual_Master_action"),
                          ("RÉFÉRENCE","actual_reference_action")):
            action=c.get(field)
            if action not in ("WAIT","NO_TRADE","ENTER","SELL"):
                continue
            out["decisions"].append(dict(source=name,mint=mint,
                strategie=arm,decision=action,slot=c.get("S1_slot"),
                horodatage_ms=None,
                preuve="Scoreur réel à S1; opération non exécutée"))
        entry=_sol(c.get("hypothetical_probe_size_lamports"))
        overlay=_sol(c.get("own_buy_overlay_sell_lamports"))
        plain=_sol(c.get("conditional_S2_sell_lamports"))
        if entry is None or not entry>0:
            continue
        if overlay is not None:
            out["projections"].append(dict(source=name,mint=mint,
                pool=_address(c.get("pool")),
                type="Contrefactuel intégrant achat propre",
                entree_hypothetique_sol=entry,
                sortie_modele_sol=overlay,
                variation_brute_sol=round(overlay-entry,9),
                pnl_master_reel=None,
                statut="HYPOTHÈSE, JAMAIS UN TRADE",
                base_provenance="S1/S2 Helius, scénario dépendant du chemin"))
        elif plain is not None:
            out["projections"].append(dict(source=name,mint=mint,
                pool=_address(c.get("pool")),
                type="Projection sur réserve S2 observée",
                entree_hypothetique_sol=entry,
                sortie_modele_sol=plain,
                variation_brute_sol=round(plain-entry,9),
                pnl_master_reel=None,
                statut="HYPOTHÈSE, JAMAIS UN TRADE",
                base_provenance="Banque S2 sans l'achat hypothétique"))


def _signed(doc,name,out):
    observations=doc.get("observations",[])
    if type(observations) is not list:
        return
    for row in observations:
        if type(row) is not dict:
            continue
        mint=_address(row.get("mint"))
        frozen=row.get("frozen_decision_before_S2")
        if type(frozen) is not dict:
            continue
        for arm,field in (("MASTER","master_action"),
                          ("RÉFÉRENCE","reference_action")):
            action=frozen.get(field)
            if action not in ("WAIT","NO_TRADE","WAIT_FOR_FEATURES","ENTER"):
                continue
            out["decisions"].append(dict(
                source=name,mint=mint,strategie=arm,decision=action,
                slot=frozen.get("source_slot"),horodatage_ms=frozen.get("at_ms"),
                preuve="Création signée et S1; signaux complets requis"))
        delta=_sol(row.get("s1_to_s2_conditional_curve_markout_lamports"))
        sell=_sol(row.get("s2_same_exact_qty_conditional_sell_lamports"))
        if delta is not None and sell is not None:
            out["projections"].append(dict(source=name,mint=mint,
                pool=_address(row.get("pool")),
                type="Projection courbe S1/S2",
                entree_hypothetique_sol=round(sell-delta,9),
                sortie_modele_sol=sell,variation_brute_sol=delta,
                pnl_master_reel=None,statut="HYPOTHÈSE, JAMAIS UN TRADE",
                base_provenance="Aucune sortie réellement simulée par le Master"))


def _integrated(doc,name,out):
    for field,label in (
        ("log_events_retained","Évènements capturés"),
        ("signed_creators_claimed","Créateurs signés détectés"),
        ("supported_native_SOL_graphs","Graphes SOL qualifiés"),
        ("actual_signed_policy_frozen_paper_cases","Décisions PAPER gelées"),
        ("paper_portfolio_closed_positions","Positions PAPER fermées")):
        val=doc.get(field)
        if type(val) is int:
            out["summary"].append(dict(source=name,
                information=label,valeur=str(val)))


def _engine_report(doc,name,out):
    # Existing bot.analyser.paper_engine writes this into data/, not paper_artifacts.
    if doc.get("paper_only") is not True or doc.get("real_orders_enabled") is not False:
        return
    for field,label in (
        ("launches_observed","Lancements observés"),
        ("quotes_recorded","Cotations USD enregistrées"),
        ("decision_count","Décisions du moteur PAPER"),
        ("open_paper_positions","Positions PAPER ouvertes"),
        ("closed_paper_positions","Positions PAPER clôturées")):
        val=doc.get(field)
        if type(val) is int:
            out["summary"].append(dict(source=name,information=label,valeur=str(val)))
    complete=doc.get("performance_data_complete") is True
    pnl=doc.get("pnl_sol")
    # Legacy report may use conversion USD -> SOL at constant FX. Even a
    # mathematically reconciled report is not source-native Master profitability.
    if complete and type(pnl) in (int,float) and -1e30<float(pnl)<1e30:
        out["summary"].append(dict(source=name,
            information="P&L PAPER legacy (conversion USD/SOL non vérifiée)",
            valeur=f"{pnl:.9f} SOL (approximation, jamais Master)"))


def synthetic_demo():
    """Opt-in offline UI demonstration, deliberately unlike market evidence."""
    return dict(
        cycles=[
            dict(source="DÉMO SYNTHÉTIQUE",strategie="MASTER",mint="TOKEN_EXEMPLE_A",
                id="DEMO-A",entree_sol=0.05,sortie_sol=0.057,
                frais_sol=0.000015,resultat_net_sol=0.006985,
                qualification="EXEMPLE FABRIQUÉ",ordre_reel=False),
            dict(source="DÉMO SYNTHÉTIQUE",strategie="RÉFÉRENCE",mint="TOKEN_EXEMPLE_B",
                id="DEMO-B",entree_sol=0.05,sortie_sol=0.047,
                frais_sol=0.000015,resultat_net_sol=-0.003015,
                qualification="EXEMPLE FABRIQUÉ",ordre_reel=False)],
        decisions=[dict(source="DÉMO SYNTHÉTIQUE",mint="TOKEN_EXEMPLE_C",
            strategie="MASTER",decision="WAIT",slot=None,horodatage_ms=None,
            preuve="Exemple fictif; pas de décision Helius")],
        projections=[],prices=[],positions=[],sources=[dict(fichier="DÉMO SYNTHÉTIQUE",
            schema="exemple",statut="100 % fictif",
            trading_live="NON",donnees_verifiees="NON")],summary=[])
