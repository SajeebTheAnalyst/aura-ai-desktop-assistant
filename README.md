<div align="center">

# AURA — Voice AI Desktop Assistant

**A frameless, always-listening desktop AI assistant for Windows.** Speak a command or ask a question — AURA transcribes it with a natural speech engine, understands it with Google Gemini, acts on it with real PC automation, and talks back through a runtime voice engine. No wake word, no button-mashing: press **Listen once**, keep the conversation going.

</div>

---

## ✨ Features

- **Continuous hands-free conversation** — press Listen once; AURA automatically returns to listening after every answer (no wake word required).
- **Natural turn-taking** — VAD-style speech segmentation with ambient-noise calibration and a 1.35 s trailing-silence end-of-speech. Short pauses ("open Chrome and… go to YouTube") are captured as one complete utterance.
- **Real Windows automation** — open apps (Power BI, PowerPoint, Chrome, Notepad, Excel, Settings…), system actions (shutdown, restart, sleep, lock), web searches, and **direct YouTube song playback** via the top search result.
- **Gemini-powered intent engine** — every transcript is classified into a single structured intent (`OPEN_APP`, `SYSTEM_ACTION`, `WEB_SEARCH`, `PLAY_MUSIC`, `CHAT`) with a short, spoken reply generated locally (JSON schema, ≤100 tokens).
- **Bilingual recognition** — speech is recognized in English (`en-US`) and Bangla/Banglish (`bn-BD`).
- **Jarvis-style visualizer** — a neon cyan orb that reacts to the live voice state (Idle → Listening → Thinking → Answering), a real-time Chat transcript tab, and a frameless glass UI.
- **Fault-tolerant voice loop** — empty transcripts never reach the LLM, STT/TTS failures recover gracefully, and stale worker threads can never restart listening (generation-guarded).
- **Chat & voice are 1:1 synced** — every reply that lands in the chat is exactly what AURA says aloud.

---

## 🖥️ Requirements

- **Windows 10/11** (uses Windows-specific commands: `start`, `shutdown`, `ms-settings`, `rundll32`)
- **Python 3.12+** (developed on 3.14)
- A working microphone and speakers
- A **Google AI Studio / Gemini API key**

---
## 📦 Installation

```powershell
# 1) Clone the repository
git clone https://github.com/SajeebTheAnalyst/aura-ai-desktop-assistant.git
cd aura-ai-desktop-assistant

# 2) Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3) Install dependencies
pip install -r requirements.txt

# 4) Configure your Gemini API key
copy .env.example .env
#    -> edit .env and paste your key from https://aistudio.google.com/apikey
```

## ⚙️ Configuration (`.env`)

| Variable                   | Default                | Description                                           |
| -------------------------- | ---------------------- | ----------------------------------------------------- |
| `GEMINI_API_KEY`           | *(required)*           | Google AI Studio / Gemini API key                     |
| `GEMINI_MODEL`             | `gemini-3.6-flash`     | Primary model for intent classification               |
| `GEMINI_FALLBACK_MODEL`    | `gemini-3.5-flash-lite`| Fallback model (used when the primary is rate-limited)|
| `GEMINI_MAX_OUTPUT_TOKENS` | `64`                   | Max reply tokens (keeps spoken answers short & fast)  |

---

## ▶️ Run AURA

```powershell
# Activate the venv (if not already active)
.\.venv\Scripts\Activate.ps1

# Start AURA
python main.py
```

The assistant boots into the HUD, pre-warms the speech engine and Gemini client, and **starts listening automatically**.

### 🎙️ What you can say

