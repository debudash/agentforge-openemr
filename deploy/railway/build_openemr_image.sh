#!/usr/bin/env bash
# Build the OpenEMR image Railway runs from a commit of this repository, and push it.
#
#   deploy/railway/build_openemr_image.sh            # HEAD
#   deploy/railway/build_openemr_image.sh <commit>
#
# Railway runs OpenEMR from this image, not the stock openemr/openemr one, so the platform the
# co-pilot module meets on Railway is the code in this repository -- the same 8.2.0-dev the dev
# stack runs. Until 2026-09-25 Railway ran the stock 8.0.0 image, and that version skew broke the
# Week 2 deploy three times (W2_ARCHITECTURE.md, "one codebase, two OpenEMRs").
#
# Upstream's docker/release/Dockerfile is used unchanged: `--build-context openemr-source=...`
# replaces its `openemr-source` stage (a git clone of upstream master) with a `git archive` of the
# commit. Fork-only files the web server should not serve are left out. The module is inside the
# image, so a module change ships by building and deploying a new image.
#
# Publishing is gated: nothing is pushed until you type DEPLOY. Pointing Railway at the pushed
# image is a separate command, printed at the end.
#
# Git Bash on Windows, or any bash with docker buildx.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
IMAGE_REPO=${IMAGE_REPO:-debulearn4ever/openemr-agent}
COMMIT=$(git -C "$REPO_ROOT" rev-parse --short "${1:-HEAD}")

if [[ -z "${1:-}" ]] && [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    echo "Uncommitted changes are not in the image: it is built from commit $COMMIT." >&2
fi

v_part() { git -C "$REPO_ROOT" show "$COMMIT:version.php" | sed -nE "s/^.v_$1 *= *'([^']*)'.*/\1/p"; }
version="$(v_part major).$(v_part minor).$(v_part patch)$(v_part tag)"
TAG="$IMAGE_REPO:$version-$COMMIT"

# The patient dashboard (ADR 0008) is served from public/dashboard/, which is build output and not
# in git. Its OAuth client ID is compiled in, so the client must be registered on the target
# instance first (deploy/railway/README.md, "Patient dashboard").
if [[ -z "${VITE_SMART_CLIENT_ID:-}" ]]; then
    echo "Set VITE_SMART_CLIENT_ID to the target instance's dashboard OAuth client ID." >&2
    exit 1
fi

src=$(mktemp -d)
trap 'rm -rf "$src"' EXIT
mkdir "$src/openemr"
git -C "$REPO_ROOT" archive "$COMMIT" | tar -x -C "$src/openemr"

echo "Building the patient dashboard into public/dashboard/ ..."
(cd "$src/openemr/dashboard" && npm ci --no-audit --no-fund && VITE_SMART_CLIENT_ID="$VITE_SMART_CLIENT_ID" npm run build)
test -f "$src/openemr/public/dashboard/index.html"

# The agent, evals, artifacts, the dashboard's source and write-ups are not OpenEMR and must not
# sit in the web root.
(cd "$src/openemr" && rm -rf copilot artifacts deploy usecases docs .gitlab-ci.yml .coderabbit.yaml \
    Dockerfile.copilot Dockerfile.seeder ALERTS.md ARCHITECTURE.md AUDIT.md COST_ANALYSIS.md \
    ENVIRONMENT.md EVAL_DATASET.md EVAL_GATE.md KEY_METRICS.md SECURITY_TESTS.md USER.md \
    W2_ARCHITECTURE.md W2_COST_LATENCY.md \
    dashboard dashboard-modernization PATIENT_DASHBOARD_MIGRATION.md)

echo "Building $TAG ..."
docker buildx build --platform linux/amd64 --load \
    -f "$REPO_ROOT/docker/release/Dockerfile" \
    --build-context openemr-source="$src" \
    --build-arg OPENEMR_VERSION="$COMMIT" \
    --build-arg IMAGE_VERSION="$version" \
    --build-arg BUILD_DATE="$(date -u +%Y-%m-%d)" \
    -t "$TAG" "$REPO_ROOT/docker/release"

# Prove the image holds this commit's OpenEMR and the module, not upstream's clone.
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh "$TAG" -c '
    cd /var/www/localhost/htdocs/openemr &&
    test -f interface/modules/custom_modules/oe-module-copilot-agent/openemr.bootstrap.php &&
    test ! -e copilot &&
    test -f public/dashboard/index.html &&
    test ! -e dashboard &&
    grep -E "v_(major|minor|patch|tag) " version.php'

echo
read -r -p "Type DEPLOY to push $TAG to Docker Hub, anything else to stop: " answer
if [[ "$answer" != "DEPLOY" ]]; then
    echo "Stopped. The image is built locally and nothing was pushed."
    exit 1
fi
docker push "$TAG"
digest=$(docker inspect --format '{{index .RepoDigests 0}}' "$TAG")

cat <<EOF

Pushed: $digest

Test it locally before Railway (see deploy/railway/README.md, "Building from this checkout"),
then point the service at it -- this redeploys OpenEMR:

  railway service source connect --image "$TAG@${digest#*@}" --service openemr-v82
EOF
