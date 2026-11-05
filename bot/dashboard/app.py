"""Rugger Bot local read-only PAPER terminal: streamlit run bot/dashboard/app.py"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import streamlit as st

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from bot.dashboard.evidence import _source,load_local,load_uploaded,parse_documents,synthetic_demo
from bot.dashboard.local_db import read_paper_db
from bot.dashboard.research_view import (EMPTY_SECTIONS,BundleRefused,committed_bundles,cycle_rows,
                                         decision_rows,load_results_registry,markdown_escape,
                                         pool_rows,summary,verify_bundle)


def money(x,sign=False):
    return "—" if x is None else f"{x:+.9f} SOL" if sign else f"{x:.9f} SOL"


def short(value):
    return value[:9]+"…"+value[-6:] if isinstance(value,str) and len(value)>22 else value


def table(rows,columns):
    if not rows:
        st.info("Aucune donnée admissible pour cette section.")
        return
    import pandas as pd
    df=pd.DataFrame(rows)
    st.dataframe(df[[c for c in columns if c in df]],use_container_width=True,hide_index=True)


def charts(cycles):
    # Never import compiled chart dependencies when there are no PAPER cycles.
    if not cycles:
        return
    import pandas as pd
    for arm in sorted({r["strategie"] for r in cycles}):
        rows=[r for r in cycles if r["strategie"]==arm]
        if rows:
            values=[0.0]
            for row in rows:
                values.append(round(values[-1]+row["resultat_net_sol"],9))
            st.caption("P&L PAPER cumulé — "+arm+" (cycles clos; pas une courbe de cours)")
            st.line_chart(pd.DataFrame({"cycle":range(len(values)),
                                        "pnl_sol":values}).set_index("cycle"),height=175)


def render_data(data,demo):
    if demo:
        st.error("DÉMONSTRATION SYNTHÉTIQUE — toutes les opérations présentées sont inventées.")
    else:
        st.warning("PAPER ONLY — aucune opération financière réelle. Les scénarios S1/S2 ne sont pas des trades du Master.")
    sources=sorted({r["source"] for key in ("cycles","decisions","projections","positions","prices")
                    for r in data.get(key,[])})
    with st.expander("Filtres",expanded=False):
        selected=set(st.multiselect("Sources",sources,default=sources))
        options=["MASTER","RÉFÉRENCE","PAPER_ENGINE","SHADOW_BASELINE"]
        arms=st.multiselect("Moteurs",options,default=options)
    cycles=[r for r in data["cycles"] if r["source"] in selected
            and r["strategie"] in arms]
    decisions=[r for r in data["decisions"] if r["source"] in selected
               and r["strategie"] in arms]
    projections=[r for r in data["projections"] if r["source"] in selected]
    positions=[r for r in data.get("positions",[]) if r["source"] in selected
               and r["strategie"] in arms]
    prices=[r for r in data.get("prices",[]) if r["source"] in selected]
    master=[r for r in cycles if r["strategie"]=="MASTER"]
    a,b,c,d=st.columns(4)
    a.metric("Capital PAPER initial de référence","10 SOL")
    b.metric("Cycles PAPER clos",len(cycles))
    c.metric("Scénarios S1/S2",len(projections))
    d.metric("P&L Master PAPER clos",money(
        round(sum(r["resultat_net_sol"] for r in master),9),True) if master else "—")
    st.caption("Plusieurs captures ne constituent pas nécessairement un seul portefeuille continu. Aucun solde total multi-session n'est inventé.")
    t1,t2,t3,t4,t5=st.tabs(["Décisions du bot","Portefeuille / Trades PAPER",
                        "Scénarios S1/S2","Prix USD observés","Sources / Qualification"])
    with t1:
        st.subheader("Décisions du bot : Master, référence et moteur PAPER local")
        st.caption("Les décisions de marché sont gelées à S1. WAIT, REJECT et ENTER ne prouvent pas un ordre exécuté.")
        table([dict(Fichier=r["source"],Token=short(r["mint"]),Moteur=r["strategie"],
                    Décision=r["decision"],Slot=r.get("slot"),
                    Preuve=r["preuve"]) for r in reversed(decisions)],
              ["Fichier","Token","Moteur","Décision","Slot","Preuve"])
    with t2:
        st.subheader("Positions closes du registre PAPER / moteur local")
        st.caption("Les gains/pertes sont des simulations et ne doivent pas être confondus avec un rendement exécutable sur Solana.")
        table([dict(Fichier=r["source"],Token=short(r["mint"]),Moteur=r["strategie"],
                    Achat_SOL=r["entree_sol"],Vente_SOL=r["sortie_sol"],
                    Frais_SOL=r["frais_sol"],PnL_net_SOL=r["resultat_net_sol"],
                    Qualité=r["qualification"]) for r in cycles],
              ["Fichier","Token","Moteur","Achat_SOL","Vente_SOL",
               "Frais_SOL","PnL_net_SOL","Qualité"])
        st.subheader("Positions PAPER ouvertes (base locale)")
        table([dict(Token=short(r["mint"]),Moteur=r["strategie"],
                    Mise_SOL=r["capital_sol"],Prix_entree_USD=r["entree_usd"],
                    Statut=r["statut"]) for r in positions],
              ["Token","Moteur","Mise_SOL","Prix_entree_USD","Statut"])
        charts(cycles)
    with t3:
        st.subheader("Hypothèses S1–S2, jamais des ordres")
        if projections:
            idx=st.selectbox("Token observé",range(len(projections)),
                format_func=lambda i:short(projections[i]["mint"])+" · "+projections[i]["source"])
            row=projections[idx]
            st.write("Mint :",row["mint"])
            st.write("Modèle :",row["type"])
            s1,s2,delta=st.columns(3)
            s1.metric("Achat fictif",money(row["entree_hypothetique_sol"]))
            s2.metric("Sortie modélisée",money(row["sortie_modele_sol"]))
            delta.metric("Variation brute théorique",money(row["variation_brute_sol"],True))
            import pandas as pd
            st.caption("Valeur d'un lot fictif entre S1 et S2; ce graphique n'est pas un cours de marché.")
            points=pd.DataFrame([dict(étape="S1",lot_SOL=row["entree_hypothetique_sol"]),
                                 dict(étape="S2",lot_SOL=row["sortie_modele_sol"])])
            st.line_chart(points.set_index("étape"),height=250)
            st.warning("Aucun trade Master ni gain net vérifié sur la base de cette projection. Frais externes et exécution inconnus.")
        else:
            st.info("Aucune projection S1/S2 admissible dans les preuves sélectionnées.")
    with t4:
        st.subheader("Prix USD réellement observés par le moteur PAPER local")
        st.caption("Points sauvegardés par le scanner papier (source du rapport local). Ce ne sont pas des prix exécutables. Pas de bougies inventées.")
        mints=sorted({r["mint"] for r in prices})
        if mints:
            mint=st.selectbox("Token (mint)",mints,key="price_mint")
            rows=sorted((r for r in prices if r["mint"]==mint),
                        key=lambda r:r["utc_timestamp"])
            import pandas as pd
            df=pd.DataFrame(rows)
            df["Date UTC"]=pd.to_datetime(df["utc_timestamp"],unit="s",utc=True)
            st.line_chart(df.set_index("Date UTC"),y="prix_usd",height=320)
            st.caption(f"{len(rows)} point(s) locaux ; source DexScreener ou fournisseur indiqué par le moteur, non vérifiée comme exécutable.")
        else:
            st.info("Pas encore de points de prix. Démarrer START_PAPER_ENGINE.bat et le scanner pour alimenter data/rugger_bot.db, ou importer une capture Helius S1/S2.")
    with t5:
        st.subheader("Provenance et données disponibles")
        table(data["sources"],["fichier","schema","statut","trading_live","donnees_verifiees"])
        table(data["summary"],["source","information","valeur"])
        st.markdown(
            "Chaque source conserve son propre contexte. Un cycle PAPER provient uniquement "
            "du ledger; une hypothèse de prix reste un scénario séparé. "
            "Sans cycle Master, le P&L Master est indisponible et non égal à zéro."
        )
        st.download_button("Exporter la vue courante JSON",
            data=json.dumps(dict(cycles=cycles,decisions=decisions,
                                 projections=projections),ensure_ascii=False,indent=2),
            file_name="rugger-paper-vue.json",mime="application/json")


LINKS={"axiom":"Axiom","solscan_token":"Solscan (token)","raydium":"Raydium",
       "solscan_pool":"Solscan (pool)","dexscreener":"DexScreener","transaction":"Solscan (tx)",
       "entry_transaction":"Solscan (tx)","exit_transaction":"Solscan (tx)"}


def link_table(rows,columns,empty):
    if not rows:
        st.info(empty)
        return
    import pandas as pd
    df=pd.DataFrame(rows)
    config={c:st.column_config.LinkColumn(c,display_text=text) for c,text in LINKS.items() if c in df}
    st.dataframe(df[[c for c in columns if c in df]],use_container_width=True,hide_index=True,
                 column_config=config)


def render_bundle(document,verification):
    s=summary(document,verification)
    st.markdown("### "+markdown_escape(verification["name"]))
    st.info(f"Étiquette : **{s['label']}**. Rejeu de recherche sur des données on-chain archivées : "
            "pas un trade du Master, non compté dans le seuil de 50 cycles et 20 créateurs, aucun ordre.")
    if s["label_reasons"]:
        st.warning("SYNTHETIC : "+" ; ".join(markdown_escape(r) for r in s["label_reasons"])+".")
    hashes=(f"fichier `{verification['file_sha256']}`, bundle `{verification['bundle_sha256']}`")
    if verification["status"]=="VERIFIED_AGAINST_RESULTS_REGISTRY":
        st.success(f"sha256 vérifié à l'affichage contre le registre RESULTS.json "
                   f"(VERIFIED_AGAINST_RESULTS_REGISTRY, variante "
                   f"{markdown_escape(verification['registry_variant'])}) : {hashes}")
    else:
        st.warning(f"Bundle cohérent avec lui-même mais absent du registre RESULTS.json "
                   f"(SELF_CONSISTENT_NOT_IN_REGISTRY) : {hashes}. Personne d'autre ne l'a enregistré.")
    a,b,c,d=st.columns(4)
    a.metric("Pools",s["pools"])
    b.metric("Décisions journalisées",s["decisions"])
    c.metric("ENTER (recherche)",s["entries"])
    d.metric("Cycles clos",s["closed_cycles"])
    if s["marked_positions"]:
        st.caption(f"Positions valorisées à la marque, jamais vendues : {s['marked_positions']} "
                   "(hors cycles clos et hors P&L).")
    st.caption("Horloge de source vérifiée : "+str(s["source_clock_verified"])+
               " · SOL/USD vérifié : "+str(s["sol_usd_verified"])+
               " · Statut de preuve : "+str(s["research_evidence_status"]))
    t1,t2,t3=st.tabs(["Pools","Décisions","Cycles BUY→SELL"])
    with t1:
        link_table(pool_rows(document),
                   ["label","pool","mint","signed_creator_verified","signed_creator_reason","trades",
                    "decisions","enter_master","enter_reference","closed_cycles",
                    "main_blocking_reasons","axiom","solscan_token","raydium","solscan_pool",
                    "dexscreener"],"Aucun pool.")
    with t2:
        rows=decision_rows(document)
        pools=sorted({r["pool"] for r in rows})
        arms=sorted({r["arm"] for r in rows})
        key=verification["bundle_sha256"][:12]
        pool=st.selectbox("Pool",["Tous"]+pools,key="pool_"+key)
        arm=st.selectbox("Bras",["Tous"]+arms,key="arm_"+key)
        rows=[r for r in rows if pool in ("Tous",r["pool"]) and arm in ("Tous",r["arm"])]
        link_table(rows,["label","index","arm","block_time","slot","transaction_index","action",
                         "blocking_reasons","score","sol_usd","sol_usd_source","sol_usd_age_ms",
                         "transaction"],"Aucune décision.")
    with t3:
        link_table(cycle_rows(document),
                   ["label","arm","outcome","entry_time","entry_slot","entry_transaction",
                    "exit_time","exit_slot","exit_transaction","exit_trigger","buy_sol","sell_sol",
                    "fees_sol","failed_attempt_fees_modelled","pnl_sol","mark_pnl_sol"],
                   "Aucun cycle de recherche : le P&L en SOL reste vide (il n'est pas égal à zéro).")


def render_research():
    st.subheader("Recherche et simulations historiques")
    st.caption("Étiquettes : HISTORICAL_REPLAY, PROSPECTIVE_PAPER, SYNTHETIC, REAL. "
               "Les liens externes s'ouvrent dans le navigateur ; ce tableau de bord ne les appelle jamais.")
    loaded,refused,registry=[],[],{}
    try:
        registry=load_results_registry(ROOT)
        loaded,refused=committed_bundles(ROOT)
    except BundleRefused as exc:
        refused.append(dict(name="validation/historical_replay_l1/RESULTS.json",reason=str(exc)))
    uploads=st.file_uploader("Importer un bundle de rejeu (JSON)",type=["json"],
                             accept_multiple_files=True,key="research_upload")
    for uploaded in uploads or []:
        try:
            loaded.append(verify_bundle(uploaded.getvalue(),registry=registry,
                                        name=_source(uploaded.name)))
        except BundleRefused as exc:
            refused.append(dict(name=_source(uploaded.name),reason=str(exc)))
    for row in refused:
        st.error(f"Bundle refusé ({markdown_escape(row['name'])}) : {markdown_escape(row['reason'])}. "
                 "Rien n'en est affiché.")
    if not loaded:
        st.info("Aucun bundle de rejeu vérifié.")
    for document,verification in loaded:
        render_bundle(document,verification)
    st.markdown("### PROSPECTIVE_PAPER")
    st.info(EMPTY_SECTIONS["PROSPECTIVE_PAPER"])
    st.markdown("### REAL")
    st.info(EMPTY_SECTIONS["REAL"])


def main():
    st.set_page_config(page_title="Rugger Bot | PAPER Terminal",
                       page_icon="📊",layout="wide")
    st.title("RUGGER BOT · TERMINAL PAPER")
    st.caption("Interface locale, lecture seule · Solana LaunchLab · Master vs référence")
    with st.sidebar:
        st.header("Pilotage du terminal")
        demo=st.toggle("Démo entièrement fictive",value=False)
        folder=st.text_input("Dossier des preuves JSON","paper_artifacts",disabled=demo)
        db=st.text_input("Base PAPER locale (lecture seule)","data/rugger_bot.db",disabled=demo)
        uploads=st.file_uploader("Importer ZIP GitHub Actions ou JSON",
            type=["json","zip"],accept_multiple_files=True,disabled=demo)
        autorefresh=st.toggle("Recharger les preuves toutes les 10 s",
                              value=False,disabled=demo)
        if st.button("Actualiser maintenant",use_container_width=True):
            st.rerun()
        st.link_button("Voir GitHub Actions",
            "https://github.com/laurentmaxence13-svg/rugger_bot_v1/actions",
            use_container_width=True)
        st.caption("Aucune clé privée ni API Helius requise par le terminal.")

    @st.fragment(run_every="10s" if autorefresh and not demo else None)
    def render():
        if demo:
            render_data(synthetic_demo(),True)
            return
        path=Path(folder).expanduser()
        if not path.is_absolute():
            path=ROOT/path
        local=load_local(path)
        imported=[]
        for uploaded in uploads or []:
            try:
                imported.extend(load_uploaded(uploaded.name,uploaded.getvalue()))
            except (ValueError,RuntimeError) as exc:
                st.error(f"Impossible d'importer {uploaded.name}: {exc}")
        legacy=load_local(ROOT/"data")
        data=parse_documents(local+legacy+imported)
        db_path=Path(db).expanduser()
        if not db_path.is_absolute():
            db_path=ROOT/db_path
        try:
            view=read_paper_db(db_path)
            for key,items in view.items():
                data[key].extend(items)
        except Exception as exc:
            st.warning("Base locale non lisible en lecture seule : "+type(exc).__name__)
        st.caption(f"{len(data['sources'])} source(s) reconnue(s) · "
                   f"{len(local)} fichier(s) local(aux) · "
                   f"{len(imported)} fichier(s) importé(s)")
        if not data["sources"]:
            st.info("Aucune preuve reconnue. Télécharge un artifact JSON/ZIP depuis GitHub Actions "
                    "puis importe-le ici, ou démarre le collecteur pour remplir paper_artifacts. "
                    "Le mode Démo permet de vérifier immédiatement les écrans.")
        render_data(data,False)
    terminal,research=st.tabs(["Terminal PAPER","Recherche et rejeux historiques"])
    with terminal:
        render()
    with research:
        render_research()


if __name__=="__main__":
    main()
