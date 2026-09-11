#!/usr/bin/env bash
#
# install_mac_integration.sh: Install SlideBridge integration for Mac PowerPoint
# 1. Installs SlideBridge.scpt to PowerPoint's Application Scripts folder.
# 2. Compiles standalone SlideBridge-Edit-Active.app.
# 3. Creates macOS Quick Action Service in ~/Library/Services/.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Installing SlideBridge Mac PowerPoint Integration ==="

# 1. PowerPoint Application Scripts folder
PP_SCRIPTS_DIR="$HOME/Library/Application Scripts/com.microsoft.Powerpoint"
mkdir -p "$PP_SCRIPTS_DIR"

echo "1. Compiling SlideBridge.scpt into: $PP_SCRIPTS_DIR"
osacompile -o "$PP_SCRIPTS_DIR/SlideBridge.scpt" "$PROJECT_ROOT/scripts/SlideBridge.applescript"

# 2. Standalone Applet in artifacts/
mkdir -p "$PROJECT_ROOT/artifacts"
echo "2. Compiling standalone applet: $PROJECT_ROOT/artifacts/SlideBridge-Edit-Active.app"
osacompile -o "$PROJECT_ROOT/artifacts/SlideBridge-Edit-Active.app" "$PROJECT_ROOT/scripts/SlideBridge.applescript"

# 3. macOS Services / Quick Action
SERVICES_DIR="$HOME/Library/Services"
mkdir -p "$SERVICES_DIR"
WORKFLOW_DIR="$SERVICES_DIR/在 Origin 編輯 (SlideBridge).workflow"
mkdir -p "$WORKFLOW_DIR/Contents"

echo "3. Creating macOS Quick Action Service: $WORKFLOW_DIR"

cat <<'EOF' > "$WORKFLOW_DIR/Contents/Info.plist"
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
EOF

cat <<'EOF' > "$WORKFLOW_DIR/Contents/document.wflow"
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
				<key>AMAccepts</key>
				<dict>
					<key>Container</key>
					<string>List</string>
					<key>Types</key>
					<array>
						<string>com.apple.applescript.object</string>
					</array>
				</dict>
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
EOF

# Refresh macOS Services cache
/System/Library/CoreServices/pbs -flush || true

echo ""
echo "=== SlideBridge Mac Integration Installed Successfully! ==="
echo "You can now edit charts directly from PowerPoint using any of the following:"
echo "1. Menu: Microsoft PowerPoint -> 服務 (Services) -> 在 Origin 編輯 (SlideBridge)"
echo "2. Keyboard Shortcut: Assign Cmd+Option+O in macOS System Settings -> Keyboard -> Keyboard Shortcuts -> Services"
echo "3. Standalone App: Double-click artifacts/SlideBridge-Edit-Active.app"
echo "4. Terminal: ./scripts/edit_active_presentation.sh"
