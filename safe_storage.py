"""Private output and handle-anchored access. Windows and Linux only."""
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import stat
import sys


class UserError(ValueError):
    """A deliberately public error; never wrap raw exceptions with this type."""


def _windows_api():
    from ctypes import wintypes as w
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
                             w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.CloseHandle.restype = w.BOOL
    k.GetFileInformationByHandleEx.argtypes = [w.HANDLE, ctypes.c_int,
                                              w.LPVOID, w.DWORD]
    k.GetFileInformationByHandleEx.restype = w.BOOL
    return k, w


def _windows_handle(path, directory=False):
    k, w = _windows_api()
    # Deny deletion/rename for directories and deny writes for media files.
    handle = k.CreateFileW(str(path), 0x80 if directory else 0x80000000,
                           3 if directory else 1, None, 3,
                           0x00200000 | (0x02000000 if directory else 0), None)
    if handle == ctypes.c_void_p(-1).value:
        raise UserError('出力先を安全に開けません。フォルダーの権限とリンクを確認してください。')
    class Attributes(ctypes.Structure):
        _fields_ = [('attributes', w.DWORD), ('tag', w.DWORD)]
    info = Attributes()
    if (not k.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
            or info.attributes & 0x400
            or bool(info.attributes & 0x10) != directory):
        k.CloseHandle(handle)
        raise UserError('出力先のリンク・特殊ファイルは利用できません。')
    return handle


@contextmanager
def directory(root, folder):
    """Pin every ancestor; Linux callers use the held directory, not its old path."""
    root, folder = Path(root), Path(folder)
    if not root.is_absolute() or not folder.is_absolute():
        raise UserError('出力先が不正です。')
    try:
        relative = folder.relative_to(root)
    except ValueError:
        raise UserError('出力先が不正です。') from None
    if '..' in relative.parts or '..' in root.parts:
        raise UserError('出力先が不正です。')
    handles = []
    try:
        if os.name == 'nt':
            current = Path(folder.anchor)
            handles.append(_windows_handle(current, True))
            for part in folder.parts[1:]:
                current /= part
                handles.append(_windows_handle(current, True))
            yield folder, ()
        elif sys.platform.startswith('linux'):
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            handles.append(os.open('/', flags))
            for part in folder.parts[1:]:
                handles.append(os.open(part, flags, dir_fd=handles[-1]))
            anchored = Path('/proc/self/fd') / str(handles[-1])
            if not anchored.is_dir():
                raise UserError('安全な出力先を利用できません。Windowsまたは通常のLinuxを使用してください。')
            yield anchored, (handles[-1],)
        else:
            raise UserError('安全なファイル処理はWindowsとLinuxに対応しています。')
    except OSError:
        raise UserError('出力先を安全に開けません。フォルダーの権限とリンクを確認してください。') from None
    finally:
        for handle in reversed(handles):
            if os.name == 'nt':
                _windows_api()[0].CloseHandle(handle)
            else:
                os.close(handle)


def make_private(path):
    """Output must not be writable by another ordinary OS account."""
    path = Path(path)
    if os.name != 'nt':
        info = path.stat()
        if info.st_uid != os.geteuid():
            raise UserError('出力先の所有者を確認してください。')
        os.chmod(path, 0o700)
        return
    k, w = _windows_api()
    a = ctypes.WinDLL('advapi32', use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.LocalFree.argtypes = [w.HLOCAL]
    k.LocalFree.restype = w.HLOCAL
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    a.OpenProcessToken.restype = w.BOOL
    a.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID,
                                      w.DWORD, ctypes.POINTER(w.DWORD)]
    a.GetTokenInformation.restype = w.BOOL
    a.ConvertSidToStringSidW.argtypes = [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
    a.ConvertSidToStringSidW.restype = w.BOOL
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR,
        w.DWORD, ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.DWORD)]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
    a.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID]
    a.SetFileSecurityW.restype = w.BOOL
    token, sid_string, descriptor = w.HANDLE(), w.LPWSTR(), w.LPVOID()
    try:
        if not a.OpenProcessToken(k.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OSError()
        size = w.DWORD()
        a.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not a.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise OSError()
        sid = ctypes.cast(buffer, ctypes.POINTER(w.LPVOID))[0]
        if not a.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
            raise OSError()
        # Protected DACL, inherited by newly created files/subdirectories.
        sddl = 'D:P(A;OICI;FA;;;' + sid_string.value + ')(A;OICI;FA;;;SY)'
        if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1,
                ctypes.byref(descriptor), None):
            raise OSError()
        if not a.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise OSError()
    except OSError:
        raise UserError('出力先のアクセス権を設定できません。共有フォルダーを避け、通常の権限で実行してください。') from None
    finally:
        if descriptor.value:
            k.LocalFree(descriptor)
        if sid_string:
            k.LocalFree(ctypes.cast(sid_string, w.HLOCAL))
        if token.value:
            k.CloseHandle(token)


def open_media(path):
    descriptor = None
    try:
        if os.name == 'nt':
            import msvcrt
            handle = _windows_handle(path)
            try:
                descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                _windows_api()[0].CloseHandle(handle)
                raise
        else:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise UserError('出力ファイルを確認してください。')
        file = os.fdopen(descriptor, 'rb')
        descriptor = None
        return file
    finally:
        if descriptor is not None:
            os.close(descriptor)
