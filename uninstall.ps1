# Uninstall Laiaudio from Windows. Your meetings (.md) are never deleted.
# install.ps1 copies this script to %LOCALAPPDATA%\Laiaudio, so Settings > Apps can run it.
$ErrorActionPreference = 'Stop'

$Data = Join-Path $env:LOCALAPPDATA 'Laiaudio'
$Config = Join-Path $env:APPDATA 'Laiaudio'

Get-Process Laiaudio, pythonw, python, llama-server -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($Data, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -PassThru | Wait-Process -Timeout 15 -ErrorAction SilentlyContinue  # until its files are free
foreach ($folder in 'app', 'venv', 'python', 'llama.cpp', 'gtk', 'downloads') {
    $path = Join-Path $Data $folder
    if (Test-Path $path) { Remove-Item $path -Recurse -Force }
}
Remove-Item (Join-Path $Data 'laiaudio.ico'), (Join-Path $Data 'app.log') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Programs')) 'Laiaudio.lnk'),
            (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Laiaudio.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Laiaudio' -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'App uninstalled.'

$models = Join-Path $Data 'models'
if (Test-Path $models) {
    $gb = (Get-ChildItem $models -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
    $answer = Read-Host ("Also delete the downloaded models ({0:N1} GB)? [y/N]" -f $gb)
    if ($answer -match '^[yY]$') { Remove-Item $models -Recurse -Force; Write-Host 'Models deleted.' }
}
if (Test-Path $Config) {
    $answer = Read-Host 'Also delete your settings? [y/N]'
    if ($answer -match '^[yY]$') { Remove-Item $Config -Recurse -Force; Write-Host 'Settings deleted.' }
}
# The script itself lives in the folder: remove the folder once nothing else is left in it
Get-ChildItem $Data -Force | Where-Object { $_.Name -ne 'uninstall.ps1' } | Select-Object -First 1 | ForEach-Object { $keep = $true }
if (-not $keep) { Remove-Item $Data -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host 'Your transcripts (.md) were kept.'
Read-Host 'Press Enter to close' | Out-Null
