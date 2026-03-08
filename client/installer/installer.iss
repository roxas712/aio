; Inno Setup script for AIO v2 Windows client (agent + kiosk + embedded Python + platform installers)

#define AppName "AIO Game Terminal v2"
#define AppVersion "0.2.0"
#define Publisher "PGOC"
#define PythonTargetDir "C:\\Program Files\\Python314"
#define PythonExePath "C:\\Program Files\\Python314\\python.exe"
#define OrcaVertDir "C:\\Program Files\\OrcaVertical"

[Setup]
AppId={{A8D54648-3C9E-4A8D-9B8B-2BAF3B1F0A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={pf}\aio
DefaultGroupName={#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
Compression=lzma
SolidCompression=yes
OutputBaseFilename=AIOv2-Setup
ArchitecturesInstallIn64BitMode=x64

SetupLogging=yes

; --- PGOC Branding / Theming ---
WizardStyle=modern
WizardImageFile="C:\AIOv2\deps\PGOC_Logo.png"
WizardSmallImageFile="C:\AIOv2\deps\PGOC_Logo.png"
WizardImageStretch=no

SetupIconFile="C:\AIOv2\deps\ic_launcher.ico"
UninstallDisplayIcon="{app}\launcher\launcher.exe"

; Colors use BGR format. Here we use a dark background with gold accent.
BackColor=$00101010
BackColor2=$00202020
BackColorDirection=ttopbottom

[Dirs]
; Core app directories
Name: "{app}\agent"; Flags: uninsalwaysuninstall
Name: "{app}\kiosk"; Flags: uninsalwaysuninstall
Name: "{app}\kiosk\img"; Flags: uninsalwaysuninstall
Name: "{app}\kiosk\vids"; Flags: uninsalwaysuninstall
Name: "{app}\config"; Flags: uninsalwaysuninstall
Name: "{app}\logs"; Flags: uninsalwaysuninstall
Name: "{app}\games"; Flags: uninsalwaysuninstall
Name: "{app}\deps"; Flags: uninsalwaysuninstall
; 3rd-party platform installers
Name: "{app}\platform_installs"; Flags: uninsalwaysuninstall
; ProgramData for AIO wallpaper
Name: "{commonappdata}\aio"; Flags: uninsalwaysuninstall
; ProgramData AIO config
Name: "{commonappdata}\aio\config"; Flags: uninsalwaysuninstall
; ProgramData AIO logs (agent writes here)
Name: "{commonappdata}\aio\logs"; Flags: uninsalwaysuninstall
; Public Documents for Bomgar / AIO tools
Name: "{commondocs}\aio"; Flags: uninsalwaysuninstall

[Files]
; --- Agent ---
Source: "C:\AIOv2\build\bin\agent.exe"; DestDir: "{app}\agent"; Flags: ignoreversion
Source: "C:\AIOv2\tools\nssm.exe"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "C:\AIOv2\agent\watchdog.py"; DestDir: "{app}\agent"; Flags: ignoreversion

; --- Kiosk Python scripts (Windows versions) ---
Source: "C:\AIOv2\kiosk\win_common.py";      DestDir: "{app}\kiosk"; Flags: ignoreversion
Source: "C:\AIOv2\kiosk\activation_win.py";  DestDir: "{app}\kiosk"; Flags: ignoreversion
Source: "C:\AIOv2\kiosk\updater_win.py";     DestDir: "{app}\kiosk"; Flags: ignoreversion
Source: "C:\AIOv2\kiosk\multi_win.py";       DestDir: "{app}\kiosk"; Flags: ignoreversion
Source: "C:\AIOv2\kiosk\single_win.py";      DestDir: "{app}\kiosk"; Flags: ignoreversion
Source: "C:\AIOv2\kiosk\return.py";          DestDir: "{app}\kiosk"; Flags: ignoreversion
Source: "C:\AIOv2\kiosk\loading.py";         DestDir: "{app}\kiosk"; Flags: ignoreversion

; --- Images / assets ---
Source: "C:\AIOv2\kiosk\img\*";  DestDir: "{app}\kiosk\img"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "C:\AIOv2\kiosk\vids\*"; DestDir: "{app}\kiosk\vids"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- Native Launcher (single-file) ---
Source: "C:\AIOv2\launcher\publish\launcher.exe"; DestDir: "{app}\launcher"; DestName: "launcher.exe"; Flags: ignoreversion

; --- AIO Wallpaper image ---
Source: "C:\AIOv2\deps\aio_wall.png"; DestDir: "{commonappdata}\aio"; DestName: "aio_wall.png"; Flags: ignoreversion

[Icons]
; Start Menu shortcut to native launcher (AIO kiosk)
Name: "{group}\Launch {#AppName}"; Filename: "{app}\launcher\launcher.exe"; WorkingDir: "{app}\launcher"

; Desktop shortcut for kiosk
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\launcher\launcher.exe"; WorkingDir: "{app}\launcher"

; Startup folder shortcut (auto-start on user login)
Name: "{commonstartup}\{#AppName}"; Filename: "{app}\launcher\launcher.exe"; WorkingDir: "{app}\launcher"

; Orca Vertical shortcuts (separate from Orca Horizontal)
Name: "{group}\Orca Vertical"; Filename: "{#OrcaVertDir}\Orca_Vertical.exe"; WorkingDir: "{#OrcaVertDir}"
Name: "{commondesktop}\Orca Vertical"; Filename: "{#OrcaVertDir}\Orca_Vertical.exe"; WorkingDir: "{#OrcaVertDir}"

[Run]
; --- Force policy refresh after hardening ---
Filename: "gpupdate.exe"; Parameters: "/force"; Flags: runhidden waituntilterminated
; 1) Download and install Python if not present (silent)
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\python-3.14.1-amd64.exe"" ""https://pgoc.ai/installers/python-3.14.1-amd64.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading Python 3.14..."; \
    Check: not PythonInstalled
Filename: "{tmp}\python-3.14.1-amd64.exe"; \
    Parameters: "/quiet InstallAllUsers=1 PrependPath=1 TargetDir=""{#PythonTargetDir}"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Python 3.14..."; \
    Check: not PythonInstalled

; 2) Upgrade pip (hidden)
Filename: "{#PythonExePath}"; \
    Parameters: "-m pip install --upgrade pip"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Upgrading pip..."; \
    Check: PythonInstalled

; 3) Install required Python packages (PyQt5, PyQtWebEngine, psutil, requests, websockets)
Filename: "{#PythonExePath}"; \
    Parameters: "-m pip install PyQt5 PyQtWebEngine psutil requests websockets"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Python dependencies (PyQt5, PyQtWebEngine, psutil, requests, websockets)..."; \
    Check: PythonInstalled


