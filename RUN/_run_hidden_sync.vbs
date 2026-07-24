' [2026-07-21 골짜기 전용] _run_hidden.vbs의 동기(대기) 버전.
' 원본(_run_hidden.vbs)은 sh.Run(...,0,False) — 비동기라 wscript.exe가 cmd/python을
' 놓아버리고 즉시 종료됨. 그러면 Task Scheduler는 wscript.exe 수명만 추적하므로
' MultipleInstances=IgnoreNew가 실제 python.exe 생존기간 동안 보호를 못 해준다
' (친구님 지적, 2026-07-21 골짜기 장기단일프로세스 전환 작업 중 발견).
' 이 파일은 골짜기(SAFEPLUS_VALLEY_HUNTER_LIVE) 전용 — 다른 엔진(캡틴 등)이 쓰는
' 원본 _run_hidden.vbs는 무접촉(영향범위를 골짜기로 한정).
' 사용: wscript.exe //B _run_hidden_sync.vbs <실행할 .cmd 파일 경로>
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count >= 1 Then
    sh.Run "cmd /c """ & WScript.Arguments(0) & """", 0, True
End If
