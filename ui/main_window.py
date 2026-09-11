"""AURA frameless Jarvis-style HUD: neon neural orb, live status, and tabbed chat.

The whole visualizer (glowing orb, status text, mic button, Home/Chat tabs and
frameless window controls) is a self-contained HTML/CSS/JS template hosted in a
QWebEngineView. Python drives it through ``window.updateState(state, text)`` and
``window.addMessage(role, text)``; the page talks back through the ``aura``
QtWebChannel bridge (mic click, minimize, close, drag).
"""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QTimer, Qt, QThread, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QMenu

from core.assistant import Assistant, AssistantResponse


VISUALIZER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AURA</title>
<style>
:root {
  --cyan: #00F0FF;
  --blue: #0066FF;
  --wave: 5.2s;      /* fluid-wave speed; JS shortens it in LISTENING/ANSWERING */
  --pulse: 3.4s;     /* core pulse speed */
  --breath: 4.6s;    /* outer glow breathing */
  --ring: 12s;       /* ring rotation speed */
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 100%; height: 100%; overflow: hidden; }
body {
  background: transparent;
  font-family: "Segoe UI", system-ui, "Helvetica Neue", sans-serif;
  color: #cfeaff;
  user-select: none;
  cursor: default;
}
#app {
  position: fixed; inset: 0;
  display: flex; flex-direction: column;
  background:
    radial-gradient(ellipse at 50% 42%, rgba(13, 22, 48, .66), rgba(6, 11, 28, .52) 58%, rgba(2, 4, 12, .40) 100%);
}
/* ---------------- header: brand, tabs, window controls ---------------- */
#header {
  flex: 0 0 42px;
  -webkit-app-region: drag;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 12px;
  background: linear-gradient(180deg, rgba(9, 15, 33, .94), rgba(5, 9, 22, .62));
  border-bottom: 1px solid rgba(0, 150, 255, .35);
  box-shadow: 0 2px 18px rgba(0, 120, 255, .30);
}
#brand {
  font-size: 13px; font-weight: 700; letter-spacing: 4px; color: #bff6ff;
  text-shadow: 0 0 10px rgba(0, 240, 255, .75);
}
#tabs { display: flex; gap: 16px; -webkit-app-region: no-drag; }
#tabs button {
  position: relative;
  background: transparent; border: none; cursor: pointer; font: inherit;
  font-size: 13px; letter-spacing: .6px; padding: 7px 2px; color: #7fa8cf;
}
#tabs button:hover { color: #bff6ff; }
#tabs button.active {
  color: #00F0FF;
  text-shadow: 0 0 10px rgba(0, 240, 255, .9);
  border-bottom: 2px solid #00F0FF;
}
#tab-badge {
  position: absolute; top: 8px; right: -6px; width: 8px; height: 8px;
  border-radius: 50%; background: #00F0FF;
  box-shadow: 0 0 8px rgba(0, 240, 255, .9); display: none;
}
#controls { display: flex; -webkit-app-region: no-drag; }
#controls button {
  width: 34px; height: 26px; margin-left: 4px; border-radius: 6px;
  background: rgba(0, 60, 120, .22); border: 1px solid rgba(0, 180, 255, .35);
  color: #bfeaff; font: inherit; font-size: 14px; line-height: 1; cursor: pointer;
}
#controls button:hover { background: rgba(0, 200, 255, .30); box-shadow: 0 0 12px rgba(0, 200, 255, .5); }
#btn-close:hover { background: rgba(255, 60, 60, .35); color: #fff; }
/* ---------------- main split ---------------- */
#main { flex: 1 1 auto; position: relative; }
/* ---------------- Home: orb + status + mic ---------------- */
#home-view {
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 24px;
}
#orb {
  position: relative; width: 272px; height: 272px;
  transition: transform .45s ease-in-out;
  transform-origin: center center;
}
.orb-glow {
  position: absolute; inset: -44px; border-radius: 50%;
  background: radial-gradient(circle, rgba(0, 240, 255, .30), rgba(0, 120, 255, .16) 44%, rgba(0, 0, 12, 0) 70%);
  animation: orbBreath var(--breath) ease-in-out infinite;
}
.orb-ring {
  position: absolute; inset: 16px; pointer-events: none;
  filter: drop-shadow(0 0 6px rgba(0, 240, 255, .9))
          drop-shadow(0 0 18px rgba(0, 150, 255, .55))
          drop-shadow(0 0 40px rgba(0, 60, 255, .35));
  animation: orbRingSpin var(--ring) linear infinite;
}
.orb-ring svg { width: 100%; height: 100%; display: block; }
.orb-core {
  position: absolute; inset: 34px; border-radius: 50%;
  background: radial-gradient(circle at 50% 50%,
    rgba(214, 246, 255, .95) 0%, rgba(0, 232, 255, .85) 9%,
    rgba(0, 170, 255, .60) 26%, rgba(0, 102, 255, .38) 45%,
    rgba(8, 24, 64, .55) 68%, rgba(2, 8, 26, .95) 92%);
  box-shadow: 0 0 26px rgba(0, 160, 255, .35), inset 0 0 36px rgba(0, 120, 255, .5);
  animation: corePulse var(--pulse) ease-in-out infinite;
}
.orb-fluid, .orb-fluid-rev {
  position: absolute; inset: 26px; border-radius: 50%;
  background:
    radial-gradient(circle at 28% 26%, rgba(0, 240, 255, .55), transparent 55%),
    radial-gradient(circle at 74% 70%, rgba(30, 140, 255, .45), transparent 55%),
    radial-gradient(circle at 50% 50%, transparent, rgba(0, 60, 180, .22) 70%);
  filter: blur(4px);
}
.orb-fluid { animation: fluidWave var(--wave) ease-in-out infinite; }
.orb-fluid-rev { animation: fluidWaveRev var(--wave) ease-in-out infinite; }
.orb-spark {
  position: absolute; inset: 40px; border-radius: 50%; pointer-events: none;
  box-shadow:
    0 0 2px rgba(0, 240, 255, .9),
    3px -4px 0 1.5px rgba(255, 255, 255, .85),
    -6px 5px 0 1.5px rgba(0, 200, 255, .8),
    7px 4px 0 1.5px rgba(0, 150, 255, .7),
    -4px -7px 0 1.5px rgba(90, 220, 255, .7);
  animation: sparkOrbit var(--ring) linear infinite;
}
@keyframes orbBreath { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.13); opacity: .80; } }
@keyframes orbRingSpin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes corePulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.06); } }
@keyframes fluidWave {
  0% { transform: scale(1) rotate(0deg); opacity: .85; }
  25% { transform: scale(1.10) rotate(24deg); opacity: 1; }
  50% { transform: scale(.92) rotate(48deg); opacity: .72; }
  75% { transform: scale(1.12) rotate(72deg); opacity: 1; }
  100% { transform: scale(1) rotate(96deg); opacity: .85; }
}
@keyframes fluidWaveRev {
  0% { transform: scale(1) rotate(0deg); opacity: .80; }
  25% { transform: scale(.94) rotate(-18deg); opacity: 1; }
  50% { transform: scale(1.08) rotate(-36deg); opacity: .80; }
  75% { transform: scale(.90) rotate(-54deg); opacity: 1; }
  100% { transform: scale(1) rotate(-72deg); opacity: .80; }
}
@keyframes sparkOrbit { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* ---- reactive state aura: IDLE soft / LISTENING pulse ring / ANSWERING blaze ---- */
body.answering-state #orb { transform: scale(1.2); }
body.answering-state .orb-ring {
  filter: drop-shadow(0 0 12px rgba(0, 240, 255, .95))
          drop-shadow(0 0 35px #00F0FF)
          drop-shadow(0 0 70px rgba(0, 102, 255, .45));
}
body.answering-state .orb-fluid,
body.answering-state .orb-fluid-rev { filter: blur(6px) brightness(1.2); }
body.idle-state .orb-glow { filter: saturate(.75); }
body.idle-state .orb-spark { opacity: .35; }
.orb-pulse-ring {
  position: absolute; inset: 8px; border-radius: 50%;
  border: 3px solid rgba(0, 240, 255, .85);
  box-shadow: 0 0 16px rgba(0, 240, 255, .70);
  display: none;
  animation: pulseRingBreath 1.6s ease-in-out infinite;
}
body.listening-state .orb-pulse-ring { display: block; }
@keyframes pulseRingBreath {
  0%, 100% { transform: scale(1); opacity: .55; box-shadow: 0 0 10px rgba(0, 240, 255, .5); }
  50% { transform: scale(1.1); opacity: 1; box-shadow: 0 0 28px rgba(0, 240, 255, .95); }
}
#status-text {
  min-height: 26px; text-align: center;
  font-size: 17px; font-weight: 600; letter-spacing: 1.6px; color: #bffcff;
  text-shadow: 0 0 12px rgba(0, 240, 255, .85);
}
#mic-button {
  width: 158px; height: 52px; border-radius: 26px; border: none; cursor: pointer;
  background: linear-gradient(135deg, #0096FF, #0044FF);
  box-shadow: 0 5px 20px rgba(0, 110, 255, .65),
              inset 0 0 0 1px rgba(0, 240, 255, .85),
              inset 0 0 20px rgba(0, 240, 255, .30);
  display: inline-flex; align-items: center; justify-content: center; gap: 9px;
  font: inherit; font-size: 13px; font-weight: 700; letter-spacing: 1.2px; color: #ffffff;
}
#mic-button:hover {
  box-shadow: 0 6px 26px rgba(0, 150, 255, .85),
              inset 0 0 0 1px rgba(0, 240, 255, 1),
              inset 0 0 22px rgba(0, 240, 255, .4);
}
#mic-button:active { transform: translateY(2px) scale(.97); }
body.busy #mic-button { animation: micPulse 1.2s ease-in-out infinite; }
@keyframes micPulse {
  0%, 100% { box-shadow: 0 5px 20px rgba(0, 110, 255, .65), inset 0 0 0 1px rgba(0, 240, 255, .85); }
  50% { box-shadow: 0 5px 34px rgba(0, 230, 255, .9), inset 0 0 0 1.5px rgba(255, 255, 255, .95); }
}
#mic-icon { width: 22px; height: 22px; display: block; }
/* ---------------- Chat: transcript log ---------------- */
#chat-view { position: absolute; inset: 0; display: none; }
#chat-log {
  position: absolute; top: 10px; left: 12px; right: 12px; bottom: 10px;
  overflow-y: auto; overflow-x: hidden;
  background: rgba(5, 10, 24, .84);
  border: 1px solid rgba(0, 170, 255, .35); border-radius: 14px;
  box-shadow: 0 0 26px rgba(0, 110, 255, .22);
  padding: 16px; font-size: 13px; line-height: 1.55;
}
#chat-log::-webkit-scrollbar { width: 8px; }
#chat-log::-webkit-scrollbar-thumb { background: rgba(0, 160, 255, .55); border-radius: 4px; }
#chat-empty { color: #6f97c4; font-style: italic; padding: 6px 0; }
.msg { display: flex; gap: 9px; margin: 4px 0 10px; padding: 6px 10px; border-radius: 9px; }
.msg.user { background: rgba(0, 90, 255, .12); }
.msg.aura { background: rgba(0, 220, 255, .10); }
.msg .label { font-weight: 700; min-width: 52px; }
.msg.user .label { color: #ffffff; text-shadow: 0 0 8px rgba(255, 255, 255, .6); }
.msg.aura .label { color: #00F0FF; text-shadow: 0 0 9px rgba(0, 240, 255, .8); }
.msg .body { flex: 1 1 auto; color: #cfeaff; word-break: break-word; white-space: pre-wrap; }
</style>
</head>
<body>
<div id="app">
  <header id="header">
    <div id="brand">AURA</div>
    <nav id="tabs">
      <button id="tab-home" class="active">Home</button>
      <button id="tab-chat">Chat<span id="tab-badge"></span></button>
    </nav>
    <div id="controls">
      <button id="btn-min" title="Minimize" aria-label="Minimize">&mdash;</button>
      <button id="btn-close" title="Close" aria-label="Close">&#10005;</button>
    </div>
  </header>
  <div id="main">
    <div id="home-view">
      <div id="orb">
        <div class="orb-glow"></div>
        <div class="orb-ring">
          <svg viewBox="0 0 100 100" aria-hidden="true">
            <defs>
              <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#00F0FF"/>
                <stop offset="45%" stop-color="#00B3FF"/>
                <stop offset="75%" stop-color="#0080FF"/>
                <stop offset="100%" stop-color="#0066FF"/>
              </linearGradient>
            </defs>
            <circle cx="50" cy="50" r="46" fill="none" stroke="url(#ringGrad)" stroke-width="2.6"/>
            <circle cx="50" cy="50" r="42" fill="none" stroke="url(#ringGrad)" stroke-width=".7" opacity=".7"/>
          </svg>
        </div>
        <div class="orb-fluid"></div>
        <div class="orb-fluid-rev"></div>
        <div class="orb-pulse-ring"></div>
        <div class="orb-spark"></div>
        <div class="orb-core"></div>
      </div>
      <div id="status-text">Listening...</div>
      <button id="mic-button" aria-label="Talk to AURA">
        <svg id="mic-icon" viewBox="0 0 24 24" aria-hidden="true">
          <rect x="5" y="3" width="14" height="10" rx="5" ry="5" fill="#FFFFFF"/>
          <path d="M8.5 6.4 h7 M8.5 9.4 h7" stroke="#0B1C38" stroke-width="1.5"/>
          <path d="M12 13 L12 17 M8 17 h8" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <span>Ask AURA</span>
      </button>
    </div>
    <div id="chat-view">
      <div id="chat-log">
        <div id="chat-empty">Your conversation with AURA will appear here in real time.</div>
      </div>
    </div>
  </div>
</div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
(function () {
  'use strict';
  var STATES = { IDLE: 1, LISTENING: 1, THINKING: 1, ANSWERING: 1, SPEAKING: 1 };
  var LABELS = { IDLE: 'Idle', LISTENING: 'Listening...', THINKING: 'Thinking...', ANSWERING: 'Answering...', SPEAKING: 'Answering...' };
  var SPEED = {
    IDLE:      { wave: '5.2s', pulse: '3.4s', breath: '5.0s', ring: '14s' },
    LISTENING: { wave: '1.8s', pulse: '1.6s', breath: '1.8s', ring: '6s' },
    THINKING:  { wave: '2.4s', pulse: '2.0s', breath: '2.8s', ring: '9s' },
    ANSWERING: { wave: '0.8s', pulse: '0.9s', breath: '1.2s', ring: '2.4s' }
  };
  var statusEl = document.getElementById('status-text');

  /* ---------------- state binding: window.updateState(state, text) ---------------- */
  function setState(state, text) {
    var s = String(state || 'IDLE').toUpperCase();
    if (s === 'SPEAKING') { s = 'ANSWERING'; }   /* alias the old state name */
    if (!STATES[s]) { s = 'IDLE'; }
    var label = (!text || !String(text).trim()) ? LABELS[s] : String(text);
    if (statusEl) { statusEl.textContent = label; }
    var speed = SPEED[s] || SPEED.IDLE;
    var root = document.documentElement.style;
    root.setProperty('--wave', speed.wave);
    root.setProperty('--pulse', speed.pulse);
    root.setProperty('--breath', speed.breath);
    root.setProperty('--ring', speed.ring);
    document.body.classList.toggle('busy', s === 'LISTENING' || s === 'ANSWERING');
    document.body.classList.toggle('idle-state', s === 'IDLE');
    document.body.classList.toggle('listening-state', s === 'LISTENING');
    document.body.classList.toggle('thinking-state', s === 'THINKING');
    document.body.classList.toggle('answering-state', s === 'ANSWERING');
  }
  window.updateState = setState;
  window.setAuraState = setState;
  if (window.pendingState) { setState(window.pendingState); }
  window.pendingState = null;

  /* ---------------- chat transcript: window.addMessage(role, text) ---------------- */
  var chatLog = document.getElementById('chat-log');
  var chatEmpty = document.getElementById('chat-empty');
  function chatVisible() {
    var v = document.getElementById('chat-view');
    return v && v.style.display !== 'none';
  }
  window.addMessage = function (role, text) {
    if (!chatLog) { return; }
    if (chatEmpty && chatEmpty.parentNode === chatLog) { chatLog.removeChild(chatEmpty); chatEmpty = null; }
    var isUser = String(role).toLowerCase() === 'user';
    var row = document.createElement('div');
    row.className = 'msg ' + (isUser ? 'user' : 'aura');
    var label = document.createElement('span');
    label.className = 'label';
    label.textContent = isUser ? 'User' : 'AURA';
    var body = document.createElement('span');
    body.className = 'body';
    body.textContent = String(text || '');
    row.appendChild(label);
    row.appendChild(body);
    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
    var badge = document.getElementById('tab-badge');
    if (badge) { badge.style.display = chatVisible() ? 'none' : 'block'; }
  };

  /* ---------------- Home / Chat tabs ---------------- */
  var tabs = { home: document.getElementById('tab-home'), chat: document.getElementById('tab-chat') };
  var views = { home: document.getElementById('home-view'), chat: document.getElementById('chat-view') };
  function activate(name) {
    var home = (name === 'home');
    if (views.home) { views.home.style.display = home ? 'flex' : 'none'; }
    if (views.chat) { views.chat.style.display = home ? 'none' : 'flex'; }
    if (tabs.home) { tabs.home.className = home ? 'active' : ''; }
    if (tabs.chat) { tabs.chat.className = home ? '' : 'active'; }
    if (!home) {
      var badge = document.getElementById('tab-badge');
      if (badge) { badge.style.display = 'none'; }
    }
  }
  if (tabs.home) { tabs.home.addEventListener('click', function () { activate('home'); }); }
  if (tabs.chat) { tabs.chat.addEventListener('click', function () { activate('chat'); }); }

  /* ---------------- bridge to Python (window.aura from QtWebChannel) ---------------- */
  function callAura(method) {
    try {
      if (window.aura && typeof window.aura[method] === 'function') { window.aura[method](); }
    } catch (err) { /* web channel not ready yet -- safe to ignore */ }
  }
  function bindClick(id, method) {
    var el = document.getElementById(id);
    if (el) { el.addEventListener('click', function () { callAura(method); }); }
  }
  bindClick('mic-button', 'micClicked');
  bindClick('btn-min', 'minimizeWindow');
  bindClick('btn-close', 'closeWindow');

  /* fallback window drag (used when -webkit-app-region is unavailable) */
  var drag = { on: false, x: 0, y: 0 };
  var header = document.getElementById('header');
  if (header) {
    header.addEventListener('mousedown', function (e) {
      if (e.button !== 0) { return; }
      drag.on = true; drag.x = e.screenX; drag.y = e.screenY;
    });
  }
  document.addEventListener('mouseup', function () { drag.on = false; });
  document.addEventListener('mousemove', function (e) {
    if (!drag.on) { return; }
    var dx = e.screenX - drag.x;
    var dy = e.screenY - drag.y;
    drag.x = e.screenX; drag.y = e.screenY;
    try {
      if (window.aura && typeof window.aura.dragMove === 'function') { window.aura.dragMove(dx, dy); }
    } catch (err) { /* ignore */ }
  });

  /* connect to the Python bridge once the web channel is up */
  if (typeof QWebChannel !== 'undefined' && window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, function (channel) {
      window.aura = channel.objects.aura;
    });
  }
})();
</script>
</body>
</html>"""
class VisualizerView(QWebEngineView):
    """The only visible surface; a right-click menu offers Minimize / Exit AURA."""

    def __init__(self, close_callback, parent=None) -> None:
        super().__init__(parent)
        self._close_callback = close_callback

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        minimize_action = menu.addAction("Minimize AURA")
        exit_action = menu.addAction("Exit AURA")
        chosen = menu.exec(event.globalPos())
        if chosen is minimize_action:
            self.showMinimized()
        elif chosen is exit_action:
            self._close_callback()


class Bridge(QObject):
    """Exposed to the web page as ``window.aura`` through a QtWebChannel."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self._window = window

    @Slot()
    def micClicked(self) -> None:
        self._window.trigger_listen()

    @Slot()
    def minimizeWindow(self) -> None:
        self._window.showMinimized()

    @Slot()
    def closeWindow(self) -> None:
        self._window.close()

    @Slot(float, float)
    def dragMove(self, dx: float, dy: float) -> None:
        position = self._window.pos()
        self._window.move(position.x() + int(round(dx)), position.y() + int(round(dy)))


class VoiceLoopWorker(QThread):
    state_changed = Signal(str)
    transcript_ready = Signal(str)
    response_ready = Signal(object)

    def __init__(self, assistant: Assistant) -> None:
        super().__init__()
        self.assistant = assistant

    def run(self) -> None:
        try:
            self.state_changed.emit("LISTENING")
            transcript = self.assistant.listen()
            self.transcript_ready.emit(transcript)
            self.state_changed.emit("THINKING")
            result = self.assistant.process(transcript)
            self.response_ready.emit(result)
            self.state_changed.emit("ANSWERING")
            self.assistant.speak(result.text)  # non-blocking background TTS
            self.assistant.wait_for_speech()   # pause STT until voice finishes
        except Exception:
            self.state_changed.emit("IDLE")


class MainWindow(QMainWindow):
    """Frameless Jarvis-style HUD with a neon orb, status line, and chat log."""

    def __init__(self, assistant: Assistant) -> None:
        super().__init__()
        self.assistant = assistant
        self.worker: VoiceLoopWorker | None = None
        self.voice_loop_enabled = False
        self._visualizer_ready = False
        self._pending_visualizer_state = "IDLE"
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("AURA")
        self.resize(520, 520)

        self.visualizer = VisualizerView(self.close, self)
        self.visualizer.setStyleSheet("background: transparent;")
        self.visualizer.page().setBackgroundColor(Qt.transparent)

        self.bridge = Bridge(self)
        channel = QWebChannel(self.visualizer.page())
        channel.registerObject("aura", self.bridge)
        self.visualizer.page().setWebChannel(channel)

        self.visualizer.loadFinished.connect(self._visualizer_loaded)
        self.visualizer.setHtml(VISUALIZER_HTML)
        self.setCentralWidget(self.visualizer)

        QShortcut(QKeySequence("Ctrl+Shift+Q"), self, self.stop_voice_loop)

    def start_voice_loop(self) -> None:
        self.voice_loop_enabled = True
        self._listen_next()

    def stop_voice_loop(self) -> None:
        self.voice_loop_enabled = False
        self.assistant.stop()
        self._set_visualizer_state("IDLE")

    def trigger_listen(self) -> None:
        """Invoked by the mic button; asks for a fresh listen right now."""
        self.voice_loop_enabled = True
        self._listen_next()

    def _listen_next(self) -> None:
        if not self.voice_loop_enabled or self.worker is not None:
            return
        worker = VoiceLoopWorker(self.assistant)
        worker.state_changed.connect(self._set_visualizer_state)
        worker.transcript_ready.connect(self._handle_transcript)
        worker.response_ready.connect(self._handle_response)
        worker.finished.connect(lambda: self._worker_finished(worker))
        self.worker = worker
        worker.start()

    def _handle_transcript(self, text: str) -> None:
        """Stream every STT recognition into the Chat transcript."""
        if self._visualizer_ready:
            self.visualizer.page().runJavaScript(f"window.addMessage('user', {json.dumps(text)});")

    def _handle_response(self, result: AssistantResponse) -> None:
        """Stream every LLM response into the Chat transcript."""
        if self._visualizer_ready:
            self.visualizer.page().runJavaScript(f"window.addMessage('aura', {json.dumps(result.text)});")

    def _worker_finished(self, worker: VoiceLoopWorker) -> None:
        if self.worker is worker:
            self.worker = None
        self._set_visualizer_state("IDLE")
        if self.voice_loop_enabled:
            QTimer.singleShot(150, self._listen_next)

    def _visualizer_loaded(self, success: bool) -> None:
        self._visualizer_ready = success
        if success:
            self._run_visualizer_state()

    def _set_visualizer_state(self, state: str) -> None:
        self._pending_visualizer_state = state.upper()
        if self._visualizer_ready:
            self._run_visualizer_state()

    def _run_visualizer_state(self) -> None:
        js = (
            f"if (typeof window.updateState === 'function') {{ window.updateState({json.dumps(self._pending_visualizer_state)}); }} "
            f"else {{ window.pendingState = {json.dumps(self._pending_visualizer_state)}; }}"
        )
        self.visualizer.page().runJavaScript(js)

    def closeEvent(self, event) -> None:
        self.stop_voice_loop()
        event.accept()
