"""
Тесты для системы управления эффектами субтитров
"""
import sys
sys.path.insert(0, 'e:/Neyro/VideoCaptioner')

from app.core.subtitle_processor.effect_manager import (
    EffectManager,
    SubtitleEffect,
    EffectConfig
)
from app.core.utils.subtitle_preview import generate_ass_file


def test_apply_ass_effect_scaling_and_index_phase():
    """Проверяем, что ASS-эффекты учитывают разрешение и фазу индекса."""
    text = "Test"

    # Проверка масштабирования базовой позиции под вертикальный кадр 480x852
    bounce = EffectManager.apply_ass_effect(
        text=text,
        effect_type=SubtitleEffect.BOUNCE.value,
        start_ms=0,
        end_ms=2000,
        effect_duration_ms=400,
        effect_intensity=1.0,
        index=0,
        motion_direction="up",
        motion_amplitude=1.0,
        motion_easing="ease_out",
        motion_jitter=0.0,
        play_res_x=480,
        play_res_y=852,
    )
    # Базовая точка для 480x852: (240, 780)
    assert "\\move(" in bounce
    assert ",240,780," in bounce

    # Проверка, что jitter-фаза для разных индексов отличается
    wave_0 = EffectManager.apply_ass_effect(
        text=text,
        effect_type=SubtitleEffect.WAVE.value,
        start_ms=0,
        end_ms=2000,
        effect_duration_ms=300,
        effect_intensity=1.0,
        index=0,
        motion_direction="up",
        motion_amplitude=1.0,
        motion_easing="ease_out",
        motion_jitter=1.0,
        play_res_x=1280,
        play_res_y=720,
    )
    wave_1 = EffectManager.apply_ass_effect(
        text=text,
        effect_type=SubtitleEffect.WAVE.value,
        start_ms=0,
        end_ms=2000,
        effect_duration_ms=300,
        effect_intensity=1.0,
        index=1,
        motion_direction="up",
        motion_amplitude=1.0,
        motion_easing="ease_out",
        motion_jitter=1.0,
        play_res_x=1280,
        play_res_y=720,
    )
    assert wave_0 != wave_1


def test_apply_ass_effect_karaoke_gradient_and_contrast_flags():
    text = "Hello world"
    result = EffectManager.apply_ass_effect(
        text=text,
        effect_type=SubtitleEffect.FADE_IN.value,
        start_ms=0,
        end_ms=2000,
        effect_duration_ms=400,
        karaoke_mode=True,
        karaoke_window_ms=1200,
        auto_contrast=True,
        anti_flicker=True,
        gradient_mode="two_color",
        gradient_color_1="#FFFFFF",
        gradient_color_2="#66CCFF",
    )

    # В режиме сегментных таймингов включается fallback на синтетический \k.
    assert "\\k" in result
    assert "\\bord3" in result
    assert "\\blur1" in result
    assert "\\1c&H" in result


def test_effect_registry_has_no_duplicates():
    dups = EffectManager.get_effect_registry_duplicates()
    assert dups["labels"] == []
    assert dups["values"] == []


def test_new_motion_effects_generate_valid_ass_tags():
    text = "Bounce"
    common = dict(
        text=text,
        start_ms=0,
        end_ms=1800,
        effect_duration_ms=600,
        effect_intensity=1.2,
        motion_direction="up",
        motion_amplitude=1.0,
        motion_easing="ease_out",
        motion_jitter=0.2,
        play_res_x=1280,
        play_res_y=720,
    )

    spring = EffectManager.apply_ass_effect(
        effect_type=SubtitleEffect.BOUNCE_SPRING.value,
        **common,
    )
    assert "\\t(" in spring and "\\pos(" in spring

    elastic = EffectManager.apply_ass_effect(
        effect_type=SubtitleEffect.ELASTIC_POP.value,
        **common,
    )
    assert "\\fscx" in elastic and "\\t(" in elastic

    whip = EffectManager.apply_ass_effect(
        effect_type=SubtitleEffect.WHIP_SLIDE.value,
        **common,
    )
    assert "\\pos(" in whip and "\\t(" in whip

    flip = EffectManager.apply_ass_effect(
        effect_type=SubtitleEffect.FLIP_IN.value,
        **common,
    )
    assert "\\frx" in flip and "\\fry" in flip and "\\t(" in flip

    rubber = EffectManager.apply_ass_effect(
        effect_type=SubtitleEffect.RUBBER_BAND.value,
        **common,
    )
    assert "\\fscx" in rubber and "\\fscy" in rubber and "\\t(" in rubber

    stomp = EffectManager.apply_ass_effect(
        effect_type=SubtitleEffect.STOMP.value,
        **common,
    )
    assert "\\pos(" in stomp and "\\fscx" in stomp and "\\fscy" in stomp