| You say…                                   | AURA does…                                                    |
| ------------------------------------------ | ------------------------------------------------------------- |
| "What's your name?"                        | Answers conversationally through voice 🔊                      |
| "What is Power BI?"                        | Gives a spoken answer (uses your profile context)              |
| "Open Power BI" / "Open Chrome"            | Launches the app                                               |
| "Open YouTube" / "Go to Google"            | Opens the site in your default browser                         |
| "Search for python pandas tutorial"        | Opens a Google search                                          |
| "Play Shape of You on YouTube"             | **Plays the top YouTube result immediately**                    |
| "Go to settings"                           | Opens Windows Settings                                          |
| "Shutdown the PC" / "Put the PC to sleep"  | Runs the system action                                          |

**Control shortcuts:** `Ctrl+Shift+Q` stops the voice session · right-click the window for **Minimize / Exit AURA** · the mic button starts a fresh listen.

> 💡 **Full multi-turn session:** Ask a question → hear the answer → ask the *next* question **without pressing anything**. AURA automatically resumes listening the moment it finishes speaking. Pause stops listening; resume continues; stop ends the session.

---
## 🏗️ Architecture

```
main.py                          # entry point: QApplication + MainWindow + Assistant
├── core/
│   ├── assistant.py             # voice coordinator: capture → transcribe → plan → act → speak
│   ├── context.py               # AURA persona + user profile + strict JSON intent schema
├── services/
│   ├── stt_service.py           # VAD-style segmented mic capture + Google speech recognition
│   ├── tts_service.py           # non-blocking, queue-based speech engine (pyttsx3) worker
│   ├── llm_service.py           # Gemini planner (JSON schema, token cap, fallback models, cooldown)
│   ├── system_control.py        # OS automation: apps, system actions, web, YouTube playback
│   └── os_service.py            # (legacy) allowlisted Windows/browser operations
├── ui/
│   └── main_window.py           # frameless Jarvis HUD: neon orb, status text, Home/Chat tabs
└── tests/
    └── test_voice_loop.py       # 12 focused voice-lifecycle tests
```

### How a voice turn works

```
LISTENING  →  user speaks  →  end-of-speech (1.35 s silence)
   →  TRANSCRIBING  →  STT transcript
   →  THINKING      →  Gemini intent {intent, target, response}
   →  ANSWERING     →  TTS speaks  →  auto-return to LISTENING
```

The voice loop is **generation-guarded**: every Listen/Pause/Stop bumps a generation counter, so a stale worker from an earlier turn can never schedule a new listen or crash the session. Worker threads are cleaned up safely via Qt's `finished` signal + `deleteLater()`.

- **Empty/near-empty** captures never reach Gemini — AURA simply listens again.
- **STT failure** → reports and retries; **TTS failure** → silently re-initializes the engine and retries (up to 3 attempts) — the conversation never dies.
- **TTS ducking**: the microphone stays paused while AURA speaks, so it never hears its own voice.

---

## ✅ Testing

```powershell
# From the project root (venv active)
python tests/test_voice_loop.py
```

Runs **12 automated tests** (no microphone/network required) covering: session start, transcript delivery, auto-restart after TTS, pause/stop blocking restarts, stale-worker cancellation, empty-transcript filtering, STT failure recovery, TTS-failure resilience, single-worker enforcement, and QThread lifetime safety.

---

## 🧰 Tech Stack

| Layer         | Technology                                                       |
| ------------- | ---------------------------------------------------------------- |
| UI            | **PySide6 (Qt 6)** — `QWebEngineView`, frameless translucent window|
| Speech-to-Text| `sounddevice` capture + VAD + Google Speech Recognition (en/bn)  |
| Text-to-Speech| `pyttsx3` (dedicated queue worker, silent retry/re-init)         |
| LLM / Intents | **Google Gemini** via `google-genai` (structured JSON output)    |
| Automation    | `webbrowser`, `subprocess`/`os`, **pywhatkit** (`playonyt`), `pygetwindow` |
| Vision        | HTML/CSS/JS neon orb visualizer rendered in Qt WebEngine        |

---

## 🙏 Acknowledgments

Built with Google Gemini, PySide6, SpeechRecognition, sounddevice, pyttsx3, and pywhatkit.