#!/usr/bin/env python3
"""
BeacNDiscordLink
================
Synchronizes your physical BEACN Mix Create mute buttons (Mic & Chat) with
Discord's Mute and Deafen status in real time.

How it works:
  1. Reads the live hardware mute button state directly from BEACN.exe memory
     (with automatic fallback to the active .beacnMixer profile XML).
  2. Triggers your Discord Toggle Mute (default: F3) and Toggle Deafen (default: F4)
     keybinds via Win32 SendInput whenever you mute/unmute on your BEACN Mix Create.

Behavior:
  - Mic button muted on BEACN (Chat unmuted)  -> Discord Mic Muted (Undeafened)
  - Mic button muted + Chat button muted      -> Discord Deafened (and Muted)
  - Mic button unmuted on BEACN               -> Discord Unmuted & Undeafened

Zero external dependencies (100% Python 3 Standard Library on Windows).
"""

import ctypes
from ctypes import wintypes
import json
import math
import os
import struct
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "mute_keybind": "F3",
    "deafen_keybind": "F4",
    "mic_channel_name": "Mic",
    "chat_channel_name": "Chat",
    "only_button_mute": True,
    "include_knob_press_mute": False,
    "deafen_when_only_chat_muted": False,
    "poll_interval_ms": 50,
    "auto_elevate_admin": True,
    "beacn_profile_override": ""
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                cfg.update(user_cfg)
        except Exception as e:
            log(f"Warning: Could not parse config.json ({e}), using defaults.")
    else:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
    return cfg


# ---------------------------------------------------------------------------
# Administrator Elevation Helper (Required to Read BEACN.exe Live RAM)
# ---------------------------------------------------------------------------

