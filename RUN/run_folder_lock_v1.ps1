# run_folder_lock_v1.ps1  (ASCII only)
# Purpose: block import hijacking. UserK must not be able to add or modify
#          .py files under C:\stock_bot\RUN, because RUN is sys.path[0].
# Owner of RUN is BUILTIN\Administrators, so UserK cannot undo a lock.
# The broker runs elevated (Administrators = FullControl) and is unaffected.
# Python silently skips __pycache__ writes when the folder is read-only.
#
# Usage (elevated PowerShell):
#   powershell -ExecutionPolicy Bypass -File C:\stock_bot\RUN\run_folder_lock_v1.ps1 -Mode Lock
#   powershell -ExecutionPolicy Bypass -File C:\stock_bot\RUN\run_folder_lock_v1.ps1 -Mode Unlock
#   powershell -ExecutionPolicy Bypass -File C:\stock_bot\RUN\run_folder_lock_v1.ps1 -Mode Status
#
# Full rollback (elevated), using the backup taken 2026-08-10:
#   icacls "C:\stock_bot" /restore "C:\stock_bot\config\acl_backup_RUN_20260810.txt"

param([ValidateSet('Lock','Unlock','Status')][string]$Mode = 'Status')

$Target = 'C:\stock_bot\RUN'
$Acct   = 'WIN10-01\UserK'

$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = New-Object Security.Principal.WindowsPrincipal($id)
$isAdmin = $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Output ("user    : " + $id.Name)
Write-Output ("elevated: " + $isAdmin)
Write-Output ("mode    : " + $Mode)
Write-Output ""

if ($Mode -ne 'Status' -and -not $isAdmin) {
    Write-Output "ERROR: Lock/Unlock requires an elevated PowerShell. Nothing changed."
    exit 1
}

if ($Mode -eq 'Lock') {
    icacls $Target /inheritance:d | Out-Null
    icacls $Target /remove:g $Acct | Out-Null
    icacls $Target /grant ("{0}:(OI)(CI)(RX)" -f $Acct) | Out-Null
}
elseif ($Mode -eq 'Unlock') {
    icacls $Target /remove:g $Acct | Out-Null
    icacls $Target /grant ("{0}:(OI)(CI)(M)" -f $Acct) | Out-Null
}

Write-Output "--- ACL now ---"
icacls $Target
