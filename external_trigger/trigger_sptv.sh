#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_OWNER:?Thiếu GITHUB_OWNER}"
: "${GITHUB_REPO:?Thiếu GITHUB_REPO}"
: "${GITHUB_TOKEN:?Thiếu GITHUB_TOKEN}"

curl --fail --silent --show-error --location \
  --request POST \
  --header "Accept: application/vnd.github+json" \
  --header "Authorization: Bearer ${GITHUB_TOKEN}" \
  --header "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/dispatches" \
  --data '{"event_type":"refresh-sptv"}'
