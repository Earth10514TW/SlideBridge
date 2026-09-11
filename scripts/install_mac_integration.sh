#!/usr/bin/env bash
#
# install_mac_integration.sh: Install SlideBridge integration for Mac PowerPoint & Finder
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Render templates with actual project root
TEMPLATE_EDIT="$PROJECT_ROOT/scripts/SlideBridge.applescript"
TEMPLATE_FIX="$PROJECT_ROOT/scripts/SlideBridgeFix.applescript"
RENDER_DIR="$(mktemp -d -t slidebridge-install)"
trap 'rm -rf "$RENDER_DIR"' EXIT

RENDERED_EDIT="$RENDER_DIR/SlideBridge.applescript"
RENDERED_FIX="$RENDER_DIR/SlideBridgeFix.applescript"

sed "s|__SLIDEBRIDGE_PROJECT_ROOT__|${PROJECT_ROOT}|g" "$TEMPLATE_EDIT" > "$RENDERED_EDIT"
sed "s|__SLIDEBRIDGE_PROJECT_ROOT__|${PROJECT_ROOT}|g" "$TEMPLATE_FIX" > "$RENDERED_FIX"

mkdir -p "$HOME/.slidebridge"
printf '%s\n' "$PROJECT_ROOT" > "$HOME/.slidebridge/project-root"

echo "=== Installing SlideBridge Mac Integration ==="
echo "Project root: $PROJECT_ROOT"

# 1. PowerPoint Application Scripts folder
PP_SCRIPTS_DIR="$HOME/Library/Application Scripts/com.microsoft.Powerpoint"
mkdir -p "$PP_SCRIPTS_DIR"

echo "1. Compiling SlideBridge.scpt into: $PP_SCRIPTS_DIR"
osacompile -o "$PP_SCRIPTS_DIR/SlideBridge.scpt" "$RENDERED_EDIT"

echo "2. Compiling SlideBridgeFix.scpt into: $PP_SCRIPTS_DIR"
osacompile -o "$PP_SCRIPTS_DIR/SlideBridgeFix.scpt" "$RENDERED_FIX"

# 2. Standalone Applet in dist/
mkdir -p "$PROJECT_ROOT/dist"
echo "3. Compiling standalone applet: $PROJECT_ROOT/dist/SlideBridge-Edit-Active.app"
osacompile -o "$PROJECT_ROOT/dist/SlideBridge-Edit-Active.app" "$RENDERED_EDIT"

# 3. macOS Services / Quick Actions
SERVICES_DIR="$HOME/Library/Services"
mkdir -p "$SERVICES_DIR"

# 3A. 在 Origin 編輯 (SlideBridge).workflow
WORKFLOW_EDIT_DIR="$SERVICES_DIR/在 Origin 編輯 (SlideBridge).workflow"
mkdir -p "$WORKFLOW_EDIT_DIR/Contents"
echo "4. Creating PowerPoint Quick Action: $WORKFLOW_EDIT_DIR"

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

# 3B. 修復 PPT 圖片 (SlideBridge).workflow (Finder Quick Action)
WORKFLOW_FIX_DIR="$SERVICES_DIR/修復 PPT 圖片 (SlideBridge).workflow"
mkdir -p "$WORKFLOW_FIX_DIR/Contents"
echo "5. Creating Finder Quick Action: $WORKFLOW_FIX_DIR"

cat <<'PLIST' > "$WORKFLOW_FIX_DIR/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>修復 PPT 圖片 (SlideBridge)</string>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSMenuItem</key>
			<dict>
				<key>default</key>
				<string>修復 PPT 圖片 (SlideBridge)</string>
			</dict>
			<key>NSMessage</key>
			<string>runWorkflowAsService</string>
			<key>NSSendFileTypes</key>
			<array>
				<string>org.openxmlformats.presentationml.presentation</string>
				<string>com.microsoft.powerpoint.pptx</string>
				<string>public.data</string>
			</array>
		</dict>
	</array>
</dict>
</plist>
PLIST

cat <<'WFLOW' > "$WORKFLOW_FIX_DIR/Contents/document.wflow"
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
	set scriptPath to (POSIX path of (path to home folder)) &amp; "Library/Application Scripts/com.microsoft.Powerpoint/SlideBridgeFix.scpt"
	run script (POSIX file scriptPath) with parameters {input, parameters}
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
				<string>E73A6B41-C68C-4BE8-B4C1-4A5964D3F592</string>
				<key>Keywords</key>
				<array>
					<string>Run</string>
				</array>
				<key>OutputUUID</key>
				<string>8FD53B4B-3CA4-428E-8FE1-FEF72B57B2F1</string>
				<key>UUID</key>
				<string>D3B519C1-72B8-4DA5-A8F8-23C6BC50B739</string>
			</dict>
		</dict>
	</array>
	<key>connectors</key>
	<dict/>
	<key>workflowMetaData</key>
	<dict>
		<key>serviceInputTypeIdentifier</key>
		<string>com.apple.Automator.fileSystemObject</string>
		<key>serviceOutputTypeIdentifier</key>
		<string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key>
		<integer>1</integer>
		<key>workflowTypeIdentifier</key>
		<string>com.apple.Automator.servicesMenu</string>
	</dict>
</dict>
</plist>
WFLOW

# 4. Build Native macOS SwiftUI App
echo "6. Building SlideBridge.app..."
bash "$PROJECT_ROOT/scripts/build_mac_app.sh"

# Refresh macOS Services cache
/System/Library/CoreServices/pbs -flush || true

echo ""
echo "=== SlideBridge Mac Integration Installed Successfully! ==="
echo "You can now use SlideBridge with any of the following:"
echo "1. Native Desktop App: dist/SlideBridge.app"
echo "2. Finder Quick Action: Right-click any .pptx -> 快速動作 -> 修復 PPT 圖片 (SlideBridge)"
echo "3. PowerPoint Menu: 服務 (Services) -> 在 Origin 編輯 (SlideBridge)"
echo "4. Keyboard Shortcut: Assign Cmd+Option+O in macOS System Settings -> Keyboard Shortcuts"
echo "5. Terminal: python3 -m slidebridge fix <file.pptx>"
