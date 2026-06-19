"""
Engleesh — Personal dictionary / training app
with translation, transcription, TTS, self-check mode, and mistake tracking.
"""

import os
import platform
import sqlite3
import subprocess
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF
from PyQt6.QtGui import QFont, QPainter, QColor, QPainterPath
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTabWidget,
    QScrollArea, QFrame,
)

from deep_translator import GoogleTranslator
from gtts import gTTS

try:
    from eng_to_ipa import convert as ipa_convert
    HAS_IPA = True
except ImportError:
    HAS_IPA = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

DB_PATH = Path(__file__).parent / "dictionary.db"
IS_MACOS = platform.system() == "Darwin"

# ─── Database ────────────────────────────────────────────────────────────────

class Database:
    def __init__(self, path: Path = DB_PATH):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_en TEXT NOT NULL UNIQUE,
                word_ru TEXT NOT NULL,
                transcription TEXT DEFAULT '',
                is_mistake INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def add_word(self, word_en, word_ru, transcription=""):
        try:
            self.conn.execute(
                "INSERT INTO words (word_en, word_ru, transcription) VALUES (?, ?, ?)",
                (word_en.strip().lower(), word_ru.strip(), transcription),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_all_words(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT id, word_en, word_ru, transcription, is_mistake "
            "FROM words ORDER BY id DESC"
        ).fetchall()]

    def toggle_mistake(self, word_id, is_mistake):
        self.conn.execute("UPDATE words SET is_mistake=? WHERE id=?",
                          (1 if is_mistake else 0, word_id))
        self.conn.commit()

    def delete_word(self, word_id):
        self.conn.execute("DELETE FROM words WHERE id=?", (word_id,))
        self.conn.commit()

    def close(self):
        self.conn.close()


# ─── Translation & Transcription ────────────────────────────────────────────

def is_english(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if ord(c) < 128) / len(letters) > 0.8


def translate_text(text, src="en", dest="ru"):
    return GoogleTranslator(source=src, target=dest).translate(text)


def get_ipa_transcription(word):
    if HAS_IPA:
        try:
            result = ipa_convert(word)
            if result and "/" not in str(result):
                return f"/{result}/"
            return str(result) if result else ""
        except Exception:
            pass
    return ""


def get_transcription_from_api(word):
    if not HAS_REQUESTS:
        return ""
    try:
        resp = requests.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=5)
        if resp.status_code == 200:
            for entry in resp.json():
                for p in entry.get("phonetics", []):
                    if p.get("text"):
                        return p["text"]
    except Exception:
        pass
    return ""


def get_transcription(word):
    ipa = get_ipa_transcription(word)
    return ipa if ipa else get_transcription_from_api(word)


def detect_and_translate(word):
    word = word.strip()
    if not word:
        raise ValueError("Empty input")
    if is_english(word):
        w_en = word.lower()
        w_ru = translate_text(w_en, src="en", dest="ru")
        return w_en, w_ru, get_transcription(w_en)
    else:
        w_ru = word
        w_en = translate_text(w_ru, src="ru", dest="en").lower()
        return w_en, w_ru, get_transcription(w_en)


# ─── TTS ─────────────────────────────────────────────────────────────────────

def play_word(word_en):
    def _play():
        tmp = None
        try:
            tts = gTTS(text=word_en, lang="en")
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp = f.name
                tts.save(tmp)
            # macOS: afplay (built-in), Linux: ffplay/mpv
            if IS_MACOS:
                subprocess.run(["afplay", tmp],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"TTS error: {e}")
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
    threading.Thread(target=_play, daemon=True).start()


# ─── Lookup thread ──────────────────────────────────────────────────────────

class LookupThread(QThread):
    finished = pyqtSignal(str, str, str, str, bool)
    error = pyqtSignal(str)

    def __init__(self, raw, db):
        super().__init__()
        self.raw = raw
        self.db = db

    def run(self):
        try:
            w_en, w_ru, tr = detect_and_translate(self.raw)
            added = self.db.add_word(w_en, w_ru, tr)
            self.finished.emit(self.raw, w_en, w_ru, tr, added)
        except Exception as e:
            self.error.emit(str(e))


# ─── Clickable hidden label ─────────────────────────────────────────────────

