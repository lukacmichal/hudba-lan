from __future__ import annotations

from html import escape as html_escape
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QTime, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeySequence, QPixmap, QFont, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QToolTip,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QTabWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QSystemTrayIcon,
    QPlainTextEdit,
    QTextEdit,
    QComboBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from music_player import __version__, __version_code__, zanre
from music_player.persistence import StateStore
from music_player.player_controller import PlayerController
from music_player.spanky import SPANOK, SPANOK2
from music_player.system_integration import set_autostart

# ── colours ────────────────────────────────────────────────────────────────────
_C_BG_HEADER = "#1e1a16"
_C_ACCENT = "#d4860a"
_C_ACCENT_LIGHT = "#f0b44c"
_C_TEXT_PRIMARY = "#f5ead1"
_C_TEXT_SECONDARY = "#a08060"
_C_SURFACE = "#2b2520"
_C_BORDER = "#3d3025"

_COMPACT_HEIGHT = 80     # height when playlist is hidden
_ROLE_DURATION = Qt.ItemDataRole.UserRole + 1
# True pri riadku, na ktory ukazuje zalozka — delegat pred nazov kresli 🔖.
_ROLE_ZALOZKA = Qt.ItemDataRole.UserRole + 2

_MENU_STYLE = (
    "QMenu { background: #1e1a16; border: 1px solid #3d3025; }"
    "QMenu::item { color: #f5ead1; padding: 4px 20px; }"
    "QMenu::item:selected { background: #d4860a; color: #1e1a16; }"
    "QMenu::item:disabled { color: #a08060; }"
    "QMenu::separator { height: 1px; background: #3d3025; margin: 2px 6px; }"
)


class _ReorderablePlaylist(QListWidget):
    """QListWidget with custom internal drag-and-drop reordering.

    Draws its own drop-indicator line, auto-scrolls near edges,
    and never lets Qt touch the internal model.
    """

    rows_moved = Signal(list, int)  # (source_rows, target_row)
    external_drop = Signal(object, object)  # (mime_data, insert_at_row_or_None)

    _SCROLL_MARGIN = 0.20  # 20 % of visible height at top/bottom triggers scroll
    _SCROLL_STEP = 4       # pixels per timer tick

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)  # we draw our own
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._drag_rows: list[int] = []
        self._drop_row: int = -1
        self._dragging = False
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(16)  # ~60 fps
        self._scroll_timer.timeout.connect(self._auto_scroll_tick)
        self._scroll_direction = 0

    def startDrag(self, supportedActions) -> None:
        self._drag_rows = sorted({idx.row() for idx in self.selectedIndexes()})
        self._dragging = True
        super().startDrag(supportedActions)
        # Drag ended (drop or cancel) — clean up.
        self._dragging = False
        self._drop_row = -1
        self._scroll_timer.stop()
        self.viewport().update()

    def selectionCommand(self, index, event=None):
        """Block selection changes while dragging to prevent flickering."""
        if self._dragging:
            return QItemSelectionModel.SelectionFlag.NoUpdate
        return super().selectionCommand(index, event)

    def _has_local_paths(self, mime_data) -> bool:
        if not mime_data.hasUrls():
            return False
        return any(u.isLocalFile() for u in mime_data.urls())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.source() is self or self._has_local_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.source() is not self:
            if not self._has_local_paths(event.mimeData()):
                event.ignore()
                return
        event.acceptProposedAction()
        pos = event.position().toPoint()
        idx = self.indexAt(pos)
        if idx.isValid():
            rect = self.visualRect(idx)
            if pos.y() > rect.center().y():
                self._drop_row = idx.row() + 1
            else:
                self._drop_row = idx.row()
        else:
            self._drop_row = self.count()
        self.viewport().update()

        # Auto-scroll when near top/bottom edge.
        vp_h = self.viewport().height()
        margin = int(vp_h * self._SCROLL_MARGIN)
        if pos.y() < margin:
            self._scroll_direction = -1
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
        elif pos.y() > vp_h - margin:
            self._scroll_direction = 1
            if not self._scroll_timer.isActive():
                self._scroll_timer.start()
        else:
            self._scroll_direction = 0
            self._scroll_timer.stop()

    def dropEvent(self, event: QDropEvent) -> None:
        self._scroll_timer.stop()
        if event.source() is self and self._drag_rows:
            # Internal reorder
            target = self._drop_row if self._drop_row >= 0 else self.count()
            rows = self._drag_rows
            self._drag_rows = []
            self._drop_row = -1
            self.viewport().update()
            event.setDropAction(Qt.DropAction.IgnoreAction)
            event.accept()
            self.rows_moved.emit(rows, target)
            return
        # External file drop — delegate to MainWindow
        if self._has_local_paths(event.mimeData()):
            insert_at = self._drop_row if self._drop_row >= 0 else None
            self._drop_row = -1
            self.viewport().update()
            self.external_drop.emit(event.mimeData(), insert_at)
            event.acceptProposedAction()
            return
        self._drop_row = -1
        self.viewport().update()
        event.ignore()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_row < 0:
            return
        from PySide6.QtGui import QPainter, QPen
        painter = QPainter(self.viewport())
        pen = QPen(QColor(_C_ACCENT), 2)
        painter.setPen(pen)
        if self._drop_row < self.count():
            rect = self.visualRect(self.model().index(self._drop_row, 0))
            y = rect.top()
        else:
            if self.count() > 0:
                rect = self.visualRect(self.model().index(self.count() - 1, 0))
                y = rect.bottom() + 1
            else:
                y = 0
        painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()

    def _auto_scroll_tick(self) -> None:
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() + self._scroll_direction * self._SCROLL_STEP)


class _PlaylistDelegate(QStyledItemDelegate):
    """Draws track name followed by duration in a smaller, dimmer font."""

    _GAP = 10  # pixels between title and duration

    def paint(self, painter, option, index) -> None:
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QStyleOptionViewItem

        # Draw background, selection highlight — but suppress the default text.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        title = opt.text
        if index.data(_ROLE_ZALOZKA):
            title = "🔖 " + title
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        dur = index.data(_ROLE_DURATION) or ""
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        text_rect = option.rect.adjusted(6, 0, -6, 0)

        painter.save()

        # Measure duration width first so we can reserve space for it.
        dur_font = QFont(option.font)
        pt = dur_font.pointSizeF()
        if pt > 0:
            dur_font.setPointSizeF(max(pt * 0.88, 1.0))
        dur_fm = QFontMetrics(dur_font)
        dur_width = dur_fm.horizontalAdvance(dur) if dur else 0

        # Draw title (left-aligned, elided to leave room for duration).
        title_color = QColor("#1e1a16") if is_selected else QColor(_C_TEXT_PRIMARY)
        painter.setPen(title_color)
        painter.setFont(option.font)
        fm = QFontMetrics(option.font)
        max_title_width = text_rect.width() - dur_width - self._GAP if dur else text_rect.width()
        elided_title = fm.elidedText(title, Qt.TextElideMode.ElideRight, max(max_title_width, 50))
        title_rect = text_rect.adjusted(0, 0, -(dur_width + self._GAP) if dur else 0, 0)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

        # Draw duration (right-aligned).
        if dur:
            dur_color = QColor("#1e1a16") if is_selected else QColor(_C_TEXT_SECONDARY)
            painter.setPen(dur_color)
            painter.setFont(dur_font)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dur)

        painter.restore()
_FULL_HEIGHT_DEFAULT = 620

