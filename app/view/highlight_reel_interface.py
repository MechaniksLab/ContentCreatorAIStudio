import os
import json
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    CommandBar,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SpinBox,
    StrongBodyLabel,
)

from app.common.config import cfg
from app.common.theme_manager import get_theme_palette
from app.config import APPDATA_PATH
from app.core.entities import SupportedVideoFormats
from app.thread.highlight_reel_thread import (
    HighlightReelAnalyzeThread,
    HighlightReelPreviewThread,
    HighlightReelRenderThread,
)


class HighlightReelInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HighlightReelInterface")
        self.video_path: str = ""
        self.candidates: List[Dict] = []
        self.output_path: str = ""
        self.analyze_thread: Optional[HighlightReelAnalyzeThread] = None
        self.render_thread: Optional[HighlightReelRenderThread] = None
        self.preview_thread: Optional[HighlightReelPreviewThread] = None
        self.presets_path = APPDATA_PATH / "highlight_reel_presets.json"
        self.presets_state_path = APPDATA_PATH / "highlight_reel_presets_state.json"

        self._build_ui()
        self._load_cfg_values()
        self.load_presets()
        self._apply_theme_style()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        choose_action = Action(FluentIcon.FOLDER, "Выбрать видео")
        choose_action.triggered.connect(self._choose_file)
        self.command_bar.addAction(choose_action)
        root.addWidget(self.command_bar)

        self.video_card = CardWidget(self)
        vrow = QHBoxLayout(self.video_card)
        self.video_label = BodyLabel("Файл не выбран")
        self.open_output_file_btn = PushButton("Открыть готовое видео")
        self.open_output_file_btn.clicked.connect(self._open_output_file)
        self.open_output_btn = PushButton("Открыть папку результата")
        self.open_output_btn.clicked.connect(self._open_output_folder)
        vrow.addWidget(self.video_label)
        vrow.addStretch(1)
        vrow.addWidget(self.open_output_file_btn)
        vrow.addWidget(self.open_output_btn)
        root.addWidget(self.video_card)

        self.scroll_area = ScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_widget = QWidget(self)
        self.scroll_widget.setObjectName("HighlightReelScrollWidget")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(12)

        self._build_analyze_card()
        self._build_candidates_card()
        self._build_render_card()
        self._relax_numeric_inputs()

        self.scroll_area.setWidget(self.scroll_widget)
        root.addWidget(self.scroll_area, 1)

    def _relax_numeric_inputs(self):
        for spin in self.findChildren(SpinBox):
            try:
                spin.setKeyboardTracking(False)
            except Exception:
                pass
            try:
                spin.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
            except Exception:
                pass

    def _build_analyze_card(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.addWidget(StrongBodyLabel("Этап 1: AI-анализ и поиск интересных моментов"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        grid.addWidget(BodyLabel("Желаемая длительность нарезки (мин):"), 0, 0)
        self.target_minutes_spin = SpinBox(self)
        self.target_minutes_spin.setRange(5, 180)
        self.target_minutes_spin.setValue(30)
        grid.addWidget(self.target_minutes_spin, 0, 1)

        grid.addWidget(BodyLabel("Степень интересности:"), 0, 2)
        self.interest_level_combo = ComboBox(self)
        self.interest_level_combo.addItems(["Низкая (мягче)", "Сбалансированная", "Высокая (плотнее)"])
        self.interest_level_combo.setCurrentText("Сбалансированная")
        grid.addWidget(self.interest_level_combo, 0, 3)

        grid.addWidget(BodyLabel("Порог интереса (%):"), 1, 0)
        self.interest_spin = SpinBox(self)
        self.interest_spin.setRange(30, 95)
        self.interest_spin.setValue(55)
        grid.addWidget(self.interest_spin, 1, 1)

        grid.addWidget(BodyLabel("Профиль удаления скучных фрагментов:"), 1, 2)
        self.boring_profile_combo = ComboBox(self)
        self.boring_profile_combo.addItems(["Мягкий", "Сбалансированный", "Строгий"])
        self.boring_profile_combo.setCurrentText("Сбалансированный")
        grid.addWidget(self.boring_profile_combo, 1, 3)

        lay.addLayout(grid)

        row3 = QHBoxLayout()
        self.auto_select_check = CheckBox("Автовыбор лучших для рендера", self)
        self.auto_select_check.setChecked(True)
        row3.addWidget(self.auto_select_check)
        row3.addWidget(BodyLabel("Запуск:"))
        self.backend_combo = ComboBox(self)
        self.backend_combo.addItems(["GPU (рекомендуется)", "CPU"])
        self.backend_combo.setCurrentIndex(0)
        row3.addWidget(self.backend_combo)
        self.cache_asr_check = CheckBox("Кэш текста (ASR)", self)
        self.cache_asr_check.setChecked(True)
        row3.addWidget(self.cache_asr_check)
        self.cache_candidates_check = CheckBox("Кэш кандидатов", self)
        self.cache_candidates_check.setChecked(True)
        row3.addWidget(self.cache_candidates_check)
        row3.addStretch(1)
        lay.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(BodyLabel("Сортировка моментов:"))
        self.sort_combo = ComboBox(self)
        self.sort_combo.addItems(["По score (убыв.)", "По таймлайну (рано→поздно)"])
        self.sort_combo.currentIndexChanged.connect(self._resort_candidates)
        row4.addWidget(self.sort_combo)
        row4.addWidget(BodyLabel("Пресет:"))
        self.preset_combo = ComboBox(self)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        row4.addWidget(self.preset_combo)
        self.new_preset_btn = PushButton("Новый")
        self.new_preset_btn.clicked.connect(self._create_new_preset)
        row4.addWidget(self.new_preset_btn)
        self.save_preset_btn = PushButton("Сохранить пресет")
        self.save_preset_btn.clicked.connect(self._save_current_preset)
        self.delete_preset_btn = PushButton("Удалить")
        self.delete_preset_btn.clicked.connect(self._delete_selected_preset)
        row4.addWidget(self.save_preset_btn)
        row4.addWidget(self.delete_preset_btn)
        row4.addStretch(1)
        lay.addLayout(row4)

        self.analyze_btn = PrimaryPushButton("Запустить AI-анализ")
        self.analyze_btn.clicked.connect(self._start_analyze)
        lay.addWidget(self.analyze_btn)

        self.scroll_layout.addWidget(card)

    def _build_candidates_card(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.addWidget(StrongBodyLabel("Этап 2: Выбор моментов для итоговой нарезки"))
        self.candidates_list = QListWidget(self)
        self.candidates_list.setSelectionMode(QListWidget.MultiSelection)
        self.candidates_list.setMinimumHeight(260)
        lay.addWidget(self.candidates_list)
        preview_row = QHBoxLayout()
        self.preview_btn = PushButton("Предпросмотр выбранного")
        self.preview_btn.clicked.connect(self._preview_selected)
        preview_row.addWidget(self.preview_btn)
        preview_row.addStretch(1)
        lay.addLayout(preview_row)
        self.scroll_layout.addWidget(card)

    def _build_render_card(self):
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.addWidget(StrongBodyLabel("Этап 3: Сборка и рендер нарезки"))

        row = QHBoxLayout()
        row.addWidget(BodyLabel("Отступ до момента (мс):"))
        self.head_pad_spin = SpinBox(self)
        self.head_pad_spin.setRange(0, 3000)
        self.head_pad_spin.setValue(220)
        row.addWidget(self.head_pad_spin)
        row.addWidget(BodyLabel("Отступ после момента (мс):"))
        self.tail_pad_spin = SpinBox(self)
        self.tail_pad_spin.setRange(0, 4000)
        self.tail_pad_spin.setValue(260)
        row.addWidget(self.tail_pad_spin)
        self.export_vertical_check = CheckBox("Экспорт 9:16 версии", self)
        self.export_vertical_check.setChecked(True)
        row.addWidget(self.export_vertical_check)
        row.addStretch(1)
        lay.addLayout(row)

        self.progress = ProgressBar(self)
        self.progress_label = BodyLabel("Ожидание")
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_label)

        self.render_btn = PrimaryPushButton("Создать нарезку")
        self.render_btn.clicked.connect(self._start_render)
        lay.addWidget(self.render_btn)

        self.scroll_layout.addWidget(card)

    def _profile_value(self) -> str:
        txt = (self.boring_profile_combo.currentText() or "").lower()
        if "мяг" in txt:
            return "soft"
        if "строг" in txt:
            return "strict"
        return "balanced"

    def _set_progress(self, value: int, message: str):
        self.progress.setValue(max(0, min(100, int(value))))
        self.progress_label.setText(message)

    def _choose_file(self):
        exts = [f"*.{e.value}" for e in SupportedVideoFormats]
        f, _ = QFileDialog.getOpenFileName(self, "Выберите видео", "", f"Video ({' '.join(exts)})")
        if not f:
            return
        self.video_path = f
        self.video_label.setText(f)

    def _start_analyze(self):
        if not self.video_path:
            InfoBar.warning("Нет файла", "Сначала выберите видео", duration=2200, parent=self)
            return
        self.analyze_btn.setEnabled(False)
        self._set_progress(2, "Старт анализа...")
        self.analyze_thread = HighlightReelAnalyzeThread(
            video_path=self.video_path,
            target_reel_minutes=self.target_minutes_spin.value(),
            interest_level=("high" if self.interest_level_combo.currentIndex() == 2 else "low" if self.interest_level_combo.currentIndex() == 0 else "balanced"),
            interest_threshold_percent=self.interest_spin.value(),
            boring_profile=self._profile_value(),
            asr_backend=("gpu" if self.backend_combo.currentIndex() == 0 else "cpu"),
            use_asr_cache=bool(self.cache_asr_check.isChecked()),
            use_candidates_cache=bool(self.cache_candidates_check.isChecked()),
        )
        self.analyze_thread.progress.connect(self._set_progress)
        self.analyze_thread.finished.connect(self._on_analyze_finished)
        self.analyze_thread.error.connect(self._on_error)
        self.analyze_thread.start()

    def _on_analyze_finished(self, candidates: List[Dict]):
        self.analyze_btn.setEnabled(True)
        self.candidates = candidates or []
        self.candidates_list.clear()

        for c in self.candidates:
            s = int(c.get("start_ms", 0)) // 1000
            e = int(c.get("end_ms", 0)) // 1000
            score = float(c.get("quality_score", c.get("score", 0.0)) or 0.0)
            title = str(c.get("title", "") or "без названия")
            txt = f"[{s:>5}s - {e:>5}s]  score={score:.1f}  {title}"
            item = QListWidgetItem(txt)
            item.setData(Qt.UserRole, c)
            self.candidates_list.addItem(item)

        if self.auto_select_check.isChecked():
            for i in range(self.candidates_list.count()):
                self.candidates_list.item(i).setSelected(True)

        self._set_progress(100, f"Готово. Найдено моментов: {len(self.candidates)}")
        self._resort_candidates()
        self._update_quality_report()
        InfoBar.success("Анализ завершён", f"Найдено {len(self.candidates)} моментов", duration=2200, parent=self)

    def _selected_candidates(self) -> List[Dict]:
        out: List[Dict] = []
        for item in self.candidates_list.selectedItems():
            data = item.data(Qt.UserRole)
            if isinstance(data, dict):
                out.append(data)
        return out

    def _start_render(self):
        if not self.video_path:
            InfoBar.warning("Нет файла", "Сначала выберите видео", duration=2200, parent=self)
            return
        selected = self._selected_candidates()
        if not selected:
            InfoBar.warning("Нет моментов", "Выберите хотя бы один момент", duration=2200, parent=self)
            return

        self.render_btn.setEnabled(False)
        self._set_progress(1, "Подготовка рендера...")
        self.render_thread = HighlightReelRenderThread(
            video_path=self.video_path,
            selected_candidates=selected,
            output_name="highlight_reel.mp4",
            head_pad_ms=self.head_pad_spin.value(),
            tail_pad_ms=self.tail_pad_spin.value(),
            export_vertical=bool(self.export_vertical_check.isChecked()),
            render_backend=("gpu" if self.backend_combo.currentIndex() == 0 else "cpu"),
        )
        self.render_thread.progress.connect(self._set_progress)
        self.render_thread.finished.connect(self._on_render_finished)
        self.render_thread.error.connect(self._on_error)
        self.render_thread.start()

    def _on_render_finished(self, output_path: str):
        self.render_btn.setEnabled(True)
        self.output_path = output_path or ""
        self._set_progress(100, "Нарезка готова")
        self._save_cfg_values()
        self._export_chapters_for_output(self.output_path)
        InfoBar.success("Готово", f"Файл сохранён:\n{self.output_path}", duration=3000, parent=self)

    def _on_error(self, message: str):
        self.analyze_btn.setEnabled(True)
        self.render_btn.setEnabled(True)
        self._set_progress(0, "Ошибка")
        InfoBar.error("Ошибка", str(message), duration=4000, position=InfoBarPosition.TOP, parent=self)

    def _open_output_folder(self):
        if not self.output_path:
            return
        p = Path(self.output_path)
        if p.exists():
            os.startfile(str(p.parent))

    def _open_output_file(self):
        if not self.output_path:
            return
        p = Path(self.output_path)
        if p.exists():
            os.startfile(str(p))

    def _apply_theme_style(self):
        p = get_theme_palette()
        self.setStyleSheet(
            f"""
            QWidget#HighlightReelInterface {{ background: {p['window_bg']}; }}
            QScrollArea {{ border: none; background: {p['window_bg']}; }}
            QWidget#HighlightReelScrollWidget {{ background: {p['window_bg']}; }}
            QAbstractScrollArea {{ background: {p['window_bg']}; }}
            QAbstractScrollArea > QWidget > QWidget {{ background: {p['window_bg']}; }}
            QWidget {{ color: {p['text']}; }}
            QListWidget {{
                background: {p['panel_bg']};
                border: 1px solid {p['border']};
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget::item {{ padding: 6px; border-radius: 6px; }}
            QComboBox, QSpinBox, QLineEdit {{
                background: {p['panel_bg']};
                color: {p['text']};
                border: 1px solid {p['border']};
                border-radius: 6px;
                padding: 4px;
            }}
            QAbstractItemView {{
                background: {p['panel_bg']};
                color: {p['text']};
                border: 1px solid {p['border']};
            }}
            CardWidget {{
                border-radius: 10px;
                background: {p['card_bg']};
                border: 1px solid {p['border']};
            }}
            """
        )

    def _resort_candidates(self):
        if not self.candidates:
            return
        mode = self.sort_combo.currentIndex()
        if mode == 1:
            ordered = sorted(self.candidates, key=lambda c: int(c.get("start_ms", 0) or 0))
        else:
            ordered = sorted(self.candidates, key=lambda c: float(c.get("quality_score", c.get("score", 0.0)) or 0.0), reverse=True)

        selected_keys = {
            (int(i.data(Qt.UserRole).get("start_ms", 0)), int(i.data(Qt.UserRole).get("end_ms", 0)))
            for i in self.candidates_list.selectedItems()
            if isinstance(i.data(Qt.UserRole), dict)
        }
        self.candidates_list.clear()
        self.candidates = ordered
        for c in ordered:
            s = int(c.get("start_ms", 0)) // 1000
            e = int(c.get("end_ms", 0)) // 1000
            score = float(c.get("quality_score", c.get("score", 0.0)) or 0.0)
            title = str(c.get("title", "") or "без названия")
            item = QListWidgetItem(f"[{s:>5}s - {e:>5}s]  score={score:.1f}  {title}")
            item.setData(Qt.UserRole, c)
            self.candidates_list.addItem(item)
            if (int(c.get("start_ms", 0)), int(c.get("end_ms", 0))) in selected_keys:
                item.setSelected(True)

    def _update_quality_report(self):
        if not self.candidates:
            return
        total_dur_s = sum(max(0, int(c.get("end_ms", 0)) - int(c.get("start_ms", 0))) for c in self.candidates) / 1000.0
        avg_score = sum(float(c.get("quality_score", c.get("score", 0.0)) or 0.0) for c in self.candidates) / max(1, len(self.candidates))
        self.progress_label.setText(
            f"Quality report: моментов={len(self.candidates)} | суммарно={total_dur_s:.1f}с | avg score={avg_score:.1f}"
        )

    def _load_cfg_values(self):
        try:
            self.target_minutes_spin.setValue(30)
            self.interest_level_combo.setCurrentText("Сбалансированная")
            self.interest_spin.setValue(int(cfg.get(cfg.highlight_reel_interest_threshold_percent)))
            self.head_pad_spin.setValue(int(cfg.get(cfg.highlight_reel_head_pad_ms)))
            self.tail_pad_spin.setValue(int(cfg.get(cfg.highlight_reel_tail_pad_ms)))
            p = str(cfg.get(cfg.highlight_reel_boring_profile) or "balanced")
            if p == "soft":
                self.boring_profile_combo.setCurrentText("Мягкий")
            elif p == "strict":
                self.boring_profile_combo.setCurrentText("Строгий")
            else:
                self.boring_profile_combo.setCurrentText("Сбалансированный")
        except Exception:
            pass

    def _save_cfg_values(self):
        try:
            cfg.set(cfg.highlight_reel_interest_threshold_percent, int(self.interest_spin.value()))
            cfg.set(cfg.highlight_reel_head_pad_ms, int(self.head_pad_spin.value()))
            cfg.set(cfg.highlight_reel_tail_pad_ms, int(self.tail_pad_spin.value()))
            cfg.set(cfg.highlight_reel_boring_profile, self._profile_value())
        except Exception:
            pass

    def _collect_current_settings(self) -> Dict:
        return {
            "target_reel_minutes": int(self.target_minutes_spin.value()),
            "interest_level": ("high" if self.interest_level_combo.currentIndex() == 2 else "low" if self.interest_level_combo.currentIndex() == 0 else "balanced"),
            "interest_threshold_percent": int(self.interest_spin.value()),
            "head_pad_ms": int(self.head_pad_spin.value()),
            "tail_pad_ms": int(self.tail_pad_spin.value()),
            "boring_profile": self._profile_value(),
            "export_vertical": bool(self.export_vertical_check.isChecked()),
            "backend": "gpu" if self.backend_combo.currentIndex() == 0 else "cpu",
            "cache_asr": bool(self.cache_asr_check.isChecked()),
            "cache_candidates": bool(self.cache_candidates_check.isChecked()),
        }

    def _apply_settings(self, d: Dict):
        try:
            self.target_minutes_spin.setValue(int(d.get("target_reel_minutes", self.target_minutes_spin.value())))
            il = str(d.get("interest_level", "balanced") or "balanced").lower()
            self.interest_level_combo.setCurrentText("Высокая (плотнее)" if il == "high" else "Низкая (мягче)" if il == "low" else "Сбалансированная")
            self.interest_spin.setValue(int(d.get("interest_threshold_percent", self.interest_spin.value())))
            self.head_pad_spin.setValue(int(d.get("head_pad_ms", self.head_pad_spin.value())))
            self.tail_pad_spin.setValue(int(d.get("tail_pad_ms", self.tail_pad_spin.value())))
            bp = str(d.get("boring_profile", self._profile_value()) or "balanced")
            self.boring_profile_combo.setCurrentText("Мягкий" if bp == "soft" else "Строгий" if bp == "strict" else "Сбалансированный")
            self.export_vertical_check.setChecked(bool(d.get("export_vertical", self.export_vertical_check.isChecked())))
            self.backend_combo.setCurrentIndex(0 if str(d.get("backend", "gpu")).lower() in {"gpu", "cuda"} else 1)
            self.cache_asr_check.setChecked(bool(d.get("cache_asr", self.cache_asr_check.isChecked())))
            self.cache_candidates_check.setChecked(bool(d.get("cache_candidates", self.cache_candidates_check.isChecked())))
        except Exception:
            pass

    def load_presets(self):
        self._presets = {}
        try:
            if self.presets_path.exists():
                self._presets = json.loads(self.presets_path.read_text(encoding="utf-8")) or {}
        except Exception:
            self._presets = {}
        self.preset_combo.clear()
        self.preset_combo.addItem("default (из cfg)")
        for k in sorted(self._presets.keys()):
            self.preset_combo.addItem(k)
        self._restore_last_selected_preset()

    # backward-compat alias for old calls
    def _load_presets(self):
        self.load_presets()

    def _save_last_selected_preset(self, name: str):
        try:
            self.presets_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.presets_state_path.write_text(json.dumps({"last_selected": name}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _restore_last_selected_preset(self):
        try:
            if not self.presets_state_path.exists():
                return
            data = json.loads(self.presets_state_path.read_text(encoding="utf-8"))
            name = str((data or {}).get("last_selected", "")).strip()
            if not name:
                return
            for i in range(self.preset_combo.count()):
                if self.preset_combo.itemText(i) == name:
                    self.preset_combo.setCurrentIndex(i)
                    return
        except Exception:
            pass

    def _create_new_preset(self):
        p = get_theme_palette()
        self.setStyleSheet(
            self.styleSheet()
            + f"\nQInputDialog, QDialog {{ background: {p['card_bg']}; color: {p['text']}; }}"
            + f"\nQLineEdit {{ background: {p['panel_bg']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 6px; padding: 5px; }}"
        )
        name, ok = QInputDialog.getText(self, "Новый пресет", "Введите имя нового пресета:")
        name = (name or "").strip()
        if not ok or not name:
            return
        self._presets[name] = self._collect_current_settings()
        try:
            self.presets_path.parent.mkdir(parents=True, exist_ok=True)
            self.presets_path.write_text(json.dumps(self._presets, ensure_ascii=False, indent=2), encoding="utf-8")
            self.load_presets()
            self.preset_combo.setCurrentText(name)
            self._save_last_selected_preset(name)
            InfoBar.success("Пресет", f"Создан: {name}", duration=1800, parent=self)
        except Exception as e:
            InfoBar.error("Ошибка", f"Не удалось создать пресет: {e}", duration=2600, parent=self)

    def _save_current_preset(self):
        name = (self.preset_combo.currentText() or "").strip() or "custom"
        if name == "default (из cfg)":
            InfoBar.warning("Пресет", "Нельзя перезаписать default. Создайте новый пресет.", duration=2200, parent=self)
            return
        self._presets[name] = self._collect_current_settings()
        try:
            self.presets_path.parent.mkdir(parents=True, exist_ok=True)
            self.presets_path.write_text(json.dumps(self._presets, ensure_ascii=False, indent=2), encoding="utf-8")
            self.load_presets()
            self.preset_combo.setCurrentText(name)
            self._save_last_selected_preset(name)
            InfoBar.success("Пресет", f"Сохранён: {name}", duration=1800, parent=self)
        except Exception as e:
            InfoBar.error("Ошибка", f"Не удалось сохранить пресет: {e}", duration=2600, parent=self)

    def _apply_selected_preset(self):
        name = (self.preset_combo.currentText() or "").strip()
        if not name or name == "default (из cfg)":
            self._load_cfg_values()
            self._save_last_selected_preset("default (из cfg)")
            return
        data = self._presets.get(name)
        if isinstance(data, dict):
            self._apply_settings(data)
            self._save_last_selected_preset(name)
            InfoBar.success("Пресет", f"Применён: {name}", duration=1800, parent=self)

    def _on_preset_changed(self, _text: str):
        self._apply_selected_preset()

    def _delete_selected_preset(self):
        name = (self.preset_combo.currentText() or "").strip()
        if not name or name == "default (из cfg)":
            InfoBar.warning("Пресеты", "Системный default удалить нельзя", duration=2200, parent=self)
            return
        if name not in self._presets:
            return
        try:
            self._presets.pop(name, None)
            self.presets_path.parent.mkdir(parents=True, exist_ok=True)
            self.presets_path.write_text(json.dumps(self._presets, ensure_ascii=False, indent=2), encoding="utf-8")
            self.load_presets()
            self.preset_combo.setCurrentText("default (из cfg)")
            self._save_last_selected_preset("default (из cfg)")
            InfoBar.success("Пресет", f"Удалён: {name}", duration=1800, parent=self)
        except Exception as e:
            InfoBar.error("Ошибка", f"Не удалось удалить пресет: {e}", duration=2600, parent=self)

    def _preview_selected(self):
        if not self.video_path:
            InfoBar.warning("Нет файла", "Сначала выберите видео", duration=2200, parent=self)
            return
        selected = self._selected_candidates()
        if not selected:
            InfoBar.warning("Нет выбора", "Выберите момент в списке", duration=2200, parent=self)
            return
        candidate = selected[0]
        self.preview_btn.setEnabled(False)
        self.preview_thread = HighlightReelPreviewThread(
            video_path=self.video_path,
            candidate=candidate,
            head_pad_ms=self.head_pad_spin.value(),
            tail_pad_ms=self.tail_pad_spin.value(),
        )
        self.preview_thread.finished.connect(self._on_preview_finished)
        self.preview_thread.error.connect(self._on_error)
        self.preview_thread.start()

    def _on_preview_finished(self, output_path: str):
        self.preview_btn.setEnabled(True)
        p = Path(output_path or "")
        if p.exists():
            try:
                os.startfile(str(p))
            except Exception:
                pass
        InfoBar.success("Предпросмотр", f"Клип создан:\n{output_path}", duration=2200, parent=self)

    def _export_chapters_for_output(self, output_path: str):
        try:
            out = Path(output_path)
            if not out.exists():
                return
            selected = self._selected_candidates()
            if not selected:
                return
            lines = []
            acc_ms = 0
            for i, c in enumerate(selected, 1):
                sec = max(0, acc_ms // 1000)
                h = sec // 3600
                m = (sec % 3600) // 60
                s = sec % 60
                title = str(c.get("title", "") or f"Момент {i}").strip()
                lines.append(f"{h:02d}:{m:02d}:{s:02d} - {title}")
                dur_ms = max(0, int(c.get("end_ms", 0)) - int(c.get("start_ms", 0)))
                dur_ms += int(self.head_pad_spin.value()) + int(self.tail_pad_spin.value())
                acc_ms += dur_ms
            chapters_path = out.with_suffix(".chapters.txt")
            chapters_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass
