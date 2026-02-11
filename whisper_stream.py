#!/usr/bin/env python3
"""Gramps Captions using whisper.cpp streaming"""
import sys
import os
import subprocess
import threading
import re
import time
from datetime import datetime

from PyQt6.QtWidgets import (QApplication, QMainWindow, QTextEdit, QLabel,
    QVBoxLayout, QHBoxLayout, QWidget, QScroller, QStackedWidget)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QFont, QFontDatabase, QTextCursor, QPainter, QColor, QLinearGradient, QPen

WHISPER_BIN = os.path.expanduser('~/whisper.cpp/build/bin/whisper-stream')
WHISPER_MODEL = os.path.expanduser('~/whisper.cpp/models/ggml-base.en-q5_0.bin')
FONT_PATH = os.path.expanduser('~/gramps-transcriber/fonts/DSEG14Classic-Bold.ttf')
PHONE_MUTED_FILE = '/tmp/phone_muted'
SILENCE_TIMEOUT = 90

# Ensure mic is at 100%
subprocess.run(['amixer', '-c', '1', 'set', 'Mic', '100%'], capture_output=True)
print('Mic set to 100%', flush=True)


class Emitter(QObject):
    new_text = pyqtSignal(str)
    status_changed = pyqtSignal(str)

emitter = Emitter()


def whisper_thread():
    """Run whisper-stream and emit transcriptions"""
    print('Starting whisper.cpp stream...', flush=True)
    emitter.status_changed.emit('whisper')

    cmd = [
        WHISPER_BIN,
        '-m', WHISPER_MODEL,
        '-c', '0',  # TONOR mic (device 0)
        '--step', '3000',
        '--length', '5000',
        '-l', 'en',
    ]

    env = os.environ.copy()
    env['TERM'] = 'dumb'  # Disable ANSI codes

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )

    print('whisper-stream process started', flush=True)

    for line in iter(proc.stdout.readline, ''):
        # Remove ANSI escape codes
        line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line)
        line = re.sub(r'\[2K', '', line)
        line = line.strip()

        # Skip empty lines, metadata, and noise
        if not line:
            continue
        if line.startswith('[') or line.startswith('init:') or line.startswith('whisper'):
            continue
        if line.startswith('main:'):
            continue
        if 'BLANK_AUDIO' in line or 'INAUDIBLE' in line:
            continue

        # This should be actual transcription
        print(f'>>> {line}', flush=True)
        emitter.new_text.emit(line)

    print('whisper-stream process ended', flush=True)


class FlipFlap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(420, 450)
        self._text = '00'
        self._dimmed = False
        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id >= 0:
            self._font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
        else:
            self._font_family = 'Arial Narrow'

    def set_text(self, text):
        if text != self._text:
            self._text = text
            self.update()

    def set_dimmed(self, dimmed):
        self._dimmed = dimmed
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        gap = 8
        flap_h = (h - gap) // 2
        r = 15
        text_col = QColor('#555') if self._dimmed else QColor('#f0f0f0')
        painter.setPen(QPen(QColor('#444'), 2))
        top_g = QLinearGradient(0, 0, 0, flap_h)
        top_g.setColorAt(0, QColor('#3d3d3d'))
        top_g.setColorAt(0.9, QColor('#2a2a2a'))
        top_g.setColorAt(1, QColor('#222'))
        painter.setBrush(top_g)
        painter.drawRoundedRect(0, 0, w, flap_h, r, r)
        bot_g = QLinearGradient(0, flap_h + gap, 0, h)
        bot_g.setColorAt(0, QColor('#1a1a1a'))
        bot_g.setColorAt(0.1, QColor('#252525'))
        bot_g.setColorAt(1, QColor('#333'))
        painter.setBrush(bot_g)
        painter.drawRoundedRect(0, flap_h + gap, w, flap_h, r, r)
        font = QFont(self._font_family, 280, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(text_col)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(self._text)
        tx = (w - tw) // 2
        cap_h = fm.capHeight()
        ty = (h // 2) + (cap_h // 2)
        painter.setClipRect(0, 0, w, flap_h)
        painter.drawText(tx, ty, self._text)
        painter.setClipRect(0, flap_h + gap, w, flap_h)
        painter.drawText(tx, ty, self._text)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 2))
        painter.drawLine(r, 2, w - r, 2)


