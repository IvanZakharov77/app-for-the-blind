@echo off
rem Builds Vega (VoiceAssist) and its installer on Windows 7 SP1, 8.1, 10 or 11 x64. Just run it.
rem Missing tools are downloaded and installed into tools\ of this folder, for this user only,
rem without administrator rights: Python 3.8.10 x64 (the last Python for Windows 7) and Inno Setup 6.2.2.
rem Everything else is downloaded through Python (tools\fetch.py): Windows 7 PowerShell 2.0 cannot do it.
setlocal
cd /d "%~dp0"
rem set VEGA_ARCH=x86 before running to build the 32-bit installer (Vega-Setup-32bit.exe).
set "PYARCH=64"
set "PYFILE=python-3.8.10-amd64.exe"
set "REQ=requirements-voice.txt"
set "ISSARCH="
set "SETUPNAME=Vega-Setup.exe"
if /i "%VEGA_ARCH%"=="x86" (
  set "PYARCH=32"
  set "PYFILE=python-3.8.10.exe"
  set "REQ=requirements-voice-x86.txt"
  set "ISSARCH=/DArch32"
  set "SETUPNAME=Vega-Setup-32bit.exe"
)
set "HERE=%CD%"
if not exist tools mkdir tools

rem ---- Windows 7: Python 3.8 needs update KB3063858 (or KB2533623) ----
ver | findstr /c:" 6.1." >nul
if not errorlevel 1 (
  wmic qfe get hotfixid 2>nul | findstr /i "KB2533623 KB3063858 KB3125574" >nul
  if errorlevel 1 echo WARNING: update KB3063858 is not found. If Python fails to start, install KB3063858 x64 from catalog.update.microsoft.com.
)

rem ---- Python 3.8 x64 ----
set "PY="
if exist "%HERE%\tools\python38\python.exe" set PY="%HERE%\tools\python38\python.exe"
if not defined PY (
  py -3.8-%PYARCH% -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=py -3.8-%PYARCH%"
)
if not defined PY (
  echo Python 3.8.10 not found: downloading and installing it into tools\python38 ...
  if not exist "%HERE%\tools\%PYFILE%" call :download https://www.python.org/ftp/python/3.8.10/%PYFILE% "%HERE%\tools\%PYFILE%"
  if not exist "%HERE%\tools\%PYFILE%" goto :manual_python
  "%HERE%\tools\%PYFILE%" /quiet InstallAllUsers=0 TargetDir="%HERE%\tools\python38" Include_launcher=0 Include_test=0 Include_doc=0 Include_tcltk=0 Shortcuts=0 AssociateFiles=0 PrependPath=0
  if exist "%HERE%\tools\python38\python.exe" set PY="%HERE%\tools\python38\python.exe"
)
if not defined PY (
  rem Python 3.8.10 was already registered elsewhere: the quiet installer keeps that place.
  py -3.8-%PYARCH% -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=py -3.8-%PYARCH%"
)
if not defined PY goto :manual_python
echo Python: %PY%

if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
.venv\Scripts\python.exe -m pip install --upgrade "pip<24.1"
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m pip install -r %REQ% pyinstaller==5.13.2
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m unittest discover -s tests
if errorlevel 1 goto :fail

rem ---- Inno Setup 6 ----
set "ISCC="
for %%P in ("%HERE%\tools\inno\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
  if not defined ISCC if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
  echo Inno Setup 6 not found: downloading and installing 6.2.2 into tools\inno ...
  .venv\Scripts\python.exe tools\fetch.py https://files.jrsoftware.org/is/6/innosetup-6.2.2.exe "%HERE%\tools\innosetup-6.2.2.exe"
  if not errorlevel 1 "%HERE%\tools\innosetup-6.2.2.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /NOICONS /DIR="%HERE%\tools\inno"
  if exist "%HERE%\tools\inno\ISCC.exe" set "ISCC=%HERE%\tools\inno\ISCC.exe"
)

