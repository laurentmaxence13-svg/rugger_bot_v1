"""Exécution À BLANC de la chaîne G2-3 (g23run 0.1.2, phase pilote) sur le dossier FICTIF de R03 (6e27bf5) -- P1/P2 du
pré-mortem. Aucun résultat : vérification technique seulement. Le code gelé n'est pas modifié : seules les deux
constantes de fenêtre du module sont remplacées EN MÉMOIRE, dans ce processus (T0 := début fictif, D_PILOT := 7),
pour que window_line et le rapport lisent [1794910886 ; 1795515686). Tout le reste est g23run.run.run tel quel, et
l'écriture reproduit main() octet pour octet (même sérialisation).
python -B -I dry_g23.py U2.json ROOT OUT SHEET_SHA"""
import hashlib
import json
import sys
from pathlib import Path

from cpmmpilot import step1 as PILOT
from g23run import run as G

FICT_START, FICT_END = 1794910886, 1795515686
U2_SHA = '3ca0260aa187f8df99ab422fc74fbbb1da4404d6f6b175548270ade3e731a963'


def main(u2_path, root, out, sheet_sha):
    if hashlib.sha256(Path(u2_path).read_bytes()).hexdigest() != U2_SHA:
        raise SystemExit('u2_not_the_anchored_file')
    out = Path(out)
    if out.exists():
        raise SystemExit('out_exists')
    assert FICT_END - FICT_START == 7 * G.DAY_S and FICT_END == G.T0          # the 7 days just before the real T0
    real = dict(T0=G.T0, D_PILOT=G.D_PILOT)
    G.T0, G.D_PILOT = FICT_START, 7                                          # in memory only
    u2 = json.loads(Path(u2_path).read_text())
    selected = [r for r in u2['selected'] if r['pool'] in G.POOLS]
    config = PILOT.amm_config_for_rules(selected, u2['t0_slot'])
    recon = {}
    doc, rows = G.run('pilot', selected=selected, root=root, config=config, sheet_sha=sheet_sha, recon=recon)
    out.mkdir(parents=True)
    shas = {}
    for name, content in (('ROWS.json', rows), ('RESULT.json', doc),
                          ('RECONSTRUCTION.json', dict(schema=G.RECONSTRUCTION_SCHEMA, pools=recon))):
        text = json.dumps(content, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n'
        (out / name).write_text(text)
        shas[name] = hashlib.sha256(text.encode()).hexdigest()
    info = dict(label='EXÉCUTION À BLANC SUR DOSSIER FICTIF -- AUCUN RÉSULTAT', window=[FICT_START, FICT_END],
                replaced_in_memory=dict(T0=[real['T0'], FICT_START], D_PILOT=[real['D_PILOT'], 7]),
                g23run_file=G.__file__, g23run_sha256=hashlib.sha256(Path(G.__file__).read_bytes()).hexdigest(),
                outputs=shas)
    (out / 'DRYRUN_INFO.json').write_text(json.dumps(info, indent=1, sort_keys=True, ensure_ascii=False) + '\n')
    print(json.dumps(shas, sort_keys=True))


if __name__ == '__main__':
    main(*sys.argv[1:5])
