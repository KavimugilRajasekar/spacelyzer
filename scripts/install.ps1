Write-Output "Installing Spacelyzer..."

# 1. Verify python is installed
$pythonCmd = $null
foreach ($cmd in "py", "python", "python3") {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $pythonCmd = $cmd
        break
    }
}

if ($null -eq $pythonCmd) {
    Write-Error "Error: Python is required but was not found on your system. Please install Python 3."
    exit 1
}

# 2. Setup directory structure
$spacelyzerDir = Join-Path $HOME ".spacelyzer"
$binDir = Join-Path $spacelyzerDir "bin"
$repoDir = Join-Path $spacelyzerDir "repo"

if (!(Test-Path $binDir)) {
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
}

# 3. Clone or Download source code
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path $repoDir) {
        Write-Output "Updating existing repository..."
        Set-Location $repoDir
        git pull --quiet
    } else {
        Write-Output "Cloning Spacelyzer repository..."
        git clone --quiet "https://github.com/KavimugilRajasekar/spacelyzer.git" $repoDir
    }
} else {
    Write-Output "git not found. Downloading repository zip archive..."
    if (Test-Path $repoDir) {
        Remove-Item -Recurse -Force $repoDir
    }
    New-Item -ItemType Directory -Force -Path $repoDir | Out-Null
    
    $zipUrl = "https://github.com/KavimugilRajasekar/spacelyzer/archive/refs/heads/main.zip"
    $zipPath = Join-Path $spacelyzerDir "repo.zip"
    
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
    
    # Extract zip contents to temp, then move files to repoDir
    $tempExtract = Join-Path $spacelyzerDir "temp_extract"
    Expand-Archive -Path $zipPath -DestinationPath $tempExtract -Force
    
    $extractedFolder = Get-ChildItem $tempExtract | Select-Object -First 1
    Move-Item -Path (Join-Path $extractedFolder.FullName "*") -Destination $repoDir -Force
    
    Remove-Item -Recurse -Force $tempExtract
    Remove-Item -Force $zipPath
}

# 4. Create launcher cmd/ps1 files in bin directory
Write-Output "Creating launcher scripts..."
$batContent = "@echo off`r`nset PYTHONPATH=%USERPROFILE%\.spacelyzer\repo;%PYTHONPATH%`r`n$pythonCmd -m spacelyzer.cli %*"
$batPath = Join-Path $binDir "spacelyzer.bat"
Set-Content -Path $batPath -Value $batContent -Force

$ps1Content = "`$env:PYTHONPATH = `"`$HOME\.spacelyzer\repo;`$env:PYTHONPATH`"`r`n& $pythonCmd -m spacelyzer.cli `$args"
$ps1Path = Join-Path $binDir "spacelyzer.ps1"
Set-Content -Path $ps1Path -Value $ps1Content -Force

# 5. Add to environment PATH (user level)
Write-Output "Configuring Environment PATH..."
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ([string]::IsNullOrEmpty($userPath)) {
    $newUserPath = $binDir
    [Environment]::SetEnvironmentVariable("PATH", $newUserPath, "User")
    Write-Output "Added Spacelyzer to User PATH environment variable."
    $env:Path = $env:Path + ";" + $binDir
} elseif ($userPath -notlike "*\.spacelyzer\bin*") {
    $newUserPath = $userPath.TrimEnd(';') + ";" + $binDir
    [Environment]::SetEnvironmentVariable("PATH", $newUserPath, "User")
    Write-Output "Added Spacelyzer to User PATH environment variable."
    
    # Also update current session PATH
    $env:Path = $env:Path + ";" + $binDir
}

# 6. Verification
Write-Output "Verification:"
& "$binDir\spacelyzer.bat" --version

Write-Output ""
Write-Output "Installation complete!"
Write-Output "Please open a new PowerShell window or restart your shell to start using 'spacelyzer'."
