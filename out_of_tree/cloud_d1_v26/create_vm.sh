#!/bin/bash
# W1 D1 v2.6 — commands for the OWNER, in Google Cloud Shell of HIS project, ONLY after his explicit GO.
# Nothing here is run by an agent. Replace every __FILL value; no secret appears in this file.
# v2.6 (2026-11-14): the WHOLE post-collection chain runs on the VM with the FROZEN code, unchanged
# (selfcheck, gate, export, series, trials, evaluate, ledger, dossier), ONE STEP AT A TIME: after each step the
# VM publishes DAYJ_STATE.json and waits for the digest anchored by RUGGER 02 (anchors/expect_<step>.txt).
# Usage: bash create_vm.sh setup | token inbound|outbound|relay | launch | anchor STEP SHA256 | start | status | teardown
#        SOLE transport = CAB token typed into RUGGER 03's secure form (R02 decision 95ef4e34, K-1..K-7).
# Cost (official on-demand price list read on 2026-11-14, cloud.google.com/products/compute/pricing/general-purpose):
#   n2-highmem-16 (16 vCPU, 128 GB) 1.048112 $/h ; n2-highmem-32 (32 vCPU, 256 GB) 2.096224 $/h, before tax.
#   The VM is billed only while it RUNS; its disk is billed until `teardown`. DEADLINE stops it whatever happens.
set -euo pipefail
PROJECT="__FILL: owner-project-id__"; REGION=us-central1; ZONE=us-central1-a
BUCKET="__FILL: owner-private-bucket__"           # private, us-central1, uniform access, public access prevention ON
IMAGE="__FILL: ubuntu-2404-noble-amd64-vYYYYMMDD__"   # a FIXED image name (not a family), recorded in the decision log
MACHINE="__FILL: n2-highmem-16 or n2-highmem-32 (sized by RUGGER 02 on the exported signature count)__"
DISK_GB=300                                        # inputs (about 5 GB), pools, bundles, ledger, margin
DEADLINE="__FILL: RFC 3339 UTC time after which the VM is stopped whatever happens, e.g. 2026-11-17T12:00:00Z__"
INBOUND_SUMS_SHA="__FILL: sha256 of INBOUND_SHA256SUMS, as anchored by RUGGER 02__"
S0=467275745
CODE_COMMIT="__FILL: commit whose tree is aff97638 (R03 c0199a3...)__"
WAIT_MINUTES=180                                   # how long the VM waits for an anchor before it powers off (then: start)
VM_SA=w1-eval-sa@$PROJECT.iam.gserviceaccount.com           # identity of the VM (bucket only)
SIGNER_SA=w1-url-signer@$PROJECT.iam.gserviceaccount.com    # source of the reduced tokens, by impersonation (no key file)
STEPS="gate export series trials evaluate ledger dossier"   # selfcheck needs no anchor: it is the first step