_STYLESHEET = f"""
QMainWindow {{
    background: transparent;
    color: {_C_TEXT_PRIMARY};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QWidget {{
    background: transparent;
    color: {_C_TEXT_PRIMARY};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    background: rgba(35, 31, 26, 120);
    border: 1px solid {_C_BORDER};
    border-radius: 6px;
    margin-top: 0px;
    padding-top: 2px;
    font-weight: 600;
    color: {_C_TEXT_SECONDARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
}}
QToolTip {{
    background: #1e1a16;
    color: {_C_TEXT_PRIMARY};
    border: 1px solid {_C_ACCENT};
    padding: 4px 6px;
}}
QListWidget {{
    background: rgba(35, 31, 26, 120);
    border: 1px solid {_C_BORDER};
    border-radius: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 3px 6px;
    border-radius: 3px;
}}
QListWidget::item:selected {{
    background: {_C_ACCENT};
    color: #1e1a16;
}}
QListWidget::item:hover:!selected {{
    background: #3a3028;
}}
QPushButton {{
    background: #6b5c4e;
    border: 1px solid #8a7a6a;
    border-radius: 4px;
    padding: 3px 10px;
    color: {_C_TEXT_PRIMARY};
    font-weight: 500;
}}
QPushButton:hover {{
    background: #8a7a6a;
    border-color: {_C_ACCENT};
}}
QPushButton:pressed {{
    background: {_C_ACCENT};
    color: #1e1a16;
}}
QSlider {{
    padding: 0px;
    margin: 0px;
}}
QSlider::groove:horizontal {{
    height: 4px;
    border-radius: 2px;
    background: #3d3028;
}}
QSlider::sub-page:horizontal {{
    border-radius: 2px;
    background: {_C_ACCENT};
}}
QSlider::add-page:horizontal {{
    border-radius: 2px;
    background: #3d3028;
}}
QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: {_C_ACCENT_LIGHT};
}}
QComboBox {{
    background: #231f1a;
    border: 1px solid {_C_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: #231f1a;
    selection-background-color: {_C_ACCENT};
}}
QCheckBox {{
    spacing: 6px;
    color: {_C_TEXT_SECONDARY};
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {_C_BORDER};
    border-radius: 3px;
    background: #231f1a;
}}
QCheckBox::indicator:checked {{
    background: {_C_ACCENT};
    border-color: {_C_ACCENT_LIGHT};
}}
QTextEdit {{
    background: #1e1a16;
    border: 1px solid {_C_BORDER};
    border-radius: 4px;
    color: {_C_TEXT_PRIMARY};
    line-height: 1.5;
    padding: 4px;
}}
QScrollArea {{ border: none; }}
QLabel#lbl_stream {{
    color: #4a8c5c;
    font-size: 11px;
}}
QLabel#lbl_status {{
    color: {_C_TEXT_SECONDARY};
    font-size: 11px;
}}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# MainWindow — compact player + collapsible playlist panel
# ═══════════════════════════════════════════════════════════════════════════════

class _BackgroundWidget(QWidget):
    """Central widget that paints a blurred album cover background."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:
        from PySide6.QtCore import QRect, QSize
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        parent = self.window()
        bg = getattr(parent, "_bg_pixmap", None)
        if bg:
            # Scale to full window width, use full_height for consistent crop
            full_h = getattr(parent, "_full_height", self.height())
            ref_size = QSize(self.width(), max(full_h, self.height()))
            scaled = bg.scaled(ref_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            # Crop from top-left corner (same origin in both modes)
            x = (scaled.width() - self.width()) // 2
            cropped = scaled.copy(QRect(x, 0, self.width(), self.height()))
            p.drawPixmap(0, 0, cropped)
        else:
            p.fillRect(self.rect(), QColor(_C_BG_HEADER))
        p.end()


class LyricsEdit(QTextEdit):
    """Read-only lyrics viewer with per-word DeepL hover translation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMouseTracking(True)
        self._api_key: str = ""
        self._hover_enabled: bool = True
        self._last_word: str = ""
        self._pending_word: str = ""
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(400)
        self._hover_timer.timeout.connect(self._fetch_and_show)
        self._tooltip_pos: QPoint = QPoint()

    def set_api_key(self, key: str) -> None:
        self._api_key = key

    def set_hover_enabled(self, enabled: bool) -> None:
        """Vypni prekladanie slov, keď sa zobrazuje slovenský preklad —
        prekladať slovenčinu do slovenčiny by len míňalo kvótu DeepL."""
        self._hover_enabled = enabled
        if not enabled:
            self._hover_timer.stop()
            self._last_word = ""

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if not self._api_key or not self._hover_enabled:
            return
        cursor = self.cursorForPosition(event.pos())
        cursor.select(cursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText().strip()
        word = "".join(c for c in word if c.isalpha())
        if word and word.lower() != self._last_word.lower():
            self._pending_word = word
            self._tooltip_pos = event.globalPosition().toPoint()
            self._hover_timer.start()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover_timer.stop()

    def _fetch_and_show(self) -> None:
        word = self._pending_word
        if not word:
            return
        self._last_word = word
        import threading
        threading.Thread(target=self._translate_and_emit, args=(word, self._tooltip_pos), daemon=True).start()

    def _translate_and_emit(self, word: str, pos: QPoint) -> None:
        from music_player.translator import translate_word
        translation = translate_word(word, self._api_key)
        if translation and translation.lower() != word.lower():
            self._show_tooltip.emit(f"{word} → {translation}", pos)

    _show_tooltip = Signal(str, QPoint)

    def _on_show_tooltip(self, text: str, pos: QPoint) -> None:
        QToolTip.showText(pos, text, self)


class _SpanokDialog(QDialog):
    """Sprava zoznamu skladieb pre tlacidlo "Spanok" alebo "Spanok 2".

    Jeden dialog pre obe tlacidla — lisia sa len tym, ktory M3U subor citaju
    a zapisuju. Zoznam sa uklada vedla config.txt, takze sa da rovnako dobre
    editovat rucne. Riadky, ktore na disku uz nie su, sa tu zobrazia oznacene
    ako chybajuce — nemiznu ticho, aby ich pouzivatel vedel opravit alebo
    vyhodit.
    """

    def __init__(
        self,
        parent,
        ktory: str,
        entries: list[str],
        missing: set[str],
        from_playlist: list[str],
        nechat: bool,
    ) -> None:
        super().__init__(parent)
        from music_player import spanky

        self._ktory = ktory
        self._from_playlist = from_playlist
        meno = spanky.nazov(ktory)
        self.setWindowTitle(f"{meno} — zoznam skladieb")
        self.setMinimumSize(620, 420)
        self.setStyleSheet(
            "QDialog { background: #1e1a16; }"
            "QLabel { color: #f5ead1; }"
            "QListWidget { background: #2a2520; color: #f5ead1; border: 1px solid #3d3025; }"
            "QListWidget::item:selected { background: #d4860a; color: #1e1a16; }"
            "QPushButton { background: #2b2520; color: #f5ead1; border: 1px solid #3d3025;"
            " padding: 4px 10px; }"
            "QPushButton:hover { border-color: #d4860a; }"
            "QCheckBox { color: #f5ead1; }"
        )
        layout = QVBoxLayout(self)
        info = QLabel(
            f"Tieto skladby pridá tlačidlo <b>{html_escape(meno)}</b> na koniec "
            "playlistu a hneď ich pustí.<br>"
            "Ak už na konci playlistu presne takto sú, nepridá nič — len ich pustí.<br>"
            "Poradie zhora nadol = poradie prehrávania. Ukladá sa do:<br>"
            f"<span style='color: #a08060;'>"
            f"{html_escape(str(spanky.playlist_path(ktory)))}</span>"
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for entry in entries:
            self._list.addItem(self._make_item(entry, entry.lower() in missing))
        layout.addWidget(self._list, 1)

        row = QHBoxLayout()
        add_files_button = QPushButton("+ Súbory")
        add_playlist_button = QPushButton(f"+ Z playlistu ({len(from_playlist)})")
        add_playlist_button.setToolTip("Pridá skladby, ktoré máš označené v playliste")
        add_playlist_button.setEnabled(bool(from_playlist))
        remove_button = QPushButton("Odstrániť")
        up_button = QPushButton("↑")
        down_button = QPushButton("↓")
        for widget in (add_files_button, add_playlist_button, remove_button, up_button, down_button):
            row.addWidget(widget)
        row.addStretch(1)
        layout.addLayout(row)

        self._nechat_checkbox = QCheckBox(
            "Nechať skladby v playliste aj po ukončení prehrávača"
        )
        self._nechat_checkbox.setChecked(nechat)
        self._nechat_checkbox.setToolTip(
            "Vypnuté (bežné): skladby z tohto zoznamu sa pri ukončení prehrávača "
            "z playlistu zase vyhodia — playlist ostane taký, aký bol predtým.\n"
            "Zapnuté: ostanú v ňom aj na ďalší deň.\n"
            f"V config.txt je to riadok {spanky.kluc_nechat(ktory)}=ano / nie"
        )
        layout.addWidget(self._nechat_checkbox)

        self._count_label = QLabel()
        layout.addWidget(self._count_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        add_files_button.clicked.connect(self._add_files)
        add_playlist_button.clicked.connect(self._add_from_playlist)
        remove_button.clicked.connect(self._remove_selected)
        up_button.clicked.connect(lambda: self._move_selected(-1))
        down_button.clicked.connect(lambda: self._move_selected(1))
        self._update_count()

    @staticmethod
    def _make_item(path: str, is_missing: bool) -> QListWidgetItem:
        name = Path(path).stem or path
        item = QListWidgetItem(f"{name} — CHÝBA NA DISKU" if is_missing else name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        if is_missing:
            item.setForeground(QColor("#c05050"))
        return item

    def nechat_v_playliste(self) -> bool:
        return self._nechat_checkbox.isChecked()

    def entries(self) -> list[str]:
        return [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
        ]

    def _append(self, paths: list[str]) -> int:
        known = {str(path).lower() for path in self.entries()}
        added = 0
        for raw in paths:
            resolved = str(Path(raw).expanduser().resolve())
            if resolved.lower() in known:
                continue
            known.add(resolved.lower())
            self._list.addItem(self._make_item(resolved, False))
            added += 1
        self._update_count()
        return added

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self.windowTitle(),
            "",
            "Audio a playlisty (*.mp3 *.flac *.aac *.ogg *.wav *.m4a *.wma *.m3u *.m3u8)",
        )
        if not files:
            return
        from music_player.models import collect_audio_paths
        self._append(collect_audio_paths(files))

    def _add_from_playlist(self) -> None:
        self._append(self._from_playlist)

    def _remove_selected(self) -> None:
        for row in sorted({index.row() for index in self._list.selectedIndexes()}, reverse=True):
            self._list.takeItem(row)
        self._update_count()

    def _move_selected(self, delta: int) -> None:
        rows = sorted({index.row() for index in self._list.selectedIndexes()}, reverse=delta > 0)
        if not rows:
            return
        for row in rows:
            if not (0 <= row + delta < self._list.count()):
                return
        for row in rows:
            item = self._list.takeItem(row)
            self._list.insertItem(row + delta, item)
            item.setSelected(True)

    def _update_count(self) -> None:
        self._count_label.setText(f"Skladieb v zozname: {self._list.count()}")


class _NovinkyDialog(QDialog):
    """Zoznam metalovych noviniek zo skenu — co este treba vypocut.

    Album ma stav nove / zaujimave / skontrolovane a podla neho je v jednej
    zo styroch zaloziek. Nic sa nemaze: `precitane.log` na NAS-e je len
    historia klikov, takze sa kazdy stav da zmenit spat — tlacidlami dole
    alebo menu po kliknuti na album. Ctrl+F hlada vo vsetkych zalozkach naraz
    a povie, v ktorej album je.

    Polozky, s ktorymi si filter nevedel rady, su zamerne az pod ciarou:
    filter sa na nich este bude ladit a nemaju miesat prve miesta.
    """

    _ROLA = Qt.ItemDataRole.UserRole

    #: (meno zalozky v subore, popis na uskovi). Poradie urcuje poradie zalaziek.
    #: Starsi subor zalozky nema — vtedy sa vsetko ukaze v prvej.
    #: Posledne dve su stavy albumu (`novinky.ZAUJIMAVE` / `SKONTROLOVANE`),
    #: prve dve ukazuju len nove albumy.
    _ZALOZKY = (
        ("tyzden", "Tento týždeň"),
        ("uz_vydane", "Už vydané"),
        ("zaujimave", "Zaujímavé"),
        ("skontrolovane", "Skontrolované"),
    )

    @property
    def _list(self):
        """Zoznam v prave otvorenej zalozke — tlacidla pracuju s nim."""
        return self._zalozky.currentWidget()

    def __init__(self, parent, zoznam, oznac) -> None:
        super().__init__(parent)
        self._zoznam = zoznam
        self._oznac = oznac

        self.setWindowTitle("Metalové novinky")
        # Styri zalozky s poctami a sedem tlacidiel dole — pod ~980 px sa
        # zalozky schovaju za sipky a tlacidla orezu.
        self.setMinimumSize(980, 560)
        self.setStyleSheet(
            "QDialog { background: #1e1a16; }"
            "QLabel { color: #f5ead1; }"
            "QListWidget { background: #2a2520; color: #f5ead1; border: 1px solid #3d3025; }"
            "QListWidget::item { padding: 3px 4px; }"
            "QListWidget::item:selected { background: #d4860a; color: #1e1a16; }"
            "QPushButton { background: #2b2520; color: #f5ead1; border: 1px solid #3d3025;"
            " padding: 4px 10px; }"
            "QPushButton:hover { border-color: #d4860a; }"
            "QPushButton:disabled { color: #6b5c4a; border-color: #2b2520; }"
            "QCheckBox { color: #f5ead1; }"
            "QLineEdit { background: #2a2520; color: #f5ead1; border: 1px solid #3d3025;"
            " padding: 3px 6px; }"
            "QLineEdit:focus { border-color: #d4860a; }"
            "QMenu { background: #2a2520; color: #f5ead1; border: 1px solid #3d3025; }"
            "QMenu::item { padding: 5px 18px; }"
            "QMenu::item:selected { background: #d4860a; color: #1e1a16; }"
            "QMenu::item:disabled { color: #6b5c4a; }"
        )

        layout = QVBoxLayout(self)
        self._info = QLabel()
        self._info.setTextFormat(Qt.TextFormat.RichText)
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        # Hladanie cez vsetky zalozky naraz — pod nim riadok, v ktorej je.
        self._hladaj = QLineEdit()
        self._hladaj.setPlaceholderText("Hľadať (Ctrl+F) — kapela, album, štýl, krajina …")
        self._hladaj.setClearButtonEnabled(True)
        self._hladaj.textChanged.connect(lambda _t: self._napln())
        layout.addWidget(self._hladaj)
        self._nalez = QLabel("")
        self._nalez.setTextFormat(Qt.TextFormat.RichText)
        self._nalez.setWordWrap(True)
        layout.addWidget(self._nalez)
        skratka = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        skratka.activated.connect(lambda: (self._hladaj.setFocus(), self._hladaj.selectAll()))

        # Dve zalozky, lebo su to dve rozne otazky. „Tento tyzden" je plan
        # („co vyjde"), „Uz vydane" je dobiehanie („co na MA pribudlo az po
        # vydani a inak by mi ucupelo"). V jednom zozname sa to mieta a nedalo
        # by sa zoradit ani podla dna, ani podla toho, co je este pred sebou.
        self._zalozky = QTabWidget()
        self._zalozky.setStyleSheet(
            "QTabBar::tab { background: #2a2520; color: #c9b48f;"
            " padding: 5px 12px; border: 1px solid #3d3025; }"
            "QTabBar::tab:selected { background: #3a3128; color: #f5ead1;"
            " border-color: #d4860a; }"
            "QTabWidget::pane { border: 1px solid #3d3025; }")
        self._zoznamy: dict[str, QListWidget] = {}
        for meno, popis in self._ZALOZKY:
            zoznam = QListWidget()
            zoznam.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            zoznam.setAlternatingRowColors(False)
            zoznam.itemSelectionChanged.connect(self._obnov_tlacidla)
            zoznam.itemDoubleClicked.connect(lambda _i: self._otvor("youtube"))
            # Lave tlacidlo len oznacuje, menu so stavmi je na pravom.
            zoznam.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            zoznam.customContextMenuRequested.connect(self._ukaz_menu)
            self._zoznamy[meno] = zoznam
            self._zalozky.addTab(zoznam, popis)
        self._zalozky.currentChanged.connect(lambda _i: self._obnov_tlacidla())
        layout.addWidget(self._zalozky, 1)

        row = QHBoxLayout()
        self._yt_button = QPushButton("▶ YouTube")
        self._yt_button.setToolTip("Otvorí album na YouTube (dvojklik na riadok robí to isté)")
        self._bc_button = QPushButton("Bandcamp")
        self._ma_button = QPushButton("Metal Archives")
        self._zanre_button = QPushButton("Žánre…")
        self._zanre_button.setToolTip(
            "Ktoré slová v štýle vydanie púšťajú a ktoré ho vyhadzujú.\n"
            "Zmena platí hneď a aj pre mail zo skenu.")
        self._zanre_button.clicked.connect(self._uprav_zanre)
        self._zaujimave_button = QPushButton("★ Zaujímavé")
        self._zaujimave_button.setToolTip("Presunie označené albumy do záložky Zaujímavé")
        self._precitane_button = QPushButton("✓ Skontrolované")
        self._precitane_button.setToolTip("Označené albumy zmiznú zo zoznamu nových")
        self._vratit_button = QPushButton("↩ Vrátiť medzi nové")
        for widget in (self._yt_button, self._bc_button, self._ma_button,
                       self._zanre_button):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(self._zaujimave_button)
        row.addWidget(self._vratit_button)
        row.addWidget(self._precitane_button)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._yt_button.clicked.connect(lambda: self._otvor("youtube"))
        self._bc_button.clicked.connect(lambda: self._otvor("bandcamp"))
        self._ma_button.clicked.connect(lambda: self._otvor("ma"))
        from music_player import novinky

        self._zaujimave_button.clicked.connect(lambda: self._nastav(novinky.ZAUJIMAVE))
        self._precitane_button.clicked.connect(lambda: self._nastav(novinky.SKONTROLOVANE))
        self._vratit_button.clicked.connect(lambda: self._nastav(novinky.NOVE))

        self._napln()

    # ── obsah ─────────────────────────────────────────────────────────────────
    def _napln(self) -> None:
        from music_player import novinky

        dopyt = self._hladaj.text().strip()
        nalezy = []
        for i, (meno, popis) in enumerate(self._ZALOZKY):
            albumy = self._albumy_zalozky(meno)
            if dopyt:
                albumy = [a for a in albumy if novinky.zhoda(a, dopyt)]
                if albumy:
                    nalezy.append((i, popis, len(albumy)))
            self._naplnZoznam(self._zoznamy[meno], albumy)
            self._zalozky.setTabText(i, f"{popis} ({len(albumy)})")

        self._info.setText(self._hlavicka())
        self._ukaz_nalez(dopyt, nalezy)
        self._obnov_tlacidla()

    def _albumy_zalozky(self, meno: str) -> list:
        from music_player import novinky

        z = self._zoznam
        if meno in (novinky.ZAUJIMAVE, novinky.SKONTROLOVANE):
            # Tu uz rozhodol clovek, nie filter zanrov — ukaze sa vsetko.
            return z.v_stave(meno)
        albumy = z.pre_zalozku(meno)
        if not albumy and not z.zalozky and meno == self._ZALOZKY[0][0]:
            # Starsi subor zalozky nema. Vsetko ide do prvej — lepsie nez
            # dve prazdne zalozky a zoznam, ktory nikde nevidno.
            albumy = list(z.albumy)
        return [a for a in albumy if z.stav(a.kluc) == novinky.NOVE]

    def _ukaz_nalez(self, dopyt: str, nalezy: list) -> None:
        """Riadok pod hladanim: v ktorych zalozkach album je.

        Ked nie je v ziadnej, povie aj preco, ak to vie — album moze byt
        v zozname, len ho skryva filter zanrov. „Nenaslo sa" bez toho by
        tvrdilo, ze sken o albume nevie, a to nemusi byt pravda.
        """
        from music_player import novinky

        if not dopyt:
            self._nalez.setText("")
            return
        if nalezy:
            self._nalez.setText("Nájdené v: " + " · ".join(
                f"<b>{html_escape(popis)}</b> ({pocet})" for _i, popis, pocet in nalezy))
            if self._zalozky.currentIndex() not in {i for i, _p, _n in nalezy}:
                self._zalozky.setCurrentIndex(nalezy[0][0])
            return
        skryte = [a for a in self._zoznam.vsetky() if novinky.zhoda(a, dopyt)]
        if skryte:
            a = skryte[0]
            self._nalez.setText(
                f"„{html_escape(dopyt)}“ nie je v žiadnej záložke — "
                f"<b>{html_escape(a.nadpis)}</b> je v zozname, ale skrýva ho filter "
                f"žánrov (štýl: {html_escape(a.styl or 'neznámy')}). Pozri Žánre…")
        else:
            self._nalez.setText(
                f"„{html_escape(dopyt)}“ nie je v žiadnej záložke ani v zozname zo skenu.")

    def _naplnZoznam(self, zoznam, albumy: list) -> None:
        """Jedna zalozka: albumy zoskupene po dnoch, nezaradene pod ciarou.

        Deliaci riadok s datumom je tu preto, ze zadanie znie „najprv po dnoch,
        potom podla abecedy" — poradie samo o sebe nie je vidiet, kym dni nie su
        oddelene. Poradie prichadza zo suboru a nemeni sa (viď `pre_zalozku`).
        """
        zoznam.clear()
        # O tom, co je „preslo" a co „nezaradene", rozhoduju AKTUALNE slova
        # filtra, nie to, co si o albume myslel sken. Vdaka tomu sa zmena
        # zanrov prejavi hned, bez cakania na nocny beh.
        preslo, nezaradene = [], []
        for a in albumy:
            (nezaradene if self._zoznam.posudok(a)[0] == zanre.NEZARADENE
             else preslo).append(a)

        if not preslo and not nezaradene:
            zoznam.addItem(self._ciara("zatiaľ nič"))

        den = None
        for album in preslo:
            if album.den != den:
                den = album.den
                zoznam.addItem(self._ciara(den or "bez dátumu vydania"))
            zoznam.addItem(self._polozka(album))

        if nezaradene:
            zoznam.addItem(self._ciara(
                f"filter si s nimi nevedel rady ({len(nezaradene)}) — "
                "štýl treba dohľadať ručne"))
            for album in nezaradene:
                zoznam.addItem(self._polozka(album))

    def _hlavicka(self) -> str:
        z = self._zoznam
        riadky = [
            f"<b>{z.pocet_novych}</b> nových · <b>{len(z.zaujimave)}</b> zaujímavých"
            f" · {len(z.precitane)} skontrolovaných"
            f" &nbsp;·&nbsp; {len(z.albumy)} v zozname zo skenu"
        ]
        if not z.z_nasu:
            riadky.append(
                "<span style='color: #d4860a;'>NAS neodpovedal — toto je posledná "
                "stiahnutá kópia. Nové albumy pribudnú, keď budeš doma.</span>")
        if z.caka:
            riadky.append(
                f"<span style='color: #a89070;'>{z.caka} odškrtnutí čaká na NAS "
                "— odošlú sa samé pri najbližšom spojení.</span>")
        return "<br>".join(riadky)

    def _polozka(self, album) -> QListWidgetItem:
        from music_player import novinky

        stav = self._zoznam.stav(album.kluc)
        nadpis = album.nadpis + {novinky.ZAUJIMAVE: "   ★",
                                 novinky.SKONTROLOVANE: "   ✓"}.get(stav, "")
        vysledok, dovod = self._zoznam.posudok(album)
        popis = album.popis
        if vysledok == zanre.NEZARADENE and dovod:
            popis = f"{popis} · {dovod}" if popis else dovod
        item = QListWidgetItem(f"{nadpis}\n      {popis}")
        item.setData(self._ROLA, album)
        if stav == novinky.SKONTROLOVANE:
            item.setForeground(QColor("#8a7a66"))
        elif stav == novinky.ZAUJIMAVE:
            item.setForeground(QColor(_C_ACCENT_LIGHT))
        elif vysledok == zanre.NEZARADENE:
            item.setForeground(QColor("#c9b48f"))
        return item

    @staticmethod
    def _ciara(text: str) -> QListWidgetItem:
        item = QListWidgetItem(f"── {text} ──")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor("#7a6a56"))
        return item

    # ── slova filtra zanrov ───────────────────────────────────────────────────
    def _uprav_zanre(self) -> None:
        """Okno na uprav slov filtra. Zmena plati hned a zapise sa na NAS.

        Je to jeden subor (`filtre.json` vedla zoznamu), z ktoreho cita aj
        nocny sken — takze co sa tu zmeni, plati aj pre mail. Keby to boli dve
        nastavenia, rozisli by sa pri prvej uprave.
        """
        z = self._zoznam
        okno = QDialog(self)
        okno.setWindowTitle("Žánre — čo sa púšťa a čo nie")
        okno.setMinimumWidth(560)
        okno.setStyleSheet(self.styleSheet()
                           + "QPlainTextEdit { background: #2a2520; color: #f5ead1;"
                             " border: 1px solid #3d3025; }")

        rozlozenie = QVBoxLayout(okno)
        vysvetlenie = QLabel(
            "Rozhoduje slovo <b>čistý</b>: zakázané žánre vyhodia vydanie len vtedy, "
            "keď je štýl výhradne z nich. Len čo je v štýle povolené slovo, vydanie "
            "prejde — <i>Death Metal/Thrash Metal</i> je death, nie thrash.<br>"
            "Jedno slovo na riadok, malé písmená. Hľadá sa ako podreťazec, "
            "takže <i>grind</i> chytí aj <i>Grindcore</i>.")
        vysvetlenie.setWordWrap(True)
        rozlozenie.addWidget(vysvetlenie)

        polia = QHBoxLayout()
        stlpce = []
        for nadpis, slova in (("Púšťa sa (aspoň jedno musí sedieť)", z.povolene),
                              ("Vyhadzuje sa (keď nesedí nič z ľavého)", z.zakazane)):
            stlpec = QVBoxLayout()
            stlpec.addWidget(QLabel(f"<b>{nadpis}</b>"))
            pole = QPlainTextEdit(zanre.do_zoznamu(slova))
            pole.setMinimumHeight(200)
            stlpec.addWidget(pole)
            polia.addLayout(stlpec)
            stlpce.append(pole)
        rozlozenie.addLayout(polia)

        stav = QLabel("")
        stav.setWordWrap(True)
        rozlozenie.addWidget(stav)

        tlacidla = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                    | QDialogButtonBox.StandardButton.Cancel)
        rozlozenie.addWidget(tlacidla)
        tlacidla.rejected.connect(okno.reject)

        def uloz() -> None:
            povolene = zanre.zo_zoznamu(stlpce[0].toPlainText())
            zakazane = zanre.zo_zoznamu(stlpce[1].toPlainText())
            if not povolene:
                # Prazdny lavy stlpec znamena „neprejde nic" — to skoro urcite
                # nikto nechce a prazdne okno by nic nevysvetlilo.
                stav.setText("<span style='color:#e0698a;'>Ľavý stĺpec nesmie byť "
                             "prázdny — inak by neprešlo nič.</span>")
                return
            spolocne = sorted(set(povolene) & set(zakazane))
            if spolocne:
                # Slovo v oboch stlpcoch by vzdy vyhralo lave; radsej to povedz,
                # nez nechat cloveka hadat, preco pravy stlpec nefunguje.
                stav.setText("<span style='color:#e0698a;'>V oboch stĺpcoch naraz: "
                             + ", ".join(spolocne)
                             + " — v takom prípade vždy vyhrá ľavý.</span>")
                return
            z.povolene, z.zakazane = povolene, zakazane
            na_nase = self._novinky_uloz_zanre(povolene, zakazane)
            self._napln()
            okno.accept()
            if not na_nase:
                # Ulozene lokalne, na NAS nie — a to je rozdiel, ktory sa musi
                # povedat: sken bude do najblizsieho spojenia filtrovat po starom
                # a mail sa s oknom rozide.
                QMessageBox.warning(
                    self, "Žánre",
                    "Zmena platí v tomto okne, ale na NAS sa nezapísala — sken "
                    "teda zatiaľ filtruje po starom.\n\nSkús to znova, keď budeš doma.")

        tlacidla.accepted.connect(uloz)
        okno.exec()

    @staticmethod
    def _novinky_uloz_zanre(povolene: list, zakazane: list) -> bool:
        from music_player import novinky

        return novinky.uloz_zanre(povolene, zakazane)

    def _vybrane(self) -> list:
        albumy = []
        for item in self._list.selectedItems():
            album = item.data(self._ROLA)
            if album is not None:
                albumy.append(album)
        return albumy

    def _obnov_tlacidla(self) -> None:
        from music_player import novinky

        vybrane = self._vybrane()
        stavy = {self._zoznam.stav(a.kluc) for a in vybrane}
        self._yt_button.setEnabled(bool(vybrane))
        self._bc_button.setEnabled(any(a.bandcamp for a in vybrane))
        self._ma_button.setEnabled(any(a.ma for a in vybrane))
        self._zaujimave_button.setEnabled(bool(stavy - {novinky.ZAUJIMAVE}))
        self._precitane_button.setEnabled(bool(stavy - {novinky.SKONTROLOVANE}))
        self._vratit_button.setEnabled(bool(stavy - {novinky.NOVE}))

    # ── menu na pravom tlacidle ───────────────────────────────────────────────
    def _ukaz_menu(self, pozicia) -> None:
        from music_player import novinky

        zoznam = self._list
        item = zoznam.itemAt(pozicia)
        if item is None or item.data(self._ROLA) is None:
            return
        # Pravy klik mimo oznacenia plati pre ten riadok (ako v Prieskumnikovi);
        # na oznacenom riadku plati pre cele oznacenie.
        if not item.isSelected():
            zoznam.setCurrentItem(item, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        vybrane = self._vybrane()
        if not vybrane:
            return
        stavy = {self._zoznam.stav(a.kluc) for a in vybrane}
        menu = QMenu(self)
        for stav, text in ((novinky.ZAUJIMAVE, "★ Zaujímavé"),
                           (novinky.NOVE, "↩ Vrátiť medzi nové"),
                           (novinky.SKONTROLOVANE, "✓ Skontrolované")):
            akcia = menu.addAction(text)
            akcia.setEnabled(bool(stavy - {stav}))
            akcia.triggered.connect(lambda _c=False, s=stav: self._nastav(s))
        menu.addSeparator()
        for kam, text, smie in (("youtube", "▶ YouTube", True),
                                ("bandcamp", "Bandcamp", any(a.bandcamp for a in vybrane)),
                                ("ma", "Metal Archives", any(a.ma for a in vybrane))):
            akcia = menu.addAction(text)
            akcia.setEnabled(smie)
            akcia.triggered.connect(lambda _c=False, k=kam: self._otvor(k))
        menu.exec(zoznam.viewport().mapToGlobal(pozicia))

    def keyPressEvent(self, event) -> None:
        # Esc najprv vycisti hladanie, az druhy zavrie okno.
        if event.key() == Qt.Key.Key_Escape and self._hladaj.text():
            self._hladaj.clear()
            return
        super().keyPressEvent(event)

    # ── akcie ─────────────────────────────────────────────────────────────────
    def _otvor(self, kam: str) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        # Viac riadkov naraz otvori viac zaloziek — pri vypocuvani noviniek je
        # to bezne, tak sa to nezakazuje.
        for album in self._vybrane():
            odkaz = {"youtube": album.youtube_odkaz,
                     "bandcamp": album.bandcamp,
                     "ma": album.ma}.get(kam, "")
            if odkaz:
                QDesktopServices.openUrl(QUrl(odkaz))

    def _nastav(self, stav: str) -> None:
        vybrane = self._vybrane()
        kluce = [a.kluc for a in vybrane if self._zoznam.stav(a.kluc) != stav]
        if not kluce:
            return
        # Udaje albumu idu do logu s nim — viď `novinky.Zoznam.snimky`.
        self._oznac(kluce, stav, {a.kluc: a for a in vybrane})
        self._zoznam.nastav(kluce, stav)
        self._napln()


class MainWindow(QMainWindow):
    _cover_ready = Signal(object, str)
    _lyrics_ready = Signal(str, str)       # (lyrics_text, track_path)
    # (translator.Preklad, track_path, title). Titul ide signálom spolu s cestou
    # zámerne: bez neho by sa preklad dal uložiť len tej skladbe, ktorá práve
    # hrá, a preklad dokončený po preskočení inam by sa zahodil aj s kvótou,
    # ktorú stál.
    _translation_ready = Signal(object, str, str)
    _metadata_ready = Signal(dict, str)    # (metadata_dict, track_path)
    _durations_ready = Signal()
    _downloads_progress = Signal(str)      # priebezny stav rozbalovania
    _downloads_done = Signal(object)       # ImportResult alebo None pri chybe
    # (Manifest | None, ci sa ma ozvat aj ked nic nove nie je). Kontrola bezi
    # vo vlakne, dialog musi vzniknut na hlavnom — signal to prehodi spat.
    # (manifest | None, ci to bola rucna kontrola, ci server odpovedal)
    _update_checked = Signal(object, bool, bool)
    # (zaloha_playlistu.Vysledok, ci sa ma ozvat aj ked sa nic nezapisalo).
    # Zapis na NAS bezi rovnako vo vlakne, hlaska patri hlavnemu.
    _zaloha_hotova = Signal(object, bool)
    # (novinky.Zoznam | None, ci sa ma otvorit okno). Zoznam sa cita zo
    # sietoveho disku, takze vo vlakne — okno musi ostat ovladatelne.
    _novinky_nacitane = Signal(object, bool)

    def __init__(
        self,
        controller: PlayerController,
        state_store: StateStore,
        *,
        api_url: str,
        autostart_enabled: bool,
        playlist_visible: bool,
        window_width: int,
        full_height: int,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.state_store = state_store
        self.api_url = api_url
        self._allow_close = False
        self._tray_message_shown = False
        self._is_seeking = False
        self._current_duration_ms = 0
        self._bg_pixmap: QPixmap | None = None
        # Posledny nacitany zoznam noviniek. `None` = este sa nedotiahol.
        self._novinky = None
        # Kolkokrat uz ticha kontrola verzie marne siahla na nedostupny NAS.
        # Viac o tom pri ODLOZENE_KONTROLY.
        self._update_pokusov = 0
        self._playlist_visible = playlist_visible
        self._full_height = max(full_height, _FULL_HEIGHT_DEFAULT)

        self.setWindowTitle("Metal Music Player")
        self.setMinimumWidth(480)
        self.setAcceptDrops(True)
        self.setStyleSheet(_STYLESHEET)

        self._build_ui(autostart_enabled)
        self._setup_tray()
        self._connect_signals()
        self._update_compact_now_playing(self.controller.current_track())
        self._update_duration(self.controller.player.duration())
        self._update_playback_position(self.controller.player.position())
        self._update_playback_state(self.controller.playback_state_name())

        # Apply initial size + playlist visibility
        if playlist_visible:
            self.resize(window_width, self._full_height)
            self.playlist_panel.show()
        else:
            self.playlist_panel.hide()
            for b in self._toolbar_buttons:
                b.hide()
            QTimer.singleShot(0, self._shrink_to_strip)

        # Ticha kontrola novej verzie na NAS-e. Az po starte, nech to nezdrzi
        # okno ani prve prehratie — kontrola je citanie zo sietoveho disku a
        # ked NAS nie je doma dostupny, trva to niekolko sekund.
        QTimer.singleShot(5000, lambda: self._skontroluj_aktualizaciu(hlasne=False))

        # Zaloha playlistu na NAS. Este o kusok neskor nez kontrola verzie:
        # ked je na NAS-e novsia verzia, appka sa o chvilu ukoncuje a
        # zalohovat playlist tesne pred tym netreba — pri dalsom starte sa
        # sam odlozi. Zaloha je zapis, kontrola verzie iba citanie, takze
        # v opacnom poradi by sa aj zbytocne stretli na tom istom share-i.
        QTimer.singleShot(9000, lambda: self._zalohuj_playlist(hlasne=False))

        # Novinky zo skenu az na koniec: je to tretie citanie z toho isteho
        # sietoveho disku a cislo v tlacidle nikam nehori.
        QTimer.singleShot(12000, lambda: self._nacitaj_novinky(hlasne=False))

    # ── persistence ────────────────────────────────────────────────────────────
    def save_state(self) -> None:
        state = self.controller.build_state(
            start_with_windows=self.autostart_checkbox.isChecked(),
            window_width=self.width(),
            window_height=self.height(),
            playlist_window_width=self.width(),
            playlist_window_height=self._full_height,
            playlist_window_visible=self._playlist_visible,
        )
        self.state_store.save(state)

    # ── window events ──────────────────────────────────────────────────────────
    def closeEvent(self, event) -> None:
        if self._allow_close or not QSystemTrayIcon.isSystemTrayAvailable():
            # Zavretie okna je pri vypnutom tray-i skutocne ukoncenie, takze
            # spankove zoznamy treba vratit este pred ulozenim stavu.
            self.controller.restore_spanok_lists()
            self.save_state()
            return super().closeEvent(event)
        event.ignore()
        self.save_state()
        self.hide()
        if not self._tray_message_shown:
            self.tray_icon.showMessage(
                "Metal Music Player",
                "Aplikácia beží ďalej v system tray.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
            self._tray_message_shown = True

    def changeEvent(self, event) -> None:
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.tray_icon.isVisible()
        ):
            self.save_state()
            QTimer.singleShot(0, self.hide)
        super().changeEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._extract_local_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._extract_local_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        # Determine insert position from drop location on the playlist widget.
        drop_pos = self.playlist_widget.mapFrom(self, event.position().toPoint())
        target_item = self.playlist_widget.itemAt(drop_pos)
        insert_at: int | None = None
        if target_item is not None:
            insert_at = self.playlist_widget.row(target_item)
        self._ingest_paths(paths, source_label="Presunuté položky", insert_at=insert_at)
        event.acceptProposedAction()

    # ── build UI ───────────────────────────────────────────────────────────────
    def _build_ui(self, autostart_enabled: bool) -> None:
        central = _BackgroundWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── compact player strip ─────────────────────────────────────────────
        player_strip = QWidget()
        self._player_strip = player_strip
        player_strip.setStyleSheet("background: rgba(30, 26, 22, 100);")
        player_strip.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        strip_layout = QVBoxLayout(player_strip)
        strip_layout.setContentsMargins(8, 0, 8, 0)
        strip_layout.setSpacing(0)

        # Row 1: track info + state/time
        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 0, 0, 0)
        info_row.setSpacing(0)
        self.info_label = QLabel("Nič nehrá")
        self.info_label.setStyleSheet(
            f"background: transparent; color: {_C_TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
        )
        self.info_label.setWordWrap(False)
        info_row.addWidget(self.info_label, 1)

        self.state_label = QLabel("●  zastavené")
        self.state_label.setStyleSheet(f"background: transparent; color: {_C_TEXT_SECONDARY}; font-size: 11px;")
        info_row.addWidget(self.state_label)

        self.position_label = QLabel("00:00 / 00:00")
        self.position_label.setStyleSheet(
            f"background: transparent; color: {_C_TEXT_SECONDARY}; font-size: 11px; margin-left: 6px;"
        )
        info_row.addWidget(self.position_label)
        strip_layout.addLayout(info_row)

        # Row 2: seek slider
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setSingleStep(1000)
        self.seek_slider.setPageStep(5000)
        self.seek_slider.setEnabled(False)
        self.seek_slider.setFixedHeight(14)
        strip_layout.addWidget(self.seek_slider)

        # Row 3: controls
        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 0)
        ctrl.setSpacing(3)

        sp = self.style()
        self.prev_button = QPushButton(sp.standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward), "")
        self.play_button = QPushButton(sp.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "")
        self.stop_button = QPushButton(sp.standardIcon(QStyle.StandardPixmap.SP_MediaStop), "")
        self.next_button = QPushButton(sp.standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward), "")

        _transport_style = (
            "background: #9a8878; border: 1px solid #b8a898; border-radius: 4px;"
        )
        self.prev_button.setToolTip("Predchádzajúca skladba")
        self.play_button.setToolTip("Prehrať / Pauza")
        self.stop_button.setToolTip("Zastaviť")
        self.next_button.setToolTip("Nasledujúca skladba")
        for b in (self.prev_button, self.play_button, self.stop_button, self.next_button):
            b.setFixedSize(30, 24)
            b.setIconSize(b.size() * 0.6)
            b.setStyleSheet(_transport_style)

        ctrl.addWidget(self.prev_button)
        ctrl.addWidget(self.play_button)
        ctrl.addWidget(self.stop_button)
        ctrl.addWidget(self.next_button)
        ctrl.addSpacing(6)

        # Volume
        self._muted = False
        self._pre_mute_volume = 75
        self.mute_button = QPushButton("🔊")
        self.mute_button.setFixedSize(24, 24)
        self.mute_button.setToolTip("Stlmiť / Zapnúť zvuk")
        self.mute_button.setStyleSheet("border: none; background: transparent; font-size: 13px; padding: 0;")
        ctrl.addWidget(self.mute_button)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.controller.snapshot().get("volume", 75))
        self.volume_slider.setFixedWidth(80)
        ctrl.addWidget(self.volume_slider)
        ctrl.addSpacing(6)
        ctrl.addStretch(1)

        # Playlist toggle
        self.playlist_toggle_button = QPushButton("☰")
        self.playlist_toggle_button.setFixedSize(24, 24)
        self.playlist_toggle_button.setToolTip("Menu")
        ctrl.addWidget(self.playlist_toggle_button)

        strip_layout.addLayout(ctrl)

        # Playlist toolbar — inside player_strip so no gap
        pl_bar = QHBoxLayout()
        pl_bar.setContentsMargins(0, 0, 0, 0)
        pl_bar.setSpacing(4)
        self.add_button = QPushButton("+ Súbory")
        self.add_folder_button = QPushButton("+ Priečinok")
        self.remove_button = QPushButton("Odstrániť")
        self.clear_button = QPushButton("Vymazať playlist")
        self.save_m3u_button = QPushButton("Uložiť M3U")
        self.save_m3u_button.setToolTip("Uložiť playlist ako M3U súbor")
        self.load_m3u_button = QPushButton("Načítať M3U")
        self.load_m3u_button.setToolTip("Načítať playlist z M3U súboru")
        self.goto_current_button = QPushButton("⏵ Aktuálna")
        self.goto_current_button.setToolTip("Skok na práve hrajúcu skladbu")
        self.sleep_jump_button = QPushButton("😴 Spánok")
        self.sleep_jump_button.setToolTip(
            "Pridá na koniec playlistu skladby zo svojho zoznamu a hneď ich pustí —\n"
            "po dohratí sa PC vypne/uspí podľa nastavenia nižšie.\n"
            "Keď už na konci playlistu sú, nepridá nič a len ich pustí.\n"
            "Prázdny zoznam = pôvodné správanie, skok na tretiu skladbu od konca.\n"
            "Pravý klik = úprava zoznamu skladieb"
        )
        self.sleep_jump_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sleep2_button = QPushButton("💕 Spánok 2")
        self.sleep2_button.setToolTip(
            "To isté, len z druhého zoznamu — na spoločný večer.\n"
            "Po dohratí sa PC vypne/uspí podľa nastavenia nižšie.\n"
            "Pravý klik = úprava zoznamu skladieb"
        )
        self.sleep2_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.zalozky_button = QPushButton("🔖 Záložky")
        self.zalozky_button.setToolTip(
            "Skladby, od ktorých sa dá jedným klikom začať hrať.\n"
            "Vyber záložku a hrá sa od nej ďalej, kým to nezastavíš\n"
            "alebo kým playlist nedohrá. Nič sa nepridáva, záložka ostáva.\n"
            "Záložku dáš pravým klikom na skladbu v playliste."
        )
        self.downloads_button = QPushButton("📦 Z Downloads")
        from music_player.downloads_import import target_dir
        self.downloads_button.setToolTip(
            "Nájde v priečinku Downloads všetky rar/zip/7z archívy s hudbou,\n"
            f"rozbalí ich do {target_dir()} a priečinok otvorí.\n"
            "Už existujúce albumy sa preskočia, archívy sa nemažú.\n"
            "Cieľ sa dá zmeniť cez MP3_TARGET v config.txt."
        )
        self.novinky_button = QPushButton("🆕 Novinky")
        self.novinky_button.setToolTip(
            "Nové metalové albumy z piatkového skenu (metal-novinky).\n"
            "Album, ktorý si už vypočul, sa dá odškrtnúť a zo zoznamu zmizne.\n"
            "Odškrtnutie platí na oboch notebookoch — ukladá sa na NAS."
        )
        self.statistika_button = QPushButton("📊 Štatistika")
        self.statistika_button.setToolTip(
            "Čo si koľkokrat počúval — skladby, interpreti, albumy a história.\n"
            "Prehratie sa počíta po 30 s (pri krátkych po 30 % skladby)."
        )
        self.export_button = QPushButton("Export")
        self.export_button.setToolTip("Exportovať nastavenia")
        self.import_button = QPushButton("Import")
        self.import_button.setToolTip("Importovať nastavenia")
        self.help_button = QPushButton("?")
        self.help_button.setToolTip("Nápoveda")
        self.help_button.setFixedWidth(28)
        self._toolbar_buttons = [self.add_button, self.add_folder_button, self.remove_button, self.clear_button, self.save_m3u_button, self.load_m3u_button, self.goto_current_button, self.sleep_jump_button, self.sleep2_button, self.zalozky_button, self.downloads_button, self.novinky_button, self.statistika_button, self.export_button, self.import_button, self.help_button]
        for b in self._toolbar_buttons:
            pl_bar.addWidget(b)
        pl_bar.addStretch(1)
        strip_layout.addLayout(pl_bar)
        root.addWidget(player_strip)

        # ── playlist panel (collapsible) ─────────────────────────────────────
        self.playlist_panel = QWidget()
        panel_layout = QVBoxLayout(self.playlist_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: playlist
        pl_group = QGroupBox("Playlist")
        pl_layout = QVBoxLayout(pl_group)
        pl_layout.setContentsMargins(6, 2, 6, 6)
        # Search bar (hidden by default, Ctrl+F to show)
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("Hľadať...")
        self._search_bar.setStyleSheet(
            "QLineEdit { background: #1e1a16; color: #f5ead1; border: 1px solid #d4860a;"
            " padding: 3px 6px; font-size: 13px; }"
        )
        self._search_bar.hide()
        self._search_bar.textChanged.connect(self._on_search_text_changed)
        self._search_bar.returnPressed.connect(self._on_search_next)
        self._search_match_index = -1
        self._search_matches: list[int] = []
        pl_layout.addWidget(self._search_bar)

        self.playlist_widget = _ReorderablePlaylist()
        self.playlist_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.playlist_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.playlist_widget.setItemDelegate(_PlaylistDelegate(self.playlist_widget))
        pl_layout.addWidget(self.playlist_widget)
        splitter.addWidget(pl_group)

        # Right: album art + track info + lyrics
        info_panel = QWidget()
        info_panel_layout = QVBoxLayout(info_panel)
        info_panel_layout.setContentsMargins(8, 8, 8, 8)
        info_panel_layout.setSpacing(6)

        # Metal Archives link
        self.ma_link_label = QLabel("")
        self.ma_link_label.setStyleSheet(f"font-size: 11px; padding: 2px 0;")
        self.ma_link_label.setOpenExternalLinks(True)
        self.ma_link_label.setTextFormat(Qt.TextFormat.RichText)
        info_panel_layout.addWidget(self.ma_link_label)

        # Album art — fills available space
        self.cover_label = QLabel()
        self.cover_label.setMinimumSize(200, 200)
        self.cover_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet(
            f"background: {_C_BG_HEADER}; border: 1px solid {_C_BORDER}; border-radius: 6px;"
        )
        self._cover_raw_data: bytes | None = None
        self._show_placeholder_cover()
        info_panel_layout.addWidget(self.cover_label, 1)


        self.lyrics_edit = LyricsEdit()
        self.lyrics_edit.setPlaceholderText("Texty piesní …")
        self.lyrics_edit._show_tooltip.connect(self.lyrics_edit._on_show_tooltip)
        self.lyrics_edit.setMinimumHeight(80)
        info_panel_layout.addWidget(self.lyrics_edit, 1)

        # Preklad celého textu — na rozdiel od prekladu slova pri prechode myšou
        # sa nespúšťa sám: jedna skladba stojí z mesačnej kvóty DeepL asi 2 000
        # znakov z 500 000, takže o tom rozhoduje klik, nie prehratie skladby.
        self.translate_button = QPushButton("🌐 Preložiť text")
        self.translate_button.setEnabled(False)
        self.translate_button.clicked.connect(self._on_translate_clicked)
        # Texty sa inak hľadajú z pamäte a disku a „nenašlo sa“ platí deň
        # (nový album) až mesiac — tlačidlo sa spýta Metal Archives hneď.
        self.reload_lyrics_button = QPushButton("🔄 Načítať texty")
        self.reload_lyrics_button.setToolTip(
            "Hľadá text tejto skladby na Metal Archives hneď, bez ohľadu na to,\n"
            "čo si prehrávač pamätá. Ostatné skladby albumu sa spýtajú pri prehratí.")
        self.reload_lyrics_button.clicked.connect(self._on_reload_lyrics_clicked)
        lyrics_buttons = QHBoxLayout()
        lyrics_buttons.addWidget(self.translate_button, 1)
        lyrics_buttons.addWidget(self.reload_lyrics_button)
        info_panel_layout.addLayout(lyrics_buttons)

        splitter.addWidget(info_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        panel_layout.addWidget(splitter, 1)

        # Footer
        footer = QWidget()
        footer.setStyleSheet("background: rgba(30, 26, 22, 100);")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(8, 3, 8, 3)
        footer_layout.setSpacing(2)

        settings_row = QHBoxLayout()
        self.autostart_checkbox = QCheckBox("Spúšťať s Windows")
        self.autostart_checkbox.setChecked(autostart_enabled)
        self.shutdown_checkbox = QCheckBox("Vypnúť PC po skončení")
        self.shutdown_checkbox.setChecked(self.controller.shutdown_when_playlist_ends)
        self.sleep_checkbox = QCheckBox("Spať po skončení")
        self.sleep_checkbox.setChecked(self.controller.sleep_when_playlist_ends)

        self.scheduled_action_combo = QComboBox()
        self.scheduled_action_combo.addItems(["Žiadna akcia", "Uspať o", "Vypnúť o"])
        self.scheduled_action_combo.setToolTip(
            "Časovač — uspí alebo vypne PC o zadanom čase (formát hodiny:minúty)"
        )
        _action_index = {"none": 0, "sleep": 1, "shutdown": 2}.get(self.controller.scheduled_action, 0)
        self.scheduled_action_combo.setCurrentIndex(_action_index)

        self.scheduled_time_edit = QTimeEdit()
        self.scheduled_time_edit.setDisplayFormat("HH:mm")
        self.scheduled_time_edit.setToolTip(
            "Čas vo formáte hodiny:minúty (HH:MM).\n"
            "Ak je čas skorší ako teraz, akcia sa vykoná zajtra."
        )
        if self.controller._is_valid_time(self.controller.scheduled_time):
            _t = self.controller.scheduled_time.split(":")
            self.scheduled_time_edit.setTime(QTime(int(_t[0]), int(_t[1])))
        else:
            _now = QTime.currentTime()
            self.scheduled_time_edit.setTime(QTime((_now.hour() + 1) % 24, 0))
        self.scheduled_time_edit.setVisible(_action_index != 0)

        self.scheduled_hint_label = QLabel("")
        self.scheduled_hint_label.setStyleSheet("color: #a89070; font-size: 11px;")
        self.scheduled_hint_label.setVisible(_action_index != 0)
        self._update_scheduled_time_hint()

        settings_row.addWidget(self.autostart_checkbox)
        settings_row.addWidget(self.shutdown_checkbox)
        settings_row.addWidget(self.sleep_checkbox)
        settings_row.addWidget(self.scheduled_action_combo)
        settings_row.addWidget(self.scheduled_time_edit)
        settings_row.addWidget(self.scheduled_hint_label)
        settings_row.addStretch(1)
        footer_layout.addLayout(settings_row)

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("lbl_stats")
        self.stats_label.setStyleSheet("color: #a89070; font-size: 11px;")
        footer_layout.addWidget(self.stats_label)

        self.stream_label = QLabel("")
        self.stream_label.setObjectName("lbl_stream")
        self.stream_label.setWordWrap(True)
        self.status_message_label = QLabel("Pretiahni súbory alebo priečinok.")
        self.status_message_label.setObjectName("lbl_status")
        self.status_message_label.setWordWrap(True)
        footer_layout.addWidget(self.stream_label)
        footer_layout.addWidget(self.status_message_label)
        panel_layout.addWidget(footer)

        root.addWidget(self.playlist_panel, 1)
        self.setCentralWidget(central)
        self.setContentsMargins(0, 0, 0, 0)
        self.centralWidget().setContentsMargins(0, 0, 0, 0)

    # ── tray ───────────────────────────────────────────────────────────────────
    def _setup_tray(self) -> None:
        icon_path = Path(__file__).parent / "icon.ico"
        if icon_path.exists():
            from PySide6.QtGui import QIcon
            app_icon = QIcon(str(icon_path))
            self.setWindowIcon(app_icon)
            tray_icon = app_icon
        else:
            tray_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.tray_icon = QSystemTrayIcon(tray_icon, self)
        tray_menu = QMenu(self)
        tray_menu.setStyleSheet(
            "QMenu { background: #1e1a16; border: 1px solid #3d3025; }"
            "QMenu::item { color: #f5ead1; padding: 4px 20px; }"
            "QMenu::item:selected { background: #d4860a; color: #1e1a16; }"
            "QMenu::separator { height: 1px; background: #3d3025; margin: 2px 6px; }"
        )
        self.show_action = QAction("Zobraziť", self)
        self.play_pause_action = QAction("Play / Pause", self)
        self.next_action = QAction("Ďalšia", self)
        self.retry_audio_action = QAction("Obnoviť audio", self)
        self.aktualizacia_action = QAction("Skontrolovať aktualizáciu", self)
        self.aktualizacia_action.triggered.connect(
            lambda: self._skontroluj_aktualizaciu(hlasne=True))
        self.quit_action = QAction("Koniec", self)
        tray_menu.addAction(self.show_action)
        tray_menu.addAction(self.play_pause_action)
        tray_menu.addAction(self.next_action)
        tray_menu.addAction(self.retry_audio_action)
        tray_menu.addSeparator()
        tray_menu.addAction(self.aktualizacia_action)
        tray_menu.addSeparator()
        tray_menu.addAction(self.quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.setToolTip("Metal Music Player")
        self.tray_icon.show()

    # ── signals ────────────────────────────────────────────────────────────────
    def _connect_signals(self) -> None:
        # Transport
        self.prev_button.clicked.connect(self.controller.previous_track)
        self.play_button.clicked.connect(self._toggle_playback_from_ui)
        self.stop_button.clicked.connect(self.controller.stop)
        self.next_button.clicked.connect(self.controller.next_track)

        # Volume
        self.volume_slider.valueChanged.connect(self.controller.set_volume)
        self.volume_slider.valueChanged.connect(self._update_mute_icon)
        self.mute_button.clicked.connect(self._toggle_mute)

        # Seek
        self.seek_slider.sliderPressed.connect(self._start_seeking)
        self.seek_slider.sliderMoved.connect(self._preview_seek_position)
        self.seek_slider.sliderReleased.connect(self._commit_seek)

        # Playlist toggle
        self.playlist_toggle_button.clicked.connect(self._toggle_playlist_panel)

        # Playlist toolbar
        self.add_button.clicked.connect(self._add_files)
        self.add_folder_button.clicked.connect(self._add_folder)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_playlist)
        self.save_m3u_button.clicked.connect(self._save_playlist_m3u)
        self.load_m3u_button.clicked.connect(self._load_playlist_m3u)
        self.goto_current_button.clicked.connect(self._goto_current_track)
        self.sleep_jump_button.clicked.connect(lambda: self._start_spanok(SPANOK))
        self.sleep_jump_button.customContextMenuRequested.connect(
            lambda _pos: self._edit_spanok_list(SPANOK)
        )
        self.sleep2_button.clicked.connect(lambda: self._start_spanok(SPANOK2))
        self.sleep2_button.customContextMenuRequested.connect(
            lambda _pos: self._edit_spanok_list(SPANOK2)
        )
        self.zalozky_button.clicked.connect(self._ukaz_zalozky)
        self.controller.zalozky_changed.connect(self._oznac_zalozky)
        self.downloads_button.clicked.connect(self._import_from_downloads)
        self.novinky_button.clicked.connect(lambda: self._nacitaj_novinky(hlasne=True))
        self.statistika_button.clicked.connect(self._ukaz_statistiku)
        self.export_button.clicked.connect(self._export_settings)
        self.import_button.clicked.connect(self._import_settings)
        self.help_button.clicked.connect(self._show_help)
        self._durations_ready.connect(self._update_durations_in_list)

        self.playlist_widget.itemDoubleClicked.connect(self._play_selected_item)
        self.playlist_widget.rows_moved.connect(self._on_playlist_rows_moved)
        self.playlist_widget.external_drop.connect(self._on_external_drop)
        self.playlist_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(self._show_playlist_context_menu)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.playlist_widget, self._remove_selected)
        QShortcut(QKeySequence("Ctrl+F"), self, self._toggle_search)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self._search_bar, self._close_search)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, self._seek_forward_5s)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, self._seek_backward_5s)

        # Settings
        self.autostart_checkbox.toggled.connect(self._toggle_autostart)
        self.shutdown_checkbox.toggled.connect(self._toggle_shutdown)
        self.sleep_checkbox.toggled.connect(self._toggle_sleep)
        self.scheduled_action_combo.currentIndexChanged.connect(self._on_scheduled_action_changed)
        self.scheduled_time_edit.timeChanged.connect(self._on_scheduled_time_changed)
        self.controller.scheduled_status_changed.connect(self._on_scheduled_status_changed)

        # Controller signals
        self.controller.current_track_changed.connect(self._update_compact_now_playing)
        self.controller.current_track_changed.connect(self._update_now_playing)
        self.controller.playback_state_changed.connect(self._update_playback_state)
        self.controller.position_changed.connect(self._update_playback_position)
        self.controller.duration_changed.connect(self._update_duration)
        self.controller.volume_changed.connect(self.volume_slider.setValue)
        self.controller.playlist_changed.connect(self._refresh_playlist)
        self.controller.playlist_changed.connect(self._update_stats)
        self.controller.playback_state_changed.connect(lambda _: self._update_stats())
        self.playlist_widget.itemSelectionChanged.connect(self._update_stats)
        self.controller.message_emitted.connect(self._show_message)
        # Navrat playlistu po "Spanok 2" sa uklada hned — po nom nasleduje
        # uspanie/vypnutie a na ulozenie pri zatvarani okna sa spoliehat neda.
        self.controller.playlist_restored.connect(self.save_state)

        # Update stats every 10s so listen time ticks in real-time
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(10_000)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start()
        self.controller.stream_state_changed.connect(self._refresh_stream_status)

        # Tray
        self.show_action.triggered.connect(self._restore_from_tray)
        self.play_pause_action.triggered.connect(self._toggle_playback_from_ui)
        self.next_action.triggered.connect(self.controller.next_track)
        self.retry_audio_action.triggered.connect(self._retry_audio)
        self.quit_action.triggered.connect(self._quit_from_tray)
        self.tray_icon.activated.connect(self._handle_tray_activated)

        # Async signals
        self._cover_ready.connect(self._on_cover_loaded)
        self._lyrics_ready.connect(self._on_lyrics_loaded)
        self._translation_ready.connect(self._on_translation_loaded)
        self._metadata_ready.connect(self._on_metadata_loaded)
        self._downloads_progress.connect(self._show_message)
        self._downloads_done.connect(self._on_downloads_imported)
        self._update_checked.connect(self._on_update_checked)
        self._novinky_nacitane.connect(self._on_novinky_nacitane)
        self._zaloha_hotova.connect(self._on_zaloha_hotova)

        # Refresh playlist now
        self._refresh_playlist()
        self._update_now_playing(self.controller.current_track())
        self._refresh_stream_status()
        self._select_current_playlist_row()

    # ── playlist toggle ────────────────────────────────────────────────────────
    def _show_help(self) -> None:
        from music_player.downloads_import import target_dir
        from music_player.self_update import LOG as update_log, popis_lokalnej_verzie
        from music_player.self_update import zdroj as _update_zdroj
        from music_player import zaloha_playlistu

        update_zdroj = _update_zdroj()
        zaloha_priecinok = zaloha_playlistu.priecinok()

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Metal Music Player v{__version__} — Nápoveda")
        dlg.setMinimumSize(520, 500)
        dlg.setStyleSheet(
            "QDialog { background: #1e1a16; }"
            "QLabel { color: #f5ead1; }"
            "QTextEdit { background: #2a2520; color: #f5ead1; border: none; font-size: 13px; }"
        )
        layout = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml(f"""
<h2 style="color: #d4860a;">Metal Music Player <span style="font-size: 14px; color: #a89070;">v{__version__} ({__version_code__})</span></h2>

<h3 style="color: #d4860a;">Prehrávanie</h3>
<ul>
<li><b>Play / Pause / Stop / Prev / Next</b> — ovládacie tlačidlá</li>
<li><b>Ctrl+Alt+Y</b> — globálna klávesová skratka na Play/Pause (funguje aj keď appka nie je v popredí)</li>
<li><b>Gapless playback</b> — ďalšia skladba sa predpripraví a spustí tesne pred koncom aktuálnej, minimálna medzera</li>
<li><b>ReplayGain</b> — automatická normalizácia hlasitosti (ak majú skladby ReplayGain tagy)</li>
<li><b>Seek slider</b> — klikni alebo ťahaj pre presun v skladbe</li>
<li><b>Šípka doľava / doprava</b> — posun o 5 sekúnd dozadu / dopredu</li>
<li><b>Volume slider</b> — hlasitosť prehrávania</li>
</ul>

<h3 style="color: #d4860a;">Playlist</h3>
<ul>
<li><b>+ Súbory / + Priečinok</b> — pridanie skladieb do playlistu</li>
<li><b>Drag & Drop</b> — pretiahni súbory/priečinky z Prieskumníka priamo do appky</li>
<li><b>Drag & Drop v playliste</b> — presuň skladby ťahaním na inú pozíciu</li>
<li><b>Dvojklik</b> — prehrá vybranú skladbu</li>
<li><b>Delete</b> — vymaže označené skladby z playlistu</li>
<li><b>Odstrániť</b> — vymaže označené skladby</li>
<li><b>Vymazať playlist</b> — vymaže celý playlist</li>
<li><b>Uložiť M3U</b> — exportuje playlist ako M3U súbor</li>
<li><b>Načítať M3U</b> — importuje playlist z M3U/M3U8 súboru</li>
<li><b>⏵ Aktuálna</b> — scrollne na práve hrajúcu skladbu</li>
<li><b>😴 Spánok</b> a <b>💕 Spánok 2</b> — dve tlačidlá, ktoré robia to isté, len každé zo svojho zoznamu: skladby z neho pridajú na koniec playlistu a hneď ich pustia, takže dohrajú už len ony a v kombinácii s <b>Vypnúť PC po skončení</b> alebo <b>Spať po skončení</b> sa potom PC vypne/uspí. <b>Spánok</b> je tvoj zoznam, <b>Spánok 2</b> spoločný.</li>
<li>Keď už na konci playlistu presne tie skladby sú, <b>nepridá sa nič</b> — len sa na ne skočí a playlist ostane, aký bol. Tlačidlo sa teda dá stláčať hoci každý večer a playlist z toho nenarastie.</li>
<li>Zoznam upravíš <b>pravým klikom na tlačidlo</b>, alebo pravým klikom na skladbu v playliste → <b>Pridať do „Spánok“ / „Spánok 2“</b>. Ukladajú sa do <b>spanok.m3u</b> a <b>spanok2.m3u</b> vedľa <b>config.txt</b>, takže sa dajú editovať aj rukou v poznámkovom bloku; koľko skladieb je v zozname, toľko sa prehrá. Inú cestu nastavíš cez <b>SPANOK_PLAYLIST</b> / <b>SPANOK2_PLAYLIST</b> v <b>config.txt</b>.</li>
<li>Pridané skladby sa pri <b>ukončení prehrávača</b> z playlistu zase vyhodia — ostane presne to, čo tam bolo predtým. Uspanie ani vypnutie PC ukončenie nie je, po zobudení sú stále tam. Zmeníš to prepínačom <b>Nechať skladby v playliste aj po ukončení prehrávača</b> v dialógu zoznamu (v <b>config.txt</b> riadok <b>SPANOK_NECHAT_V_PLAYLISTE</b> / <b>SPANOK2_NECHAT_V_PLAYLISTE</b> = ano / nie).</li>
<li>Keď je <b>spanok.m3u</b> prázdny, tlačidlo <b>Spánok</b> sa správa po starom: preskočí na tretiu skladbu od konca playlistu.</li>
<li><b>🔖 Záložky</b> — skladby, od ktorých sa dá jedným klikom začať hrať. Klik na tlačidlo ukáže zoznam záložiek v poradí playlistu; vybraná skladba sa pustí a hrá sa od nej ďalej, kým to nezastavíš alebo kým playlist nedohrá (vtedy platí <b>Vypnúť PC po skončení</b> / <b>Spať po skončení</b> ako vždy). Na rozdiel od Spánku sa do playlistu <b>nič nepridáva</b> a záložka po prehratí ostáva, kde bola. Záložku dáš pravým klikom na skladbu → <b>🔖 Pridať záložku</b> alebo v menu tlačidla (vezme označenú skladbu); v playliste ju spoznáš podľa 🔖 pred názvom. Záložka ide so skladbou, keď ju v playliste presunieš; keď skladbu z playlistu odstrániš, záložka ostane a v menu sa ukáže ako chýbajúca. Záložky sú pre každý notebook vlastné, ako playlist.</li>
<li><b>📦 Z Downloads</b> — nájde v priečinku Downloads všetky rar/zip/7z archívy, ktoré obsahujú hudbu, rozbalí ich do <b>{target_dir()}</b> (rok sa mení sám, každý album do vlastného podpriečinka) a ten priečinok otvorí. Priečinok albumu sa pomenuje <b>Interpret - Album - Rok</b> — názvy typu <i>Dark Plague`2026`Masquerade by necroscum</i> sa upracú samy. Keď sa z názvu nedá vyčítať, kde končí kapela a začína album, prehrávač sa opýta zoznamu noviniek a potom <b>Metal Archives</b> — odtiaľ berie aj správny zápis (<i>Behemoth - I, Scvlptor</i>, <i>Boötes Void</i>). Keď sa zhoda nenájde, názov sa nechá tak, ako prišiel; netipuje sa. Vypína sa <b>NAZVY_MA=nie</b> v <b>config.txt</b>. Na záver vypíše prehľad — ktoré albumy pribudli a s koľkými skladbami, ktoré sa preskočili, lebo tam už boli, a ktoré sa nepodarilo rozbaliť. Archívy v Downloads nechá tak. Cieľ zmeníš cez <b>MP3_TARGET</b> v <b>config.txt</b></li>
<li><b>🆕 Novinky</b> — nové metalové albumy zo skenu <b>metal-novinky</b>. Číslo v tlačidle je počet tých, ktoré si ešte neodškrtol. Okno má dve záložky: <b>Tento týždeň</b> (čo vychádza od pondelka do nedele, aj keď to sken našiel o týždeň skôr) a <b>Už vydané</b> (albumy, ktoré na Metal Archives pribudli až po svojom vydaní — inak by ti ušli). V oboch sú albumy zoradené podľa dňa vydania a v rámci dňa podľa abecedy. Pri každom je štýl, dátum vydania a odkazy na <b>YouTube</b>, <b>Bandcamp</b> a <b>Metal Archives</b> (dvojklik na riadok otvorí YouTube). Tlačidlom <b>✓ Skontrolované</b> album zo zoznamu zmizne — ale nezmaže sa: zaškrtávadlo <b>Zobraziť aj skontrolované</b> ho vráti a dá sa vrátiť aj medzi nové. Odškrtnutie sa ukladá na NAS, takže platí na oboch notebookoch. Pod čiarou sú albumy, s ktorými si filter žánrov nevedel rady — tie ešte treba posúdiť ručne. Keď album stiahneš a rozbalíš cez <b>📦 Z Downloads</b>, odškrtne sa sám. Vypína sa cez <b>NOVINKY=nie</b> v <b>config.txt</b></li>
<li><b>Ctrl+F</b> — vyhľadávanie v playliste, Enter = ďalší výskyt, Escape = zatvoriť</li>
<li><b>Pravý klik</b> — kontextové menu (metadáta, záložka, pridať do „Spánok“ / „Spánok 2“, odstrániť)</li>
</ul>

<h3 style="color: #d4860a;">Metadáta a Metal Archives</h3>
<ul>
<li><b>Pravý klik → Zobraziť metadáta</b> — zobrazí a umožní editovať MP3 tagy (názov, interpret, album, žáner, track č., disk č., skladateľ, komentár...)</li>
<li><b>Metal Archives</b> — automaticky vyhľadá album na metal-archives.com a zobrazí link</li>
<li><b>Cover</b> — automaticky stiahne a zobrazí obal albumu</li>
<li><b>Texty piesní</b> — automaticky vyhľadá a zobrazí texty</li>
<li><b>Pozadie</b> — rozmazaný obal albumu ako pozadie appky</li>
</ul>

<h3 style="color: #d4860a;">LAN Streaming</h3>
<ul>
<li><b>Automatický stream</b> — pri prehrávaní sa sprístupní HTTP stream pre Android appku</li>
<li><b>Adaptívny bitrate</b> — stream sa prispôsobí kvalite zdrojového súboru (max 160 kbps)</li>
<li><b>UDP beacon</b> — Android appka automaticky nájde prehrávač v sieti</li>
</ul>

<h3 style="color: #d4860a;">Nastavenia</h3>
<ul>
<li><b>Spúšťať s Windows</b> — automatický štart pri spustení systému</li>
<li><b>Vypnúť PC po skončení</b> — vypne počítač keď dohrá playlist</li>
<li><b>Spať po skončení</b> — uspí počítač keď dohrá playlist (vzájomne vylúčené s vypnutím)</li>
<li><b>Uspať o / Vypnúť o</b> — časovač: uspí alebo vypne PC o zadanom čase. Čas je vo formáte <b>hodiny:minúty</b> (HH:MM); ak je skorší ako aktuálny čas, akcia sa vykoná zajtra</li>
<li><b>Export</b> — záloha nastavení a playlistu do JSON súboru</li>
<li><b>Import</b> — obnovenie nastavení zo zálohy</li>
</ul>

<h3 style="color: #d4860a;">Štatistiky</h3>
<ul>
<li><b>Playlist</b> — počet skladieb a celkový čas</li>
<li><b>Označené</b> — počet a čas označených skladieb (pri výbere viacerých)</li>
<li><b>Celkovo prehraných</b> — koľko skladieb si prehrál a koľko času si počúval</li>
</ul>

<h3 style="color: #d4860a;">Ostatné</h3>
<ul>
<li><b>☰</b> — zobrazí/skryje playlist (compact mód)</li>
<li><b>System tray</b> — minimalizácia do lišty vedľa hodín, tooltip zobrazuje aktuálnu skladbu</li>
<li><b>Tmavý titulný panel</b> — Windows 10/11 dark mode</li>
</ul>

<h3 style="color: #d4860a;">Aktualizácie</h3>
<ul>
<li><b>Nainštalovaná verzia</b> — {html_escape(popis_lokalnej_verzie())}</li>
<li><b>Zdroj</b> — {html_escape(str(update_zdroj))}</li>
<li>Prehrávač sa po spustení sám pozrie na NAS. Sťahuje sa až po tvojom
potvrdení a pred inštaláciou sa overí kontrolný súčet balíka.</li>
<li>Keď NAS nie je dostupný (si mimo domu), <b>nepovie nič</b> — kontrola sa
proste preskočí.</li>
<li><b>Tvoje súbory update neprepíše</b>: <b>config.txt</b>, <b>spanok.m3u</b>
a <b>spanok2.m3u</b> ostanú také, aké sú. Keď niektorý chýba (nová
inštalácia), doplní sa vzor z balíka.</li>
<li>Kontrolu vypneš riadkom <b>UPDATE_KONTROLA=nie</b> v <b>config.txt</b>,
iný priečinok nastavíš cez <b>UPDATE_ZDROJ</b>.</li>
<li>Heslo k NAS-u appka v sebe nemá. Keď sa naň nedostane priamo, prihlási sa
údajmi z <b>nas-credentials.local</b>; na notebooku, kde ten súbor nie je, má
prihlásenie uložené Windows (<b>cmdkey</b> — urobí to inštalátor z NAS-u).</li>
<li>Po aktualizácii sa prehrávač sám ukončí a znova spustí. Priebeh je
v <b>{html_escape(str(update_log))}</b>.</li>
</ul>

<h3 style="color: #d4860a;">Záloha playlistu</h3>
<ul>
<li>Pri každom spustení sa aktuálny playlist odloží na NAS do
<b>{html_escape(str(zaloha_priecinok))}</b> — každý počítač má vlastný
priečinok, lebo playlist má každý svoj.</li>
<li><b>Zapisuje sa len pri zmene.</b> Keď playlist ostal taký, aký bol,
nepribudne nič; dátum v názve súboru je teda dátum zmeny.</li>
<li>Záloha je obyčajný <b>.m3u8</b> zoznam s celými cestami. Vrátiš ho tak, že
ho <b>pretiahneš myšou do okna</b> prehrávača, alebo cez <b>Načítať M3U</b>.
Skladby sa <b>pridávajú na koniec</b> — na presnú obnovu najprv
<b>Vymazať playlist</b>. Otvorí ho aj poznámkový blok a prehrá hociktorý iný
prehrávač.</li>
<li>Drží sa posledných <b>{zaloha_playlistu.pocet_zaloh()}</b> záloh, staršie sa
mažú. Počet zmeníš kľúčom <b>ZALOHA_POCET</b>, iný priečinok cez
<b>ZALOHA_PRIECINOK</b>, celé to vypneš <b>ZALOHA_PLAYLISTU=nie</b>
(všetko v <b>config.txt</b>).</li>
<li>Keď NAS nie je dostupný, záloha sa <b>ticho preskočí</b> — rovnako ako
kontrola aktualizácií.</li>
</ul>
        """)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        skontroluj = buttons.addButton(
            "Skontrolovať aktualizáciu teraz", QDialogButtonBox.ButtonRole.ActionRole
        )
        skontroluj.clicked.connect(
            lambda: (dlg.accept(), self._skontroluj_aktualizaciu(hlasne=True))
        )
        zalohuj = buttons.addButton(
            "Zálohovať playlist teraz", QDialogButtonBox.ButtonRole.ActionRole
        )
        zalohuj.clicked.connect(
            lambda: (dlg.accept(), self._zalohuj_playlist(hlasne=True))
        )
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.exec()

    # ── statistika pocuvania ───────────────────────────────────────────────────
    def _ukaz_statistiku(self) -> None:
        from music_player.statistika_okno import StatistikaOkno

        if self.controller.statistika is None:
            QMessageBox.information(self, "Štatistika", "Štatistika nie je zapnutá.")
            return
        StatistikaOkno(self.controller, self).exec()

    # ── metalove novinky ───────────────────────────────────────────────────────
    def _nacitaj_novinky(self, *, hlasne: bool) -> None:
        """Zoznam noviniek z NAS-u. `hlasne=True` je stlacene tlacidlo.

        Ticha kontrola po starte len doplni pocet do tlacidla; ked NAS nie je
        dostupny, nepovie nic — rovnako ako kontrola verzie a zaloha playlistu.
        """
        import threading

        from music_player import novinky

        if not novinky.zapnute():
            if hlasne:
                QMessageBox.information(
                    self, "Novinky",
                    "Novinky sú vypnuté — v config.txt je riadok NOVINKY=nie.")
            return

        if hlasne:
            self._show_message("Pozerám sa na NAS po novinkách...")
            self.novinky_button.setEnabled(False)

        def _bezi() -> None:
            try:
                zoznam = novinky.nacitaj()
            except Exception:  # noqa: BLE001 - vlakno nesmie zhodit appku
                zoznam = None
            self._novinky_nacitane.emit(zoznam, hlasne)

        threading.Thread(target=_bezi, daemon=True).start()

    def _on_novinky_nacitane(self, zoznam, hlasne: bool) -> None:
        from music_player import novinky

        self.novinky_button.setEnabled(True)
        if zoznam is None:
            if hlasne:
                QMessageBox.warning(
                    self, "Novinky",
                    "Zoznam noviniek sa nepodarilo prečítať.\n\n"
                    f"Zdroj: {novinky.priecinok()}")
            return

        self._novinky = zoznam
        self._obnov_pocet_noviniek()
        if not hlasne:
            return

        if not zoznam.albumy:
            QMessageBox.information(
                self, "Novinky",
                "Zoznam je zatiaľ prázdny.\n\n"
                "Napĺňa ho piatkový sken metalových noviniek; do prehrávača sa "
                "dostane to, čo prejde filtrom žánrov.\n\n"
                f"Zdroj: {novinky.priecinok()}")
            return

        dlg = _NovinkyDialog(self, zoznam, self._oznac_novinky)
        dlg.exec()
        self._obnov_pocet_noviniek()
        self._show_message(f"Nevypočutých noviniek: {zoznam.pocet_novych}.")

    def _obnov_pocet_noviniek(self) -> None:
        """Cislo v tlacidle. Bez neho by clovek nemal preco okno otvorit."""
        pocet = self._novinky.pocet_novych if self._novinky is not None else 0
        self.novinky_button.setText(
            f"🆕 Novinky ({pocet})" if pocet else "🆕 Novinky")

    def _oznac_novinky(self, kluce, stav=True, albumy=None) -> None:
        """Zapis stavu albumov na NAS. Vo vlakne — okno na neho cakat nemusi.

        `stav` je `novinky.NOVE / ZAUJIMAVE / SKONTROLOVANE`; `True`/`False`
        ostava ako skratka za skontrolovane/nove.

        Ci sa zapis podaril, sa uz nezistuje: ked NAS neodpovie, `novinky.oznac`
        si zapis odlozi a odosle ho pri najblizsom nacitani zoznamu.
        """
        import threading

        from music_player import novinky

        if isinstance(stav, bool):
            stav = novinky.SKONTROLOVANE if stav else novinky.NOVE
        zoznam = list(kluce)
        threading.Thread(
            target=lambda: novinky.oznac(zoznam, stav=stav, albumy=albumy),
            daemon=True).start()

    def _oznac_stiahnute_novinky(self, result) -> list[str]:
        """Rozbaleny album sa v novinkach odskrtne sam.

        Ked som si ho stiahol, uz som sa rozhodol — v zozname nemusi zavadzat.
        Parovanie je cez `nazvy.kluc`, ktory zahadzuje interpunkciu: priecinok
        sa vola "Augurium - Faith and Death - 2026", sken pise "Faith & Death".
        Ked sa zoznam este nedotiahol z NAS-u, nerobi sa nic — nie je s cim.
        """
        from music_player import nazvy

        if self._novinky is None:
            return []
        podla_nazvu = {}
        for album in self._novinky.albumy:
            podla_nazvu.setdefault(nazvy.kluc(album.kapela, album.album), album)

        najdene = []
        for outcome in result.extracted:
            rozobrany = nazvy.rozober(outcome.album)
            if rozobrany is None:
                continue
            album = podla_nazvu.get(nazvy.kluc(rozobrany.interpret, rozobrany.album))
            # Zaujimavy album sa stiahnutim neodskrtava — je v zalozke zamerne.
            if album is not None and self._novinky.stav(album.kluc) == "nove":
                najdene.append(album)

        if najdene:
            self._novinky.precitane.update(a.kluc for a in najdene)
            self._oznac_novinky([a.kluc for a in najdene], True,
                                {a.kluc: a for a in najdene})
            self._obnov_pocet_noviniek()
        return [a.nadpis for a in najdene]

    # ── aktualizacia z NAS-u ───────────────────────────────────────────────────
    # Kedy sa tichá kontrola zopakuje, ked NAS nebol na dosah (minúty).
    #
    # Kontrola pri starte bezi 5 sekund po otvoreni okna. Na notebooku, ktory
    # prehravac spusta hned po zobudeni (`hudba-po-zobudeni.ps1`), je vtedy
    # siet este casto dole — a kedze sa kontrola uz nikdy neopakovala, appka
    # o novych verziach nevedela az do dalsieho rucneho spustenia. Tak zostal
    # jeden notebook na starej verzii.
    #
    # Tri pokusy staci: siet po zobudeni nabehne do minuty, a ked ani po
    # stvrthodine nie je, si mimo domu a dalsie pytanie uz nic neprinesie.
    ODLOZENE_KONTROLY = (1, 5, 15)

    def _skontroluj_aktualizaciu(self, *, hlasne: bool) -> None:
        """Pozrie sa na NAS, ci tam nie je novsia verzia.

        `hlasne=False` je kontrola pri starte: ozve sa len vtedy, ked naozaj
        nieco nove je. `hlasne=True` je stlacene tlacidlo — vtedy musi prist
        odpoved aj ked nic nove nie je, inak to vyzera, ze tlacidlo nefunguje.
        """
        import threading

        from music_player import self_update

        if not hlasne and not self_update.kontrola_pri_starte():
            return

        if hlasne:
            self._show_message("Pozerám sa na NAS...")

        def _bezi() -> None:
            # Citanie z odpojeneho sietoveho disku trva aj niekolko sekund,
            # preto vo vlakne — okno musi ostat ovladatelne.
            manifest = self_update.zisti()
            # Ked sa manifest neda precitat, este sa oplati vediet, ci je NAS
            # vobec na dosah: "si mimo domu" a "share ta nepusti" su dve rozne
            # veci a druha sa ma povedat nahlas. Aj toto je siet, teda vo vlakne.
            odpoveda = False if manifest is not None else self_update.server_odpoveda(
                self_update.zdroj())
            self._update_checked.emit(manifest, hlasne, odpoveda)

        threading.Thread(target=_bezi, daemon=True).start()

    def _on_update_checked(self, manifest, hlasne: bool, odpoveda: bool) -> None:
        from music_player import self_update

        if manifest is None:
            if hlasne:
                QMessageBox.information(
                    self, "Aktualizácia",
                    "NAS neodpovedal, alebo je na ňom neplatný latest.json.\n\n"
                    f"Zdroj: {self_update.zdroj()}\n"
                    f"Máš verziu {self_update.popis_lokalnej_verzie()}.",
                )
            elif odpoveda:
                # Server je na dosah a manifest sa aj tak neda precitat — teda
                # nie "si mimo domu", ale "share ta nepusti". Mlcat tu bola
                # chyba: v tomto stave sa appka uz NIKDY sama neaktualizuje
                # a na druhom notebooku ticho zostarne o niekolko verzii. Presne
                # to sa stalo, a vysvitlo to az nahodou. Preto sa to odteraz
                # povie aj pri kontrole pri starte — aj za cenu toho, ze to bude
                # pri kazdom spusteni. Kym sa to neopravi, je to pravda.
                QMessageBox.warning(
                    self, "Aktualizácie nefungujú",
                    "NAS odpovedá, ale nepustí ma k zoznamu verzií — táto "
                    "inštalácia sa teda sama neaktualizuje.\n\n"
                    f"Zdroj: {self_update.zdroj()}\n"
                    f"Máš verziu {self_update.popis_lokalnej_verzie()}.\n\n"
                    "Chýba uložené prihlásenie na NAS. Otvor príkazový riadok "
                    "a spusti:\n\n"
                    "    cmdkey /add:nas.local /user:nasuser /pass\n\n"
                    "Potom prehrávač zavri a znova otvor.",
                )
            elif self._update_pokusov < len(self.ODLOZENE_KONTROLY):
                # NAS nie je na dosah. Nemusi to znamenat "si mimo domu" —
                # po zobudeni notebooku este len nabieha siet. Skusi sa to
                # este parkrat; ticho, ako doteraz.
                minut = self.ODLOZENE_KONTROLY[self._update_pokusov]
                self._update_pokusov += 1
                QTimer.singleShot(
                    minut * 60_000,
                    lambda: self._skontroluj_aktualizaciu(hlasne=False))
            return

        if not self_update.je_novsia(manifest):
            if hlasne:
                QMessageBox.information(
                    self, "Aktualizácia",
                    f"Máš najnovšiu verziu {self_update.popis_lokalnej_verzie()}.",
                )
            return

        # Rovnaka veta ako v androidovych appkach (docs/shared-standard.md kap. 2.4).
        text = (
            f"Na NAS-e je verzia {manifest.popis}, "
            f"máš {self_update.popis_lokalnej_verzie()}. Nainštalovať teraz?"
        )
        if manifest.poznamka:
            text += f"\n\nČo je nové:\n{manifest.poznamka}"
        text += "\n\nPrehrávač sa na chvíľu ukončí a sám sa znova spustí."

        okno = QMessageBox(QMessageBox.Icon.Question, "Nová verzia", text,
                           QMessageBox.StandardButton.NoButton, self)
        ano = okno.addButton("Nainštalovať", QMessageBox.ButtonRole.AcceptRole)
        okno.addButton("Neskôr", QMessageBox.ButtonRole.RejectRole)
        okno.exec()
        if okno.clickedButton() is ano:
            self._nainstaluj_aktualizaciu(manifest)

    def _nainstaluj_aktualizaciu(self, manifest) -> None:
        from music_player import self_update

        self._show_message(f"Sťahujem verziu {manifest.popis}...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            priprava, ponechane = self_update.priprav(manifest)
            self_update.spusti_aplikator(priprava)
        except self_update.ChybaAktualizacie as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Aktualizácia", str(exc))
            self._show_message("Aktualizácia sa nepodarila.")
            return
        except OSError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Aktualizácia", f"Aktualizácia zlyhala: {exc}")
            self._show_message("Aktualizácia sa nepodarila.")
            return
        QApplication.restoreOverrideCursor()

        if ponechane:
            # Nech je jasne, ze nastavenia ostali — inak by ich clovek po
            # kazdom vydani zbytocne kontroloval.
            self._show_message("Nechávam tvoje: " + ", ".join(ponechane))

        # Odtialto uz kopiruje aktualizuj.ps1 a caka na ukoncenie tohto
        # procesu. Ukoncujeme sa preto rovnako, ako pri "Ukoncit" z tray-u.
        self._quit_from_tray()

    # ── zaloha playlistu na NAS ────────────────────────────────────────────────
    def _zalohuj_playlist(self, *, hlasne: bool) -> None:
        """Odlozi aktualny playlist na NAS, ked sa od poslednej zalohy zmenil.

        `hlasne=False` je zaloha pri starte: ozve sa len jednou vetou v stavovom
        riadku a pri nedostupnom NAS-e mlci. `hlasne=True` je stlacene tlacidlo
        — vtedy musi prist odpoved vzdy, aj "nezmenil sa" aj "NAS neodpovedal",
        inak to vyzera, ze tlacidlo nefunguje.
        """
        import threading

        from music_player import zaloha_playlistu

        if not hlasne and not zaloha_playlistu.zapnuta():
            return

        if hlasne:
            self._show_message("Zálohujem playlist na NAS...")

        # Playlist sa cita TU, na hlavnom vlakne — vo vlakne uz len putuje
        # hotovy zoznam. Kopia zoznamu preto, ze appka sa medzitym da dalej
        # ovladat a menit playlist popod bezici zapis.
        tracks = list(self.controller.playlist)
        hraje = self.controller.current_track()

        def _bezi() -> None:
            # Zapis na sietovy disk trva a moze aj vyprsat — okno musi ostat
            # ovladatelne.
            vysledok = zaloha_playlistu.zalohuj(tracks, hraje=hraje)
            self._zaloha_hotova.emit(vysledok, hlasne)

        threading.Thread(target=_bezi, daemon=True).start()

    def _on_zaloha_hotova(self, vysledok, hlasne: bool) -> None:
        from music_player import zaloha_playlistu

        if not hlasne:
            if vysledok.sprava:
                self._show_message(vysledok.sprava)
            return

        priecinok = zaloha_playlistu.priecinok()
        if vysledok.stav == "zapisane":
            text = (
                f"Playlist ({vysledok.pocet} skladieb) je zazálohovaný:\n\n"
                f"{vysledok.subor}"
            )
            if vysledok.zmazane:
                text += f"\n\nStaršie zálohy zmazané: {vysledok.zmazane}"
        elif vysledok.stav == "nezmenene":
            text = (
                "Playlist sa od poslednej zálohy nezmenil, takže sa nič "
                f"nezapisovalo.\n\nPosledná záloha:\n{vysledok.subor}"
            )
        elif vysledok.stav == "prazdny":
            text = "Playlist je prázdny — nie je čo zálohovať."
        elif vysledok.stav == "vypnute":
            text = (
                "Zálohovanie je vypnuté riadkom ZALOHA_PLAYLISTU=nie "
                "v config.txt."
            )
        elif vysledok.stav == "nedostupne":
            text = (
                "Na NAS sa nedostanem, záloha sa preskočila.\n\n"
                f"Priečinok: {priecinok}"
            )
        else:
            text = f"Zálohu sa nepodarilo zapísať:\n\n{vysledok.detail}"

        QMessageBox.information(self, "Záloha playlistu", text)
        self._show_message(vysledok.sprava or "Záloha playlistu: " + vysledok.stav)

    def _export_settings(self) -> None:
        import shutil
        src = self.state_store.state_file
        if not src.exists():
            self._show_message("Žiadne nastavenia na export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportovať nastavenia", "metal_player_backup.json",
            "JSON súbory (*.json);;Všetky súbory (*)"
        )
        if path:
            try:
                shutil.copy2(str(src), path)
                self._show_message(f"Nastavenia exportované: {Path(path).name}")
            except OSError as e:
                self._show_message(f"Chyba: {e}")

    def _import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importovať nastavenia", "",
            "JSON súbory (*.json);;Všetky súbory (*)"
        )
        if not path:
            return
        try:
            import json
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if "playlist" not in data and "volume" not in data:
                self._show_message("Neplatný súbor nastavení.")
                return
            import shutil
            shutil.copy2(path, str(self.state_store.state_file))
            self._show_message("Nastavenia importované. Reštartuj prehrávač.")
        except (OSError, json.JSONDecodeError) as e:
            self._show_message(f"Chyba: {e}")

    def _toggle_playlist_panel(self) -> None:
        if self._playlist_visible:
            self._full_height = self.height()
            self._playlist_visible = False
            self.playlist_panel.hide()
            for b in self._toolbar_buttons:
                b.hide()
            # Let Qt recalculate, then fix window to the player strip height
            QTimer.singleShot(0, self._shrink_to_strip)
        else:
            self._playlist_visible = True
            self.setMinimumHeight(300)
            self.setMaximumHeight(16777215)
            for b in self._toolbar_buttons:
                b.show()
            self.playlist_panel.show()
            self.resize(self.width(), self._full_height)

    def _shrink_to_strip(self) -> None:
        h = self._player_strip.sizeHint().height()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.resize(self.width(), h)
        self.setFixedHeight(self.height())

    # ── now playing (compact strip) ────────────────────────────────────────────
    def _update_compact_now_playing(self, track) -> None:
        if track is None:
            self.info_label.setText("Nič nehrá")
            self._current_duration_ms = 0
            self._set_seek_value(0, 0)
            self.seek_slider.setEnabled(False)
            self._update_position_label(0, 0)
            self.tray_icon.setToolTip("Metal Music Player")
            return
        parts = [track.title]
        if track.artist:
            parts.append(track.artist)
        text = " – ".join(parts)
        quality = _read_audio_quality(track.path)
        if quality:
            text = f"{text}  ({quality})"
        self.info_label.setText(text)
        self.seek_slider.setEnabled(True)
        tray_tip = f"{track.artist} – {track.title}" if track.artist else track.title
        self.tray_icon.setToolTip(tray_tip)

    # ── now playing (info panel) ───────────────────────────────────────────────
    def _update_now_playing(self, track) -> None:
        if track is None:
            self.ma_link_label.setText("")
            self._select_current_playlist_row()
            self._refresh_stream_status()
            self._show_placeholder_cover()
            self.lyrics_edit.clear()
            self._reset_translation_state()
            return

        self.ma_link_label.setText("")
        self._select_current_playlist_row()
        self._refresh_stream_status()

        self._load_cover_async(track)
        self.lyrics_edit.clear()
        self._reset_translation_state()
        self.lyrics_edit.setPlaceholderText("Načítavam texty piesní …")
        self._load_lyrics_async(track)
        self._load_metadata_async(track)

    # ── playback state ─────────────────────────────────────────────────────────
    def _update_playback_state(self, state_name: str) -> None:
        sp = self.style()
        if state_name == "playing":
            self.play_button.setIcon(sp.standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        else:
            self.play_button.setIcon(sp.standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        dot_colors = {"playing": "#4caf50", "paused": "#ffa000", "stopped": "#777"}
        color = dot_colors.get(state_name, "#777")
        labels = {"playing": "prehráva", "paused": "pauza", "stopped": "zastavené"}
        self.state_label.setText(
            f'<span style="color:{color}">●</span>  {labels.get(state_name, state_name)}'
        )

    # ── seek / position ────────────────────────────────────────────────────────
    def _update_duration(self, duration_ms: int) -> None:
        self._current_duration_ms = max(int(duration_ms), 0)
        if not self._is_seeking:
            pos = min(int(self.controller.player.position()), self._current_duration_ms)
            self._set_seek_value(pos, self._current_duration_ms)
            self._update_position_label(pos, self._current_duration_ms)
        self.seek_slider.setEnabled(
            self._current_duration_ms > 0 and self.controller.current_track() is not None
        )

    def _update_playback_position(self, position_ms: int) -> None:
        if not self._is_seeking:
            safe = max(int(position_ms), 0)
            self._set_seek_value(safe, self._current_duration_ms)
            self._update_position_label(safe, self._current_duration_ms)

    def _set_seek_value(self, value: int, maximum: int) -> None:
        bmax = max(int(maximum), 0)
        bval = max(0, min(int(value), bmax)) if bmax > 0 else 0
        self.seek_slider.blockSignals(True)
        self.seek_slider.setRange(0, bmax)
        self.seek_slider.setValue(bval)
        self.seek_slider.blockSignals(False)

    def _update_position_label(self, position_ms: int, duration_ms: int) -> None:
        self.position_label.setText(
            f"{_format_ms(position_ms)} / {_format_ms(duration_ms)}"
        )

    def _start_seeking(self) -> None:
        if self.seek_slider.maximum() <= 0:
            return
        self._is_seeking = True
        self._update_position_label(self.seek_slider.value(), self._current_duration_ms)

    def _preview_seek_position(self, value: int) -> None:
        self._update_position_label(value, self._current_duration_ms)

    def _commit_seek(self) -> None:
        if self.seek_slider.maximum() <= 0:
            self._is_seeking = False
            return
        self._is_seeking = False
        self.controller.seek(int(self.seek_slider.value()))
        self.save_state()

    def _seek_forward_5s(self) -> None:
        if self.controller.current_track() is None:
            return
        self.controller.seek(int(self.controller.player.position()) + 5000)

    def _seek_backward_5s(self) -> None:
        if self.controller.current_track() is None:
            return
        self.controller.seek(int(self.controller.player.position()) - 5000)

    # ── playback toggle ────────────────────────────────────────────────────────
    def _toggle_playback_from_ui(self) -> None:
        state = self.controller.playback_state_name()
        # Paused → always resume from current position, never switch tracks
        if state == "paused":
            self.controller.toggle_playback()
            self.save_state()
            return
        # Stopped + different row selected → play that track
        selected_row = self.playlist_widget.currentRow()
        if (
            state == "stopped"
            and 0 <= selected_row < len(self.controller.playlist)
            and selected_row != self.controller.current_index
        ):
            self.controller.play_track_at(selected_row)
            self.save_state()
            return
        self.controller.toggle_playback()
        self.save_state()

    # ── audio retry (tray only) ────────────────────────────────────────────────
    def _retry_audio(self) -> None:
        self.controller.retry_playback()
        self.save_state()
        self._show_message("Obnova audio prehrávania…")

    # ── mute toggle ────────────────────────────────────────────────────────────
    def _toggle_mute(self) -> None:
        if self._muted:
            self._muted = False
            self.volume_slider.setValue(self._pre_mute_volume)
        else:
            self._pre_mute_volume = max(self.volume_slider.value(), 1)
            self._muted = True
            self.volume_slider.setValue(0)

    def _update_mute_icon(self, value: int) -> None:
        if value == 0:
            self.mute_button.setText("🔇")
        elif value < 50:
            self.mute_button.setText("🔉")
        else:
            self.mute_button.setText("🔊")

    # ── tray ───────────────────────────────────────────────────────────────────
    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        # Skladby spankovych zoznamov musia z playlistu von skor, nez sa stav
        # ulozi — inak by sa zapisali do state.json a na druhy den tam boli zase.
        self.controller.restore_spanok_lists()
        self._allow_close = True
        self.save_state()
        QApplication.instance().quit()

    def _handle_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        }:
            self._restore_from_tray()

    # ── cover art ──────────────────────────────────────────────────────────────
    def _show_placeholder_cover(self) -> None:
        self.cover_label.clear()
        self.cover_label.setText("♪")
        self.cover_label.setStyleSheet(
            f"background: {_C_BG_HEADER}; border: 1px solid {_C_BORDER}; border-radius: 6px;"
            f" font-size: 64px; color: {_C_BORDER};"
        )

    def _update_background(self, data: bytes | None) -> None:
        if not data:
            self._bg_pixmap = None
            self.centralWidget().update()
            return
        from PySide6.QtGui import QImage, QPainter as _QPainter
        img = QImage()
        if not img.loadFromData(data):
            self._bg_pixmap = None
            self.centralWidget().update()
            return
        # Real Gaussian blur via QGraphicsBlurEffect.
        from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect
        src_pix = QPixmap.fromImage(img).scaled(
            800, 600, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(src_pix)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(15)
        item.setGraphicsEffect(blur)
        scene.addItem(item)
        result = QImage(src_pix.size(), QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(QColor(0, 0, 0, 0))
        p = _QPainter(result)
        scene.render(p)
        # Dark overlay for readability.
        p.fillRect(result.rect(), QColor(30, 26, 22, 60))
        p.end()
        self._bg_pixmap = QPixmap.fromImage(result)
        self.centralWidget().update()

    def _show_cover(self, data: bytes) -> None:
        pix = QPixmap()
        if pix.loadFromData(data):
            self._cover_raw_data = data
            self.cover_label.setText("")
            self.cover_label.setStyleSheet(
                f"background: {_C_BG_HEADER}; border: 1px solid {_C_BORDER}; border-radius: 6px;"
            )
            self._scale_cover_to_label()
        else:
            self._cover_raw_data = None
            self._show_placeholder_cover()

    def _scale_cover_to_label(self) -> None:
        if not self._cover_raw_data:
            return
        w = self.cover_label.width() or 300
        h = self.cover_label.height() or 300
        pix = QPixmap()
        if pix.loadFromData(self._cover_raw_data):
            pix = pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.cover_label.setPixmap(pix)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_cover_to_label()

    # ── stream status ──────────────────────────────────────────────────────────
    def _refresh_stream_status(self) -> None:
        snapshot = self.controller.snapshot()
        if snapshot.get("streamingActive"):
            self.stream_label.setText(
                f"LAN stream: ACTIVE  │  {snapshot.get('streamUrl', '')}"
            )
            return
        if snapshot.get("streamingReady"):
            self.stream_label.setText(
                f"LAN stream: pripravený  │  {snapshot.get('streamUrl', '')}"
            )
            return
        last_error = snapshot.get("streamLastError") or "ffmpeg nie je dostupný"
        self.stream_label.setText(f"LAN stream: OFF  │  {last_error}")

    # ── playlist ───────────────────────────────────────────────────────────────
    def _refresh_playlist(self) -> None:
        self.playlist_widget.setUpdatesEnabled(False)
        self.playlist_widget.clear()
        missing_durations = []
        so_zalozkou = self.controller.riadky_so_zalozkou()
        for i, track in enumerate(self.controller.playlist):
            item = QListWidgetItem(track.display_text)
            item.setData(Qt.ItemDataRole.UserRole, track.path)
            item.setData(_ROLE_DURATION, track.duration_display)
            if i in so_zalozkou:
                item.setData(_ROLE_ZALOZKA, True)
            tooltip = f"{track.artist} – {track.title}" if track.artist else track.title
            if track.album:
                tooltip += f"\n{track.album}"
                if track.year:
                    tooltip += f" ({track.year})"
            item.setToolTip(tooltip)
            self.playlist_widget.addItem(item)
            if track.duration_ms <= 0:
                missing_durations.append(i)
        self.playlist_widget.setUpdatesEnabled(True)
        self._select_current_playlist_row()
        # Fill missing durations in background
        if missing_durations:
            import threading
            threading.Thread(
                target=self._fill_missing_durations,
                args=(missing_durations,),
                daemon=True,
            ).start()

    def _oznac_zalozky(self) -> None:
        """Prekresli 🔖 v playliste bez skladania celeho zoznamu nanovo."""
        so_zalozkou = self.controller.riadky_so_zalozkou()
        for i in range(self.playlist_widget.count()):
            item = self.playlist_widget.item(i)
            chcem = i in so_zalozkou
            if bool(item.data(_ROLE_ZALOZKA)) != chcem:
                item.setData(_ROLE_ZALOZKA, chcem)

    def _fill_missing_durations(self, indices: list[int]) -> None:
        from music_player.models import _read_duration_ms
        for i in indices:
            if i >= len(self.controller.playlist):
                break
            track = self.controller.playlist[i]
            dur = _read_duration_ms(track.path)
            if dur > 0:
                track.duration_ms = dur
        # Schedule UI update on main thread via signal
        self._durations_ready.emit()

    def _update_durations_in_list(self) -> None:
        for i, track in enumerate(self.controller.playlist):
            if i < self.playlist_widget.count() and track.duration_ms > 0:
                item = self.playlist_widget.item(i)
                if item and not item.data(_ROLE_DURATION):
                    item.setData(_ROLE_DURATION, track.duration_display)
        self._update_stats()

    def _select_current_playlist_row(self) -> None:
        if 0 <= self.controller.current_index < self.playlist_widget.count():
            self.playlist_widget.setCurrentRow(self.controller.current_index)

    # ── async loaders ──────────────────────────────────────────────────────────
    def _load_cover_async(self, track) -> None:
        import threading
        self._cover_track_path = track.path

        def _load():
            data = None
            try:
                from music_player.web_metadata import fetch_cover
                data = fetch_cover(track.artist or "", track.album or "", track.path)
            except Exception:
                pass
            if not data:
                try:
                    from music_player.tags import _extract_cover
                    data = _extract_cover(track.path)
                except Exception:
                    pass
            self._cover_ready.emit(data, track.path)

        threading.Thread(target=_load, daemon=True).start()

    def _load_lyrics_async(self, track, vynutit: bool = False) -> None:
        import threading
        self._lyrics_track_path = track.path

        def _load():
            text = ""
            try:
                from music_player.web_metadata import fetch_lyrics
                text = fetch_lyrics(track.artist or "", track.title or "", track.album or "",
                                    track.path, vynutit=vynutit)
            except Exception:
                pass
            self._lyrics_ready.emit(text, track.path)

        threading.Thread(target=_load, daemon=True).start()

    def _on_reload_lyrics_clicked(self) -> None:
        track = self.controller.current_track()
        if track is None:
            return
        self.reload_lyrics_button.setEnabled(False)
        self.lyrics_edit.clear()
        self._reset_translation_state()
        self.lyrics_edit.setPlaceholderText("Hľadám texty na Metal Archives …")
        self._load_lyrics_async(track, vynutit=True)

    # ── preklad celého textu ───────────────────────────────────────────────────
    def _reset_translation_state(self) -> None:
        """Pri prepnutí skladby zahoď preklad predošlej.

        Preklad sa nezahadzuje z disku — len z okna. Na disku ostáva a pri
        návrate k skladbe sa načíta bez ďalšieho dopytu do DeepL.
        """
        self._lyrics_original = ""
        self._lyrics_translation = ""
        self._showing_translation = False
        self._translation_running = False
        self.lyrics_edit.set_hover_enabled(True)
        self.translate_button.setEnabled(False)
        self.translate_button.setText("🌐 Preložiť text")

    def _on_translate_clicked(self) -> None:
        if self._translation_running or not self._lyrics_original:
            return

        # Späť na originál — prepínač, aby sa dal preklad čítať vedľa neho.
        if self._showing_translation:
            self._showing_translation = False
            self.lyrics_edit.setText(self._lyrics_original)
            self.lyrics_edit.set_hover_enabled(True)
            self.translate_button.setText("🌐 Preložiť text")
            return

        if self._lyrics_translation:
            self._show_translation(self._lyrics_translation)
            return

        track = self.controller.current_track()
        if track is None:
            return

        # Preklad z disku, ak tam z minula je — kvótu DeepL minieme na skladbu raz.
        from music_player.disk_cache import read_cached_translation
        cached = read_cached_translation(track.path, track.title or "")
        if cached:
            self._lyrics_translation = cached
            self._show_translation(cached)
            return

        self._translation_running = True
        self.translate_button.setEnabled(False)
        self.translate_button.setText("Prekladám …")
        self._translate_lyrics_async(track, self._lyrics_original)

    def _translate_lyrics_async(self, track, text: str) -> None:
        import threading

        def _run():
            from music_player.translator import Preklad, translate_lyrics
            try:
                vysledok = translate_lyrics(text, self.lyrics_edit._api_key)
            except Exception as e:
                vysledok = Preklad(chyba=f"Preklad zlyhal: {e}")
            self._translation_ready.emit(vysledok, track.path, track.title or "")

        threading.Thread(target=_run, daemon=True).start()

    def _show_translation(self, text: str) -> None:
        self._showing_translation = True
        self.lyrics_edit.setText(text)
        # Slovenčinu netreba prekladať po slovách a každý hover by míňal kvótu.
        self.lyrics_edit.set_hover_enabled(False)
        self.translate_button.setText("↩ Originál")
        self.translate_button.setEnabled(True)

    def _on_translation_loaded(self, vysledok, track_path: str, title: str) -> None:
        # Uložiť sa musí VŽDY a ako prvé, nezávisle od toho, čo práve hrá.
        # Kvóta DeepL je už minutá; zahodiť preklad preto, že používateľ
        # medzitým preskočil inam, by znamenalo zaplatiť ho pri ďalšom klepnutí
        # druhýkrát.
        if vysledok.text:
            from music_player.disk_cache import write_cached_translation
            write_cached_translation(track_path, title, vysledok.text)

        # Do okna ide výsledok len vtedy, keď stále patrí zobrazenej skladbe.
        # Prázdny originál znamená to isté v inom prevedení: preskočil preč
        # a späť, text sa načítava odznova a prepínač by nemal na čo prepnúť.
        # Na disku už preklad je, takže ďalšie klepnutie ho vytiahne zadarmo.
        if getattr(self, "_lyrics_track_path", "") != track_path:
            return
        self._translation_running = False
        if not self._lyrics_original:
            return
        self.translate_button.setEnabled(True)

        if vysledok.chyba:
            self.translate_button.setText("🌐 Preložiť text")
            QMessageBox.warning(self, "Preklad textu", vysledok.chyba)
            return

        self._lyrics_translation = vysledok.text
        self._show_translation(vysledok.text)

        if vysledok.varovanie:
            QMessageBox.warning(self, "Kvóta DeepL sa míňa", vysledok.varovanie)

    def _load_metadata_async(self, track) -> None:
        import threading
        self._metadata_track_path = track.path

        def _load():
            meta = None
            try:
                from music_player.web_metadata import fetch_album_metadata
                meta = fetch_album_metadata(track.artist or "", track.album or "", track.path)
            except Exception:
                pass
            self._metadata_ready.emit(meta or {}, track.path)

        threading.Thread(target=_load, daemon=True).start()

    # ── async callbacks ────────────────────────────────────────────────────────
    def _on_cover_loaded(self, data: bytes | None, track_path: str) -> None:
        # Ignore late results for a track the user has already skipped past
        # (same staleness guard as lyrics/metadata below).
        if getattr(self, "_cover_track_path", "") != track_path:
            return
        self._update_background(data)
        if data:
            self._show_cover(data)
        else:
            self._show_placeholder_cover()

    def _on_lyrics_loaded(self, text: str, track_path: str) -> None:
        tlacidlo = getattr(self, "reload_lyrics_button", None)
        if tlacidlo is not None:
            tlacidlo.setEnabled(True)
        if getattr(self, "_lyrics_track_path", "") != track_path:
            return
        if text:
            self.lyrics_edit.setText(text)
            self._lyrics_original = text
            # Kľúč sa tu zámerne nekontroluje: `set_api_key` beží až po vzniku
            # okna, takže v tejto chvíli ešte nemusí byť nastavený. Chýbajúci
            # kľúč ohlási `translate_lyrics()` až pri kliknutí.
            self.translate_button.setEnabled(True)
        else:
            self.lyrics_edit.clear()
            self.lyrics_edit.setPlaceholderText(
                "Texty piesní sa nenašli.\n\nAk na Metal Archives medzitým pribudli, "
                "klikni 🔄 Načítať texty.")
            self.translate_button.setEnabled(False)

    def _on_metadata_loaded(self, meta: dict, track_path: str) -> None:
        if getattr(self, "_metadata_track_path", "") != track_path:
            return
        if not meta:
            return
        album_url = meta.get("album_url")
        if album_url:
            self.ma_link_label.setText(
                f'<a href="{album_url}" style="color: {_C_ACCENT};">⛓ Metal Archives</a>'
            )

    # ── playlist actions ───────────────────────────────────────────────────────
    def _play_selected_item(self, item: QListWidgetItem) -> None:
        row = self.playlist_widget.row(item)
        if 0 <= row < len(self.controller.playlist):
            self.controller.play_track_at(row)

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Vyber hudobné súbory",
            "",
            "Audio a playlisty (*.mp3 *.flac *.aac *.ogg *.wav *.m4a *.wma *.m3u *.m3u8)",
        )
        self._ingest_paths(files, source_label="Pridané súbory")

    def _add_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Vyber priečinok s hudbou")
        if not directory:
            return
        self._ingest_paths([directory], source_label="Pridaný priečinok")

    def _ingest_paths(self, paths: list[str], *, source_label: str, insert_at: int | None = None) -> None:
        if not paths:
            return
        added, first_added_index = self.controller.add_paths(paths, play_on_first_add=True, insert_at=insert_at)
        if added:
            if first_added_index is not None:
                self.playlist_widget.setCurrentRow(first_added_index)
            self._show_message(f"{source_label}: {added} skladieb.")
            return
        self._show_message("Nenašli sa žiadne nové podporované audio súbory.")

    # ── import archívov z Downloads ────────────────────────────────────────────
    def _import_from_downloads(self) -> None:
        import threading
        from music_player import downloads_import

        self.downloads_button.setEnabled(False)
        self._show_message("Hľadám v Downloads archívy s hudbou…")

        def _work():
            try:
                result = downloads_import.import_from_downloads(
                    progress=self._downloads_progress.emit,
                    dohladat=self._dohladaj_nazov,
                )
            except Exception as exc:  # noqa: BLE001 - chybu ukážeme používateľovi
                self._downloads_done.emit(exc)
                return
            self._downloads_done.emit(result)

        threading.Thread(target=_work, daemon=True).start()

    def _dohladaj_nazov(self, surovy: str):
        """Kto je kapela a co je album — ked to z nazvu priecinka nie je zrejme.

        Najprv zoznam noviniek: je uz stiahnuty, odpoved je okamzita a prave
        odtial albumy chodia (vypocujem, potom stiahnem). Az ked tam nie je,
        ide sa na Metal Archives — to je jedno-dve hladania a par sekund.
        Bezi to vo vlakne rozbalovania, takze okno to nezdrzi.
        """
        from music_player import nazvy, nazvy_ma

        if self._novinky is not None:
            zo_zoznamu = nazvy.najdi_v_zozname(
                surovy, [(a.kapela, a.album) for a in self._novinky.albumy])
            if zo_zoznamu is not None:
                return zo_zoznamu
        return nazvy_ma.dohladaj(surovy)

    def _on_downloads_imported(self, result) -> None:
        from music_player import downloads_import

        self.downloads_button.setEnabled(True)

        if isinstance(result, Exception):
            self._show_message(f"Rozbaľovanie zlyhalo: {result}")
            QMessageBox.warning(self, "Import z Downloads", f"Rozbaľovanie zlyhalo:\n{result}")
            return

        if not result.outcomes:
            self._show_message(f"V Downloads nie sú žiadne archívy s hudbou ({downloads_import.downloads_dir()}).")
            return

        skladieb = sum(o.tracks for o in result.extracted)
        if result.extracted:
            parts = [
                f"rozbalené {len(result.extracted)}"
                f" ({self._sklonuj(skladieb, 'skladba', 'skladby', 'skladieb')})"
            ]
        else:
            parts = ["nič nové"]
        if result.skipped:
            parts.append(f"preskočené {len(result.skipped)}")
        if result.failed:
            parts.append(f"chyby {len(result.failed)}")
        self._show_message(f"{result.target}: " + ", ".join(parts) + ".")

        self._show_downloads_report(result, self._oznac_stiahnute_novinky(result))
        downloads_import.open_in_explorer(result.target)

    @staticmethod
    def _sklonuj(pocet: int, jeden: str, dva: str, viac: str) -> str:
        """1 album, 2 albumy, 5 albumov — inak to v hlásení škrípe."""
        if pocet == 1:
            return f"{pocet} {jeden}"
        if 2 <= pocet <= 4:
            return f"{pocet} {dva}"
        return f"{pocet} {viac}"

    def _show_downloads_report(self, result, oznacene: list[str] | None = None) -> None:
        """Prehľad toho, čo sa rozbalilo — pri viacerých archívoch je súhrn málo."""
        def zoznam(nadpis: str, farba: str, polozky: list, riadok) -> str:
            if not polozky:
                return ""
            html = f'<h3 style="color: {farba}; margin-bottom: 4px;">{nadpis} ({len(polozky)})</h3><ul style="margin-top: 0;">'
            html += "".join(f"<li>{riadok(o)}</li>" for o in polozky)
            return html + "</ul>"

        skladieb = sum(o.tracks for o in result.extracted)
        stopy = lambda o: self._sklonuj(o.tracks, "skladba", "skladby", "skladieb")
        telo = zoznam(
            "Pridané albumy", "#7bbf6a", result.extracted,
            lambda o: f"<b>{html_escape(o.album)}</b> — {stopy(o)}",
        )
        telo += zoznam(
            "Preskočené — už tam boli", "#a89070", result.skipped,
            lambda o: f"{html_escape(o.album)} — {stopy(o)}",
        )
        telo += zoznam(
            "Nepodarilo sa rozbaliť", "#d46a6a", result.failed,
            lambda o: f"{html_escape(o.archive.name)} — {html_escape(o.detail)}",
        )
        telo += zoznam(
            "Odškrtnuté v novinkách", "#a89070", list(oznacene or []),
            lambda nadpis: html_escape(nadpis),
        )
        premenovane = [o for o in result.extracted if o.premenovany]
        telo += zoznam(
            "Premenované", "#a89070", premenovane,
            lambda o: f"{html_escape(o.povodny)} &rarr; <b>{html_escape(o.album)}</b>",
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("Import z Downloads")
        dlg.setMinimumSize(560, 420)
        dlg.setStyleSheet(
            "QDialog { background: #1e1a16; }"
            "QTextEdit { background: #2a2520; color: #f5ead1; border: none; font-size: 13px; }"
        )
        layout = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        if result.extracted:
            nadpis = (
                f"Pribudlo {self._sklonuj(len(result.extracted), 'album', 'albumy', 'albumov')}"
                f" — {self._sklonuj(skladieb, 'skladba', 'skladby', 'skladieb')}"
            )
        else:
            nadpis = "Nepribudol žiadny nový album"
        text.setHtml(
            f'<h2 style="color: #d4860a;">{nadpis}</h2>'
            f'<p style="color: #a89070;">{html_escape(str(result.target))}</p>{telo}'
        )
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.exec()

    def _on_external_drop(self, mime_data, insert_at) -> None:
        paths = self._extract_local_paths(mime_data)
        if paths:
            self._ingest_paths(paths, source_label="Presunuté položky", insert_at=insert_at)

    def _on_playlist_rows_moved(self, source_rows: list[int], target_row: int) -> None:
        scroll_val = self.playlist_widget.verticalScrollBar().value()
        new_selection = self.controller.move_indices(source_rows, target_row)
        # playlist_changed already fired synchronously inside move_indices,
        # so the widget is rebuilt.  Now fix selection and scroll.
        self.playlist_widget.clearSelection()
        for row in new_selection:
            if 0 <= row < self.playlist_widget.count():
                self.playlist_widget.item(row).setSelected(True)
        if new_selection:
            self.playlist_widget.setCurrentRow(new_selection[0])
        self.playlist_widget.verticalScrollBar().setValue(scroll_val)
        self.save_state()

    def _remove_selected(self) -> None:
        rows = sorted({item.row() for item in self.playlist_widget.selectedIndexes()})
        if not rows:
            self._show_message("Vyber aspoň jednu skladbu na odstránenie.")
            return
        select_after = rows[0]
        self.controller.remove_indices(rows)
        # All signals already fired (synchronous). Override selection to the
        # row that slid into the first removed position, not the playing track.
        if self.playlist_widget.count() > 0:
            self.playlist_widget.setCurrentRow(min(select_after, self.playlist_widget.count() - 1))
        self._show_message("Vybrané skladby boli odstránené.")

    def _show_playlist_context_menu(self, pos) -> None:
        item = self.playlist_widget.itemAt(pos)
        if item is None:
            return
        row = self.playlist_widget.row(item)
        if not (0 <= row < len(self.controller.playlist)):
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #1e1a16; border: 1px solid #3d3025; }"
            "QMenu::item { color: #f5ead1; padding: 4px 20px; }"
            "QMenu::item:selected { background: #d4860a; color: #1e1a16; }"
        )
        metadata_action = menu.addAction("Zobraziť metadáta")
        zalozka = self.controller.zalozka_na_riadku(row)
        if zalozka >= 0:
            zalozka_action = menu.addAction("🔖 Odstrániť záložku")
        else:
            zalozka_action = menu.addAction("🔖 Pridať záložku")
        spanok_action = menu.addAction("Pridať do „Spánok“")
        sleep2_action = menu.addAction("Pridať do „Spánok 2“")
        remove_action = menu.addAction("Odstrániť")
        chosen = menu.exec(self.playlist_widget.mapToGlobal(pos))
        if chosen == metadata_action:
            self._show_track_metadata(row)
        elif chosen == zalozka_action:
            if zalozka >= 0:
                self._odober_zalozku(zalozka)
            else:
                self._pridaj_zalozku(row)
        elif chosen == spanok_action:
            self._add_selection_to_spanok(SPANOK)
        elif chosen == sleep2_action:
            self._add_selection_to_spanok(SPANOK2)
        elif chosen == remove_action:
            self._remove_selected()

    def _show_track_metadata(self, row: int) -> None:
        track = self.controller.playlist[row]
        from music_player.tags import read_tags
        tags = read_tags(track.path)
        quality = _read_audio_quality(track.path)

        dlg = QDialog(self)
        dlg.setWindowTitle("Metadáta")
        dlg.setMinimumWidth(450)
        dlg.setStyleSheet(
            "QDialog { background: #1e1a16; }"
            "QLabel { color: #f5ead1; }"
            "QLineEdit { background: #2a2520; color: #f5ead1; border: 1px solid #3d3025;"
            " padding: 3px 6px; font-size: 13px; }"
            "QLineEdit:focus { border-color: #d4860a; }"
        )
        layout = QFormLayout(dlg)
        layout.addRow("Súbor:", QLabel(Path(track.path).name))

        title_edit = QLineEdit(tags.title or "")
        artist_edit = QLineEdit(tags.artist or "")
        album_artist_edit = QLineEdit(tags.album_artist or "")
        album_edit = QLineEdit(tags.album or "")
        year_edit = QLineEdit(tags.year or "")
        genre_edit = QLineEdit(tags.genre or "")
        track_num_edit = QLineEdit(tags.track_number or "")
        disc_num_edit = QLineEdit(tags.disc_number or "")
        composer_edit = QLineEdit(tags.composer or "")
        comment_edit = QLineEdit(tags.comment or "")

        layout.addRow("Názov:", title_edit)
        layout.addRow("Interpret:", artist_edit)
        layout.addRow("Album artist:", album_artist_edit)
        layout.addRow("Album:", album_edit)
        layout.addRow("Rok:", year_edit)
        layout.addRow("Žáner:", genre_edit)
        layout.addRow("Track č.:", track_num_edit)
        layout.addRow("Disk č.:", disc_num_edit)
        layout.addRow("Skladateľ:", composer_edit)
        layout.addRow("Komentár:", comment_edit)
        layout.addRow("Kvalita:", QLabel(quality or "—"))
        layout.addRow("Cesta:", QLabel(track.path))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            from music_player.tags import write_tags
            if write_tags(
                track.path,
                title=title_edit.text().strip(),
                artist=artist_edit.text().strip(),
                album=album_edit.text().strip(),
                year=year_edit.text().strip(),
                album_artist=album_artist_edit.text().strip(),
                genre=genre_edit.text().strip(),
                track_number=track_num_edit.text().strip(),
                disc_number=disc_num_edit.text().strip(),
                composer=composer_edit.text().strip(),
                comment=comment_edit.text().strip(),
            ):
                track.title = title_edit.text().strip() or Path(track.path).stem
                track.artist = artist_edit.text().strip()
                track.album = album_edit.text().strip()
                track.year = year_edit.text().strip()
                self._refresh_playlist()
                self._show_message("Tagy boli uložené.")
            else:
                self._show_message("Nepodarilo sa uložiť tagy.")

    def _clear_playlist(self) -> None:
        self.controller.clear_playlist()
        self._show_message("Playlist bol vymazaný.")

    def _save_playlist_m3u(self) -> None:
        if not self.controller.playlist:
            self._show_message("Playlist je prázdny.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Uložiť playlist", "", "M3U Playlist (*.m3u);;Všetky súbory (*)"
        )
        if not path:
            return
        try:
            lines = ["#EXTM3U"]
            for track in self.controller.playlist:
                dur_s = track.duration_ms // 1000 if track.duration_ms > 0 else -1
                display = track.display_text
                lines.append(f"#EXTINF:{dur_s},{display}")
                lines.append(track.path)
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            self._show_message(f"Playlist uložený: {Path(path).name}")
        except OSError as e:
            self._show_message(f"Chyba pri ukladaní: {e}")

    def _load_playlist_m3u(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Načítať playlist", "",
            "M3U Playlist (*.m3u *.m3u8);;Všetky súbory (*)"
        )
        if not path:
            return
        self._ingest_paths([path])

    def _goto_current_track(self) -> None:
        idx = self.controller.current_index
        if 0 <= idx < self.playlist_widget.count():
            self.playlist_widget.setCurrentRow(idx)
            self.playlist_widget.scrollToItem(self.playlist_widget.item(idx))

    # ── Spánok / Spánok 2 ──────────────────────────────────────────────────────
    def _start_spanok(self, ktory: str) -> None:
        """Obe spankove tlacidla — lisia sa len tym, ktory zoznam pustia."""
        from music_player import spanky

        meno = spanky.nazov(ktory)
        index, missing = self.controller.start_spanok(ktory)
        if 0 <= index < self.playlist_widget.count():
            self.playlist_widget.setCurrentRow(index)
            self.playlist_widget.scrollToItem(self.playlist_widget.item(index))
        if missing:
            tail = "Zvyšok zoznamu hrá." if index >= 0 else "Prehrať sa nedalo nič."
            QMessageBox.warning(
                self,
                meno,
                "Tieto riadky zoznamu sa nedajú prehrať (súbor neexistuje, alebo to nie je "
                "podporované audio):\n\n" + "\n".join(missing) + "\n\n" + tail
                + f" Zoznam upravíš pravým klikom na tlačidlo „{meno}“.",
            )
            return
        if index < 0:
            answer = QMessageBox.question(
                self,
                meno,
                f"Zoznam skladieb pre „{meno}“ je zatiaľ prázdny.\n"
                "Chceš ho teraz zadefinovať?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._edit_spanok_list(ktory)

    def _selected_playlist_paths(self) -> list[str]:
        rows = sorted({index.row() for index in self.playlist_widget.selectedIndexes()})
        return [
            self.controller.playlist[row].path
            for row in rows
            if 0 <= row < len(self.controller.playlist)
        ]

    def _edit_spanok_list(self, ktory: str) -> None:
        from music_player import spanky

        meno = spanky.nazov(ktory)
        zoznam = spanky.load(ktory)
        dlg = _SpanokDialog(
            self,
            ktory,
            zoznam.tracks + zoznam.missing,
            {item.lower() for item in zoznam.missing},
            self._selected_playlist_paths(),
            spanky.nechat_v_playliste(ktory),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        saved = dlg.entries()
        try:
            path = spanky.save(ktory, saved)
            spanky.nastav_nechat(ktory, dlg.nechat_v_playliste())
        except OSError as exc:
            QMessageBox.warning(self, meno, f"Zoznam sa nepodarilo uložiť: {exc}")
            return
        self._show_message(f"{meno}: v zozname je {len(saved)} skladieb ({path.name}).")

    def _add_selection_to_spanok(self, ktory: str) -> None:
        from music_player import spanky

        meno = spanky.nazov(ktory)
        paths = self._selected_playlist_paths()
        if not paths:
            self._show_message("Vyber aspoň jednu skladbu.")
            return
        try:
            added, path = spanky.append(ktory, paths)
        except OSError as exc:
            QMessageBox.warning(self, meno, f"Zoznam sa nepodarilo uložiť: {exc}")
            return
        if added:
            self._show_message(f"{meno}: do zoznamu pribudlo {added} skladieb ({path.name}).")
        else:
            self._show_message(f"{meno}: vybrané skladby už v zozname sú.")

    # ── Záložky ────────────────────────────────────────────────────────────────
    def _ukaz_zalozky(self) -> None:
        """Menu pod tlacidlom: zalozky v poradi playlistu, pridanie a odobratie."""
        playlist = self.controller.playlist
        # V poradi playlistu, chybajuce na koniec — menu sa cita zhora ako playlist.
        polozky = sorted(
            (
                (self.controller.zalozka_index(zalozka), poradie, zalozka)
                for poradie, zalozka in enumerate(self.controller.zalozky)
            ),
            key=lambda polozka: (polozka[0] < 0, polozka[0]),
        )

        def popis(index: int, zalozka) -> str:
            if index < 0:
                return _skrat(Path(zalozka.path).stem, 60) + " — už nie je v playliste"
            return f"{index + 1}. " + _skrat(playlist[index].display_text, 70)

        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        if not polozky:
            menu.addAction("Zatiaľ žiadne záložky").setEnabled(False)
        for index, poradie, zalozka in polozky:
            akcia = menu.addAction(popis(index, zalozka))
            if index < 0:
                akcia.setEnabled(False)
            else:
                akcia.triggered.connect(lambda _=False, p=poradie: self._hraj_zalozku(p))

        menu.addSeparator()
        riadok = self._riadok_pre_zalozku()
        if riadok < 0:
            menu.addAction("Záložku dáš pravým klikom na skladbu v playliste").setEnabled(False)
        elif self.controller.zalozka_na_riadku(riadok) >= 0:
            menu.addAction(
                f"Označená skladba {riadok + 1}. už záložku má"
            ).setEnabled(False)
        else:
            pridat = menu.addAction(
                f"Pridať záložku: {riadok + 1}. " + _skrat(playlist[riadok].display_text, 60)
            )
            pridat.triggered.connect(lambda _=False, r=riadok: self._pridaj_zalozku(r))
        if polozky:
            odobrat = menu.addMenu("Odstrániť záložku")
            odobrat.setStyleSheet(_MENU_STYLE)
            for index, poradie, zalozka in polozky:
                odobrat.addAction(popis(index, zalozka)).triggered.connect(
                    lambda _=False, p=poradie: self._odober_zalozku(p)
                )
        menu.exec(self.zalozky_button.mapToGlobal(QPoint(0, self.zalozky_button.height())))

    def _riadok_pre_zalozku(self) -> int:
        """Skladba, na ktoru by sa dala zalozka z menu: oznacena, inak prave hrajuca."""
        riadky = sorted({index.row() for index in self.playlist_widget.selectedIndexes()})
        if riadky and riadky[0] < len(self.controller.playlist):
            return riadky[0]
        if 0 <= self.controller.current_index < len(self.controller.playlist):
            return self.controller.current_index
        return -1

    def _hraj_zalozku(self, poradie: int) -> None:
        index = self.controller.hraj_zalozku(poradie)
        if 0 <= index < self.playlist_widget.count():
            self.playlist_widget.setCurrentRow(index)
            self.playlist_widget.scrollToItem(self.playlist_widget.item(index))

    def _pridaj_zalozku(self, riadok: int) -> None:
        # Uklada sa hned: zalozka je zamerny krok a vecer po nom casto ide
        # "Vypnut PC po skonceni", kde sa na ulozenie pri zatvarani spoliehat neda.
        if self.controller.pridaj_zalozku(riadok):
            self.save_state()

    def _odober_zalozku(self, poradie: int) -> None:
        if not (0 <= poradie < len(self.controller.zalozky)):
            return
        meno = Path(self.controller.zalozky[poradie].path).stem
        self.controller.odober_zalozku(poradie)
        self.save_state()
        self._show_message(f"Záložka odstránená: {meno}")

    # ── settings ───────────────────────────────────────────────────────────────
    def _toggle_autostart(self, checked: bool) -> None:
        try:
            set_autostart(checked)
        except OSError as exc:
            self.autostart_checkbox.blockSignals(True)
            self.autostart_checkbox.setChecked(not checked)
            self.autostart_checkbox.blockSignals(False)
            QMessageBox.warning(self, "Autostart", f"Autostart sa nepodarilo zmeniť: {exc}")

    # ── stats ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _format_duration(ms: int) -> str:
        total_s = ms // 1000
        h, remainder = divmod(total_s, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            return f"{h}h {m:02d}m"
        return f"{m}m {s:02d}s"

    def _update_stats(self) -> None:
        playlist = self.controller.playlist
        total_tracks = len(playlist)
        total_ms = sum(t.duration_ms for t in playlist)

        selected = self.playlist_widget.selectedIndexes()
        sel_count = len(selected)
        sel_ms = 0
        if sel_count > 0:
            for idx in selected:
                row = idx.row()
                if 0 <= row < total_tracks:
                    sel_ms += playlist[row].duration_ms

        parts = [f"Playlist: {total_tracks} skladieb ({self._format_duration(total_ms)})"]
        if sel_count > 1:
            parts.append(f"Označených: {sel_count} ({self._format_duration(sel_ms)})")

        played = self.controller.total_tracks_played
        listened = self.controller._effective_listen_ms()
        if played > 0:
            parts.append(f"Celkovo prehraných: {played} ({self._format_duration(listened)})")

        self.stats_label.setText("  │  ".join(parts))

    # ── search ─────────────────────────────────────────────────────────────────
    def _toggle_search(self) -> None:
        if self._search_bar.isVisible():
            self._close_search()
        else:
            self._search_bar.show()
            self._search_bar.setFocus()
            self._search_bar.selectAll()

    def _close_search(self) -> None:
        self._search_bar.hide()
        self._search_bar.clear()
        self._search_matches = []
        self._search_match_index = -1
        self.playlist_widget.setFocus()

    def _on_search_text_changed(self, text: str) -> None:
        self._search_matches = []
        self._search_match_index = -1
        if not text:
            return
        text_lower = text.lower()
        for i in range(self.playlist_widget.count()):
            item = self.playlist_widget.item(i)
            if item and text_lower in item.text().lower():
                self._search_matches.append(i)
        if self._search_matches:
            self._search_match_index = 0
            self.playlist_widget.setCurrentRow(self._search_matches[0])
            self.playlist_widget.scrollToItem(self.playlist_widget.item(self._search_matches[0]))

    def _on_search_next(self) -> None:
        if not self._search_matches:
            return
        self._search_match_index = (self._search_match_index + 1) % len(self._search_matches)
        row = self._search_matches[self._search_match_index]
        self.playlist_widget.setCurrentRow(row)
        self.playlist_widget.scrollToItem(self.playlist_widget.item(row))

    def _toggle_shutdown(self, checked: bool) -> None:
        self.controller.shutdown_when_playlist_ends = checked
        if checked:
            self.sleep_checkbox.blockSignals(True)
            self.sleep_checkbox.setChecked(False)
            self.sleep_checkbox.blockSignals(False)
            self.controller.sleep_when_playlist_ends = False

    def _toggle_sleep(self, checked: bool) -> None:
        self.controller.sleep_when_playlist_ends = checked
        if checked:
            self.shutdown_checkbox.blockSignals(True)
            self.shutdown_checkbox.setChecked(False)
            self.shutdown_checkbox.blockSignals(False)
            self.controller.shutdown_when_playlist_ends = False

    def _on_scheduled_action_changed(self, index: int) -> None:
        action = ["none", "sleep", "shutdown"][index]
        self.scheduled_time_edit.setVisible(index != 0)
        self.scheduled_hint_label.setVisible(index != 0)
        if index != 0:
            t = self.scheduled_time_edit.time()
            hhmm = f"{t.hour():02d}:{t.minute():02d}"
            self.controller.scheduled_time = hhmm
        self.controller.set_scheduled_action(action)
        self._update_scheduled_time_hint()

    def _on_scheduled_time_changed(self, t: QTime) -> None:
        hhmm = f"{t.hour():02d}:{t.minute():02d}"
        self.controller.set_scheduled_time(hhmm)
        self._update_scheduled_time_hint()

    def _update_scheduled_time_hint(self) -> None:
        t = self.scheduled_time_edit.time()
        cur = QTime.currentTime()
        is_tomorrow = (t.hour() * 60 + t.minute()) <= (cur.hour() * 60 + cur.minute())
        self.scheduled_hint_label.setText(
            "hodiny:minúty — zajtra" if is_tomorrow else "hodiny:minúty"
        )

    def _on_scheduled_status_changed(self, message: str) -> None:
        if message:
            self._show_message(message)
        else:
            combo_index = self.scheduled_action_combo.currentIndex()
            if combo_index != 0:
                self.scheduled_action_combo.blockSignals(True)
                self.scheduled_action_combo.setCurrentIndex(0)
                self.scheduled_action_combo.blockSignals(False)
                self.scheduled_time_edit.setVisible(False)
                self.scheduled_hint_label.setVisible(False)

    # ── misc ───────────────────────────────────────────────────────────────────
    def _show_message(self, message: str) -> None:
        self.status_message_label.setText(message)
        self._refresh_stream_status()

    def _extract_local_paths(self, mime_data) -> list[str]:
        if not mime_data.hasUrls():
            return []
        paths: list[str] = []
        for url in mime_data.urls():
            if url.isLocalFile():
                local = url.toLocalFile()
                if local:
                    paths.append(local)
        return paths


def _read_audio_quality(path: str) -> str:
    """Return a short quality string, e.g. 'FLAC 44.1kHz 16bit' or 'MP3 320kbps'."""
    try:
        from mutagen import File as MutagenFile
        f = MutagenFile(path)
        if f is None:
            return ""
        info = f.info
        ext = Path(path).suffix.lower()
        sr = getattr(info, "sample_rate", 0)
        sr_str = f"{sr / 1000:.1f}kHz" if sr else ""

        if ext == ".flac":
            bits = getattr(info, "bits_per_sample", 0)
            parts = ["FLAC", sr_str, f"{bits}bit" if bits else ""]
        elif ext == ".mp3":
            br = getattr(info, "bitrate", 0)
            parts = ["MP3", f"{br // 1000}kbps" if br else "", sr_str]
        elif ext in (".m4a", ".aac"):
            br = getattr(info, "bitrate", 0)
            parts = ["AAC", f"{br // 1000}kbps" if br else "", sr_str]
        elif ext == ".ogg":
            br = getattr(info, "bitrate", 0)
            parts = ["OGG", f"{br // 1000}kbps" if br else "", sr_str]
        elif ext == ".wav":
            bits = getattr(info, "bits_per_sample", 0)
            parts = ["WAV", sr_str, f"{bits}bit" if bits else ""]
        elif ext == ".wma":
            br = getattr(info, "bitrate", 0)
            parts = ["WMA", f"{br // 1000}kbps" if br else "", sr_str]
        else:
            br = getattr(info, "bitrate", 0)
            parts = [ext[1:].upper(), f"{br // 1000}kbps" if br else "", sr_str]

        return "  ".join(p for p in parts if p)
    except Exception:
        return ""


def _format_ms(value: int) -> str:
    total_seconds = max(int(value), 0) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _skrat(text: str, dlzka: int) -> str:
    """Skrati text do menu, aby nazov albumu nenafukol menu cez celu obrazovku."""
    if len(text) <= dlzka:
        return text
    return text[: dlzka - 1].rstrip() + "…"
