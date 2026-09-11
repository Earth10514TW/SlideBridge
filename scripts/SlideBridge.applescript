-- SlideBridge AppleScript Handler for Microsoft PowerPoint Mac
-- Enables one-click/hotkey editing of Origin charts in a Windows VM.
-- Compatible with AppleScriptTask (VBA) and macOS Shortcuts/Quick Actions.
--
-- This file is a TEMPLATE. scripts/install_mac_integration.sh substitutes
-- __SLIDEBRIDGE_PROJECT_ROOT__ with the real checkout path before compiling,
-- so the checked-in copy carries no machine-specific path.
--
-- At run time the project root is resolved in this order:
--   1. the SLIDEBRIDGE_PROJECT_ROOT environment variable, if set;
--   2. ~/.slidebridge/project-root, written by the installer;
--   3. the path baked in at install time.
-- Re-run scripts/install_mac_integration.sh after moving the checkout.

on run
	editSelectedOriginChart("")
end run

on editSelectedOriginChart(paramStr)
	set projectRoot to resolveProjectRoot()
	if projectRoot is "" then
		display alert "SlideBridge 尚未安裝完成" message "找不到專案路徑。請在 SlideBridge 目錄執行：bash scripts/install_mac_integration.sh" as critical
		return "ERROR: project root not found"
	end if

	set scriptPath to projectRoot & "/scripts/edit_active_presentation.sh"

	try
		-- Run the bridge script
		set cmd to quoted form of scriptPath & " 2>&1"
		set scriptOutput to do shell script cmd

		-- Show system notification
		display notification "Origin 圖表已成功同步至 PowerPoint！" with title "SlideBridge" subtitle "更新完成"
		return "SUCCESS"
	on error errMsg
		-- Show user friendly alert
		display alert "SlideBridge 編輯失敗" message errMsg as critical
		return "ERROR: " & errMsg
	end try
end editSelectedOriginChart

on resolveProjectRoot()
	-- 1. Explicit override, useful for testing or unusual layouts.
	try
		set override to system attribute "SLIDEBRIDGE_PROJECT_ROOT"
		if override is not "" then return override
	end try

	-- 2. Path recorded by the installer; survives the repo being moved as long
	--    as the installer is re-run.
	set configPath to (POSIX path of (path to home folder)) & ".slidebridge/project-root"
	try
		set recorded to do shell script "cat " & quoted form of configPath & " 2>/dev/null"
		if recorded is not "" then return recorded
	end try

	-- 3. Path baked in at install time.
	return "__SLIDEBRIDGE_PROJECT_ROOT__"
end resolveProjectRoot
