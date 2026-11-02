"""Rugger Render public-market PAPER endpoint; no wallet or live-trade API.

Separate roles: actual Master decisions stay research/WAIT on unverified
DexScreener observations; bounded experimental PAPER engine operates on live
indicative prices. Render Free suspends inactive web services and storage is
ephemeral: this is not 24/7, nor an economic profitability demonstration.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit

from bot.ops.render_paper_engine import PaperState, run_public_worker
from bot.ops.render_readonly_service import Observer as SignedHeliusObserver

os.environ["RUGGER_NO_DOTENV"]="1"
os.environ["RUGGER_LIVE_ENABLED"]="0"
STORE=PaperState()
# This observer reads signed LaunchLab evidence only. It never signs or trades.
# It is OFF unless explicitly enabled and supplied a Helius key via Render secrets.
SIGNED_SOURCE=SignedHeliusObserver()
STOP=threading.Event()

PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rugger Master · PAPER observation</title>
<style>
:root{color-scheme:dark;font-family:system-ui,Arial,sans-serif;background:#080c16;color:#e7edf7}
*{box-sizing:border-box}body{margin:0;padding:22px;max-width:1200px;margin-inline:auto}
h1{font-size:27px;margin:0}h2{font-size:16px;margin:0 0 15px}
header{display:flex;justify-content:space-between;gap:15px;align-items:center;padding:8px 0 27px}
.note{color:#93a1bd;font-size:13px;line-height:1.6}main{display:grid;gap:16px}
.cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.card{background:#111827;border:1px solid #263249;border-radius:14px;padding:19px;overflow:auto}
.metric{font-size:28px;font-weight:750;padding-top:8px}
small{color:#aab8cd}.positive{color:#29d6a0}.negative{color:#fb7d8b}
.pill{border-radius:25px;background:#182b3b;color:#8bc7ed;font-size:12px;padding:8px 12px}
table{width:100%;border-collapse:collapse;font-size:13px;min-width:550px}
td,th{border-bottom:1px solid #263249;padding:11px 8px;text-align:left;vertical-align:top}
th{color:#95a7c4;font-weight:500}
button{background:#293d60;border:1px solid #456393;padding:10px 14px;border-radius:8px;color:#fff;cursor:pointer}
a{color:#8bbcff}.warn{border-left:3px solid #f4bc59;padding-left:12px;color:#dbb978}
@media(max-width:730px){.cols{grid-template-columns:1fr}body{padding:13px}header{display:block}}
</style></head><body>
<header><div><h1>Rugger Master <span style="color:#22c6aa">/ PAPER</span></h1>
<div class="note">Observation du marché Solana · Master original en lecture seule · Stratégie PAPER expérimentale séparée</div></div>
<span class="pill" id="health">Chargement…</span></header>
<main><section class="cols">
<div class="card"><small>Capital virtuel estimé</small><div class="metric" id="total">—</div><div class="note">Valorisation théorique, non exécutable</div></div>
<div class="card"><small>Cash virtuel disponible</small><div class="metric" id="cash">—</div><div class="note">Capital initial : 10 SOL</div></div>
<div class="card"><small>Trades PAPER clôturés</small><div class="metric" id="closed">—</div><div class="note" id="realized">Résultat simulé</div></div>
</section>
<section class="card"><h2>Décisions du véritable Master</h2><p class="note warn">Les données DexScreener ne valident pas les créateurs, la liquidité exécutable ou les frais : le Master doit refuser toute entrée non qualifiée. Aucun trade PAPER expérimental n'est attribué au Master.</p>
<div style="overflow:auto"><table><thead><tr><th>Token</th><th>Décision</th><th>Pourquoi</th></tr></thead><tbody id="master"><tr><td colspan="3">En attente d'observations</td></tr></tbody></table></div></section>
<section class="card"><h2>Créations LaunchLab vérifiées · Helius</h2>
<div class="note warn">Observateur de signatures publiques, distinct des profils promotionnels DexScreener. Désactivé sans activation explicite et clé Helius côté serveur. Les captures ne constituent ni des entrées du Master, ni des transactions PAPER.</div>
<div class="metric" style="font-size:19px" id="helius-state">État : chargement…</div>
<div class="note" id="helius-counts">Aucune preuve récupérée pour le moment.</div>
<div class="note"><a href="/api/helius">Statut Helius vérifiable (JSON)</a></div></section>
<section class="card"><h2>Positions du moteur PAPER expérimental</h2>
<div class="note">Entrées de 0,05 SOL ; sortie à +8 %, -6 % ou 90 secondes ; frais hypothétiques 1 % par côté + 0,00001 SOL par côté. Prix indicatifs, pas de transaction blockchain.</div>
<div style="overflow:auto"><table><thead><tr><th>Token</th><th>Mise</th><th>Quantité virtuelle</th><th>État</th></tr></thead><tbody id="positions"><tr><td colspan="4">Aucune position</td></tr></tbody></table></div></section>
<section class="card"><h2>Observations Solana</h2><div class="note" id="source">Attente des premières données</div>
<div style="overflow:auto"><table><thead><tr><th>Token</th><th>DEX</th><th>Prix SOL/token</th><th>Liquidité USD</th></tr></thead><tbody id="market"><tr><td colspan="4">Recherche…</td></tr></tbody></table></div></section>
<section class="card"><h2>Journal PAPER</h2><div style="overflow:auto"><table><thead><tr><th>Date UTC</th><th>Événement</th><th>Détails</th></tr></thead><tbody id="events"><tr><td colspan="3">Aucun événement</td></tr></tbody></table></div></section>
<section class="note warn">Prototype de validation sur service Render gratuit : le service peut s'endormir et les données temporaires peuvent disparaître au redéploiement. Pas d'ordres réels, pas de signature ni de P&amp;L prouvé. <a href="/api/status">API JSON</a></section>
</main>
<script>
function fmt(v,n=5){return Number.isFinite(Number(v))?Number(v).toFixed(n):"—"}
function el(id){return document.getElementById(id)}
function rows(id,values,widths){const parent=el(id);parent.replaceChildren();if(!values.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=widths;td.textContent='Aucune donnée disponible';tr.appendChild(td);parent.appendChild(tr);return}
for(const row of values){const tr=document.createElement('tr');for(const value of row){const td=document.createElement('td');td.textContent=String(value);tr.appendChild(td)}parent.appendChild(tr)}}
// Signed-source status must refresh even when the experimental market API fails.
async function drawHelius(){try{const hr=await fetch('/api/helius',{cache:'no-store'});if(!hr.ok)throw Error('HTTP '+hr.status);
const h=await hr.json(),s=h.last_summary||{};
el('helius-state').textContent='Source Helius : '+(h.observer_status||'INCONNU');
el('helius-counts').textContent='Captures : '+(h.cycle_count||0)+
' · créations signées confirmées : '+(s.crypto_signed_creation_transactions??'—')+
' · décisions S1 figées : '+(s.frozen_S1_decisions??'—')+
' · positions Master exécutées : 0'+
(h.last_safe_error_class?' · erreur : '+h.last_safe_error_class:'');
}catch(err){el('helius-state').textContent='Observateur Helius inaccessible : '+String(err.message||err)}}
async function draw(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json(),obs=d.observations||{},pos=d.positions||[];
const total=(Number(d.cash_sol)||0)+pos.reduce((v,p)=>v+Number(p.quantity||0)*Number(obs[p.mint]?.price||0)*.99,0);
el('total').textContent=fmt(total,6)+' SOL';el('cash').textContent=fmt(d.cash_sol,6)+' SOL';
el('closed').textContent=(d.closed||[]).length;const realized=(d.closed||[]).reduce((a,x)=>a+Number(x.pnl_sol||0),0);el('realized').textContent='P&L PAPER réalisé (modélisé) : '+fmt(realized,6)+' SOL';
const age=d.service?.last_source_age_seconds;el('health').textContent=d.service?.source_fresh?'Marché observé · '+age+' s':d.last_error?'Données : '+d.last_error:'En attente du marché';
el('source').textContent='Source : profils promotionnels DexScreener, paires SOL publiques · '+(d.polls||0)+' cycles · dernière observation : '+(age===null?'—':age+' secondes')+'. Ni univers complet des créations ni devis exécutables.';
rows('master',(d.master_shadow||[]).map(x=>[x.mint?.slice(0,11)+'…',x.action,(x.reasons||[]).slice(0,3).join(', ')||x.reason||'—']),3);
rows('positions',pos.map(x=>[x.symbol||x.mint.slice(0,10),fmt(x.spent_sol,4)+' SOL',fmt(x.quantity,2),'OUVERTE']),4);
rows('market',(d.candidates||[]).slice(0,12).map(x=>[x.symbol+' · '+x.mint.slice(0,8),x.dex,fmt(x.price_sol,10),fmt(x.liquidity_usd,0)]),4);
rows('events',(d.events||[]).slice(-14).reverse().map(x=>[new Date(x.at_ms).toISOString().slice(11,19),x.kind,JSON.stringify(x.details).slice(0,180)]),3);
}catch(err){el('health').textContent='Service indisponible : '+String(err.message||err)}}
draw();drawHelius();setInterval(draw,15000);setInterval(drawHelius,15000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            data=PAGE.encode("utf-8")
            mime="text/html; charset=utf-8"
        elif path == "/healthz":
            data=b'{"status":"up","financial_order_submitted":false}'
            mime="application/json"
        elif path == "/api/helius":
            data=json.dumps(SIGNED_SOURCE.snapshot(),allow_nan=False).encode("utf-8")
            mime="application/json"
        elif path == "/api/status":
            data=json.dumps(STORE.snapshot(),allow_nan=False).encode("utf-8")
            mime="application/json"
        elif path == "/api/trades":
            s=STORE.snapshot()
            data=json.dumps({"positions":s["positions"],"closed":s["closed"],
                "financial_order_submitted":False}).encode("utf-8")
            mime="application/json"
        elif path == "/api/events":
            data=json.dumps({"events":STORE.snapshot()["events"]}).encode("utf-8")
            mime="application/json"
        else:
            self.send_error(404);return
        self.send_response(200)
        self.send_header("Content-Type",mime)
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'")
        self.send_header("Access-Control-Allow-Origin","https://rugger-wallet-master.vercel.app")
        self.send_header("Access-Control-Allow-Methods","GET")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.send_error(405, "No financial or remote execution actions permitted")

    def log_message(self,*args):
        pass


def main():
    raw=os.environ.get("PORT","10000")
    if not raw.isascii() or not raw.isdigit() or not 1<=int(raw)<=65535:
        raise ValueError("invalid Render port")
    background=threading.Thread(target=run_public_worker,args=(STORE,),
                                name="rugger-public-paper-observer",daemon=True)
    background.start()
    server=ThreadingHTTPServer(("0.0.0.0",int(raw)),Handler)
    if SIGNED_SOURCE.settings["enabled"]:
        SIGNED_SOURCE.start()
    try:
        server.serve_forever()
    finally:
        SIGNED_SOURCE.stop()
        server.server_close()


if __name__=="__main__":
    main()
