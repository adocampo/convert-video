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
            winget install --id $WingetId --source winget --accept-source-agreements --accept-package-agreements --silent
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
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
    & $script:PythonExe -m pip install --user pipx 2>&1 | Out-Null
    & $script:PythonExe -m pipx ensurepath 2>&1 | Out-Null
    $ErrorActionPreference = $prev
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
    git clone --depth 1 $RepoUrl $tmpDir 2>&1 | Out-Null
    Write-Info "Cloned to $tmpDir"
    return $tmpDir
}

# ── Check runtime dependencies ───────────────

function Find-BinaryPath {
    <# Search common install directories for a binary that is not in PATH. #>
    param([string]$Name)
    # Try where.exe first (Windows equivalent of 'which')
    try {
        $whereResult = where.exe "$Name.exe" 2>$null | Select-Object -First 1
        if ($whereResult -and (Test-Path $whereResult)) {
            return (Split-Path $whereResult -Parent)
        }
    } catch {}
    $searchRoots = @(
        "$env:ProgramFiles",
        "${env:ProgramFiles(x86)}",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
        "$env:LOCALAPPDATA\Programs"
    )
    foreach ($root in $searchRoots) {
        if (-not $root -or -not (Test-Path $root)) { continue }
        $hits = Get-ChildItem -Path $root -Filter "$Name.exe" -Recurse -ErrorAction SilentlyContinue -Depth 3 |
                Select-Object -First 1
        if ($hits) { return $hits.DirectoryName }
    }
    return $null
}