die() { echo "STOP: $*"; exit 2; }
need_filled() { [[ "$PROJECT$BUCKET$IMAGE$MACHINE$DEADLINE$INBOUND_SUMS_SHA$CODE_COMMIT" != *__FILL* ]] || die "fill every __FILL value first"; }
check_values() {
  case "$MACHINE" in n2-highmem-16|n2-highmem-32) ;; *) die "bad MACHINE" ;; esac
  [[ "$DEADLINE" =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || die "bad DEADLINE"
  [[ "$INBOUND_SUMS_SHA" =~ ^[0-9a-f]{64}$ ]] || die "bad INBOUND_SUMS_SHA"
  [[ "$CODE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "bad CODE_COMMIT"
}

case "${1:-}" in
setup)
  need_filled; check_values; gcloud config set project $PROJECT
  # 1. Private bucket (created only if absent), then CHECKED (R02 O-2). No automatic deletion (R02 e372f4c5).
  gcloud storage buckets describe gs://$BUCKET >/dev/null 2>&1 || \
    gcloud storage buckets create gs://$BUCKET --location=$REGION --uniform-bucket-level-access --public-access-prevention
  d=$(gcloud storage buckets describe gs://$BUCKET --format='value(public_access_prevention,uniform_bucket_level_access,location)')
  [ "$d" = "$(printf 'enforced\tTrue\tUS-CENTRAL1')" ] || die "bucket_settings:$d"
  # 2. Two service accounts, bucket-scoped only, no key file ever created.
  for sa in w1-eval-sa w1-url-signer; do
    gcloud iam service-accounts describe $sa@$PROJECT.iam.gserviceaccount.com >/dev/null 2>&1 || \
      gcloud iam service-accounts create $sa --display-name="W1 D1 $sa (bucket only)"
    gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member=serviceAccount:$sa@$PROJECT.iam.gserviceaccount.com --role=roles/storage.objectAdmin >/dev/null
    roles=$(gcloud projects get-iam-policy $PROJECT --flatten=bindings[].members --filter="bindings.members:serviceAccount:$sa@" --format='value(bindings.role)')
    [ -z "$roles" ] || die "project_roles_on_$sa:$roles"               # R02 O-2: no project-level role
    [ -z "$(gcloud iam service-accounts keys list --iam-account=$sa@$PROJECT.iam.gserviceaccount.com --managed-by=user --format='value(name)')" ] || die "user_key_on_$sa"
  done
  me=$(gcloud config get-value account)
  gcloud iam service-accounts add-iam-policy-binding $SIGNER_SA --member="user:$me" --role=roles/iam.serviceAccountTokenCreator >/dev/null
  # 3. No external IP: Google APIs only, via Private Google Access; there must be NO Cloud NAT in the region (R02 O-4).
  gcloud compute networks subnets update default --region=$REGION --enable-private-ip-google-access
  [ -z "$(gcloud compute routers list --regions=$REGION --format='value(nats)' | tr -d '[]')" ] || die "cloud_nat_present_in_$REGION"
  echo "setup OK" ;;

token)          # a 1 h access token of the signer SA, reduced by a Credential Access Boundary:
                #   inbound  = CREATE under inbound/ only (RUGGER 03 deposits the inputs)
                #   outbound = READ under outbound/ only (RUGGER 03 fetches the final results)
                #   relay    = READ under outbound/ AND CREATE under anchors/ (RUGGER 03 relays each step between
                #              the VM and RUGGER 02) — needs RUGGER 02's written amendment of K-1 before any use
                # The owner types it into RUGGER 03's SECURE FORM (host storage.googleapis.com, header Authorization:
                # Bearer); the proxy injects it, nobody sees it in a chat. Then `clear` (K-2).
  need_filled; dir=${2:-}
  case "$dir" in inbound|outbound|relay) ;; *) die "usage: token inbound|outbound|relay" ;; esac
  base=$(gcloud auth print-access-token --impersonate-service-account=$SIGNER_SA)
  cab=$(python3 -c '
import json, sys
bucket, kind = sys.argv[1:]
def rule(prefix, role):
    return {"availableResource": "//storage.googleapis.com/projects/_/buckets/" + bucket,
            "availablePermissions": ["inRole:" + role],
            "availabilityCondition": {"expression": "resource.name.startsWith(\"projects/_/buckets/%s/objects/%s/\")" % (bucket, prefix)}}
rules = {"inbound": [rule("inbound", "roles/storage.objectCreator")],
         "outbound": [rule("outbound", "roles/storage.objectViewer")],
         "relay": [rule("outbound", "roles/storage.objectViewer"), rule("anchors", "roles/storage.objectCreator")]}[kind]
print(json.dumps({"accessBoundary": {"accessBoundaryRules": rules}}))' "$BUCKET" "$dir")
  tok=$(printf '%s' "$base" | curl -sS --fail https://sts.googleapis.com/v1/token \
        --data-urlencode grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
        --data-urlencode subject_token_type=urn:ietf:params:oauth:token-type:access_token \
        --data-urlencode requested_token_type=urn:ietf:params:oauth:token-type:access_token \
        --data-urlencode "subject_token@-" --data-urlencode "options=$cab" | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
  echo "Token ($dir), valid <= 1 h (copy it ONLY into RUGGER 03's secure form; never into a chat, GitHub or a file; then clear):"
  echo "$tok" ;;

launch)
  need_filled; check_values
  gcloud compute instances create w1-eval --zone=$ZONE --machine-type=$MACHINE \
    --image=$IMAGE --image-project=ubuntu-os-cloud --boot-disk-size=${DISK_GB}GB --boot-disk-type=pd-balanced \
    --no-address --service-account=$VM_SA --scopes=https://www.googleapis.com/auth/devstorage.read_write \
    --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
    --termination-time=$DEADLINE --instance-termination-action=STOP \
    --metadata-from-file=startup-script=startup.sh \
    --metadata=bucket=$BUCKET,inbound_sums_sha256=$INBOUND_SUMS_SHA,s0=$S0,workers=8,wait_minutes=$WAIT_MINUTES,deadline=$DEADLINE,code_commit=$CODE_COMMIT,block-project-ssh-keys=TRUE,enable-oslogin=TRUE
  echo "follow (read only): bash create_vm.sh status" ;;

anchor)         # the owner deposits the digest RUGGER 02 anchored for the step BEFORE this one (the VM waits for it)
  need_filled; step=${2:-}; sha=${3:-}
  case " $STEPS " in *" $step "*) ;; *) die "usage: anchor <$STEPS> <sha256>" ;; esac
  [[ "$sha" =~ ^[0-9a-f]{64}$ ]] || die "bad_sha256"
  gcloud storage ls "gs://$BUCKET/anchors/expect_$step.txt" >/dev/null 2>&1 && die "anchor_already_deposited:$step"
  printf '%s\n' "$sha" > /tmp/expect_$step.txt
  gcloud storage cp --quiet /tmp/expect_$step.txt "gs://$BUCKET/anchors/expect_$step.txt"; rm -f /tmp/expect_$step.txt
  echo "anchor deposited for $step (dayj itself refuses a digest that is not the previous step's)" ;;

