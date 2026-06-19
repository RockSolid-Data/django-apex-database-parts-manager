; Inno Setup script -- called by build_installer.bat with /D defines

#ifndef AppName
  #define AppName "ApexDatabase"
#endif
#ifndef AppDisplayName
  #define AppDisplayName "Apex Database"
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppAuthor
  #define AppAuthor "Rock Solid Data"
#endif
#ifndef AppDescription
  #define AppDescription "Catalog, Inventory & Invoicing"
#endif
#ifndef UpgradeCode
  #define UpgradeCode "00000000-0000-0000-0000-000000000000"
#endif
#ifndef BuildDir
  #define BuildDir "build\" + AppName
#endif

[Setup]
AppId={{{#UpgradeCode}}
AppName={#AppDisplayName}
AppVersion={#AppVersion}
AppVerName={#AppDisplayName} {#AppVersion}
AppPublisher={#AppAuthor}
DefaultDirName={localappdata}\{#AppName}
DefaultGroupName={#AppDisplayName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename={#AppName}_Setup_v{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=force
CloseApplicationsFilter=*.exe
RestartApplications=no
#ifdef IconFile
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppName}.exe
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppDisplayName}"; Filename: "{app}\{#AppName}.exe"; Comment: "{#AppDescription}"
Name: "{userdesktop}\{#AppDisplayName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon
Name: "{group}\{#AppDisplayName} (Debug)"; Filename: "{app}\{#AppName}_Debug.exe"
Name: "{group}\Uninstall {#AppDisplayName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Launch {#AppDisplayName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#AppName}.exe"; Flags: runhidden; RunOnceId: "KillApp"
Filename: "taskkill"; Parameters: "/F /IM {#AppName}_Debug.exe"; Flags: runhidden; RunOnceId: "KillDebug"

[Code]
function InitializeSetup(): Boolean;
var
  MarkerPath, MarkerContent, ExistingName: String;
  MarkerAnsi: AnsiString;
  NameStart, NameEnd: Integer;
begin
  Result := True;
  MarkerPath := ExpandConstant('{localappdata}\{#AppName}\.app_identity');
  if FileExists(MarkerPath) then
  begin
    if LoadStringFromFile(MarkerPath, MarkerAnsi) then
    begin
      MarkerContent := String(MarkerAnsi);
      // Extract app_name from JSON (simple parse)
      NameStart := Pos('"app_name"', MarkerContent);
      if NameStart > 0 then
      begin
        NameStart := Pos(':', Copy(MarkerContent, NameStart, Length(MarkerContent))) + NameStart;
        NameStart := Pos('"', Copy(MarkerContent, NameStart, Length(MarkerContent))) + NameStart;
        NameEnd := Pos('"', Copy(MarkerContent, NameStart, Length(MarkerContent))) + NameStart - 1;
        ExistingName := Copy(MarkerContent, NameStart, NameEnd - NameStart);
        if (ExistingName <> '') and (ExistingName <> '{#AppName}') then
        begin
          if MsgBox('The install directory already belongs to "' + ExistingName + '".' + #13#10 +
                    'Installing {#AppDisplayName} here will overwrite it.' + #13#10#13#10 +
                    'Continue anyway?', mbConfirmation, MB_YESNO) = IDNO then
            Result := False;
        end;
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\.app_identity'),
      '{"app_name": "{#AppName}", "display_name": "{#AppDisplayName}"}', False);
end;

