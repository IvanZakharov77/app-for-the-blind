"""Read-only IMAPI 2 capability probe for optical CD/DVD drives."""

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Tuple


@dataclass(frozen=True)
class OpticalProbe:
    drive_count: int
    writer_count: int
    ready_writer_count: int
    # (IMAPI index, free bytes, drive root such as "E:\\") for writers holding blank media.
    ready_drives: Tuple[Tuple[int, int, str], ...] = ()


def parse_probe_output(output: bytes) -> OpticalProbe:
    try:
        lines = output.decode("ascii").strip().splitlines()
        kind, total = lines[0].split("|")
        if kind != "TOTAL":
            raise ValueError("Нет ответа IMAPI.")
        drive_count = int(total)
        if not 0 <= drive_count <= 32 or len(lines) != drive_count + 1:
            raise ValueError("Неверное число приводов.")
        writers = ready = 0
        ready_drives = []
        indexes = set()
        for line in lines[1:]:
            fields = line.split("|")
            if len(fields) not in (6, 7) or fields[0] != "DRIVE":
                raise ValueError("Неверные данные привода.")
            index, supported, media, status, sectors = map(int, fields[1:6])
            root = fields[6].strip() if len(fields) == 7 else ""
            if index in indexes or not 0 <= index < drive_count:
                raise ValueError("Повтор привода.")
            indexes.add(index)
            if supported:
                writers += 1
                if media and status & 2 and not status & 0xFC00 and sectors > 0:
                    ready += 1
                    ready_drives.append((index, sectors * 2048, root))
        return OpticalProbe(drive_count, writers, ready, tuple(ready_drives))
    except (UnicodeError, IndexError, TypeError, ValueError) as error:
        raise ValueError("Не удалось прочитать ответ IMAPI.") from error


_PROBE_SCRIPT = r'''
Option Explicit
On Error Resume Next
Dim master, recorder, writer, index, supported, media, status, sectors, root
Set master = CreateObject("IMAPI2.MsftDiscMaster2")
If Err.Number <> 0 Then WScript.Quit(2)
WScript.Echo "TOTAL|" & master.Count
For index = 0 To master.Count - 1
    supported = 0
    media = 0
    status = 0
    sectors = 0
    root = ""
    Err.Clear
    Set recorder = CreateObject("IMAPI2.MsftDiscRecorder2")
    recorder.InitializeDiscRecorder(master.Item(index))
    If Err.Number = 0 Then
        Err.Clear
        root = recorder.VolumePathNames(0)
        If Err.Number <> 0 Then root = ""
        Err.Clear
        Set writer = CreateObject("IMAPI2.MsftDiscFormat2Data")
        writer.Recorder = recorder
        If Err.Number = 0 Then
            Err.Clear
            If writer.IsRecorderSupported(recorder) Then supported = -1
            If Err.Number <> 0 Then supported = 0
            If supported <> 0 Then
                Err.Clear
                If writer.IsCurrentMediaSupported(recorder) Then media = -1
                If Err.Number <> 0 Then media = 0
                If media <> 0 Then
                    Err.Clear
                    status = writer.CurrentMediaStatus
                    If Err.Number <> 0 Then status = 0
                    Err.Clear
                    sectors = writer.FreeSectorsOnMedia
                    If Err.Number <> 0 Then sectors = 0
                End If
            End If
        End If
    End If
    WScript.Echo "DRIVE|" & index & "|" & supported & "|" & media & "|" & status & "|" & sectors & "|" & root
Next
'''


def probe_optical() -> OpticalProbe:
    if sys.platform != "win32":
        raise OSError("Проверка оптического привода доступна только на Windows.")
    cscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cscript.exe"
    with TemporaryDirectory(prefix="voiceassist-optical-") as folder:
        script = Path(folder, "probe.vbs")
        script.write_text(_PROBE_SCRIPT, encoding="ascii")
        result = subprocess.run([str(cscript), "//B", "//Nologo", str(script)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=15, check=False)
    if result.returncode != 0:
        raise OSError("IMAPI или Windows Script Host недоступен.")
    return parse_probe_output(result.stdout)
