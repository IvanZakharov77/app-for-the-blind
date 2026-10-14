"""Download and unpack one build component; used by build-windows.cmd instead of PowerShell.

Windows 7 has PowerShell 2.0 without Invoke-WebRequest and Expand-Archive, and its
system TLS often fails on modern sites. Python 3.8 brings its own TLS, so this works everywhere.
Usage: python tools/fetch.py URL TARGET [--unzip FOLDER]
"""

import shutil
import ssl
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def extract_archive(path: Path, folder: Path) -> None:
    """Reject unsafe or unexpectedly large ZIP members before unpacking a build asset."""
    with zipfile.ZipFile(str(path)) as archive:
        total = 0
        for member in archive.infolist():
            name = member.filename
            parts = PurePosixPath(name).parts
            mode = (member.external_attr >> 16) & 0o170000
            if (not name or name.startswith("/") or "\\" in name or "\x00" in name
                    or ".." in parts or not parts or ":" in parts[0]
                    or mode == stat.S_IFLNK):
                raise ValueError("Unsafe ZIP member: {}".format(name))
            total += member.file_size
            if member.file_size > 1024 ** 3 or total > 2 * 1024 ** 3:
                raise ValueError("ZIP asset is unexpectedly large.")
        archive.extractall(str(folder))


def main(arguments) -> int:
    url, target = arguments[0], Path(arguments[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    print("Downloading", url)
    request = urllib.request.Request(url, headers={"User-Agent": "Vega-build"})
    try:
        import certifi  # Windows 7 without updates lacks newer root certificates
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=60, context=context) as response, partial.open("wb") as stream:
        shutil.copyfileobj(response, stream, 1024 * 1024)
    partial.replace(target)
    if len(arguments) > 2 and arguments[2] == "--unzip":
        folder = Path(arguments[3])
        extract_archive(target, folder)
        target.unlink()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as error:  # the .cmd only needs the exit code; English text survives any console code page
        print("Download failed:", error)
        raise SystemExit(1)
