# BeacNDiscordLink 🎙️🎚️ ➡️ 💬

Synchronizes your physical **BEACN Mix Create** mute buttons (`Mic` and `Chat` channels) with **Discord's in-app Mute and Deafen status** in real time so people in your Discord voice channel can see when you mute or deafen yourself using your BEACN hardware.

---

## ✨ What It Does

| BEACN Mix Create State | Discord Voice Status | What Others See in Discord |
| :--- | :--- | :--- |
| **`Mic` button Muted** *(and `Chat` Unmuted)* | **Mic Muted** *(Audio Live)* | 🔴 Red **Muted** microphone icon next to your name |
| **Both `Mic` AND `Chat` buttons Muted** | **Deafened** *(Mic + Audio Muted)* | 🔴 Red **Deafened** headphones + muted mic icons |
| **`Mic` button Unmuted** | **Unmuted & Live** | 🟢 Normal active voice state |

* **100% Real-Time Hardware Detection:** Reads the live hardware mute button state directly from `BEACN.exe` process memory (`50ms` polling, `<0.1%` CPU usage), with automatic fallback to your active `.beacnMixer` profile.
* **Dedicated Mute Buttons Only (by default):** Only the physical **Mute buttons below the `Mic` and `Chat` knobs** trigger Discord Mute/Deafen (pressing the volume knobs themselves will not trigger Discord unless you enable it in `config.json`).
* **Zero External Dependencies:** Uses 100% built-in **Python 3 Standard Library** (`ctypes` Win32 API) on Windows—no `pip install` required.

---

## 🚀 Quick Start (2 Minutes)

### Step 1: Set Your Mute & Deafen Keybinds in Discord
1. Open **Discord** $\rightarrow$ **User Settings (⚙️)** $\rightarrow$ **Keybinds**.
2. Click **Add a Keybind** twice and set:
   * **Action:** `Toggle Mute` $\rightarrow$ **Keybind:** `F3` *(or any key you prefer)*
   * **Action:** `Toggle Deafen` $\rightarrow$ **Keybind:** `F4` *(or any key you prefer)*

*(If you prefer different keys like `F13`/`F14` or `ctrl+shift+m`, just edit `"mute_keybind"` and `"deafen_keybind"` in [`config.json`](config.json).)*

### Step 2: Run `Start-BeacNDiscordLink.bat`
1. Make sure **Python 3** is installed on Windows ([python.org](https://www.python.org/downloads/) — check **"Add Python to PATH"** during installation).
2. Double-click **`Start-BeacNDiscordLink.bat`**.
3. Click **Yes** on the Windows Administrator prompt *(needed because `BEACN.exe` runs as Administrator)*.
4. Press the **Mute button** under your **Mic** knob (and **Chat** knob) on your **BEACN Mix Create**—Discord will immediately toggle Mute (`F3`) and Deafen (`F4`)!

---

## 🔄 Run Automatically with Windows (Hidden in Background)

* **Enable Auto-Start:** Double-click **`Install-AutoStart.bat`**. This adds a shortcut to your Windows Startup folder (`shell:startup`) that launches `Start-Hidden.vbs` silently in the background when you log in.
* **Disable Auto-Start:** Double-click **`Uninstall-AutoStart.bat`**.

---

## ⚙️ Configuration (`config.json`)

You can customize settings in `config.json`:

```json
{
  "mute_keybind": "F3",
  "deafen_keybind": "F4",
  "mic_channel_name": "Mic",
  "chat_channel_name": "Chat",
  "only_button_mute": true,
  "include_knob_press_mute": false,
  "deafen_when_only_chat_muted": false,
  "poll_interval_ms": 50,
  "auto_elevate_admin": true,
  "beacn_profile_override": ""
}
```

| Option | Default | Description |
| :--- | :--- | :--- |
| `mute_keybind` | `"F3"` | Keybind configured in Discord for **Toggle Mute** (supports `F1`–`F24` or combos like `"ctrl+shift+m"`). |
| `deafen_keybind` | `"F4"` | Keybind configured in Discord for **Toggle Deafen** (supports `F1`–`F24` or combos like `"ctrl+shift+d"`). |
| `mic_channel_name` | `"Mic"` | Name of your Microphone knob channel in the BEACN App. |
| `chat_channel_name` | `"Chat"` | Name of your Voice Chat knob channel in the BEACN App. |
| `include_knob_press_mute` | `false` | Set to `true` if you also want pressing the top of the knob to trigger Discord Mute/Deafen. |
| `deafen_when_only_chat_muted` | `false` | Set to `true` if you want muting `Chat` alone (even when `Mic` is still live) to deafen you on Discord. |
| `poll_interval_ms` | `50` | How often (in milliseconds) to check the live BEACN hardware state. |

---

## 📄 License

Released under the [MIT License](LICENSE).