class ClockView(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet('background: black;')
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setSpacing(30)
        self.hours = FlipFlap()
        self.mins = FlipFlap()
        row_layout.addWidget(self.hours)
        row_layout.addWidget(self.mins)
        layout.addWidget(row)
        self.dimmed = False

    def update_time(self):
        now = datetime.now()
        self.hours.set_text(now.strftime('%H'))
        self.mins.set_text(now.strftime('%M'))
        h = now.hour
        night = h >= 22 or h < 7
        if night != self.dimmed:
            self.dimmed = night
            self.hours.set_dimmed(night)
            self.mins.set_dimmed(night)


class CaptionView(QWidget):
    def __init__(self):
        super().__init__()
        self.font_sizes = {'S': 28, 'M': 36, 'L': 48}
        self.current_size = 'M'
        self.color_schemes = [
            ('W/B', '#ffffff', '#000000'),
            ('B/W', '#000000', '#ffffff'),
            ('Y/B', '#ffff00', '#000000'),
            ('G/B', '#00ff00', '#000000'),
        ]
        self.current_scheme = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 15, 25, 15)
        top_bar = QHBoxLayout()

        self.size_buttons = {}
        for size in ['S', 'M', 'L']:
            btn = QLabel(size)
            btn.setFixedSize(50, 50)
            btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn.mousePressEvent = lambda e, s=size: self.set_size(s)
            self.size_buttons[size] = btn
            top_bar.addWidget(btn)

        spacer = QLabel('  ')
        spacer.setFixedWidth(30)
        top_bar.addWidget(spacer)

        self.color_buttons = []
        for i, (name, text_col, bg_col) in enumerate(self.color_schemes):
            btn = QLabel('A')
            btn.setFixedSize(50, 50)
            btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn.setStyleSheet(f'background: {bg_col}; color: {text_col}; border-radius: 25px; font-size: 24px; font-weight: bold; border: 2px solid #444;')
            btn.mousePressEvent = lambda e, idx=i: self.set_color(idx)
            self.color_buttons.append(btn)
            top_bar.addWidget(btn)

        top_bar.addStretch()

        self.phone_icon = QLabel('📞')
        self.phone_icon.setStyleSheet('color: #00ff00; background: transparent; font-size: 40px;')
        self.phone_icon.hide()
        top_bar.addWidget(self.phone_icon)

        self.status_label = QLabel('')
        top_bar.addWidget(self.status_label)

        layout.addLayout(top_bar)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.text.setStyleSheet('background: black; color: white; border: none;')
        self.text.verticalScrollBar().setStyleSheet(
            'QScrollBar:vertical { background: #222; width: 30px; border-radius: 15px; }'
            'QScrollBar::handle:vertical { background: #666; min-height: 60px; border-radius: 15px; }'
            'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }'
        )
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        QScroller.grabGesture(self.text.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        layout.addWidget(self.text)

        self.update_size_buttons()
        self.update_color_buttons()
        self.set_size('M')
        self.set_color(0)

    def set_size(self, size):
        self.current_size = size
        self.text.setFont(QFont('Helvetica', self.font_sizes[size], QFont.Weight.Bold))
        self.update_size_buttons()

    def set_color(self, idx):
        self.current_scheme = idx
        name, text_col, bg_col = self.color_schemes[idx]
        self.text.setStyleSheet(f'background: {bg_col}; color: {text_col}; border: none;')
        self.setStyleSheet(f'background: {bg_col};')
        self.update_color_buttons()

    def update_size_buttons(self):
        for size, btn in self.size_buttons.items():
            if size == self.current_size:
                btn.setStyleSheet('background: #444; color: white; border-radius: 25px; font-size: 24px; font-weight: bold;')
            else:
                btn.setStyleSheet('background: #222; color: #888; border-radius: 25px; font-size: 24px;')

    def update_color_buttons(self):
        for i, btn in enumerate(self.color_buttons):
            name, text_col, bg_col = self.color_schemes[i]
            if i == self.current_scheme:
                btn.setStyleSheet(f'background: {bg_col}; color: {text_col}; border-radius: 25px; font-size: 24px; font-weight: bold; border: 3px solid #0af;')
            else:
                btn.setStyleSheet(f'background: {bg_col}; color: {text_col}; border-radius: 25px; font-size: 24px; font-weight: bold; border: 2px solid #444;')

    def set_status(self, mode):
        if mode == 'whisper':
            self.status_label.setText('🎤 WHISPER')
            self.status_label.setStyleSheet('color: #00ffaa; background: #003322; padding: 8px 15px; border-radius: 10px; font-size: 22px; font-weight: bold;')

    def add_text(self, t):
        c = self.text.textCursor()
        c.movePosition(QTextCursor.MoveOperation.End)
        if self.text.toPlainText():
            c.insertText(' ')
        c.insertText(t)
        self.text.setTextCursor(c)
        self.text.ensureCursorVisible()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Gramps')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.showFullScreen()

        self.stack = QStackedWidget()
        self.stack.setStyleSheet('background: black; border: none;')
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet('background: black; border: none;')
        self.setCentralWidget(self.stack)

        self.clock_view = ClockView()
        self.caption_view = CaptionView()

        self.stack.addWidget(self.clock_view)
        self.stack.addWidget(self.caption_view)

        self.last_activity = 0

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

        self.mute_timer = QTimer()
        self.mute_timer.timeout.connect(self.check_muted)
        self.mute_timer.start(500)

        emitter.new_text.connect(self.on_text)
        emitter.status_changed.connect(self.on_status_changed)

        self.stack.setCurrentIndex(0)

    def signal_activity(self):
        self.last_activity = time.time()
        if self.stack.currentIndex() != 1:
            self.stack.setCurrentIndex(1)

    def tick(self):
        self.clock_view.update_time()
        if self.last_activity > 0:
            age = time.time() - self.last_activity
            if age > SILENCE_TIMEOUT and self.stack.currentIndex() == 1:
                self.stack.setCurrentIndex(0)

    def check_muted(self):
        try:
            if os.path.exists(PHONE_MUTED_FILE):
                with open(PHONE_MUTED_FILE, 'r') as f:
                    if f.read().strip() == '1':
                        self.caption_view.phone_icon.show()
                    else:
                        self.caption_view.phone_icon.hide()
            else:
                self.caption_view.phone_icon.hide()
        except:
            pass

    def on_text(self, t):
        self.signal_activity()
        self.caption_view.add_text(t)

    def on_status_changed(self, mode):
        self.caption_view.set_status(mode)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            QApplication.quit()


def main():
    print('Starting Gramps Captions (whisper.cpp)...', flush=True)
    try:
        import systemd.daemon
        systemd.daemon.notify('READY=1')
    except:
        pass

    threading.Thread(target=whisper_thread, daemon=True).start()

    def wd():
        try:
            import systemd.daemon
            while True:
                time.sleep(10)
                systemd.daemon.notify('WATCHDOG=1')
        except:
            pass
    threading.Thread(target=wd, daemon=True).start()

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
