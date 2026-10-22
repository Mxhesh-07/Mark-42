; Tier 2 E2 — Inno Setup installer for MARK-42 (JARVIS).
;
; Build the app first (see docs/REPRODUCIBLE.md):
;     python -m agent.build stage && pyinstaller MarkJarvis.spec
; then compile this file with Inno Setup 6 (ISCC.exe packaging\installer.iss).
;
; Nothing here embeds credentials: config/ is created on first run by the
; wizard and api_keys.json is gitignored, not shipped. The [Files] section
; pulls the frozen bundle that agent.build.verify() has already scanned.

#define AppName "MARK-42"
#define AppVersion "0.1.0"
#define AppPublisher "MARK-42"
#define AppExe "JARVIS.exe"
#define SourceDir "..\dist\JARVIS"

[Setup]
AppId={{5C0B54E1-0F6E-4A6B-9D5C-7C2E1C9A4B31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=MARK-42-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExe}
; E4 note: when a signing certificate is available, set SignTool here and in
; the [Files] section (see docs/REPRODUCIBLE.md "Code signing"). Unsigned
; builds deliberately do not pretend to be signed.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; The bundle is built and verified by agent.build (credentials scanned out).
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; First run opens the wizard inside the app (agent/first_run.py): API key, then
; the microphone with a live level meter. No key is ever written by the
; installer, so an unattended install can never ship one.
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Runtime state lives outside {app} only if the user moved it; nothing to add
; here on purpose — an uninstall must not guess which memory to delete.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
