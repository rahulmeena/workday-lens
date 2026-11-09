param(
  [string]$AppVersion = "0.1.0-beta",
  [ValidateSet("arm64", "x64")]
  [string]$TargetArch = "arm64",
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

function Normalize-Architecture([string]$Value) {
  if ([string]::IsNullOrWhiteSpace($Value)) {
    return ""
  }

  $normalized = $Value.Trim().ToLowerInvariant()
  if (@("arm64", "aarch64", "aa64") -contains $normalized) {
    return "arm64"
  }
  if (@("x64", "amd64", "x86_64") -contains $normalized) {
    return "x64"
  }
  if (@("x86", "ia32", "i386", "i686") -contains $normalized) {
    return "x86"
  }
  return $normalized
}

function Assert-Architecture([string]$Label, [string]$Actual, [string]$Expected) {
  $actualArch = Normalize-Architecture $Actual
  if ($actualArch -ne $Expected) {
    throw "$Label architecture is '$Actual'; expected '$Expected' for -TargetArch $TargetArch. Use native $Expected tooling before building this installer."
  }
  Write-Host "$Label architecture: $actualArch"
}

function Get-PeMachine([string]$Path) {
  $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    $reader = New-Object System.IO.BinaryReader($stream)
    try {
      $stream.Seek(0x3C, [System.IO.SeekOrigin]::Begin) | Out-Null
      $peOffset = $reader.ReadInt32()
      $stream.Seek($peOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
      $signature = $reader.ReadUInt32()
      if ($signature -ne 0x00004550) {
        throw "File is not a PE executable: $Path"
      }

      $machine = $reader.ReadUInt16()
      switch ($machine) {
        0x14c { return "x86" }
        0x8664 { return "x64" }
        0xaa64 { return "arm64" }
        default { return ("0x{0:X4}" -f $machine) }
      }
    } finally {
      $reader.Close()
    }
  } finally {
    $stream.Close()
  }
}

function Assert-PeArchitecture([string]$Path, [string]$Label, [string]$Expected) {
  if (-not (Test-Path $Path)) {
    throw "$Label is missing: $Path"
  }
  $machine = Get-PeMachine $Path
  Assert-Architecture $Label $machine $Expected
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
$python = Require-Command "python.exe"

Write-Host "Preparing $TargetArch Windows build..."

$nodeArch = & $node -p "process.arch"
if ($LASTEXITCODE -ne 0) {
  throw "Unable to inspect Node architecture from $node."
}
Assert-Architecture "Node" $nodeArch $TargetArch
Assert-PeArchitecture $node "node.exe" $TargetArch

$pythonArch = & $python -c "import platform; print(platform.machine())"
if ($LASTEXITCODE -ne 0) {
  throw "Unable to inspect Python architecture from $python."
}
Assert-Architecture "Python" $pythonArch $TargetArch
Assert-PeArchitecture $python "python.exe" $TargetArch

& $python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller is not installed for $TargetArch Python. Install packaging\requirements-build.txt with the native $TargetArch Python, then rerun packaging\build_windows.ps1."
}
$pyinstallerExe = $python
$pyinstallerArgs = @("-m", "PyInstaller")

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
Assert-PeArchitecture (Join-Path $PyInstallerAppDir "WorkdayLensLauncher.exe") "WorkdayLensLauncher.exe" $TargetArch

Write-Host "Staging app payload for installer..."
Copy-Item -Recurse -Force -Path (Join-Path $PyInstallerAppDir "*") -Destination $AppStageDir

Set-Content -Path (Join-Path $AppStageDir "VERSION.txt") -Value $AppVersion -Encoding ascii
Set-Content -Path (Join-Path $AppStageDir "ARCHITECTURE.txt") -Value $TargetArch -Encoding ascii

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
  "/DTargetArch=$TargetArch" `
  "/DSourceDir=$AppStageDir" `
  "/DOutputDir=$InstallerOutDir" `
  (Join-Path $PackagingDir "installer.iss")

Write-Host "Installer ready in $InstallerOutDir"
