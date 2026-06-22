Write-Output "Installing Spacelyzer..."

# 1. Verify Python is installed
$pythonCmd = $null
foreach ($cmd in "py", "python", "python3") {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $pythonCmd = $cmd
        break
    }
}

if ($null -eq $pythonCmd) {
    Write-Error "Error: Python 3 is required but was not found on your system."
    Write-Error "       Install it from https://www.python.org/downloads/ and re-run this script."
    exit 1
}

# Verify Python is at least version 3.8
$pyVersion = & $pythonCmd -c "import sys; print(sys.version_info >= (3,8))" 2>&1
if ($pyVersion -ne "True") {
    Write-Error "Error: Python 3.8 or newer is required. Found: $pythonCmd"
    exit 1
}

Write-Output "  Python found: $pythonCmd"

# 2. Setup directory structure
$spacelyzerDir = Join-Path $HOME ".spacelyzer"
$binDir        = Join-Path $spacelyzerDir "bin"
$repoDir       = Join-Path $spacelyzerDir "repo"
$snapshotsDir  = Join-Path $spacelyzerDir "snapshots"

if (!(Test-Path $binDir))      { New-Item -ItemType Directory -Force -Path $binDir      | Out-Null }
if (!(Test-Path $snapshotsDir)) { New-Item -ItemType Directory -Force -Path $snapshotsDir | Out-Null }

# 3. Clone or download source code
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path $repoDir) {
        Write-Output "Updating existing repository..."
        # Use git -C so we never mutate the script's working directory
        $gitResult = git -C $repoDir pull --quiet 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git pull failed: $gitResult"
            exit 1
        }
    } else {
        Write-Output "Cloning Spacelyzer repository..."
        git clone --quiet "https://github.com/KavimugilRajasekar/spacelyzer.git" $repoDir 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git clone failed. Check your internet connection and try again."
            exit 1
        }
    }
} else {
    Write-Output "git not found. Downloading repository zip archive..."
    if (Test-Path $repoDir) { Remove-Item -Recurse -Force $repoDir }
    New-Item -ItemType Directory -Force -Path $repoDir | Out-Null

    $zipUrl  = "https://github.com/KavimugilRajasekar/spacelyzer/archive/refs/heads/main.zip"
    $zipPath = Join-Path $spacelyzerDir "repo.zip"

    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -ErrorAction Stop
    } catch {
        Write-Error "Download failed: $_"
        Write-Error "Check your internet connection and try again."
        exit 1
    }

    $tempExtract = Join-Path $spacelyzerDir "temp_extract"
    try {
        Expand-Archive -Path $zipPath -DestinationPath $tempExtract -Force
        $extractedFolder = Get-ChildItem $tempExtract | Select-Object -First 1
        Move-Item -Path (Join-Path $extractedFolder.FullName "*") -Destination $repoDir -Force
    } catch {
        Write-Error "Archive extraction failed: $_"
        exit 1
    } finally {
        if (Test-Path $tempExtract) { Remove-Item -Recurse -Force $tempExtract }
        if (Test-Path $zipPath)     { Remove-Item -Force $zipPath }
    }
}

# Sanity-check: ensure the package exists in the cloned/downloaded repo
if (!(Test-Path (Join-Path $repoDir "spacelyzer" "__init__.py"))) {
    Write-Error "Repository structure looks wrong — spacelyzer package not found in $repoDir"
    exit 1
}

# 4. Create launcher scripts in the bin directory
Write-Output "Creating launcher scripts..."

# .bat launcher (cmd.exe / legacy terminals)
$batContent = "@echo off`r`nset PYTHONPATH=%USERPROFILE%\.spacelyzer\repo;%PYTHONPATH%`r`n$pythonCmd -m spacelyzer %*"
$batPath = Join-Path $binDir "spacelyzer.bat"
Set-Content -Path $batPath -Value $batContent -Encoding ASCII -Force

# .ps1 launcher (PowerShell)
$ps1Content = "`$env:PYTHONPATH = `"`$HOME\.spacelyzer\repo;`$env:PYTHONPATH`"`r`n& $pythonCmd -m spacelyzer `$args"
$ps1Path = Join-Path $binDir "spacelyzer.ps1"
Set-Content -Path $ps1Path -Value $ps1Content -Force

# 5. Add bin directory to user-level PATH
Write-Output "Configuring Environment PATH..."
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ([string]::IsNullOrEmpty($userPath) -or ($userPath -notlike "*\.spacelyzer\bin*")) {
    $newUserPath = if ([string]::IsNullOrEmpty($userPath)) { $binDir } else { $userPath.TrimEnd(';') + ";" + $binDir }
    [Environment]::SetEnvironmentVariable("PATH", $newUserPath, "User")
    # Also update current-session PATH so the verification below works
    $env:Path = $env:Path.TrimEnd(';') + ";" + $binDir
    Write-Output "  Added $binDir to User PATH."
} else {
    Write-Output "  PATH already contains Spacelyzer bin directory."
}

# 6. Verification
Write-Output ""
Write-Output "Verification:"
try {
    & "$batPath" --version
    if ($LASTEXITCODE -ne 0) { throw "spacelyzer exited with code $LASTEXITCODE" }
} catch {
    Write-Error "Verification failed: $_"
    Write-Error "Try running manually: & '$batPath' --version"
    exit 1
}

Write-Output ""
Write-Output "Installation complete!"
Write-Output "Open a new PowerShell / CMD window to use 'spacelyzer' from anywhere."
Write-Output "Snapshots are stored in: $snapshotsDir"
