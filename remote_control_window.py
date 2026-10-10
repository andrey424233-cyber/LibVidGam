"""Компактный пульт управления телефоном с захватом мыши.

Захват мыши: кликните по зелёной зоне — мышь «залипнет» в окне.
Esc или правый клик — освободить.

Колёсико мыши над пультом = прокрутка списка на телефоне.
"""
import os

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QPushButton, QGroupBox, QCheckBox,
                             QMessageBox, QApplication, QSlider)


try:
    from pynput import keyboard as pynput_kb
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


CURSOR_STEP = 0.025
MOUSE_PIXEL_TO_NORM = 0.001

# Сколько пикселей прокрутки за один "щелчок" колеса
SCROLL_PIXELS_PER_TICK = 200


class MouseCaptureZone(QWidget):
    """Зона захвата мыши."""

    delta = pyqtSignal(int, int)
    tapped = pyqtSignal()
    captured = pyqtSignal()
    released = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_default_style()

        self._captured = False
        self._center = None
        self._sensitivity = 1.0
        self._system_cursor_hidden = False

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)

        self._label = QLabel("🔒  Кликните здесь для захвата мыши")
        self._label.setAlignment(Qt.AlignCenter)
        v.addWidget(self._label)

        self._hint = QLabel("ЛКМ — тап  ·  ПКМ или Esc — освободить")
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        v.addWidget(self._hint)

    def _apply_default_style(self):
        self.setStyleSheet("""
            MouseCaptureZone {
                background-color: #1f2a1f;
                border: 2px solid #3a4a3a;
                border-radius: 8px;
            }
            MouseCaptureZone:hover { border-color: #27ae60; }
        """)
        if hasattr(self, '_label'):
            self._label.setStyleSheet(
                "QLabel { color: #a0d0a0; font-size: 13px; font-weight: bold;"
                " background: transparent; border: none; }"
            )
        if hasattr(self, '_hint'):
            self._hint.setStyleSheet(
                "QLabel { color: #777; font-size: 10px;"
                " background: transparent; border: none; }"
            )

    def _apply_captured_style(self):
        self.setStyleSheet("""
            MouseCaptureZone {
                background-color: #2f1a1a;
                border: 2px solid #c0392b;
                border-radius: 8px;
            }
        """)
        self._label.setStyleSheet(
            "QLabel { color: #ffd0d0; font-size: 13px; font-weight: bold;"
            " background: transparent; border: none; }"
        )
        self._hint.setStyleSheet(
            "QLabel { color: #a55; font-size: 10px;"
            " background: transparent; border: none; }"
        )

    def set_sensitivity(self, value):
        self._sensitivity = max(0.1, min(5.0, float(value)))

    def is_captured(self):
        return self._captured

    def capture(self):
        if self._captured:
            return
        self._captured = True
        self.setCursor(Qt.BlankCursor)
        self._hide_system_cursor()
        self._center = self.mapToGlobal(self.rect().center())
        try:
            QCursor.setPos(self._center)
        except Exception:
            pass
        self._label.setText("🔓  Мышь захвачена — Esc для выхода")
        self._apply_captured_style()
        self._timer.start()
        self.captured.emit()

    def release(self):
        if not self._captured:
            return
        self._captured = False
        self._timer.stop()
        self.setCursor(Qt.PointingHandCursor)
        self._show_system_cursor()
        if self._center:
            try:
                QCursor.setPos(self._center)
            except Exception:
                pass
        self._label.setText("🔒  Кликните здесь для захвата мыши")
        self._apply_default_style()
        self.released.emit()

    def toggle(self):
        if self._captured:
            self.release()
        else:
            self.capture()

    def _hide_system_cursor(self):
        if self._system_cursor_hidden:
            return
        try:
            import ctypes
            for _ in range(20):
                if ctypes.windll.user32.ShowCursor(False) < 0:
                    break
            self._system_cursor_hidden = True
        except Exception:
            pass

    def _show_system_cursor(self):
        if not self._system_cursor_hidden:
            return
        try:
            import ctypes
            for _ in range(20):
                if ctypes.windll.user32.ShowCursor(True) >= 0:
                    break
            self._system_cursor_hidden = False
        except Exception:
            pass

    def _tick(self):
        if not self._captured or self._center is None:
            return
        try:
            pos = QCursor.pos()
        except Exception:
            return

        dx = pos.x() - self._center.x()
        dy = pos.y() - self._center.y()

        if dx == 0 and dy == 0:
            return
        if abs(dx) < 1 and abs(dy) < 1:
            return

        self.delta.emit(dx, dy)

        try:
            QCursor.setPos(self._center)
        except Exception:
            pass

    def mousePressEvent(self, event):
        if not self._captured:
            self.capture()
        else:
            if event.button() == Qt.LeftButton:
                self.tapped.emit()
            elif event.button() == Qt.RightButton:
                self.release()


