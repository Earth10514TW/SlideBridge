-- SlideBridge AppleScript Handler for Microsoft PowerPoint Mac
-- Enables one-click/hotkey editing of Origin charts in Windows Parallels VM.
-- Compatible with AppleScriptTask (VBA) and macOS Shortcuts/Quick Actions.

on run
    editSelectedOriginChart("")
end run

on editSelectedOriginChart(paramStr)
    set projectPath to "/Users/earth/Documents/ChatGPT/SlideBridge"
    set scriptPath to projectPath & "/scripts/edit_active_presentation.sh"
    
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