; 3b) Ensure MachineId is present in registry for Windows terminals
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{tmp}\aio_set_machineid.ps1"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Writing MachineId to registry..."

; 3c) Create default client.json for agent (server_url + ping_path + version)
Filename: "powershell.exe"; \
    Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{tmp}\aio_init_clientjson.ps1"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Creating default agent config (client.json)..."

; 3d) Copy agent client.json into ProgramData as a diagnostic fallback
Filename: "cmd.exe"; \
    Parameters: "/C if not exist ""{commonappdata}\aio\config"" mkdir ""{commonappdata}\aio\config"" & copy /Y ""{app}\config\client.json"" ""{commonappdata}\aio\config\client.json"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Saving client.json to ProgramData..."

; 4) Download and install .NET 8 runtime (required for Orca Vertical)
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\runtime_8.exe"" ""https://pgoc.ai/installers/runtime_8.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading .NET 8 runtime..."
Filename: "{tmp}\runtime_8.exe"; \
    Parameters: "/quiet /norestart"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing .NET 8 runtime..."

; 5) Download and install Google Chrome silently (for Golden Dragon City)
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\ChromeSetup.exe"" ""https://pgoc.ai/installers/chrome_setup.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading Google Chrome installer..."
Filename: "{tmp}\ChromeSetup.exe"; \
    Parameters: "/silent /install"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Google Chrome..."

; 6) Download and install Firefox silently (for Classic Online)
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\FirefoxSetup.exe"" ""https://pgoc.ai/installers/firefox_setup.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading Firefox installer..."
Filename: "{tmp}\FirefoxSetup.exe"; \
    Parameters: "-ms"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Firefox..."

; 7) Download and install Fire Phoenix silently (EXE)
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\firephoenix.exe"" ""https://pgoc.ai/installers/firephoenix.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading Fire Phoenix installer..."
Filename: "{tmp}\firephoenix.exe"; \
    Parameters: "/silent"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Fire Phoenix..."

; 8) Download and install Golden Dragon City silently (EXE)
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\PlayGDInstaller.exe"" ""https://pgoc.ai/installers/playgd.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading Golden Dragon City installer..."
Filename: "{tmp}\PlayGDInstaller.exe"; \
    Parameters: "/silent"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Golden Dragon City..."

