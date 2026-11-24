# Install Laiaudio on Windows 11: a private Python with the engine, llama.cpp, the native app (built here with a
# private .NET SDK) and its shortcuts. AI models are downloaded from inside the app the first time you open it.
# Run it again to update (for example after downloading a new version). Double-click install.cmd to run it.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Windows PowerShell 5.1 downloads are very slow with a progress bar

$PythonVersion = '3.14.10'       # official CPython from NuGet: no installer, no PATH changes
$LlamaCppRelease = 'b12098'      # official llama.cpp build with Vulkan (same release as install.sh)
$DotnetSdkVersion = '10.0.404'   # .NET 10 LTS, only to build the app (winui/Laiaudio.csproj pins Windows App SDK)

$Repo = $PSScriptRoot
$Data = Join-Path $env:LOCALAPPDATA 'Laiaudio'
$Venv = Join-Path $Data 'venv'
$Temp = Join-Path $Data 'downloads'
$App = Join-Path $Data 'app'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Laiaudio.lnk'
$Desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Laiaudio.lnk'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Laiaudio'

function Say($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# External programs are judged by their exit code: Windows PowerShell 5.1 turns any line they write to stderr
# (a pip warning, for example) into an error when $ErrorActionPreference is Stop
function Run([string]$exe, [string[]]$arguments) {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { throw "$exe is missing" }
    $ErrorActionPreference = 'Continue'
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$exe failed (exit code $LASTEXITCODE)" }
}

function Quietly([string]$exe, [string[]]$arguments) {
    $ErrorActionPreference = 'Continue'
    & $exe @arguments *> $null
    $LASTEXITCODE -eq 0
}

function Fetch([string]$url, [string]$file) {
    Run 'curl.exe' @('-fL', '--retry', '3', '--progress-bar', '-o', $file, $url)
}

function Installed([string]$folder, [string]$version) {
    $marker = Join-Path $folder '.laiaudio-version'
    (Test-Path $marker) -and ((Get-Content $marker -Raw).Trim() -eq $version)
}

function Mark([string]$folder, [string]$version) {
    Set-Content -Path (Join-Path $folder '.laiaudio-version') -Value $version -Encoding ASCII
}

function Fresh([string]$folder) {
    if (Test-Path $folder) { Remove-Item $folder -Recurse -Force }
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
}

if ([Environment]::OSVersion.Version.Build -lt 22000) {
    Write-Host 'Laiaudio needs Windows 11.' -ForegroundColor Red
    exit 1
}
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    Write-Host 'Laiaudio needs a 64-bit Intel or AMD processor (x64).' -ForegroundColor Red
    exit 1
}
New-Item -ItemType Directory -Path $Data, $Temp -Force | Out-Null

