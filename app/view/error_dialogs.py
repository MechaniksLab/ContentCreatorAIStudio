import os
import sys
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import QApplication, QDialog, QHBoxLayout, QTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import InfoBar, InfoBarPosition, PrimaryPushButton, PushButton

from app.config import LOG_PATH


def show_copyable_error(
    parent: Optional[QWidget],
    title: str,
    message: str,
    details: str = "",
    *,
    log_path: Optional[Path] = None,
    duration: int = 8000,
) -> None:
    """Show a user-readable error dialog with copyable technical details."""
    clean_title = str(title or "Ошибка")
    clean_message = str(message or "Произошла ошибка")
    clean_details = str(details or "").strip() or "Технических деталей нет."
    logs_dir = Path(log_path or LOG_PATH)
    full_text = (
        f"{clean_title}\n\n"
        f"{clean_message}\n\n"
        "Что можно сделать:\n"
        "- Проверьте выбранные файлы, настройки и доступность нужных моделей.\n"
        "- Если ошибка повторяется, скопируйте текст ошибки и приложите лог.\n\n"
        "--- Технические детали ---\n"
        f"{clean_details}"
    )

    InfoBar.error(
        clean_title,
        f"{clean_message}\nПодробности открыты в отдельном окне, текст можно скопировать.",
        duration=duration,
        position=InfoBarPosition.TOP,
        parent=parent,
    )

    dlg = QDialog(parent)
    dlg.setWindowTitle(clean_title)
    dlg.resize(980, 540)
    layout = QVBoxLayout(dlg)

    text = QTextEdit(dlg)
    text.setReadOnly(True)
    text.setPlainText(full_text)
    layout.addWidget(text)

    buttons = QHBoxLayout()
    copy_btn = PrimaryPushButton("Скопировать ошибку", dlg)
    open_logs_btn = PushButton("Открыть папку логов", dlg)
    close_btn = PushButton("Закрыть", dlg)
    buttons.addWidget(copy_btn)
    buttons.addWidget(open_logs_btn)
    buttons.addWidget(close_btn)
    buttons.addStretch(1)
    layout.addLayout(buttons)

    def copy_error() -> None:
        QApplication.clipboard().setText(text.toPlainText())
        InfoBar.success("Скопировано", "Текст ошибки скопирован в буфер обмена", duration=1800, parent=dlg)

    def open_logs() -> None:
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(logs_dir))
            else:
                InfoBar.warning(
                    "Папка логов",
                    f"Откройте папку вручную: {logs_dir}",
                    duration=5000,
                    position=InfoBarPosition.TOP,
                    parent=dlg,
                )
        except Exception as exc:
            InfoBar.error(
                "Не удалось открыть логи",
                str(exc),
                duration=5000,
                position=InfoBarPosition.TOP,
                parent=dlg,
            )

    copy_btn.clicked.connect(copy_error)
    open_logs_btn.clicked.connect(open_logs)
    close_btn.clicked.connect(dlg.accept)
    dlg.exec_()
