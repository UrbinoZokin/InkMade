; Inno Setup script for packaging the Flutter Windows app.
; 1) Build app assets first with: flutter build windows --release
; 2) Open this .iss file in Inno Setup Compiler and click Build.

; ------------------ RELEASE PLACEHOLDERS ------------------
; TODO: Replace with your customer-facing app name.
#define MyAppName "Inky Impressions"
; TODO: Replace with your company / publisher name.
#define MyAppPublisher "Your Company Name"
; TODO: Keep in sync with pubspec.yaml version.
#define MyAppVersion "0.1.0"
; TODO: Replace with your Windows executable name from build\\windows\\x64\\runner\\Release.
#define MyAppExeName "desktop_app.exe"
; TODO: Update if your Flutter build output path differs.
#define MyAppSourceDir "..\\build\\windows\\x64\\runner\\Release"
; TODO: Replace with your .ico file used for installer + shortcuts.
#define MyInstallerIcon "..\\assets\\icons\\app_icon.ico"

[Setup]
AppId={{5C352F50-4D64-4A2D-90FE-EECDE6D218C9}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=InkyImpressionsInstaller_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\\{#MyAppExeName}
SetupIconFile={#MyInstallerIcon}

; Installer is fully wizard-driven (no command prompt required by end users).
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#MyAppSourceDir}\\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
; Start Menu shortcut
Name: "{group}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; IconFilename: "{#MyInstallerIcon}"
; Desktop shortcut
Name: "{autodesktop}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; IconFilename: "{#MyInstallerIcon}"

[Run]
Filename: "{app}\\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
