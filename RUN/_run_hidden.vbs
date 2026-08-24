' [투명 실행기 2026-06-12] 예약작업 창 안 보이게 — 친구님 지시 "평소에도 안 보이는 게 좋아"
' 사용: wscript.exe //B _run_hidden.vbs <실행할 .cmd 파일 경로>
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count >= 1 Then
    sh.Run "cmd /c """ & WScript.Arguments(0) & """", 0, False
End If
