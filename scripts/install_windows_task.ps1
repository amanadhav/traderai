# install_windows_task.ps1 - schedule the TraderAI morning run on Windows.
#
# Creates a Scheduled Task that runs morning_run.py weekdays at 7:00 AM
# (before US market open in most US time zones - adjust -Time below).
# Replaces the old macOS launchd plists.
#
# Usage (from the repo root, in PowerShell):
#   .\scripts\install_windows_task.ps1            # install / update
#   .\scripts\install_windows_task.ps1 -Remove    # uninstall

param(
    [switch]$Remove,
    [string]$Time = "07:00"
)

$taskName = "TraderAI Morning Run"
$repo = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed task '$taskName'"
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "backend/morning_run.py" `
    -WorkingDirectory $repo

$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At $Time

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName `
    -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Installed '$taskName' - weekdays at $Time"
Write-Host "Output lands in morning_run_log.txt and daily_brief.json in $repo"
Write-Host "Manage it in Task Scheduler, or remove with: .\scripts\install_windows_task.ps1 -Remove"