; Kill any Golden Dragon City processes that auto-started
Filename: "taskkill.exe"; Parameters: "/IM playgd.exe /T /F"; \
    Flags: runhidden; StatusMsg: "Stopping Golden Dragon City (if running)..."
Filename: "taskkill.exe"; Parameters: "/IM chrome.exe /T /F"; \
    Flags: runhidden; StatusMsg: "Stopping Chrome (if launched by GDC)..."

; 9) Download and install Orca Horizontal silently (EXE)
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\Orca_Horizontal_Install.exe"" ""https://pgoc.ai/installers/orca_horizontal.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading Orca (Horizontal) installer..."
Filename: "{tmp}\Orca_Horizontal_Install.exe"; \
    Parameters: "/silent"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Orca (Horizontal)..."

; 10) Download and install Orca Vertical silently (MSI) to its own folder on C:
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\Orca_Vertical_Setup.msi"" ""https://pgoc.ai/installers/orca_vertical.msi"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading Orca (Vertical) installer..."
Filename: "msiexec.exe"; \
    Parameters: "/i ""{tmp}\Orca_Vertical_Setup.msi"" INSTALLDIR=""{#OrcaVertDir}"" /qn /norestart"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing Orca (Vertical)..."

; Kill any Orca processes that auto-started
Filename: "taskkill.exe"; Parameters: "/IM Orca.exe /T /F"; \
    Flags: runhidden; StatusMsg: "Stopping Orca (if running)..."
Filename: "taskkill.exe"; Parameters: "/IM playorca.mobi.exe /T /F"; \
    Flags: runhidden; StatusMsg: "Stopping Orca browser shell (if running)..."

; Download Bomgar remote support client to Public Documents\aio
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{commondocs}\aio\bomgar-scc-w0eec30jzfffee5wi1eizdy65hf5yg7jf5zgfyjc40hc90.exe"" ""https://pgoc.ai/installers/bomgar-scc-w0eec30jzfffee5wi1eizdy65hf5yg7jf5zgfyjc40hc90.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading Bomgar remote support client..."

; 11) Disable hibernation & sleep, set performance power plan
Filename: "powercfg.exe"; Parameters: "-setactive SCHEME_MIN";              Flags: runhidden waituntilterminated; StatusMsg: "Setting High Performance power plan..."
Filename: "powercfg.exe"; Parameters: "-change -monitor-timeout-ac 0";      Flags: runhidden waituntilterminated; StatusMsg: "Disabling display sleep (AC)..."
Filename: "powercfg.exe"; Parameters: "-change -monitor-timeout-dc 0";      Flags: runhidden waituntilterminated; StatusMsg: "Disabling display sleep (DC)..."
Filename: "powercfg.exe"; Parameters: "-change -standby-timeout-ac 0";      Flags: runhidden waituntilterminated; StatusMsg: "Disabling standby (AC)..."
Filename: "powercfg.exe"; Parameters: "-change -standby-timeout-dc 0";      Flags: runhidden waituntilterminated; StatusMsg: "Disabling standby (DC)..."
Filename: "powercfg.exe"; Parameters: "-hibernate off";                     Flags: runhidden waituntilterminated; StatusMsg: "Disabling hibernation..."

; 12) Disable Windows Update services
Filename: "sc.exe"; Parameters: "stop wuauserv";                  Flags: runhidden waituntilterminated; StatusMsg: "Stopping Windows Update service..."
Filename: "sc.exe"; Parameters: "config wuauserv start= disabled"; Flags: runhidden waituntilterminated; StatusMsg: "Disabling Windows Update service..."
Filename: "sc.exe"; Parameters: "stop UsoSvc";                    Flags: runhidden waituntilterminated; StatusMsg: "Stopping Update Orchestrator..."
Filename: "sc.exe"; Parameters: "config UsoSvc start= disabled";  Flags: runhidden waituntilterminated; StatusMsg: "Disabling Update Orchestrator..."

; 12b) Disable Windows Update Medic Service (prevents Windows from re-enabling updates)
Filename: "sc.exe"; Parameters: "stop WaaSMedicSvc";                  Flags: runhidden waituntilterminated; StatusMsg: "Stopping Windows Update Medic..."
Filename: "sc.exe"; Parameters: "config WaaSMedicSvc start= disabled"; Flags: runhidden waituntilterminated; StatusMsg: "Disabling Windows Update Medic..."

