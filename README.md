# AURA - Multilingual AI Desktop Assistant

AURA is a safety-first Windows desktop assistant for English, Bangla, Banglish, and mixed-language commands. Phase 1 through Phase 5 are implemented. Phase 6 has not started.

## Capabilities

- Typed and microphone input through Faster-Whisper STT
- Optional OpenAI-powered structured command understanding
- Deterministic parser fallback when the LLM is unavailable
- English, Bangla, Banglish, and mixed-language starter understanding
- Local Windows text-to-speech with pyttsx3
- Allowlisted Windows application launching and closing
- Browser website opening and Google search
- Controlled keyboard actions: `type_text`, `press_key`, and `hotkey`
- Safe multi-step execution through the existing router
- Lightweight action verification where practical
- Risk-based permissions and visible confirmation for medium/high-risk actions
- Shared cancellation, Stop button, tray Stop, and `Ctrl+Shift+Q`
- Local activity logging without API keys or microphone recordings

The application allowlist currently includes Notepad, Calculator, Paint, Explorer, Chrome, Edge, and Excel. Availability is checked on the local machine; an application that is not installed is reported instead of launching an arbitrary path. Mouse automation, arbitrary window handles, Excel/Power Query workflows, shell execution, and unrestricted computer control are not implemented.

## Architecture

```text
Voice / Text Input
	|
Speech-to-Text
	|
LLM Intent Understanding or Deterministic Fallback
	|
Structured Command
	|
Schema Validation
	|
Risk / Permission Policy
	|
Allowlisted Command Router
	|
Automation Adapter
	|
Windows / Browser
	|
Verification
	|
Response
	|
Text-to-Speech
```

### Security boundary: LLM is not the executor

The LLM can only return structured intent data. It cannot run PowerShell, CMD, Python, `subprocess`, `os.system`, `eval`, or `exec`. Local validation rejects unsupported intents and arbitrary executable paths. The application-controlled router is the only path to an automation adapter, and `PermissionManager` determines risk independently of any LLM-provided value.

## Safety controls

- Applications resolve through a centralized allowlist and known executable names.
- Browser destinations accept only normalized `http://` or `https://` URLs.
- `javascript:`, `data:`, `file:`, `vbscript:`, malformed URLs, and shell-injection-shaped destinations are rejected.
- Search terms are URL-encoded as data and are never passed to a shell.
- Each multi-step action is checked for cancellation, validation, and permission before execution.
- `AURA, stop`, the GUI Stop button, tray Stop, and `Ctrl+Shift+Q` cancel the current task.
- No microphone recordings or generated speech audio are persisted.
- `.env` and local logs are ignored by Git. API keys must remain in the local environment.
- Activity logs record operational metadata and errors, never API keys, authentication headers, or raw audio.

Browser verification confirms that launch was initiated; it does not inspect page content. Application verification is lightweight and process-based.

## Setup

Python 3.14.2 is the verified development environment on Windows.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set only the values you need. The OpenAI provider is optional; without `AURA_LLM_API_KEY`, AURA uses the deterministic parser.

Start AURA from the repository root:

```powershell
python -m app.main
```

## Configuration

The application reads these environment variables:

```text
AURA_LLM_PROVIDER=openai
AURA_LLM_MODEL=gpt-4o-mini
AURA_LLM_API_KEY=
AURA_TTS_ENABLED=true
AURA_TTS_VOICE=
AURA_TTS_RATE=
AURA_TTS_VOLUME=
```

Keep real API keys in `.env` or the process environment only. Never commit `.env`, keys, tokens, or credentials.

## Tests and checks

Run the full test suite:

```powershell
python -m unittest discover -s tests -v
```

Compile the project:

```powershell
python -m compileall -q app tests
```

The test suite uses fake LLM, browser, keyboard, and TTS backends where hardware or a real API would otherwise be required.

## Repository scope

This checkpoint covers Phases 1-5 only. Excel COM, spreadsheet workflows, Power Query, advanced data analysis, autonomous screen understanding, unrestricted shell/Python execution, packaging, and installers belong to later work and are intentionally absent.