class HiddenLabel(QLabel):
    def __init__(self, real_text, placeholder="[ … ]", parent=None):
        super().__init__(placeholder, parent)
        self._real = real_text
        self._placeholder = placeholder
        self._revealed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("color: #999; font-style: italic;")

    def mousePressEvent(self, event):
        self._revealed = not self._revealed
        self.setText(self._real if self._revealed else self._placeholder)
        if self._revealed:
            self.setStyleSheet("color: #333; font-style: normal;")
        else:
            self.setStyleSheet("color: #999; font-style: italic;")


class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, label="", parent=None):
        super().__init__(parent)
        self._checked = False
        self._label_text = label
        self.setFixedHeight(30)
        self.setFixedWidth(160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self):
        return self._checked

    def setChecked(self, val):
        if self._checked != val:
            self._checked = val
            self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.update()
        self.toggled.emit(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        track_w, track_h = 42, 22
        knob_r = 9
        track_y = (h - track_h) / 2
        track_x = 0

        if self._checked:
            p.setBrush(QColor("#4caf50"))
        else:
            p.setBrush(QColor("#ccc"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(track_x, track_y, track_w, track_h), track_h / 2, track_h / 2)

        knob_x = track_x + track_w - knob_r * 2 - 3 if self._checked else track_x + 3
        knob_y = h / 2
        p.setBrush(QColor("#fff"))
        p.drawEllipse(QRectF(knob_x, knob_y - knob_r, knob_r * 2, knob_r * 2))

        p.setPen(QColor("#555"))
        p.setFont(QFont("Helvetica Neue", 12))
        p.drawText(QRectF(track_w + 8, 0, w - track_w - 8, h), Qt.AlignmentFlag.AlignVCenter, self._label_text)
        p.end()


# ─── Word row ────────────────────────────────────────────────────────────────

class WordRow(QFrame):
    def __init__(self, word, hide_ru, hide_en, on_play, on_toggle, on_delete, parent=None):
        super().__init__(parent)
        self.word = word
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "WordRow { background: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; }"
            "WordRow:hover { background: #f0f4ff; border-color: #c0d0f0; }"
        )
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 4, 14, 4)
        layout.setSpacing(8)

        en = word["word_en"]
        tr = word["transcription"] or "—"
        ru = word["word_ru"]

        # English
        if hide_en:
            layout.addWidget(HiddenLabel(en))
        else:
            lbl = QLabel(en)
            lbl.setFont(QFont("Helvetica Neue", 14, QFont.Weight.DemiBold))
            lbl.setStyleSheet("color: #1a1a2e;")
            layout.addWidget(lbl)

        # Transcription
        if hide_en:
            layout.addWidget(HiddenLabel(tr))
        else:
            lbl = QLabel(tr)
            lbl.setFont(QFont("Helvetica Neue", 12))
            lbl.setStyleSheet("color: #888;")
            layout.addWidget(lbl)

        layout.addStretch(1)

        # Russian
        if hide_ru:
            layout.addWidget(HiddenLabel(ru))
        else:
            lbl = QLabel(ru)
            lbl.setFont(QFont("Helvetica Neue", 14))
            lbl.setStyleSheet("color: #333;")
            layout.addWidget(lbl)

        # Play button
        btn_play = QPushButton("🔊")
        btn_play.setFixedSize(34, 30)
        btn_play.setStyleSheet(
            "QPushButton { border: none; font-size: 16px; border-radius: 6px; }"
            "QPushButton:hover { background: #e8f0fe; }"
        )
        btn_play.clicked.connect(lambda: on_play(en))
        layout.addWidget(btn_play)

        # Star button
        star = "★" if word["is_mistake"] else "☆"
        color = "#e6a817" if word["is_mistake"] else "#bbb"
        btn_star = QPushButton(star)
        btn_star.setFixedSize(30, 30)
        btn_star.setStyleSheet(
            f"QPushButton {{ border: none; font-size: 18px; color: {color}; border-radius: 6px; }}"
            "QPushButton:hover { background: #fff3cd; }"
        )
        btn_star.clicked.connect(lambda: on_toggle(word["id"], word["is_mistake"]))
        layout.addWidget(btn_star)

        # Delete button
        btn_del = QPushButton("✕")
        btn_del.setFixedSize(28, 28)
        btn_del.setStyleSheet(
            "QPushButton { border: none; font-size: 14px; color: #bbb; border-radius: 6px; }"
            "QPushButton:hover { color: #e74c3c; background: #fdecea; }"
        )
        btn_del.clicked.connect(lambda: on_delete(word["id"]))
        layout.addWidget(btn_del)


