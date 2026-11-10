"""Install verified language resources alongside the VR runtime."""
import ctypes
from ctypes import wintypes
import msvcrt
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

from gameplay_hd import checked
import language_pack


def require_closed():
    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD), ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError("Could not check whether Darkwatch is running.")
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.exe.casefold().startswith("darkwatch_") and entry.exe.casefold().endswith(".exe"):
                raise ValueError("Close Darkwatch before changing languages or starting another copy.")
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise OSError("Could not finish checking running applications.")
    finally:
        kernel.CloseHandle(snapshot)


@contextmanager
def operation(root):
    lock = checked(root, "launcher-ui/.runtime-operation.lock")
    with lock.open("a+b") as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise ValueError("Another launcher operation is using this VR build.") from error
        try:
            require_closed()
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def catalog(payload, code):
    name = "portuguese" if code == "pt-BR" else "ps2-" + language_pack.DISC_LANGUAGES[code].lower()
    result = language_pack.Catalog(checked(payload, name + "-catalog.json").read_bytes())
    if result.language != code:
        raise ValueError("Language catalog identity mismatch.")
    return result


def status(runtime, payload):
    fields = {"language": language_pack.selected(runtime)}
    for code, label in language_pack.LANGUAGES.items():
        try:
            available = catalog(payload, code).validate(runtime, full=False)
        except (OSError, ValueError):
            available = False
        fields["portuguese_installed" if code == "pt-BR" else label.lower() + "_installed"] = available
    fields["spanish_audio_installed"] = fields["spanish_installed"]
    return fields


def select(runtime, payload, code, cancel):
    if code != "en" and not catalog(payload, code).validate(runtime, cancel):
        raise ValueError("Install or repair that language before selecting it.")
    cancel()
    require_closed()
    language_pack.select(runtime, code)


def install(runtime, payload, state, code, iso, cancel, notify):
    resource = catalog(payload, code)
    total = sum(row["size"] for row in resource.files.values())
    if shutil.disk_usage(runtime).free < 3 * total + 128 * 1024 * 1024:
        raise ValueError("Not enough space to stage the language pack.")
    if code == "pt-BR":
        resource.install(checked(payload, "portuguese-text.zip"), runtime, cancel, notify, require_closed)
        return
    if Path(iso).suffix.lower() != ".iso":
        raise ValueError("Choose your supported PAL PS2 Darkwatch ISO (SLES-53564).")
    import ps2_spanish
    state.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ps2-language-", dir=state) as directory:
        archive = Path(directory) / "prepared.zip"
        ps2_spanish.prepare(iso, checked(runtime, "assets"), archive, cancel, notify, language=code)
        resource.install(archive, runtime, cancel, notify, require_closed)