function Add-ToUserPath {
    <# Append a directory to the persistent user PATH if not already present. #>
    param([string]$Dir)
    $currentUser = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    if ($currentUser -and $currentUser.ToLower().Contains($Dir.ToLower())) { return }
    $newPath = if ($currentUser) { "$currentUser;$Dir" } else { $Dir }
    [System.Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    # Also update the running session
    if (-not $env:Path.ToLower().Contains($Dir.ToLower())) {
        $env:Path = "$env:Path;$Dir"
    }
    Write-Info "Added to user PATH: $Dir"
}

function Install-RuntimeDeps {
    $deps = @(
        @{ Name = 'HandBrakeCLI'; WingetId = 'HandBrake.HandBrake'; ChocoName = 'handbrake-cli'; ScoopName = 'handbrake-cli'; Label = 'HandBrake (includes CLI)' },
        @{ Name = 'mediainfo';    WingetId = 'MediaArea.MediaInfo';  ChocoName = 'mediainfo-cli';  ScoopName = 'mediainfo';      Label = 'MediaInfo CLI' },
        @{ Name = 'mkvpropedit'; WingetId = 'MoritzBunkus.MKVToolNix'; ChocoName = 'mkvtoolnix';  ScoopName = 'mkvtoolnix';     Label = 'MKVToolNix' },
        @{ Name = 'mkvmerge';    WingetId = '';                          ChocoName = '';                ScoopName = '';                Label = '' }
    )

    $installed_any = $false
    foreach ($dep in $deps) {
        if (Test-Command $dep.Name) { continue }
        # mkvmerge is provided by MKVToolNix (same package as mkvpropedit), skip duplicate install
        if ($dep.Name -eq 'mkvmerge') { continue }
        Write-Warn "$($dep.Label) not found. Installing..."
        Install-Pkg -WingetId $dep.WingetId -ChocoName $dep.ChocoName -ScoopName $dep.ScoopName -Label $dep.Label
        $installed_any = $true
    }

    if ($installed_any) {
        # Refresh PATH so newly installed tools are visible
        $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [System.Environment]::GetEnvironmentVariable('Path', 'User')
    }

    # Search for binaries that are installed but not in PATH and add their directories
    $pathsAdded = @{}
    foreach ($dep in $deps) {
        if (Test-Command $dep.Name) { continue }
        $dir = Find-BinaryPath $dep.Name
        if ($dir -and -not $pathsAdded.ContainsKey($dir)) {
            Add-ToUserPath $dir
            $pathsAdded[$dir] = $true
        }
    }

    # Final status check
    $still_missing = @()
    foreach ($dep in $deps) {
        if (-not (Test-Command $dep.Name)) {
            $still_missing += $dep.Name
        }
    }
    if ($still_missing.Count -gt 0) {
        Write-Warn "Some dependencies are still not in PATH: $($still_missing -join ', ')"
        Write-Warn "You can configure their paths in clutch Settings > Binary Paths."
    } else {
        Write-Info "All runtime dependencies found: $($deps.Name -join ', ')"
    }
}

# ── Scheduled Task (Windows Service) ─────────
$script:TaskName = 'clutch'

function Get-ClutchExePath {
    <# Resolve the full path to clutch.exe installed by pipx. #>
    # Refresh PATH so recently installed binaries are visible
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $cmd = Get-Command $AppName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # Fallback: standard pipx binary location
    $fallback = Join-Path $env:USERPROFILE ".local\bin\$AppName.exe"
    if (Test-Path $fallback) { return $fallback }
    return $null
}

function Install-ScheduledTask {
    <# Register a scheduled task that starts clutch --serve at system startup.
       The task runs as the current user and does not require an interactive logon. #>

    $clutchExe = Get-ClutchExePath
    if (-not $clutchExe) {
        Write-Warn "Could not locate $AppName executable. Skipping scheduled task creation."
        return
    }

    # Check for an existing task
    $existing = Get-ScheduledTask -TaskName $script:TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Warn "Scheduled task '$($script:TaskName)' already exists."
        $overwrite = Read-Host "    Overwrite it? [y/N]"
        if ($overwrite -notmatch '^[yY]') {
            Write-Info "Keeping existing scheduled task."
            return
        }
        Unregister-ScheduledTask -TaskName $script:TaskName -Confirm:$false
    }

    $arguments = "--serve --listen-host 0.0.0.0 --listen-port 8765"

    $action   = New-ScheduledTaskAction -Execute $clutchExe -Argument $arguments
    # -AtStartup runs when the machine boots, before any user logs in
    $trigger  = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit 0 `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries

    # To run at startup without requiring an interactive logon session
    # Windows needs the user's password to store credentials for the task.
    $user = "$env:USERDOMAIN\$env:USERNAME"
    Write-Host ''
    Write-Warn "Windows requires your password to run the task at startup without logon."
    Write-Warn "The password is stored securely by the Task Scheduler; this script does not keep it."
    $securePass = Read-Host "    Password for $user" -AsSecureString
    $cred = New-Object System.Management.Automation.PSCredential($user, $securePass)
    $plainPass = $cred.GetNetworkCredential().Password

    try {
        Register-ScheduledTask `
            -TaskName $script:TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -User $user `
            -Password $plainPass `
            -RunLevel Highest `
            -Description "Run clutch media transcoding service at system startup" `
            | Out-Null
        Write-Info "Scheduled task '$($script:TaskName)' registered successfully."
        Write-Info "  Executable : $clutchExe"
        Write-Info "  Arguments  : $arguments"
        Write-Info "  Trigger    : At system startup (runs as $user)"
        Write-Host ''
        $startNow = Read-Host "    Start the service now? [Y/n]"
        if ($startNow -match '^[nN]') {
            Write-Info "Service will start on next boot."
        } else {
            Start-ScheduledTask -TaskName $script:TaskName
            Write-Info "Service started. Dashboard: http://localhost:8765"
        }
    } catch {
        Write-Warn "Failed to register scheduled task: $_"
        Write-Warn "You can create it manually with Task Scheduler."
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
$prev = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
$pipxList = & pipx list 2>&1 | Out-String
if ($pipxList -match [regex]::Escape($LegacyAppName)) {
    Write-Info "Legacy pipx installation detected; removing $LegacyAppName"
    & pipx uninstall $LegacyAppName 2>&1 | Out-Null
}
if ($pipxList -match [regex]::Escape($AppName)) {
    Write-Info "Existing $AppName installation detected; reinstalling"
    & pipx uninstall $AppName 2>&1 | Out-Null
}
$ErrorActionPreference = $prev

Write-Info "Installing $AppName via pipx..."
& pipx install $sourceDir

Write-Host ''
Install-RuntimeDeps

# Clean up temp clone if used
if ($sourceDir -ne $PSScriptRoot -and $sourceDir -like "*clutch-install-*") {
    Remove-Item -Recurse -Force $sourceDir -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Info "Installation complete!"
Write-Host ''

# Offer to register as a Windows scheduled task (service mode)
$registerService = Read-Host "[?] Register clutch as a Windows service (scheduled task at startup)? [Y/n]"
if ($registerService -match '^[nN]') {
    Write-Info "Skipped service registration. Run '$AppName --help' to get started."
} else {
    Install-ScheduledTask
}
