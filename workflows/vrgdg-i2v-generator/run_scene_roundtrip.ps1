param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 100000)]
    [int]$Scene,

    [string]$ServerUrl = "http://127.0.0.1:8188",

    [int]$TimeoutSeconds = 7200,

    [switch]$EnableUpscale
)

$ErrorActionPreference = "Stop"
$generator = Join-Path $PSScriptRoot "generate_vrgdg_i2v_workflows.ps1"
$runner = Join-Path $PSScriptRoot "run_scene_roundtrip.py"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = "python"
}

$generated = & $generator `
    -ProjectRoot $ProjectRoot `
    -Scenes @($Scene) `
    -DisableUpscale:(-not $EnableUpscale)
$workflowFiles = @($generated.GeneratedWorkflowFiles)
if ($workflowFiles.Count -ne 1) {
    throw "Expected one generated workflow for scene $Scene; received $($workflowFiles.Count)."
}

Write-Host "Generated workflow: $($workflowFiles[0])" -ForegroundColor Cyan
Write-Host "Submitting scene $Scene and waiting for unattended restore..." -ForegroundColor Cyan
& $python $runner `
    --project $ProjectRoot `
    --scene $Scene `
    --workflow $workflowFiles[0] `
    --server $ServerUrl `
    --timeout $TimeoutSeconds
if ($LASTEXITCODE -ne 0) {
    throw "The unattended scene round trip failed with exit code $LASTEXITCODE."
}
