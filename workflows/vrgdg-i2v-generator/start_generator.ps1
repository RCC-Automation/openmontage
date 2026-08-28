$ErrorActionPreference = "Stop"

$generator = Join-Path $PSScriptRoot "generate_vrgdg_i2v_workflows.ps1"
$projectRoot = Read-Host "VRGDG project directory (the folder containing vrgdg_builder_session.json)"
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    throw "A project directory is required."
}

Write-Host ""
Write-Host "1 - one scene"
Write-Host "2 - several selected scenes"
Write-Host "3 - all scenes"
$mode = Read-Host "Choose 1, 2, or 3"
$disableUpscale = (Read-Host "Disable the slow LTX upscale/refine pass? (Y/n)") -notmatch '^(n|no)$'

$parameters = @{
    ProjectRoot = $projectRoot
    DisableUpscale = $disableUpscale
}
switch ($mode) {
    "1" {
        $scene = [int](Read-Host "Scene number")
        $parameters.Scenes = @($scene)
    }
    "2" {
        $text = Read-Host "Scene numbers separated by commas (example: 4,6,9)"
        $scenes = @($text -split ',' | ForEach-Object { [int]$_.Trim() })
        $parameters.Scenes = $scenes
    }
    "3" { $parameters.AllScenes = $true }
    default { throw "Choose 1, 2, or 3." }
}
& $generator @parameters
