"""Archive only PUBLIC mainnet observations produced by bounded PAPER probes.

A GitHub Actions artifact is per-run evidence, not part of the git repository.
The archive never contains API keys, private keys, signed transactions or
credentials, and it NEVER certifies economic profitability. It is suitable
for subsequent deduplication by pool/creator/slot. Artifacts are retained for
only the workflow-configured retention period.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA="rugger-paper-observation-archive-v1"
_KINDS=frozenset(("active_survivor_cohort","s1_capacity_s2",
                  "historical_launchlab_sample"))
_FORBIDDEN_KEYS=frozenset(("api_key","helius_api_key","private_key","secret_key",
            "wallet_secret","seed_phrase","mnemonic","rpc_authenticated_url",
            "authorization","access_token","refresh_token","signed_transaction"))
_SECRET_PATTERN=re.compile(
    r"(?:api[-_]?key\s*[=:]|bearer\s+|private[-_]?key\s*[=:]|"
    r"mainnet\.helius-rpc\.com/\?api-key=)",re.I)


def _verify_public_only(value, depth=0):
    if depth>18:
        raise ValueError("paper_evidence_recursion_cap")
    if type(value) is dict:
        if len(value)>5000:
            raise ValueError("paper_evidence_dictionary_cap")
        for k,v in value.items():
            if type(k) is not str:
                raise ValueError("paper_evidence_nonstring_key")
            if k.lower() in _FORBIDDEN_KEYS or _SECRET_PATTERN.search(k):
                raise ValueError("paper_evidence_forbidden_key")
            _verify_public_only(v,depth+1)
    elif type(value) is list:
        if len(value)>5000:
            raise ValueError("paper_evidence_list_cap")
        for v in value:
            _verify_public_only(v,depth+1)
    elif type(value) is str:
        if len(value)>90000 or _SECRET_PATTERN.search(value):
            raise ValueError("paper_evidence_secret_or_length_refused")
    elif value is None or type(value) in (int,bool):
        return
    else:
        raise ValueError("paper_evidence_noncanonical_type")


def build_archive(report, *, kind, run_id, commit_sha, now_iso):
    if type(report) is not dict or kind not in _KINDS:
        raise ValueError("paper_evidence_kind_or_report_invalid")
    if (report.get("financial_order_submitted") is not False
            or report.get("live_ready_to_arm") is not False):
        raise ValueError("paper_evidence_must_remain_read_only")
    if type(run_id) is not str or not re.fullmatch(r"[0-9]{1,16}",run_id):
        raise ValueError("paper_evidence_run_id_invalid")
    if type(commit_sha) is not str or not re.fullmatch(r"[a-f0-9]{40}",commit_sha):
        raise ValueError("paper_evidence_commit_sha_invalid")
    if type(now_iso) is not str or len(now_iso)>40 or not now_iso.endswith("+00:00"):
        raise ValueError("paper_evidence_UTC_timestamp_required")
    _verify_public_only(report)
    payload=json.dumps(report,sort_keys=True,separators=(",",":"),
                       ensure_ascii=True,allow_nan=False)
    if len(payload.encode())>250_000:
        raise ValueError("paper_evidence_250kb_cap")
    digest=hashlib.sha256(payload.encode()).hexdigest()
    return dict(schema=_SCHEMA,kind=kind,run_id=run_id,
        commit_sha=commit_sha,created_at_utc=now_iso,
        observation_sha256=digest,observation=json.loads(payload),
        financial_order_submitted=False,live_ready_to_arm=False,
        independent_creator_holdout_validated=False,
        economic_edge_validated=False)


def archive_from_github_actions(report, *, kind):
    """Opt-in only from a GitHub Actions run; cannot write outside workspace."""
    if os.getenv("RUGGER_WRITE_PUBLIC_EVIDENCE")!="1":
        return None
    if os.getenv("GITHUB_ACTIONS")!="true":
        raise ValueError("paper_evidence_GitHub_Actions_only")
    root=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    run_id=os.environ["GITHUB_RUN_ID"]
    sha=os.environ["GITHUB_SHA"]
    now=datetime.now(timezone.utc).isoformat()
    output=build_archive(report,kind=kind,run_id=run_id,
                         commit_sha=sha,now_iso=now)
    directory=root/".artifacts"/"paper_public_observations"
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/(kind+"-"+run_id+".json")
    # Refuse symlink-created escape and avoid arbitrary paths or secret files.
    if not target.resolve().is_relative_to(root):
        raise ValueError("paper_evidence_path_escape")
    target.write_text(json.dumps(output,sort_keys=True,indent=2)+"\n",
                      encoding="utf-8")
    return dict(path=str(target.relative_to(root)),
                observation_sha256=output["observation_sha256"],
                archive_created=True)