rem ---- Third-party parts that are not in the repository (all free): see installer\THIRD-PARTY.md ----
if not exist third_party mkdir third_party
if not exist third_party\vosk-model-small-ru-0.22 (
  .venv\Scripts\python.exe tools\fetch.py https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip third_party\vosk-ru.zip --unzip third_party
  if errorlevel 1 (echo Could not download the Vosk model. Put vosk-model-small-ru-0.22 into third_party. & goto :fail)
)
if /i "%VEGA_ARCH%"=="x86" goto :no_piper
if not exist third_party\piper\piper.exe (
  .venv\Scripts\python.exe tools\fetch.py https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip third_party\piper.zip --unzip third_party
  if errorlevel 1 echo Piper could not be downloaded. A bundled RHVoice installer is required if Piper is unavailable.
)
rem Piper needs the Visual C++ runtime, which a bare Windows 7/8 does not have (laptop log: «Голос Piper не ответил»).
rem The DLLs go next to piper.exe, so it starts without installing anything.
if exist third_party\piper\piper.exe for %%D in (msvcp140.dll vcruntime140.dll vcruntime140_1.dll msvcp140_1.dll) do (
  if not exist third_party\piper\%%D if exist "%SystemRoot%\System32\%%D" copy /y "%SystemRoot%\System32\%%D" third_party\piper\ >nul
)
if exist third_party\piper\piper.exe if not exist third_party\piper\ru_RU-irina-medium.onnx (
  .venv\Scripts\python.exe tools\fetch.py https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx third_party\piper\ru_RU-irina-medium.onnx && .venv\Scripts\python.exe tools\fetch.py https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json third_party\piper\ru_RU-irina-medium.onnx.json
  if errorlevel 1 echo Piper voice could not be downloaded. A bundled RHVoice installer is required if Piper is unavailable.
)
:no_piper
rem Windows 7 has no Russian Windows voice and Piper may not run there: always bundle RHVoice Aleksandr (SAPI).
if not exist third_party\rhvoice mkdir third_party\rhvoice
if not exist third_party\rhvoice\RHVoice-voice-Russian-Aleksandr.exe .venv\Scripts\python.exe tools\fetch.py https://github.com/RHVoice/aleksandr-rus/releases/download/4.2/RHVoice-voice-Russian-Aleksandr-v4.2.2017.22-setup.exe third_party\rhvoice\RHVoice-voice-Russian-Aleksandr.exe
if not exist third_party\rhvoice\RHVoice-voice-Russian-Aleksandr.exe echo RHVoice could not be downloaded: Windows 7 without Piper will have no Russian voice.
rem Do not produce a voice assistant installer with no bundled Russian speech option.
if not exist third_party\piper\piper.exe goto :check_rhvoice
if not exist third_party\piper\ru_RU-irina-medium.onnx goto :check_rhvoice
if not exist third_party\piper\ru_RU-irina-medium.onnx.json goto :check_rhvoice
goto :voice_ready
:check_rhvoice
if not exist third_party\rhvoice\RHVoice-voice-Russian-Aleksandr.exe (
  echo No complete Piper voice and no RHVoice installer in third_party\rhvoice.
  echo Put RHVoice there or fix the Piper download, then run this script again.
  goto :fail
)
:voice_ready

rem ---- Programs ----
rem pyttsx3 loads its SAPI driver by name and vosk loads libvosk.dll at run time: PyInstaller cannot see either.
set HIDDEN=--hidden-import pyttsx3.drivers --hidden-import pyttsx3.drivers.sapi5 --collect-all vosk
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --noconsole --name VoiceAssist --icon assets\vega.ico %HIDDEN% run_voiceassist.py
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --console --name VoiceAssistSetup %HIDDEN% run_voiceassist.py
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m PyInstaller --noconfirm --onedir --console --name VoiceAssistNativeHost run_native_host.py
if errorlevel 1 goto :fail
rem A frozen CLI startup must work before packaging the installer.
dist\VoiceAssistSetup\VoiceAssistSetup.exe --help >nul
if errorlevel 1 (
  echo The frozen VoiceAssistSetup.exe failed its startup smoke test.
  goto :fail
)

rem ---- Installer ----
if not defined ISCC (
  echo Inno Setup could not be installed: only the dist\ folders were built.
  echo Install Inno Setup 6.2.2 from https://jrsoftware.org and run this file again.
  goto :fail
)
"%ISCC%" %ISSARCH% installer\VoiceAssist.iss
if errorlevel 1 goto :fail
if not exist installer\Output\%SETUPNAME% (
  echo Inno Setup returned success but Vega-Setup.exe was not found.
  goto :fail
)
echo.
echo ============================================================
echo  DONE. The installer is ready:
echo  %HERE%\installer\Output\%SETUPNAME%
echo  Copy this one file to the user's computer and run it.
echo ============================================================
if not defined CI explorer "%HERE%\installer\Output"
if not defined CI pause
exit /b 0

:fail
echo.
echo ============================================================
echo  BUILD STOPPED. Read the lines above, fix the reason and
echo  run build-windows.cmd again: finished steps are skipped.
echo ============================================================
if not defined CI pause
exit /b 1

:download
rem Before Python exists: PowerShell with TLS 1.2 (needs .NET 4.5), then certutil (Internet Explorer 11 TLS).
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = 3072; (New-Object Net.WebClient).DownloadFile('%~1', '%~2')" >nul 2>nul
if exist "%~2" exit /b 0
certutil -urlcache -split -f "%~1" "%~2" >nul 2>nul
if exist "%~2" exit /b 0
exit /b 1

:manual_python
echo.
echo Could not install Python automatically.
echo Download https://www.python.org/ftp/python/3.8.10/%PYFILE%
echo save it as tools\%PYFILE% in this folder and run this file again.
echo On Windows 7 first install update KB3063858 x64 from catalog.update.microsoft.com.
if not defined CI pause
exit /b 1
