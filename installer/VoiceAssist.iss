; VoiceAssist installer: one file, no administrator rights, works on Windows 7 SP1 x64 and newer.
; Saved as UTF-8 with BOM: without it Inno Setup reads the Russian text and file names as ANSI.
; Everything goes into the user's own profile, so updates and removal never need a password.

#define AppName "Vega"
#define AppVersion "0.3.5"

[Setup]
AppId={{6C1F7E7A-4E55-4C8B-9A9E-0B7C5D1A2F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=VoiceAssist
DefaultDirName={localappdata}\Programs\VoiceAssist
DefaultGroupName=Vega
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=6.1sp1
OutputDir=Output
OutputBaseFilename=Vega-Setup
Compression=lzma2/max
SolidCompression=yes
DisableProgramGroupPage=yes
UninstallDisplayName=Vega — голосовой помощник
WizardStyle=classic

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "autostart"; Description: "Запускать Вегу при входе в Windows (рекомендуется)"
Name: "desktopicon"; Description: "Значок на рабочем столе"

[Files]
Source: "..\dist\VoiceAssist\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
; PyInstaller 5 one-folder builds keep the DLLs next to each exe. All three come from the same
; Python and packages, so the shared files are identical and one folder serves all three exes.
Source: "..\dist\VoiceAssistSetup\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\dist\VoiceAssistNativeHost\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\third_party\vosk-model-small-ru-0.22\*"; DestDir: "{app}\model"; Flags: recursesubdirs ignoreversion
Source: "..\third_party\piper\*"; DestDir: "{app}\piper"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist
Source: "..\third_party\rhvoice\*"; DestDir: "{app}\rhvoice"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist
Source: "..\third_party\nvda\nvdaControllerClient64.dll"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
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
      'Установите KB3063858 для x64 из каталога Центра обновления Майкрософт (catalog.update.microsoft.com) ' +
      'или просто обновите Windows, затем запустите установку снова.', mbError, MB_OK);
    Result := False;
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