start)          # after a pause (the VM powers off when no anchor came within WAIT_MINUTES): start it again
  need_filled
  gcloud compute instances start w1-eval --zone=$ZONE
  echo "started; follow: bash create_vm.sh status" ;;

status)
  need_filled
  gcloud compute instances describe w1-eval --zone=$ZONE --format='value(status)'
  gcloud compute instances get-serial-port-output w1-eval --zone=$ZONE 2>/dev/null | grep -E 'STOP|PAUSE|step |EXIT|done|boot ' | tail -20 || true ;;

teardown)       # once RUGGER 03 has downloaded and RUGGER 02 has checked the hashes
  need_filled
  gcloud compute instances get-serial-port-output w1-eval --zone=$ZONE > serial_w1-eval.txt 2>/dev/null || true   # kept (R02 C2)
  gcloud compute instances delete w1-eval --zone=$ZONE --quiet || true
  gcloud storage rm -r "gs://$BUCKET/inbound" "gs://$BUCKET/outbound" "gs://$BUCKET/anchors" || true
  gcloud compute disks delete w1-eval --zone=$ZONE --quiet 2>/dev/null || true      # boot disk (auto-deleted with the VM by default)
  gcloud iam service-accounts delete $VM_SA --quiet; gcloud iam service-accounts delete $SIGNER_SA --quiet
  left=$(gcloud compute instances list --filter=name=w1-eval --format='value(name)'); [ -z "$left" ] || die "vm_still_present"
  disk=$(gcloud compute disks list --filter=name=w1-eval --format='value(name)'); [ -z "$disk" ] || die "disk_still_present"
  objs=$(gcloud storage ls "gs://$BUCKET/inbound/**" "gs://$BUCKET/outbound/**" "gs://$BUCKET/anchors/**" 2>/dev/null || true); [ -z "$objs" ] || die "bucket_objects_still_present"
  echo "teardown OK: no VM, no disk, no service account; inbound/, outbound/ and anchors/ removed (other prefixes untouched)" ;;
*) die "usage: setup | token inbound|outbound|relay | launch | anchor STEP SHA256 | start | status | teardown" ;;
esac