def is_user_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Re-launch the current Python script with Administrator privileges (UAC)."""
    script_path = os.path.abspath(__file__)
    extra_args = [a for a in sys.argv[1:] if a != "--elevated"]
    params = " ".join([f'"{script_path}"', '"--elevated"'] + [f'"{a}"' for a in extra_args])
    # SW_SHOWNORMAL = 1, SW_HIDE = 0
    show_cmd = 0 if "--hidden" in sys.argv else 1
    res = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, BASE_DIR, show_cmd
    )
    return int(res) > 32


# ---------------------------------------------------------------------------
# Win32 SendInput Keybind Controller (Triggers Discord Mute / Deafen)
# ---------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


VK_MAP: Dict[str, int] = {
    "BACKSPACE": 0x08, "TAB": 0x09, "ENTER": 0x0D, "RETURN": 0x0D,
    "SHIFT": 0x10, "CTRL": 0x11, "CONTROL": 0x11, "ALT": 0x12, "MENU": 0x12,
    "PAUSE": 0x13, "CAPSLOCK": 0x14, "ESC": 0x1B, "ESCAPE": 0x1B,
    "SPACE": 0x20, "PAGEUP": 0x21, "PAGEDOWN": 0x22, "END": 0x23, "HOME": 0x24,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "INSERT": 0x2D, "DELETE": 0x2E,
    "LWIN": 0x5B, "RWIN": 0x5C,
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63,
    "NUMPAD4": 0x64, "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67,
    "NUMPAD8": 0x68, "NUMPAD9": 0x69,
    "MULTIPLY": 0x6A, "ADD": 0x6B, "SUBTRACT": 0x6D, "DECIMAL": 0x6E, "DIVIDE": 0x6F,
    "SCROLLLOCK": 0x91,
    "LSHIFT": 0xA0, "RSHIFT": 0xA1, "LCTRL": 0xA2, "RCTRL": 0xA3,
    "LALT": 0xA4, "RALT": 0xA5,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
# F1 .. F24 (0x70 .. 0x87)
for _i in range(1, 25):
    VK_MAP[f"F{_i}"] = 0x70 + (_i - 1)
# 0 .. 9 (0x30 .. 0x39)
for _c in "0123456789":
    VK_MAP[_c] = ord(_c)
# A .. Z (0x41 .. 0x5A)
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    VK_MAP[_c] = ord(_c)


def parse_keybind(keybind_str: str) -> List[int]:
    """Parse a keybind string like 'F3', 'F4', or 'ctrl+shift+m' into virtual key codes."""
    parts = [p.strip().upper() for p in keybind_str.replace("-", "+").split("+") if p.strip()]
    vks: List[int] = []
    for p in parts:
        if p in VK_MAP:
            vks.append(VK_MAP[p])
        else:
            raise ValueError(f"Unknown key '{p}' in keybind '{keybind_str}'")
    if not vks:
        raise ValueError(f"Empty keybind '{keybind_str}'")
    return vks


def send_keybind(keybind_str: str) -> None:
    """
    Send a global key press + release using Win32 SendInput with both Virtual-Key
    and hardware Scan Code so Discord's global hook detects it in any window/game.
    """
    vks = parse_keybind(keybind_str)

    def _make_key_input(vk: int, is_up: bool) -> INPUT:
        scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFFFF
        flags = KEYEVENTF_KEYUP if is_up else 0
        if vk in (0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x6F, 0xA3, 0xA5):
            flags |= KEYEVENTF_EXTENDEDKEY
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
        return inp

    # Press keys in order
    down_inputs = (_make_key_input(vk, False) for vk in vks)
    down_arr = (INPUT * len(vks))(*down_inputs)
    user32.SendInput(len(vks), ctypes.byref(down_arr), ctypes.sizeof(INPUT))

    # Hold briefly so Discord's global hook reliably registers the press
    time.sleep(0.035)

    # Release keys in reverse order
    up_inputs = (_make_key_input(vk, True) for vk in reversed(vks))
    up_arr = (INPUT * len(vks))(*up_inputs)
    user32.SendInput(len(vks), ctypes.byref(up_arr), ctypes.sizeof(INPUT))


class DiscordKeybindController:
    """
    Synchronizes Discord's Mute and Deafen states using Discord's Toggle Mute (F3)
    and Toggle Deafen (F4) keybinds.

    Accounts for Discord's coupled Mute/Deafen behavior:
      - Deafening in Discord automatically mutes your mic while deafened.
      - Ensuring Discord is in the Muted state BEFORE pressing Toggle Deafen guarantees
        that pressing Toggle Deafen again to undeafen returns Discord to the Muted state,
        so unmuting Chat alone keeps Mic muted, while unmuting Mic unmutes both.
    """

    def __init__(self, cfg: dict):
        self.mute_key = cfg.get("mute_keybind", "F3").strip() or "F3"
        self.deafen_key = cfg.get("deafen_keybind", "F4").strip() or "F4"
        self.is_muted = False
        self.is_deafened = False
        self.initialized = False

    def initialize_state(self, initial_mute: bool, initial_deaf: bool) -> None:
        self.is_muted = bool(initial_mute)
        self.is_deafened = bool(initial_deaf)
        self.initialized = True

    def sync_to_target(self, target_mute: bool, target_deaf: bool, dry_run: bool = False) -> List[str]:
        """
        Transition Discord from (self.is_muted, self.is_deafened) to (target_mute, target_deaf)
        and return the list of keybinds triggered.
        """
        triggered: List[str] = []

        if target_deaf:
            # We want Discord to be Deafened (and Muted).
            if not self.is_deafened:
                # Ensure self.is_muted is True BEFORE deafening so Discord remembers selfMute=True
                if not self.is_muted:
                    if not dry_run:
                        send_keybind(self.mute_key)
                        time.sleep(0.06)
                    self.is_muted = True
                    triggered.append(f"{self.mute_key} (Mute)")
                if not dry_run:
                    send_keybind(self.deafen_key)
                self.is_deafened = True
                triggered.append(f"{self.deafen_key} (Deafen)")
        else:
            # We want Discord to be Undeafened (target_deaf == False).
            if self.is_deafened:
                # Toggle Deafen off; because self.is_muted was True before deafening,
                # Discord returns to Undeafened + Muted (self.is_muted == True).
                if not dry_run:
                    send_keybind(self.deafen_key)
                    if not target_mute:
                        time.sleep(0.06)
                self.is_deafened = False
                triggered.append(f"{self.deafen_key} (Undeafen)")

            # Now adjust Mute state if needed
            if self.is_muted != target_mute:
                if not dry_run:
                    send_keybind(self.mute_key)
                self.is_muted = target_mute
                action_label = "Mute" if target_mute else "Unmute"
                triggered.append(f"{self.mute_key} ({action_label})")

        return triggered


# ---------------------------------------------------------------------------
# Live BEACN.exe Process Memory Reader
# ---------------------------------------------------------------------------

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_READWRITE = 0x04


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ULONG_PTR),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * wintypes.MAX_PATH),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(wintypes.BYTE)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * wintypes.MAX_PATH),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def find_beacn_pid() -> Optional[int]:
    """Find the Process ID of BEACN.exe using Toolhelp32Snapshot."""
    h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h_snap == wintypes.HANDLE(-1).value or not h_snap:
        return None
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if kernel32.Process32FirstW(h_snap, ctypes.byref(pe)):
            while True:
                if pe.szExeFile.lower() == "beacn.exe":
                    return int(pe.th32ProcessID)
                if not kernel32.Process32NextW(h_snap, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(h_snap)
    return None


def get_module_base_and_path(pid: int) -> Tuple[Optional[int], Optional[str]]:
    """Return (base_address, exe_path) for BEACN.exe in the given PID."""
    h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if h_snap == wintypes.HANDLE(-1).value or not h_snap:
        return None, None
    try:
        me = MODULEENTRY32W()
        me.dwSize = ctypes.sizeof(MODULEENTRY32W)
        if kernel32.Module32FirstW(h_snap, ctypes.byref(me)):
            while True:
                if me.szModule.lower() == "beacn.exe":
                    base_addr = ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value
                    return base_addr, me.szExePath
                if not kernel32.Module32NextW(h_snap, ctypes.byref(me)):
                    break
    finally:
        kernel32.CloseHandle(h_snap)
    return None, None


def find_rtti_vtable_rvas(exe_path: str) -> Dict[str, int]:
    """
    Dynamically compute the main vtable RVAs of MixerData and MixerComponent
    from BEACN.exe's PE headers and RTTI descriptors.
    """
    rvas: Dict[str, int] = {}
    try:
        with open(exe_path, "rb") as f:
            pe = f.read()
        e_lfanew = struct.unpack_from("<I", pe, 0x3C)[0]
        num_sections = struct.unpack_from("<H", pe, e_lfanew + 6)[0]
        opt_hdr_size = struct.unpack_from("<H", pe, e_lfanew + 20)[0]
        image_base = struct.unpack_from("<Q", pe, e_lfanew + 24 + 24)[0]
        sec_offset = e_lfanew + 24 + opt_hdr_size

        sections = []
        for i in range(num_sections):
            name, vsize, vaddr, rsize, roff = struct.unpack_from("<8sIIII", pe, sec_offset + i * 40)[:5]
            sections.append((name.rstrip(b"\x00").decode("ascii", errors="ignore"), vsize, vaddr, rsize, roff))

        def file_to_rva(foff: int) -> Optional[int]:
            for _, vsize, vaddr, rsize, roff in sections:
                if roff <= foff < roff + rsize:
                    return vaddr + (foff - roff)
            return None

        rdata_sec = [s for s in sections if s[0] == ".rdata"]
        if not rdata_sec:
            return rvas
        _, rdata_vsize, rdata_vaddr, rdata_rsize, rdata_roff = rdata_sec[0]
        rdata = pe[rdata_roff : rdata_roff + rdata_rsize]

        for label, cls_bytes in [
            ("MixerData", b".?AVMixerData@@\x00"),
            ("MixerComponent", b".?AVMixerComponent@@\x00"),
            ("MixCreateMixerKnobAppUI", b".?AVMixCreateMixerKnobAppUI@@\x00"),
        ]:
            idx = pe.find(cls_bytes)
            if idx == -1:
                continue
            td_rva = file_to_rva(idx - 16)
            if td_rva is None:
                continue
            pos = 0
            target_bytes = struct.pack("<I", td_rva)
            while (pos := rdata.find(target_bytes, pos)) != -1:
                col_foff = rdata_roff + pos - 12
                sig, offset, cd_off, td, chd = struct.unpack_from("<IIIII", pe, col_foff)
                if sig == 1 and offset == 0:
                    col_rva = file_to_rva(col_foff)
                    if col_rva is not None:
                        col_va = image_base + col_rva
                        vpos = rdata.find(struct.pack("<Q", col_va))
                        if vpos != -1:
                            rvas[label] = rdata_vaddr + vpos + 8
                            break
                pos += 4
    except Exception:
        pass
    return rvas


class BeacNMemoryMonitor:
    """
    Reads real-time hardware mute states directly from BEACN.exe process memory.

    Each live channel strip (MixerChannel struct, 0x60 bytes) contains:
      +0x00 (uint64): char* pointer to null-terminated UTF-8 channel name ("Mic", "Chat", etc.)
      +0x18 (uint8) : mixerHPMute
      +0x19 (uint8) : mixerBroadcastMute
      +0x1A (uint8) : mixerChatMute
      +0x1B (uint8) : mixerVodTrackMute
      +0x20 (int32) : mixerPlaceInOrder
      +0x28 (int32) : bartonKnobType (1 = Mic, 3 = Chat)
      +0x50 (int32) : knobMuteMode (42..46)
      +0x54 (int32) : muteMode (42..46)
      +0x58 (uint8) : knobMuteState (0 = Live, 1 = Muted)
      +0x59 (uint8) : buttonMuteState (0 = Live, 1 = Muted)
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.pid: Optional[int] = None
        self.h_proc: Optional[int] = None
        self.mic_channel_ptr: Optional[int] = None
        self.chat_channel_ptr: Optional[int] = None
        self.vtable_rvas: Dict[str, int] = {}
        self.base_addr: Optional[int] = None
        self.access_denied_logged = False

    def close(self) -> None:
        if self.h_proc:
            try:
                kernel32.CloseHandle(self.h_proc)
            except Exception:
                pass
        self.h_proc = None
        self.pid = None
        self.mic_channel_ptr = None
        self.chat_channel_ptr = None

    def _read_mem(self, addr: int, size: int) -> Optional[bytes]:
        if not self.h_proc or not addr or addr < 0x10000:
            return None
        buf = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t(0)
        ok = kernel32.ReadProcessMemory(
            self.h_proc,
            ctypes.c_void_p(addr),
            buf,
            size,
            ctypes.byref(bytes_read),
        )
        if not ok or bytes_read.value != size:
            return None
        return buf.raw

    def _read_cstring(self, ptr: int, max_len: int = 32) -> Optional[str]:
        raw = self._read_mem(ptr, max_len)
        if not raw or b"\x00" not in raw:
            return None
        s = raw.split(b"\x00", 1)[0]
        if not (1 <= len(s) <= 24):
            return None
        if not all(32 <= b < 127 for b in s):
            return None
        return s.decode("ascii", errors="ignore")

    def _validate_channel_struct(self, ptr: int) -> Optional[Tuple[str, int, bytes]]:
        """
        Verify if `ptr` points to a valid MixerChannel struct in BEACN.exe memory.
        Returns (channel_name, knob_type, raw_96_bytes) if valid, else None.
        """
        raw = self._read_mem(ptr, 0x60)
        if not raw:
            return None

        lock_st = raw[0x08]
        linked = raw[0x09]
        if lock_st not in (0, 1) or linked not in (0, 1):
            return None

        # Route mute flags (+0x18 .. +0x1D)
        for offset in range(0x18, 0x1E):
            if raw[offset] not in (0, 1):
                return None

        place_in_order, _, knob_type = struct.unpack_from("<iii", raw, 0x20)
        if not (0 <= place_in_order <= 16 and 1 <= knob_type <= 32):
            return None

        knob_mute_mode, btn_mute_mode = struct.unpack_from("<ii", raw, 0x50)
        if not (42 <= knob_mute_mode <= 46 and 42 <= btn_mute_mode <= 46):
            return None

        if raw[0x58] not in (0, 1) or raw[0x59] not in (0, 1) or raw[0x5A] not in (0, 1):
            return None

        str_ptr = struct.unpack_from("<Q", raw, 0x00)[0]
        name = self._read_cstring(str_ptr)
        if not name:
            return None

        return name, knob_type, raw

    def _ensure_process(self) -> bool:
        pid = find_beacn_pid()
        if not pid:
            self.close()
            return False

        if self.pid == pid and self.h_proc:
            return True

        self.close()
        h_proc = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not h_proc:
            if not self.access_denied_logged:
                self.access_denied_logged = True
                log("Notice: BEACN.exe is running as Administrator. Please run BeacNDiscordLink as Administrator to read live button presses.")
            return False

        self.pid = pid
        self.h_proc = h_proc
        self.access_denied_logged = False
        self.base_addr, exe_path = get_module_base_and_path(pid)
        if exe_path and not self.vtable_rvas:
            self.vtable_rvas = find_rtti_vtable_rvas(exe_path)
        return True

    def _locate_live_channels(self) -> bool:
        """
        Scan BEACN.exe heap for the live MixCreateMixerKnobAppUI / MixerComponent / MixerData
        objects to obtain the exact pointers to the live Mic and Chat MixerChannel structs.
        """
        if not self.h_proc:
            return False

        mic_target = self.cfg.get("mic_channel_name", "Mic").strip().lower()
        chat_target = self.cfg.get("chat_channel_name", "Chat").strip().lower()

        ui_vtable_list: List[bytes] = []
        data_vtable_bytes = None
        if self.base_addr and self.vtable_rvas:
            for k in ("MixCreateMixerKnobAppUI", "MixerComponent"):
                if k in self.vtable_rvas:
                    ui_vtable_list.append(struct.pack("<Q", self.base_addr + self.vtable_rvas[k]))
            if "MixerData" in self.vtable_rvas:
                data_vtable_bytes = struct.pack("<Q", self.base_addr + self.vtable_rvas["MixerData"])

        candidate_ptrs: List[int] = []

        mbi = MEMORY_BASIC_INFORMATION()
        addr = 0x10000
        max_addr = 0x7FFFFFFEFFFF

        while addr < max_addr:
            res = kernel32.VirtualQueryEx(
                self.h_proc, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
            )
            if not res:
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize or 0
            if size == 0:
                break

            if (
                mbi.State == MEM_COMMIT
                and mbi.Type == MEM_PRIVATE
                and mbi.Protect == PAGE_READWRITE
                and size <= 64 * 1024 * 1024
            ):
                chunk = self._read_mem(base, size)
                if chunk:
                    # 1. Check MixCreateMixerKnobAppUI / MixerComponent instances (active live UI/Hardware channels)
                    for vt_bytes in ui_vtable_list:
                        pos = 0
                        while (pos := chunk.find(vt_bytes, pos)) != -1:
                            if pos + 0x158 <= len(chunk):
                                ch_ptr = struct.unpack_from("<Q", chunk, pos + 0x150)[0]
                                if ch_ptr not in candidate_ptrs:
                                    candidate_ptrs.append(ch_ptr)
                            pos += 8

                    # 2. Check live MixerData instance ([MixerData + 0xC8] != 0 is Live, == 0 is Snapshot)
                    if data_vtable_bytes:
                        pos = 0
                        while (pos := chunk.find(data_vtable_bytes, pos)) != -1:
                            if pos + 0xD0 <= len(chunk):
                                snapshot_ptr = struct.unpack_from("<Q", chunk, pos + 0xC8)[0]
                                vec_begin, vec_end = struct.unpack_from("<QQ", chunk, pos + 0x60)
                                count = (vec_end - vec_begin) // 16
                                if snapshot_ptr != 0 and 1 <= count <= 16:
                                    vec_raw = self._read_mem(vec_begin, count * 16)
                                    if vec_raw:
                                        for i in range(count):
                                            ch_ptr = struct.unpack_from("<Q", vec_raw, i * 16)[0]
                                            if ch_ptr not in candidate_ptrs:
                                                candidate_ptrs.append(ch_ptr)
                            pos += 8

            addr = base + size

        found_mic = None
        found_chat = None

        for ptr in candidate_ptrs:
            info = self._validate_channel_struct(ptr)
            if not info:
                continue
            name, knob_type, _ = info
            name_low = name.strip().lower()
            if found_mic is None and (name_low == mic_target or knob_type == 1):
                found_mic = ptr
            if found_chat is None and (name_low == chat_target or knob_type == 3):
                found_chat = ptr

        if found_mic and found_chat:
            self.mic_channel_ptr = found_mic
            self.chat_channel_ptr = found_chat
            log(f"Connected to live BEACN.exe memory (PID {self.pid})")
            return True

        return False

    def read_mute_states(self) -> Optional[Tuple[bool, bool]]:
        """
        Read (mic_muted, chat_muted) directly from BEACN.exe RAM in <1ms.
        Automatically locates or refreshes channel pointers if needed.
        """
        if not self._ensure_process():
            return None

        if not self.mic_channel_ptr or not self.chat_channel_ptr:
            if not self._locate_live_channels():
                return None

        mic_info = self._validate_channel_struct(self.mic_channel_ptr)
        chat_info = self._validate_channel_struct(self.chat_channel_ptr)

        if not mic_info or not chat_info:
            # Pointers moved (e.g., profile switched in BEACN App); re-scan once
            self.mic_channel_ptr = None
            self.chat_channel_ptr = None
            if not self._locate_live_channels():
                return None
            mic_info = self._validate_channel_struct(self.mic_channel_ptr)
            chat_info = self._validate_channel_struct(self.chat_channel_ptr)
            if not mic_info or not chat_info:
                return None

        include_knob = bool(self.cfg.get("include_knob_press_mute", False))

        def _extract_muted(raw_bytes: bytes) -> bool:
            btn_muted = raw_bytes[0x59] == 1
            if include_knob:
                knob_muted = raw_bytes[0x58] == 1
                return btn_muted or knob_muted
            return btn_muted

        return _extract_muted(mic_info[2]), _extract_muted(chat_info[2])


