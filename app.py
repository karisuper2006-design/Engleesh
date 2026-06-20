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

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF, QSize
from PyQt6.QtGui import QFont, QPainter, QColor, QPainterPath, QPixmap, QIcon, QPen
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
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS word_folders (
                word_id INTEGER NOT NULL,
                folder_id INTEGER NOT NULL,
                PRIMARY KEY (word_id, folder_id),
                FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE,
                FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE
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

    def create_folder(self, name):
        self.conn.execute("INSERT INTO folders (name) VALUES (?)", (name.strip(),))
        self.conn.commit()
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def get_folders(self):
        return [dict(r) for r in self.conn.execute("SELECT id, name FROM folders ORDER BY id DESC").fetchall()]

    def add_words_to_folder(self, folder_id, word_ids):
        for wid in word_ids:
            try:
                self.conn.execute("INSERT OR IGNORE INTO word_folders (word_id, folder_id) VALUES (?, ?)", (wid, folder_id))
            except Exception:
                pass
        self.conn.commit()

    def get_folder_words(self, folder_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT w.id, w.word_en, w.word_ru, w.transcription, w.is_mistake "
            "FROM words w JOIN word_folders wf ON w.id = wf.word_id "
            "WHERE wf.folder_id = ? ORDER BY w.id DESC", (folder_id,)
        ).fetchall()]

    def get_folder_word_count(self, folder_id):
        return self.conn.execute("SELECT COUNT(*) FROM word_folders WHERE folder_id=?", (folder_id,)).fetchone()[0]

    def remove_word_from_folder(self, folder_id, word_id):
        self.conn.execute("DELETE FROM word_folders WHERE folder_id=? AND word_id=?", (folder_id, word_id))
        self.conn.commit()

    def delete_folder(self, folder_id):
        self.conn.execute("DELETE FROM word_folders WHERE folder_id=?", (folder_id,))
        self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self.conn.commit()

    def update_word(self, word_id, word_en, word_ru, transcription):
        self.conn.execute(
            "UPDATE words SET word_en=?, word_ru=?, transcription=? WHERE id=?",
            (word_en.strip().lower(), word_ru.strip(), transcription, word_id))
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


def _make_play_icon(size=18):
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#555"))
    path = QPainterPath()
    path.moveTo(3, 2)
    path.lineTo(3, size - 2)
    path.lineTo(8, size - 4)
    path.lineTo(8, 4)
    path.closeSubpath()
    p.drawPath(path)
    for r, cx in [(3, 11), (4, 14)]:
        p.drawEllipse(QRectF(cx, size / 2 - r, r * 2, r * 2))
    p.end()
    return QIcon(px)