def test_word_timestamp_mode_disables_synthetic_karaoke_k_tags():
    result = EffectManager.apply_ass_effect(
        text="hello",
        effect_type=SubtitleEffect.WORD_HIGHLIGHT.value,
        start_ms=1000,
        end_ms=1450,
        karaoke_mode=True,
        use_word_timestamps=True,
    )
    assert "\\k" not in result


def test_preview_smoke_for_multiple_presets_configs():
    style = (
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Default,Arial,46,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,"
        "0,0,1,2,1,2,20,20,30,1\n"
        "Style: Secondary,Arial,34,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,"
        "0,0,1,2,1,2,20,20,30,1\n"
    )

    presets = [
        {"effect_type": "word_highlight", "karaoke_mode": True},
        {"effect_type": "fade_in", "karaoke_mode": False},
        {"effect_type": "neon_flicker", "karaoke_mode": False},
    ]

    for p in presets:
        ass_path = generate_ass_file(
            style_str=style,
            preview_text=("Hello world", "Привет мир"),
            video_width=1280,
            video_height=720,
            effect_type=p["effect_type"],
            effect_duration_ms=500,
            effect_intensity=1.2,
            karaoke_mode=p["karaoke_mode"],
            karaoke_window_ms=1200,
            gradient_mode="off",
        )
        assert ass_path
        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "[Events]" in content
        assert "Dialogue:" in content


def test_all_effects():
    """Тестирование всех эффектов"""
    manager = EffectManager()
    
    test_text = "Привет мир"
    time_position = 1.0
    
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ ЭФФЕКТОВ СУБТИТРОВ")
    print("=" * 60)
    
    effects_to_test = [
        (SubtitleEffect.NONE, "NONE"),
        (SubtitleEffect.FADE_IN, "FADE_IN"),
        (SubtitleEffect.FADE_OUT, "FADE_OUT"),
        (SubtitleEffect.FADE_IN_OUT, "FADE_IN_OUT"),
        (SubtitleEffect.BOUNCE, "BOUNCE"),
        (SubtitleEffect.PULSE, "PULSE"),
        (SubtitleEffect.WAVE, "WAVE"),
        (SubtitleEffect.SPIN, "SPIN"),
        (SubtitleEffect.ZOOM_IN, "ZOOM_IN"),
        (SubtitleEffect.SWING, "SWING"),
        (SubtitleEffect.GLITCH, "GLITCH"),
        (SubtitleEffect.TYPEWRITER, "TYPEWRITER"),
        (SubtitleEffect.TWINKLE, "TWINKLE"),
        (SubtitleEffect.RAINBOW, "RAINBOW"),
        (SubtitleEffect.SHINE, "SHINE"),
    ]
    
    print(f"\nТекст для теста: '{test_text}'")
    print(f"Временная позиция: {time_position}")
    print("-" * 60)
    
    for effect_type, name in effects_to_test:
        config = EffectConfig(effect_type=effect_type, duration=2.0, intensity=1.0)
        result = manager.apply_effects_to_subtitle(test_text, config, time_position)
        print(f"\n[{name}]:")
        print(f"  Результат: {result}")
    
    print("\n" + "=" * 60)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 60)


def test_typewriter_progression():
    """Тестирование прогрессии эффекта пишущей машинки"""
    manager = EffectManager()
    
    text = "Это тестовое предложение для проверки"
    duration = 3.0
    
    print("\n" + "=" * 60)
    print("ТЕСТ ПРОГРЕССИИ TYPEWRITER")
    print(f"Текст: '{text}'")
    print(f"Длительность: {duration} сек")
    print("-" * 60)
    
    for t in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        result = manager.generate_typewriter_effect(text, t, duration)
        print(f"t={t:.1f}: '{result}'")
    
    print("=" * 60)


def test_wave_effect():
    """Тестирование волнового эффекта для отдельных слов"""
    manager = EffectManager()
    
    text = "Первое Второе Третье Четвертое"
    config = EffectConfig(effect_type=SubtitleEffect.WAVE, duration=2.0, intensity=1.0)
    
    print("\n" + "=" * 60)
    print("ТЕСТ ВОЛНОВОГО ЭФФЕКТА (по словам)")
    print(f"Текст: '{text}'")
    print("-" * 60)
    
    for t in [0.0, 0.5, 1.0, 1.5]:
        result = manager.apply_effects_to_subtitle(text, config, t)
        print(f"t={t:.1f}: {result}")
    
    print("=" * 60)


if __name__ == "__main__":
    test_all_effects()
    test_typewriter_progression()
    test_wave_effect()
