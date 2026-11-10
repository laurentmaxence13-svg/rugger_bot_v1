#!/bin/bash
# W1 D1 — commands for the OWNER, in Google Cloud Shell of HIS project, ONLY after his explicit GO.
# Nothing here is run by an agent. Replace every __FILL value; no secret appears in this file.
# Usage: bash create_vm.sh setup | token inbound|outbound | launch | teardown
#        SOLE transport = CAB token via RUGGER 03's secure form (R02 decision 95ef4e34, K-1..K-7).
#        sign-inbound / sign-outbound exist ONLY as a fallback requiring a NEW R02 decision (dry run proving CAB fails).
# Cost frame (R04 quote): n2-highmem-8 on-demand us-central1 ~0.524 $/h before tax; GCS egress ~0.12 $/GB (R02 O-5)
# for the outbound download; total cap 20 $ TTC. The VM powers off at the end of startup.sh (then TERMINATED:
# no CPU billing, the 100 GB disk is billed until `teardown`, R02 O-1); it is deleted at 12 h if still running.
set -euo pipefail
PROJECT="__FILL: owner-project-id__"; REGION=us-central1; ZONE=us-central1-a
BUCKET="__FILL: owner-private-bucket__"           # private, us-central1, uniform access, public access prevention ON
IMAGE="__FILL: ubuntu-2404-noble-amd64-vYYYYMMDD__"   # a FIXED image name (not a family), recorded in the decision log
INBOUND_SUMS_SHA="__FILL: sha256 of INBOUND_SHA256SUMS, as anchored by RUGGER 02__"
S0=467275745
CODE_COMMIT="__FILL: commit whose tree is aff97638 (R03 c0199a3...)__"
START_STEP="__FILL: none | trials | evaluate__"   # none = equivalence-only dry run (no W1 data)
EXPECT_SHA="__FILL: digest of the step before START_STEP, anchored by RUGGER 02 (any hex for none)__"
CHAIN=chained                                      # accepted in writing by R02 (C1-C5); anchored = per-step anchors
VM_SA=w1-eval-sa@$PROJECT.iam.gserviceaccount.com           # identity of the VM (bucket only)
SIGNER_SA=w1-url-signer@$PROJECT.iam.gserviceaccount.com    # signs per-object URLs by impersonation (no key file)
URL_TTL=1h

die() { echo "STOP: $*"; exit 2; }
need_filled() { [[ "$PROJECT$BUCKET$IMAGE$INBOUND_SUMS_SHA$CODE_COMMIT$START_STEP$EXPECT_SHA" != *__FILL* ]] || die "fill every __FILL value first"; }
case "$START_STEP" in none|trials|evaluate|__FILL*) ;; *) die "bad START_STEP" ;; esac
case "$CHAIN" in anchored|chained) ;; *) die "bad CHAIN" ;; esac