def _make_del_icon(size=22):
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#fff"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = 4
    p.drawLine(m + 2, m, size - m - 2, m)
    p.drawLine(m + 5, m + 2, m + 4, size - m)
    p.drawLine(size - m - 5, m + 2, size - m - 4, size - m)
    p.drawLine(m + 1, m + 2, size - m - 1, m + 2)
    cx = size / 2
    p.drawLine(cx, m + 5, cx, size - m - 2)
    p.end()
    return QIcon(px)


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
    selection_toggled = pyqtSignal(int)

    def __init__(self, word, hide_ru, hide_en, on_play, on_toggle, on_delete, on_edit, parent=None):
        super().__init__(parent)
        self.word = word
        self.on_edit = on_edit
        self.on_delete = on_delete
        self._selected = False
        self._swiped = False
        self._drag_start_x = 0
        self._dragging = False
        self._selectable = False
        self._checked = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._update_style()
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        self._content = QFrame(self)
        self._content.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self._content)
        layout.setContentsMargins(14, 4, 14, 4)
        layout.setSpacing(8)

        self._check_btn = None

        en = word["word_en"]
        tr = word["transcription"] or "—"
        ru = word["word_ru"]

        if hide_en:
            self._en_label = HiddenLabel(en)
        else:
            self._en_label = QLabel(en)
            self._en_label.setFont(QFont("Helvetica Neue", 14, QFont.Weight.DemiBold))
            self._en_label.setStyleSheet("color: #1a1a2e;")
        layout.addWidget(self._en_label)

        if hide_en:
            self._tr_label = HiddenLabel(tr)
        else:
            self._tr_label = QLabel(tr)
            self._tr_label.setFont(QFont("Helvetica Neue", 12))
            self._tr_label.setStyleSheet("color: #888;")
        layout.addWidget(self._tr_label)

        layout.addStretch(1)

        if hide_ru:
            self._ru_label = HiddenLabel(ru)
        else:
            self._ru_label = QLabel(ru)
            self._ru_label.setFont(QFont("Helvetica Neue", 14))
            self._ru_label.setStyleSheet("color: #333;")
        layout.addWidget(self._ru_label)

        btn_play = QPushButton()
        btn_play.setIcon(_make_play_icon())
        btn_play.setFixedSize(28, 28)
        btn_play.setIconSize(QSize(18, 18))
        btn_play.setStyleSheet(
            "QPushButton { border: none; border-radius: 6px; color: #999; }"
            "QPushButton:hover { background: #e8f0fe; }")
        btn_play.clicked.connect(lambda: on_play(en))
        layout.addWidget(btn_play)

        star = "★" if word["is_mistake"] else "☆"
        color = "#e6a817" if word["is_mistake"] else "#999"
        btn_star = QPushButton(star)
        btn_star.setFixedSize(28, 28)
        btn_star.setStyleSheet(
            f"QPushButton {{ border: none; font-size: 16px; color: {color}; border-radius: 6px; }}"
            "QPushButton:hover { background: #fff3cd; }")
        btn_star.clicked.connect(lambda: on_toggle(word["id"], word["is_mistake"]))
        layout.addWidget(btn_star)

        self._btn_del = QPushButton()
        self._btn_del.setIcon(_make_del_icon())
        self._btn_del.setFixedSize(50, 36)
        self._btn_del.setIconSize(self._btn_del.size() - QSize(4, 4))
        self._btn_del.setStyleSheet(
            "QPushButton { background: #e74c3c; border: none; border-radius: 18px; }"
            "QPushButton:hover { background: #c0392b; }")
        self._btn_del.clicked.connect(lambda: on_delete(word["id"]))
        self._btn_del.setParent(self)
        self._btn_del.hide()

        self._content.installEventFilter(self)

    def set_selectable(self, selectable, checked=False):
        self._selectable = selectable
        self._checked = checked
        layout = self._content.layout()
        if selectable:
            if self._check_btn is None:
                self._check_btn = QPushButton()
                self._check_btn.setFixedSize(22, 22)
                self._check_btn.setStyleSheet(self._check_style())
                self._check_btn.clicked.connect(lambda: self.selection_toggled.emit(self.word["id"]))
                layout.insertWidget(0, self._check_btn)
            self._check_btn.setStyleSheet(self._check_style())
        elif self._check_btn is not None:
            layout.removeWidget(self._check_btn)
            self._check_btn.deleteLater()
            self._check_btn = None

    def _check_style(self):
        if self._checked:
            return ("QPushButton { background: #3b82f6; border: none; border-radius: 11px; }"
                    "QPushButton:hover { background: #2563eb; }")
        return ("QPushButton { background: #fff; border: 2px solid #ccc; border-radius: 11px; }"
                "QPushButton:hover { border-color: #3b82f6; }")

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(
                "WordRow { background: #f0f7ff; border: 2px solid #3b82f6; border-radius: 8px; }")
        else:
            self.setStyleSheet(
                "WordRow { background: #ffffff; border: 2px solid transparent; border-radius: 8px; }"
                "WordRow:hover { background: #f0f4ff; border-color: #c0d0f0; }")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        h = self.height()
        self._btn_del.setFixedSize(50, h - 10)
        self._btn_del.move(self.width() - 60, 5)
        self._content.setGeometry(0, 0, self.width(), h)

    def eventFilter(self, obj, event):
        if obj == self._content:
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self._selectable:
                    self.selection_toggled.emit(self.word["id"])
                    return True
                self._drag_start_x = event.position().x()
                self._dragging = True
                return False
            elif event.type() == event.Type.MouseMove and self._dragging:
                dx = event.position().x() - self._drag_start_x
                if self._swiped:
                    new_x = -80 + dx
                else:
                    new_x = min(0, dx)
                new_x = max(-80, min(0, new_x))
                self._content.move(new_x, 0)
                return True
            elif event.type() == event.Type.MouseButtonRelease and self._dragging:
                self._dragging = False
                dx = event.position().x() - self._drag_start_x
                if self._swiped:
                    final = -80 if dx < 40 else 0
                else:
                    final = -80 if dx < -40 else 0
                self._swiped = (final == -80)
                self._animate_slide(final)
                if not self._swiped:
                    self._check_click(event.position())
                if self._swiped:
                    self._btn_del.show()
                    self._btn_del.raise_()
                return True
            elif event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
                return False
        return super().eventFilter(obj, event)

    def _animate_slide(self, target_x):
        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        anim = QPropertyAnimation(self._content, b"pos")
        anim.setDuration(200)
        anim.setStartValue(self._content.pos())
        from PyQt6.QtCore import QPoint
        anim.setEndValue(QPoint(target_x, 0))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._slide_anim = anim
        if target_x == 0:
            self._btn_del.hide()

    def _check_click(self, pos):
        if self._selected:
            en_pos = self._en_label.mapFrom(self._content, pos.toPoint())
            if not isinstance(self._en_label, HiddenLabel) and self._en_label.geometry().contains(en_pos):
                self._start_edit(self._en_label, "en")
                return
            ru_pos = self._ru_label.mapFrom(self._content, pos.toPoint())
            if not isinstance(self._ru_label, HiddenLabel) and self._ru_label.geometry().contains(ru_pos):
                self._start_edit(self._ru_label, "ru")
                return
        self._selected = not self._selected
        self._update_style()

    def mousePressEvent(self, event):
        if self._swiped and event.button() == Qt.MouseButton.LeftButton:
            return
        super().mousePressEvent(event)

    def _start_edit(self, label, field):
        edit = QLineEdit(label.text())
        edit.setFont(label.font())
        edit.setStyleSheet(
            "QLineEdit { border: 2px solid #3b82f6; border-radius: 4px; padding: 2px 6px; "
            "background: #fff; color: #1a1a2e; }")
        edit.setMinimumWidth(label.width())
        edit.editingFinished.connect(lambda: self._finish_edit(edit, label, field))
        edit.returnPressed.connect(lambda: edit.clearFocus())
        lay = self._content.layout()
        idx = lay.indexOf(label)
        lay.removeWidget(label)
        label.hide()
        lay.insertWidget(idx, edit)
        edit.setFocus()
        edit.selectAll()

    def _finish_edit(self, edit, label, field):
        new_val = edit.text().strip()
        if not new_val:
            edit.setText(label.text())
            return
        old_val = self.word[f"word_{field}"]
        if new_val != old_val:
            self.word[f"word_{field}"] = new_val.lower() if field == "en" else new_val
            if field == "en":
                self.word["transcription"] = get_transcription(new_val.lower()) or self.word.get("transcription", "")
            self.on_edit(self.word)
        lay = self._content.layout()
        idx = lay.indexOf(edit)
        lay.removeWidget(edit)
        edit.deleteLater()
        if field == "en":
            label.setText(self.word["word_en"])
            if not isinstance(self._tr_label, HiddenLabel):
                self._tr_label.setText(self.word.get("transcription", "—") or "—")
        else:
            label.setText(self.word["word_ru"])
        lay.insertWidget(idx, label)
        label.show()


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
        self.select_mode = False
        self.selected_word_ids = set()
        self.current_folder_id = None

        self.setWindowTitle("Engleesh")
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
        hdr.addStretch()
        root.addLayout(hdr)

        # Input row
        inp = QHBoxLayout()
        inp.setSpacing(8)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText("Введите слово на английском или русском…")
        self.entry.returnPressed.connect(self._add_word)
        inp.addWidget(self.entry, 1)
        self.add_btn = QPushButton("Добавить")
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
        self._cb_hide_ru = ToggleSwitch("Скрыть перевод")
        self._cb_hide_ru.toggled.connect(self._on_toggle_ru)
        mode_layout.addWidget(self._cb_hide_ru)
        mode_layout.addStretch()
        self._cb_hide_en = ToggleSwitch("Скрыть английский")
        self._cb_hide_en.toggled.connect(self._on_toggle_en)
        mode_layout.addWidget(self._cb_hide_en)
        mode_layout.addStretch()
        root.addWidget(mode_frame)

        # Toolbar
        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(8)
        self.btn_menu = QPushButton("☰")
        self.btn_menu.setFixedSize(32, 32)
        self.btn_menu.setStyleSheet(
            "QPushButton { background: #e8eaef; border: none; border-radius: 8px; font-size: 16px; color: #555; }"
            "QPushButton:hover { background: #dde1e7; }")
        self.btn_menu.clicked.connect(self._show_menu)
        self.toolbar.addWidget(self.btn_menu)
        self.btn_select = QPushButton("Выбрать")
        self.btn_select.setFixedHeight(32)
        self.btn_select.setStyleSheet(
            "QPushButton { background: #3b82f6; color: white; border: none; border-radius: 8px; "
            "padding: 0 14px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background: #2563eb; }")
        self.btn_select.clicked.connect(self._toggle_select_mode)
        self.toolbar.addWidget(self.btn_select)
        self.toolbar.addStretch()
        root.addLayout(self.toolbar)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        # Tab: All words
        self.tab_all_widget = QWidget()
        all_lay = QVBoxLayout(self.tab_all_widget)
        all_lay.setContentsMargins(0, 6, 0, 0)
        all_lay.setSpacing(0)
        self.tabs.addTab(self.tab_all_widget, "Все слова")

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
        self.tabs.addTab(self.tab_mist_widget, "Ошибки")

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

        # Tab: Folders
        self.tab_folders_widget = QWidget()
        folders_lay = QVBoxLayout(self.tab_folders_widget)
        folders_lay.setContentsMargins(0, 6, 0, 0)
        folders_lay.setSpacing(0)
        self.tabs.addTab(self.tab_folders_widget, "Папки")

        self.folders_scroll = QScrollArea()
        self.folders_scroll.setWidgetResizable(True)
        self.folders_scroll.setStyleSheet("QScrollArea { border: none; background: #f5f6fa; }")
        self.folders_container = QWidget()
        self.folders_container.setStyleSheet("background: #f5f6fa;")
        self.folders_layout = QVBoxLayout(self.folders_container)
        self.folders_layout.setSpacing(6)
        self.folders_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.folders_scroll.setWidget(self.folders_container)
        folders_lay.addWidget(self.folders_scroll)

        # Folder view (hidden by default, shown when inside a folder)
        self.folder_view_widget = QWidget()
        folder_view_lay = QVBoxLayout(self.folder_view_widget)
        folder_view_lay.setContentsMargins(0, 6, 0, 0)
        folder_view_lay.setSpacing(0)
        self.folder_view_scroll = QScrollArea()
        self.folder_view_scroll.setWidgetResizable(True)
        self.folder_view_scroll.setStyleSheet("QScrollArea { border: none; background: #f5f6fa; }")
        self.folder_view_container = QWidget()
        self.folder_view_container.setStyleSheet("background: #f5f6fa;")
        self.folder_view_layout = QVBoxLayout(self.folder_view_container)
        self.folder_view_layout.setSpacing(6)
        self.folder_view_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.folder_view_scroll.setWidget(self.folder_view_container)
        folder_view_lay.addWidget(self.folder_view_scroll)

        self._load_words()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _on_toggle_ru(self, checked):
        self.hide_ru = checked
        self._load_words()

    def _on_toggle_en(self, checked):
        self.hide_en = checked
        self._load_words()

    def _on_tab_changed(self, index):
        if index == 2:
            self.toolbar.setVisible(False)
            self.current_folder_id = None
            self._load_folders()
        else:
            self.toolbar.setVisible(True)
            self.current_folder_id = None
            if self.select_mode:
                self._exit_select_mode()

    def mousePressEvent(self, event):
        child = self.childAt(event.pos())
        while child:
            if isinstance(child, WordRow):
                return super().mousePressEvent(event)
            child = child.parent()
        for layout in [self.word_layout, self.mist_layout, self.folder_view_layout]:
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if isinstance(w, WordRow) and w._selected:
                    w._selected = False
                    w._update_style()
        super().mousePressEvent(event)

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    # ── Select mode ─────────────────────────────────────────────────────

    def _toggle_select_mode(self):
        if self.select_mode:
            self._exit_select_mode()
        else:
            self.select_mode = True
            self.selected_word_ids.clear()
            self.btn_select.setText("Отмена")
            self.btn_select.setStyleSheet(
                "QPushButton { background: #2563eb; color: white; border: none; border-radius: 18px; "
                "padding: 0 20px; font-size: 13px; font-weight: bold; }")
            self._load_words()

    def _exit_select_mode(self):
        self.select_mode = False
        self.selected_word_ids.clear()
        self.btn_select.setText("Выбрать")
        self.btn_select.setStyleSheet(
            "QPushButton { background: #3b82f6; color: white; border: none; border-radius: 18px; "
            "padding: 0 20px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background: #2563eb; }")
        self._load_words()

    def _toggle_word_selection(self, word_id):
        if word_id in self.selected_word_ids:
            self.selected_word_ids.discard(word_id)
        else:
            self.selected_word_ids.add(word_id)
        self._load_words()

    # ── Menu ────────────────────────────────────────────────────────────

    def _show_menu(self):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        create_act = menu.addAction("Создать папку")
        add_act = menu.addAction("Добавить в папку")
        action = menu.exec(self.btn_menu.mapToGlobal(self.btn_menu.rect().bottomLeft()))
        if action == create_act:
            self._create_folder()
        elif action == add_act:
            self._add_to_folder()

    def _create_folder(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Создать папку", "Название папки:")
        if not ok or not name.strip():
            return
        folder_id = self.db.create_folder(name.strip())
        if self.selected_word_ids:
            self.db.add_words_to_folder(folder_id, list(self.selected_word_ids))
        self._exit_select_mode()
        self.status.setText(f"Папка «{name.strip()}» создана.")
        self.status.setStyleSheet("color: #27ae60; font-size: 12px;")
        self.tabs.setCurrentIndex(2)

    def _add_to_folder(self):
        if not self.selected_word_ids:
            self.status.setText("Сначала выберите слова.")
            self.status.setStyleSheet("color: #e67e22; font-size: 12px;")
            return
        folders = self.db.get_folders()
        if not folders:
            self.status.setText("Сначала создайте папку.")
            self.status.setStyleSheet("color: #e67e22; font-size: 12px;")
            return
        count = len(self.selected_word_ids)
        from PyQt6.QtWidgets import QInputDialog
        names = [f["name"] for f in folders]
        name, ok = QInputDialog.getItem(self, "Добавить в папку", "Выберите папку:", names, 0, False)
        if not ok:
            return
        folder = next(f for f in folders if f["name"] == name)
        self.db.add_words_to_folder(folder["id"], list(self.selected_word_ids))
        self._exit_select_mode()
        self.status.setText(f"{count} слов(о) добавлено в «{name}».")
        self.status.setStyleSheet("color: #27ae60; font-size: 12px;")

    # ── Folders ─────────────────────────────────────────────────────────

    def _load_folders(self):
        self._clear_layout(self.folders_layout)
        folders = self.db.get_folders()
        if not folders:
            lbl = QLabel("Пока нет папок. Выберите слова и создайте папку.")
            lbl.setStyleSheet("color: #aaa; font-size: 14px; padding: 30px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.folders_layout.addWidget(lbl)
            return
        for f in folders:
            count = self.db.get_folder_word_count(f["id"])
            item = QFrame()
            item.setFrameShape(QFrame.Shape.NoFrame)
            item.setStyleSheet(
                "QFrame { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; }"
                "QFrame:hover { background: #f0f4ff; border-color: #c0d0f0; }")
            item.setFixedHeight(52)
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            lay = QHBoxLayout(item)
            lay.setContentsMargins(14, 8, 14, 8)
            icon_lbl = QLabel("📁")
            icon_lbl.setFont(QFont("Helvetica Neue", 18))
            lay.addWidget(icon_lbl)
            name_lbl = QLabel(f["name"])
            name_lbl.setFont(QFont("Helvetica Neue", 14, QFont.Weight.DemiBold))
            name_lbl.setStyleSheet("color: #1a1a2e;")
            lay.addWidget(name_lbl, 1)
            count_lbl = QLabel(f"{count} слов")
            count_lbl.setStyleSheet("color: #888; font-size: 12px;")
            lay.addWidget(count_lbl)
            fid = f["id"]
            item.mousePressEvent = lambda e, fid=fid: self._open_folder(fid)
            self.folders_layout.addWidget(item)

    def _open_folder(self, folder_id):
        self.current_folder_id = folder_id
        self._clear_layout(self.folder_view_layout)
        self.tabs.addTab(self.folder_view_widget, "← Назад")
        self.tabs.setCurrentWidget(self.folder_view_widget)
        folder = next((f for f in self.db.get_folders() if f["id"] == folder_id), None)
        if not folder:
            return
        back_btn = QPushButton("← Назад к папкам")
        back_btn.setStyleSheet(
            "QPushButton { background: none; border: none; color: #3b82f6; font-weight: bold; "
            "font-size: 13px; text-align: left; padding: 8px 14px; }"
            "QPushButton:hover { background: #e8f0fe; border-radius: 6px; }")
        back_btn.clicked.connect(self._back_to_folders)
        self.folder_view_layout.addWidget(back_btn)
        title_lbl = QLabel(folder["name"])
        title_lbl.setFont(QFont("Helvetica Neue", 16, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #1a1a2e; padding: 4px 14px;")
        self.folder_view_layout.addWidget(title_lbl)
        words = self.db.get_folder_words(folder_id)
        if not words:
            lbl = QLabel("Папка пуста.")
            lbl.setStyleSheet("color: #aaa; font-size: 14px; padding: 30px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.folder_view_layout.addWidget(lbl)
        else:
            for w in words:
                row = WordRow(w, self.hide_ru, self.hide_en, play_word,
                              self._toggle_mistake, self._delete_word, self._edit_word)
                self.folder_view_layout.addWidget(row)

    def _back_to_folders(self):
        idx = self.tabs.indexOf(self.folder_view_widget)
        if idx >= 0:
            self.tabs.removeTab(idx)
        self.current_folder_id = None
        self.tabs.setCurrentIndex(2)

    # ── Load words ──────────────────────────────────────────────────────

    def _load_words(self):
        self._clear_layout(self.word_layout)
        self._clear_layout(self.mist_layout)

        words = self.db.get_all_words()
        if not words:
            lbl = QLabel("Пока нет слов. Добавьте первое слово выше!")
            lbl.setStyleSheet("color: #aaa; font-size: 14px; padding: 30px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.word_layout.addWidget(lbl)
            return

        for w in words:
            row = WordRow(w, self.hide_ru, self.hide_en, play_word,
                          self._toggle_mistake, self._delete_word, self._edit_word)
            if self.select_mode:
                row.set_selectable(True, w["id"] in self.selected_word_ids)
                row.selection_toggled.connect(self._toggle_word_selection)
            self.word_layout.addWidget(row)
            if w["is_mistake"]:
                mist_row = WordRow(w, self.hide_ru, self.hide_en, play_word,
                                   self._toggle_mistake, self._delete_word, self._edit_word)
                if self.select_mode:
                    mist_row.set_selectable(True, w["id"] in self.selected_word_ids)
                    mist_row.selection_toggled.connect(self._toggle_word_selection)
                self.mist_layout.addWidget(mist_row)

        if not any(w["is_mistake"] for w in words):
            lbl = QLabel("Пока нет ошибок. Отмечайте слова звёздочкой ☆, чтобы они появились здесь.")
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
        self.status.setText("Слово удалено.")
        self.status.setStyleSheet("color: #888; font-size: 12px;")

    def _edit_word(self, word):
        self.db.update_word(word["id"], word["word_en"], word["word_ru"], word.get("transcription", ""))
        self._load_words()

    def _add_word(self):
        raw = self.entry.text().strip()
        if not raw:
            return
        self.status.setText("Поиск…")
        self.status.setStyleSheet("color: #888; font-size: 12px;")
        self.add_btn.setEnabled(False)

        self._lookup_thread = LookupThread(raw, self.db)
        self._lookup_thread.finished.connect(self._on_added)
        self._lookup_thread.error.connect(self._on_error)
        self._lookup_thread.start()

    def _on_added(self, raw, w_en, w_ru, tr, added):
        self.add_btn.setEnabled(True)
        if added:
            self.status.setText(f"Добавлено: {w_en} — {w_ru}  {tr}")
            self.status.setStyleSheet("color: #27ae60; font-size: 12px;")
            self.entry.clear()
            self._load_words()
        else:
            self.status.setText(f"«{w_en}» уже существует.")
            self.status.setStyleSheet("color: #e67e22; font-size: 12px;")

    def _on_error(self, msg):
        self.add_btn.setEnabled(True)
        self.status.setText(f"Ошибка: {msg}")
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
