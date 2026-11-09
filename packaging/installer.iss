#define AppName "Workday Lens"
#ifndef AppVersion
  #define AppVersion "0.1.0-beta"
#endif
#ifndef TargetArch
  #define TargetArch "arm64"
#endif
#if TargetArch == "arm64"
  #define InstallerArchitectures "arm64"
#elif TargetArch == "x64"
  #define InstallerArchitectures "x64compatible and not arm64"
#else
  #error Unsupported TargetArch.
#endif
#ifndef SourceDir
  #error SourceDir must be provided on the ISCC command line.
#endif
#ifndef OutputDir
  #define OutputDir AddBackslash(SourcePath) + "out\installer"
#endif
#define SetupIconFilePath AddBackslash(SourcePath) + "assets\workday-lens-friendly.ico"

[Setup]
AppId={{A28A7E46-2D4E-4A35-BE3A-14C91811A301}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Rahul Meena
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
DisableProgramGroupPage=yes
Compression=lzma
SolidCompression=yes
OutputDir={#OutputDir}
OutputBaseFilename=WorkdayLensSetup-{#AppVersion}-{#TargetArch}
ArchitecturesAllowed={#InstallerArchitectures}
ArchitecturesInstallIn64BitMode={#InstallerArchitectures}
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\WorkdayLensLauncher.exe
SetupIconFile={#SetupIconFilePath}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\WorkdayLensLauncher.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\WorkdayLensLauncher.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WorkdayLensLauncher.exe"; Parameters: "--prepare-nvda-install"; StatusMsg: "Preparing bundled NVDA..."; Flags: runhidden waituntilterminated
Filename: "{app}\WorkdayLensLauncher.exe"; Parameters: "--create-portable-nvda"; StatusMsg: "Installing bundled NVDA runtime..."; Flags: runhidden waituntilterminated
Filename: "{app}\WorkdayLensLauncher.exe"; Parameters: "--install-nvda-addon"; StatusMsg: "Connecting NVDA to Workday Lens..."; Flags: runhidden waituntilterminated
Filename: "{app}\WorkdayLensLauncher.exe"; Parameters: "--finalize-nvda-install"; StatusMsg: "Finishing NVDA setup..."; Flags: runhidden waituntilterminated
Filename: "{app}\WorkdayLensLauncher.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\WorkdayLensLauncher.exe"; Parameters: "--uninstall-nvda"; StatusMsg: "Removing bundled NVDA..."; RunOnceId: "WorkdayLensUninstallNvda"; Flags: runhidden waituntilterminated
