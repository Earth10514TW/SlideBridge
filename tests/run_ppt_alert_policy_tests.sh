#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="$(mktemp -d -t slidebridge-ppt-alert-policy)"
TEST_BIN="$TEST_DIR/runner"
trap 'rm -rf "$TEST_DIR"' EXIT

swiftc -parse-as-library \
  "$ROOT_DIR/mac/SlideBridgeApp/Utilities/PPTAlertInterceptor.swift" \
  "$ROOT_DIR/tests/PPTAlertPolicyRegression.swift" \
  -o "$TEST_BIN"
"$TEST_BIN"
