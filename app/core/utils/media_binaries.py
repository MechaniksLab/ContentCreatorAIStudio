from pathlib import Path

from app.config import BIN_PATH


def resolve_project_media_binary(tool_name: str) -> str:
    """Строгий project-only резолв бинарников ffmpeg/ffprobe.

    PATH намеренно не используется.
    """
    name = str(tool_name or "").strip().lower()
    if not name:
        return tool_name

    candidates = [
        BIN_PATH / f"{name}.exe",
        BIN_PATH / name,
    ]
    for c in candidates:
        if Path(c).exists():
            return str(Path(c).resolve())

    # Важно: не падаем на import-time (часть модулей резолвит бинари при загрузке).
    # Возвращаем ожидаемый project-only путь; фактическая ошибка проявится в месте вызова subprocess.
    # PATH по-прежнему не используется.
    return str((BIN_PATH / f"{name}.exe").resolve())
