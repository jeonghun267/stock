' [2026-07-21 캡틴 전용] _run_hidden.vbs의 동기(대기) 버전.
' 원본(_run_hidden.vbs)은 sh.Run(...,0,False) - 비동기라 wscript.exe가 cmd/python을
' 놓아버리고 즉시 종료됨. Task Scheduler는 wscript.exe 수명만 추적하므로
' MultipleInstances=IgnoreNew가 실제 python.exe 생존기간 동안 보호를 못 해준다.
' 7/20 캡틴 09:00:01/09:00:02 이중 기동 미스터리의 유력한 원인(친구님 지시, 2026-07-21).
' 이 파일은 캡틴(SAFEPLUS_MFLOW_CAPTAIN_LIVE) 전용 - 골짜기 전용 VBS
' (_run_hidden_sync.vbs)와도 별도 파일. 원본 _run_hidden.vbs는 무접촉(다른 엔진들이
' 계속 씀). 목적은 이중 기동 방지 하나뿐 - RUN_SEC/스케줄/전략/주문 로직 전부 무접촉.
' 사용: wscript.exe //B _run_hidden_captain_sync.vbs <실행할 .cmd 파일 경로>
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count >= 1 Then
    sh.Run "cmd /c """ & WScript.Arguments(0) & """", 0, True
End If
