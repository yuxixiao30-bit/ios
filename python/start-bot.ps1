# 后台启动鲸鱼娘（隐藏窗口，PID 写进 run.pid）
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root 'run.pid'
# 不写死中文路径，避免 PowerShell 5.1 按 ANSI 读脚本时把路径读坏
$Python = Join-Path (Split-Path -Parent $Root) '.venv-py\Scripts\python.exe'

if (Test-Path $PidFile) {
    $old = Get-Content $PidFile -Raw
    if ($old) { $old = $old.Trim() }
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue)) {
        Write-Host "已在运行，PID=$old"
        exit 0
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root 'logs') | Out-Null

$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'

$proc = Start-Process -FilePath $Python `
    -ArgumentList 'run.py' `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Root 'logs\console.out.log') `
    -RedirectStandardError  (Join-Path $Root 'logs\console.err.log') `
    -PassThru

$proc.Id | Set-Content -Path $PidFile -Encoding ascii
Write-Host "已启动，PID=$($proc.Id)；控制口 http://127.0.0.1:7790/status"