; 12c) Disable BITS and Delivery Optimization (often used to fetch updates)
Filename: "sc.exe"; Parameters: "stop bits";                  Flags: runhidden waituntilterminated; StatusMsg: "Stopping BITS..."
Filename: "sc.exe"; Parameters: "config bits start= disabled"; Flags: runhidden waituntilterminated; StatusMsg: "Disabling BITS..."
Filename: "sc.exe"; Parameters: "stop DoSvc";                  Flags: runhidden waituntilterminated; StatusMsg: "Stopping Delivery Optimization..."
Filename: "sc.exe"; Parameters: "config DoSvc start= disabled"; Flags: runhidden waituntilterminated; StatusMsg: "Disabling Delivery Optimization..."

; 12d) Disable common Windows Update scheduled tasks
Filename: "schtasks.exe"; Parameters: "/Change /TN ""\\Microsoft\\Windows\\UpdateOrchestrator\\Schedule Scan"" /Disable"; Flags: runhidden waituntilterminated; StatusMsg: "Disabling UpdateOrchestrator Schedule Scan..."
Filename: "schtasks.exe"; Parameters: "/Change /TN ""\\Microsoft\\Windows\\UpdateOrchestrator\\USO_UxBroker"" /Disable"; Flags: runhidden waituntilterminated; StatusMsg: "Disabling UpdateOrchestrator USO_UxBroker..."
Filename: "schtasks.exe"; Parameters: "/Change /TN ""\\Microsoft\\Windows\\UpdateOrchestrator\\Reboot"" /Disable"; Flags: runhidden waituntilterminated; StatusMsg: "Disabling UpdateOrchestrator Reboot task..."
Filename: "schtasks.exe"; Parameters: "/Change /TN ""\\Microsoft\\Windows\\WindowsUpdate\\Scheduled Start"" /Disable"; Flags: runhidden waituntilterminated; StatusMsg: "Disabling WindowsUpdate Scheduled Start..."

; 13) Disable Windows Firewall for all profiles
Filename: "netsh.exe"; Parameters: "advfirewall set allprofiles state off"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Disabling Windows Firewall...";

; 14) Set all network connection profiles to Private
Filename: "powershell.exe"; Parameters: "-Command ""Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private"""; \
    Flags: runhidden waituntilterminated; StatusMsg: "Setting network profiles to Private..."

; 14b) Set AIO wallpaper for the current user
Filename: "reg.exe"; \
    Parameters: "add ""HKCU\Control Panel\Desktop"" /v Wallpaper /t REG_SZ /d ""{commonappdata}\aio\aio_wall.png"" /f"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Configuring desktop wallpaper..."

; Configure wallpaper style: Fill (WallpaperStyle=10, TileWallpaper=0)
Filename: "reg.exe"; \
    Parameters: "add ""HKCU\Control Panel\Desktop"" /v WallpaperStyle /t REG_SZ /d 10 /f"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Setting wallpaper style..."
Filename: "reg.exe"; \
    Parameters: "add ""HKCU\Control Panel\Desktop"" /v TileWallpaper /t REG_SZ /d 0 /f"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Disabling wallpaper tiling..."

; Force wallpaper reload so it applies immediately
Filename: "RUNDLL32.EXE"; \
    Parameters: "USER32.DLL,UpdatePerUserSystemParameters"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Applying desktop wallpaper..."

; 15) Download and install GPU driver based on user selection

; NVIDIA GT 1030
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\gt1030.exe"" ""https://pgoc.ai/installers/gt1030.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading NVIDIA GT 1030 driver installer..."; \
    Check: IsGT1030Selected
Filename: "{tmp}\gt1030.exe"; \
    Parameters: "/s"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing NVIDIA GT 1030 driver..."; \
    Check: IsGT1030Selected

; AMD RX 550
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\rx550.exe"" ""https://pgoc.ai/installers/rx550.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading AMD RX 550 driver installer..."; \
    Check: IsRX550Selected
Filename: "{tmp}\rx550.exe"; \
    Parameters: "/S"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing AMD RX 550 driver..."; \
    Check: IsRX550Selected

; AMD RX 6400
Filename: "cmd.exe"; \
    Parameters: "/C curl -L -o ""{tmp}\rx6400.exe"" ""https://pgoc.ai/installers/rx6400.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Downloading AMD RX 6400 driver installer..."; \
    Check: IsRX6400Selected
Filename: "{tmp}\rx6400.exe"; \
    Parameters: "/S"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing AMD RX 6400 driver..."; \
    Check: IsRX6400Selected

; 16) Remove game auto-start entries from HKCU\...\Run (Orca & Fire Phoenix)
Filename: "reg.exe"; \
    Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v ""electron.app.Orca"" /f"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Removing Orca auto-start entry from HKCU..."
