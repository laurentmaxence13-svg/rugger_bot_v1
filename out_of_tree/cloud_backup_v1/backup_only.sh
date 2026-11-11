#!/bin/bash
# W1 BACKUP ONLY — commands for the OWNER, in Google Cloud Shell of HIS project, ONLY after his explicit final GO.
# Nothing here is run by an agent. No VM, no disk, no network change. Replace every __FILL value; no secret is in this file.
# Derived from the audited package cloud_d1_v25/create_vm.sh (bucket checks and CAB token unchanged); v2.5 itself is untouched.
#
# Usage: bash backup_only.sh setup
#        bash backup_only.sh token                      # 1 h token that can ONLY CREATE objects under gs://BUCKET/w1-backup/
#        bash backup_only.sh verify                     # owner side: names, sizes and checksums of what was received
#        bash backup_only.sh sha256 SHA256SUMS          # owner side: recompute sha256 of every object against the anchored list
#        bash backup_only.sh delete DELETE-W1-BACKUP    # removes the objects, the service account and the bucket
#
# What the writer can do: create new objects under the prefix. It cannot read, list, overwrite or delete (role
# objectCreator, reduced to the prefix by a Credential Access Boundary): the copy stays SEALED for every agent.
# Indicative cost, TO BE CONFIRMED by the owner on the Google Cloud price list before his GO: storage of 6 to 14 GB in
# us-central1 is a few tens of cents per month; uploading is free; DOWNLOADING the copy out of Google Cloud is billed per GB.
set -euo pipefail
PROJECT="__FILL: owner-project-id__"; REGION=us-central1
BUCKET="__FILL: owner-private-bucket__"           # private, us-central1, uniform access, public access prevention ON
PREFIX=w1-backup
WRITER=w1-backup-writer
WRITER_SA=$WRITER@$PROJECT.iam.gserviceaccount.com

