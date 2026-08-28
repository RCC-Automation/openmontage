[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot,

    [string]$VrgdgRoot,

    [Alias("Scene", "SceneNumbers")]
    [int[]]$Scenes,

    [switch]$AllScenes,

    [string]$OutputDirectory,
    [switch]$DisableUpscale,
    [int]$TileSize = 256,
    [int]$Overlap = 64,
    [int]$TemporalSize = 32,
    [int]$TemporalOverlap = 16
)

$ErrorActionPreference = "Stop"

function Set-NodeInput {
    param(
        [Parameter(Mandatory = $true)]$Workflow,
        [Parameter(Mandatory = $true)][string]$NodeId,
        [Parameter(Mandatory = $true)][string]$InputName,
        [Parameter(Mandatory = $true)]$Value
    )

    $nodeProperty = $Workflow.PSObject.Properties[$NodeId]
    if ($null -eq $nodeProperty) {
        throw "Required node '$NodeId' was not found in the VRGDG base workflow."
    }

    $inputProperty = $nodeProperty.Value.inputs.PSObject.Properties[$InputName]
    if ($null -eq $inputProperty) {
        $nodeProperty.Value.inputs | Add-Member -NotePropertyName $InputName -NotePropertyValue $Value
    } else {
        $inputProperty.Value = $Value
    }
}

function Format-SrtTime {
    param([double]$Seconds)

    $milliseconds = [math]::Max(0, [math]::Round($Seconds * 1000))
    $hours = [math]::Floor($milliseconds / 3600000)
    $milliseconds -= $hours * 3600000
    $minutes = [math]::Floor($milliseconds / 60000)
    $milliseconds -= $minutes * 60000
    $secs = [math]::Floor($milliseconds / 1000)
    $milliseconds -= $secs * 1000
    return "{0:00}:{1:00}:{2:00},{3:000}" -f $hours, $minutes, $secs, $milliseconds
}

function ConvertTo-FileSlug {
    param(
        [string]$Text,
        [int]$MaximumLength = 48
    )

    $slug = ([string]$Text).Trim().ToLowerInvariant()
    $slug = [regex]::Replace($slug, "[^\p{L}\p{Nd}]+", "-").Trim("-")
    if ($slug.Length -gt $MaximumLength) {
        $slug = $slug.Substring(0, $MaximumLength).TrimEnd("-")
    }
    return $slug
}

function Get-EffectiveSettings {
    param($GlobalSettings, $Scene)

    $effective = $GlobalSettings | ConvertTo-Json -Depth 30 | ConvertFrom-Json
    if ($Scene.use_scene_i2v_video_settings -and $null -ne $Scene.i2v_video_settings) {
        foreach ($property in $Scene.i2v_video_settings.PSObject.Properties) {
            if ($null -eq $property.Value) { continue }
            $existing = $effective.PSObject.Properties[$property.Name]
            if ($null -eq $existing) {
                $effective | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value
            } else {
                $existing.Value = $property.Value
            }
        }
    }
    return $effective
}

function Find-VrgdgRoot {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes\comfyui-vrgamedevgirl"),
        (Join-Path $env:LOCALAPPDATA "ComfyUI\custom_nodes\comfyui-vrgamedevgirl")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return $candidate
        }
    }
    throw "Could not locate comfyui-vrgamedevgirl automatically. Pass -VrgdgRoot with its custom-node directory."
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$VrgdgRoot = if ([string]::IsNullOrWhiteSpace($VrgdgRoot)) { Find-VrgdgRoot } else { [System.IO.Path]::GetFullPath($VrgdgRoot) }
$sessionPath = Join-Path $ProjectRoot "vrgdg_builder_session.json"
$baseWorkflowPath = Join-Path $VrgdgRoot "Workflows\UsedForUIDoNotTouch\Singlei2vForUI_API.json"
$outputDirectory = if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    Join-Path $ProjectRoot "workflows\generated_i2v_tiled"
} else {
    [System.IO.Path]::GetFullPath($OutputDirectory)
}
$srtPath = Join-Path $outputDirectory "all_project_scenes.srt"

if (-not (Test-Path -LiteralPath $sessionPath -PathType Leaf)) {
    throw "VRGDG session not found: $sessionPath"
}
if (-not (Test-Path -LiteralPath $baseWorkflowPath -PathType Leaf)) {
    throw "VRGDG base API workflow not found: $baseWorkflowPath"
}

$session = Get-Content -LiteralPath $sessionPath -Raw | ConvertFrom-Json
$baseWorkflow = Get-Content -LiteralPath $baseWorkflowPath -Raw | ConvertFrom-Json
$projectScenes = @($session.segments)
if ($projectScenes.Count -eq 0) {
    throw "No scenes were found in $sessionPath"
}

