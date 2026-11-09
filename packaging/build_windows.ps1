param(
  [string]$AppVersion = "0.1.0-beta",
  [string]$OutDirName = "out",
  [switch]$SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $RepoRoot "frontend"
$PackagingDir = $PSScriptRoot
$OutDir = Join-Path $PackagingDir $OutDirName
$PyInstallerOut = Join-Path $OutDir "pyinstaller"
$AppStageDir = Join-Path $OutDir "app\WorkdayLens"
$RuntimeDir = Join-Path $AppStageDir "runtime"
$RuntimeAssetsDir = Join-Path $RuntimeDir "assets"
$RuntimeFrontendDir = Join-Path $RuntimeDir "frontend"
$RuntimeNodeDir = Join-Path $RuntimeDir "node"
$RuntimeNvdaDir = Join-Path $RuntimeDir "nvda"
$InstallerOutDir = Join-Path $OutDir "installer"

function Require-Command([string]$Name) {
  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $command) {
    throw "Required command not found on PATH: $Name"
  }
  return $command.Source
}

function Resolve-InnoSetupCompiler() {
  $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
  if ($command) {
    return $command.Source
  }

  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
  )

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  return $null
}

function Reset-Directory([string]$Path) {
  if (Test-Path $Path) {
    Remove-Item -Recurse -Force -LiteralPath $Path
  }
  New-Item -ItemType Directory -Path $Path | Out-Null
}

function Copy-IfExists([string]$Source, [string]$Destination) {
  if (Test-Path $Source) {
    Copy-Item -Recurse -Force -Path $Source -Destination $Destination
  }
}

function Copy-DirectoryContentsIfExists([string]$SourceDir, [string]$DestinationDir) {
  if (Test-Path $SourceDir) {
    Copy-Item -Recurse -Force -Path (Join-Path $SourceDir "*") -Destination $DestinationDir
  }
}

$npm = Require-Command "npm.cmd"
$node = Require-Command "node.exe"

$pyinstaller = Get-Command "pyinstaller" -ErrorAction SilentlyContinue
if ($pyinstaller) {
  $pyinstallerExe = $pyinstaller.Source
  $pyinstallerArgs = @()
} else {
  $python = Require-Command "python.exe"
  & $python -m PyInstaller --version | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed on PATH or available via python -m PyInstaller. Install it first, then rerun packaging\build_windows.ps1."
  }
  $pyinstallerExe = $python
  $pyinstallerArgs = @("-m", "PyInstaller")
}

Write-Host "Building frontend standalone bundle..."
Push-Location $FrontendDir
try {
  & $npm run build
} finally {
  Pop-Location
}

$StandaloneDir = Join-Path $FrontendDir ".next\standalone"
$StandaloneServer = Join-Path $StandaloneDir "server.js"
if (-not (Test-Path $StandaloneServer)) {
  throw "Frontend standalone build output is missing: $StandaloneServer"
}

Reset-Directory $OutDir
New-Item -ItemType Directory -Path $PyInstallerOut | Out-Null
New-Item -ItemType Directory -Path $RuntimeAssetsDir -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeFrontendDir -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeNodeDir -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeNvdaDir -Force | Out-Null
New-Item -ItemType Directory -Path $InstallerOutDir -Force | Out-Null

Write-Host "Staging frontend runtime..."
Copy-Item -Recurse -Force -Path (Join-Path $StandaloneDir "*") -Destination $RuntimeFrontendDir
New-Item -ItemType Directory -Path (Join-Path $RuntimeFrontendDir ".next") -Force | Out-Null
Copy-Item -Recurse -Force -Path (Join-Path $FrontendDir ".next\static") -Destination (Join-Path $RuntimeFrontendDir ".next")
Copy-IfExists (Join-Path $FrontendDir "public") (Join-Path $RuntimeFrontendDir "public")

Write-Host "Staging Node runtime..."
Copy-Item -Force -Path $node -Destination (Join-Path $RuntimeNodeDir "node.exe")

Write-Host "Staging launcher assets..."
Copy-DirectoryContentsIfExists (Join-Path $PackagingDir "assets") $RuntimeAssetsDir

Write-Host "Staging NVDA runtime assets..."
Copy-DirectoryContentsIfExists (Join-Path $PackagingDir "nvda") $RuntimeNvdaDir

Write-Host "Building launcher executable with PyInstaller..."
Push-Location $RepoRoot
try {
  & $pyinstallerExe @pyinstallerArgs `
    --noconfirm `
    --clean `
    --distpath $PyInstallerOut `
    --workpath (Join-Path $OutDir "build") `
    (Join-Path $PackagingDir "WorkdayLensLauncher.spec")
} finally {
  Pop-Location
}

$PyInstallerAppDir = Join-Path $PyInstallerOut "WorkdayLensLauncher"
if (-not (Test-Path (Join-Path $PyInstallerAppDir "WorkdayLensLauncher.exe"))) {
  throw "PyInstaller output is missing WorkdayLensLauncher.exe"
}

Write-Host "Staging app payload for installer..."
Copy-Item -Recurse -Force -Path (Join-Path $PyInstallerAppDir "*") -Destination $AppStageDir

Set-Content -Path (Join-Path $AppStageDir "VERSION.txt") -Value $AppVersion -Encoding ascii

if ($SkipInstaller) {
  Write-Host "App payload ready at $AppStageDir"
  exit 0
}

$iscc = Resolve-InnoSetupCompiler
if (-not $iscc) {
  throw "Inno Setup compiler (ISCC.exe) is not installed on PATH. Install Inno Setup or rerun with -SkipInstaller."
}

Write-Host "Building Inno Setup installer..."
& $iscc `
  "/DAppVersion=$AppVersion" `
  "/DSourceDir=$AppStageDir" `
  "/DOutputDir=$InstallerOutDir" `
  (Join-Path $PackagingDir "installer.iss")

Write-Host "Installer ready in $InstallerOutDir"
