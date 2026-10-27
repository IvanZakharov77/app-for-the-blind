/* vega7.dll: the few Windows 8+ functions that ONNX Runtime (inside Piper, the voice Irina) asks for,
   for Windows 7. tools/win7_shim.py points onnxruntime.dll's api-ms-win-* imports at this DLL; the
   functions Windows 7 already has are forwarded to kernel32/advapi32 by the generated .def file.
   Where the real function exists (Windows 8 and newer), it is used. Ivan, 2026-10-27: Piper failed on
   Windows 7 with 0xC0000139 (entry point not found). */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

static FARPROC real(const char *dll, const char *name)
{
    HMODULE module = GetModuleHandleA(dll);
    if (!module)
        module = LoadLibraryA(dll);
    return module ? GetProcAddress(module, name) : NULL;
}

typedef VOID (WINAPI *precise_time)(LPFILETIME);

VOID WINAPI Vega7GetSystemTimePreciseAsFileTime(LPFILETIME time)
{
    static precise_time found;
    static LONG looked;
    if (!InterlockedCompareExchange(&looked, 1, 0))
        found = (precise_time)real("kernel32.dll", "GetSystemTimePreciseAsFileTime");
    if (found)
        found(time);
    else
        GetSystemTimeAsFileTime(time);
}

typedef struct {
    DWORD dwSize, dwFileAttributes, dwFileFlags, dwSecurityQosFlags;
    LPSECURITY_ATTRIBUTES lpSecurityAttributes;
    HANDLE hTemplateFile;
} VEGA7_CREATEFILE2_PARAMETERS;

typedef HANDLE (WINAPI *create_file2)(LPCWSTR, DWORD, DWORD, DWORD, VEGA7_CREATEFILE2_PARAMETERS *);

HANDLE WINAPI Vega7CreateFile2(LPCWSTR name, DWORD access, DWORD share, DWORD disposition, VEGA7_CREATEFILE2_PARAMETERS *extra)
{
    create_file2 found = (create_file2)real("kernel32.dll", "CreateFile2");
    if (found)
        return found(name, access, share, disposition, extra);
    if (!extra)
        return CreateFileW(name, access, share, NULL, disposition, FILE_ATTRIBUTE_NORMAL, NULL);
    return CreateFileW(name, access, share, extra->lpSecurityAttributes, disposition,
                       extra->dwFileAttributes | extra->dwFileFlags | extra->dwSecurityQosFlags, extra->hTemplateFile);
}

typedef ULONG (WINAPI *event_set_information)(ULONGLONG, int, PVOID, ULONG);

ULONG WINAPI Vega7EventSetInformation(ULONGLONG handle, int what, PVOID data, ULONG size)
{
    event_set_information found = (event_set_information)real("advapi32.dll", "EventSetInformation");
    return found ? found(handle, what, data, size) : ERROR_NOT_SUPPORTED;
}

/* Root of a path: «C:\», «\\server\share\» or «\». Returns the length of the root part. */
static size_t root_length(const WCHAR *path)
{
    if (path[0] && path[1] == L':')
        return path[2] == L'\\' ? 3 : 2;
    if (path[0] == L'\\' && path[1] == L'\\') {
        size_t at = 2, slashes = 0;
        while (path[at] && slashes < 2) {
            if (path[at] == L'\\')
                slashes++;
            at++;
        }
        return at;
    }
    return path[0] == L'\\' ? 1 : 0;
}

HRESULT WINAPI Vega7PathCchRemoveBackslash(WCHAR *path, SIZE_T size)
{
    size_t length;
    if (!path || !size)
        return E_INVALIDARG;
    length = lstrlenW(path);
    if (length == 0 || path[length - 1] != L'\\' || length <= root_length(path))
        return S_FALSE;
    path[length - 1] = 0;
    return S_OK;
}

HRESULT WINAPI Vega7PathCchRemoveFileSpec(WCHAR *path, SIZE_T size)
{
    size_t root, length, at;
    if (!path || !size)
        return E_INVALIDARG;
    root = root_length(path);
    length = lstrlenW(path);
    if (length <= root)
        return S_FALSE;
    at = length;
    while (at > root && path[at - 1] != L'\\')
        at--;
    if (at > root)
        at--;  /* the backslash before the last part goes too, but never the root's own */
    path[at] = 0;
    return S_OK;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)instance; (void)reason; (void)reserved;
    return TRUE;
}
