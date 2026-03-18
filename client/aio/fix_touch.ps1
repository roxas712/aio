# Fix inverted touch axes — disable/re-enable touch device
# Run this in PowerShell as Administrator

$touch = Get-PnpDevice | Where-Object { $_.FriendlyName -like "*touch*" -and $_.Status -eq "OK" }
if ($touch) {
    Write-Host "Found touch device: $($touch.FriendlyName)"
    Write-Host "Disabling..."
    $touch | Disable-PnpDevice -Confirm:$false
    Start-Sleep -Seconds 3
    Write-Host "Re-enabling..."
    $touch | Enable-PnpDevice -Confirm:$false
    Write-Host "Done. Test touch now."
} else {
    Write-Host "No touch device found. Trying broader search..."
    $all = Get-PnpDevice | Where-Object { $_.FriendlyName -like "*HID*" -and $_.Class -eq "HIDClass" -and $_.Status -eq "OK" }
    $all | Format-Table FriendlyName, InstanceId -AutoSize
    Write-Host "If you see a touch device above, run:"
    Write-Host '  Disable-PnpDevice -InstanceId "<InstanceId>" -Confirm:$false'
    Write-Host '  Start-Sleep 3'
    Write-Host '  Enable-PnpDevice -InstanceId "<InstanceId>" -Confirm:$false'
}
