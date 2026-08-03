' [투명 실행기·동기판 2026-07-31] _run_hidden.vbs 와 같지만 마지막 인자만 True = 끝날 때까지 기다림.
' 반복 태스크(IgnoreNew 필요)·감시 대상·전략 LIVE 는 이걸 쓴다. 기존 _run_hidden.vbs(비동기·28개 사용 중)는 불변.
' 사용: wscript.exe //B _run_hidden_wait.vbs <실행할 .cmd 파일 경로>
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count >= 1 Then
    sh.Run "cmd /c """ & WScript.Arguments(0) & """", 0, True
End If