Filename: "reg.exe"; \
    Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v ""electron.app.FirePhoenix"" /f"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Removing Fire Phoenix auto-start entry from HKCU..."


; --- Install AIO Agent using NSSM ---
Filename: "{app}\tools\nssm.exe"; \
    Parameters: "install AIOAgent ""{app}\agent\agent.exe"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing AIO Agent service..."

Filename: "{app}\tools\nssm.exe"; \
    Parameters: "set AIOAgent Start SERVICE_AUTO_START"; \
    Flags: runhidden waituntilterminated

Filename: "{app}\tools\nssm.exe"; \
    Parameters: "set AIOAgent AppDirectory ""{app}\agent"""; \
    Flags: runhidden waituntilterminated

Filename: "{app}\tools\nssm.exe"; \
    Parameters: "start AIOAgent"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Starting AIO Agent service..."

; --- Install AIO Watchdog service ---
Filename: "{app}\tools\nssm.exe"; \
    Parameters: "install AIOWatchdog ""{#PythonExePath}"" ""{app}\agent\watchdog.py"""; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Installing AIO Watchdog service..."

Filename: "{app}\tools\nssm.exe"; \
    Parameters: "set AIOWatchdog AppDirectory ""{app}\agent"""; \
    Flags: runhidden waituntilterminated

Filename: "{app}\tools\nssm.exe"; \
    Parameters: "set AIOWatchdog Start SERVICE_AUTO_START"; \
    Flags: runhidden waituntilterminated

Filename: "{app}\tools\nssm.exe"; \
    Parameters: "start AIOWatchdog"; \
    Flags: runhidden waituntilterminated; \
    StatusMsg: "Starting AIO Watchdog service..."

; 18) Auto-start the kiosk app once installer completes (no checkbox)
Filename: "{app}\launcher\launcher.exe"; \
    Flags: nowait postinstall skipifsilent; \
    Check: PythonInstalled

; --- Lock down filesystem for kiosk user (deny writes outside AIO) ---
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Desktop"" /deny *S-1-5-32-545:(W,M)"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Documents"" /deny *S-1-5-32-545:(W,M)"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Downloads"" /deny *S-1-5-32-545:(W,M)"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Pictures"" /deny *S-1-5-32-545:(W,M)"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Videos"" /deny *S-1-5-32-545:(W,M)"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Music"" /deny *S-1-5-32-545:(W,M)"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""C:\Users\Public\Documents"" /deny *S-1-5-32-545:(W,M)"; Flags: runhidden waituntilterminated

; --- Explicitly allow AIO data directory ---
Filename: "cmd.exe"; Parameters: "/C icacls ""C:\ProgramData\aio"" /grant *S-1-5-32-545:(OI)(CI)(M)"; Flags: runhidden waituntilterminated


[Registry]

; --- Disable UAC ---
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "EnableLUA"; ValueData: 0; Flags: uninsdeletevalue

; --- Disable Lock Screen ---
Root: HKLM; Subkey: "SOFTWARE\Policies\Microsoft\Windows\Personalization"; ValueType: dword; ValueName: "NoLockScreen"; ValueData: 1; Flags: uninsdeletevalue

; --- Disable automatic Windows Updates ---
Root: HKLM; Subkey: "SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"; ValueType: dword; ValueName: "NoAutoUpdate"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"; ValueType: dword; ValueName: "AUOptions"; ValueData: 1; Flags: uninsdeletevalue

; --- Lock down Task Manager ---
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "DisableTaskMgr"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "DisableTaskMgr"; ValueData: 1; Flags: uninsdeletevalue

; --- Disable Win keys ---
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"; ValueType: dword; ValueName: "NoWinKeys"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer"; ValueType: dword; ValueName: "NoWinKeys"; ValueData: 1; Flags: uninsdeletevalue

; --- Replace Explorer shell with AIO launcher ---
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"; ValueType: string; ValueName: "Shell"; ValueData: "{app}\launcher\launcher.exe"; Flags: uninsdeletevalue

; --- Suppress Windows Security & notifications ---
Root: HKLM; Subkey: "SOFTWARE\Policies\Microsoft\Windows Defender Security Center\Notifications"; ValueType: dword; ValueName: "DisableNotifications"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Policies\Microsoft\Windows\Explorer"; ValueType: dword; ValueName: "DisableNotificationCenter"; ValueData: 1; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\PushNotifications"; ValueType: dword; ValueName: "ToastEnabled"; ValueData: 0; Flags: uninsdeletevalue

