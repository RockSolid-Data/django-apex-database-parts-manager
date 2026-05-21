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
; Extract media zip only on FRESH install (no existing media folder).
; On upgrades, the launcher handles incremental media sync.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Expand-Archive -LiteralPath '{src}\{#AppName}_Media.zip' -DestinationPath '{localappdata}\{#AppName}' -Force"""; StatusMsg: "Extracting media files (this may take a few minutes)..."; Flags: runhidden; Check: ShouldExtractMedia
Filename: "{app}\{#AppName}.exe"; Description: "Launch {#AppDisplayName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#AppName}.exe"; Flags: runhidden; RunOnceId: "KillApp"
Filename: "taskkill"; Parameters: "/F /IM {#AppName}_Debug.exe"; Flags: runhidden; RunOnceId: "KillDebug"

[Code]
function MediaZipExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{src}\{#AppName}_Media.zip'));
end;

function ShouldExtractMedia: Boolean;
begin
  // Only extract if the zip exists AND the media folder is not already populated
  Result := MediaZipExists
    and not DirExists(ExpandConstant('{localappdata}\{#AppName}\media\parts'));
end;
