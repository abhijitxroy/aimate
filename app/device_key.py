"""Protect Windows encryption keys with current-user DPAPI, without UI prompts."""
import os
from pathlib import Path
from cryptography.fernet import Fernet


def dpapi(data, decrypt=False):
    if os.name != "nt":
        raise ValueError("Windows device protection is unavailable on this platform.")
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size",wintypes.DWORD),("data",ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    target=Blob()
    crypt=ctypes.WinDLL("crypt32",use_last_error=True)
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    call=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    call.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    call.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    kernel.LocalFree.restype=ctypes.c_void_p
    try:
        if not call(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
            raise ValueError("Windows could not unlock the encryption key. Use the Windows account that created it.")
        return ctypes.string_at(target.data,target.size)
    finally:
        ctypes.memset(buffer,0,len(data))
        if target.data:
            ctypes.memset(target.data,0,target.size)
            kernel.LocalFree(ctypes.cast(target.data,ctypes.c_void_p))


def load_key(directory):
    directory=Path(directory).resolve()
    legacy=directory/"encryption.key"
    protected=directory/"encryption.dpapi"
    if os.name != "nt":
        if not legacy.exists():
            with legacy.open("xb") as file:
                file.write(Fernet.generate_key())
        legacy.chmod(0o600)
        return legacy.read_bytes()
    if protected.exists():
        return dpapi(protected.read_bytes(),decrypt=True)
    key=legacy.read_bytes() if legacy.exists() else Fernet.generate_key()
    Fernet(key)  # Verify key format before migrating existing credentials.
    encoded=dpapi(key)
    if dpapi(encoded,decrypt=True) != key:
        raise ValueError("Device key verification failed; original key preserved.")
    with protected.open("xb") as file:
        file.write(encoded)
        file.flush()
        os.fsync(file.fileno())
    if dpapi(protected.read_bytes(),decrypt=True) != key:
        raise ValueError("Device key verification failed; original key preserved.")
    if legacy.exists():
        legacy.unlink()
    return key
