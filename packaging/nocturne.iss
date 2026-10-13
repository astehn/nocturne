; Inno Setup 6 script for the Windows installer. Compiled by build_windows.ps1:
;
;     ISCC.exe /DAppVersion=0.51.0 /DAppVersionNum=0.51.0.0 packaging\nocturne.iss
;
; Packs dist\Nocturne (the PyInstaller directory) into
; dist\Nocturne-<version>-windows-x64-setup.exe. Pure ASCII on purpose: Inno
; reads a BOM-less script in the system code page.
;
; Per-user, no admin: the same place GraXpert installs, so a user without an
; administrator account can install and update. Everything the installer writes
; is under the user's own profile and HKCU.
;
; ~\.nocturne (settings, models, logs, recent projects) is NEVER named here, so
; neither an upgrade nor the uninstaller can touch it.

#ifndef AppVersion
  #error Pass /DAppVersion=<version> (build_windows.ps1 reads it from nocturne\__init__.py)
#endif
#ifndef AppVersionNum
  #define AppVersionNum "0.0.0.0"
#endif

[Setup]
; THE APPID MUST NEVER CHANGE. It is the key of the uninstall entry and what
; makes the next version an upgrade in place rather than a second install.
AppId={{572EA84D-F5DE-45FE-925E-91A4B4AB96C9}
AppName=Nocturne
AppVersion={#AppVersion}
AppVerName=Nocturne {#AppVersion}
AppPublisher=Andreas Stehn
AppPublisherURL=https://nocturneastro.com
AppSupportURL=https://nocturneastro.com
VersionInfoVersion={#AppVersionNum}
VersionInfoProductVersion={#AppVersionNum}
VersionInfoProductTextVersion={#AppVersion}

PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Nocturne
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

SetupIconFile=nocturne.ico
UninstallDisplayIcon={app}\Nocturne.exe
OutputDir=..\dist
OutputBaseFilename=Nocturne-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Restart Manager: an upgrade while Nocturne is running from {app} asks to
; close it instead of failing on a locked file. It is not restarted: the user
; may have unsaved work they would rather reopen themselves.
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; The previous version's Python bundle goes first: a module or DLL that a newer
; build no longer ships would otherwise linger and could be imported in place
; of the right one.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Nocturne\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Nocturne"; Filename: "{app}\Nocturne.exe"
Name: "{autodesktop}\Nocturne"; Filename: "{app}\Nocturne.exe"; Tasks: desktopicon

[Registry]
; HKA is HKCU\Software\Classes in a per-user install.
; .nocturne is Nocturne's own format, so Nocturne owns it.
Root: HKA; Subkey: "Software\Classes\.nocturne"; ValueType: string; ValueName: ""; ValueData: "Nocturne.Project"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.nocturne\OpenWithProgids"; ValueType: string; ValueName: "Nocturne.Project"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\Nocturne.Project"; ValueType: string; ValueName: ""; ValueData: "Nocturne project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Nocturne.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\Nocturne.exe"",0"
Root: HKA; Subkey: "Software\Classes\Nocturne.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Nocturne.exe"" ""%1"""

; FITS belongs to whatever the user already opens it with (ASTAP, Siril, PixInsight):
; Nocturne is only OFFERED under "Open with". The extensions' default value is
; never written, so it cannot be changed or removed by install or uninstall.
Root: HKA; Subkey: "Software\Classes\Nocturne.Image"; ValueType: string; ValueName: ""; ValueData: "FITS image"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Nocturne.Image\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\Nocturne.exe"",0"
Root: HKA; Subkey: "Software\Classes\Nocturne.Image\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Nocturne.exe"" ""%1"""
; The bare extension keys only so that a key this installer created is not left
; behind empty; uninstall works backwards, so the OpenWithProgids below go first.
Root: HKA; Subkey: "Software\Classes\.fits"; Flags: uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.fit"; Flags: uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.fts"; Flags: uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.fits\OpenWithProgids"; ValueType: string; ValueName: "Nocturne.Image"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.fit\OpenWithProgids"; ValueType: string; ValueName: "Nocturne.Image"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.fts\OpenWithProgids"; ValueType: string; ValueName: "Nocturne.Image"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty

[Run]
Filename: "{app}\Nocturne.exe"; Description: "{cm:LaunchProgram,Nocturne}"; Flags: nowait postinstall skipifsilent
