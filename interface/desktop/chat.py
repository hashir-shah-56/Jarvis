"""JARVIS Stage 8.3B chat-only hybrid desktop page."""
from __future__ import annotations
from PySide6.QtCore import Qt, QObject, QThread, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QTextEdit, QPushButton, QFrame, QComboBox
from ai.models import AssistantText
from ai.hybrid_chat import HybridChat

class MessageInput(QTextEdit):
    submitted = Signal()
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            if not event.isAutoRepeat(): self.submitted.emit()
            event.accept();return
        super().keyPressEvent(event)

class ChatWorker(QObject):
    completed = Signal(str, str)
    def __init__(self, prompt, mode):
        super().__init__();self.prompt=prompt;self.mode=mode
    def run(self):
        try:
            result, provider, fallback = HybridChat().chat(self.prompt, self.mode)
            label = provider.upper() + (' / FALLBACK' if fallback else '')
            message = result.text if isinstance(result, AssistantText) else 'ERROR: '+result.error_id
            self.completed.emit(message, label)
        except Exception:
            self.completed.emit('ERROR: AI_PROVIDER_ERROR', 'UNKNOWN')

class ChatPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent);self._thread=None;self._worker=None;self._busy=False;self._closing=False
        root=QVBoxLayout(self);root.setContentsMargins(26,22,26,22);root.setSpacing(14)
        header=QHBoxLayout();title=QLabel('NEURAL COMMUNICATION // CHAT ONLY');title.setObjectName('section');header.addWidget(title);header.addStretch()
        self.mode=QComboBox();self.mode.addItem('OFFLINE / LOCAL', 'local');self.mode.addItem('GEMINI / CLOUD', 'gemini');self.mode.addItem('AUTO / FALLBACK', 'auto');self.mode.setToolTip('All modes are chat-only. No OS actions or memory writes.');header.addWidget(self.mode);root.addLayout(header)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.Shape.NoFrame);self.scroll.setStyleSheet('QScrollArea {background:#090506;border:1px solid #49201c;border-radius:8px;}')
        self.messages=QWidget();self.message_layout=QVBoxLayout(self.messages);self.message_layout.setContentsMargins(18,18,18,18);self.message_layout.setSpacing(12);self.message_layout.addStretch(1);self.scroll.setWidget(self.messages);root.addWidget(self.scroll,1)
        self.status=QLabel('READY  •  CHAT ONLY  •  NO TOOLS');self.status.setObjectName('muted');root.addWidget(self.status)
        row=QHBoxLayout();self.input=MessageInput();self.input.setPlaceholderText('Message Jarvis (Enter sends; Shift+Enter adds newline)');self.input.setFixedHeight(75);self.input.setAcceptRichText(False);self.input.submitted.connect(self.submit);row.addWidget(self.input,1)
        self.send_button=QPushButton('TRANSMIT');self.send_button.setObjectName('send');self.send_button.clicked.connect(self.submit);row.addWidget(self.send_button);root.addLayout(row)
        self.add_message('JARVIS','Chat-only hybrid mode is ready. Select LOCAL, GEMINI, or AUTO. No system actions can be executed.')

    def add_message(self, role, message):
        container=QWidget();row=QHBoxLayout(container);row.setContentsMargins(0,0,0,0)
        bubble=QFrame();bubble.setObjectName('chatBubble');bubble.setStyleSheet('QFrame#chatBubble {background:%s;border:1px solid %s;border-radius:9px;}' % (('#29100e','#8a352b') if role=='YOU' else ('#130b0b','#51241e')))
        col=QVBoxLayout(bubble);col.setContentsMargins(13,10,13,10)
        name=QLabel(role);name.setStyleSheet('color:#f0a34b;font-size:11px;font-weight:bold;background:transparent;')
        body=QLabel(message);body.setWordWrap(True);body.setTextFormat(Qt.TextFormat.PlainText);body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);body.setStyleSheet('color:#e7c5ba;background:transparent;')
        col.addWidget(name);col.addWidget(body);bubble.setMaximumWidth(700)
        if role=='YOU':row.addStretch(1);row.addWidget(bubble)
        else:row.addWidget(bubble);row.addStretch(1)
        self.message_layout.insertWidget(self.message_layout.count()-1,container)
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def submit(self):
        if self._busy or self._closing:return
        prompt=self.input.toPlainText().strip()
        if not prompt:return
        if len(prompt)>4096:self.status.setText('INPUT LIMIT: 4096 CHARACTERS');return
        self.input.clear();self.add_message('YOU',prompt);self._busy=True;self.input.setEnabled(False);self.send_button.setEnabled(False);self.mode.setEnabled(False)
        selected=self.mode.currentData();self.status.setText('PROCESSING  •  '+selected.upper())
        self._thread=QThread(self);self._worker=ChatWorker(prompt,selected);self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run);self._worker.completed.connect(self._on_reply);self._worker.completed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater);self._thread.finished.connect(self._thread.deleteLater);self._thread.finished.connect(self._on_finished);self._thread.start()

    def _on_reply(self, text, provider):
        if not self._closing:self.add_message('JARVIS ['+provider+']',text);self.status.setText('READY  •  '+provider+'  •  CHAT ONLY')

    def _on_finished(self):
        self._thread=None;self._worker=None;self._busy=False
        if not self._closing:self.input.setEnabled(True);self.send_button.setEnabled(True);self.mode.setEnabled(True);self.input.setFocus()

    def shutdown(self):
        self._closing=True
        if self._thread is not None and self._thread.isRunning():
            # Do not destroy a running QThread. Wait for the bounded network timeout.
            self._thread.quit();self._thread.wait()