; --- Disable USB mass storage ---
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Services\USBSTOR"; ValueType: dword; ValueName: "Start"; ValueData: 4; Flags: uninsdeletevalue

; --- Harden Ctrl+Alt+Del (machine) ---
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "DisableLockWorkstation"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "DisableLogoff"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "DisableChangePassword"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "HideFastUserSwitching"; ValueData: 1; Flags: uninsdeletevalue

; --- Harden Ctrl+Alt+Del (user) ---
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "DisableLockWorkstation"; ValueData: 1; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "DisableLogoff"; ValueData: 1; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "DisableChangePassword"; ValueData: 1; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Policies\System"; ValueType: dword; ValueName: "HideFastUserSwitching"; ValueData: 1; Flags: uninsdeletevalue

; --- Suppress file dialogs ---
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer"; ValueType: dword; ValueName: "NoFileMenu"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer"; ValueType: dword; ValueName: "NoViewContextMenu"; ValueData: 1; Flags: uninsdeletevalue
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer"; ValueType: dword; ValueName: "NoFolderOptions"; ValueData: 1; Flags: uninsdeletevalue

; --- Disable Alt+F4 (Scancode Map) ---
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Keyboard Layout"; ValueType: binary; ValueName: "Scancode Map"; ValueData: 00 00 00 00 00 00 00 00 02 00 00 00 00 00 3E 00 00 00 00 00; Flags: uninsdeletevalue

[UninstallDelete]
; Cleanup logs/config/games/deps/platform_installs and Bomgar folder
Type: filesandordirs; Name: "{app}\config"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\games"
Type: filesandordirs; Name: "{app}\deps"
Type: filesandordirs; Name: "{app}\platform_installs"
Type: filesandordirs; Name: "{commondocs}\aio"
Type: filesandordirs; Name: "{commonappdata}\aio\config"
Type: filesandordirs; Name: "{commonappdata}\aio\logs"

; Remove installed game/browser applications deployed by this installer
Type: filesandordirs; Name: "C:\Program Files (x86)\FirePhoenix"
Type: filesandordirs; Name: "C:\Program Files (x86)\Orca"
Type: filesandordirs; Name: "C:\Program Files\OrcaVertical"
Type: filesandordirs; Name: "C:\Program Files (x86)\PlayGD"
Type: filesandordirs; Name: "C:\Program Files (x86)\Mozilla Firefox"
Type: filesandordirs; Name: "C:\Program Files\Mozilla Firefox"
Type: filesandordirs; Name: "C:\Program Files (x86)\Google\Chrome"
Type: filesandordirs; Name: "C:\Program Files\Google\Chrome"

[Code]

var
  SelectedGPU: Integer;

const
  GPU_GT1030 = 1;
  GPU_RX550  = 2;
  GPU_RX6400 = 3;
  GPU_OTHER  = 4;

function PythonInstalled: Boolean;
begin
  { Simple check: does the target python.exe exist? }
  Result := FileExists('{#PythonExePath}');
end;

function IsGT1030Selected: Boolean;
begin
  Result := SelectedGPU = GPU_GT1030;
end;

function IsRX550Selected: Boolean;
begin
  Result := SelectedGPU = GPU_RX550;
end;

function IsRX6400Selected: Boolean;
begin
  Result := SelectedGPU = GPU_RX6400;
end;

var
  TermsPage: TWizardPage;
  TermsMemo: TNewMemo;
  TermsCheck: TNewCheckBox;
  GPUPage: TWizardPage;
  rbGT1030, rbRX550, rbRX6400, rbOther: TNewRadioButton;
  GpuInfoLabel: TNewStaticText;

procedure GPUOptionClick(Sender: TObject);
begin
  { Show recommendation text when "Other/None" is selected }
  if rbOther.Checked then
    GpuInfoLabel.Visible := True
  else
    GpuInfoLabel.Visible := False;
end;

procedure InitializeWizard;
var
  lbl: TNewStaticText;
