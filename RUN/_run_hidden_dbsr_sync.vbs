' [2026-07-22 DEEP_SIGNAL_REC dedicated] sync (wait) variant of _run_hidden.vbs.
' Original _run_hidden.vbs uses sh.Run(...,0,False) - async, so wscript.exe exits
' immediately and Task Scheduler only tracks the wscript lifetime. Then
' MultipleInstances=IgnoreNew cannot protect the real python.exe lifetime.
' Same fix pattern as _run_hidden_sync.vbs (valley) / _run_hidden_captain_sync.vbs
' (captain, 2026-07-21): one dedicated copy per engine to keep blast radius small.
' This file is for SAFEPLUS_DEEP_SIGNAL_REC only (1-min repetition restart safety
' net added 2026-07-22; engine self-terminates via DBSR_END wall clock 15:10).
' Usage: wscript.exe //B _run_hidden_dbsr_sync.vbs <path to .cmd file>
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count >= 1 Then
    sh.Run "cmd /c """ & WScript.Arguments(0) & """", 0, True
End If