# ---------------------------------------------------------------------------
# Fallback: BEACN Mix Create Profile XML Reader
# ---------------------------------------------------------------------------

def get_windows_documents_dir() -> str:
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    res = ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
    if res == 0 and buf.value:
        return buf.value
    return os.path.expanduser(r"~\Documents")


def get_active_beacn_mixer_profile_path(cfg: dict) -> Optional[str]:
    override = cfg.get("beacn_profile_override", "").strip()
    if override and os.path.exists(override):
        return override

    appdata = os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming"))
    last_loaded_xml = os.path.join(appdata, "BEACN", "lastLoaded.profiles")
    docs_dir = get_windows_documents_dir()
    mixer_profiles_dir = os.path.join(docs_dir, "BEACN", "profiles", "MixerProfiles")

    profile_name = None
    if os.path.exists(last_loaded_xml):
        try:
            tree = ET.parse(last_loaded_xml)
            root = tree.getroot()
            mixer_el = root.find("MixerProfile")
            if mixer_el is not None:
                profile_name = mixer_el.attrib.get("lastLoadedProfile")
        except Exception:
            pass

    if profile_name and os.path.isdir(mixer_profiles_dir):
        candidate = os.path.join(mixer_profiles_dir, f"{profile_name}.beacnMixer")
        if os.path.exists(candidate):
            return candidate

    if os.path.isdir(mixer_profiles_dir):
        files = [
            os.path.join(mixer_profiles_dir, f)
            for f in os.listdir(mixer_profiles_dir)
            if f.lower().endswith(".beacnmixer")
        ]
        if files:
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            return files[0]

    return None


