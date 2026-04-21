#Requires -Version 5.1
<#
.SYNOPSIS
    Install clutch via pipx on Windows.
.DESCRIPTION
    Installs Python 3, pipx, and clutch from source or from the GitHub
    repository.  Also checks for optional runtime dependencies
    (HandBrakeCLI, mediainfo, mkvpropedit, mkvmerge).
    Supports winget, choco, and scoop as package managers.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoUrl        = 'https://github.com/adocampo/clutch.git'
$AppName        = 'clutch'
$LegacyAppName  = 'convert-video'

# ── Helpers ──────────────────────────────────
function Write-Info  { param([string]$Msg) Write-Host "[+] $Msg" -ForegroundColor Green }
function Write-Warn  { param([string]$Msg) Write-Host "[!] $Msg" -ForegroundColor Yellow }
function Write-Fail  { param([string]$Msg) Write-Host "[x] $Msg" -ForegroundColor Red; exit 1 }

function Test-Command { param([string]$Name) $null -ne (Get-Command $Name -ErrorAction SilentlyContinue) }

function Test-RealPython {
    <# Returns the python executable name if a real interpreter is found, $null otherwise.
       Windows ships MS Store stubs (WindowsApps\python.exe) that are not real interpreters. #>
    foreach ($candidate in @('python', 'python3', 'py')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        # Skip MS Store stubs: they live in WindowsApps and are tiny (0-byte or ≤10 KB).
        $exe = $cmd.Source
        if ($exe -and $exe -like '*WindowsApps*') {
            $size = (Get-Item $exe -ErrorAction SilentlyContinue).Length
            if ($size -lt 20480) { continue }
        }
        # Verify it actually responds to --version
        try {
            $out = & $candidate --version 2>&1
            if ($out -match 'Python \d+\.\d+') { return $candidate }
        } catch { continue }
    }
    return $null
}

# ── Detect package manager ───────────────────
function Get-PackageManager {
    if (Test-Command 'winget')  { return 'winget' }
    if (Test-Command 'choco')   { return 'choco'  }
    if (Test-Command 'scoop')   { return 'scoop'  }
    return $null
}

function Install-Pkg {
    param([string]$WingetId, [string]$ChocoName, [string]$ScoopName, [string]$Label)
    $mgr = Get-PackageManager
    switch ($mgr) {
        'winget' {
            Write-Warn "Installing $Label via winget..."
            winget install --id $WingetId --accept-source-agreements --accept-package-agreements --silent
        }
        'choco' {
            Write-Warn "Installing $Label via choco..."
            choco install $ChocoName -y
        }
        'scoop' {
            Write-Warn "Installing $Label via scoop..."
            scoop install $ScoopName
        }
        default {
            Write-Fail "No supported package manager found (winget, choco, or scoop). Install $Label manually."
        }
    }
}

# ── Ensure Python 3.9+ ──────────────────────
$script:PythonExe = 'python'

function Ensure-Python {
    $found = Test-RealPython
    if ($found) {
        $ver = & $found -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $parts = $ver -split '\.'
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 9) {
                Write-Info "Python $ver found ($found)"
                $script:PythonExe = $found
                return
            }
            Write-Warn "Python $ver found but 3.9+ is required"
        }
    } else {
        Write-Warn "No real Python interpreter found (MS Store stubs are ignored)"
    }
    Install-Pkg -WingetId 'Python.Python.3.12' -ChocoName 'python' -ScoopName 'python' -Label 'Python 3'
    # Refresh PATH so the new python is visible
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $found = Test-RealPython
    if (-not $found) {
        Write-Fail "Python was installed but is not in PATH. Restart your terminal and run this script again."
    }
    $script:PythonExe = $found
    Write-Info "Python installed ($found)"
}

