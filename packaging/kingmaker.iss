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
english.KeptGame=Your game was kept in%n%1%n%nThe launcher's settings are there too, the cloud access among them (protected for this Windows user). Delete the folder yourself if this PC is leaving the table.
italian.KeptGame=La tua partita è rimasta in%n%1%n%nCi sono anche le impostazioni del launcher, accesso al cloud compreso (protetto per questo utente di Windows). Cancella la cartella tu stesso se questo PC lascia il tavolo.
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
// Before anything is removed: the launcher and the server it started must
// be gone, or their files stay locked and Windows reports "some elements
// could not be removed". Then the question about the game, asked *before*
// the program is removed: answered Yes, the whole folder goes with it;
// answered No, saves\ and assets\ are left and the uninstaller is told so
// through the message at the end.
var
  KeepGame: Boolean;

procedure StopTheApp;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#AppExe}" /T', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function InitializeUninstall(): Boolean;
begin
  StopTheApp;
  // The installers the launcher downloaded for its updates sit in %TEMP%:
  // not secrets, but not worth keeping either.
  DelTree(GetEnv('TEMP') + '\Kingmaker-Kingdom-Manager-*-Setup.exe', False, True, False);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Game: String;
begin
  Game := ExpandConstant('{app}');
  if CurUninstallStep = usUninstall then
  begin
    KeepGame := False;
    if DirExists(Game + '\saves') or DirExists(Game + '\assets') then
    begin
      if UninstallSilent or (MsgBox(FmtMessage(CustomMessage('DeleteGame'), [Game]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDNO) then
        KeepGame := True
      else
      begin
        // The launcher's settings and lock live in saves\ too: one sweep.
        DelTree(Game + '\saves', True, True, True);
        DelTree(Game + '\assets', True, True, True);
      end;
    end;
  end;
  if (CurUninstallStep = usPostUninstall) and KeepGame and not UninstallSilent then
    MsgBox(FmtMessage(CustomMessage('KeptGame'), [Game]), mbInformation, MB_OK);
end;
