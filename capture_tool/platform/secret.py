"""Keep the Gemini key encrypted with Windows DPAPI: only this Windows user on this PC can
decrypt it, so copying settings.json elsewhere doesn't leak it."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

_ENTROPY = b"CaptureTool-ai-key"


class SecretError(Exception):
    pass


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    b = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    b._buf = buf  # keep alive
    return b


_crypt = ctypes.WinDLL("crypt32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32")
_crypt.CryptProtectData.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB), ctypes.c_void_p,
                                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
_crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB), ctypes.c_void_p,
                                      ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
_k32.LocalFree.argtypes = [ctypes.c_void_p]
CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _out(blob: _BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _k32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect(text: str) -> str:
    out = _BLOB()
    if not _crypt.CryptProtectData(ctypes.byref(_blob(text.encode("utf-8"))), "CaptureTool", ctypes.byref(_blob(_ENTROPY)),
                                   None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise SecretError("키를 암호화하지 못했습니다.")
    return base64.b64encode(_out(out)).decode("ascii")


def unprotect(blob: str) -> str:
    try:
        data = base64.b64decode(blob, validate=True)
    except ValueError as e:
        raise SecretError("저장된 키를 읽지 못했습니다.") from e
    out = _BLOB()
    if not _crypt.CryptUnprotectData(ctypes.byref(_blob(data)), None, ctypes.byref(_blob(_ENTROPY)), None, None,
                                     CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise SecretError("저장된 키를 읽지 못했습니다. 설정에서 키를 다시 넣어 주세요.")
    return _out(out).decode("utf-8")
