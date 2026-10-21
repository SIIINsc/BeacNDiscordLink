#!/usr/bin/env python3
"""
BeacNDiscordLink
================
Synchronizes your physical BEACN Mix Create mute buttons with Discord's
in-app Mute and Deafen status via Discord Local RPC (IPC).

Behavior:
  - Mic button muted on BEACN (Chat unmuted)  -> Discord Mic Muted (Undeafened)
  - Mic button muted + Chat button muted      -> Discord Deafened (and Muted)
  - Mic button unmuted on BEACN               -> Discord Unmuted (and Undeafened)

Zero external dependencies (100% Python 3 Standard Library on Windows).
"""

import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import secrets
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Default public Discord RPC Application ID (supports OAuth2 PKCE out-of-the-box)
DEFAULT_CLIENT_ID = "1224385725949284403"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DEFAULT_SCOPES = ["rpc", "rpc.voice.read", "rpc.voice.write"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
TOKEN_CACHE_PATH = os.path.join(BASE_DIR, "token_cache.json")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Configuration & Token Cache
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "client_id": DEFAULT_CLIENT_ID,
    "client_secret": "",
    "redirect_uri": "http://127.0.0.1",
    "mic_channel_name": "Mic",
    "chat_channel_name": "Chat",
    "only_button_mute": True,
    "include_knob_press_mute": False,
    "deafen_when_only_chat_muted": False,
    "poll_interval_ms": 50,
    "discord_target": "both",
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
    if not cfg.get("client_id"):
        cfg["client_id"] = DEFAULT_CLIENT_ID
    return cfg


def load_token_cache() -> dict:
    if os.path.exists(TOKEN_CACHE_PATH):
        try:
            with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_token_cache(cache: dict) -> None:
    try:
        with open(TOKEN_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        log(f"Warning: Failed to save token cache: {e}")


# ---------------------------------------------------------------------------
# BEACN Mix Create Profile & State Reader
# ---------------------------------------------------------------------------

def get_windows_documents_dir() -> str:
    """Resolve the user's Windows Documents directory (supports OneDrive redirection)."""
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    # CSIDL_PERSONAL = 5
    res = ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
    if res == 0 and buf.value:
        return buf.value
    return os.path.expanduser(r"~\Documents")


def get_active_beacn_mixer_profile_path(cfg: dict) -> Optional[str]:
    """
    Locate the active .beacnMixer file by reading:
      %APPDATA%\\BEACN\\lastLoaded.profiles
    and resolving:
      <Documents>\\BEACN\\profiles\\MixerProfiles\\<lastLoadedProfile>.beacnMixer
    """
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

    # Fallback: most recently modified .beacnMixer file in MixerProfiles
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


def read_beacn_mute_states(profile_path: str, cfg: dict) -> Optional[Tuple[bool, bool]]:
    """
    Parse the live <mixerTree> in the active .beacnMixer XML file and return:
      (mic_muted, chat_muted)
    Returns None if the file is currently being written by BEACN App.
    """
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            xml_text = f.read()
        if not xml_text.strip():
            return None
        root = ET.fromstring(xml_text)
    except Exception:
        return None

    # Top-level <mixerTree> holds the real-time live state (whereas <Snapshot><mixerTree> is the saved preset)
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

        # Match Mic channel by name or BEACN knob type 1 (Mic)
        if mic_el is None and (m_name == mic_name_target or knob_type == "1"):
            mic_el = child

        # Match Chat channel by name or BEACN knob type 3 (Voice Chat)
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


def compute_discord_voice_target(
    mic_muted: bool, chat_muted: bool, cfg: dict
) -> Tuple[bool, bool]:
    """
    Compute (discord_mute, discord_deaf) from (beacn_mic_muted, beacn_chat_muted).

    Rules:
      1. If BOTH Mic AND Chat are muted on BEACN -> Discord Deafen = True, Mute = True
      2. If Mic is muted (and Chat is not muted) -> Discord Deafen = False, Mute = True
      3. If Mic is unmuted                       -> Discord Deafen = False, Mute = False
         (Unless deafen_when_only_chat_muted is enabled in config.json)
    """
    if mic_muted and chat_muted:
        return True, True
    if mic_muted and not chat_muted:
        return True, False
    if chat_muted and bool(cfg.get("deafen_when_only_chat_muted", False)):
        return True, True
    return False, False


# ---------------------------------------------------------------------------
# Discord Local IPC / RPC Client
# ---------------------------------------------------------------------------

def generate_pkce_pair() -> Tuple[str, str]:
    """Generate an OAuth2 PKCE (code_verifier, code_challenge) pair using S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def exchange_oauth_code(
    client_id: str,
    code: str,
    code_verifier: Optional[str] = None,
    client_secret: str = "",
    redirect_uri: str = "http://127.0.0.1",
) -> dict:
    """Exchange an authorization_code for an OAuth2 access_token at Discord's token endpoint."""
    for include_redirect in (False, True):
        form = {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
        }
        if include_redirect and redirect_uri:
            form["redirect_uri"] = redirect_uri
        if client_secret:
            form["client_secret"] = client_secret
        elif code_verifier:
            form["code_verifier"] = code_verifier

        body = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_TOKEN_URL,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "BeacNDiscordLink/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if not include_redirect and "redirect_uri" in err_body:
                continue
            raise RuntimeError(f"HTTP {e.code}: {err_body}") from e
    raise RuntimeError("Failed to exchange OAuth code.")


def refresh_oauth_token(
    client_id: str,
    refresh_token: str,
    client_secret: str = "",
) -> dict:
    """Refresh an expired OAuth2 access_token."""
    form = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if client_secret:
        form["client_secret"] = client_secret

    body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "BeacNDiscordLink/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


class DiscordIPCConnection:
    """Manages a single Discord Local IPC named pipe connection (\\.\pipe\discord-ipc-X)."""

    def __init__(self, pipe_index: int, client_id: str, client_secret: str, redirect_uri: str):
        self.pipe_index = pipe_index
        self.pipe_path = rf"\\.\pipe\discord-ipc-{pipe_index}"
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.pipe = None
        self.connected = False
        self.authenticated = False
        self.user_id: Optional[str] = None
        self.username: Optional[str] = None
        self.client_label: str = f"discord-ipc-{pipe_index}"

    def close(self) -> None:
        self.connected = False
        self.authenticated = False
        if self.pipe is not None:
            try:
                self.pipe.close()
            except Exception:
                pass
            self.pipe = None

    def _send_frame(self, op: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        header = struct.pack("<II", op, len(raw))
        self.pipe.write(header + raw)

    def _recv_frame(self) -> Tuple[int, dict]:
        header = self.pipe.read(8)
        if not header or len(header) < 8:
            raise ConnectionError("Discord IPC pipe closed.")
        op, length = struct.unpack("<II", header)
        data = b""
        while len(data) < length:
            chunk = self.pipe.read(length - len(data))
            if not chunk:
                raise ConnectionError("EOF while reading Discord IPC frame.")
            data += chunk
        return op, json.loads(data.decode("utf-8"))

    def _request(self, cmd: str, args: dict) -> dict:
        nonce = str(uuid.uuid4())
        self._send_frame(1, {"cmd": cmd, "args": args, "nonce": nonce})
        # Read frames until we get the response matching our nonce
        for _ in range(32):
            op, msg = self._recv_frame()
            if op == 1 and msg.get("nonce") == nonce:
                return msg
        raise RuntimeError(f"Timed out waiting for Discord RPC response to {cmd}")

    def connect_and_authenticate(self, token_cache: dict) -> bool:
        if not os.path.exists(self.pipe_path):
            return False

        try:
            self.pipe = open(self.pipe_path, "r+b", buffering=0)
            # 1. Handshake (op=0)
            self._send_frame(0, {"v": 1, "client_id": self.client_id})
            op, ready = self._recv_frame()
            if op != 1 or ready.get("evt") != "READY":
                self.close()
                return False

            data = ready.get("data", {})
            user = data.get("user", {})
            self.user_id = str(user.get("id", f"pipe_{self.pipe_index}"))
            self.username = user.get("username", "Unknown")
            api_ep = data.get("config", {}).get("api_endpoint", "")
            if "ptb" in api_ep:
                self.client_label = f"Discord PTB ({self.username})"
            elif "canary" in api_ep:
                self.client_label = f"Discord Canary ({self.username})"
            else:
                self.client_label = f"Discord ({self.username})"

            self.connected = True

            # 2. Check cached OAuth token for this user_id + client_id
            cache_key = f"{self.client_id}:{self.user_id}"
            token_entry = token_cache.get(cache_key, {})
            access_token = token_entry.get("access_token")
            refresh_tok = token_entry.get("refresh_token")

            if access_token:
                auth_resp = self._request("AUTHENTICATE", {"access_token": access_token})
                if auth_resp.get("evt") != "ERROR":
                    self.authenticated = True
                    log(f"Connected & authenticated with {self.client_label}")
                    return True

                # Try refreshing token if we have a refresh_token
                if refresh_tok:
                    try:
                        new_tok = refresh_oauth_token(
                            self.client_id, refresh_tok, self.client_secret
                        )
                        access_token = new_tok.get("access_token")
                        if access_token:
                            token_cache[cache_key] = {
                                "access_token": access_token,
                                "refresh_token": new_tok.get("refresh_token", refresh_tok),
                                "username": self.username,
                            }
                            save_token_cache(token_cache)
                            auth_resp = self._request("AUTHENTICATE", {"access_token": access_token})
                            if auth_resp.get("evt") != "ERROR":
                                self.authenticated = True
                                log(f"Connected & refreshed auth with {self.client_label}")
                                return True
                    except Exception:
                        pass

            # 3. No valid cached token -> Trigger interactive in-app AUTHORIZE prompt in Discord
            log(f"Requesting one-time authorization in {self.client_label}...")
            log(">>> Please click 'Authorize' inside your Discord window! <<<")

            verifier, challenge = generate_pkce_pair()
            auth_args = {
                "client_id": self.client_id,
                "scopes": DEFAULT_SCOPES,
            }
            if not self.client_secret:
                auth_args["code_challenge"] = challenge
                auth_args["code_challenge_method"] = "S256"

            code_resp = self._request("AUTHORIZE", auth_args)
            if code_resp.get("evt") == "ERROR":
                err_msg = code_resp.get("data", {}).get("message", "Unknown error")
                log(f"Authorization declined or failed on {self.client_label}: {err_msg}")
                self.close()
                return False

            code = code_resp.get("data", {}).get("code")
            if not code:
                self.close()
                return False

            tok_data = exchange_oauth_code(
                client_id=self.client_id,
                code=code,
                code_verifier=verifier if not self.client_secret else None,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
            )
            access_token = tok_data.get("access_token")
            if not access_token:
                self.close()
                return False

            token_cache[cache_key] = {
                "access_token": access_token,
                "refresh_token": tok_data.get("refresh_token", ""),
                "username": self.username,
            }
            save_token_cache(token_cache)

            auth_resp = self._request("AUTHENTICATE", {"access_token": access_token})
            if auth_resp.get("evt") == "ERROR":
                log(f"AUTHENTICATE failed on {self.client_label}: {auth_resp}")
                self.close()
                return False

            self.authenticated = True
            log(f"Authorized & connected to {self.client_label}!")
            return True

        except Exception as e:
            self.close()
            return False

    def set_voice_state(self, mute: bool, deaf: bool) -> bool:
        """
        Explicitly set Discord's voice settings:
          - If deaf is True: sets {"deaf": True, "mute": True}
          - If deaf is False and mute is True: sets {"deaf": False, "mute": True}
          - If both False: sets {"deaf": False, "mute": False}
        """
        if not self.connected or not self.authenticated:
            return False
        try:
            resp = self._request("SET_VOICE_SETTINGS", {"mute": bool(mute), "deaf": bool(deaf)})
            return resp.get("evt") != "ERROR"
        except Exception:
            self.close()
            return False


class DiscordRPCManager:
    """Manages connections across all running Discord instances (discord-ipc-0 .. 9)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.token_cache = load_token_cache()
        self.connections: Dict[int, DiscordIPCConnection] = {}

    def ensure_connections(self) -> List[DiscordIPCConnection]:
        target_filter = self.cfg.get("discord_target", "both").lower()
        active: List[DiscordIPCConnection] = []

        for idx in range(4):
            pipe_path = rf"\\.\pipe\discord-ipc-{idx}"
            conn = self.connections.get(idx)

            if conn is not None and conn.connected and conn.authenticated:
                if self._matches_target(conn, target_filter):
                    active.append(conn)
                continue

            if os.path.exists(pipe_path):
                new_conn = DiscordIPCConnection(
                    pipe_index=idx,
                    client_id=self.cfg.get("client_id", DEFAULT_CLIENT_ID),
                    client_secret=self.cfg.get("client_secret", ""),
                    redirect_uri=self.cfg.get("redirect_uri", "http://127.0.0.1"),
                )
                if new_conn.connect_and_authenticate(self.token_cache):
                    self.connections[idx] = new_conn
                    if self._matches_target(new_conn, target_filter):
                        active.append(new_conn)

        return active

    @staticmethod
    def _matches_target(conn: DiscordIPCConnection, target_filter: str) -> bool:
        if target_filter in ("both", "all", ""):
            return True
        if target_filter == "ptb":
            return "ptb" in conn.client_label.lower()
        if target_filter in ("stable", "standard", "discord"):
            return "ptb" not in conn.client_label.lower() and "canary" not in conn.client_label.lower()
        return True

    def sync_state(self, mute: bool, deaf: bool) -> int:
        conns = self.ensure_connections()
        success_count = 0
        for conn in conns:
            if conn.set_voice_state(mute=mute, deaf=deaf):
                success_count += 1
        return success_count


# ---------------------------------------------------------------------------
# Main Monitor Loop
# ---------------------------------------------------------------------------

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
    print("=" * 70)
    print("  BeacNDiscordLink - BEACN Mix Create <-> Discord Mute/Deafen Sync")
    print("=" * 70)

    cfg = load_config()
    profile_path = get_active_beacn_mixer_profile_path(cfg)

    if not profile_path:
        log("ERROR: Could not find any .beacnMixer profile in Documents\\BEACN\\profiles\\MixerProfiles.")
        log("Make sure the BEACN App is installed and has saved a Mixer profile.")
        return 1

    log(f"Watching BEACN Profile: {profile_path}")
    trigger_desc = (
        "Mute Buttons + Knob Press"
        if cfg.get("include_knob_press_mute")
        else "Dedicated Mute Buttons below Mic & Chat knobs"
    )
    log(f"Trigger Mode: {trigger_desc}")

    rpc = DiscordRPCManager(cfg)
    if not dry_run:
        conns = rpc.ensure_connections()
        if not conns:
            log("Waiting for Discord to open and authorize...")

    last_mtime = 0.0
    last_state: Optional[Tuple[bool, bool]] = None
    last_profile_check = time.time()
    poll_sec = max(0.02, float(cfg.get("poll_interval_ms", 50)) / 1000.0)

    try:
        while True:
            now = time.time()
            # Periodically check if the user switched profiles in the BEACN App
            if now - last_profile_check > 5.0:
                last_profile_check = now
                new_profile = get_active_beacn_mixer_profile_path(cfg)
                if new_profile and new_profile != profile_path:
                    profile_path = new_profile
                    last_mtime = 0.0
                    log(f"Switched active BEACN Profile to: {profile_path}")

            try:
                mtime = os.path.getmtime(profile_path)
            except OSError:
                mtime = 0.0

            if mtime != last_mtime:
                states = read_beacn_mute_states(profile_path, cfg)
                if states is not None:
                    last_mtime = mtime
                    mic_muted, chat_muted = states
                    if states != last_state:
                        last_state = states
                        target_mute, target_deaf = compute_discord_voice_target(
                            mic_muted, chat_muted, cfg
                        )
                        synced = 0 if dry_run else rpc.sync_state(mute=target_mute, deaf=target_deaf)
                        badge = format_status_badge(
                            mic_muted, chat_muted, target_mute, target_deaf
                        )
                        if dry_run:
                            log(f"{badge} (Dry Run)")
                        else:
                            log(f"{badge} (Synced to {synced} Discord client(s))")

            if once:
                break

            time.sleep(poll_sec)
    except KeyboardInterrupt:
        log("Stopping BeacNDiscordLink. Goodbye!")
        return 0

    return 0


if __name__ == "__main__":
    run_once = "--once" in sys.argv or "--status" in sys.argv or "--dry-run" in sys.argv
    is_dry = "--dry-run" in sys.argv
    sys.exit(run_monitor(once=run_once, dry_run=is_dry))
