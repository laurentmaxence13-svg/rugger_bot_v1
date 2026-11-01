"""Rugger Bot local read-only PAPER terminal: streamlit run bot/dashboard/app.py"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import streamlit as st

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from bot.dashboard.evidence import load_local,load_uploaded,parse_documents,synthetic_demo


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
    import pandas as pd
    for arm in ("MASTER","RÉFÉRENCE"):
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
    sources=sorted({r["source"] for key in ("cycles","decisions","projections")
                    for r in data[key]})
    with st.expander("Filtres",expanded=False):
        selected=set(st.multiselect("Sources",sources,default=sources))
        arms=st.multiselect("Moteurs",["MASTER","RÉFÉRENCE"],
                            default=["MASTER","RÉFÉRENCE"])
    cycles=[r for r in data["cycles"] if r["source"] in selected
            and r["strategie"] in arms]
    decisions=[r for r in data["decisions"] if r["source"] in selected
               and r["strategie"] in arms]
    projections=[r for r in data["projections"] if r["source"] in selected]
    master=[r for r in cycles if r["strategie"]=="MASTER"]
    a,b,c,d=st.columns(4)
    a.metric("Capital PAPER initial de référence","10 SOL")
    b.metric("Cycles PAPER clos",len(cycles))
    c.metric("Scénarios S1/S2",len(projections))
    d.metric("P&L Master PAPER clos",money(
        round(sum(r["resultat_net_sol"] for r in master),9),True) if master else "—")
    st.caption("Plusieurs captures ne constituent pas nécessairement un seul portefeuille continu. Aucun solde total multi-session n'est inventé.")
    t1,t2,t3,t4=st.tabs(["Décisions du bot","Portefeuille / Trades PAPER",
                        "Scénarios memecoins","Sources / Qualification"])
    with t1:
        st.subheader("Décisions Master et référence")
        st.caption("Les décisions de marché sont gelées à S1. WAIT, REJECT et ENTER ne prouvent pas un ordre exécuté.")
        table([dict(Fichier=r["source"],Token=short(r["mint"]),Moteur=r["strategie"],
                    Décision=r["decision"],Slot=r.get("slot"),
                    Preuve=r["preuve"]) for r in reversed(decisions)],
              ["Fichier","Token","Moteur","Décision","Slot","Preuve"])
    with t2:
        st.subheader("Positions clôturées, issues exclusivement du ledger PAPER")
        st.caption("Les gains/pertes sont des simulations et ne doivent pas être confondus avec un rendement exécutable sur Solana.")
        table([dict(Fichier=r["source"],Token=short(r["mint"]),Moteur=r["strategie"],
                    Achat_SOL=r["entree_sol"],Vente_SOL=r["sortie_sol"],
                    Frais_SOL=r["frais_sol"],PnL_net_SOL=r["resultat_net_sol"],
                    Qualité=r["qualification"]) for r in cycles],
              ["Fichier","Token","Moteur","Achat_SOL","Vente_SOL",
               "Frais_SOL","PnL_net_SOL","Qualité"])
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


def main():
    st.set_page_config(page_title="Rugger Bot | PAPER Terminal",
                       page_icon="📊",layout="wide")
    st.title("RUGGER BOT · TERMINAL PAPER")
    st.caption("Interface locale, lecture seule · Solana LaunchLab · Master vs référence")
    with st.sidebar:
        st.header("Pilotage du terminal")
        demo=st.toggle("Démo entièrement fictive",value=False)
        folder=st.text_input("Dossier des preuves JSON","paper_artifacts",disabled=demo)
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
        data=parse_documents(local+imported)
        st.caption(f"{len(data['sources'])} source(s) reconnue(s) · "
                   f"{len(local)} fichier(s) local(aux) · "
                   f"{len(imported)} fichier(s) importé(s)")
        if not data["sources"]:
            st.info("Aucune preuve reconnue. Télécharge un artifact JSON/ZIP depuis GitHub Actions "
                    "puis importe-le ici, ou démarre le collecteur pour remplir paper_artifacts. "
                    "Le mode Démo permet de vérifier immédiatement les écrans.")
        render_data(data,False)
    render()


if __name__=="__main__":
    main()
