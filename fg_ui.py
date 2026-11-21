"""FocusGuard GUI (Windows) - same Material-style dark UI with the analog dial timer.
Runs as a normal user: it reads the session state and asks Windows (UAC prompt) to start
a locked session through the elevated "--ctl" mode of this same program."""
import json, math, os, re, sys, time
from datetime import date
from pathlib import Path

try:
    from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
    from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPen
    from PyQt5.QtWidgets import (
        QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
        QListWidgetItem, QMessageBox, QPushButton, QStyle, QStyledItemDelegate,
        QTabWidget, QVBoxLayout, QWidget,
    )
except ImportError:  # also runs on PyQt6 (e.g. when testing)
    from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPen
    from PyQt6.QtWidgets import (
        QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
        QListWidgetItem, QMessageBox, QPushButton, QStyle, QStyledItemDelegate,
        QTabWidget, QVBoxLayout, QWidget,
    )

import fg_core

STATE = fg_core.STATE
HIST = fg_core.HIST
CONF = Path(os.environ.get("APPDATA", str(Path.home()))) / "FocusGuard" / "config.json"


def epos(e):
    """Mouse position as QPointF on both PyQt5 and PyQt6."""
    return e.position() if hasattr(e, "position") else e.localPos()


def resource_path(name):
    base = getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent))
    return os.path.join(base, name)


DEFAULT_BLOCK = [
    "facebook.com", "m.facebook.com", "web.facebook.com", "fb.com",
    "messenger.com", "instagram.com", "web.telegram.org", "t.me",
    "x.com", "twitter.com", "tiktok.com", "youtube.com", "m.youtube.com",
    "reddit.com", "discord.com", "web.whatsapp.com", "linkedin.com",
    "pinterest.com",
]
# Never blocked, even if a parent domain is in the block list
DEFAULT_ALLOW = [
    "gemini.google.com", "aistudio.google.com", "notebooklm.google.com",
    "chatgpt.com", "claude.ai", "perplexity.ai",
]

# ---------- Material-style palette (dark, teal primary) ----------
BG, SURFACE, SURFACE_HI = "#0F1419", "#171C23", "#212832"
OUTLINE, TRACK = "#3A424D", "#262D36"
TEXT, MUTED = "#E1E3E8", "#8A929E"
PRIMARY, ON_PRIMARY, PRIMARY_CONT = "#7FD1C4", "#00382F", "#00504A"