# ─── Light theme stylesheet ─────────────────────────────────────────────────

LIGHT_STYLE = """
QMainWindow { background: #f5f6fa; }
QWidget { background: #f5f6fa; color: #333; }

QLineEdit {
    background: #ffffff; border: 2px solid #dde1e7; border-radius: 8px;
    padding: 8px 12px; font-size: 14px; color: #333;
}
QLineEdit:focus { border: 2px solid #3b82f6; }
QLineEdit::placeholder { color: #aaa; }

QPushButton#addBtn {
    background: #3b82f6; color: white; border: none; border-radius: 8px;
    padding: 8px 20px; font-size: 14px; font-weight: bold;
}
QPushButton#addBtn:hover { background: #2563eb; }
QPushButton#addBtn:disabled { background: #b0c4de; }

QTabWidget::pane { border: none; background: #f5f6fa; }
QTabBar::tab {
    background: #e8eaef; color: #666; padding: 10px 24px;
    border: none; border-bottom: 3px solid transparent;
    font-size: 13px; font-weight: bold; margin-right: 2px;
}
QTabBar::tab:selected {
    color: #3b82f6; border-bottom: 3px solid #3b82f6; background: #f5f6fa;
}
QTabBar::tab:hover { background: #dde1e7; }

QScrollArea { border: none; background: #f5f6fa; }
QScrollBar:vertical {
    background: #f5f6fa; width: 8px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #c0c4cc; border-radius: 4px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #a0a4ac; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""


# ─── Main window ────────────────────────────────────────────────────────────

class DictionaryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.hide_ru = False
        self.hide_en = False
        self._lookup_thread = None

        self.setWindowTitle("Engleesh — Personal Dictionary")
        self.setMinimumSize(820, 520)
        self.resize(900, 600)
        self.setStyleSheet(LIGHT_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Engleesh")
        title.setFont(QFont("Helvetica Neue", 26, QFont.Weight.Bold))
        title.setStyleSheet("color: #3b82f6;")
        hdr.addWidget(title)
        sub = QLabel("  Personal dictionary & trainer")
        sub.setStyleSheet("color: #888; font-size: 14px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignBottom)
        hdr.addWidget(sub)
        hdr.addStretch()
        root.addLayout(hdr)

        # Input row
        inp = QHBoxLayout()
        inp.setSpacing(8)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Type a word in English or Russian…")
        self.entry.returnPressed.connect(self._add_word)
        inp.addWidget(self.entry, 1)
        self.add_btn = QPushButton("Add")
        self.add_btn.setObjectName("addBtn")
        self.add_btn.setFixedWidth(90)
        self.add_btn.clicked.connect(self._add_word)
        inp.addWidget(self.add_btn)
        root.addLayout(inp)

        # Status
        self.status = QLabel("")
        self.status.setStyleSheet("color: #888; font-size: 12px;")
        root.addWidget(self.status)

        # Self-check mode bar
        mode_frame = QFrame()
        mode_frame.setStyleSheet(
            "QFrame { background: #e8eaef; border-radius: 8px; padding: 4px; }"
        )
        mode_layout = QHBoxLayout(mode_frame)
        mode_layout.setContentsMargins(12, 6, 12, 6)
        lbl = QLabel("Self-check:")
        lbl.setStyleSheet("color: #666; font-weight: bold; font-size: 12px;")
        mode_layout.addWidget(lbl)
        self._cb_hide_ru = ToggleSwitch("Скрыть перевод")
        self._cb_hide_ru.toggled.connect(self._on_toggle_ru)
        mode_layout.addWidget(self._cb_hide_ru)
        self._cb_hide_en = ToggleSwitch("Скрыть английский")
        self._cb_hide_en.toggled.connect(self._on_toggle_en)
        mode_layout.addWidget(self._cb_hide_en)
        mode_layout.addStretch()
        root.addWidget(mode_frame)

        # Tabs
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # Tab: All words
        self.tab_all_widget = QWidget()
        all_lay = QVBoxLayout(self.tab_all_widget)
        all_lay.setContentsMargins(0, 6, 0, 0)
        all_lay.setSpacing(0)
        self.tabs.addTab(self.tab_all_widget, "All words")

        self.word_scroll = QScrollArea()
        self.word_scroll.setWidgetResizable(True)
        self.word_scroll.setStyleSheet("QScrollArea { border: none; background: #f5f6fa; }")
        self.word_container = QWidget()
        self.word_container.setStyleSheet("background: #f5f6fa;")
        self.word_layout = QVBoxLayout(self.word_container)
        self.word_layout.setSpacing(6)
        self.word_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.word_scroll.setWidget(self.word_container)
        all_lay.addWidget(self.word_scroll)

        # Tab: Mistakes
        self.tab_mist_widget = QWidget()
        mist_lay = QVBoxLayout(self.tab_mist_widget)
        mist_lay.setContentsMargins(0, 6, 0, 0)
        mist_lay.setSpacing(0)
        self.tabs.addTab(self.tab_mist_widget, "Mistakes")

        self.mist_scroll = QScrollArea()
        self.mist_scroll.setWidgetResizable(True)
        self.mist_scroll.setStyleSheet("QScrollArea { border: none; background: #f5f6fa; }")
        self.mist_container = QWidget()
        self.mist_container.setStyleSheet("background: #f5f6fa;")
        self.mist_layout = QVBoxLayout(self.mist_container)
        self.mist_layout.setSpacing(6)
        self.mist_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.mist_scroll.setWidget(self.mist_container)
        mist_lay.addWidget(self.mist_scroll)

        self._load_words()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _on_toggle_ru(self, checked):
        self.hide_ru = checked
        self._load_words()

    def _on_toggle_en(self, checked):
        self.hide_en = checked
        self._load_words()

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    def _load_words(self):
        self._clear_layout(self.word_layout)
        self._clear_layout(self.mist_layout)

        words = self.db.get_all_words()
        if not words:
            lbl = QLabel("No words yet. Add your first word above!")
            lbl.setStyleSheet("color: #aaa; font-size: 14px; padding: 30px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.word_layout.addWidget(lbl)
            return

        for w in words:
            self.word_layout.addWidget(
                WordRow(w, self.hide_ru, self.hide_en, play_word, self._toggle_mistake, self._delete_word))
            if w["is_mistake"]:
                self.mist_layout.addWidget(
                    WordRow(w, self.hide_ru, self.hide_en, play_word, self._toggle_mistake, self._delete_word))

        if not any(w["is_mistake"] for w in words):
            lbl = QLabel("No mistakes yet. Mark words with ☆ to track them here.")
            lbl.setStyleSheet("color: #aaa; font-size: 14px; padding: 30px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mist_layout.addWidget(lbl)

    # ── Actions ──────────────────────────────────────────────────────────

    def _toggle_mistake(self, word_id, current):
        self.db.toggle_mistake(word_id, not current)
        self._load_words()

    def _delete_word(self, word_id):
        self.db.delete_word(word_id)
        self._load_words()
        self.status.setText("Word removed.")
        self.status.setStyleSheet("color: #888; font-size: 12px;")

    def _add_word(self):
        raw = self.entry.text().strip()
        if not raw:
            return
        self.status.setText("Looking up…")
        self.status.setStyleSheet("color: #888; font-size: 12px;")
        self.add_btn.setEnabled(False)

        self._lookup_thread = LookupThread(raw, self.db)
        self._lookup_thread.finished.connect(self._on_added)
        self._lookup_thread.error.connect(self._on_error)
        self._lookup_thread.start()

    def _on_added(self, raw, w_en, w_ru, tr, added):
        self.add_btn.setEnabled(True)
        if added:
            self.status.setText(f"Added: {w_en} — {w_ru}  {tr}")
            self.status.setStyleSheet("color: #27ae60; font-size: 12px;")
            self.entry.clear()
            self._load_words()
        else:
            self.status.setText(f"«{w_en}» already exists.")
            self.status.setStyleSheet("color: #e67e22; font-size: 12px;")

    def _on_error(self, msg):
        self.add_btn.setEnabled(True)
        self.status.setText(f"Error: {msg}")
        self.status.setStyleSheet("color: #e74c3c; font-size: 12px;")

    def closeEvent(self, event):
        self.db.close()
        event.accept()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    app.setFont(QFont("Helvetica Neue", 13))
    window = DictionaryApp()
    window.show()
    sys.exit(app.exec())
