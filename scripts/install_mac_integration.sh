#!/usr/bin/env bash
#
# install_mac_integration.sh: Install SlideBridge integration for Mac PowerPoint
#
# The Finder Quick Action ("修復 PPT 圖片 (SlideBridge)") was removed: the
# SwiftUI app covers batch repair via drag and drop, and Automator's sandbox
# kept breaking the shell handoff (com.apple.provenance). Installing now
# purges any leftover copy from a previous install.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Render templates with actual project root
TEMPLATE_EDIT="$PROJECT_ROOT/scripts/SlideBridge.applescript"
RENDER_DIR="$(mktemp -d -t slidebridge-install)"
trap 'rm -rf "$RENDER_DIR"' EXIT

RENDERED_EDIT="$RENDER_DIR/SlideBridge.applescript"

sed "s|__SLIDEBRIDGE_PROJECT_ROOT__|${PROJECT_ROOT}|g" "$TEMPLATE_EDIT" > "$RENDERED_EDIT"

mkdir -p "$HOME/.slidebridge"
printf '%s\n' "$PROJECT_ROOT" > "$HOME/.slidebridge/project-root"

echo "=== Installing SlideBridge Mac Integration ==="
echo "Project root: $PROJECT_ROOT"

# 0. Check and ensure resvg (pure CLI vector renderer) is installed
echo "Checking SVG renderer (resvg)..."
RESVG_FOUND=false
if command -v resvg >/dev/null 2>&1; then
  RESVG_FOUND=true
  echo "✔ resvg is already available in PATH: $(command -v resvg)"
elif [ -x "/opt/homebrew/bin/resvg" ] || [ -x "/usr/local/bin/resvg" ] || [ -x "$PROJECT_ROOT/bin/resvg" ]; then
  RESVG_FOUND=true
  echo "✔ resvg is already installed."
else
  echo "resvg not found. Attempting automatic installation..."
  if command -v brew >/dev/null 2>&1; then
    echo "Installing resvg via Homebrew..."
    if brew install resvg; then
      RESVG_FOUND=true
      echo "✔ resvg installed successfully via Homebrew."
    fi
  fi
  if [ "$RESVG_FOUND" != "true" ]; then
    echo "Homebrew installation unavailable; downloading prebuilt resvg binary..."
    ARCH="$(uname -m)"
    if [ "$ARCH" = "arm64" ]; then
      ZIP_NAME="resvg-macos-aarch64.zip"
    else
      ZIP_NAME="resvg-macos-x86_64.zip"
    fi
    DOWNLOAD_URL="https://github.com/linebender/resvg/releases/download/v0.48.1/${ZIP_NAME}"
    TEMP_ZIP="$(mktemp -t resvg-dl.XXXXXX).zip"
    mkdir -p "$PROJECT_ROOT/bin"
    if curl -fsSL -o "$TEMP_ZIP" "$DOWNLOAD_URL" && unzip -q -o "$TEMP_ZIP" resvg -d "$PROJECT_ROOT/bin"; then
      chmod +x "$PROJECT_ROOT/bin/resvg"
      xattr -d com.apple.quarantine "$PROJECT_ROOT/bin/resvg" 2>/dev/null || true
      RESVG_FOUND=true
      echo "✔ Downloaded and configured resvg at $PROJECT_ROOT/bin/resvg"
    else
      echo "⚠️ Could not auto-download resvg. You can install it with 'brew install resvg'."
    fi
    rm -f "$TEMP_ZIP"
  fi
fi

# 1. PowerPoint Application Scripts folder
PP_SCRIPTS_DIR="$HOME/Library/Application Scripts/com.microsoft.Powerpoint"
mkdir -p "$PP_SCRIPTS_DIR"

echo "1. Compiling SlideBridge.scpt into: $PP_SCRIPTS_DIR"
osacompile -o "$PP_SCRIPTS_DIR/SlideBridge.scpt" "$RENDERED_EDIT"

# 2. Standalone Applet in dist/
mkdir -p "$PROJECT_ROOT/dist"
echo "2. Compiling standalone applet: $PROJECT_ROOT/dist/SlideBridge-Edit-Active.app"
osacompile -o "$PROJECT_ROOT/dist/SlideBridge-Edit-Active.app" "$RENDERED_EDIT"

# 3. PowerPoint Services menu
SERVICES_DIR="$HOME/Library/Services"
mkdir -p "$SERVICES_DIR"

