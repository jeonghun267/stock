Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count < 1 Then
    WScript.Quit 2
End If
exitCode = sh.Run("cmd /c """ & WScript.Arguments(0) & """", 0, True)
WScript.Quit exitCode
