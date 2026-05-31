import os
import re
from PyQt6.QtWidgets import (
    QMainWindow, QTextEdit, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QComboBox, QSpinBox,
    QSlider, QDialog, QFileDialog, QMenu, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QThread, QObject, pyqtSignal
from PyQt6.QtGui import (
    QTextCharFormat, QColor, QTextCursor, QFont,
    QKeySequence, QShortcut, QPainter, QPixmap,
)

from src.search import simple_search, fuzzy_search, or_search, proximity_search
from src.translation import translate_en_es, get_images, correct_word

# Highlight colors
COLORS = {
    'match':   QColor('#FFE566'),
    'a':       QColor('#66BBFF'),
    'b':       QColor('#FF9966'),
    'current': QColor('#FF4444'),
}

MARKER_COLORS = {
    'match':   QColor('#CCA000'),
    'a':       QColor('#0077CC'),
    'b':       QColor('#CC5500'),
}

# (interval_ms, pixels_per_tick)
SPEED_PARAMS = {
    1:  (2000, 1),
    2:  (1000, 1),
    3:  (500,  1),
    4:  (250,  1),
    5:  (100,  1),
    6:  (100,  2),
    7:  (100,  3),
    8:  (50,   3),
    9:  (50,   5),
    10: (50,   8),
}


# ---------------------------------------------------------------------------
# MarkerBar
# ---------------------------------------------------------------------------

class MarkerBar(QWidget):
    """Thin panel alongside the scroll bar showing match positions."""

    def __init__(self, text_edit: QTextEdit, parent=None):
        super().__init__(parent)
        self.text_edit = text_edit
        self._markers: list[tuple[float, QColor]] = []
        self.setFixedWidth(10)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_markers(self, matches, text_length: int):
        if text_length == 0:
            self._markers = []
        else:
            self._markers = [
                (m.start / text_length, MARKER_COLORS.get(m.label, MARKER_COLORS['match']))
                for m in matches
            ]
        self.update()

    def clear_markers(self):
        self._markers = []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#E8E8E8'))
        h = self.height()
        for ratio, color in self._markers:
            y = int(ratio * h)
            painter.fillRect(0, max(0, y - 1), self.width(), 3, color)
        painter.end()


# ---------------------------------------------------------------------------
# SearchBar
# ---------------------------------------------------------------------------

class SearchBar(QWidget):
    closed = pyqtSignal()
    search_requested = pyqtSignal(dict)
    navigate = pyqtSignal(int)  # +1 / -1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_params = None
        self._build_ui()
        self.hide()

    def _build_ui(self):
        self.setStyleSheet('background:#F0F0F0; border-top: 1px solid #CCC;')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['Simple', 'Fuzzy', 'Proximidad', 'OR'])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)
        self.mode_combo.currentIndexChanged.connect(self._reset_last_params)
        layout.addWidget(self.mode_combo)

        self.input_a = QLineEdit()
        self.input_a.setPlaceholderText('Buscar...')
        self.input_a.returnPressed.connect(self._handle_enter)
        self.input_a.textChanged.connect(self._reset_last_params)
        layout.addWidget(self.input_a)

        self.input_b = QLineEdit()
        self.input_b.setPlaceholderText('Segundo término...')
        self.input_b.returnPressed.connect(self._handle_enter)
        self.input_b.textChanged.connect(self._reset_last_params)
        self.input_b.hide()
        layout.addWidget(self.input_b)

        self.spin_n = QSpinBox()
        self.spin_n.setMinimum(1)
        self.spin_n.setMaximum(9999)
        self.spin_n.setValue(50)
        self.spin_n.setPrefix('n < ')
        self.spin_n.setSuffix(' chars')
        self.spin_n.valueChanged.connect(self._reset_last_params)
        self.spin_n.hide()
        layout.addWidget(self.spin_n)

        self.btn_prev = QPushButton('◀')
        self.btn_prev.setFixedWidth(28)
        self.btn_prev.clicked.connect(lambda: self.navigate.emit(-1))
        layout.addWidget(self.btn_prev)

        self.btn_next = QPushButton('▶')
        self.btn_next.setFixedWidth(28)
        self.btn_next.clicked.connect(lambda: self.navigate.emit(1))
        layout.addWidget(self.btn_next)

        self.lbl_count = QLabel('')
        self.lbl_count.setMinimumWidth(80)
        layout.addWidget(self.lbl_count)

        btn_close = QPushButton('✕')
        btn_close.setFixedWidth(28)
        btn_close.clicked.connect(self.closed.emit)
        layout.addWidget(btn_close)

    def _on_mode_change(self, idx):
        mode = self.mode_combo.currentText()
        two_fields = mode in ('Proximidad', 'OR')
        self.input_b.setVisible(two_fields)
        self.spin_n.setVisible(mode == 'Proximidad')
        labels = {
            'Simple':     ('Buscar...',       ''),
            'Fuzzy':      ('Buscar (fuzzy)...', ''),
            'Proximidad': ('Término A...',    'Término B...'),
            'OR':         ('Término A...',    'Término B...'),
        }
        a, b = labels.get(mode, ('Buscar...', ''))
        self.input_a.setPlaceholderText(a)
        self.input_b.setPlaceholderText(b)

    def _reset_last_params(self):
        self._last_params = None

    def _collect_params(self) -> dict:
        return {
            'mode':    self.mode_combo.currentText(),
            'query_a': self.input_a.text(),
            'query_b': self.input_b.text(),
            'n':       self.spin_n.value(),
        }

    def _handle_enter(self):
        params = self._collect_params()
        if params == self._last_params:
            self.navigate.emit(1)
        else:
            self._last_params = params
            self.search_requested.emit(params)

    def show_bar(self):
        self.show()
        self.input_a.setFocus()
        self.input_a.selectAll()

    def set_count(self, current: int, total: int):
        if total == 0:
            self.lbl_count.setText('Sin resultados')
        else:
            self.lbl_count.setText(f'{current} / {total}')