# ── Ensure pipx ──────────────────────────────
function Ensure-Pipx {
    if (Test-Command 'pipx') {
        Write-Info "pipx found at $(Get-Command pipx | Select-Object -ExpandProperty Source)"
        return
    }
    Write-Warn "Installing pipx via pip..."
    & $script:PythonExe -m pip install --user pipx 2>$null
    & $script:PythonExe -m pipx ensurepath 2>$null
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (Test-Command 'pipx')) {
        Write-Fail "pipx was installed but is not in PATH. Restart your terminal and run this script again."
    }
    Write-Info "pipx installed"
}

# ── Ensure git ───────────────────────────────
function Ensure-Git {
    if (Test-Command 'git') {
        Write-Info "git found"
        return
    }
    Install-Pkg -WingetId 'Git.Git' -ChocoName 'git' -ScoopName 'git' -Label 'Git'
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (Test-Command 'git')) {
        Write-Fail "git was installed but is not in PATH. Restart your terminal and run this script again."
    }
}

# ── Resolve source directory ─────────────────
function Resolve-Source {
    $scriptDir = $PSScriptRoot
    if ($scriptDir -and (Test-Path (Join-Path $scriptDir 'pyproject.toml'))) {
        Write-Info "Installing from local checkout: $scriptDir"
        return $scriptDir
    }
    Ensure-Git
    $tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "clutch-install-$([guid]::NewGuid().ToString('N').Substring(0,8))"
    Write-Info "Cloning $RepoUrl into temporary directory..."
    git clone --depth 1 $RepoUrl $tmpDir 2>$null
    Write-Info "Cloned to $tmpDir"
    return $tmpDir
}

# ── Check runtime dependencies ───────────────
function Check-RuntimeDeps {
    $deps = @(
        @{ Name = 'HandBrakeCLI'; Hint = 'https://handbrake.fr/downloads2.php (install the CLI version)' },
        @{ Name = 'mediainfo';    Hint = 'winget install MediaArea.MediaInfo.CLI  /  choco install mediainfo-cli' },
        @{ Name = 'mkvpropedit';  Hint = 'winget install MKVToolNix.MKVToolNix    /  choco install mkvtoolnix' },
        @{ Name = 'mkvmerge';     Hint = 'Included with MKVToolNix (see above)' }
    )
    $missing = @()
    foreach ($dep in $deps) {
        if (-not (Test-Command $dep.Name)) {
            $missing += $dep
        }
    }
    if ($missing.Count -gt 0) {
        Write-Warn "Optional runtime dependencies not found:"
        foreach ($m in $missing) {
            Write-Host "    $($m.Name)  -> $($m.Hint)" -ForegroundColor Yellow
        }
    } else {
        Write-Info "Runtime dependencies found: $($deps.Name -join ', ')"
    }
}

# ── Main ─────────────────────────────────────
Write-Host ''
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host '  clutch installer (Windows)' -ForegroundColor Cyan
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host ''

$mgr = Get-PackageManager
if ($mgr) {
    Write-Info "Package manager: $mgr"
} else {
    Write-Warn "No package manager detected (winget, choco, scoop). Some auto-installs may fail."
}

Ensure-Python
Ensure-Pipx
Write-Host ''

$sourceDir = Resolve-Source
Write-Host ''

# Remove legacy or existing installation
$pipxList = & pipx list 2>$null | Out-String
if ($pipxList -match [regex]::Escape($LegacyAppName)) {
    Write-Info "Legacy pipx installation detected; removing $LegacyAppName"
    & pipx uninstall $LegacyAppName 2>$null
}
if ($pipxList -match [regex]::Escape($AppName)) {
    Write-Info "Existing $AppName installation detected; reinstalling"
    & pipx uninstall $AppName 2>$null
}

Write-Info "Installing $AppName via pipx..."
& pipx install $sourceDir

Write-Host ''
Check-RuntimeDeps

# Clean up temp clone if used
if ($sourceDir -ne $PSScriptRoot -and $sourceDir -like "*clutch-install-*") {
    Remove-Item -Recurse -Force $sourceDir -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Info "Installation complete! Run '$AppName --help' to get started."
