; VoiceAssist installer: one file, no administrator rights, works on Windows 7 SP1 and newer, 32- and 64-bit.
; Saved as UTF-8 with BOM: without it Inno Setup reads the Russian text and file names as ANSI.
; Everything goes into the user's own profile, so updates and removal never need a password.

#define AppName "Vega"
#define AppVersion "0.6.3"

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
; 64-bit programs and Piper; on 32-bit Windows the 32-bit programs from dist32 (no Piper there:
; it has no 32-bit version, so Vega speaks with the Windows voice or RHVoice).
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
Source: "..\third_party\rhvoice\*"; DestDir: "{app}\rhvoice"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist
Source: "..\third_party\nvda\nvdaControllerClient64.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\third_party\nvda\nvdaControllerClient32.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\chrome_extension\*"; DestDir: "{app}\chrome_extension"; Flags: recursesubdirs ignoreversion
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
  Flags: skipifdoesntexist waituntilterminated shellexec; Check: NoRussianVoice
; Link with Chrome: the extension has a fixed ID (see chrome_extension\EXTENSION_ID.txt).
Filename: "{app}\VoiceAssistSetup.exe"; Parameters: "--register-extension-id jdnfenolnkkdfhdphjapooponmobhjhb --native-host-exe ""{app}\VoiceAssistNativeHost.exe"""; \
  StatusMsg: "Связываю Вегу с Chrome…"; Flags: runhidden waituntilterminated
Filename: "{app}\VoiceAssist.exe"; Parameters: "--voice --model ""{app}\model"""; Description: "Запустить Вегу"; Flags: postinstall nowait skipifsilent

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

function InitializeSetup(): Boolean;
begin
  Result := True;
  if GetProcAddress(GetModuleHandle('kernel32.dll'), 'AddDllDirectory') = 0 then
  begin
    MsgBox('В этой Windows 7 нет обновления KB3063858 (или KB2533623), без него Vega не запустится.' + #13#10 + #13#10 +
      'Установите KB3063858 для вашей разрядности Windows из каталога Центра обновления Майкрософт (catalog.update.microsoft.com) ' +
      'или просто обновите Windows, затем запустите установку снова.', mbError, MB_OK);
    Result := False;
  end;
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
  if ChromeInstalled() then
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
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /IM VoiceAssist.exe /F', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