case "${1:-}" in
setup)
  need_filled; gcloud config set project $PROJECT
  # 1. Private bucket (created only if absent), then CHECKED (R02 O-2), auto-cleaned after 7 days.
  gcloud storage buckets describe gs://$BUCKET >/dev/null 2>&1 || \
    gcloud storage buckets create gs://$BUCKET --location=$REGION --uniform-bucket-level-access --public-access-prevention
  d=$(gcloud storage buckets describe gs://$BUCKET --format='value(public_access_prevention,uniform_bucket_level_access,location)')
  [ "$d" = "$(printf 'enforced\tTrue\tUS-CENTRAL1')" ] || die "bucket_settings:$d"
  printf '{"rule":[{"action":{"type":"Delete"},"condition":{"age":7}}]}' > /tmp/lc.json
  gcloud storage buckets update gs://$BUCKET --lifecycle-file=/tmp/lc.json
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

token)          # RECOMMENDED transport (R02 B-3 "jeton réduit par CAB"): a 1 h access token of the signer SA
                # (bucket objectAdmin only), further reduced by a Credential Access Boundary to ONE prefix:
                # inbound/ = write, outbound/ = read. The owner types it into RUGGER 03's SECURE FORM (host
                # storage.googleapis.com, header Authorization: Bearer); the proxy injects it, nobody sees it in a chat.
  need_filled; dir=${2:-}
  case "$dir" in inbound) role=roles/storage.objectCreator ;; outbound) role=roles/storage.objectViewer ;; *) die "usage: token inbound|outbound" ;; esac
  base=$(gcloud auth print-access-token --impersonate-service-account=$SIGNER_SA)
  cab=$(python3 -c 'import json,sys; b,d,r=sys.argv[1:]; print(json.dumps({"accessBoundary":{"accessBoundaryRules":[{"availableResource":"//storage.googleapis.com/projects/_/buckets/"+b,"availablePermissions":["inRole:"+r],"availabilityCondition":{"expression":"resource.name.startsWith(\"projects/_/buckets/%s/objects/%s/\")" % (b,d)}}]}}))' "$BUCKET" "$dir" "$role")
  tok=$(printf '%s' "$base" | curl -sS --fail https://sts.googleapis.com/v1/token \
        --data-urlencode grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
        --data-urlencode subject_token_type=urn:ietf:params:oauth:token-type:access_token \
        --data-urlencode requested_token_type=urn:ietf:params:oauth:token-type:access_token \
        --data-urlencode "subject_token@-" --data-urlencode "options=$cab" | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
  echo "Token for $dir/ only, valid <= 1 h (copy it ONLY into RUGGER 03's secure form; never into a chat, GitHub or a file):"
  echo "$tok" ;;

sign-inbound)   # FALLBACK only (the URL transits in clear to RUGGER 03). NAMES.txt = one inbound object name per line (written by r03_transfer.sh prepare)
  need_filled; [ -f "${2:-}" ] || die "usage: sign-inbound NAMES.txt"
  umask 077; out=inbound_put_urls.tsv; : > $out
  while IFS= read -r name; do
    case "$name" in ""|*..*|/*) die "bad_name:$name" ;; esac
    url=$(gcloud storage sign-url "gs://$BUCKET/inbound/$name" --http-verb=PUT --duration=$URL_TTL \
          --impersonate-service-account=$SIGNER_SA --format='value(signed_url)')
    printf '%s\t%s\n' "$name" "$url" >> $out
  done < "$2"
  echo "wrote $out (SECRET, expires in $URL_TTL: give it to RUGGER 03 only, never in GitHub or a log)" ;;

launch)
  need_filled
  gcloud compute instances create w1-eval --zone=$ZONE --machine-type=n2-highmem-8 \
    --image=$IMAGE --image-project=ubuntu-os-cloud --boot-disk-size=100GB --boot-disk-type=pd-balanced \
    --no-address --service-account=$VM_SA --scopes=https://www.googleapis.com/auth/devstorage.read_write \
    --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
    --max-run-duration=12h --instance-termination-action=DELETE \
    --metadata-from-file=startup-script=startup.sh \
    --metadata=bucket=$BUCKET,inbound_sums_sha256=$INBOUND_SUMS_SHA,s0=$S0,start_step=$START_STEP,expect_sha=$EXPECT_SHA,workers=8,chain_mode=$CHAIN,code_commit=$CODE_COMMIT,block-project-ssh-keys=TRUE,enable-oslogin=TRUE
  echo "follow (read only): gcloud compute instances get-serial-port-output w1-eval --zone=$ZONE | grep -E 'STOP|step|EXIT|done|PASS'"
  echo "keep the serial console: gcloud compute instances get-serial-port-output w1-eval --zone=$ZONE > serial_w1-eval.txt (R02 C2)" ;;

sign-outbound)  # after EXIT in the serial console; GET URLs for every outbound object
  need_filled; umask 077; out=outbound_get_urls.tsv; : > $out
  for obj in $(gcloud storage ls "gs://$BUCKET/outbound/"); do
    url=$(gcloud storage sign-url "$obj" --http-verb=GET --duration=$URL_TTL --impersonate-service-account=$SIGNER_SA --format='value(signed_url)')
    printf '%s\t%s\n' "${obj##*/}" "$url" >> $out
  done
  echo "wrote $out (SECRET, expires in $URL_TTL: give it to RUGGER 03 only)" ;;

teardown)       # once RUGGER 03 has downloaded and RUGGER 02 has checked the hashes
  need_filled
  gcloud compute instances delete w1-eval --zone=$ZONE --quiet || true
  gcloud storage rm -r "gs://$BUCKET/inbound" "gs://$BUCKET/outbound" "gs://$BUCKET/anchors" || true
  gcloud compute disks delete w1-eval --zone=$ZONE --quiet 2>/dev/null || true      # boot disk (auto-deleted with the VM by default)
  gcloud iam service-accounts delete $VM_SA --quiet; gcloud iam service-accounts delete $SIGNER_SA --quiet
  left=$(gcloud compute instances list --filter=name=w1-eval --format='value(name)'); [ -z "$left" ] || die "vm_still_present"
  disk=$(gcloud compute disks list --filter=name=w1-eval --format='value(name)'); [ -z "$disk" ] || die "disk_still_present"
  objs=$(gcloud storage ls "gs://$BUCKET/**" 2>/dev/null || true); [ -z "$objs" ] || die "bucket_objects_still_present"
  echo "teardown OK: no VM, no disk, no service account; bucket objects removed (bucket kept empty, lifecycle 7 d)" ;;
*) die "usage: setup | token inbound|outbound | launch | teardown  (fallback: sign-inbound NAMES.txt | sign-outbound)" ;;
esac
