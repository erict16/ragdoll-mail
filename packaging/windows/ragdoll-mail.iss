; Ragdoll Mail Windows Installer (Inno Setup 6)
; Modelled on S2Arm's per-user installer pattern:
; - Installs under %LOCALAPPDATA%\Programs\Ragdoll Mail (no admin / UAC required)
; - Places uninstaller outside {app} so future atomic in-app updates never lose Uninstall
; - Supports silent in-place upgrades (/VERYSILENT /NORESTART /CLOSEAPPLICATIONS)
; - Adds install dir to user PATH (optional, checked by default) so `ragdoll` CLI works in terminals
; - Preserves user config & local mail index on uninstall

#ifndef AppVersion
  #define AppVersion "0.12.0"
#endif

#define AppName "Ragdoll Mail"
#define AppExeName "Ragdoll Mail.exe"
#define CliExeName "ragdoll.exe"
#define AppPublisher "Ragdoll Mail"
#define AppURL "https://github.com/erict16/ragdoll-mail"

[Setup]
AppId={{8F2A91B4-4E7C-4D32-9C81-2A6B5D4E10F7}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
UninstallFilesDir={localappdata}\RagdollMail\Uninstall
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableDirPage=auto
DirExistsWarning=no
OutputDir=..\..\dist
OutputBaseFilename=ragdoll-mail-windows-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
ChangesEnvironment=yes
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addpath"; Description: "Add ragdoll CLI to user PATH"; GroupDescription: "Command-line tool:"

[Files]
Source: "..\..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\{#CliExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up app binaries and any atomic self-update swap leftovers, keeping user data intact
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{localappdata}\Programs\Ragdoll Mail.old"
Type: filesandordirs; Name: "{localappdata}\Programs\Ragdoll Mail.new"

[Code]
const
  EnvKey = 'Environment';

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + UpperCase(Param) + ';', ';' + UpperCase(OrigPath) + ';') = 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OrigPath, NewPath, AppDir: string;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addpath') then
  begin
    AppDir := ExpandConstant('{app}');
    if NeedsAddPath(AppDir) then
    begin
      if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', OrigPath) then
        OrigPath := '';
      if (Length(OrigPath) > 0) and (OrigPath[Length(OrigPath)] <> ';') then
        NewPath := OrigPath + ';' + AppDir
      else
        NewPath := OrigPath + AppDir;
      RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', NewPath);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  OrigPath, AppDir, LowerOrig, LowerDir: string;
  P: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDir := ExpandConstant('{app}');
    if RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', OrigPath) then
    begin
      LowerOrig := ';' + LowerCase(OrigPath) + ';';
      LowerDir := ';' + LowerCase(AppDir) + ';';
      P := Pos(LowerDir, LowerOrig);
      if P > 0 then
      begin
        Delete(OrigPath, P, Length(AppDir) + 1);
        if (Length(OrigPath) > 0) and (OrigPath[Length(OrigPath)] = ';') then
          Delete(OrigPath, Length(OrigPath), 1);
        if (Length(OrigPath) > 0) and (OrigPath[1] = ';') then
          Delete(OrigPath, 1, 1);
        RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvKey, 'Path', OrigPath);
      end;
    end;
  end;
end;
