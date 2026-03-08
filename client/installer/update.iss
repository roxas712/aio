; aio_update.iss
; Inno Setup script for building AIO v2 update.exe
; This merges/overwrites the existing AIO installation at C:\Program Files\aio
; with the contents of C:\AIOv2\updates\aio, and updates ProgramData\aio\version.json.

#define AppName "AIO Game Terminal v2"
#define AppVersion "0.0.0"              ; Optional, not critical for the updater
#define Publisher "PGOC"
#define InstallSourceRoot "C:\\AIOv2\\updates\\aio"
#define InstallTargetRoot "C:\\Program Files\\aio"

[Setup]
AppId={{A8D54648-3C9E-4A8D-9B8B-2BAF3B1F0A10}    ; Same AppId as main installer
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={#InstallTargetRoot}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
Compression=lzma
SolidCompression=yes
OutputBaseFilename=AIOv2-Update
ArchitecturesInstallIn64BitMode=x64
SetupLogging=yes
Uninstallable=no        ; This update.exe will not appear in Add/Remove Programs

[Dirs]
; Ensure ProgramData and config directories exist
Name: "{commonappdata}\aio"; Flags: uninsneveruninstall
Name: "{commonappdata}\aio\config"; Flags: uninsneveruninstall
Name: "{app}\config"; Flags: uninsneveruninstall

[Files]
; 1) Copy all updated app files from C:\AIOv2\updates\aio into C:\Program Files\aio
;    - Recursively, preserving structure
;    - Overwrite existing files
;    - Exclude version.json (handled separately)
Source: "{#InstallSourceRoot}\*"; \
    DestDir: "{app}"; \
    Excludes: "version.json"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; 2) Copy version.json into Program Files config (authoritative for app version)
Source: "{#InstallSourceRoot}\version.json"; \
    DestDir: "{app}\config"; \
    DestName: "version.json"; \
    Flags: ignoreversion

; 3) Mirror version.json into ProgramData for agent/updater reference
Source: "{#InstallSourceRoot}\version.json"; \
    DestDir: "{commonappdata}\aio\config"; \
    DestName: "version.json"; \
    Flags: ignoreversion

[Run]
; No additional commands needed here.
; The outer updater (updater_win.py) will:
; - Download this update.exe
; - Run it silently with /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
; - Then relaunch activation_win.py

[Code]
; No custom code required for this simple merge-style update.