die() { echo "STOP: $*"; exit 2; }
[[ "$PROJECT$BUCKET" != *__FILL* ]] || die "fill every __FILL value first"
[[ "$PROJECT" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || die "bad_project_id"
[[ "$BUCKET" =~ ^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$ ]] || die "bad_bucket_name"

case "${1:-}" in
setup)
  gcloud config set project $PROJECT
  # 1. Private bucket (created only if absent), then CHECKED.
  gcloud storage buckets describe gs://$BUCKET >/dev/null 2>&1 || \
    gcloud storage buckets create gs://$BUCKET --location=$REGION --uniform-bucket-level-access --public-access-prevention
  d=$(gcloud storage buckets describe gs://$BUCKET --format='value(public_access_prevention,uniform_bucket_level_access,location)')
  [ "$d" = "$(printf 'enforced\tTrue\tUS-CENTRAL1')" ] || die "bucket_settings:$d"
  # 2. One service account, create-only on this bucket, no project role, no key file ever created.
  gcloud iam service-accounts describe $WRITER_SA >/dev/null 2>&1 || \
    gcloud iam service-accounts create $WRITER --display-name="W1 backup writer (create only, one bucket)"
  gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member=serviceAccount:$WRITER_SA --role=roles/storage.objectCreator >/dev/null
  roles=$(gcloud projects get-iam-policy $PROJECT --flatten=bindings[].members --filter="bindings.members:serviceAccount:$WRITER@" --format='value(bindings.role)')
  [ -z "$roles" ] || die "project_roles_on_$WRITER:$roles"
  [ -z "$(gcloud iam service-accounts keys list --iam-account=$WRITER_SA --managed-by=user --format='value(name)')" ] || die "user_key_on_$WRITER"
  me=$(gcloud config get-value account)
  gcloud iam service-accounts add-iam-policy-binding $WRITER_SA --member="user:$me" --role=roles/iam.serviceAccountTokenCreator >/dev/null
  echo "setup OK: bucket gs://$BUCKET (private), writer $WRITER_SA (create only). Nothing else was created." ;;

token)          # a 1 h access token of the writer, reduced by a Credential Access Boundary to CREATE under ONE prefix.
                # The owner types it into RUGGER 03's SECURE FORM (host storage.googleapis.com, header Authorization:
                # Bearer); the proxy injects it, nobody sees it in a chat. It expires by itself after 1 h.
  role=roles/storage.objectCreator
  base=$(gcloud auth print-access-token --impersonate-service-account=$WRITER_SA)
  cab=$(python3 -c 'import json,sys; b,d,r=sys.argv[1:]; print(json.dumps({"accessBoundary":{"accessBoundaryRules":[{"availableResource":"//storage.googleapis.com/projects/_/buckets/"+b,"availablePermissions":["inRole:"+r],"availabilityCondition":{"expression":"resource.name.startsWith(\"projects/_/buckets/%s/objects/%s/\")" % (b,d)}}]}}))' "$BUCKET" "$PREFIX" "$role")
  tok=$(printf '%s' "$base" | curl -sS --fail https://sts.googleapis.com/v1/token \
        --data-urlencode grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
        --data-urlencode subject_token_type=urn:ietf:params:oauth:token-type:access_token \
        --data-urlencode requested_token_type=urn:ietf:params:oauth:token-type:access_token \
        --data-urlencode "subject_token@-" --data-urlencode "options=$cab" | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
  echo "Token: CREATE under $PREFIX/ only, valid <= 1 h (copy it ONLY into RUGGER 03's secure form; never into a chat, GitHub or a file):"
  echo "$tok" ;;

verify)         # owner side, read with the owner's own rights: what arrived, with sizes and Google's checksums
  gcloud storage objects list "gs://$BUCKET/$PREFIX/**" --format='table(name,size,crc32c_hash,md5_hash,creation_time)'
  echo "objects: $(gcloud storage ls "gs://$BUCKET/$PREFIX/**" | wc -l)   total bytes: $(gcloud storage du -s "gs://$BUCKET/$PREFIX" | awk '{print $1}')" ;;

sha256)         # owner side: SHA256SUMS = "<sha256>  <object name under the prefix>" per line, the list anchored by RUGGER 02
  [ -f "${2:-}" ] || die "usage: sha256 SHA256SUMS"
  bad=0; n=0
  while read -r want name; do
    case "$name" in ""|*..*|/*) die "bad_name:$name" ;; esac
    got=$(gcloud storage cat "gs://$BUCKET/$PREFIX/$name" | sha256sum | cut -d' ' -f1)
    n=$((n+1)); [ "$got" = "$want" ] || { echo "MISMATCH $name"; bad=$((bad+1)); }
  done < "$2"
  [ "$bad" = 0 ] || die "sha256_mismatches:$bad"
  echo "sha256 OK: $n objects identical to the anchored list" ;;

delete)         # when the owner decides the copy is no longer needed
  [ "${2:-}" = "DELETE-W1-BACKUP" ] || die "usage: delete DELETE-W1-BACKUP"
  gcloud storage rm -r "gs://$BUCKET/$PREFIX" || true
  gcloud iam service-accounts delete $WRITER_SA --quiet || true
  objs=$(gcloud storage ls "gs://$BUCKET/**" 2>/dev/null || true); [ -z "$objs" ] || die "bucket_objects_still_present"
  gcloud storage buckets delete gs://$BUCKET
  left=$(gcloud iam service-accounts list --filter="email:$WRITER_SA" --format='value(email)'); [ -z "$left" ] || die "service_account_still_present"
  gcloud storage buckets describe gs://$BUCKET >/dev/null 2>&1 && die "bucket_still_present"
  echo "delete OK: no object, no service account, no bucket" ;;
*) die "usage: setup | token | verify | sha256 SHA256SUMS | delete DELETE-W1-BACKUP" ;;
esac