begin
  { Terms / Service Agreement page }
  TermsPage := CreateCustomPage(
    wpWelcome,
    'Terms and Service Agreement',
    'Please review and accept the following terms before continuing.'
  );

  TermsMemo := TNewMemo.Create(TermsPage.Surface);
  TermsMemo.Parent := TermsPage.Surface;
  TermsMemo.Left := 0;
  TermsMemo.Top := 0;
  TermsMemo.Width := TermsPage.SurfaceWidth;
  TermsMemo.Height := ScaleY(200);
  TermsMemo.ReadOnly := True;
  TermsMemo.ScrollBars := ssVertical;
  TermsMemo.Text :=
    'This installer and the AIO Game Terminal v2 software are proprietary to Prestige Group of Companies (PGOC).'#13#10#13#10 +
    'All components, including but not limited to the kiosk application, agent, updater, and supporting scripts,'#13#10 +
    'were designed and developed by Troy Moore for use by PGOC and its authorized partners.'#13#10#13#10 +
    'Copying, cloning, reverse engineering, redistribution, or unauthorized replication of this software, its assets,'#13#10 +
    'or its configuration is strictly prohibited unless you have written permission from PGOC.'#13#10#13#10 +
    'By proceeding with this installation, you acknowledge that this software is provided for use on approved kiosk systems'#13#10 +
    'only and may not be used as a general-purpose desktop environment. Misuse, tampering, or deploying this software'#13#10 +
    'on non-approved systems is grounds for termination of access and may be subject to legal action.'#13#10#13#10 +
    'If you do not agree to these terms, cancel the installation now.';

  TermsCheck := TNewCheckBox.Create(TermsPage.Surface);
  TermsCheck.Parent := TermsPage.Surface;
  TermsCheck.Caption := 'I have read and agree to the terms above.';
  TermsCheck.Left := 0;
  TermsCheck.Top := TermsMemo.Top + TermsMemo.Height + ScaleY(8);
  TermsCheck.Width := TermsPage.SurfaceWidth;

  { GPU selection page }
  GPUPage := CreateCustomPage(
    TermsPage.ID,
    'Select Your GPU',
    'Choose the GPU installed in this system. This determines which driver (if any) will be installed.'
  );

  rbGT1030 := TNewRadioButton.Create(GPUPage.Surface);
  rbGT1030.Parent := GPUPage.Surface;
  rbGT1030.Caption := 'NVIDIA GT 1030';
  rbGT1030.Left := 0;
  rbGT1030.Top := ScaleY(16);
  rbGT1030.OnClick := @GPUOptionClick;

  rbRX550 := TNewRadioButton.Create(GPUPage.Surface);
  rbRX550.Parent := GPUPage.Surface;
  rbRX550.Caption := 'AMD RX 550';
  rbRX550.Left := 0;
  rbRX550.Top := rbGT1030.Top + ScaleY(24);
  rbRX550.OnClick := @GPUOptionClick;

  rbRX6400 := TNewRadioButton.Create(GPUPage.Surface);
  rbRX6400.Parent := GPUPage.Surface;
  rbRX6400.Caption := 'AMD RX 6400';
  rbRX6400.Left := 0;
  rbRX6400.Top := rbRX550.Top + ScaleY(24);
  rbRX6400.OnClick := @GPUOptionClick;

  rbOther := TNewRadioButton.Create(GPUPage.Surface);
  rbOther.Parent := GPUPage.Surface;
  rbOther.Caption := 'Other / None';
  rbOther.Left := 0;
  rbOther.Top := rbRX6400.Top + ScaleY(24);
  rbOther.Checked := True;  { default }
  rbOther.OnClick := @GPUOptionClick;

  GpuInfoLabel := TNewStaticText.Create(GPUPage.Surface);
  GpuInfoLabel.Parent := GPUPage.Surface;
  GpuInfoLabel.Left := 0;
  GpuInfoLabel.Top := rbOther.Top + ScaleY(32);
  GpuInfoLabel.Width := GPUPage.SurfaceWidth;
  GpuInfoLabel.Caption :=
    'Note: A dedicated 4GB GPU is highly recommended for proper functionality of the All In One system.'#13#10#13#10 +
    'For best results, PGOC recommends one of the following GPUs:'#13#10 +
    ' - NVIDIA GT 1030'#13#10 +
    ' - AMD RX 550'#13#10 +
    ' - AMD RX 6400';
  GpuInfoLabel.WordWrap := True;
  GpuInfoLabel.Visible := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  { Enforce agreement to terms }
  if CurPageID = TermsPage.ID then
  begin
    if not TermsCheck.Checked then
    begin
      MsgBox('You must agree to the terms to continue.', mbError, MB_OK);
      Result := False;
      exit;
    end;
  end;

  { Capture GPU selection when leaving GPU page }
  if CurPageID = GPUPage.ID then
  begin
    if rbGT1030.Checked then
      SelectedGPU := GPU_GT1030
    else if rbRX550.Checked then
      SelectedGPU := GPU_RX550
    else if rbRX6400.Checked then
      SelectedGPU := GPU_RX6400
    else
      SelectedGPU := GPU_OTHER;
  end;
end;

