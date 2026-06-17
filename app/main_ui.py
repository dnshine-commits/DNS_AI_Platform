"""
Emergency Bell - PyQt5 Touch Kiosk UI v2 (1024x600 최적화)

화면 구조:
  IDLE (좌우 분할)
   ├─ 좌측 터치 → 예방·관리 메뉴 (아차사고/TBM/관리자/환경설정) + 뒤로가기
   └─ 우측 터치 → 긴급 메뉴 (구급/화재/작업중지/관리자) + 뒤로가기

  → 카테고리 선택 → FlowScreen (워크플로우 진행)
       ├─ 일반: 자동 진행
       └─ 아차사고/TBM: 종료 버튼으로 즉시 전사 시작
  → CompleteScreen (완료)

  환경 설정 → SettingsScreen (마이크 인덱스, 모델 등)
"""
import sys
import asyncio
import logging
from datetime import datetime
from pathlib import Path

import sounddevice as sd

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame, QGridLayout, QGraphicsDropShadowEffect,
    QSizePolicy, QScrollArea, QShortcut, QSpacerItem, QComboBox,
)
from PyQt5.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal,
    QThread, QSize, QRect,
)
from PyQt5.QtGui import (
    QFont, QFontDatabase, QColor, QPalette, QPainter, QPen, QBrush,
    QIcon, QCursor, QKeySequence,
)

import qasync

from . import config, workflow
from .workflow import FlowEvent, FLOWS

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ===========================================================
# 공통 스타일 (1024x600 컴팩트 버전)
# ===========================================================
STYLE = f"""
QWidget {{
    background-color: {config.COLORS["bg"]};
    color: {config.COLORS["text"]};
    font-family: "JetBrains Mono", "D2Coding", "NanumGothicCoding", monospace;
}}
QFrame#panel {{
    background-color: {config.COLORS["bg_panel"]};
    border: 1px solid {config.COLORS["border"]};
    border-radius: 4px;
}}
QPushButton#backBtn {{
    background: transparent;
    color: {config.COLORS['text_dim']};
    border: 1px solid {config.COLORS['border']};
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 12px;
    letter-spacing: 1px;
}}
QPushButton#backBtn:pressed {{
    background-color: {config.COLORS['bg_panel']};
    color: {config.COLORS['text']};
}}
QPushButton#stopBtn {{
    background-color: {config.COLORS['emergency']};
    color: white;
    border: 2px solid #FCA5A5;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: 14px;
    font-weight: 900;
    letter-spacing: 3px;
}}
QPushButton#stopBtn:pressed {{
    background-color: #7F1D1D;
}}
QPushButton#resetBtn {{
    background-color: {config.COLORS['accent']};
    color: black;
    font-weight: 900;
    letter-spacing: 3px;
    border: none;
    border-radius: 4px;
    padding: 8px 20px;
    font-size: 12px;
}}
QPushButton#resetBtn:pressed {{
    background-color: #FCD34D;
}}
QPushButton#splitBtn {{
    background-color: {config.COLORS['bg_panel']};
    border-radius: 10px;
}}
QComboBox {{
    background-color: {config.COLORS['bg_panel']};
    color: {config.COLORS['text']};
    border: 1px solid {config.COLORS['border']};
    border-radius: 4px;
    padding: 4px;
    font-size: 12px;
    min-height: 24px;
}}
"""


