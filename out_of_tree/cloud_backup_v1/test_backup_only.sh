#!/bin/bash
# Offline test with STUB gcloud / curl (no network, no Google account): refusals, the exact commands issued, the boundary.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin"; log="$tmp/calls.log"; : > "$log"
cat > "$tmp/bin/gcloud" <<'STUB'
#!/bin/bash
echo "gcloud $*" >> "$CALLS"
case "$*" in
  *"buckets describe"*"--format"*) printf 'enforced\tTrue\tUS-CENTRAL1\n' ;;
  *"buckets describe"*) [ -f "$STATE/bucket" ] ;;
  *"buckets create"*) touch "$STATE/bucket" ;;
  *"buckets delete"*) rm -f "$STATE/bucket" ;;
  *"service-accounts describe"*) exit 1 ;;
  *"get-value account"*) echo owner@example.com ;;
  *"print-access-token"*) echo BASE-TOKEN ;;
  *"storage cat"*) printf 'hello' ;;
  *) : ;;
esac
STUB
cat > "$tmp/bin/curl" <<'STUB'
#!/bin/bash
echo "curl $*" >> "$CALLS"; cat > /dev/null; echo '{"access_token":"REDUCED-TOKEN"}'
STUB
chmod +x "$tmp/bin/gcloud" "$tmp/bin/curl"
export CALLS="$log" STATE="$tmp" PATH="$tmp/bin:$PATH"
fail() { echo "FAIL: $*"; exit 1; }
# 1. unfilled: every command refuses, nothing is called
for cmd in setup token verify "delete DELETE-W1-BACKUP"; do
  out=$(bash "$here/backup_only.sh" $cmd 2>&1) && fail "unfilled $cmd ran"; [[ "$out" == *"fill every __FILL value first"* ]] || fail "unfilled message: $out"
done
[ ! -s "$log" ] || fail "a command was issued while unfilled"
filled="$tmp/filled.sh"
sed -e 's/__FILL: owner-project-id__/my-project-123/' -e 's/__FILL: owner-private-bucket__/my-w1-backup-bucket/' "$here/backup_only.sh" > "$filled"
sed 's/__FILL: owner-project-id__/my-project-123/' "$here/backup_only.sh" > "$tmp/half.sh"
out=$(bash "$tmp/half.sh" setup 2>&1) && fail "half-filled ran"; [[ "$out" == *"fill every"* ]] || fail "half-filled message"
sed -e 's/__FILL: owner-project-id__/My_Project/' -e 's/__FILL: owner-private-bucket__/b/' "$here/backup_only.sh" > "$tmp/bad.sh"
out=$(bash "$tmp/bad.sh" setup 2>&1) && fail "bad project ran"; [[ "$out" == *bad_project_id* ]] || fail "bad project message"
[ ! -s "$log" ] || fail "a command was issued before the checks"
# 2. setup: private bucket, one create-only account, no VM, no key, no project role granted
bash "$filled" setup > "$tmp/out" || fail "setup failed: $(cat "$tmp/out")"
grep -q "buckets create gs://my-w1-backup-bucket --location=us-central1 --uniform-bucket-level-access --public-access-prevention" "$log" || fail "bucket creation flags"
grep -q "add-iam-policy-binding gs://my-w1-backup-bucket --member=serviceAccount:w1-backup-writer@my-project-123.iam.gserviceaccount.com --role=roles/storage.objectCreator" "$log" || fail "writer role"
grep -Eq "gcloud (compute|projects add-iam-policy-binding)|keys create|objectAdmin|objectViewer|allUsers|allAuthenticatedUsers" "$log" && fail "forbidden command in setup"
[ "$(grep -c 'roles/' "$log")" = 2 ] || fail "unexpected role grants: $(grep 'roles/' "$log")"
# 3. token: impersonates the writer, boundary = objectCreator under the prefix only; the base token is never printed
: > "$log"; out=$(bash "$filled" token)
[[ "$out" == *REDUCED-TOKEN* && "$out" != *BASE-TOKEN* ]] || fail "token output: $out"
grep -q "print-access-token --impersonate-service-account=w1-backup-writer@my-project-123.iam.gserviceaccount.com" "$log" || fail "impersonation"
grep -q 'inRole:roles/storage.objectCreator' "$log" || fail "boundary role"
grep -Fq 'resource.name.startsWith(\"projects/_/buckets/my-w1-backup-bucket/objects/w1-backup/\")' "$log" || fail "boundary prefix: $(cat "$log")"
grep -q "//storage.googleapis.com/projects/_/buckets/my-w1-backup-bucket" "$log" || fail "boundary resource"
# 4. sha256: a mismatch stops, an identical list passes, a path escape is refused
good=$(printf 'hello' | sha256sum | cut -d' ' -f1)
printf '%s  part_000\n' "$good" > "$tmp/sums"; bash "$filled" sha256 "$tmp/sums" | grep -q "sha256 OK: 1 objects" || fail "sha256 ok"
printf '%s  part_000\n' "$(printf 'other' | sha256sum | cut -d' ' -f1)" > "$tmp/sums"
out=$(bash "$filled" sha256 "$tmp/sums" 2>&1) && fail "mismatch accepted"; [[ "$out" == *"sha256_mismatches:1"* ]] || fail "mismatch message: $out"
printf '%s  ../x\n' "$good" > "$tmp/sums"; out=$(bash "$filled" sha256 "$tmp/sums" 2>&1) && fail "escape accepted"; [[ "$out" == *bad_name* ]] || fail "escape message"
# 5. delete needs the confirmation word, then removes objects, account and bucket and checks
: > "$log"; out=$(bash "$filled" delete 2>&1) && fail "delete without word ran"; [ ! -s "$log" ] || fail "delete issued commands without the word"
bash "$filled" delete DELETE-W1-BACKUP | grep -q "delete OK" || fail "delete"
grep -q "storage rm -r gs://my-w1-backup-bucket/w1-backup" "$log" && grep -q "service-accounts delete w1-backup-writer@" "$log" && grep -q "buckets delete gs://my-w1-backup-bucket" "$log" || fail "delete commands"
out=$(bash "$filled" other 2>&1) && fail "unknown command ran"; [[ "$out" == *usage* ]] || fail "usage"
echo "ALL OK"
