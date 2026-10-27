; VoiceAssist installer: one file, no administrator rights, works on Windows 7 SP1 and newer, 32- and 64-bit.
; Saved as UTF-8 with BOM: without it Inno Setup reads the Russian text and file names as ANSI.
; Everything goes into the user's own profile, so updates and removal never need a password.

#define AppName "Vega"
#define AppVersion "0.6.9"

[Setup]
AppId={{6C1F7E7A-4E55-4C8B-9A9E-0B7C5D1A2F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=VoiceAssist
DefaultDirName={localappdata}\Programs\VoiceAssist
DefaultGroupName=Vega
PrivilegesRequired=lowest
#ifdef Universal
; Ivan, 2026-10-27: one installer for every Windows from 7 SP1. On 64-bit Windows it installs the
; 64-bit programs and Piper; on 32-bit Windows the 32-bit programs from dist32 and a 32-bit Piper
; from piper32 (Piper has no official 32-bit version, so piper-x86.yml builds it).
ArchitecturesInstallIn64BitMode=x64
#else
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
#endif
OutputBaseFilename=Vega-Setup
MinVersion=6.1sp1
OutputDir=Output
Compression=lzma2/max
SolidCompression=yes
SetupIconFile=..\assets\vega.ico
DisableProgramGroupPage=yes
UninstallDisplayName=Vega — голосовой помощник
WizardStyle=classic
; A silent self-update must never stop halfway because a file is still in use (Ivan, 2026-10-27:
; after «проверь обновления» Vega no longer started): programs holding Vega's files are closed.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "autostart"; Description: "Запускать Вегу при входе в Windows (рекомендуется)"
Name: "desktopicon"; Description: "Значок на рабочем столе"

[Files]
; PyInstaller 5 one-folder builds keep the DLLs next to each exe. All three come from the same
; Python and packages, so the shared files are identical and one folder serves all three exes.
#ifdef Universal
Source: "..\dist\VoiceAssist\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Check: Is64BitInstallMode
Source: "..\dist\VoiceAssistSetup\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Check: Is64BitInstallMode
Source: "..\dist\VoiceAssistNativeHost\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Check: Is64BitInstallMode
Source: "..\dist32\VoiceAssist\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Check: not Is64BitInstallMode
Source: "..\dist32\VoiceAssistSetup\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Check: not Is64BitInstallMode
Source: "..\dist32\VoiceAssistNativeHost\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion; Check: not Is64BitInstallMode
#else
Source: "..\dist\VoiceAssist\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\dist\VoiceAssistSetup\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\dist\VoiceAssistNativeHost\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
#endif
Source: "..\third_party\vosk-model-small-ru-0.22\*"; DestDir: "{app}\model"; Flags: recursesubdirs ignoreversion
Source: "..\third_party\piper\*"; DestDir: "{app}\piper"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist; Check: Is64BitInstallMode
; 32-bit Windows (Ivan's test laptop, 2026-10-27): Piper built for 32 bits (.github/workflows/piper-x86.yml), same voice Irina.
Source: "..\piper32\*"; DestDir: "{app}\piper"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist; Check: not Is64BitInstallMode
Source: "..\third_party\piper\ru_RU-irina-medium.onnx*"; DestDir: "{app}\piper"; Flags: ignoreversion skipifsourcedoesntexist; Check: not Is64BitInstallMode
Source: "..\third_party\rhvoice\*"; DestDir: "{app}\rhvoice"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist
Source: "..\third_party\nvda\nvdaControllerClient64.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\third_party\nvda\nvdaControllerClient32.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\chrome_extension\*"; DestDir: "{app}\chrome_extension"; Flags: recursesubdirs ignoreversion
; Windows 7 SP1 without update KB3063858 (Ivan, 2026-10-27: people cannot be asked to install updates):
; the installer puts it in itself, from these Microsoft files, without the internet or Windows Update.
Source: "..\third_party\kb\windows6.1-kb3063858-x86.msu"; Flags: dontcopy skipifsourcedoesntexist
Source: "..\third_party\kb\windows6.1-kb3063858-x64.msu"; Flags: dontcopy skipifsourcedoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\COMPATIBILITY.md"; DestDir: "{app}"; Flags: ignoreversion
; The installer's guide opens in Notepad on any Windows: .md has no program on Windows 7.
Source: "..\ИНСТРУКЦИЯ.md"; DestDir: "{app}"; DestName: "ИНСТРУКЦИЯ.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\Vega"; Filename: "{app}\VoiceAssist.exe"; Parameters: "--voice --model ""{app}\model"""
Name: "{group}\Инструкция Vega"; Filename: "{app}\ИНСТРУКЦИЯ.txt"
Name: "{group}\Удалить Vega"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Vega"; Filename: "{app}\VoiceAssist.exe"; Parameters: "--voice --model ""{app}\model"""; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VoiceAssist"; \
  ValueData: """{app}\VoiceAssist.exe"" --voice --model ""{app}\model"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
; Russian Windows voice for Windows 7, which has none: the free RHVoice SAPI installers, if they were bundled.
; It registers a system voice, so Windows asks for permission (shellexec shows that request).
Filename: "{app}\rhvoice\RHVoice-voice-Russian-Aleksandr.exe"; Parameters: "/S"; StatusMsg: "Устанавливаю русский голос RHVoice…"; \
  Flags: skipifdoesntexist waituntilterminated shellexec; Check: NoRussianVoice and not VegaUpdate
; Link with Chrome: the extension has a fixed ID (see chrome_extension\EXTENSION_ID.txt).
Filename: "{app}\VoiceAssistSetup.exe"; Parameters: "--register-extension-id jdnfenolnkkdfhdphjapooponmobhjhb --native-host-exe ""{app}\VoiceAssistNativeHost.exe"""; \
  StatusMsg: "Связываю Вегу с Chrome…"; Flags: runhidden waituntilterminated
Filename: "{app}\VoiceAssist.exe"; Parameters: "--voice --model ""{app}\model"""; Description: "Запустить Вегу"; Flags: postinstall nowait skipifsilent; Check: not KbInstalled
; Vega updated herself (voiceassist\updater.py runs this installer silently with /vegaupdate=1): start the new one.
Filename: "{app}\VoiceAssist.exe"; Parameters: "--voice --model ""{app}\model"""; Flags: nowait; Check: VegaUpdate

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM VoiceAssist.exe /F"; Flags: runhidden; RunOnceId: "StopVoiceAssist"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: files; Name: "{userappdata}\VoiceAssist\gemini.json"

[Code]
// Python 3.8 (inside Vega) loads its libraries with AddDllDirectory. Plain Windows 7 SP1 lacks it
// until update KB2533623 / KB3063858 (or the KB3125574 rollup); without it Vega would not start.
function GetModuleHandle(Name: String): THandle; external 'GetModuleHandleW@kernel32.dll stdcall';
function GetProcAddress(Module: THandle; Name: AnsiString): THandle; external 'GetProcAddress@kernel32.dll stdcall';

var
  KbDone: Boolean;

function NeedsKb(): Boolean;
begin
  Result := GetProcAddress(GetModuleHandle('kernel32.dll'), 'AddDllDirectory') = 0;
end;

// KB3063858 was put in just now: Windows uses it only after a restart, so Vega starts after it.
function KbInstalled(): Boolean;
begin
  Result := KbDone;
end;

function NeedRestart(): Boolean;
begin
  Result := KbDone;
end;

// DISM takes the update straight from the .msu, so it works even where Windows Update is switched off
// (many home builds of Windows 7). wusa is the second try. A 32-bit installer on 64-bit Windows must
// call the 64-bit DISM through Sysnative. Windows asks for permission once (runas).
function InstallKb(): String;
var
  Name, Script: String;
  Code: Integer;
begin
  Result := '';
  if IsWin64 then Name := 'windows6.1-kb3063858-x64.msu' else Name := 'windows6.1-kb3063858-x86.msu';
  try
    ExtractTemporaryFile(Name);
  except
    Result := 'в установщике нет файла обновления';
    exit;
  end;
  Script := ExpandConstant('{tmp}\kb.cmd');
  SaveStringToFile(Script,
    '@echo off' + #13#10 +
    'set "SYS=%SystemRoot%\System32"' + #13#10 +
    'if exist "%SystemRoot%\Sysnative\dism.exe" set "SYS=%SystemRoot%\Sysnative"' + #13#10 +
    'cd /d "%~dp0"' + #13#10 +
    'if not exist kb mkdir kb' + #13#10 +
    '"%SYS%\expand.exe" -F:* "' + Name + '" kb >nul' + #13#10 +
    'for %%C in (kb\Windows6.1-KB3063858-*.cab) do "%SYS%\dism.exe" /online /add-package /packagepath:"%%~fC" /quiet /norestart' + #13#10 +
    'set RC=%errorlevel%' + #13#10 +
    'if "%RC%"=="0" exit /b 0' + #13#10 +
    'if "%RC%"=="3010" exit /b 0' + #13#10 +
    '"%SYS%\wusa.exe" "%~dp0' + Name + '" /quiet /norestart' + #13#10 +
    'set RC2=%errorlevel%' + #13#10 +
    'if "%RC2%"=="3010" exit /b 0' + #13#10 +
    'if "%RC2%"=="2359302" exit /b 0' + #13#10 +
    'exit /b %RC2%' + #13#10, False);
  WizardForm.StatusLabel.Caption := 'Устанавливается обновление Windows KB3063858, нужное Веге. Это займёт пару минут...';
  if not ShellExec('runas', ExpandConstant('{cmd}'), '/C ""' + Script + '""', ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, Code) then
    Result := 'Windows не дала разрешение (' + SysErrorMessage(Code) + ')'
  else if Code <> 0 then
    Result := 'код ' + IntToStr(Code)
  else
    KbDone := True;
end;

// Vega's own silent self-update (voiceassist\updater.py): no questions, no Chrome download, Vega starts again.
function VegaUpdate(): Boolean;
begin
  Result := ExpandConstant('{param:vegaupdate|0}') = '1';
end;

// A Russian Windows voice is registered under Speech\Voices\Tokens with Language 419 (hex LCID of Russian).
function NoRussianVoice(): Boolean;
var
  Names: TArrayOfString;
  I: Integer;
  Language: String;
begin
  Result := True;
  if RegGetSubkeyNames(HKLM, 'SOFTWARE\Microsoft\Speech\Voices\Tokens', Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
      if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\Speech\Voices\Tokens\' + Names[I] + '\Attributes', 'Language', Language) then
        if Pos('419', Language) > 0 then
          Result := False;
end;


// Two editions (Ivan, 2026-10-15): standard, or with Gemini, which hears again the phrases Vega did not
// understand. The Gemini key is pasted here and saved to %APPDATA%\VoiceAssist\gemini.json.
var
  EditionPage: TInputOptionWizardPage;
  KeyPage: TInputQueryWizardPage;

function KeyFile(): String;
begin
  Result := ExpandConstant('{userappdata}\VoiceAssist\gemini.json');
end;

function SavedKey(): String;
var
  Text: AnsiString;
  Start: Integer;
begin
  Result := '';
  if LoadStringFromFile(KeyFile(), Text) then
  begin
    Start := Pos('"key"', Text);
    if Start > 0 then
    begin
      Text := Copy(Text, Start + 5, Length(Text));
      Start := Pos('"', Text);
      Text := Copy(Text, Start + 1, Length(Text));
      Result := Copy(Text, 1, Pos('"', Text) - 1);
    end;
  end;
end;

procedure OpenKeySite(Sender: TObject);
var
  Code: Integer;
begin
  ShellExec('open', 'https://aistudio.google.com/apikey', '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

procedure InitializeWizard();
var
  Button: TNewButton;
begin
  EditionPage := CreateInputOptionPage(wpSelectTasks, 'Вариант Веги', 'Обычная или с ИИ Gemini?',
    'Обычная работает без интернета. С Gemini Вега лучше понимает неразборчивую речь и команды своими словами: ' +
    'фразы, которые она не поняла сама, отправляются в Google Gemini. Нужен интернет и бесплатный ключ Google.',
    True, False);
  EditionPage.Add('Обычная (без интернета)');
  EditionPage.Add('С Gemini (лучше понимает, нужен ключ)');
  if SavedKey() <> '' then
    EditionPage.SelectedValueIndex := 1
  else
    EditionPage.SelectedValueIndex := 0;

  KeyPage := CreateInputQueryPage(EditionPage.ID, 'Ключ Gemini', 'Как получить бесплатный ключ (2 минуты)',
    '1. Нажмите кнопку «Открыть сайт Google» ниже и войдите в свой Google (почта Gmail и пароль).' + #13#10 +
    '2. Если сайт спросит согласие с условиями, отметьте галочку и нажмите «Continue».' + #13#10 +
    '3. Справа вверху нажмите «Create API key».' + #13#10 +
    '4. В окне «Create a new key» имя не меняйте. В поле «Choose an imported project» выберите любой проект. ' +
    'Если список пуст, выберите «Create project», впишите Vega и нажмите «Create»: проект встанет в это поле.' + #13#10 +
    '5. Нажмите «Create key». Откроется окно «API key details» с ключом (длинная строка). Нажмите внизу «Copy key».' + #13#10 +
    '6. Вернитесь сюда, щёлкните в поле «Ключ» и нажмите Ctrl+V. Затем «Далее».');
  KeyPage.Add('Ключ:', False);
  KeyPage.Values[0] := SavedKey();

  Button := TNewButton.Create(KeyPage);
  Button.Parent := KeyPage.Surface;
  Button.Caption := 'Открыть сайт Google';
  Button.Width := ScaleX(180);
  Button.Height := ScaleY(26);
  Button.Top := KeyPage.Edits[0].Top + KeyPage.Edits[0].Height + ScaleY(12);
  Button.Left := KeyPage.Edits[0].Left;
  Button.OnClick := @OpenKeySite;
end;

function WithGemini(): Boolean;
begin
  Result := EditionPage.SelectedValueIndex = 1;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = KeyPage.ID) and not WithGemini();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Key: String;
begin
  Result := True;
  if CurPageID = KeyPage.ID then
  begin
    Key := Trim(KeyPage.Values[0]);
    KeyPage.Values[0] := Key;
    if Key = '' then
    begin
      MsgBox('Вставьте ключ в поле «Ключ» (Ctrl+V) или вернитесь назад и выберите обычную Вегу.', mbError, MB_OK);
      Result := False;
    end
    else if (Pos('"', Key) > 0) or (Pos(' ', Key) > 0) then
    begin
      MsgBox('В ключе не должно быть пробелов и кавычек. Скопируйте его ещё раз кнопкой «Copy key».', mbError, MB_OK);
      Result := False;
    end
    else if (Copy(Key, 1, 4) <> 'AIza') and (Copy(Key, 1, 3) <> 'AQ.') then
      Result := MsgBox('Обычно ключ начинается с AQ. или AIza. Всё равно использовать этот?', mbConfirmation, MB_YESNO) = IDYES;
  end;
end;

// Ivan, 2026-10-15: Vega works with Google Chrome; when there is none, the installer puts it in by itself.
function ChromeInstalled(): Boolean;
begin
  Result := RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe') or
            RegKeyExists(HKLM, 'Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe') or
            FileExists(ExpandConstant('{localappdata}\Google\Chrome\Application\chrome.exe')) or
            FileExists(ExpandConstant('{commonpf32}\Google\Chrome\Application\chrome.exe')) or
            (IsWin64 and FileExists(ExpandConstant('{commonpf64}\Google\Chrome\Application\chrome.exe')));
end;

// Google's online installer gives each Windows the newest Chrome it supports (109 on Windows 7 and 8).
procedure InstallChrome();
var
  Code: Integer;
begin
  if ChromeInstalled() or VegaUpdate() then
    exit;
  WizardForm.StatusLabel.Caption := 'Скачивается и устанавливается Google Chrome. Это может занять несколько минут...';
  try
    DownloadTemporaryFile('https://dl.google.com/chrome/install/latest/chrome_installer.exe', 'chrome_installer.exe', '', nil);
    Exec(ExpandConstant('{tmp}\chrome_installer.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code);
  except
    Log('Chrome download failed: ' + GetExceptionMessage);
  end;
  if not ChromeInstalled() then
    MsgBox('Google Chrome установить не удалось (нет интернета или Google не дал установщик). ' +
           'Vega работает и без него; Chrome можно поставить позже и запустить установщик Vega ещё раз.', mbInformation, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    InstallChrome();
    if WithGemini() then
    begin
      ForceDirectories(ExpandConstant('{userappdata}\VoiceAssist'));
      SaveStringToFile(KeyFile(), '{"key": "' + Trim(KeyPage.Values[0]) + '"}', False);
    end
    else
      DeleteFile(KeyFile());
  end;
end;

// An older Vega may still run (autostart): stop it so its files can be replaced and the new one starts.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  Problem: String;
begin
  // taskkill returns before Windows lets go of the files, so wait a little before replacing them.
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /T /IM VoiceAssist.exe & taskkill /F /T /IM VoiceAssistNativeHost.exe & taskkill /F /IM piper.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(3000);
  Result := '';
  if NeedsKb() then
  begin
    Problem := InstallKb();
    if Problem <> '' then
      MsgBox('Не удалось установить обновление Windows KB3063858 (' + Problem + '). Без него Вега на этой Windows 7 не запустится.' + #13#10 + #13#10 +
        'Запустите установку Веги ещё раз и разрешите изменения, когда Windows спросит.', mbError, MB_OK);
  end;
end;
