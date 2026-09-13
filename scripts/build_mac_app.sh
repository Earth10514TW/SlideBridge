#!/usr/bin/env bash
#
# build_mac_app.sh: Build the native macOS SwiftUI SlideBridge.app bundle
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_BUNDLE="$PROJECT_ROOT/dist/SlideBridge.app"
CONTENTS="$APP_BUNDLE/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

echo "=== Building SlideBridge.app (macOS SwiftUI Native) ==="
echo "Project Root: $PROJECT_ROOT"
echo "Target: $APP_BUNDLE"

mkdir -p "$(dirname "$APP_BUNDLE")"
rm -rf "$APP_BUNDLE"
mkdir -p "$MACOS" "$RESOURCES"

# 1. Info.plist
cat << 'PLIST' > "$CONTENTS/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>zh_TW</string>
	<key>CFBundleDisplayName</key>
	<string>SlideBridge</string>
	<key>CFBundleExecutable</key>
	<string>SlideBridge</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>CFBundleIdentifier</key>
	<string>com.slidebridge.desktop</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>SlideBridge</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>0.1.0</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>LSMinimumSystemVersion</key>
	<string>13.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSHumanReadableCopyright</key>
	<string>Copyright © 2026 SlideBridge Open Source. All rights reserved.</string>
	<key>CFBundleDocumentTypes</key>
	<array>
		<dict>
			<key>CFBundleTypeExtensions</key>
			<array>
				<string>pptx</string>
			</array>
			<key>CFBundleTypeName</key>
			<string>Microsoft PowerPoint Presentation</string>
			<key>CFBundleTypeRole</key>
			<string>Editor</string>
			<key>LSHandlerRank</key>
			<string>Alternate</string>
		</dict>
	</array>
</dict>
</plist>
PLIST

echo "APPL????" > "$CONTENTS/PkgInfo"

# 2. Compile Swift Sources
echo "Compiling Swift Sources..."
SDK_PATH="$(xcrun --show-sdk-path --sdk macosx)"

swiftc -parse-as-library \
  -O \
  -target arm64-apple-macosx13.0 \
  -sdk "$SDK_PATH" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Models/Models.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Utilities/Localization.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Utilities/BridgeProcess.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Utilities/PPTAlertInterceptor.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/ViewModels/ViewModels.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Views/BatchRepairView.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Views/OriginEditView.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Views/DoctorView.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Views/OnboardingView.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/Views/ContentView.swift" \
  "$PROJECT_ROOT/mac/SlideBridgeApp/App.swift" \
  -o "$MACOS/SlideBridge"

# 3. Copy AppIcon.icns into Resources
if [ -f "$PROJECT_ROOT/mac/SlideBridgeApp/Resources/AppIcon.icns" ]; then
  cp "$PROJECT_ROOT/mac/SlideBridgeApp/Resources/AppIcon.icns" "$RESOURCES/AppIcon.icns"
fi

# 4. Embed Project Root marker so the App always locates the engine
mkdir -p "$HOME/.slidebridge"
printf '%s\n' "$PROJECT_ROOT" > "$HOME/.slidebridge/project-root"

# 5. Ad-hoc code sign bundle
dot_clean "$APP_BUNDLE" 2>/dev/null || true
xattr -cr "$APP_BUNDLE" 2>/dev/null || true
xattr -c "$APP_BUNDLE" 2>/dev/null || true
xattr -d com.apple.FinderInfo "$APP_BUNDLE" 2>/dev/null || true
codesign --force --deep --sign - "$APP_BUNDLE"

echo "✔ Build complete: $APP_BUNDLE"
ls -lh "$MACOS/SlideBridge"
