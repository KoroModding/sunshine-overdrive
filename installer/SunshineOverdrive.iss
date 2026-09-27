; Sunshine Overdrive — installateur Windows (Inno Setup 6)
;
; Installe le profil de jeu Dolphin deliver\GMSE01.ini dans
; <dossier utilisateur de Dolphin>\GameSettings\GMSE01.ini.
;   - détection du dossier utilisateur : registre de Dolphin
;     (HKCU\Software\Dolphin Emulator\UserConfigPath), puis %APPDATA%, puis
;     Documents ; modifiable (Dolphin portable : dossier « User » à côté de
;     Dolphin.exe) ;
;   - un GMSE01.ini préexistant qui n'est pas le nôtre est mis de côté
;     (GMSE01.ini.avant-sunshine-overdrive) et restauré à la désinstallation ;
;   - aucun droit administrateur ; désinstallation depuis les Paramètres ;
;   - /DOLPHINDIR="chemin" impose le dossier (installation silencieuse :
;     /VERYSILENT /SUPPRESSMSGBOXES /DOLPHINDIR="...").
;
; Construction : ISCC.exe /DAppVer=1.0.0 installer\SunshineOverdrive.iss

#ifndef AppVer
  #define AppVer "1.0.0"
#endif

[Setup]
AppId={{6B1F3C2A-8D4E-4F7A-9C21-5E0D7A3B9F10}
AppName=Sunshine Overdrive
AppVersion={#AppVer}
AppVerName=Sunshine Overdrive {#AppVer}
AppPublisher=KoroModding
AppPublisherURL=https://github.com/KoroModding/sunshine-overdrive
AppSupportURL=https://github.com/KoroModding/sunshine-overdrive/issues
DefaultDirName={localappdata}\Sunshine Overdrive
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Sunshine-Overdrive-Setup-{#AppVer}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=auto
UninstallDisplayName=Sunshine Overdrive — Super Mario Sunshine 120 FPS

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
french.DirCaption=Dossier utilisateur de Dolphin
french.DirDescription=Où Dolphin range-t-il ses réglages ?
french.DirSub=Le profil sera copié dans le sous-dossier GameSettings de ce dossier.%n%nDolphin installé normalement : le dossier détecté convient. Dolphin portable : choisissez le dossier « User » situé à côté de Dolphin.exe.
french.DirLabel=Dossier utilisateur de Dolphin :
french.NotDolphin=Ce dossier ne ressemble pas à un dossier utilisateur de Dolphin (pas de Config\Dolphin.ini).%n%nLancez Dolphin au moins une fois, ou choisissez le bon dossier.%n%nContinuer quand même ?
french.Backup=Un profil GMSE01.ini existant a été mis de côté :%n%1%nIl sera restauré si vous désinstallez Sunshine Overdrive.
french.Reminder=Sunshine Overdrive est installé.%n%nÀ savoir :%n• Démarrez (ou redémarrez) Super Mario Sunshine (NTSC-U, GMSE01) dans Dolphin.%n• N'activez aucun code Gecko ou Action Replay pour ce jeu.%n• Pour l'écran large : Graphiques > Rapport d'aspect > Forcer 16:9.%n• Il faut un PC capable d'émuler le jeu à 2× sa vitesse.
french.Restored=Le profil GMSE01.ini d'origine a été restauré.
english.DirCaption=Dolphin user folder
english.DirDescription=Where does Dolphin keep its settings?
english.DirSub=The profile will be copied to the GameSettings subfolder of this folder.%n%nRegular Dolphin install: the detected folder is fine. Portable Dolphin: pick the "User" folder next to Dolphin.exe.
english.DirLabel=Dolphin user folder:
english.NotDolphin=This folder does not look like a Dolphin user folder (no Config\Dolphin.ini).%n%nRun Dolphin at least once, or pick the right folder.%n%nContinue anyway?
english.Backup=An existing GMSE01.ini profile was set aside:%n%1%nIt will be restored if you uninstall Sunshine Overdrive.
english.Reminder=Sunshine Overdrive is installed.%n%nGood to know:%n• Start (or restart) Super Mario Sunshine (NTSC-U, GMSE01) in Dolphin.%n• Do not enable any Gecko or Action Replay code for this game.%n• For widescreen: Graphics > Aspect Ratio > Force 16:9.%n• Your PC must be able to emulate the game at 2× speed.
english.Restored=The original GMSE01.ini profile was restored.

[Files]
Source: "..\deliver\GMSE01.ini"; DestDir: "{code:DolphinDir}\GameSettings"; Flags: ignoreversion uninsneveruninstall
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
Root: HKCU; Subkey: "Software\Sunshine Overdrive"; ValueType: string; ValueName: "DolphinUserDir"; ValueData: "{code:DolphinDir}"; Flags: uninsdeletekey

[Code]
const
  MARK_NEW = 'Sunshine Overdrive';
  MARK_OLD = 'Framerate Sunshine';
  BACKUP_SUFFIX = '.avant-sunshine-overdrive';

var
  DirPage: TInputDirWizardPage;
  BackupMsg: String;

function Normalize(S: String): String;
begin
  StringChangeEx(S, '/', '\', True);
  Result := RemoveBackslashUnlessRoot(S);
end;

function DetectDolphinDir(): String;
var
  S: String;
begin
  if RegQueryStringValue(HKCU, 'Software\Dolphin Emulator', 'UserConfigPath', S) and (S <> '')
     and DirExists(Normalize(S)) then
  begin
    Result := Normalize(S);
    exit;
  end;
  S := ExpandConstant('{userappdata}\Dolphin Emulator');
  if DirExists(S) then begin Result := S; exit; end;
  S := ExpandConstant('{userdocs}\Dolphin Emulator');
  if DirExists(S) then begin Result := S; exit; end;
  Result := ExpandConstant('{userappdata}\Dolphin Emulator');
end;

function DolphinDir(Param: String): String;
begin
  Result := Normalize(DirPage.Values[0]);
end;

function IsOurs(const FileName: String): Boolean;
var
  S: AnsiString;
begin
  Result := LoadStringFromFile(FileName, S)
            and ((Pos(MARK_NEW, S) > 0) or (Pos(MARK_OLD, S) > 0));
end;

procedure InitializeWizard();
begin
  DirPage := CreateInputDirPage(wpWelcome,
    CustomMessage('DirCaption'), CustomMessage('DirDescription'),
    CustomMessage('DirSub'), False, '');
  DirPage.Add(CustomMessage('DirLabel'));
  if ExpandConstant('{param:DOLPHINDIR|}') <> '' then
    DirPage.Values[0] := ExpandConstant('{param:DOLPHINDIR|}')
  else
    DirPage.Values[0] := DetectDolphinDir();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DirPage.ID then
    if not FileExists(Normalize(DirPage.Values[0]) + '\Config\Dolphin.ini') then
      Result := MsgBox(CustomMessage('NotDolphin'), mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Target, Backup: String;
begin
  if CurStep = ssInstall then
  begin
    Target := DolphinDir('') + '\GameSettings\GMSE01.ini';
    Backup := Target + BACKUP_SUFFIX;
    ForceDirectories(DolphinDir('') + '\GameSettings');
    if FileExists(Target) and not IsOurs(Target) and not FileExists(Backup) then
      if RenameFile(Target, Backup) then
        BackupMsg := FmtMessage(CustomMessage('Backup'), [Backup]);
  end;
  if CurStep = ssDone then
  begin
    if BackupMsg <> '' then
      SuppressibleMsgBox(BackupMsg, mbInformation, MB_OK, IDOK);
    SuppressibleMsgBox(CustomMessage('Reminder'), mbInformation, MB_OK, IDOK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir, Target, Backup: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    if not RegQueryStringValue(HKCU, 'Software\Sunshine Overdrive', 'DolphinUserDir', Dir) then
      exit;
    Target := Normalize(Dir) + '\GameSettings\GMSE01.ini';
    Backup := Target + BACKUP_SUFFIX;
    if FileExists(Target) and IsOurs(Target) then
      DeleteFile(Target);
    if FileExists(Backup) and not FileExists(Target) then
      if RenameFile(Backup, Target) then
        SuppressibleMsgBox(CustomMessage('Restored'), mbInformation, MB_OK, IDOK);
  end;
end;
