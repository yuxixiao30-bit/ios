# 注销计划任务
$TaskName = 'iirose-whale'
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已注销：$TaskName"
} catch {
    Write-Host "注销失败或本来就没有：$($_.Exception.Message)"
}
