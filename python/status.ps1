# 看一眼现在什么状态
try {
    $r = Invoke-RestMethod -Uri 'http://127.0.0.1:7790/status' -TimeoutSec 5
    $r | ConvertTo-Json -Depth 5
} catch {
    Write-Host "控制口没响应：$($_.Exception.Message)"
    exit 1
}