echo "3. Creating PowerPoint Services item: $SERVICES_DIR/在 Origin 編輯 (SlideBridge).workflow"
WORKFLOW_EDIT_DIR="$SERVICES_DIR/在 Origin 編輯 (SlideBridge).workflow"
mkdir -p "$WORKFLOW_EDIT_DIR/Contents"

# Purge the retired Finder Quick Action from earlier installs
LEGACY_FIX_DIR="$SERVICES_DIR/修復 PPT 圖片 (SlideBridge).workflow"
if [ -d "$LEGACY_FIX_DIR" ]; then
  echo "4. Removing retired Finder Quick Action: $LEGACY_FIX_DIR"
  rm -rf "$LEGACY_FIX_DIR"
fi
rm -f "$PP_SCRIPTS_DIR/SlideBridgeFix.scpt"

cat <<'PLIST' > "$WORKFLOW_EDIT_DIR/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>在 Origin 編輯 (SlideBridge)</string>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSMenuItem</key>
			<dict>
				<key>default</key>
				<string>在 Origin 編輯 (SlideBridge)</string>
			</dict>
			<key>NSMessage</key>
			<string>runWorkflowAsService</string>
			<key>NSRequiredContext</key>
			<dict>
				<key>NSApplicationIdentifier</key>
				<string>com.microsoft.Powerpoint</string>
			</dict>
		</dict>
	</array>
</dict>
</plist>
PLIST

cat <<'WFLOW' > "$WORKFLOW_EDIT_DIR/Contents/document.wflow"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AMApplicationBuild</key>
	<string>523</string>
	<key>AMApplicationVersion</key>
	<string>2.10</string>
	<key>AMDocumentVersion</key>
	<string>2</string>
	<key>actions</key>
	<array>
		<dict>
			<key>action</key>
			<dict>
				<key>AMActionVersion</key>
				<string>1.0.2</string>
				<key>AMApplication</key>
				<array>
					<string>Automator</string>
				</array>
				<key>AMParameterProperties</key>
				<dict>
					<key>source</key>
					<dict/>
				</dict>
				<key>AMProvides</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Types</key>
					<array>
						<string>com.apple.applescript.object</string>
					</array>
				</dict>
				<key>ActionBundlePath</key>
				<string>/System/Library/Automator/Run AppleScript.action</string>
				<key>ActionName</key>
				<string>Run AppleScript</string>
				<key>ActionParameters</key>
				<dict>
					<key>source</key>
					<string>on run {input, parameters}
	set scriptPath to (POSIX path of (path to home folder)) &amp; "Library/Application Scripts/com.microsoft.Powerpoint/SlideBridge.scpt"
	run script (POSIX file scriptPath)
	return input
end run</string>
				</dict>
				<key>BundleIdentifier</key>
				<string>com.apple.Automator.RunScript</string>
				<key>CFBundleVersion</key>
				<string>1.0.2</string>
				<key>Class Name</key>
				<string>RunScriptAction</string>
				<key>InputUUID</key>
				<string>B6E861B5-364F-4DC0-BC5B-01584988F96C</string>
				<key>Keywords</key>
				<array>
					<string>Run</string>
				</array>
				<key>OutputUUID</key>
				<string>29EEB079-F843-4C70-98EB-B66EB77AE78E</string>
				<key>UUID</key>
				<string>95E2B96F-BE44-4BCF-8B53-73DF3A9E256C</string>
			</dict>
		</dict>
	</array>
	<key>connectors</key>
	<dict/>
	<key>workflowMetaData</key>
	<dict>
		<key>serviceApplicationBundleID</key>
		<string>com.microsoft.Powerpoint</string>
		<key>serviceApplicationPath</key>
		<string>/Applications/Microsoft PowerPoint.app</string>
		<key>serviceInputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceOutputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key>
		<integer>0</integer>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>
	</dict>
</dict>
</plist>
WFLOW

# 4. Build Native macOS SwiftUI App
echo "5. Building SlideBridge.app..."
bash "$PROJECT_ROOT/scripts/build_mac_app.sh"

# Refresh macOS Services cache
/System/Library/CoreServices/pbs -flush || true

echo ""
echo "=== SlideBridge Mac Integration Installed Successfully! ==="
echo "You can now use SlideBridge with any of the following:"
echo "1. Native Desktop App: dist/SlideBridge.app (batch repair via drag and drop)"
echo "2. PowerPoint Menu: 服務 (Services) -> 在 Origin 編輯 (SlideBridge)"
echo "3. Keyboard Shortcut: Assign Cmd+Option+O in macOS System Settings -> Keyboard Shortcuts"
echo "4. Terminal: python3 -m slidebridge fix <file.pptx>"
