"""Make ONNX Runtime (inside Piper) start on Windows 7 (Ivan, 2026-10-27: 0xC0000139 there).

Official onnxruntime.dll imports api-ms-win-* API sets that Windows 7 does not have, and five functions
that appeared in Windows 8. This script, run in CI on a folder with onnxruntime*.dll:
1. renames every api-ms-win-* import of those DLLs to vega7.dll (same bytes, so nothing else moves);
2. writes vega7.def: the five functions come from vega7.c, everything else is forwarded to the
   kernel32/advapi32 functions Windows 7 already has;
3. builds vega7.dll for the given architecture with MSVC and puts it next to them.
Windows 8 and newer get the real functions through vega7.c as well.

    python tools/win7_shim.py <folder> x86|x64
    python tools/win7_shim.py --check <folder>   (fails if a program there still needs Windows 8)
"""

import glob
import os
import subprocess
import sys

import pefile

SHIM = "vega7.dll"
OWN = {"GetSystemTimePreciseAsFileTime", "CreateFile2", "EventSetInformation",
       "PathCchRemoveBackslash", "PathCchRemoveFileSpec"}
ADVAPI = ("EventRegister", "EventUnregister", "EventWriteTransfer", "EventWrite", "EventEnabled",
          "EventProviderEnabled", "EventActivityIdControl", "EventWriteEx", "EventWriteString")


def patch(path):
    """Point the api-ms-win-* imports of one DLL at vega7.dll; the imported names it needs."""
    pe = pefile.PE(path)
    data = bytearray(pe.__data__)
    needed = set()
    for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for entry in getattr(pe, attr, []):
            dll = entry.dll.decode()
            if not dll.lower().startswith("api-ms-win-") or dll.lower().startswith("api-ms-win-crt-"):
                continue
            rva = entry.struct.szName if attr.endswith("DELAY_IMPORT") else entry.struct.Name
            offset = pe.get_offset_from_rva(rva)
            assert data[offset:offset + len(dll)] == dll.encode()
            data[offset:offset + len(dll)] = SHIM.encode().ljust(len(dll), b"\0")
            for imp in entry.imports:
                if not imp.name:
                    raise SystemExit("{}: {} imported by number".format(path, dll))
                needed.add(imp.name.decode())
            print("{}: {} -> {} ({})".format(os.path.basename(path), dll, SHIM, ", ".join(sorted(imp.name.decode() for imp in entry.imports))))
    bound = pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_BOUND_IMPORT"]
    pe.close()
    if needed:
        patched = pefile.PE(data=bytes(data))
        directory = patched.OPTIONAL_HEADER.DATA_DIRECTORY[bound]
        directory.VirtualAddress = directory.Size = 0
        patched.write(path)
    return needed


# Functions that appeared in Windows 8 or later and that the C++ runtime, ONNX Runtime and the like use.
WIN8_ONLY = {"CopyFile2", "CreateFile2", "GetSystemTimePreciseAsFileTime", "EventSetInformation", "PathCchRemoveBackslash",
             "PathCchRemoveFileSpec", "PathCchCombine", "PathCchAppend", "WaitOnAddress", "WakeByAddressSingle",
             "WakeByAddressAll", "GetCurrentThreadStackLimits", "SetThreadDescription", "GetThreadDescription",
             "GetSystemCpuSetInformation", "CreateFileMappingFromApp", "MapViewOfFileFromApp", "VirtualAllocFromApp",
             "GetPackageFamilyName", "GetCurrentPackageId", "SetThreadInformation", "GetProcessMitigationPolicy",
             "SetProcessMitigationPolicy", "PrefetchVirtualMemory", "DiscardVirtualMemory", "OfferVirtualMemory"}


def check(folder):
    """Every Windows 8+ import left in the folder's programs (DLLs found in the folder itself count as present)."""
    own = {os.path.basename(p).lower() for p in glob.glob(os.path.join(folder, "**", "*.dll"), recursive=True)}
    problems = []
    for path in sorted(glob.glob(os.path.join(folder, "**", "*.dll"), recursive=True) +
                       glob.glob(os.path.join(folder, "**", "*.exe"), recursive=True) +
                       glob.glob(os.path.join(folder, "**", "*.pyd"), recursive=True)):
        try:
            pe = pefile.PE(path, fast_load=True)
            pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        except pefile.PEFormatError:
            continue
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            dll = entry.dll.decode().lower()
            if dll in own or dll.startswith("api-ms-win-crt-"):
                continue
            names = [imp.name.decode() for imp in entry.imports if imp.name]
            if dll.startswith(("api-ms-win-", "ext-ms-win-")):
                problems.append("{}: {} ({})".format(os.path.relpath(path, folder), dll, ", ".join(names)))
            else:
                problems += ["{}: {}!{}".format(os.path.relpath(path, folder), dll, name) for name in names if name in WIN8_ONLY]
        pe.close()
    return problems


def main(folder, arch):
    needed = set()
    for path in glob.glob(os.path.join(folder, "onnxruntime*.dll")):
        needed |= patch(path)
    if not needed:
        print("nothing to patch")
        return
    here = os.path.dirname(os.path.abspath(__file__))
    lines = ["LIBRARY vega7", "EXPORTS"]
    for name in sorted(needed):
        if name in OWN:
            lines.append("    {0}=Vega7{0}".format(name))
        elif name in ADVAPI:
            lines.append("    {0}=advapi32.{0}".format(name))
        else:
            lines.append("    {0}=kernel32.{0}".format(name))
    build = os.path.join(folder, "_vega7")
    os.makedirs(build, exist_ok=True)
    with open(os.path.join(build, "vega7.def"), "w") as out:
        out.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    vswhere = os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe")
    vs = subprocess.check_output([vswhere, "-latest", "-property", "installationPath"], text=True).strip()
    vcvars = os.path.join(vs, "VC", "Auxiliary", "Build", "vcvarsall.bat")
    target = os.path.abspath(os.path.join(folder, SHIM))
    # No C runtime at all (/NODEFAULTLIB, own entry point): vega7.dll depends on kernel32 only.
    command = ('"{}" {} && cl /nologo /O2 /GS- /LD "{}" /Fe"{}" /Fo"{}" /link /NODEFAULTLIB /ENTRY:DllMain '
               '/DEF:"{}" /SUBSYSTEM:WINDOWS,6.01 kernel32.lib advapi32.lib').format(
        vcvars, arch, os.path.join(here, "win7shim", "vega7.c"), target, os.path.join(build, "vega7.obj"),
        os.path.join(build, "vega7.def"))
    done = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(done.stdout.decode("cp437", "replace"))
    if done.returncode:
        raise SystemExit("vega7.dll did not build (exit code {})".format(done.returncode))
    for leftover in glob.glob(os.path.join(folder, "vega7.exp")) + glob.glob(os.path.join(folder, "vega7.lib")):
        os.remove(leftover)
    subprocess.call('rmdir /s /q "{}"'.format(build), shell=True)
    print("built", target)


if __name__ == "__main__":
    if sys.argv[1] == "--check":
        found = check(sys.argv[2])
        print("\n".join(found) if found else "Windows 7: no Windows 8+ imports in " + sys.argv[2])
        sys.exit(1 if found else 0)
    main(sys.argv[1], sys.argv[2])
