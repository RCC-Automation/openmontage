param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [string]$ServerUrl = "http://127.0.0.1:8188",

    [int]$TimeoutSeconds = 7200,

    [switch]$EnableUpscale
)

$ErrorActionPreference = "Stop"
$sessionPath = Join-Path $ProjectRoot "vrgdg_builder_session.json"
if (-not (Test-Path -LiteralPath $sessionPath -PathType Leaf)) {
    throw "VRGDG session was not found: $sessionPath"
}
$roundTrip = Join-Path $PSScriptRoot "run_scene_roundtrip.ps1"
$session = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
$remaining = @()
for ($index = 0; $index -lt @($session.segments).Count; $index++) {
    $segment = $session.segments[$index]
    $videoPath = [string]$segment.video_path
    $complete = ([string]$segment.video_status -eq "done") -and `
        (-not [string]::IsNullOrWhiteSpace($videoPath)) -and `
        (Test-Path -LiteralPath $videoPath -PathType Leaf)
    if (-not $complete) {
        $remaining += ($index + 1)
    }
}

if ($remaining.Count -eq 0) {
    Write-Host "All VRGDG scenes already have completed video files." -ForegroundColor Green
    return
}

Write-Host "Remaining scenes: $($remaining -join ', ')" -ForegroundColor Cyan
foreach ($scene in $remaining) {
    Write-Host ""
    Write-Host "=== Rendering and restoring scene $scene ===" -ForegroundColor Yellow
    $parameters = @{
        ProjectRoot = $ProjectRoot
        Scene = $scene
        ServerUrl = $ServerUrl
        TimeoutSeconds = $TimeoutSeconds
        EnableUpscale = [bool]$EnableUpscale
    }
    & $roundTrip @parameters
    if ($LASTEXITCODE -ne 0) {
        throw "Batch stopped because scene $scene failed. Rerun this command to resume from the first incomplete scene."
    }
}

Write-Host ""
Write-Host "All remaining scene videos were rendered and restored." -ForegroundColor Green