def read_beacn_xml_mute_states(profile_path: str, cfg: dict) -> Optional[Tuple[bool, bool]]:
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            xml_text = f.read()
        if not xml_text.strip():
            return None
        root = ET.fromstring(xml_text)
    except Exception:
        return None

    mixer_tree = root.find("mixerTree")
    if mixer_tree is None:
        return None

    mic_name_target = cfg.get("mic_channel_name", "Mic").strip().lower()
    chat_name_target = cfg.get("chat_channel_name", "Chat").strip().lower()
    include_knob = bool(cfg.get("include_knob_press_mute", False))

    mic_el = None
    chat_el = None

    for child in mixer_tree:
        if not child.tag.startswith("mixer"):
            continue
        m_name = child.attrib.get("mixerName", "").strip().lower()
        knob_type = child.attrib.get("bartonKnobType", "")
        if mic_el is None and (m_name == mic_name_target or knob_type == "1"):
            mic_el = child
        if chat_el is None and (m_name == chat_name_target or knob_type == "3"):
            chat_el = child

    def is_channel_muted(el: Optional[ET.Element]) -> bool:
        if el is None:
            return False
        btn_muted = el.attrib.get("buttonMuteState", "0") == "1"
        if include_knob:
            knob_muted = el.attrib.get("knobMuteState", "0") == "1"
            return btn_muted or knob_muted
        return btn_muted

    return is_channel_muted(mic_el), is_channel_muted(chat_el)


