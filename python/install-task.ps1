# 注册开机自启：优先计划任务，没权限就退回「启动」文件夹（不需要管理员）
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = 'iirose-whale'
$StartScript = Join-Path $Root 'start-bot.ps1'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $StartScript)
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'iirose 鲸鱼娘机器人（iirosebot + AI）' -Force | Out-Null
    Write-Host "已注册计划任务：$TaskName（下次登录自动启动）"
    exit 0
} catch {
    Write-Host "计划任务注册失败（多半是没管理员权限）：$($_.Exception.Message)"
}

# 退路：用户启动文件夹里的一个 cmd，登录时会自己跑
$startup = [Environment]::GetFolderPath('Startup')
$cmdPath = Join-Path $startup 'iirose-whale.cmd'
$cmd = @"
@echo off
powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "$StartScript"
"@
Set-Content -Path $cmdPath -Value $cmd -Encoding ascii
Write-Host "已放入启动文件夹：$cmdPath（下次登录自动启动，不需要管理员）"
