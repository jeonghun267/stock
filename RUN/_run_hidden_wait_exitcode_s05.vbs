' S05 hidden synchronous launcher.
' Preserve the child CMD exit code so Task Scheduler restart-on-failure works.
If WScript.Arguments.Count < 1 Then
    WScript.Quit 2
End If

Set sh = CreateObject("WScript.Shell")
rc = sh.Run("cmd /d /c """ & WScript.Arguments(0) & """", 0, True)
WScript.Quit rc
