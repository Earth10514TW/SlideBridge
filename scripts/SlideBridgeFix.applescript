-- SlideBridge Batch Repair AppleScript Handler
-- Handles files passed from Finder Quick Action or Droplet

on run {input, parameters}
	set projectRoot to resolveProjectRoot()
	if projectRoot is "" then
		display alert "SlideBridge 尚未安裝" message "找不到專案路徑，請先開啟 SlideBridge App 完成配置。" as critical
		return input
	end if

	set fixedCount to 0
	set failList to {}

	repeat with aFile in input
		set posixPath to POSIX path of aFile
		if posixPath ends with ".pptx" or posixPath ends with ".PPTX" then
			set scriptPath to projectRoot & "/scripts/fix_presentation.sh"
			set cmd to quoted form of scriptPath & " " & quoted form of posixPath & " 2>&1"
			try
				set scriptOutput to do shell script cmd
				set fixedCount to fixedCount + 1
			on error errMsg
				set end of failList to (POSIX path of aFile) & ": " & errMsg
			end try
		end if
	end repeat

	if fixedCount > 0 then
		if (count of failList) is 0 then
			display notification ("已成功修復 " & fixedCount & " 份簡報！") with title "SlideBridge" subtitle "產出 <檔名>_fixed.pptx"
		else
			display alert "部分簡報修復失敗" message ("成功：" & fixedCount & " 份\n失敗：" & (count of failList) & " 份") as warning
		end if
	else if (count of failList) > 0 then
		display alert "SlideBridge 修復失敗" message (item 1 of failList) as critical
	else
		display alert "未選取 PPTX 簡報" message "請選取副檔名為 .pptx 的 PowerPoint 檔案。" as informational
	end if

	return input
end run

on resolveProjectRoot()
	try
		set override to system attribute "SLIDEBRIDGE_PROJECT_ROOT"
		if override is not "" then return override
	end try

	set configPath to (POSIX path of (path to home folder)) & ".slidebridge/project-root"
	try
		set recorded to do shell script "cat " & quoted form of configPath & " 2>/dev/null"
		if recorded is not "" then return recorded
	end try

	return "__SLIDEBRIDGE_PROJECT_ROOT__"
end resolveProjectRoot