# ---------------------------------------------------------------------------
# Target State Logic & Main Loop
# ---------------------------------------------------------------------------

def compute_discord_voice_target(
    mic_muted: bool, chat_muted: bool, cfg: dict
) -> Tuple[bool, bool]:
    """
    Compute (discord_mute, discord_deaf) from (beacn_mic_muted, beacn_chat_muted):
      1. Both Mic AND Chat muted on BEACN -> Discord Deafen = True, Mute = True
      2. Mic muted (Chat unmuted)         -> Discord Deafen = False, Mute = True
      3. Mic unmuted                      -> Discord Deafen = False, Mute = False
    """
    if mic_muted and chat_muted:
        return True, True
    if mic_muted and not chat_muted:
        return True, False
    if chat_muted and bool(cfg.get("deafen_when_only_chat_muted", False)):
        return True, True
    return False, False


def format_status_badge(mic_muted: bool, chat_muted: bool, discord_mute: bool, discord_deaf: bool) -> str:
    mic_str = "MUTED" if mic_muted else "LIVE "
    chat_str = "MUTED" if chat_muted else "LIVE "
    if discord_deaf:
        disc_str = "DEAFENED (Mic Muted + Audio Deafened)"
    elif discord_mute:
        disc_str = "MIC MUTED (Audio Live)"
    else:
        disc_str = "UNMUTED & LIVE"
    return f"BEACN [Mic: {mic_str} | Chat: {chat_str}]  ==>  Discord [{disc_str}]"


