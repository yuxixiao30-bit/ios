# 停掉后台的鲸鱼娘
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root 'run.pid'

if (-not (Test-Path $PidFile)) {
    Write-Host '没有 run.pid，可能本来就没在跑'
    exit 0
}

$botPid = (Get-Content $PidFile -Raw).Trim()
$proc = Get-Process -Id $botPid -ErrorAction SilentlyContinue
if ($proc) {
    Stop-Process -Id $botPid -Force
    Write-Host "已停止，PID=$botPid"
} else {
    Write-Host "PID=$botPid 已经不在了"
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