# ---------------------------------------------------------------------------
# Translation dialog
# ---------------------------------------------------------------------------

class _LoadingWorker(QObject):
    done = pyqtSignal(str, list, str)  # translation, [image_bytes], corrected_word

    def __init__(self, word: str, api_key: str):
        super().__init__()
        self.word = word
        self.api_key = api_key

    def run(self):
        corrected = correct_word(self.word)
        translation = translate_en_es(corrected)
        images = get_images(corrected, self.api_key)
        self.done.emit(translation, images, corrected)


class TranslationDialog(QDialog):
    def __init__(self, word: str, api_key: str, parent=None):
        super().__init__(parent)
        self._original_word = word
        self.setWindowTitle(f'"{word}"')
        self.setMinimumWidth(520)
        self._thread = None

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        lbl_word = QLabel(f'<h3 style="margin:0">{word}</h3>')
        lbl_word.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_word)

        self.lbl_correction = QLabel('')
        self.lbl_correction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_correction.setStyleSheet('font-size: 12px; color: #888; font-style: italic;')
        self.lbl_correction.hide()
        layout.addWidget(self.lbl_correction)

        self.lbl_translation = QLabel('<i>Traduciendo...</i>')
        self.lbl_translation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_translation.setStyleSheet('font-size: 16px; color: #333;')
        layout.addWidget(self.lbl_translation)

        img_row = QHBoxLayout()
        self.img_labels: list[QLabel] = []
        for _ in range(3):
            lbl = QLabel('...')
            lbl.setFixedSize(155, 155)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet('border: 1px solid #ccc; background: #f5f5f5; color: #999;')
            img_row.addWidget(lbl)
            self.img_labels.append(lbl)
        layout.addLayout(img_row)

        self._start_worker(word, api_key)

    def _start_worker(self, word: str, api_key: str):
        self._thread = QThread()
        self._worker = _LoadingWorker(word, api_key)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_loaded)
        self._worker.done.connect(self._thread.quit)
        self._thread.start()

    def _on_loaded(self, translation: str, images: list, corrected: str):
        if corrected != self._original_word.lower():
            self.lbl_correction.setText(f'typo corregido → {corrected}')
            self.lbl_correction.show()
        self.lbl_translation.setText(f'<b style="font-size:18px">→ {translation}</b>')
        for i, data in enumerate(images[:3]):
            if data:
                px = QPixmap()
                px.loadFromData(data)
                if not px.isNull():
                    scaled = px.scaled(
                        155, 155,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.img_labels[i].setPixmap(scaled)
                    self.img_labels[i].setText('')
                else:
                    self.img_labels[i].setText('(sin imagen)')
            else:
                self.img_labels[i].setText('(sin imagen)')


def _reflow(text: str) -> str:
    """Join hard-wrapped lines: only keep newlines after sentence-ending punctuation."""
    text = re.sub(r'\n[ \t]*\n', '\x00', text)         # preservar párrafos (línea en blanco)
    text = re.sub(r'([^.?!\n]) *\n *', r'\1 ', text)   # unir líneas consumiendo espacios al rededor del salto
    return text.replace('\x00', '\n\n')


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class LectorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._matches = []
        self._current_idx = -1
        self._pixabay_key = os.environ.get('PIXABAY_API_KEY', '')
        self._autoscroll_timer = QTimer()
        self._autoscroll_timer.timeout.connect(self._do_autoscroll)
        self._setup_ui()
        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setWindowTitle('Lector')
        self.resize(900, 680)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        # Text area + marker bar
        content = QHBoxLayout()
        content.setSpacing(0)
        content.setContentsMargins(0, 0, 0, 0)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.text_edit.customContextMenuRequested.connect(self._on_right_click)
        self._style_text_edit()
        content.addWidget(self.text_edit)

        self.marker_bar = MarkerBar(self.text_edit)
        content.addWidget(self.marker_bar)

        content_widget = QWidget()
        content_widget.setLayout(content)
        root.addWidget(content_widget, stretch=1)

        self.search_bar = SearchBar()
        self.search_bar.closed.connect(self._close_search)
        self.search_bar.search_requested.connect(self._on_search)
        self.search_bar.navigate.connect(self._navigate)
        root.addWidget(self.search_bar)

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(42)
        bar.setStyleSheet('background:#F5F5F5; border-bottom:1px solid #DDD;')
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        btn_open = QPushButton('Abrir archivo')
        btn_open.clicked.connect(self._open_file)
        layout.addWidget(btn_open)

        layout.addStretch()

        self.btn_autoscroll = QPushButton('▶ Auto-scroll')
        self.btn_autoscroll.setCheckable(True)
        self.btn_autoscroll.clicked.connect(self._toggle_autoscroll)
        layout.addWidget(self.btn_autoscroll)

        self.lbl_vel = QLabel('Vel:')
        self.lbl_vel.hide()
        layout.addWidget(self.lbl_vel)

        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 10)
        self.speed_slider.setValue(3)
        self.speed_slider.setFixedWidth(110)
        self.speed_slider.valueChanged.connect(self._update_autoscroll_speed)
        self.speed_slider.hide()
        layout.addWidget(self.speed_slider)

        return bar

    def _style_text_edit(self):
        font = QFont('Georgia', 14)
        self.text_edit.setFont(font)
        self.text_edit.setStyleSheet('''
            QTextEdit {
                background-color: #FAFAF7;
                color: #1A1A1A;
                border: none;
                selection-background-color: #B3D7FF;
            }
        ''')
        self.text_edit.document().setDocumentMargin(60)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence('Ctrl+F'), self, self._open_search)
        QShortcut(QKeySequence('Escape'), self, self._close_search)

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Abrir archivo', '',
            'Archivos de texto (*.txt *.md *.rst *.csv);;Todos (*)',
        )
        if path:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                self._set_text(f.read())
            self.setWindowTitle(f'Lector — {os.path.basename(path)}')
            self._close_search()

    def _set_text(self, text: str):
        self.text_edit.setPlainText(_reflow(text))
        from PyQt6.QtGui import QTextBlockFormat
        doc = self.text_edit.document()
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        block_fmt = QTextBlockFormat()
        block_fmt.setLineHeight(160, 1)  # 1 = ProportionalHeight
        cursor.setBlockFormat(block_fmt)
        cursor.setPosition(0)
        self.text_edit.setTextCursor(cursor)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _open_search(self):
        self.search_bar.show_bar()

    def _close_search(self):
        self.search_bar.hide()
        self.text_edit.setExtraSelections([])
        self.marker_bar.clear_markers()
        self._matches = []
        self._current_idx = -1

    def _on_search(self, params: dict):
        text = self.text_edit.toPlainText()
        mode = params['mode']
        a, b, n = params['query_a'], params['query_b'], params['n']

        if mode == 'Simple':
            self._matches = simple_search(text, a)
        elif mode == 'Fuzzy':
            self._matches = fuzzy_search(text, a)
        elif mode == 'OR':
            self._matches = or_search(text, a, b)
        elif mode == 'Proximidad':
            self._matches = proximity_search(text, a, b, n)

        self._current_idx = 0 if self._matches else -1
        self._apply_highlights()
        self.marker_bar.set_markers(self._matches, len(text))

        if self._matches:
            self._scroll_to(0)

        self.search_bar.set_count(
            self._current_idx + 1 if self._matches else 0,
            len(self._matches),
        )

    def _apply_highlights(self):
        selections = []
        for i, m in enumerate(self._matches):
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(self.text_edit.document())
            sel.cursor.setPosition(m.start)
            sel.cursor.setPosition(m.end, QTextCursor.MoveMode.KeepAnchor)
            sel.format = QTextCharFormat()
            color = COLORS['current'] if i == self._current_idx else COLORS.get(m.label, COLORS['match'])
            sel.format.setBackground(color)
            selections.append(sel)
        self.text_edit.setExtraSelections(selections)

    def _scroll_to(self, idx: int):
        if not self._matches or not (0 <= idx < len(self._matches)):
            return
        self._current_idx = idx
        self._apply_highlights()
        cursor = QTextCursor(self.text_edit.document())
        cursor.setPosition(self._matches[idx].start)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()
        self.search_bar.set_count(idx + 1, len(self._matches))

    def _navigate(self, direction: int):
        if not self._matches:
            return
        self._scroll_to((self._current_idx + direction) % len(self._matches))

    # ------------------------------------------------------------------
    # Right-click translation
    # ------------------------------------------------------------------

    def _on_right_click(self, pos):
        cursor = self.text_edit.cursorForPosition(pos)
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText().strip()
        if not word:
            return
        menu = QMenu(self)
        action = menu.addAction(f'Traducir "{word}"')
        action.triggered.connect(lambda: self._translate(word))
        menu.exec(self.text_edit.mapToGlobal(pos))

    def _translate(self, word: str):
        dlg = TranslationDialog(word, self._pixabay_key, self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Auto-scroll
    # ------------------------------------------------------------------

    def _toggle_autoscroll(self, checked: bool):
        if checked:
            self.btn_autoscroll.setText('⏸ Pausar')
            self.lbl_vel.show()
            self.speed_slider.show()
            self._update_autoscroll_speed()
            self._autoscroll_timer.start()
        else:
            self.btn_autoscroll.setText('▶ Auto-scroll')
            self.lbl_vel.hide()
            self.speed_slider.hide()
            self._autoscroll_timer.stop()

    def _update_autoscroll_speed(self):
        interval, _ = SPEED_PARAMS[self.speed_slider.value()]
        self._autoscroll_timer.setInterval(interval)

    def _do_autoscroll(self):
        _, pixels = SPEED_PARAMS[self.speed_slider.value()]
        sb = self.text_edit.verticalScrollBar()
        new_val = sb.value() + pixels
        if new_val >= sb.maximum():
            sb.setValue(sb.maximum())
            self._autoscroll_timer.stop()
            self.btn_autoscroll.setChecked(False)
            self.btn_autoscroll.setText('▶ Iniciar')
        else:
            sb.setValue(new_val)
