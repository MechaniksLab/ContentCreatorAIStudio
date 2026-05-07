import re
from pathlib import Path
from typing import Dict, Optional


def is_mainly_cjk(text: str) -> bool:
    """
    判断文本是否主要由中日韩文字组成
    """
    # 定义CJK字符的Unicode范围
    cjk_patterns = [
        r"[\u4e00-\u9fff]",  # 中日韩统一表意文字
        r"[\u3040-\u309f]",  # 平假名
        r"[\u30a0-\u30ff]",  # 片假名
        r"[\uac00-\ud7af]",  # 韩文音节
    ]
    cjk_count = 0
    for pattern in cjk_patterns:
        cjk_count += len(re.findall(pattern, text))
    total_chars = len("".join(text.split()))
    return cjk_count / total_chars > 0.4 if total_chars > 0 else False


def parse_ass_info(ass_content: str) -> tuple[int, Dict[str, int]]:
    """
    从ASS文件内容中解析视频宽度和各样式的字体大小

    Returns:
        tuple: (视频宽度, {样式名: 字体大小})
    """
    # 获取视频宽度
    play_res_x = 1280  # 默认宽度
    font_sizes = {"Default": 40}  # 默认字体大小

    # 查找视频宽度
    res_x_match = re.search(r"PlayResX:\s*(\d+)", ass_content)
    if res_x_match:
        play_res_x = int(res_x_match.group(1))

    # 查找所有样式的字体大小
    style_section = re.search(r"\[V4\+ Styles\].*?\[", ass_content, re.DOTALL)
    if style_section:
        style_content = style_section.group(0)

        # 获取Format行定义的字段顺序
        format_match = re.search(r"Format:(.*?)$", style_content, re.MULTILINE)
        if format_match:
            # 解析字段名称
            fields = [f.strip() for f in format_match.group(1).split(",")]
            # 找到Fontsize字段的位置
            try:
                fontsize_index = fields.index("Fontsize")
                name_index = fields.index("Name")

                # 使用正确的字段位置来匹配样式行
                for style_line in re.finditer(
                    r"Style:(.*?)$", style_content, re.MULTILINE
                ):
                    style_parts = [p.strip() for p in style_line.group(1).split(",")]
                    if len(style_parts) >= max(fontsize_index + 1, name_index + 1):
                        style_name = style_parts[name_index]
                        font_size = int(style_parts[fontsize_index])
                        font_sizes[style_name] = font_size
            except ValueError:
                pass

    return play_res_x, font_sizes


def estimate_text_width(text: str, font_size: int) -> int:
    """
    估算文本宽度（像素）

    Args:
        text: 文本内容
        font_size: 字体大小

    Returns:
        int: 估算的文本宽度（像素）
    """
    # CJK字符通常是方形，宽度约等于字体大小。
    # Для латиницы берём более реалистичную (и чуть консервативную) оценку,
    # чтобы реже недооценивать ширину и выходить за края в шортсах.
    width = 0
    for char in text:
        if re.match(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]", char):
            width += font_size
        elif char.isspace():
            width += font_size * 0.33
        elif re.match(r"[A-ZА-ЯЁ]", char):
            width += font_size * 0.68
        elif re.match(r"[a-zа-яё]", char):
            width += font_size * 0.60
        elif re.match(r"[0-9]", char):
            width += font_size * 0.58
        elif re.match(r"[\.,:;!\?\-_'" + '"' + r"`~]", char):
            width += font_size * 0.40
        else:
            width += font_size * 0.62
    return int(width)


def _strip_ass_overrides(text: str) -> str:
    """Удаляет ASS override-теги вида {...} для корректной оценки видимой ширины."""
    if not text:
        return text
    return re.sub(r"\{[^}]*\}", "", text)


def _extract_max_fscx_percent(text: str) -> int:
    """Возвращает максимальный fscx из ASS-текста (если нет — 100)."""
    if not text:
        return 100
    vals = [int(v) for v in re.findall(r"\\fscx(\d+)", text)]
    return max(vals) if vals else 100


