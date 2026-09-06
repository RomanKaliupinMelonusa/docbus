# docbus installer for Windows (PowerShell)
# Usage: irm https://raw.githubusercontent.com/RomanKaliupinMelonusa/docbus/main/install.ps1 | iex
#
# This script:
#   1. Checks for uv (installs it if missing)
#   2. Finds the latest docbus GitHub release and its wheel asset
#   3. Installs docbus via `uv tool install <wheel-url>`
#
# docbus still needs pandoc and mmdc (mermaid-cli) on PATH at runtime.
# This installer does not vendor them -- see the README for install links.

$ErrorActionPreference = 'Stop'

$Repo      = 'RomanKaliupinMelonusa/docbus'
$GitHubApi = "https://api.github.com/repos/$Repo/releases/latest"

function Write-Info    { param([string]$Msg) Write-Host "  -> $Msg" -ForegroundColor Cyan }
function Write-Ok      { param([string]$Msg) Write-Host "  [OK] $Msg" -ForegroundColor Green }
function Write-Warning2 { param([string]$Msg) Write-Host "  [!] $Msg" -ForegroundColor Yellow }
function Write-Err     { param([string]$Msg) Write-Host "  [X] $Msg" -ForegroundColor Red; exit 1 }

Write-Host "`ndocbus installer`n" -ForegroundColor White

# --- uv ---
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    Write-Info "uv not found -- installing..."
    irm https://astral.sh/uv/install.ps1 | iex
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCmd) {
        Write-Err "uv installation succeeded but 'uv' is not on PATH. Please restart your terminal and retry."
    }
    Write-Ok "uv installed"
} else {
    Write-Ok "uv found at $($uvCmd.Source)"
}

# --- Find the latest release and its wheel asset ---
Write-Info "Fetching latest release..."
$release = Invoke-RestMethod -Uri $GitHubApi -Headers @{ Accept = 'application/vnd.github+json' }
$tagName = $release.tag_name
if (-not $tagName) {
    Write-Err "Could not determine latest release tag from GitHub API."
}
$wheelAsset = $release.assets | Where-Object { $_.name -like '*.whl' } | Select-Object -First 1
if (-not $wheelAsset) {
    Write-Err "Could not find a .whl asset on release $tagName."
}
Write-Ok "Latest release: $tagName"

# --- Install ---
Write-Info "Installing docbus $tagName..."
& uv tool install --force $wheelAsset.browser_download_url
if ($LASTEXITCODE -ne 0) {
    Write-Err "uv tool install failed."
}

# --- Ensure PATH is updated for new shells ---
try {
    & uv tool update-shell 2>&1 | Out-Null
} catch {
    Write-Warning2 "Could not update user PATH automatically. Run 'uv tool update-shell' manually."
}

# --- Verify ---
$docbusCmd = Get-Command docbus -ErrorAction SilentlyContinue
if ($docbusCmd) {
    Write-Ok "Verified: docbus responds correctly"
} else {
    $binDir = & uv tool dir --bin 2>$null
    Write-Warning2 "'docbus' was installed but isn't on PATH in this shell yet."
    Write-Host ""
    Write-Host "    Open a new terminal, or run this in the current one:"
    Write-Host "      `$env:Path = `"$binDir;`$env:Path`""
    Write-Host ""
}

# --- Runtime dependency check (report what's actually missing, not a blanket reminder) ---
$missing = @()
if (-not (Get-Command pandoc -ErrorAction SilentlyContinue)) { $missing += 'pandoc' }
if (-not (Get-Command mmdc -ErrorAction SilentlyContinue)) { $missing += 'mmdc' }
if ($missing.Count -eq 0) {
    Write-Ok "pandoc and mmdc (mermaid-cli) both found on PATH"
} else {
    Write-Host ""
    Write-Host "  docbus also needs the following on PATH (not found): $($missing -join ' ')"
    if ($missing -contains 'pandoc') { Write-Host "    pandoc: https://pandoc.org/installing.html" }
    if ($missing -contains 'mmdc')   { Write-Host "    mmdc:   npm install -g @mermaid-js/mermaid-cli" }
    Write-Host ""
}

Write-Host "  Run 'docbus --help' to get started."
Write-Host ""
