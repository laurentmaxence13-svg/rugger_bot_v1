"""Deliberate defects in w1aux/ledger_resume.py: each must make test_ledger_resume.py fail."""
import json, shutil, subprocess
from pathlib import Path
S = Path('/tmp/claude-0/-home-user/e0619565-42dc-58dc-a353-d81a7198e975/scratchpad')
V = '/tmp/claude-0/-home-user-rugger-bot-v1/e0619565-42dc-58dc-a353-d81a7198e975/scratchpad/venv312/bin/python'
SRC = S / 'wt_tooling/out_of_tree/w1aux_v76'
MUT = [
 ('no_occurrence_rank', "        keys.append(hashlib.sha256(json.dumps([base, occurrence]).encode()).hexdigest())\n",
  "        keys.append(hashlib.sha256(json.dumps([base, 0]).encode()).hexdigest())\n"),
 ('timeline_not_in_key', "                timeline_sha256=hashlib.sha256(timeline_doc.encode()).hexdigest(),\n", "                timeline_sha256=None,\n"),
 ('params_not_in_key', "                params=_canonical(params),\n", "                params=None,\n"),
 ('indices_not_in_key', "                indices=sorted(indices))\n", "                indices=None)\n"),
 ('history_not_in_key', "                history=None if history is None else [history.sha256, history.label],\n", "                history=None,\n"),
 ('series_not_in_key', "                series=None if series is None else [series.sha256, series.max_age_ms, series.max_confidence_ppm],\n", "                series=None,\n"),
 ('archive_sha_not_in_key', "    return dict(archive=[archive.pool, archive._sha256],\n", "    return dict(archive=[archive.pool],\n"),
 ('eager_archive_accepted', "        raise LedgerResumeError('cache_needs_lazy_archives')\n", "        pass\n"),
 ('kwargs_accepted', "            raise LedgerResumeError('unexpected_keyword_arguments')\n", "            pass\n"),
 ('sha_not_checked', "        if hashlib.sha256(data).hexdigest() != self.index[key]:\n", "        if False:\n"),
 ('missing_file_crashes', "        if not path.is_file():\n            self.rejected += 1\n            return None\n", ""),
 ('embedded_key_not_checked', "        if not isinstance(doc, dict) or doc.get('key') != key:\n", "        if not isinstance(doc, dict):\n"),
 ('foreign_accepted', "            raise LedgerResumeError('foreign_entry_in_resume_dir:' + sorted(foreign)[0])\n", "            pass\n"),
 ('orphan_accepted', "                raise LedgerResumeError('orphan_file_in_resume_dir:' + path.name)\n", "                pass\n"),
 ('tmp_not_removed', "                path.unlink()\n                self.tmp_removed += 1\n", "                self.tmp_removed += 1\n"),
 ('meta_not_checked', "        if json.loads(meta_path.read_text(encoding='utf-8')) != self.meta:\n", "        if False:\n"),
 ('meta_missing_accepted', "            raise LedgerResumeError('resume_dir_without_meta')\n", "            pass\n"),
 ('bad_line_ignored', "                raise LedgerResumeError('resume_index_line_unreadable')\n", "                continue\n"),
 ('tail_not_rewritten', "        if lines and lines[-1] != '':                               # drop the interrupted tail before appending\n", "        if False:\n"),
 ('file_before_index', """        with open(self.dir / INDEX, 'a', encoding='utf-8') as handle:       # index line first: no orphan file
            handle.write(json.dumps(dict(key=key, sha256=sha)) + '\\n')
            handle.flush()
            os.fsync(handle.fileno())
""", ""),
 ('result_not_stored', "                cache.put(key, value)\n", ""),
 ('cache_never_read', "            value = cache.get(key)\n", "            value = None\n"),
 ('lookup_without_check', "                    or not all(lp._same(x, y) for x, y in zip(a, calls[i][0])) \\\n", "                    or False \\\n"),
 ('unused_results_accepted', "        if next(position, None) is not None:\n            raise LedgerResumeError('ledger_calls_not_all_used')\n", ""),
 ('binding_not_required', "        raise LedgerResumeError('binding_required')\n", "        pass\n"),
 ('not_reentrancy_guarded', "    if _ACTIVE['on'] or lp._ACTIVE['on']:\n", "    if lp._ACTIVE['on']:\n"),
 ('ledger_sha_not_checked', "    lp._check_ledger_module()\n", ""),
 ('no_lazy_archives', "        with lazy.lazy_archives():\n", "        with contextlib.nullcontext():\n"),
 ('openings_file_refused', "            if path.name in (META, INDEX, OPENINGS):\n", "            if path.name in (META, INDEX):\n"),
 ('resumes_not_counted', "resumes=cache.openings - 1)", "resumes=0)"),
 ('reused_not_counted', "                STATS['reused'] += 1\n", "                pass\n"),
]
out = []
for name, old, new in MUT:
    dst = S / 'mut_lr' / 'pkg_final'
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(SRC, dst)
    f = dst / 'w1aux' / 'ledger_resume.py'
    text = f.read_text()
    assert text.count(old) == 1, name
    f.write_text(text.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(dst / 'w1aux/tests/test_ledger_resume.py'), '-p', 'no:cacheprovider',
                        '-q', '-x', '-W', 'error'], cwd=S / 'wt_w1', capture_output=True, text=True, timeout=1500,
                       env={'PYTHONPATH': f"{S/'wt_w1'}:{dst}", 'RUGGER_NO_DOTENV': '1', 'PATH': '/usr/bin:/bin'})
    last = (r.stdout.strip().splitlines() or [''])[-1]
    out.append(dict(mutant=name, detected=r.returncode != 0, last=last))
    print(json.dumps(out[-1]), flush=True)
print(f"detected {sum(o['detected'] for o in out)}/{len(out)}")
