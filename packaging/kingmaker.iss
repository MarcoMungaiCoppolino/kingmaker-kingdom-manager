; Inno Setup script for Kingmaker Kingdom Manager.
;
;   ISCC /DAppVersion=1.1.0 /DSourceDir=dist\Kingmaker Kingdom Manager ^
;        /DOutputDir=packaging\out /DOutputName=Kingmaker-Kingdom-Manager-1.1.0-Setup kingmaker.iss
;
; packaging/build.py passes the four defines. Per-user install, no
; administrator rights: the game lives next to the program (saves\, assets\),
; so the folder must be the user's own. Updates replace only _internal\;
; the uninstaller asks whether to delete the game too.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\Kingmaker Kingdom Manager"
#endif
#ifndef OutputDir
  #define OutputDir "out"
#endif
#ifndef OutputName
  #define OutputName "Kingmaker-Kingdom-Manager-Setup"
#endif

#define AppName "Kingmaker Kingdom Manager"
#define AppExe "Kingmaker Kingdom Manager.exe"
#define AppPublisher "Marco Mungai Coppolino"
#define AppURL "https://github.com/MarcoMungaiCoppolino/kingmaker-kingdom-manager"

[Setup]
AppId={{7C1B4A7E-2E7A-4D8B-9A3B-5F2C0E6D1A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile=icon\kingmaker.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[CustomMessages]
english.DeleteGame=Also delete your game — the saves and the images in%n%1 ?%n%nChoose No to keep them for a later install.
italian.DeleteGame=Cancellare anche la partita — i salvataggi e le immagini in%n%1 ?%n%nScegli No per conservarli per una prossima installazione.
english.KeptGame=Your game was kept in%n%1
italian.KeptGame=La tua partita è rimasta in%n%1
english.DesktopIcon=Create a &desktop shortcut
italian.DesktopIcon=Crea un collegamento sul &desktop

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; An update replaces the program whole: stale libraries of the previous
; version must not survive next to the new ones. saves\ and assets\ are
; never listed here.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\saves"
Name: "{app}\assets"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// The uninstaller removes what it installed; the game is the user's, so it
// asks. Yes: the whole folder goes. No: saves\ and assets\ stay, and a
// message says where.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Game: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Game := ExpandConstant('{app}');
    if DirExists(Game + '\saves') or DirExists(Game + '\assets') then
    begin
      if MsgBox(FmtMessage(CustomMessage('DeleteGame'), [Game]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Game, True, True, True)
      else if not UninstallSilent then
        MsgBox(FmtMessage(CustomMessage('KeptGame'), [Game]), mbInformation, MB_OK);
    end;
  end;
end;