procedure WriteTextFile(const FilePath: string; const Contents: string);
begin
  SaveStringToFile(FilePath, Contents, False);
end;

procedure PrepareAioPowerShellScripts();
var
  p1, p2: string;
  s1, s2: string;
begin
  p1 := ExpandConstant('{tmp}\\aio_set_machineid.ps1');
  p2 := ExpandConstant('{tmp}\\aio_init_clientjson.ps1');

  s1 :=
    '$ErrorActionPreference = ''SilentlyContinue''' + #13#10 +
    '$u = (Get-CimInstance Win32_ComputerSystemProduct).UUID' + #13#10 +
    'if ($u -and $u -ne "00000000-0000-0000-0000-000000000000") {' + #13#10 +
    '  New-Item -Path "HKLM:\SOFTWARE\PGOC\AIO" -Force | Out-Null' + #13#10 +
    '  New-ItemProperty -Path "HKLM:\SOFTWARE\PGOC\AIO" -Name "MachineId" -Value $u -PropertyType String -Force | Out-Null' + #13#10 +
    '}' + #13#10;

  s2 :=
    '$ErrorActionPreference = ''SilentlyContinue''' + #13#10 +
    '$p = ''' + ExpandConstant('{app}\config\client.json') + '''' + #13#10 +
    'if (!(Test-Path $p)) {' + #13#10 +
    '  $verPath = ''' + ExpandConstant('{app}\config\version.json') + '''' + #13#10 +
    '  $ver = "1.17"' + #13#10 +
    '  if (Test-Path $verPath) {' + #13#10 +
    '    try {' + #13#10 +
    '      $j = Get-Content $verPath -Raw | ConvertFrom-Json' + #13#10 +
    '      if ($j.Version) { $ver = $j.Version } elseif ($j.version) { $ver = $j.version }' + #13#10 +
    '    } catch {}' + #13#10 +
    '  }' + #13#10 +
    '  $obj = @{ uuid = ''''; server_url = ''https://pgoc.ai''; ping_path = ''/client/ping''; poll_interval_idle = 60; poll_interval_active = 300; app_version = $ver; terminal_type = ''multi''; lock_status = ''unlocked'' }' + #13#10 +
    '  ($obj | ConvertTo-Json -Depth 5) | Set-Content -Encoding UTF8 $p' + #13#10 +
    '}' + #13#10;

  WriteTextFile(p1, s1);
  WriteTextFile(p2, s2);
end;

// Ensure scripts exist before the [Run] section tries to execute them
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    PrepareAioPowerShellScripts();
  end;
end;
[UninstallRun]
Filename: "{app}\tools\nssm.exe"; Parameters: "stop AIOAgent"; Flags: runhidden waituntilterminated;
Filename: "{app}\tools\nssm.exe"; Parameters: "remove AIOAgent confirm"; Flags: runhidden waituntilterminated;
; --- Remove AIO Watchdog service ---
Filename: "{app}\tools\nssm.exe"; Parameters: "stop AIOWatchdog"; Flags: runhidden waituntilterminated
Filename: "{app}\tools\nssm.exe"; Parameters: "remove AIOWatchdog confirm"; Flags: runhidden waituntilterminated
Filename: "reg.exe"; \
  Parameters: "add ""HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"" /v Shell /t REG_SZ /d explorer.exe /f"; \
  Flags: runhidden waituntilterminated

; --- Restore filesystem permissions on uninstall ---
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Desktop"" /remove:d *S-1-5-32-545"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Documents"" /remove:d *S-1-5-32-545"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Downloads"" /remove:d *S-1-5-32-545"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Pictures"" /remove:d *S-1-5-32-545"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Videos"" /remove:d *S-1-5-32-545"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""%USERPROFILE%\Music"" /remove:d *S-1-5-32-545"; Flags: runhidden waituntilterminated
Filename: "cmd.exe"; Parameters: "/C icacls ""C:\Users\Public\Documents"" /remove:d *S-1-5-32-545"; Flags: runhidden waituntilterminated
; --- Restore USB mass storage on uninstall ---
Filename: "reg.exe"; \
  Parameters: "add ""HKLM\SYSTEM\CurrentControlSet\Services\USBSTOR"" /v Start /t REG_DWORD /d 3 /f"; \
  Flags: runhidden waituntilterminated

; --- Restore keyboard scancode mappings ---
Filename: "reg.exe"; \
  Parameters: "delete ""HKLM\SYSTEM\CurrentControlSet\Control\Keyboard Layout"" /v ""Scancode Map"" /f"; \
  Flags: runhidden waituntilterminated