# ===========================================================
# 펄스 라벨 (사운드 웨이브)
# ===========================================================
class PulseLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars = [0.4] * 9
        self.setMinimumHeight(40)
        self.setMaximumHeight(50)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.audio_level = 0.5
        self.phase = 0

    def start(self):
        self.timer.start(50)

    def stop(self):
        self.timer.stop()

    def set_level(self, level: float):
        self.audio_level = max(0.2, min(1.0, level))

    def tick(self):
        import math
        self.phase += 0.3
        for i in range(len(self.bars)):
            self.bars[i] = 0.3 + 0.7 * abs(math.sin(self.phase + i * 0.5)) * self.audio_level
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        bar_w = 6
        gap = 4
        total = len(self.bars) * (bar_w + gap) - gap
        x = (w - total) // 2
        cy = h // 2
        color = QColor(config.COLORS["accent"])
        for v in self.bars:
            bh = int(h * 0.7 * v)
            p.fillRect(x, cy - bh // 2, bar_w, bh, color)
            x += bar_w + gap


# ===========================================================
# 단계 인디케이터
# ===========================================================
class StepIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.steps = []
        self.current = 0
        self.completed = -1
        self.accent = config.COLORS["accent"]
        self.setMinimumHeight(34)
        self.setMaximumHeight(40)

    def set_flow(self, steps: list, accent: str):
        self.steps = steps
        self.accent = accent
        self.current = 0
        self.completed = -1
        self.update()

    def set_step(self, idx: int, completed: bool = False):
        self.current = idx
        if completed:
            self.completed = idx
        self.update()

    def paintEvent(self, _event):
        if not self.steps:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        bar_h = 4
        bar_y = (h - bar_h) // 2 - 6
        n = len(self.steps)
        seg_w = (w - (n - 1) * 4) // n
        accent_color = QColor(self.accent)
        for i in range(n):
            x = i * (seg_w + 4)
            if i <= self.completed:
                color = accent_color
            elif i == self.current:
                color = QColor(self.accent)
                color.setAlpha(180)
            else:
                color = QColor(config.COLORS["border"])
            p.fillRect(x, bar_y, seg_w, bar_h, color)
        p.setPen(QColor(config.COLORS["text_dim"]))
        font = QFont("JetBrains Mono", 8)
        p.setFont(font)
        p.drawText(QRect(0, bar_y + 10, w, 14), Qt.AlignCenter,
                   f"STEP {self.current + 1} / {n}")


# ===========================================================
# 화면 1: IDLE (좌우 분할)
# ===========================================================
class IdleScreen(QWidget):
    selected_side = pyqtSignal(str)  # "prevention" | "urgent"

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        left_btn = self._make_split_button(
            "예방·관리", "PREVENTION", "📋",
            "아차사고 · TBM\n관리자 · 환경설정",
            "#A78BFA",
        )
        left_btn.clicked.connect(lambda: self.selected_side.emit("prevention"))
        layout.addWidget(left_btn, 1)

        right_btn = self._make_split_button(
            "긴급", "URGENT", "🚨",
            "구급 · 화재\n작업중지 · 관리자",
            "#FF3355",
        )
        right_btn.clicked.connect(lambda: self.selected_side.emit("urgent"))
        layout.addWidget(right_btn, 1)

    def _make_split_button(self, title_kr: str, title_en: str, icon: str,
                            subtitle: str, color: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("splitBtn")
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        btn.setStyleSheet(f"""
            QPushButton#splitBtn {{
                background-color: {config.COLORS['bg_panel']};
                border: 3px solid {color}80;
                border-radius: 12px;
                color: {config.COLORS['text']};
                text-align: center;
            }}
            QPushButton#splitBtn:pressed {{
                background-color: {color}25;
                border: 3px solid {color};
            }}
        """)

        v = QVBoxLayout(btn)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(4)
        v.setContentsMargins(8, 8, 8, 8)

        tag = QLabel(title_en)
        tag.setAlignment(Qt.AlignCenter)
        tag.setStyleSheet(f"color: {color}; font-size: 10px; letter-spacing: 4px; font-weight: bold; background: transparent; border: none;")
        v.addWidget(tag)

        ico = QLabel(icon)
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet(f"font-size: 56px; background: transparent; border: none;")
        v.addWidget(ico)

        title = QLabel(title_kr)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {config.COLORS['text']}; font-size: 26px; font-weight: 900; letter-spacing: 2px; background: transparent; border: none;")
        v.addWidget(title)

        sub = QLabel(subtitle)
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color: {config.COLORS['text_dim']}; font-size: 11px; letter-spacing: 1px; background: transparent; border: none;")
        v.addWidget(sub)

        hint = QLabel("터치하여 메뉴 열기")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color: {color}; font-size: 9px; letter-spacing: 3px; background: transparent; border: none;")
        v.addWidget(hint)

        return btn


# ===========================================================
# 화면 2: 메뉴 (4개 카테고리 + 뒤로가기)
# ===========================================================
class MenuScreen(QWidget):
    selected = pyqtSignal(str)
    back = pyqtSignal()

    def __init__(self, side: str, parent=None):
        super().__init__(parent)
        self.side = side

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 10, 16, 12)

        # 헤더
        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)

        if side == "urgent":
            tag_text = "EMERGENCY · 긴급 메뉴"
            tag_color = config.COLORS["emergency"]
            title_text = "상황을 선택해 주세요"
            self.flow_keys = ["emergency", "fire", "stop", "manager"]
        else:
            tag_text = "PREVENTION · 예방·관리"
            tag_color = "#A78BFA"
            title_text = "메뉴를 선택해 주세요"
            self.flow_keys = ["incident", "tbm", "manager", "settings"]

        tag = QLabel(tag_text)
        tag.setStyleSheet(f"color: {tag_color}; font-size: 10px; letter-spacing: 3px; font-weight: bold;")
        title = QLabel(title_text)
        title.setStyleSheet(f"font-size: 18px; font-weight: 900; color: {config.COLORS['text']};")
        title_box.addWidget(tag)
        title_box.addWidget(title)
        header.addLayout(title_box)
        header.addStretch()

        back_btn = QPushButton("◀ 뒤로")
        back_btn.setObjectName("backBtn")
        back_btn.setMinimumSize(70, 36)
        back_btn.clicked.connect(self.back.emit)
        header.addWidget(back_btn, alignment=Qt.AlignTop)
        layout.addLayout(header)

        # 4개 그리드
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, key in enumerate(self.flow_keys):
            flow = FLOWS[key]
            color = config.COLORS[flow["color_key"]]
            btn = self._make_category_button(flow["icon"], flow["label"], color)
            btn.clicked.connect(lambda _checked, k=key: self.selected.emit(k))
            row, col = divmod(i, 2)
            grid.addWidget(btn, row, col)
        layout.addLayout(grid, 1)

    def _make_category_button(self, icon: str, label: str, color: str) -> QPushButton:
        btn = QPushButton(f"{icon}  {label}")
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {config.COLORS['bg_panel']};
                border: 2px solid {color}60;
                border-radius: 10px;
                color: {config.COLORS['text']};
                font-size: 18px;
                font-weight: 700;
                padding: 8px;
            }}
            QPushButton:pressed {{
                background-color: {color}25;
                border: 2px solid {color};
            }}
        """)
        return btn


# ===========================================================
# 화면 3: 워크플로우 진행
# ===========================================================
class FlowScreen(QWidget):
    user_stop = pyqtSignal()
    back_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow_key = None
        self.is_recording = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(6)

        # 상단
        header = QHBoxLayout()
        self.tag = QLabel("PROCESSING")
        self.tag.setStyleSheet(f"color: {config.COLORS['accent']}; font-size: 10px; letter-spacing: 3px;")
        header.addWidget(self.tag)
        header.addStretch()

        back_btn = QPushButton("◀ 뒤로")
        back_btn.setObjectName("backBtn")
        back_btn.setMinimumSize(70, 32)
        back_btn.clicked.connect(self.back_pressed.emit)
        header.addWidget(back_btn)
        layout.addLayout(header)

        layout.addStretch(1)

        # 큰 안내 문구
        self.prompt = QLabel("처리 중입니다")
        self.prompt.setAlignment(Qt.AlignCenter)
        self.prompt.setWordWrap(True)
        self.prompt.setStyleSheet(f"""
            font-size: 22px; font-weight: 900;
            color: {config.COLORS['accent']};
            letter-spacing: 1px;
        """)
        layout.addWidget(self.prompt)

        # 사운드 웨이브
        self.wave = PulseLabel()
        self.wave.hide()
        layout.addWidget(self.wave)

        # 단계명
        self.step_name = QLabel("")
        self.step_name.setAlignment(Qt.AlignCenter)
        self.step_name.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {config.COLORS['text']};")
        layout.addWidget(self.step_name)

        # 디테일
        self.detail = QLabel("")
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"font-size: 11px; color: {config.COLORS['text_dim']}; letter-spacing: 1px;")
        layout.addWidget(self.detail)

        # 종료 버튼
        self.stop_btn = QPushButton("■ 발화 종료 / 전사 시작")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setMinimumSize(280, 50)
        self.stop_btn.clicked.connect(self.user_stop.emit)
        self.stop_btn.hide()
        stop_wrap = QHBoxLayout()
        stop_wrap.addStretch()
        stop_wrap.addWidget(self.stop_btn)
        stop_wrap.addStretch()
        layout.addLayout(stop_wrap)

        # 단계 인디케이터
        self.indicator = StepIndicator()
        self.indicator.setMaximumWidth(800)
        ind_wrap = QHBoxLayout()
        ind_wrap.addStretch()
        ind_wrap.addWidget(self.indicator)
        ind_wrap.addStretch()
        layout.addLayout(ind_wrap)

        # 전사 결과
        self.transcript_label = QLabel("")
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setMaximumHeight(80)
        self.transcript_label.setStyleSheet(f"""
            font-size: 12px; color: {config.COLORS['text']};
            background-color: {config.COLORS['bg_panel']};
            border-left: 3px solid {config.COLORS['accent']};
            padding: 8px 12px; border-radius: 3px;
        """)
        self.transcript_label.hide()
        tr_wrap = QHBoxLayout()
        tr_wrap.addStretch()
        tr_wrap.addWidget(self.transcript_label, 1)
        tr_wrap.addStretch()
        layout.addLayout(tr_wrap)

        layout.addStretch(1)

    def start(self, flow_key: str):
        self.flow_key = flow_key
        flow = FLOWS[flow_key]
        accent = config.COLORS[flow["color_key"]]

        self.tag.setText(f"PROCESSING · {flow['label'].upper()}")
        self.tag.setStyleSheet(f"color: {accent}; font-size: 10px; letter-spacing: 3px; font-weight: bold;")
        self.indicator.set_flow(flow["steps"], accent)
        self.transcript_label.hide()
        self.wave.hide()
        self.stop_btn.hide()
        self.is_recording = False
        self.prompt.setText("준비 중...")
        self.step_name.setText("")
        self.detail.setText("")

    def update_event(self, ev: FlowEvent):
        flow = FLOWS[self.flow_key]

        recording_step = (
            (self.flow_key in ("emergency", "fire") and ev.step_index == 1) or
            (self.flow_key == "stop" and ev.step_index == 2) or
            (self.flow_key in ("incident", "tbm") and ev.step_index == 1)
        )
        manager_call = (self.flow_key == "manager" and ev.step_index == 1)

        if ev.status == "running":
            self.step_name.setText(flow["steps"][ev.step_index])
            self.detail.setText(ev.detail)

            if recording_step:
                if self.flow_key in ("incident", "tbm"):
                    self.prompt.setText(ev.detail or "내용을 말씀해 주세요")
                else:
                    self.prompt.setText("발생상황을 말씀해 주세요")
                self.wave.show()
                self.wave.start()
                self.stop_btn.show()
                self.is_recording = True
            elif manager_call:
                self.prompt.setText("통화 진행 중...")
                self.wave.hide()
                self.wave.stop()
                self.stop_btn.setText("■ 통화 종료")
                self.stop_btn.show()
                self.is_recording = True
            else:
                self.prompt.setText(flow["steps"][ev.step_index])
                self.wave.hide()
                self.wave.stop()
                self.stop_btn.hide()
                self.is_recording = False

            self.indicator.set_step(ev.step_index, completed=False)

        elif ev.status == "ok":
            self.indicator.set_step(ev.step_index, completed=True)
            self.wave.hide()
            self.wave.stop()
            self.stop_btn.hide()
            self.is_recording = False
            self.stop_btn.setText("■ 발화 종료 / 전사 시작")
            if ev.transcript:
                self.transcript_label.setText(f"💬 \"{ev.transcript}\"")
                self.transcript_label.show()


# ===========================================================
# 화면 4: 완료
# ===========================================================
class CompleteScreen(QWidget):
    reset = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        check = QLabel("✓")
        check.setAlignment(Qt.AlignCenter)
        check.setStyleSheet(f"""
            font-size: 48px; color: {config.COLORS['ok']};
            border: 3px solid {config.COLORS['ok']};
            border-radius: 40px;
            min-width: 80px; max-width: 80px;
            min-height: 80px; max-height: 80px;
        """)
        wrap = QHBoxLayout()
        wrap.addStretch(); wrap.addWidget(check); wrap.addStretch()
        layout.addLayout(wrap)

        tag = QLabel("EVENT · REGISTERED")
        tag.setAlignment(Qt.AlignCenter)
        tag.setStyleSheet(f"color: {config.COLORS['ok']}; font-size: 10px; letter-spacing: 3px;")
        layout.addWidget(tag)

        self.title = QLabel("처리 완료")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(f"font-size: 26px; font-weight: 900; color: {config.COLORS['text']};")
        layout.addWidget(self.title)

        self.subtitle = QLabel("")
        self.subtitle.setAlignment(Qt.AlignCenter)
        self.subtitle.setStyleSheet(f"font-size: 14px; color: {config.COLORS['text']};")
        layout.addWidget(self.subtitle)

        self.event_id_label = QLabel("")
        self.event_id_label.setAlignment(Qt.AlignCenter)
        self.event_id_label.setStyleSheet(f"color: {config.COLORS['text_dim']}; font-size: 11px; letter-spacing: 2px;")
        layout.addWidget(self.event_id_label)

        reset_btn = QPushButton("초기화 · RESET")
        reset_btn.setObjectName("resetBtn")
        reset_btn.setMinimumSize(180, 44)
        reset_btn.clicked.connect(self.reset.emit)
        btn_wrap = QHBoxLayout()
        btn_wrap.addStretch(); btn_wrap.addWidget(reset_btn); btn_wrap.addStretch()
        layout.addLayout(btn_wrap)

    def set_result(self, flow_key: str, event_id: str):
        flow = FLOWS.get(flow_key, {})
        label = flow.get("label", "처리")

        if flow_key in ("emergency", "fire", "stop"):
            self.title.setText(f"{label} 접수 완료")
            self.subtitle.setText("신속히 대피해 주세요")
        elif flow_key == "manager":
            self.title.setText("통화 종료")
            self.subtitle.setText("내용이 관제 시스템에 등록되었습니다")
        elif flow_key == "incident":
            self.title.setText("아차 사고 신고 완료")
            self.subtitle.setText("안전 개선에 도움이 됩니다")
        elif flow_key == "tbm":
            self.title.setText("TBM 등록 완료")
            self.subtitle.setText("회의 내용이 기록되었습니다")
        else:
            self.title.setText(f"{label} 완료")
            self.subtitle.setText("")

        self.event_id_label.setText(f"EVENT_ID · {event_id}" if event_id else "")


# ===========================================================
# 화면 5: 환경 설정 (스크롤 영역으로)
# ===========================================================
class SettingsScreen(QWidget):
    back = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)

        # 헤더
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        tag = QLabel("SETTINGS · 환경 설정")
        tag.setStyleSheet(f"color: {config.COLORS['settings']}; font-size: 10px; letter-spacing: 3px; font-weight: bold;")
        title = QLabel("환경 설정")
        title.setStyleSheet(f"font-size: 18px; font-weight: 900; color: {config.COLORS['text']};")
        title_box.addWidget(tag)
        title_box.addWidget(title)
        header.addLayout(title_box)
        header.addStretch()

        back_btn = QPushButton("◀ 뒤로")
        back_btn.setObjectName("backBtn")
        back_btn.setMinimumSize(70, 36)
        back_btn.clicked.connect(self.back.emit)
        header.addWidget(back_btn, alignment=Qt.AlignTop)
        layout.addLayout(header)

        # 스크롤 가능한 카드 영역
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setSpacing(6)
        inner_layout.setContentsMargins(0, 0, 0, 0)

        inner_layout.addWidget(self._info_card("디바이스 ID", config.DEVICE_ID))
        inner_layout.addWidget(self._info_card("설치 위치", config.DEVICE_LOCATION))
        inner_layout.addWidget(self._info_card("관제 서버", config.SERVER_URL))
        inner_layout.addWidget(self._info_card(
            "Whisper 모델", f"{config.WHISPER_MODEL_SIZE} ({config.WHISPER_DEVICE})"
        ))

        try:
            devs = sd.query_devices()
            if config.AUDIO_DEVICE_INDEX is not None and config.AUDIO_DEVICE_INDEX < len(devs):
                mic_info = devs[config.AUDIO_DEVICE_INDEX]['name']
            else:
                mic_info = "기본 입력 장치"
            inner_layout.addWidget(self._info_card(
                "마이크", f"#{config.AUDIO_DEVICE_INDEX or '기본'} · {mic_info}"
            ))
        except Exception as e:
            inner_layout.addWidget(self._info_card("마이크", f"조회 실패: {e}"))

        inner_layout.addWidget(self._info_card(
            "긴급 녹음 시간", f"{config.RECORD_SECONDS}초 (자동 종료)"
        ))
        inner_layout.addWidget(self._info_card(
            "TBM·아차사고 녹음", f"최대 {config.RECORD_SECONDS_LONG}초 (종료 버튼)"
        ))

        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        note = QLabel("⚠ 설정 변경은 config.py 수정 후 재시작 필요")
        note.setAlignment(Qt.AlignCenter)
        note.setStyleSheet(f"color: {config.COLORS['text_dim']}; font-size: 10px;")
        layout.addWidget(note)

    def _info_card(self, label: str, value: str) -> QWidget:
        w = QFrame()
        w.setStyleSheet(f"""
            QFrame {{
                background-color: {config.COLORS['bg_panel']};
                border: 1px solid {config.COLORS['border']};
                border-radius: 4px;
            }}
        """)
        h = QHBoxLayout(w)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)

        l_label = QLabel(label)
        l_label.setStyleSheet(f"color: {config.COLORS['text_dim']}; font-size: 10px; letter-spacing: 2px; font-weight: bold; min-width: 130px; border: none;")
        h.addWidget(l_label)

        l_value = QLabel(value)
        l_value.setStyleSheet(f"color: {config.COLORS['text']}; font-size: 12px; border: none;")
        l_value.setWordWrap(True)
        h.addWidget(l_value, 1)

        return w


# ===========================================================
# 메인 윈도우
# ===========================================================
class EmergencyBellWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Emergency Bell System")
        self.setStyleSheet(STYLE)

        self._stop_event: asyncio.Event = None
        self._current_source = "urgent"

        # 풀스크린
        if config.FULLSCREEN:
            self.showFullScreen()
        else:
            self.resize(1024, 600)
        if config.HIDE_CURSOR:
            self.setCursor(QCursor(Qt.BlankCursor))

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 상단 상태바 (얇게)
        root.addWidget(self._build_statusbar())

        # 화면 스택
        self.stack = QStackedWidget()
        self.idle = IdleScreen()
        self.menu_urgent = MenuScreen("urgent")
        self.menu_prevention = MenuScreen("prevention")
        self.flow_screen = FlowScreen()
        self.complete = CompleteScreen()
        self.settings = SettingsScreen()

        for w in (self.idle, self.menu_urgent, self.menu_prevention,
                  self.flow_screen, self.complete, self.settings):
            self.stack.addWidget(w)

        root.addWidget(self.stack, 1)

        # 시그널
        self.idle.selected_side.connect(self._on_side_selected)
        self.menu_urgent.selected.connect(self._start_flow)
        self.menu_urgent.back.connect(self._go_idle)
        self.menu_prevention.selected.connect(self._on_prevention_selected)
        self.menu_prevention.back.connect(self._go_idle)
        self.flow_screen.user_stop.connect(self._on_user_stop)
        self.flow_screen.back_pressed.connect(self._go_idle)
        self.complete.reset.connect(self._go_idle)
        self.settings.back.connect(lambda: self.stack.setCurrentWidget(self.menu_prevention))

        # 시계
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
        self._update_clock()

        QShortcut(QKeySequence("Esc"), self, activated=self.close)

    def _build_statusbar(self):
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {config.COLORS['bg_panel']};
                border-bottom: 1px solid {config.COLORS['border']};
            }}
            QLabel {{ color: {config.COLORS['text_dim']}; font-size: 10px; letter-spacing: 1px; border: none; }}
        """)
        bar.setFixedHeight(28)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        layout.addWidget(QLabel("● ONLINE"))
        layout.addWidget(QLabel(f"|  {config.DEVICE_ID}"))
        layout.addWidget(QLabel(f"|  📍 {config.DEVICE_LOCATION}"))
        layout.addStretch()

        self.clock_label = QLabel("00:00:00")
        layout.addWidget(self.clock_label)
        return bar

    def _update_clock(self):
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))

    def _go_idle(self):
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()
        self.stack.setCurrentWidget(self.idle)

    def _on_side_selected(self, side: str):
        self._current_source = side
        if side == "urgent":
            self.stack.setCurrentWidget(self.menu_urgent)
        else:
            self.stack.setCurrentWidget(self.menu_prevention)

    def _on_prevention_selected(self, flow_key: str):
        if flow_key == "settings":
            self.stack.setCurrentWidget(self.settings)
        else:
            self._start_flow(flow_key)

    def _start_flow(self, flow_key: str):
        self.flow_screen.start(flow_key)
        self.stack.setCurrentWidget(self.flow_screen)
        self._stop_event = asyncio.Event()
        asyncio.ensure_future(self._run_flow_async(flow_key))

    async def _run_flow_async(self, flow_key: str):
        last_event_id = ""
        try:
            async for ev in workflow.run_flow(
                flow_key,
                stop_event=self._stop_event,
                source=self._current_source,
            ):
                if self.stack.currentWidget() is not self.flow_screen:
                    logger.info("워크플로우 중단 - 화면 이동")
                    return
                self.flow_screen.update_event(ev)
                if ev.event_id:
                    last_event_id = ev.event_id
        except Exception as e:
            logger.exception(f"워크플로우 오류: {e}")

        if self.stack.currentWidget() is self.flow_screen:
            self.complete.set_result(flow_key, last_event_id)
            self.stack.setCurrentWidget(self.complete)

    def _on_user_stop(self):
        if self._stop_event and not self._stop_event.is_set():
            logger.info("사용자가 종료 버튼 누름")
            self._stop_event.set()


# ===========================================================
# 진입점
# ===========================================================
def main():
    app = QApplication(sys.argv)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = EmergencyBellWindow()
    win.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
