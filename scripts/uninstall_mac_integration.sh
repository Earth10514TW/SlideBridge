#!/usr/bin/env bash
#
# uninstall_mac_integration.sh: Remove SlideBridge macOS integration services
#
set -euo pipefail

SERVICES_DIR="$HOME/Library/Services"
PP_SCRIPTS_DIR="$HOME/Library/Application Scripts/com.microsoft.Powerpoint"

echo "=== Removing SlideBridge Mac Integration ==="

rm -rf "$SERVICES_DIR/在 Origin 編輯 (SlideBridge).workflow"
rm -rf "$SERVICES_DIR/修復 PPT 圖片 (SlideBridge).workflow"
rm -f "$PP_SCRIPTS_DIR/SlideBridge.scpt"
rm -f "$PP_SCRIPTS_DIR/SlideBridgeFix.scpt"

# Refresh macOS Services cache
/System/Library/CoreServices/pbs -flush || true

echo "✔ 成功移除 SlideBridge 系統整合服務（PowerPoint 服務選單）。"
