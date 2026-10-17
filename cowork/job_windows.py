"""Un « Job Object » Windows : les processus lancés par Cowork meurent avec Agent
First, même s'il plante (sans lui, un serveur lancé par `start` lui survivait).

Le job est créé une fois et reste ouvert tant qu'Agent First tourne. À sa mort,
Windows ferme le job et tue tout ce qui y est rattaché ; les enfants d'un processus
rattaché naissent dans le même job (un python lancé par PowerShell y est donc aussi).
"""
import ctypes
import logging
import os
import threading
from ctypes import wintypes

journal = logging.getLogger(__name__)

_TUER_A_LA_FERMETURE = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
_LIMITES_ETENDUES = 9  # JobObjectExtendedLimitInformation
_DROITS = 0x0100 | 0x0001  # PROCESS_SET_QUOTA | PROCESS_TERMINATE


class _LimitesDeBase(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _Compteurs(ctypes.Structure):
    _fields_ = [
        (nom, ctypes.c_uint64)
        for nom in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")
    ]


class _LimitesEtendues(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _LimitesDeBase),
        ("IoInfo", _Compteurs),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_verrou = threading.Lock()
_noyau = None
_job = None


def rattacher(pid: int) -> bool:
    """Rattache le processus `pid` au job d'Agent First. False si c'est impossible
    (hors Windows, refus du système) : le processus tourne quand même, il sera
    seulement arrêté par `arreter_tout` et non par la mort d'Agent First."""
    if os.name != "nt":
        return False
    try:
        with _verrou:
            job = _job_ouvert()
        processus = _noyau.OpenProcess(_DROITS, False, pid)
        if not processus:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not _noyau.AssignProcessToJobObject(job, processus):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _noyau.CloseHandle(processus)
        return True
    except OSError:
        journal.warning("Processus %s non rattaché au job d'Agent First", pid, exc_info=True)
        return False


def _job_ouvert():
    """Le job d'Agent First, créé au premier appel (appelé sous _verrou)."""
    global _noyau, _job
    if _job is None:
        _noyau = _charger()
        job = _noyau.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        limites = _LimitesEtendues()
        limites.BasicLimitInformation.LimitFlags = _TUER_A_LA_FERMETURE
        if not _noyau.SetInformationJobObject(job, _LIMITES_ETENDUES, ctypes.byref(limites), ctypes.sizeof(limites)):
            erreur = ctypes.WinError(ctypes.get_last_error())
            _noyau.CloseHandle(job)
            raise erreur
        _job = job
    return _job


def _charger():
    noyau = ctypes.WinDLL("kernel32", use_last_error=True)
    noyau.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    noyau.CreateJobObjectW.restype = wintypes.HANDLE
    noyau.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    noyau.SetInformationJobObject.restype = wintypes.BOOL
    noyau.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    noyau.OpenProcess.restype = wintypes.HANDLE
    noyau.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    noyau.AssignProcessToJobObject.restype = wintypes.BOOL
    noyau.CloseHandle.argtypes = [wintypes.HANDLE]
    noyau.CloseHandle.restype = wintypes.BOOL
    return noyau
