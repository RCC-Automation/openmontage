param(
    [Parameter(Mandatory = $true)]
    [string]$WorkflowDirectory
)

$ErrorActionPreference = "Stop"
$WorkflowDirectory = [System.IO.Path]::GetFullPath($WorkflowDirectory)
if (-not (Test-Path -LiteralPath $WorkflowDirectory -PathType Container)) {
    throw "Workflow directory not found: $WorkflowDirectory"
}

$files = @(Get-ChildItem -LiteralPath $WorkflowDirectory -Filter "i2v_scene_*_tiled.json" -File)
if ($files.Count -eq 0) {
    throw "No generated scene workflows found in $WorkflowDirectory"
}

$errors = @()
foreach ($file in $files) {
    try {
        $workflow = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        $match = [regex]::Match($file.Name, "scene_(\d+)")
        $sceneNumber = [int]$match.Groups[1].Value
        if ($workflow.'936'.class_type -ne "VAEDecodeTiled") { $errors += "$($file.Name): decoder is not tiled" }
        if ([int]$workflow.'936'.inputs.tile_size -gt 256) { $errors += "$($file.Name): tile size exceeds 256" }
        if ($workflow.'936'.inputs.vae[0] -ne "271:256") { $errors += "$($file.Name): missing video VAE link" }
        if ([int]$workflow.'929'.inputs.value -ne ($sceneNumber - 1)) { $errors += "$($file.Name): wrong image index" }
        if ([int]$workflow.'930'.inputs.value -ne $sceneNumber) { $errors += "$($file.Name): wrong scene selector" }
        if (-not $workflow.'273'.inputs.images) { $errors += "$($file.Name): saver has no image input" }
        if (-not $workflow.'273'.inputs.audio) { $errors += "$($file.Name): saver has no audio input" }
    } catch {
        $errors += "$($file.Name): $($_.Exception.Message)"
    }
}

if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_ }
    throw "$($errors.Count) validation error(s)."
}

[pscustomobject]@{
    Directory = $WorkflowDirectory
    Workflows = $files.Count
    Result = "valid"
}
