# Start the Windows ComfyUI on port 8188, with the settings measurement chose.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start_comfyui_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_comfyui_windows.ps1 -Port 8190
#
# Why not just use Comfy Desktop's Start button:
#
#   * the port must be predictable. `lib/comfy_routing.py` sends Wan workflows to
#     8189 (WSL) and everything else to 8188. Comfy Desktop silently moves to the
#     next free port when it believes one is busy - it moved to 8189 on
#     2026-08-30 because of a *stale* lock file, which would have sent LTX to the
#     Wan server and Wan to a server whose weights had been deleted.
#   * `--disable-mmap` must be OFF. Measured 2026-08-30 over three runs: removing
#     it made cold loading 4x faster (72.5s -> 18.5s), cut peak RSS by 6 GiB, and
#     was marginally faster overall. See wiki/comfyui/two-platforms.md.
#
# Paths are discovered, not hard-coded. Override with COMFYUI_INSTALL_DIR,
# COMFYUI_SHARED_DIR or COMFYUI_MODEL_PATHS_CONFIG if this machine is unusual.
#
# Ctrl-C stops it. Nothing detaches.

[CmdletBinding()]
param(
    [int]$Port = 8188,
    [string]$InstallDir,
    [string]$SharedDir,
    [string]$ModelPathsConfig
)

$ErrorActionPreference = "Stop"

function Resolve-InstallDir {
    if ($InstallDir) { return $InstallDir }
    if ($env:COMFYUI_INSTALL_DIR) { return $env:COMFYUI_INSTALL_DIR }
    $base = Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Installs"
    if (Test-Path $base) {
        foreach ($d in @((Join-Path $base "ComfyUI")) + (Get-ChildItem $base -Directory | ForEach-Object { $_.FullName })) {
            if (Test-Path (Join-Path $d "ComfyUI\main.py")) { return $d }
        }
    }
    throw "ComfyUI install not found. Pass -InstallDir or set COMFYUI_INSTALL_DIR."
}

function Resolve-SharedDir {
    if ($SharedDir) { return $SharedDir }
    if ($env:COMFYUI_SHARED_DIR) { return $env:COMFYUI_SHARED_DIR }
    $d = Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Shared"
    if (Test-Path $d) { return $d }
    throw "ComfyUI shared tree not found. Pass -SharedDir or set COMFYUI_SHARED_DIR."
}

function Resolve-ModelPathsConfig {
    if ($ModelPathsConfig) { return $ModelPathsConfig }
    if ($env:COMFYUI_MODEL_PATHS_CONFIG) { return $env:COMFYUI_MODEL_PATHS_CONFIG }
    # Comfy Desktop writes one yaml per instance; newest is the live one.
    $dir = Join-Path $env:APPDATA "Comfy Desktop\instance-model-paths"
    if (Test-Path $dir) {
        $f = Get-ChildItem $dir -Filter *.yaml | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($f) { return $f.FullName }
    }
    return $null   # ComfyUI still finds models under its own tree
}

$install = Resolve-InstallDir
$shared  = Resolve-SharedDir
$paths   = Resolve-ModelPathsConfig
$py      = Join-Path $install "ComfyUI\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No ComfyUI venv python at $py" }

# A stale lock is what pushed the port to 8189 in the first place.
$locks = Join-Path $env:APPDATA "Comfy Desktop\port-locks"
if (Test-Path $locks) {
    Get-ChildItem $locks -Filter *.json -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) { throw "Port $Port is already in use by pid $($busy.OwningProcess). Stop it first." }

Write-Host "ComfyUI (Windows) on http://127.0.0.1:$Port  -  Ctrl-C to stop" -ForegroundColor Cyan
Write-Host "Wan workflows do NOT run here; they are routed to WSL." -ForegroundColor DarkGray
Write-Host "install: $install" -ForegroundColor DarkGray

$comfyArgs = @(
    "-s", (Join-Path "ComfyUI" "main.py"),
    "--port", $Port,
    "--enable-manager", "--enable-manager-legacy-ui",
    "--input-directory",  (Join-Path $shared "input"),
    "--output-directory", (Join-Path $shared "output")
)
if ($paths) { $comfyArgs += @("--extra-model-paths-config", $paths) }

Set-Location $install
& $py @comfyArgs
