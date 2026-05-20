; Inno Setup script for WH-347 Audit Engine
; Build: ISCC installer.iss  (after PyInstaller produces dist\WH347 Audit Engine\)

[Setup]
AppName=WH-347 Audit Engine
AppVersion=1.0.1
AppPublisher=Stodola Construction
AppPublisherURL=https://github.com/ethanstod/Audit-App-v2
AppSupportURL=https://github.com/ethanstod/Audit-App-v2/issues
DefaultDirName={autopf}\WH347 Audit Engine
DefaultGroupName=WH-347 Audit Engine
AllowNoIcons=yes
OutputBaseFilename=WH347-Audit-Engine-Setup
OutputDir=dist
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Run without admin if user has no admin rights
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checked

[Files]
Source: "dist\WH347 Audit Engine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\WH-347 Audit Engine"; Filename: "{app}\WH347 Audit Engine.exe"
Name: "{group}\Uninstall WH-347 Audit Engine"; Filename: "{uninstallexe}"
Name: "{autodesktop}\WH-347 Audit Engine"; Filename: "{app}\WH347 Audit Engine.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\WH347 Audit Engine.exe"; Description: "{cm:LaunchProgram,WH-347 Audit Engine}"; Flags: nowait postinstall skipifsilent