STYLE = """
QWidget { background: @BG; color: @TEXT; }
QLabel { background: transparent; }
QPushButton { background: @SURFACE_HI; border: none; border-radius: 18px; padding: 8px 18px; }
QFrame#card { background: @SURFACE; border-radius: 28px; }
QLabel#title { font-size: 24px; font-weight: 500; }
QLabel#hint { color: @MUTED; }
QLabel#pill { background: @SURFACE_HI; border-radius: 16px; padding: 8px 16px; color: @PRIMARY; font-weight: 500; }
QPushButton#filled { background: @PRIMARY; color: @ON_PRIMARY; border: none; border-radius: 28px; min-height: 56px; font-size: 16px; font-weight: 600; }
QPushButton#filled:hover { background: #9BE0D4; }
QPushButton#filled:disabled { background: @TRACK; color: #6B7380; }
QPushButton#chip { background: transparent; border: 1px solid @OUTLINE; border-radius: 17px; padding: 7px 16px; }
QPushButton#chip:hover { background: @SURFACE_HI; }
QPushButton#chip:checked { background: @PRIMARY_CONT; border: 1px solid @PRIMARY_CONT; color: #A6F2E4; }
QPushButton#chip:disabled { color: #5B6370; }
QPushButton#tonal { background: @SURFACE_HI; color: @PRIMARY; font-weight: 500; border-radius: 19px; padding: 9px 22px; min-height: 20px; }
QPushButton#tonal:hover { background: #2A323D; }
QPushButton#quiet { background: transparent; color: @MUTED; border-radius: 19px; padding: 9px 14px; min-height: 20px; }
QPushButton#quiet:hover { background: @SURFACE_HI; color: @TEXT; }
QLineEdit { background: @SURFACE_HI; border: 2px solid transparent; border-radius: 20px; padding: 9px 16px; selection-background-color: @PRIMARY_CONT; }
QLineEdit:focus { border: 2px solid @PRIMARY; }
QTabWidget, QStackedWidget { background: transparent; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: @MUTED; padding: 12px 18px; border: none; border-bottom: 3px solid transparent; font-weight: 500; }
QTabBar::tab:selected { color: @PRIMARY; border-bottom: 3px solid @PRIMARY; }
QTabBar::tab:hover { color: @TEXT; }
QWidget#panel { background: transparent; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px; }
QScrollBar::handle:vertical { background: @OUTLINE; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def qss():
    pal = {"BG": BG, "SURFACE_HI": SURFACE_HI, "SURFACE": SURFACE,
           "OUTLINE": OUTLINE, "TRACK": TRACK, "TEXT": TEXT, "MUTED": MUTED,
           "PRIMARY_CONT": PRIMARY_CONT, "ON_PRIMARY": ON_PRIMARY,
           "PRIMARY": PRIMARY}
    s = STYLE
    for k in sorted(pal, key=len, reverse=True):
        s = s.replace("@" + k, pal[k])
    return s


def read_json(path, default):
    return fg_core.read_json(path, default)


def normalize(raw):
    d = raw.strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0]
    d = re.sub(r"^www\.", "", d)
    return d if re.match(r"^([a-z0-9-]+\.)+[a-z]{2,}$", d) else ""


# ---------- Analog dial ----------
class Dial(QWidget):
    """Drag the handle around the face to pick 5..180 minutes.
    While a session is locked it shows the remaining time instead."""
    valueChanged = pyqtSignal(int)
    MAXM, STEP = 180, 5

    def __init__(self):
        super().__init__()
        self.value = 50
        self.locked = False
        self.remaining = 0.0
        self.lock_text = ""
        self._drag = False
        self.setMinimumSize(360, 360)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- state --
    def set_value(self, v):
        v = max(self.STEP, min(self.MAXM, int(v)))
        if v != self.value:
            self.value = v
            self.update()
        self.valueChanged.emit(self.value)

    def set_locked(self, locked, remaining_min=0.0, text=""):
        self.locked, self.remaining, self.lock_text = locked, remaining_min, text
        self.setCursor(Qt.CursorShape.ArrowCursor if locked
                       else Qt.CursorShape.PointingHandCursor)
        self.update()

    # -- geometry helpers --
    def _geom(self):
        s = min(self.width(), self.height())
        return QPointF(self.width() / 2, self.height() / 2), s / 2 - 6

    @staticmethod
    def _pt(c, ang, rad):
        return QPointF(c.x() + math.sin(ang) * rad, c.y() - math.cos(ang) * rad)

    # -- painting --
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, r = self._geom()

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SURFACE))
        p.drawEllipse(c, r, r)

        # ticks: one per 5 min, major every 15 min
        for i in range(36):
            major = i % 3 == 0
            pen = QPen(QColor(MUTED if major else OUTLINE), 2.2 if major else 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            a = math.radians(i * 10)
            p.drawLine(self._pt(c, a, r * (0.89 if major else 0.925)),
                       self._pt(c, a, r * 0.96))

        # numbers
        f = QFont(self.font())
        f.setPointSizeF(max(8.0, r * 0.065))
        p.setFont(f)
        fm = QFontMetricsF(f)
        p.setPen(QColor(MUTED))
        for i in range(0, 36, 3):
            t = str((i * 5) or 180)
            pos = self._pt(c, math.radians(i * 10), r * 0.78)
            p.drawText(QPointF(pos.x() - fm.horizontalAdvance(t) / 2,
                               pos.y() + (fm.ascent() - fm.descent()) / 2), t)

        # track + progress arc
        tr, w = r * 0.56, r * 0.10
        rect = QRectF(c.x() - tr, c.y() - tr, 2 * tr, 2 * tr)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(TRACK), w)
        p.setPen(pen)
        p.drawEllipse(c, tr, tr)

        minutes = self.remaining if self.locked else self.value
        span = min(max(minutes, 0), self.MAXM) / self.MAXM * 360
        pen = QPen(QColor(PRIMARY), w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        if span >= 359.5:
            p.drawEllipse(c, tr, tr)
        elif span > 0.5:
            p.drawArc(rect, 90 * 16, int(-span * 16))

        # handle
        hp = self._pt(c, math.radians(span), tr)
        p.setPen(Qt.PenStyle.NoPen)
        if self._drag:
            p.setBrush(QColor(127, 209, 196, 60))
            p.drawEllipse(hp, w * 1.7, w * 1.7)
        p.setBrush(QColor(PRIMARY))
        p.drawEllipse(hp, w * (0.7 if self.locked else 0.95), w * (0.7 if self.locked else 0.95))
        if not self.locked:
            p.setBrush(QColor(ON_PRIMARY))
            p.drawEllipse(hp, w * 0.3, w * 0.3)

        # centre text
        if self.locked:
            main, sub = self.lock_text, "remaining"
        else:
            main = str(self.value)
            sub = "minutes" if self.value < 60 else f"minutes ({self.value // 60} h {self.value % 60:02d})"
        mf = QFont(self.font())
        mf.setPointSizeF(r * (0.17 if len(main) > 5 else 0.26))
        mf.setWeight(QFont.Weight.Light)
        p.setFont(mf)
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(c.x() - tr, c.y() - r * 0.30, 2 * tr, r * 0.40),
                   Qt.AlignmentFlag.AlignCenter, main)
        sf = QFont(self.font())
        sf.setPointSizeF(max(8.0, r * 0.07))
        p.setFont(sf)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(c.x() - tr, c.y() + r * 0.10, 2 * tr, r * 0.14),
                   Qt.AlignmentFlag.AlignCenter, sub)

    # -- interaction --
    def _set_from(self, pt):
        c, _ = self._geom()
        d = pt - c
        ang = math.degrees(math.atan2(d.x(), -d.y())) % 360
        m = round(ang / 360 * self.MAXM / self.STEP) * self.STEP
        if m <= 0:
            m = self.MAXM if self.value > self.MAXM / 2 else self.STEP
        m = max(self.STEP, min(self.MAXM, m))
        if m != self.value:
            self.value = m
            self.valueChanged.emit(m)
        self.update()

    def mousePressEvent(self, e):
        if self.locked:
            return
        self._drag = True
        self._set_from(epos(e))

    def mouseMoveEvent(self, e):
        if self._drag:
            self._set_from(epos(e))

    def mouseReleaseEvent(self, _e):
        self._drag = False
        self.update()

    def wheelEvent(self, e):
        if not self.locked:
            step = self.STEP if e.angleDelta().y() > 0 else -self.STEP
            self.set_value(self.value + step)


# ---------- Site list with Material switches ----------
ROLE = Qt.ItemDataRole.UserRole


class SwitchDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 46)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect)
        on = bool(index.data(ROLE))
        p.setPen(Qt.PenStyle.NoPen)
        if option.state & QStyle.StateFlag.State_Selected:
            p.setBrush(QColor(SURFACE_HI))
            p.drawRoundedRect(r.adjusted(4, 2, -4, -2), 14, 14)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            p.setBrush(QColor("#1D232B"))
            p.drawRoundedRect(r.adjusted(4, 2, -4, -2), 14, 14)
        p.setPen(QColor(TEXT if on else MUTED))
        p.drawText(QRectF(r.left() + 18, r.top(), r.width() - 100, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   index.data(Qt.ItemDataRole.DisplayRole))
        # switch
        sw, sh = 44.0, 26.0
        x, y = r.right() - 18 - sw, r.center().y() - sh / 2
        track = QRectF(x, y, sw, sh)
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(PRIMARY))
        else:
            p.setPen(QPen(QColor("#6B7380"), 2))
            p.setBrush(QColor(TRACK))
        p.drawRoundedRect(track.adjusted(1, 1, -1, -1), sh / 2, sh / 2)
        kr = 9.5 if on else 6.5
        kx = x + sw - sh / 2 if on else x + sh / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ON_PRIMARY if on else "#9AA2AE"))
        p.drawEllipse(QPointF(kx, y + sh / 2), kr, kr)
        p.restore()


class SiteList(QListWidget):
    toggled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setItemDelegate(SwitchDelegate(self))
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)

    def mousePressEvent(self, e):
        item = self.itemAt(epos(e).toPoint())
        if item and epos(e).x() > self.viewport().width() - 90:
            item.setData(ROLE, not item.data(ROLE))
            self.toggled.emit()
        super().mousePressEvent(e)


class ListPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, items):
        super().__init__()
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        self.list = SiteList()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Add a site, e.g. example.com")
        add = QPushButton("Add")
        add.setObjectName("tonal")
        rm = QPushButton("Remove")
        rm.setObjectName("quiet")
        row.addWidget(self.edit, 1)
        row.addWidget(add)
        row.addWidget(rm)
        lay.addLayout(row)
        for d, c in items:
            self._add(d, c)
        add.clicked.connect(self.add_clicked)
        self.edit.returnPressed.connect(self.add_clicked)
        rm.clicked.connect(self.remove_clicked)
        self.list.toggled.connect(self.changed)

    def _add(self, domain, on=True):
        it = QListWidgetItem(domain)
        it.setData(ROLE, bool(on))
        self.list.addItem(it)

    def add_clicked(self):
        d = normalize(self.edit.text())
        if not d:
            QMessageBox.warning(self, "Invalid site", "Enter a domain like example.com")
            return
        if d not in [t for t, _ in self.items()]:
            self._add(d)
            self.changed.emit()
        self.edit.clear()

    def remove_clicked(self):
        it = self.list.currentItem()
        if it:
            self.list.takeItem(self.list.row(it))
            self.changed.emit()

    def items(self):
        return [(self.list.item(i).text(), bool(self.list.item(i).data(ROLE)))
                for i in range(self.list.count())]

    def checked(self):
        return [t for t, c in self.items() if c]


# ---------- Main window ----------
class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FocusGuard")
        self.setMinimumSize(980, 620)

        conf = read_json(CONF, {})
        self.block = ListPanel(conf.get("block") or [[d, True] for d in DEFAULT_BLOCK])
        self.allow = ListPanel(conf.get("allow") or [[d, True] for d in DEFAULT_ALLOW])
        self.block.changed.connect(self.save_conf)
        self.allow.changed.connect(self.save_conf)

        # header
        title = QLabel("FocusGuard")
        title.setObjectName("title")
        self.today = QLabel("")
        self.today.setObjectName("pill")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.today)

        # left: dial + chips + start
        self.dial = Dial()
        self.dial.valueChanged.connect(self.sync_chips)
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.chips = []
        chips_row = QHBoxLayout()
        chips_row.addStretch()
        for m in (25, 50, 90, 120):
            b = QPushButton(f"{m} min")
            b.setObjectName("chip")
            b.setCheckable(True)
            b.clicked.connect(lambda _c, v=m: self.dial.set_value(v))
            self.chips.append((m, b))
            chips_row.addWidget(b)
        chips_row.addStretch()

        self.start_btn = QPushButton("Start focus session")
        self.start_btn.setObjectName("filled")
        self.start_btn.clicked.connect(self.start)

        left = QVBoxLayout()
        left.setSpacing(14)
        left.addWidget(self.dial, 1)
        left.addWidget(self.hint)
        left.addLayout(chips_row)
        left.addSpacing(6)
        left.addWidget(self.start_btn)

        # right: site card
        tabs = QTabWidget()
        tabs.addTab(self.block, "Blocked sites")
        tabs.addTab(self.allow, "Always allowed")
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 14, 22, 20)
        cl.addWidget(tabs)

        body = QHBoxLayout()
        body.setSpacing(28)
        body.addLayout(left, 5)
        body.addWidget(card, 4)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 28)
        root.setSpacing(18)
        root.addLayout(head)
        root.addLayout(body, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.sync_chips()
        self.refresh()

    def sync_chips(self, *_):
        for m, b in self.chips:
            b.setChecked(self.dial.value == m)

    def save_conf(self):
        CONF.parent.mkdir(parents=True, exist_ok=True)
        CONF.write_text(json.dumps({"block": self.block.items(),
                                    "allow": self.allow.items()}, indent=2),
                        encoding="utf-8")

    def effective_domains(self):
        allow = self.allow.checked()
        def allowed(d):
            return any(d == a or d.endswith("." + a) for a in allow)
        return [d for d in self.block.checked() if not allowed(d)]

    def refresh(self):
        st = read_json(STATE, None)
        now = time.time()
        locked = bool(st and st.get("end", 0) > now)
        if locked:
            rem = max(0, int(st["end"] - now))
            h, r = divmod(rem, 3600)
            m, s = divmod(r, 60)
            self.dial.set_locked(True, rem / 60, f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}")
            self.hint.setText(f"{len(st['domains'])} sites blocked. Stay with it.")
            self.start_btn.setText("Locked until " + time.strftime("%H:%M", time.localtime(st["end"])))
        else:
            self.dial.set_locked(False)
            self.hint.setText("Drag the handle to set your session length")
            self.start_btn.setText("Start focus session")
        for w in [self.start_btn, self.block, self.allow] + [b for _, b in self.chips]:
            w.setEnabled(not locked)

        today = date.today().strftime("%Y-%m-%d")
        total = sum(e["minutes"] for e in read_json(HIST, []) if e.get("date") == today)
        self.today.setText(f"{total // 60} h {total % 60:02d} min studied today")

    def start(self):
        domains = self.effective_domains()
        if not domains:
            QMessageBox.warning(self, "Nothing to block", "Turn on at least one site.")
            return
        mins = self.dial.value
        ok = QMessageBox.question(
            self, "Start session",
            f"Block {len(domains)} sites for {mins} minutes?\n"
            "You can't stop it early.\n\n"
            "Windows will now ask for permission (UAC) - click Yes.")
        if ok != QMessageBox.StandardButton.Yes:
            return
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Starting...")
        code = fg_core.run_elevated_and_wait(
            ["start", str(mins), *domains], pump=QApplication.processEvents)
        if code is None:
            QMessageBox.warning(self, "Could not start", "Permission was cancelled.")
        elif code != 0:
            QMessageBox.warning(self, "Could not start",
                                fg_core.read_ctl_error() or f"Failed (code {code}).")
        self.refresh()


def run_gui():
    try:  # sharp rendering on high-DPI / scaled Windows screens (Qt5)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    except AttributeError:
        pass
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("FocusGuard")
    app.setWindowIcon(QIcon(resource_path("focusguard.ico")))
    font = QFont()
    font.setFamilies(["Roboto", "Segoe UI", "Noto Sans", "Arial"])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(qss())
    w = Main()
    w.show()
    return app, w


def selftest(out_path):
    """Used by the GitHub build: start the UI, check the hosts logic, then quit."""
    lines = []
    try:
        block = fg_core.build_block(["example.com"])
        assert "0.0.0.0 www.example.com" in block
        assert fg_core.strip_block("a\n" + block + "b\n") == "a\nb\n"
        lines.append("hosts logic ok")
        app, w = run_gui()
        QTimer.singleShot(800, app.quit)
        app.exec() if hasattr(app, "exec") else app.exec_()
        lines.append("ui ok")
        code = 0
    except Exception as e:
        lines.append("FAILED: %r" % (e,))
        code = 1
    try:
        Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass
    return code
