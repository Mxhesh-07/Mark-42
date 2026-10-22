# Tier 2 E4 - code signing for the Windows build.
#
# Requires a code-signing certificate installed in the current user's
# certificate store (or a .pfx). Nothing here invents a certificate: without
# one the script exits non-zero and the build stays visibly unsigned.
#
# Usage:
#   $env:JARVIS_CERT_SHA1 = "ABCDEF..."     # thumbprint, from certmgr
#   powershell -ExecutionPolicy Bypass -File packaging\sign_windows.ps1
#
# Optional:
#   $env:JARVIS_SIGNTOOL   path to signtool.exe (defaults to the Windows SDK)
#   $env:JARVIS_TIMESTAMP  RFC3161 URL (defaults to DigiCert)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$targets = @()
$exe = Join-Path $repo "dist\JARVIS\JARVIS.exe"
if (Test-Path $exe) { $targets += $exe }
Get-ChildItem (Join-Path $repo "dist\installer") -Filter "*.exe" -ErrorAction SilentlyContinue |
    ForEach-Object { $targets += $_.FullName }

if ($targets.Count -eq 0) {
    Write-Error "nothing to sign: build dist\JARVIS first (see docs/REPRODUCIBLE.md)"
    exit 2
}

$thumb = $env:JARVIS_CERT_SHA1
if (-not $thumb) {
    Write-Error "JARVIS_CERT_SHA1 is not set; refusing to report an unsigned build as signed"
    exit 2
}

$signtool = $env:JARVIS_SIGNTOOL
if (-not $signtool) {
    $candidates = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse `
        -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "x64" } |
        Sort-Object FullName -Descending
    if ($candidates) { $signtool = $candidates[0].FullName }
}
if (-not $signtool -or -not (Test-Path $signtool)) {
    Write-Error "signtool.exe not found; install the Windows SDK or set JARVIS_SIGNTOOL"
    exit 2
}

$timestamp = $env:JARVIS_TIMESTAMP
if (-not $timestamp) { $timestamp = "http://timestamp.digicert.com" }

foreach ($target in $targets) {
    Write-Host "[sign] $target"
    & $signtool sign /sha1 $thumb /fd SHA256 /tr $timestamp /td SHA256 $target
    if ($LASTEXITCODE -ne 0) {
        Write-Error "signing failed for $target"
        exit $LASTEXITCODE
    }
    & $signtool verify /pa /v $target
    if ($LASTEXITCODE -ne 0) {
        Write-Error "signature verification failed for $target"
        exit $LASTEXITCODE
    }
}

Write-Host "[sign] ok - $($targets.Count) file(s) signed and verified"