def _extract_rotation_expansion_factor(text: str) -> float:
    """Оценивает расширение bbox из-за поворота frz (1.0..1.42)."""
    if not text:
        return 1.0
    vals = [abs(float(v)) for v in re.findall(r"\\frz(-?\d+(?:\.\d+)?)", text)]
    if not vals:
        return 1.0
    import math
    max_deg = max(vals) % 180.0
    rad = math.radians(max_deg)
    # bbox expansion for rotated rectangle projection
    factor = abs(math.cos(rad)) + abs(math.sin(rad))
    return max(1.0, min(1.42, factor))


def _fit_text_to_width_with_scale(text: str, max_width: int, font_size: int) -> str:
    """
    Если строка шире max_width, добавляет ASS-масштаб по X/Y, чтобы уместить текст.

    Возвращает исходный текст, если масштаб не нужен.
    """
    if not text:
        return text

    # Масштабируем по самой длинной строке (если текст многострочный через \N).
    visible_lines = [
        ln for ln in _strip_ass_overrides(text).split("\\N") if ln is not None
    ]
    visible = max(visible_lines, key=lambda s: len(s), default="")
    if not visible:
        return text

    current_width = estimate_text_width(visible, font_size)
    current_width = int(current_width * (_extract_max_fscx_percent(text) / 100.0))
    current_width = int(current_width * _extract_rotation_expansion_factor(text))
    # Компенсация реального рендера (outline/shadow/blur/shape),
    # чтобы safe-margin в UI оставался «честным процентом»,
    # а запас учитывался в оценке самой строки, а не в скрытом сужении зоны.
    current_width = int(current_width * 1.90)
    if current_width <= max_width:
        return text

    scale = max(1, min(100, int((max_width / max(1, current_width)) * 100)))
    return f"{{\\fscx{scale}\\fscy{scale}}}{text}"


def _required_scale_percent(text: str, max_width: int, font_size: int) -> int:
    """Вычисляет требуемый процент масштаба (1..100), чтобы текст влез по ширине."""
    visible_lines = [ln for ln in _strip_ass_overrides(text).split("\\N") if ln is not None]
    visible = max(visible_lines, key=lambda s: len(s), default="")
    if not visible:
        return 100
    current_width = estimate_text_width(visible, font_size)
    current_width = int(current_width * (_extract_max_fscx_percent(text) / 100.0))
    current_width = int(current_width * _extract_rotation_expansion_factor(text))
    # Компенсация реального рендера (outline/shadow/blur/shape),
    # чтобы safe-margin в UI оставался «честным процентом»,
    # а запас учитывался в оценке самой строки, а не в скрытом сужении зоны.
    current_width = int(current_width * 1.90)
    if current_width <= max_width:
        return 100
    return max(1, min(100, int((max_width / max(1, current_width)) * 100)))


def _enforce_max_scale_in_ass_text(text: str, max_scale: int) -> str:
    """
    Пропорционально масштабирует существующие \fscx/\fscy так,
    чтобы итоговая ширина влезала в max_scale, но форма эффекта сохранялась.
    """
    if not text:
        return text
    max_scale = max(1, min(100, int(max_scale)))

    ratio = max_scale / 100.0

    def _cap_x(m):
        v = int(m.group(1))
        return f"\\fscx{max(1, int(v * ratio))}"

    def _cap_y(m):
        v = int(m.group(1))
        return f"\\fscy{max(1, int(v * ratio))}"

    out = re.sub(r"\\fscx(\d+)", _cap_x, text)
    out = re.sub(r"\\fscy(\d+)", _cap_y, out)

    # Если масштабных тегов нет, добавляем безопасный базовый.
    if "\\fscx" not in out and "\\fscy" not in out and max_scale < 100:
        out = f"{{\\fscx{max_scale}\\fscy{max_scale}}}{out}"
    return out


