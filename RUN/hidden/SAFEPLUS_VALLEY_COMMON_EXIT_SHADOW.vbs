Option Explicit
Dim shell, command, result
Set shell = CreateObject("WScript.Shell")
command = "cmd.exe /d /c ""C:\stock_bot\RUN\hidden\SAFEPLUS_VALLEY_COMMON_EXIT_SHADOW.cmd"""
result = shell.Run(command, 0, True)
WScript.Quit result