class RemoteControlWindow(QWidget):
    """Компактный пульт управления телефоном."""

    def __init__(self, db, mobile_server, parent=None):
        super().__init__(parent)
        self.db = db
        self.server = mobile_server

        self.setWindowTitle("Пульт")
        self.setFixedSize(400, 680)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowStaysOnTopHint
            | Qt.WindowCloseButtonHint
        )

        self._setup_style()
        self._build_ui()
        self._position_bottom_right()

        self._pynput_listener = None

        self._update_status_timer = QTimer(self)
        self._update_status_timer.setInterval(1500)
        self._update_status_timer.timeout.connect(self._refresh_status)
        self._update_status_timer.start()

        self._refresh_status()

    def _setup_style(self):
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #e0e0e0; }
            QLabel { color: #e0e0e0; background: transparent; }
            QGroupBox {
                color: #ffffff; border: 1px solid #2a2a2a;
                border-radius: 8px; margin-top: 10px; padding-top: 12px;
                background-color: transparent;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 5px;
                color: #ffffff; font-weight: bold; font-size: 12px;
            }
            QPushButton {
                background-color: #2a2a2a; color: #e0e0e0;
                border: none; border-radius: 6px;
                padding: 6px 10px; font-size: 13px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton:pressed { background-color: #c0392b; }
            QPushButton#accent {
                background-color: #c0392b; color: white; font-weight: bold;
            }
            QPushButton#accent:hover { background-color: #e74c3c; }
            QCheckBox { color: #e0e0e0; font-size: 12px; }
            QSlider::groove:horizontal {
                height: 4px; background: #2a2a2a; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #c0392b; width: 14px; height: 14px;
                margin: -5px 0; border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #c0392b; border-radius: 2px;
            }
        """)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.status_label = QLabel("Подключений: 0")
        self.status_label.setStyleSheet("QLabel { color: #e67e22; font-size: 13px; }")
        top.addWidget(self.status_label)
        top.addStretch()
        self.chk_global = QCheckBox("Глоб. клавиши")
        self.chk_global.setEnabled(HAS_PYNPUT)
        self.chk_global.setChecked(False)
        self.chk_global.toggled.connect(self._on_global_toggled)
        top.addWidget(self.chk_global)
        root.addLayout(top)

        self.zone = MouseCaptureZone()
        self.zone.delta.connect(self._on_zone_delta)
        self.zone.tapped.connect(lambda: self._send("tap_here"))
        root.addWidget(self.zone)

        sens_row = QHBoxLayout()
        sens_row.addWidget(QLabel("Чувств.:"))
        self.sens_slider = QSlider(Qt.Horizontal)
        self.sens_slider.setMinimum(10)
        self.sens_slider.setMaximum(300)
        self.sens_slider.setValue(100)
        self.sens_slider.valueChanged.connect(self._on_sensitivity_changed)
        sens_row.addWidget(self.sens_slider, 1)
        self.sens_label = QLabel("1.00×")
        self.sens_label.setFixedWidth(50)
        self.sens_label.setStyleSheet("QLabel { color: #888; font-size: 11px; }")
        sens_row.addWidget(self.sens_label)
        root.addLayout(sens_row)

        self.chk_auto_capture = QCheckBox("Захватывать мышь при открытии пульта")
        self.chk_auto_capture.setChecked(False)
        root.addWidget(self.chk_auto_capture)

        arrows_group = QGroupBox("Стрелки (альтернатива мыши)")
        g = QGridLayout()
        g.setSpacing(4)

        self.btn_up = QPushButton("↑")
        self.btn_up.setFixedHeight(44)
        self.btn_up.clicked.connect(lambda: self._send_cursor_delta(0, -CURSOR_STEP))

        self.btn_down = QPushButton("↓")
        self.btn_down.setFixedHeight(44)
        self.btn_down.clicked.connect(lambda: self._send_cursor_delta(0, CURSOR_STEP))

        self.btn_left = QPushButton("←")
        self.btn_left.setFixedHeight(44)
        self.btn_left.clicked.connect(lambda: self._send_cursor_delta(-CURSOR_STEP, 0))

        self.btn_right = QPushButton("→")
        self.btn_right.setFixedHeight(44)
        self.btn_right.clicked.connect(lambda: self._send_cursor_delta(CURSOR_STEP, 0))

        self.btn_enter = QPushButton("⏎")
        self.btn_enter.setFixedHeight(44)
        self.btn_enter.setObjectName("accent")
        self.btn_enter.clicked.connect(lambda: self._send("tap_here"))

        self.btn_center = QPushButton("⌖ центр")
        self.btn_center.setFixedHeight(28)
        self.btn_center.clicked.connect(lambda: self._send("cursor_reset"))

        g.addWidget(self.btn_up, 0, 1)
        g.addWidget(self.btn_left, 1, 0)
        g.addWidget(self.btn_enter, 1, 1)
        g.addWidget(self.btn_right, 1, 2)
        g.addWidget(self.btn_down, 2, 1)
        g.addWidget(self.btn_center, 3, 0, 1, 3)

        arrows_group.setLayout(g)
        root.addWidget(arrows_group)

        media_group = QGroupBox("Медиа")
        m = QHBoxLayout()
        m.setSpacing(6)

        self.btn_play = QPushButton("▶/⏸")
        self.btn_play.setFixedHeight(40)
        self.btn_play.clicked.connect(lambda: self._send("toggle"))
        m.addWidget(self.btn_play)

        self.btn_vr = QPushButton("🥽 VR")
        self.btn_vr.setFixedHeight(40)
        self.btn_vr.clicked.connect(lambda: self._send("vr_toggle"))
        m.addWidget(self.btn_vr)

        self.btn_close = QPushButton("✕ Esc")
        self.btn_close.setFixedHeight(40)
        self.btn_close.clicked.connect(lambda: self._send("close"))
        m.addWidget(self.btn_close)

        media_group.setLayout(m)
        root.addWidget(media_group)

        vr_group = QGroupBox("VR настройка")
        v = QGridLayout()
        v.setSpacing(4)

        self.btn_shift_l10 = QPushButton("⇦⇦")
        self.btn_shift_l10.clicked.connect(lambda: self._send("vr_shift", delta=-10))
        self.btn_shift_l1 = QPushButton("⇦")
        self.btn_shift_l1.clicked.connect(lambda: self._send("vr_shift", delta=-1))
        self.btn_shift_r1 = QPushButton("⇨")
        self.btn_shift_r1.clicked.connect(lambda: self._send("vr_shift", delta=1))
        self.btn_shift_r10 = QPushButton("⇨⇨")
        self.btn_shift_r10.clicked.connect(lambda: self._send("vr_shift", delta=10))

        v.addWidget(self.btn_shift_l10, 0, 0)
        v.addWidget(self.btn_shift_l1, 0, 1)
        v.addWidget(self.btn_shift_r1, 0, 2)
        v.addWidget(self.btn_shift_r10, 0, 3)

        self.btn_zoom_out = QPushButton("−зум")
        self.btn_zoom_out.clicked.connect(lambda: self._send("vr_zoom", delta=-0.05))
        self.btn_zoom_in = QPushButton("+зум")
        self.btn_zoom_in.clicked.connect(lambda: self._send("vr_zoom", delta=0.05))
        self.btn_shift_reset = QPushButton("сбр.сдв.")
        self.btn_shift_reset.clicked.connect(lambda: self._send("vr_shift_reset"))
        self.btn_zoom_reset = QPushButton("сбр.зум")
        self.btn_zoom_reset.clicked.connect(lambda: self._send("vr_zoom_reset"))

        v.addWidget(self.btn_zoom_out, 1, 0)
        v.addWidget(self.btn_zoom_in, 1, 1)
        v.addWidget(self.btn_shift_reset, 1, 2)
        v.addWidget(self.btn_zoom_reset, 1, 3)

        vr_group.setLayout(v)
        root.addWidget(vr_group)

        util_group = QGroupBox("Ещё")
        u = QHBoxLayout()
        u.setSpacing(6)

        self.btn_seek_back = QPushButton("⏪5с")
        self.btn_seek_back.clicked.connect(lambda: self._send("seek_rel", delta=-5000))
        u.addWidget(self.btn_seek_back)

        self.btn_seek_fwd = QPushButton("⏩5с")
        self.btn_seek_fwd.clicked.connect(lambda: self._send("seek_rel", delta=5000))
        u.addWidget(self.btn_seek_fwd)

        self.btn_vol_down = QPushButton("🔉")
        self.btn_vol_down.clicked.connect(lambda: self._send("volume_down"))
        u.addWidget(self.btn_vol_down)

        self.btn_vol_up = QPushButton("🔊")
        self.btn_vol_up.clicked.connect(lambda: self._send("volume_up"))
        u.addWidget(self.btn_vol_up)

        util_group.setLayout(u)
        root.addWidget(util_group)

        root.addStretch()

    def _position_bottom_right(self):
        try:
            screen = QApplication.primaryScreen().availableGeometry()
            x = screen.right() - self.width() - 20
            y = screen.bottom() - self.height() - 20
            self.move(max(0, x), max(0, y))
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if self.chk_auto_capture.isChecked():
            QTimer.singleShot(200, self.zone.capture)

    # ---------- команды ----------

    def _send(self, cmd, **kwargs):
        if self.server is None:
            return
        payload = {"cmd": cmd}
        payload.update(kwargs)
        try:
            self.server.send_command(payload)
        except Exception as e:
            print(f"[remote] send: {e}")

    def _send_cursor_delta(self, dx, dy):
        self._send("cursor_delta", dx=round(dx, 4), dy=round(dy, 4))

    def _on_zone_delta(self, dx, dy):
        sens = self.zone._sensitivity
        ndx = dx * MOUSE_PIXEL_TO_NORM * sens
        ndy = dy * MOUSE_PIXEL_TO_NORM * sens
        ndx = max(-0.15, min(0.15, ndx))
        ndy = max(-0.15, min(0.15, ndy))
        self._send("cursor_delta", dx=round(ndx, 4), dy=round(ndy, 4))

    def _on_sensitivity_changed(self, value):
        sens = value / 100.0
        self.zone.set_sensitivity(sens)
        self.sens_label.setText(f"{sens:.2f}×")

    # ---------- колёсико мыши ----------

    def wheelEvent(self, event):
        """Прокрутка списка на телефоне колёсиком."""
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        if delta == 0:
            return

        # Знак: колесо вниз = отрицательный delta = прокрутка вниз (dy > 0)
        dy = int(-delta / 120.0 * SCROLL_PIXELS_PER_TICK)
        if dy == 0:
            return

        self._send("scroll", dy=dy)
        event.accept()

    # ---------- статус ----------

    def _refresh_status(self):
        n = 0
        try:
            n = self.server.client_count() if self.server else 0
        except Exception:
            pass
        self.status_label.setText(f"Подключений: {n}")
        color = "#27ae60" if n > 0 else "#e67e22"
        self.status_label.setStyleSheet(
            f"QLabel {{ color: {color}; font-size: 13px; }}"
        )

    def focusOutEvent(self, event):
        if self.zone.is_captured():
            self.zone.release()
        super().focusOutEvent(event)

    def closeEvent(self, event):
        try:
            self.zone.release()
        except Exception:
            pass
        self._stop_pynput()
        try:
            self._update_status_timer.stop()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------- клавиатура ----------

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        if key == Qt.Key_Escape:
            if self.zone.is_captured():
                self.zone.release()
                return
            self._send("close")
            return

        if self.zone.is_captured():
            if key == Qt.Key_Space or key in (Qt.Key_Return, Qt.Key_Enter):
                self._send("tap_here")
                return

        if key == Qt.Key_Up and not (mods & Qt.ShiftModifier) and not (mods & Qt.ControlModifier):
            self._send_cursor_delta(0, -CURSOR_STEP)
            return
        if key == Qt.Key_Down and not (mods & Qt.ShiftModifier) and not (mods & Qt.ControlModifier):
            self._send_cursor_delta(0, CURSOR_STEP)
            return
        if key == Qt.Key_Left and not (mods & Qt.ShiftModifier) and not (mods & Qt.ControlModifier):
            self._send_cursor_delta(-CURSOR_STEP, 0)
            return
        if key == Qt.Key_Right and not (mods & Qt.ShiftModifier) and not (mods & Qt.ControlModifier):
            self._send_cursor_delta(CURSOR_STEP, 0)
            return

        if key == Qt.Key_Left and (mods & Qt.ShiftModifier) and not (mods & Qt.ControlModifier):
            self._send("seek_rel", delta=-5000)
            return
        if key == Qt.Key_Right and (mods & Qt.ShiftModifier) and not (mods & Qt.ControlModifier):
            self._send("seek_rel", delta=5000)
            return

        if key == Qt.Key_Left and (mods & Qt.ControlModifier):
            self._send("seek_rel", delta=-30000)
            return
        if key == Qt.Key_Right and (mods & Qt.ControlModifier):
            self._send("seek_rel", delta=30000)
            return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._send("tap_here")
            return

        if key == Qt.Key_Space:
            self._send("toggle")
            return

        if key == Qt.Key_V:
            self._send("vr_toggle")
            return

        if key == Qt.Key_BracketLeft:
            self._send("vr_shift", delta=-10)
            return
        if key == Qt.Key_BracketRight:
            self._send("vr_shift", delta=10)
            return
        if key == Qt.Key_Backslash:
            self._send("vr_shift_reset")
            return

        if key == Qt.Key_Minus:
            self._send("vr_zoom", delta=-0.05)
            return
        if key == Qt.Key_Equal:
            self._send("vr_zoom", delta=0.05)
            return
        if key == Qt.Key_0:
            self._send("vr_zoom_reset")
            return

        if key == Qt.Key_PageUp:
            self._send("volume_up")
            return
        if key == Qt.Key_PageDown:
            self._send("volume_down")
            return

        super().keyPressEvent(event)

    # ---------- pynput ----------

    def _on_global_toggled(self, checked):
        if not HAS_PYNPUT:
            return
        if checked:
            self._start_pynput()
        else:
            self._stop_pynput()

    def _start_pynput(self):
        if self._pynput_listener is not None:
            return
        try:
            def on_press(key):
                try:
                    if key == pynput_kb.Key.up:
                        self._send_cursor_delta(0, -CURSOR_STEP)
                    elif key == pynput_kb.Key.down:
                        self._send_cursor_delta(0, CURSOR_STEP)
                    elif key == pynput_kb.Key.left:
                        self._send_cursor_delta(-CURSOR_STEP, 0)
                    elif key == pynput_kb.Key.right:
                        self._send_cursor_delta(CURSOR_STEP, 0)
                    elif key == pynput_kb.Key.enter:
                        self._send("tap_here")
                    elif key == pynput_kb.Key.space:
                        self._send("toggle")
                    elif key == pynput_kb.Key.esc:
                        self._send("close")
                except Exception as e:
                    print(f"[remote] pynput: {e}")

            self._pynput_listener = pynput_kb.Listener(on_press=on_press)
            self._pynput_listener.start()
        except Exception as e:
            QMessageBox.warning(self, "pynput", f"Не удалось запустить: {e}")
            self.chk_global.setChecked(False)

    def _stop_pynput(self):
        if self._pynput_listener is not None:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass
            self._pynput_listener = None