def auto_wrap_text(text: str, max_width: int, font_size: int) -> str:
    """
    自动为文本添加换行符

    Args:
        text: 原始文本
        max_width: 最大宽度（像素）
        font_size: 字体大小

    Returns:
        str: 处理后的文本
    """
    if not text:
        return text

    # Если переносы уже есть, всё равно проверяем fitting каждой строки.
    if "\\N" in text:
        lines = text.split("\\N")
        fitted_lines = [
            _fit_text_to_width_with_scale(line, max_width, font_size) if line else line
            for line in lines
        ]
        return "\\N".join(fitted_lines)

    # 如果不是主要由CJK字符组成，则不处理
    if not is_mainly_cjk(text):
        # Для не-CJK (например, длинных латинских слов) применяем ужатие по ширине.
        return _fit_text_to_width_with_scale(text, max_width, font_size)

    # 分割文本为字符列表
    chars = list(text)
    current_line = ""
    result = []

    for char in chars:
        temp_line = current_line + char
        # 计算当前行宽度
        line_width = estimate_text_width(temp_line, font_size)

        if line_width > max_width:
            result.append(current_line)
            current_line = char
        else:
            current_line = temp_line

    if current_line:
        result.append(current_line)

    wrapped = "\\N".join(result)
    # Даже после переноса отдельная строка может быть слишком широкой — дополнительно ужимаем.
    return _fit_text_to_width_with_scale(wrapped, max_width, font_size)


def auto_wrap_ass_file(
    input_file: str,
    output_file: str = None,
    video_width: Optional[int] = None,
    video_height: Optional[int] = None,
    safe_margin_x_percent: int = 8,
    safe_area_enabled: bool = True,
):
    """
    处理ASS文件，为文本添加自动换行

    Args:
        input_file: 输入ASS文件路径
        output_file: 输出ASS文件路径，如果为None则覆盖输入文件
        video_width: 视频宽度，如果提供则覆盖ASS文件中的设置
        video_height: 视频高度，如果提供则覆盖ASS文件中的设置
    """
    if output_file is None:
        output_file = input_file

    # 读取ASS文件
    with open(input_file, "r", encoding="utf-8") as f:
        ass_content = f.read()

    # 解析字体大小（在修改分辨率之前）
    play_res_x, font_sizes = parse_ass_info(ass_content)

    # 如果没有提供视频宽度，使用ASS文件中的宽度
    if video_width is None:
        video_width = play_res_x

    if safe_area_enabled:
        # Строго следуем настройке UI Safe Margin X,
        # чтобы preview и финальный рендер совпадали по горизонтальной зоне.
        user_margin_ratio = max(0.0, min(0.45, float(safe_margin_x_percent) / 100.0))
        # Базовый технический отступ даже при 0%:
        # пользователь ожидает, что текст в любом случае не упирается в края.
        # UI-процент добавляется ПОВЕРХ этого базового отступа.
        base_margin_ratio = 0.06
        total_margin_ratio = min(0.49, base_margin_ratio + user_margin_ratio)
        safe_width = int(video_width * (1.0 - 2.0 * total_margin_ratio))
        max_text_width = max(1, int(safe_width))
    else:
        # Safe Area выключен: не применяем safe-width фильтр.
        max_text_width = max(1, int(video_width))

    # 处理对话行
    def process_dialogue_line(match):
        full_line = match.group(0)

        # 提取样式名
        style_pattern = r"Dialogue:[^,]*,[^,]*,[^,]*,([^,]*),"
        style_match = re.search(style_pattern, full_line)
        style_name = style_match.group(1).strip() if style_match else "Default"

        # 获取对应样式的字体大小
        font_size = font_sizes.get(style_name, font_sizes["Default"])

        # 获取文本内容
        text_part = match.group(1)

        # 处理文本部分
        wrapped_text = auto_wrap_text(text_part, max_text_width, font_size)

        if safe_area_enabled:
            # Защита от эффектов, которые могут позже переопределять масштаб
            # (например, через \fscx100/\fscy100 внутри тэгов):
            # ограничиваем максимальный масштаб по требуемому fit.
            needed_scale = _required_scale_percent(wrapped_text, max_text_width, font_size)
            wrapped_text = _enforce_max_scale_in_ass_text(wrapped_text, needed_scale)

        # 替换原文本
        return full_line.replace(text_part, wrapped_text)

    # 使用正则表达式匹配并处理对话行
    pattern = r"Dialogue:[^,]*(?:,[^,]*){8},(.*?)$"
    processed_content = re.sub(
        pattern, process_dialogue_line, ass_content, flags=re.MULTILINE
    )

    # 保存处理后的文件
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(processed_content)

    return output_file