if ($AllScenes -and $Scenes.Count -gt 0) {
    throw "Use either -Scenes (or -Scene) or -AllScenes, not both."
}
if (-not $AllScenes -and $Scenes.Count -eq 0) {
    throw "Select one or more scenes with -Scene 7 / -Scenes 4,6,9, or select everything with -AllScenes."
}
if ($AllScenes) {
    $selectedScenes = @(1..$projectScenes.Count)
} else {
    $selectedScenes = @($Scenes | Sort-Object -Unique)
}

foreach ($sceneNumber in $selectedScenes) {
    if ($sceneNumber -lt 1 -or $sceneNumber -gt $projectScenes.Count) {
        throw "Scene $sceneNumber is outside the available range 1..$($projectScenes.Count)."
    }
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

$srtBlocks = for ($index = 0; $index -lt $projectScenes.Count; $index++) {
    $scene = $projectScenes[$index]
    $start = Format-SrtTime ([double]$scene.start)
    $end = Format-SrtTime ([double]$scene.end)
    "{0}`r`n{1} --> {2}`r`nScene {0}" -f ($index + 1), $start, $end
}
[System.IO.File]::WriteAllText($srtPath, ($srtBlocks -join "`r`n`r`n") + "`r`n", [System.Text.UTF8Encoding]::new($false))

$settings = $session.i2v_video_settings
$audioPath = [string]$session.audio_path
$outputBaseName = (Split-Path $ProjectRoot -Leaf) + "\image_to_video_clips"

if ([string]::IsNullOrWhiteSpace($audioPath) -or -not (Test-Path -LiteralPath $audioPath -PathType Leaf)) {
    throw "Project audio file was not found: $audioPath"
}
if ($null -eq $settings) {
    throw "The project has no i2v_video_settings block and is not a compatible VRGDG I2V Builder project."
}
if (-not $settings.use_gguf_model) {
    throw "This generator currently supports VRGDG projects configured for the GGUF LTX model. This project uses the non-GGUF workflow variant."
}

$generated = @()
foreach ($sceneNumber in $selectedScenes) {
    $scene = $projectScenes[$sceneNumber - 1]
    $sceneSettings = Get-EffectiveSettings $settings $scene
    $workflow = $baseWorkflow | ConvertTo-Json -Depth 100 | ConvertFrom-Json

    $descriptionSource = [string]$scene.label
    if ([string]::IsNullOrWhiteSpace($descriptionSource) -or $descriptionSource -match '^scene\s*\d+$') {
        $descriptionSource = [string]$scene.story_beat
    }
    if ([string]::IsNullOrWhiteSpace($descriptionSource)) {
        $descriptionSource = [string]$scene.i2v_prompt
    }
    $sceneSlug = ConvertTo-FileSlug $descriptionSource
    $sceneBaseName = "scene_{0:0000}" -f $sceneNumber
    if (-not [string]::IsNullOrWhiteSpace($sceneSlug)) {
        $sceneBaseName += "_$sceneSlug"
    }

    # AMD/ROCm workaround: use small spatial tiles for the LTX video VAE.
    $decoder = $workflow.PSObject.Properties["936"].Value
    $decoder.class_type = "VAEDecodeTiled"
    $decoder._meta.title = "VAE Decode Tiled (AMD safe)"
    Set-NodeInput $workflow "936" "tile_size" $TileSize
    Set-NodeInput $workflow "936" "overlap" $Overlap
    Set-NodeInput $workflow "936" "temporal_size" $TemporalSize
    Set-NodeInput $workflow "936" "temporal_overlap" $TemporalOverlap

    # Project and scene-specific inputs.
    $sceneImagePath = [string]$scene.custom_image_path
    $imageFolder = if (-not [string]::IsNullOrWhiteSpace($sceneImagePath) -and (Test-Path -LiteralPath $sceneImagePath -PathType Leaf)) {
        [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($sceneImagePath))
    } else {
        Join-Path $ProjectRoot "openmontage_recast"
    }
    if (-not (Test-Path -LiteralPath $imageFolder -PathType Container)) {
        throw "Scene $sceneNumber image folder was not found: $imageFolder"
    }
    Set-NodeInput $workflow "925" "folder_path" $imageFolder
    Set-NodeInput $workflow "929" "value" ($sceneNumber - 1)
    Set-NodeInput $workflow "930" "value" $sceneNumber
    Set-NodeInput $workflow "933" "text" ([string]$scene.i2v_prompt)
    Set-NodeInput $workflow "935" "value" $srtPath
    Set-NodeInput $workflow "927" "audio_file" $audioPath
    Set-NodeInput $workflow "437" "value" $outputBaseName
    Set-NodeInput $workflow "634" "base_name" $sceneBaseName

    # Global VRGDG render settings saved with the project.
    Set-NodeInput $workflow "736:425" "value" ([int]$sceneSettings.width)
    Set-NodeInput $workflow "736:426" "value" ([int]$sceneSettings.height)
    Set-NodeInput $workflow "736:424" "value" ([int]$sceneSettings.fps)
    Set-NodeInput $workflow "736:449" "value" ([long]$sceneSettings.seed)
    Set-NodeInput $workflow "181" "frame_rate" ([int]$sceneSettings.fps)
    Set-NodeInput $workflow "218:287" "enable_auto_queue" $false
    Set-NodeInput $workflow "218:287" "tail_loss_frames" ([int]$sceneSettings.tail_loss_frames)
    Set-NodeInput $workflow "218:287" "pre_frames" ([int]$sceneSettings.pre_frames)
    Set-NodeInput $workflow "218:287" "overwrite_mode" "backup"

    # Carry the Builder's two-pass sampler configuration into the standalone graph.
    Set-NodeInput $workflow "218:186" "sampler_name" ([string]$sceneSettings.pass1_sampler_name)
    Set-NodeInput $workflow "218:209" "sigmas" ([string]$sceneSettings.pass1_sigmas)
    Set-NodeInput $workflow "218:222" "strength" ([double]$sceneSettings.pass1_inplace_strength)
    Set-NodeInput $workflow "218:222" "bypass" ([bool]$sceneSettings.pass1_inplace_bypass)
    Set-NodeInput $workflow "219:187" "sampler_name" ([string]$sceneSettings.pass2_sampler_name)
    Set-NodeInput $workflow "219:208" "sigmas" $(if ($DisableUpscale) { "0.0" } else { [string]$sceneSettings.pass2_sigmas })
    Set-NodeInput $workflow "219:221" "strength" ([double]$sceneSettings.pass2_inplace_strength)
    Set-NodeInput $workflow "219:221" "bypass" ([bool]$sceneSettings.pass2_inplace_bypass)

    Set-NodeInput $workflow "271:215" "unet_name" ([string]$sceneSettings.unet_name)
    Set-NodeInput $workflow "271:216" "clip_name1" ([string]$sceneSettings.clip_name1)
    Set-NodeInput $workflow "271:216" "clip_name2" ([string]$sceneSettings.clip_name2)
    Set-NodeInput $workflow "271:256" "vae_name" ([string]$sceneSettings.vae_name)
    Set-NodeInput $workflow "271:254" "vae_name" ([string]$sceneSettings.audio_vae_name)
    Set-NodeInput $workflow "271:211" "model_name" ([string]$sceneSettings.upscale_model_name)

    # Preserve optional project or scene-level LoRAs.
    $loras = @($sceneSettings.loras)
    Set-NodeInput $workflow "937" "use_custom_loras" ([bool]$sceneSettings.use_loras)
    Set-NodeInput $workflow "937" "lora_count" ([int]$sceneSettings.lora_count)
    for ($loraIndex = 1; $loraIndex -le 20; $loraIndex++) {
        $lora = if ($loraIndex -le $loras.Count) { $loras[$loraIndex - 1] } else { $null }
        Set-NodeInput $workflow "937" "lora_$loraIndex" $(if ($null -ne $lora) { [string]$lora.name } else { "[none]" })
        Set-NodeInput $workflow "937" "first_pass_strength_$loraIndex" $(if ($null -ne $lora) { [double]$lora.first_pass_strength } else { 1.0 })
        Set-NodeInput $workflow "937" "second_pass_strength_$loraIndex" $(if ($null -ne $lora) { [double]$lora.second_pass_strength } else { 1.0 })
    }

    $fileName = "i2v_{0}_tiled.json" -f $sceneBaseName
    $destination = Join-Path $outputDirectory $fileName
    [System.IO.File]::WriteAllText(
        $destination,
        ($workflow | ConvertTo-Json -Depth 100),
        [System.Text.UTF8Encoding]::new($false)
    )
    $generated += $destination
}

# Store a reusable, valid scene-1 template beside the generated workflows.
$template = $baseWorkflow | ConvertTo-Json -Depth 100 | ConvertFrom-Json
$templateDecoder = $template.PSObject.Properties["936"].Value
$templateDecoder.class_type = "VAEDecodeTiled"
$templateDecoder._meta.title = "VAE Decode Tiled (AMD safe)"
Set-NodeInput $template "936" "tile_size" $TileSize
Set-NodeInput $template "936" "overlap" $Overlap
Set-NodeInput $template "936" "temporal_size" $TemporalSize
Set-NodeInput $template "936" "temporal_overlap" $TemporalOverlap
$templatePath = Join-Path $outputDirectory "i2v_general_template_tiled.json"
[System.IO.File]::WriteAllText($templatePath, ($template | ConvertTo-Json -Depth 100), [System.Text.UTF8Encoding]::new($false))

[pscustomobject]@{
    Project = $ProjectRoot
    SceneCount = $projectScenes.Count
    GeneratedScenes = ($selectedScenes -join ", ")
    TileSize = $TileSize
    UpscaleDisabled = [bool]$DisableUpscale
    OutputDirectory = $outputDirectory
    SupportingTemplate = $templatePath
    TimingSrt = $srtPath
    GeneratedWorkflowCount = $generated.Count
    GeneratedWorkflowFiles = @($generated)
}
