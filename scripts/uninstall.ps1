Write-Output "Uninstalling Spacelyzer..."

$spacelyzerDir = Join-Path $HOME ".spacelyzer"
$binDir = Join-Path $spacelyzerDir "bin"

# 1. Remove folder
if (Test-Path $spacelyzerDir) {
    Remove-Item -Recurse -Force $spacelyzerDir
    Write-Output "Removed Spacelyzer directory: $spacelyzerDir"
}

# 2. Clean environment PATH
Write-Output "Updating Environment PATH..."
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -like "*\.spacelyzer\bin*") {
    # Remove binDir from Path
    # Split by semicolon, filter out target path, join back
    $pathParts = $userPath -split ";" | Where-Object { $_.TrimEnd('\') -ne $binDir.TrimEnd('\') }
    $newUserPath = $pathParts -join ";"
    [Environment]::SetEnvironmentVariable("PATH", $newUserPath, "User")
    Write-Output "Removed Spacelyzer from User PATH environment variable."
}

Write-Output "Uninstallation complete!"