# An open Laiaudio keeps its files in use: close it before updating them
Get-Process Laiaudio, pythonw, python, llama-server -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($Data, [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -PassThru | Wait-Process -Timeout 15 -ErrorAction SilentlyContinue  # until its files are free

Say 'Microsoft Visual C++ runtime'
$vc = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64' -ErrorAction SilentlyContinue
if ($vc -and $vc.Installed -eq 1) {
    Write-Host '  already installed'
} else {
    Write-Host '  installing (Windows asks for permission)'
    $redist = Join-Path $Temp 'vc_redist.x64.exe'
    Fetch 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $redist
    $p = Start-Process $redist -ArgumentList '/install', '/quiet', '/norestart' -Verb RunAs -Wait -PassThru
    if ($p.ExitCode -notin 0, 1638, 3010) { throw "Visual C++ runtime setup failed (exit code $($p.ExitCode))" }
}

Say "Python $PythonVersion"
$Python = Join-Path $Data 'python'
if (Installed $Python $PythonVersion) {
    Write-Host '  already installed'
} else {
    $package = Join-Path $Temp 'python.zip'
    Fetch "https://api.nuget.org/v3-flatcontainer/python/$PythonVersion/python.$PythonVersion.nupkg" $package
    $unpacked = Join-Path $Temp 'python'
    Fresh $unpacked
    Run 'tar.exe' @('-xf', $package, '-C', $unpacked, 'tools')
    if (Test-Path $Python) { Remove-Item $Python -Recurse -Force }
    Move-Item (Join-Path $unpacked 'tools') $Python
    Mark $Python $PythonVersion
    if (Test-Path $Venv) { Remove-Item $Venv -Recurse -Force }  # a venv belongs to one Python version
}

# Earlier Windows builds drew the window with GTK; the native app does not need that runtime anymore
$Gtk = Join-Path $Data 'gtk'
if (Test-Path $Gtk) { Remove-Item $Gtk -Recurse -Force }

Say "llama.cpp $LlamaCppRelease (Vulkan), for the translation AI"
$Llama = Join-Path $Data 'llama.cpp'
if (Installed $Llama $LlamaCppRelease) {
    Write-Host '  already installed'
} else {
    $zip = Join-Path $Temp 'llama.zip'
    Fetch "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaCppRelease/llama-$LlamaCppRelease-bin-win-vulkan-x64.zip" $zip
    Fresh $Llama
    Run 'tar.exe' @('-xf', $zip, '-C', $Llama)
    Mark $Llama $LlamaCppRelease
}

Say 'Python environment'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Run (Join-Path $Python 'python.exe') @('-m', 'venv', $Venv)
}
Run $VenvPython @('-m', 'pip', 'install', '-q', '--upgrade', 'pip')
Quietly $VenvPython @('-m', 'pip', 'uninstall', '-q', '-y', 'PyGObject', 'pycairo') | Out-Null  # from the GTK version
$nvidia = (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) -and (Quietly 'nvidia-smi.exe' @('-L'))
if ($nvidia) {
    Write-Host 'NVIDIA GPU detected: transcription will use CUDA'
    Quietly $VenvPython @('-m', 'pip', 'uninstall', '-q', '-y', 'onnxruntime') | Out-Null
    $extra = 'nvidia'
} else {
    Write-Host 'No NVIDIA GPU: transcription will use the CPU (Parakeet v2 Lite)'
    Quietly $VenvPython @('-m', 'pip', 'uninstall', '-q', '-y', 'onnxruntime-gpu') | Out-Null
    $extra = 'cpu'
}
# Build from a local copy: pip and dotnet cannot build from a network path such as \\wsl.localhost
$source = Join-Path $Temp 'source'
Fresh $source
Copy-Item (Join-Path $Repo 'pyproject.toml'), (Join-Path $Repo 'README.md'), (Join-Path $Repo 'LICENSE') $source
Copy-Item (Join-Path $Repo 'laiaudio'), (Join-Path $Repo 'winui') $source -Recurse
Get-ChildItem $source -Recurse -Directory | Where-Object { $_.Name -in '__pycache__', 'bin', 'obj' } |
    Remove-Item -Recurse -Force
Run $VenvPython @('-m', 'pip', 'install', '-q', '--upgrade', "$source[$extra]")

Say "Laiaudio (WinUI 3), built with the .NET SDK $DotnetSdkVersion"
# The SDK and the build packages (~2 GB unpacked) live in the downloads folder, deleted at the end: only the app stays
$Dotnet = Join-Path $Temp 'dotnet'
Fresh $Dotnet
$script = Join-Path $Temp 'dotnet-install.ps1'
Fetch 'https://dot.net/v1/dotnet-install.ps1' $script
Run 'powershell.exe' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script, '-Version', $DotnetSdkVersion,
                       '-InstallDir', $Dotnet, '-NoPath')
# Everything the build writes stays in that folder, and .NET sends no telemetry
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_NOLOGO = '1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
$env:DOTNET_CLI_HOME = $Temp
$env:NUGET_PACKAGES = Join-Path $Temp 'nuget'
if (Test-Path $App) { Remove-Item $App -Recurse -Force }
Run (Join-Path $Dotnet 'dotnet.exe') @('publish', (Join-Path $source 'winui\Laiaudio.csproj'), '-c', 'Release',
                                       '-p:Platform=x64', '-p:UseSharedCompilation=false', '-nodeReuse:false',
                                       '-o', $App, '-v:q', '-nologo')
Quietly (Join-Path $Dotnet 'dotnet.exe') @('build-server', 'shutdown') | Out-Null  # frees the downloads folder

Say 'Shortcuts and Apps list'
$icon = Join-Path $Data 'laiaudio.ico'
Copy-Item (Join-Path $Repo 'laiaudio\data\laiaudio.ico') $icon -Force  # for the Apps list
Copy-Item (Join-Path $Repo 'uninstall.ps1') (Join-Path $Data 'uninstall.ps1') -Force
$shell = New-Object -ComObject WScript.Shell
foreach ($path in $StartMenu, $Desktop) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = Join-Path $App 'Laiaudio.exe'
    $link.Arguments = ''
    $link.WorkingDirectory = $Data
    $link.IconLocation = Join-Path $App 'Laiaudio.exe'
    $link.Description = 'Live meeting captions with local AI'
    $link.Save()
}
New-Item -Path $UninstallKey -Force | Out-Null
$version = (Select-String -Path (Join-Path $Repo 'pyproject.toml') -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
$entry = @{
    DisplayName = 'Laiaudio'; DisplayVersion = $version; Publisher = 'Paolium'; DisplayIcon = $icon
    InstallLocation = $Data; URLInfoAbout = 'https://github.com/Paolium/laiaudio'
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $Data 'uninstall.ps1')`""
}
foreach ($name in $entry.Keys) { Set-ItemProperty -Path $UninstallKey -Name $name -Value $entry[$name] }
Set-ItemProperty -Path $UninstallKey -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $UninstallKey -Name NoRepair -Value 1 -Type DWord

Remove-Item $Temp -Recurse -Force -ErrorAction SilentlyContinue

Say 'Done'
Write-Host 'Open Laiaudio from the Start menu or the desktop shortcut.'
Write-Host 'The first time, it offers to download the transcription model.'