def run_monitor(once: bool = False, dry_run: bool = False) -> int:
    cfg = load_config()

    # Automatically elevate to Administrator so ReadProcessMemory on BEACN.exe works seamlessly
    if (
        cfg.get("auto_elevate_admin", True)
        and not is_user_admin()
        and "--no-elevate" not in sys.argv
        and "--elevated" not in sys.argv
        and not dry_run
    ):
        log("Requesting Administrator privileges to read live BEACN Mix Create state...")
        if relaunch_as_admin():
            return 0
        log("Warning: Could not elevate to Administrator. Falling back to profile file watcher.")

    print("=" * 72)
    print("  BeacNDiscordLink - BEACN Mix Create <-> Discord Mute/Deafen Sync")
    print("=" * 72)

    kb = DiscordKeybindController(cfg)
    log(f"Discord Keybinds: Toggle Mute = [{kb.mute_key}] | Toggle Deafen = [{kb.deafen_key}]")
    trigger_desc = (
        "Mute Buttons + Knob Press"
        if cfg.get("include_knob_press_mute")
        else "Dedicated Mute Buttons below Mic & Chat knobs"
    )
    log(f"Trigger Mode: {trigger_desc}")

    mem_monitor = BeacNMemoryMonitor(cfg)
    profile_path = get_active_beacn_mixer_profile_path(cfg)
    last_state: Optional[Tuple[bool, bool]] = None
    poll_sec = max(0.02, float(cfg.get("poll_interval_ms", 50)) / 1000.0)

    try:
        while True:
            # 1. Primary: Read real-time hardware mute state from BEACN.exe memory
            states = mem_monitor.read_mute_states()

            # 2. Fallback: Read from active .beacnMixer XML if BEACN.exe isn't accessible
            if states is None and profile_path:
                states = read_beacn_xml_mute_states(profile_path, cfg)

            if states is not None and states != last_state:
                mic_muted, chat_muted = states
                target_mute, target_deaf = compute_discord_voice_target(
                    mic_muted, chat_muted, cfg
                )

                if last_state is None:
                    # Initial state on startup: record current state without firing keybinds
                    kb.initialize_state(target_mute, target_deaf)
                    badge = format_status_badge(mic_muted, chat_muted, target_mute, target_deaf)
                    log(f"{badge} (Initial state ready)")
                else:
                    triggered_keys = kb.sync_to_target(target_mute, target_deaf, dry_run=dry_run)
                    badge = format_status_badge(mic_muted, chat_muted, target_mute, target_deaf)
                    keys_str = ", ".join(triggered_keys) if triggered_keys else "No key needed"
                    if dry_run:
                        log(f"{badge} [Dry Run: {keys_str}]")
                    else:
                        log(f"{badge} [Triggered: {keys_str}]")

                last_state = states

            if once:
                break

            time.sleep(poll_sec)
    except KeyboardInterrupt:
        log("Stopping BeacNDiscordLink. Goodbye!")
        return 0
    finally:
        mem_monitor.close()

    return 0


if __name__ == "__main__":
    run_once = "--once" in sys.argv or "--status" in sys.argv or "--dry-run" in sys.argv
    is_dry = "--dry-run" in sys.argv
    sys.exit(run_monitor(once=run_once, dry_run=is_dry))
