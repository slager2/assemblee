"""Editing recipes: concrete, ready-made shot patterns for vertical Reels/Shorts, built only from the rich vocabulary.

Each recipe is plain data the agent can show the model as optional inspiration (ideas_prompt), or expand into raw
shot dicts for EDL.make_shot (to_shots). Every transition/effect/grade/camera/text_anim/card_style value here is
checked against vocab.py by scripts/check_ideas.py (validate() below), so the model never sees a recipe it cannot build.
Sources and the reasoning behind each recipe: docs/inspiration.md.

Recipe fields:
    id, name_ru, moods (tags for ideas_prompt(mood=...)), when_to_use, caption_pattern, music_hint (edl.MUSIC key),
    why_it_works, source_url, structure: list of steps.
A step uses the same keys as a raw EDL shot (kind, seconds, camera, effects, grade, look, transition_out,
transition_params, transition_seconds, card_style, text_anim, caption_style, caption_position, speed) plus:
    role       what the shot does in the story (hook, setup, reveal, payoff, loop...)
    asset_hint what picture to pick (Russian, for the model)
    caption    caption / card title template ({...} = fill in), for cards also `subtitle`
    same_as    index of an earlier step whose picture must be reused (before/after, loops, freeze-frames)
    sfx        edl.SFX key played at the start of the shot
    animated   True if the step needs an animated/video picture (speed)
"""
import random

S = {  # sources, cited by recipes and docs/inspiration.md
    "tiktok_cbp": "https://ads.tiktok.com/help/article/creative-best-practices?lang=en",
    "tiktok_codes": "https://ads.tiktok.com/business/library/Creative_Codes_ENG.pdf",
    "sme_hooks": "https://www.socialmediaexaminer.com/youtube-shorts-hooks-and-curiosity-loops-that-explode-your-views/",
    "hoyos": "https://creatorscience.com/podcast/jenny-hoyos/",
    "galloway": "https://threadreaderapp.com/thread/1646898356419981315.html",
    "kapwing_freeze": "https://www.kapwing.com/resources/how-to-do-the-record-scratch-yep-thats-me-meme/",
    "kym_freeze": "https://knowyourmeme.com/memes/record-scratch-freeze-frame",
    "kuleshov": "https://www.studiobinder.com/blog/kuleshov-effect/",
    "cutting": "https://www.flickfilosopher.com/2014/02/people-complain-fast-edits-modern-films-need-know.html",
    "speed_ramp": "https://www.studiobinder.com/blog/how-to-speed-ramp-in-premiere/",
    "vidpros_trans": "https://vidpros.com/best-transitions-for-short-form-videos/",
    "framenotion": "https://framenotion.com/blog/best-transitions-for-short-form-video-ads",
    "videobolt_zoom": "https://blog.videobolt.net/post/how-to-create-super-zoom-effect-in-premiere-pro",
    "beatsync_trap": "https://beatsyncpro.ai/blog/trap-music-video-editing-guide-2026.html",
    "loop_capcut": "https://www.capcut.com/create/seamless-loop-videos-continuity-techniques",
    "loop_social": "https://thesocialcat.com/glossary/video-loop-short-form-content",
    "pattern_interrupt": "https://www.capcut.com/create/pattern-interrupt-technique-short-form-video",
    "before_after": "https://insense.pro/blog/how-to-make-before-and-after-video",
    "split_capcut": "https://www.capcut.com/create/split-screen-effects-multi-frame-videos",
    "peak_end": "https://www.billiondollarboy.com/news/brands-need-to-rethink-the-final-three-seconds-of-social-content",
    "retro_motion": "https://www.motionelements.com/blog/articles/bringing-the-past-into-the-present-how-retro-aesthetics-are-shaping-video-production-today",
    "artlist_authentic": "https://artlist.io/blog/authentic-content/",
    "grade_trends": "https://pixflow.net/blog/top-video-editing-trends-2025/",
    "kinetic": "https://www.grid.uns.ac.rs/symposium/download/2024/89.pdf",
    "open_loops": "https://www.socialync.io/blog/open-loops-in-content-2026",
    "ranking": "https://www.gofaceless.ai/en/blog/youtube-shorts-retention-strategy",
    "hook_formulas": "https://www.opus.pro/blog/youtube-shorts-hook-formulas",
}

MOODS = ("energetic", "dark", "retro", "dreamy", "epic", "funny", "calm", "tech", "story")


def _cam(a, b, easing="ease_in_out", sxy=None, exy=None):
    c = {"start_scale": a, "end_scale": b, "easing": easing}
    if sxy:
        c["start_xy"] = sxy
    if exy:
        c["end_xy"] = exy
    return c


RECIPES = [
    # ------------------------------------------------------------------ hooks first
    {"id": "scroll_stop_flash", "name_ru": "Вспышка-стоп", "moods": ["energetic", "epic"],
     "when_to_use": "первые 2 секунды любого энергичного ролика: самый сильный кадр сразу, без вступления",
     "structure": [
         {"role": "hook", "kind": "picture", "seconds": 0.9, "asset_hint": "самый яркий, необычный кадр", "camera": _cam(100, 135, "punch"),
          "effects": [{"id": "rgb_split", "amount": 0.4}], "caption": "{дерзкое утверждение, 3-5 слов}", "caption_style": "cartoon",
          "caption_position": "center", "transition_out": "flash", "transition_seconds": 0.25, "sfx": "boom"},
         {"role": "context", "kind": "picture", "seconds": 1.8, "asset_hint": "что это и где", "camera": _cam(115, 100, "ease_out"),
          "caption": "{кто/что, одной фразой}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "cross_zoom",
          "transition_params": {"amount": 0.6}, "transition_seconds": 0.35}],
     "caption_pattern": "«Это не должно было работать.» / «Самый странный сервер в Roblox»",
     "music_hint": "epic", "why_it_works": "TikTok советует уложить суть в первые 3 секунды и крючок в первые 6; вспышка + удар камеры — визуальный «стоп» для пальца",
     "source_url": S["tiktok_cbp"]},
    {"id": "pov_hook", "name_ru": "POV-крючок", "moods": ["funny", "story"],
     "when_to_use": "когда зрителя можно поставить на место героя: «POV: ты единственный игрок на сервере»",
     "structure": [
         {"role": "hook", "kind": "picture", "seconds": 2.2, "asset_hint": "вид от первого лица или пустое место", "camera": _cam(110, 125, "ease_in"),
          "effects": [{"id": "camera_shake", "params": {"amount": 18, "frequency": 3}}, {"id": "vignette", "amount": 0.25}],
          "caption": "POV: {ситуация, в которой оказался зритель}", "caption_style": "subtitle", "caption_position": "top", "transition_out": "cut"},
         {"role": "turn", "kind": "picture", "seconds": 1.6, "asset_hint": "неожиданный поворот ситуации", "camera": _cam(100, 140, "punch"),
          "caption": "{и тут...}", "caption_style": "cartoon", "caption_position": "center", "transition_out": "whip",
          "transition_params": {"direction": "east"}, "transition_seconds": 0.3, "sfx": "whoosh"}],
     "caption_pattern": "«POV: ты зашёл на сервер в 3 ночи» → «и ты тут не один»",
     "music_hint": "dark_drone", "why_it_works": "формат POV в списках формул крючков — для узнавания и юмора; ручная тряска делает кадр «живым», не рекламным",
     "source_url": S["hook_formulas"]},
    {"id": "text_first_hook", "name_ru": "Сначала слово", "moods": ["story", "tech", "calm"],
     "when_to_use": "если у картинок нет «вау»-кадра: крючок держит текст-вопрос, картинка отвечает",
     "structure": [
         {"role": "hook", "kind": "card", "seconds": 1.8, "card_style": "minimal", "text_anim": "word_by_word",
          "caption": "{вопрос, 3-6 слов}?", "subtitle": "{намёк на ответ}", "transition_out": "cross_zoom", "transition_params": {"amount": 0.7}, "transition_seconds": 0.4},
         {"role": "answer", "kind": "picture", "seconds": 2.0, "asset_hint": "кадр-ответ", "camera": _cam(130, 105, "ease_out"),
          "caption": "{короткий ответ}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "cut"}],
     "caption_pattern": "«Что будет, если паук вырастет?» / «Почему тут никого нет?»",
     "music_hint": "warm_pad", "why_it_works": "текстовый крючок — «самый недооценённый тип» по Social Media Examiner; работает без звука; TikTok рекомендует 5–10 слов в секунду",
     "source_url": S["sme_hooks"]},
    {"id": "error_screen_hook", "name_ru": "Системная ошибка", "moods": ["tech", "dark", "funny"],
     "when_to_use": "игры, приложения, всё цифровое: ролик начинается как сбой интерфейса",
     "structure": [
         {"role": "hook", "kind": "card", "seconds": 1.6, "card_style": "system", "text_anim": "decode",
          "caption": "ОШИБКА: {что сломалось}", "subtitle": "{код или пояснение}", "transition_out": "glitch", "transition_params": {"amount": 0.9}, "transition_seconds": 0.35, "sfx": "glitch"},
         {"role": "reveal", "kind": "picture", "seconds": 2.0, "asset_hint": "то, что «сломалось»", "camera": _cam(100, 125, "punch"),
          "effects": [{"id": "vr_digital_glitch", "params": {"amplitude": [60, 10]}}, {"id": "rgb_split", "params": {"amount": [30, 4]}}],
          "caption": "{объяснение сбоя}", "caption_style": "system", "caption_position": "bottom", "transition_out": "vhs_damage", "transition_params": {"amount": 0.5}}],
     "caption_pattern": "«ОШИБКА: ИГРОКОВ НЕ НАЙДЕНО» / «СИСТЕМА: ПАУК ЭВОЛЮЦИОНИРОВАЛ»",
     "music_hint": "chiptune", "why_it_works": "прерывание шаблона: зритель ждёт контент, а видит «сбой»; глитч, затухающий к нулю, — это раскрытие, а не шум",
     "source_url": S["pattern_interrupt"]},
    {"id": "mystery_blur_reveal", "name_ru": "Тайна в расфокусе", "moods": ["story", "dark", "calm"],
     "when_to_use": "загадка «угадай, что это», анонс, тизер нового мира",
     "structure": [
         {"role": "hook", "kind": "picture", "seconds": 2.4, "asset_hint": "кадр, который интересно угадывать", "camera": _cam(150, 115, "ease_out"),
          "effects": [{"id": "gaussian_blur", "params": {"blurriness": [60, 8]}}, {"id": "vignette", "params": {"amount": -70}}],
          "caption": "Угадай, {что/где} это", "caption_style": "subtitle", "caption_position": "top", "transition_out": "cut"},
         {"role": "reveal", "kind": "picture", "seconds": 2.0, "asset_hint": "тот же кадр", "same_as": 0, "camera": _cam(115, 100, "ease_out"),
          "effects": [{"id": "wonder_glow", "amount": 0.3}], "caption": "{ответ}", "caption_style": "cartoon", "caption_position": "bottom",
          "transition_out": "iris_round", "sfx": "rise"}],
     "caption_pattern": "«Угадай, что это за игра» → «Это паук. Тот самый.»",
     "music_hint": "dark_drone", "why_it_works": "открытая петля любопытства: зритель остаётся до ответа, уйти = бросить загадку",
     "source_url": S["open_loops"]},
    # ------------------------------------------------------------------ transitions-driven chains
    {"id": "zoom_through_chain", "name_ru": "Пролёт сквозь кадры", "moods": ["energetic", "epic"],
     "when_to_use": "путешествие по миру/уровням: «всё глубже»",
     "structure": [
         {"role": "enter", "kind": "picture", "seconds": 1.4, "asset_hint": "общий план", "camera": _cam(100, 170, "ease_in"),
          "transition_out": "cross_zoom", "transition_params": {"amount": 0.9}, "transition_seconds": 0.35, "caption": "{уровень 1}", "caption_style": "subtitle", "caption_position": "top"},
         {"role": "deeper", "kind": "picture", "seconds": 1.2, "asset_hint": "следующий слой мира", "camera": _cam(170, 110, "ease_out"),
          "transition_out": "zoom_blur", "transition_params": {"amount": 0.8}, "transition_seconds": 0.35, "caption": "{уровень 2}", "caption_style": "subtitle", "caption_position": "top"},
         {"role": "deepest", "kind": "picture", "seconds": 2.0, "asset_hint": "самый глубокий/страшный слой", "camera": _cam(160, 100, "ease_out"),
          "effects": [{"id": "vignette", "amount": 0.4}], "caption": "{финальный уровень}", "caption_style": "cartoon", "caption_position": "center", "transition_out": "cut", "sfx": "boom"}],
     "caption_pattern": "«Поверхность» → «Ниже» → «Туда никто не спускался»",
     "music_hint": "epic", "why_it_works": "зум-переход: оба кадра двигаются в одну сторону, и склейка ощущается как движение сквозь пространство",
     "source_url": S["videobolt_zoom"]},
    {"id": "whip_chain", "name_ru": "Цепочка вжухов", "moods": ["energetic", "funny"],
     "when_to_use": "перечислить 3-5 вещей быстро: игры, локации, фичи",
     "structure": [
         {"role": "item", "kind": "picture", "seconds": 1.0, "asset_hint": "пункт 1", "camera": _cam(130, 130, "ease_in", [0.4, 0.5], [0.6, 0.5]),
          "transition_out": "whip", "transition_params": {"direction": "east", "blur": 90}, "transition_seconds": 0.3, "sfx": "whoosh", "caption": "{пункт 1}", "caption_style": "cartoon", "caption_position": "bottom"},
         {"role": "item", "kind": "picture", "seconds": 1.0, "asset_hint": "пункт 2", "camera": _cam(130, 130, "ease_in", [0.4, 0.5], [0.6, 0.5]),
          "transition_out": "whip", "transition_params": {"direction": "east", "blur": 90}, "transition_seconds": 0.3, "sfx": "whoosh", "caption": "{пункт 2}", "caption_style": "cartoon", "caption_position": "bottom"},
         {"role": "item", "kind": "picture", "seconds": 1.0, "asset_hint": "пункт 3", "camera": _cam(130, 130, "ease_in", [0.4, 0.5], [0.6, 0.5]),
          "transition_out": "whip", "transition_params": {"direction": "east", "blur": 90}, "transition_seconds": 0.3, "sfx": "whoosh", "caption": "{пункт 3}", "caption_style": "cartoon", "caption_position": "bottom"},
         {"role": "land", "kind": "picture", "seconds": 2.0, "asset_hint": "главный пункт", "camera": _cam(100, 130, "punch"),
          "caption": "{главный пункт}", "caption_style": "cartoon", "caption_position": "center", "transition_out": "cut"}],
     "caption_pattern": "одно-два слова на пункт: «Слаймы» → «Драконы» → «Сад» → «Всё в одной игре»",
     "music_hint": "chiptune", "why_it_works": "вжух скрывает склейку в размытии; камера в каждом кадре едет в ту же сторону, что и вжух — гиды подчёркивают совпадение направления",
     "source_url": S["vidpros_trans"]},
    {"id": "beat_flash_montage", "name_ru": "Монтаж под бит", "moods": ["energetic", "epic"],
     "when_to_use": "середина ролика, когда надо показать много картинок за 4-5 секунд",
     "structure": [
         *[{"role": "beat", "kind": "picture", "seconds": 0.7, "asset_hint": f"кадр {k + 1} из разных мест", "camera": _cam(100, 118, "punch"),
            "transition_out": "flash", "transition_params": {"intensity": 70}, "transition_seconds": 0.2} for k in range(5)],
         {"role": "hold", "kind": "picture", "seconds": 2.4, "asset_hint": "самый красивый кадр — пауза после бита", "camera": _cam(110, 100, "ease_out"),
          "effects": [{"id": "light_leaks", "amount": 0.4}], "caption": "{итог одной фразой}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "cut"}],
     "caption_pattern": "без подписей на быстрых кадрах; одна фраза на паузе",
     "music_hint": "epic", "why_it_works": "флеш-кадры на ударах — приём из бит-монтажа; длинная пауза после серии работает как контраст",
     "source_url": S["beatsync_trap"]},
    {"id": "speed_ramp_punch", "name_ru": "Рамп-удар", "moods": ["energetic", "epic"],
     "when_to_use": "подчеркнуть один момент: появление босса, взрыв, рекорд",
     "structure": [
         {"role": "build", "kind": "picture", "seconds": 1.8, "asset_hint": "момент перед событием", "camera": _cam(100, 108, "linear"),
          "effects": [{"id": "directional_blur", "params": {"length": [20, 80]}}], "transition_out": "cut", "sfx": "rise"},
         {"role": "impact", "kind": "picture", "seconds": 1.4, "asset_hint": "тот же кадр", "same_as": 0, "camera": _cam(108, 160, "punch", None, [0.5, 0.45]),
          "effects": [{"id": "camera_shake", "params": {"amount": 40, "frequency": 8}}, {"id": "rgb_split", "params": {"amount": [25, 3]}}],
          "caption": "{одно слово-удар}", "caption_style": "cartoon", "caption_position": "center", "transition_out": "earthquake", "transition_params": {"shake": 80}, "transition_seconds": 0.3, "sfx": "boom"}],
     "caption_pattern": "«БАМ.» / «ВОТ ОН.» / «x100»",
     "music_hint": "epic", "why_it_works": "рамп — медленно-медленно-резко: ускорение в момент удара делает его центром внимания (StudioBinder)",
     "source_url": S["speed_ramp"]},
    # ------------------------------------------------------------------ meme formats
    {"id": "freeze_callout", "name_ru": "Стоп-кадр «Да, это я»", "moods": ["funny", "story"],
     "when_to_use": "начало истории с конца: показать абсурдную ситуацию, заморозить, «как я сюда попал»",
     "structure": [
         {"role": "situation", "kind": "picture", "seconds": 1.6, "asset_hint": "абсурдная ситуация", "camera": _cam(100, 125, "ease_in"),
          "transition_out": "cut"},
         {"role": "freeze", "kind": "picture", "seconds": 2.4, "asset_hint": "тот же кадр", "same_as": 0, "camera": _cam(125, 125, "linear"),
          "effects": [{"id": "black_white"}, {"id": "magnify", "params": {"center": [0.5, 0.5], "magnification": 170, "size": 330}}],
          "grade": {"contrast": 30}, "caption": "Да. Это я.\nСейчас объясню, как так вышло", "caption_style": "system", "caption_position": "top", "transition_out": "tv_power", "sfx": "glitch"},
         {"role": "rewind", "kind": "card", "seconds": 1.4, "card_style": "retro2011", "text_anim": "typewriter", "caption": "{время} назад", "subtitle": "",
          "transition_out": "vhs_damage", "transition_params": {"amount": 0.6}}],
     "caption_pattern": "«Да. Это я.» → «За 3 дня до этого...»",
     "music_hint": "chiptune", "why_it_works": "мем record scratch / freeze frame: момент заморозки должен наступить в первые секунды (Kapwing), потом — флешбэк",
     "source_url": S["kapwing_freeze"]},
    {"id": "before_after_wipe", "name_ru": "До / После", "moods": ["story", "calm", "epic"],
     "when_to_use": "апдейт игры, ремастер, прогресс, «было — стало»",
     "structure": [
         {"role": "before", "kind": "picture", "seconds": 1.6, "asset_hint": "картинка «было»", "camera": _cam(110, 110, "linear"),
          "effects": [{"id": "black_white"}, {"id": "noise", "amount": 0.4}], "grade": {"faded_film": 40, "contrast": -20},
          "caption": "ДО", "caption_style": "system", "caption_position": "top", "transition_out": "linear_wipe", "transition_params": {"angle": 90, "feather": 20}, "transition_seconds": 0.6},
         {"role": "after", "kind": "picture", "seconds": 2.6, "asset_hint": "тот же кадр или «стало»", "same_as": 0, "camera": _cam(110, 135, "punch"),
          "grade": {"saturation": 145, "vibrance": 30, "contrast": 20}, "effects": [{"id": "light_leaks", "amount": 0.3}],
          "caption": "ПОСЛЕ", "caption_style": "cartoon", "caption_position": "top", "transition_out": "cut", "sfx": "notify"}],
     "caption_pattern": "«ДО» / «ПОСЛЕ» крупно сверху; одна строка снизу — что изменилось",
     "music_hint": "warm_pad", "why_it_works": "контраст до/после читается без звука; держать «до» 1-2 с, «после» 2-4 с, снимать с одной точки",
     "source_url": S["before_after"]},
    {"id": "versus_card", "name_ru": "Против", "moods": ["energetic", "funny"],
     "when_to_use": "сравнить две игры, два мира, «ожидание vs реальность»",
     "structure": [
         {"role": "side_a", "kind": "picture", "seconds": 1.8, "asset_hint": "вариант А", "camera": _cam(100, 120, "ease_in"),
          "grade": {"temperature": -45, "saturation": 80}, "caption": "{А}", "caption_style": "cartoon", "caption_position": "top",
          "transition_out": "split", "transition_params": {"orientation": "Horizontal"}, "transition_seconds": 0.4},
         {"role": "vs", "kind": "card", "seconds": 1.2, "card_style": "glitch", "text_anim": "scale_pop", "caption": "VS", "subtitle": "",
          "transition_out": "barn_doors", "transition_params": {"orientation": "Vertical"}, "transition_seconds": 0.4, "sfx": "boom"},
         {"role": "side_b", "kind": "picture", "seconds": 1.8, "asset_hint": "вариант Б", "camera": _cam(100, 120, "ease_in"),
          "grade": {"temperature": 45, "saturation": 140}, "caption": "{Б}", "caption_style": "cartoon", "caption_position": "top", "transition_out": "cut"}],
     "caption_pattern": "«Ожидание» VS «Реальность» / «2011» VS «2026»",
     "music_hint": "chiptune", "why_it_works": "сравнение — встроенный вопрос «кто победит»; холодная и тёплая стороны различаются даже на миниатюре",
     "source_url": S["split_capcut"]},
    {"id": "countdown_top3", "name_ru": "Топ-3 с отсчётом", "moods": ["energetic", "funny", "story"],
     "when_to_use": "рейтинг, подборка: зритель досматривает ради №1",
     "structure": [
         {"role": "hook", "kind": "card", "seconds": 1.5, "card_style": "cartoon", "text_anim": "slide_up", "caption": "ТОП-3 {чего}", "subtitle": "№1 вас удивит",
          "transition_out": "pop_motion", "transition_seconds": 0.35},
         {"role": "n3", "kind": "card", "seconds": 1.2, "card_style": "minimal", "text_anim": "scale_pop", "caption": "3", "subtitle": "{пункт 3}", "transition_out": "push", "transition_params": {"direction": "north"}, "transition_seconds": 0.3},
         {"role": "item3", "kind": "picture", "seconds": 1.6, "asset_hint": "пункт 3", "camera": _cam(100, 120, "ease_in"), "transition_out": "push", "transition_params": {"direction": "north"}, "transition_seconds": 0.3},
         {"role": "n2", "kind": "card", "seconds": 1.2, "card_style": "minimal", "text_anim": "scale_pop", "caption": "2", "subtitle": "{пункт 2}", "transition_out": "push", "transition_params": {"direction": "north"}, "transition_seconds": 0.3},
         {"role": "item2", "kind": "picture", "seconds": 1.6, "asset_hint": "пункт 2", "camera": _cam(100, 125, "ease_in"), "transition_out": "push", "transition_params": {"direction": "north"}, "transition_seconds": 0.3},
         {"role": "n1", "kind": "card", "seconds": 1.3, "card_style": "glitch", "text_anim": "glitch", "caption": "1", "subtitle": "{пункт 1}", "transition_out": "flash", "transition_seconds": 0.25, "sfx": "rise"},
         {"role": "item1", "kind": "picture", "seconds": 2.6, "asset_hint": "пункт 1 — лучший кадр", "camera": _cam(100, 140, "punch"),
          "effects": [{"id": "wonder_glow", "amount": 0.4}, {"id": "lens_flare", "params": {"center": [0.92, 0.06], "brightness": [60, 130]}}], "transition_out": "cut", "sfx": "boom"}],
     "caption_pattern": "«ТОП-3 самых жутких мест» — каждый следующий пункт сильнее предыдущего",
     "music_hint": "epic", "why_it_works": "листикл: «зритель остаётся ради третьего пункта»; список должен нарастать, плоский список теряет зрителей",
     "source_url": S["ranking"]},
    {"id": "loop_ending", "name_ru": "Бесконечная петля", "moods": ["story", "calm", "funny"],
     "when_to_use": "почти любой короткий ролик (до 20 с): последний кадр перетекает в первый",
     "structure": [
         {"role": "open", "kind": "picture", "seconds": 1.8, "asset_hint": "кадр-петля (тот же будет в конце)", "camera": _cam(135, 110, "ease_out"),
          "caption": "{вторая половина фразы}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "cut"},
         {"role": "middle", "kind": "picture", "seconds": 2.2, "asset_hint": "основное содержание", "camera": _cam(100, 120, "ease_in_out"), "transition_out": "film_dissolve", "transition_seconds": 0.5},
         {"role": "close", "kind": "picture", "seconds": 1.8, "asset_hint": "тот же кадр, что в начале", "same_as": 0, "camera": _cam(110, 135, "ease_in"),
          "caption": "{первая половина фразы}...", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "cut"}],
     "caption_pattern": "конец: «И вот почему этот сервер...» → начало: «...до сих пор никто не закрыл»",
     "music_hint": "warm_pad", "why_it_works": "незаконченная фраза в конце продолжается в начале; камера финала заканчивает там, где начинается первый кадр — повторы поднимают удержание",
     "source_url": S["loop_capcut"]},
    # ------------------------------------------------------------------ aesthetics
    {"id": "vhs_memory", "name_ru": "Кассета из 2007", "moods": ["retro", "story", "dreamy"],
     "when_to_use": "ностальгия, «старые добрые», классические карты, детство",
     "structure": [
         {"role": "hook", "kind": "card", "seconds": 1.6, "card_style": "retro2011", "text_anim": "typewriter", "caption": "{год}", "subtitle": "{где/что}",
          "transition_out": "vhs_damage", "transition_params": {"amount": 0.7}, "transition_seconds": 0.5},
         *[{"role": "memory", "kind": "picture", "seconds": 2.0, "asset_hint": f"старый кадр {k + 1}", "camera": _cam(112, 100, "linear"),
            "grade": {"faded_film": 45, "temperature": 18, "saturation": 85, "contrast": -10},
            "effects": [{"id": "noise", "amount": 0.3}, {"id": "rgb_split", "amount": 0.15}, {"id": "lens_distortion", "params": {"curvature": -20}}],
            "caption": "{воспоминание}", "caption_style": "retro2011", "caption_position": "bottom",
            "transition_out": "vhs_damage" if k == 0 else "tv_power", "transition_params": {"amount": 0.5} if k == 0 else {}, "transition_seconds": 0.5} for k in range(2)],
         {"role": "end", "kind": "card", "seconds": 1.8, "card_style": "final", "text_anim": "fade_letters", "caption": "{что осталось сейчас}", "subtitle": ""}],
     "caption_pattern": "«2011. Сервер был полон.» → «Мы строили тут всё лето»",
     "music_hint": "warm_pad", "why_it_works": "VHS/CRT-эстетика контрастирует с гладким контентом ленты и даёт ощущение «настоящего артефакта»",
     "source_url": S["retro_motion"]},
    {"id": "crt_boot", "name_ru": "Включение старого телевизора", "moods": ["retro", "tech"],
     "when_to_use": "интро или финал: ролик «включается» и «выключается» как кинескоп",
     "structure": [
         {"role": "boot", "kind": "card", "seconds": 1.4, "card_style": "system", "text_anim": "typewriter", "caption": "КАНАЛ {N}", "subtitle": "{название}",
          "transition_out": "tv_power", "transition_params": {"line": 6}, "transition_seconds": 0.6},
         {"role": "picture", "kind": "picture", "seconds": 2.2, "asset_hint": "первый кадр", "camera": _cam(100, 112, "ease_in"),
          "effects": [{"id": "lens_distortion", "params": {"curvature": -40}}, {"id": "noise", "amount": 0.3}],
          "transition_out": "phosphor", "transition_params": {"decay": 70}, "transition_seconds": 0.6},
         {"role": "picture", "kind": "picture", "seconds": 2.2, "asset_hint": "второй кадр", "camera": _cam(112, 100, "ease_out"),
          "effects": [{"id": "lens_distortion", "params": {"curvature": -40}}, {"id": "noise", "amount": 0.3}], "caption": "{подпись}", "caption_style": "system", "caption_position": "bottom",
          "transition_out": "tv_power", "transition_seconds": 0.6}],
     "caption_pattern": "«КАНАЛ 3 — ПОСЛЕДНИЙ ОНЛАЙН»",
     "music_hint": "dark_drone", "why_it_works": "кривизна кинескопа + выключение в полоску — узнаваемые маркеры ретро-эстетики, которые отделяют ролик от «полированной» ленты",
     "source_url": S["retro_motion"]},
    {"id": "kinetic_manifesto", "name_ru": "Кинетический манифест", "moods": ["epic", "story", "tech"],
     "when_to_use": "питч, слоган, три коротких тезиса между картинками",
     "structure": [
         {"role": "claim", "kind": "card", "seconds": 1.4, "card_style": "minimal", "text_anim": "tracking_in", "caption": "{тезис 1}", "subtitle": "",
          "transition_out": "push", "transition_params": {"direction": "west"}, "transition_seconds": 0.3},
         {"role": "proof", "kind": "picture", "seconds": 1.0, "asset_hint": "доказательство 1", "camera": _cam(100, 120, "punch"), "transition_out": "push", "transition_params": {"direction": "west"}, "transition_seconds": 0.3},
         {"role": "claim", "kind": "card", "seconds": 1.4, "card_style": "minimal", "text_anim": "slide_up", "caption": "{тезис 2}", "subtitle": "",
          "transition_out": "push", "transition_params": {"direction": "west"}, "transition_seconds": 0.3},
         {"role": "proof", "kind": "picture", "seconds": 1.0, "asset_hint": "доказательство 2", "camera": _cam(100, 120, "punch"), "transition_out": "push", "transition_params": {"direction": "west"}, "transition_seconds": 0.3},
         {"role": "claim", "kind": "card", "seconds": 1.8, "card_style": "final", "text_anim": "blur_in", "caption": "{вывод}", "subtitle": "{название}"}],
     "caption_pattern": "три тезиса по 2-4 слова: «Без игроков.» «Без правил.» «Без выхода.»",
     "music_hint": "epic", "why_it_works": "скорость и интерполяция анимации текста влияют на понимание (исследование кинетической типографики); короткие тезисы читаются за долю секунды",
     "source_url": S["kinetic"]},
    {"id": "one_word_beats", "name_ru": "Одно слово на кадр", "moods": ["energetic", "story"],
     "when_to_use": "фраза из 4-6 слов, разложенная по кадрам: каждый кадр — одно слово",
     "structure": [
         *[{"role": "word", "kind": "picture", "seconds": 0.8, "asset_hint": f"кадр под слово {k + 1}", "camera": _cam(105, 125, "punch"),
            "caption": f"{{слово {k + 1}}}", "caption_style": "cartoon", "caption_position": "center", "transition_out": "cut"} for k in range(4)],
         {"role": "last_word", "kind": "picture", "seconds": 2.0, "asset_hint": "кадр под последнее слово", "camera": _cam(100, 140, "punch"),
          "effects": [{"id": "rgb_split", "params": {"amount": [20, 3]}}], "caption": "{последнее слово}", "caption_style": "cartoon", "caption_position": "center", "transition_out": "cut", "sfx": "boom"}],
     "caption_pattern": "«Ты» → «никогда» → «не» → «выйдешь» → «ОТСЮДА.»",
     "music_hint": "dark_drone", "why_it_works": "смена кадра каждые ~1 с (средняя длина кадра в кино упала до ~2.5 с и продолжает падать); каждое слово — повод остаться",
     "source_url": S["cutting"]},
    {"id": "cold_to_warm_story", "name_ru": "Цветовая история: холод → тепло", "moods": ["story", "calm", "dreamy"],
     "when_to_use": "история «из одиночества к друзьям», «из тьмы к свету»: цвет рассказывает сюжет",
     "structure": [
         {"role": "cold", "kind": "picture", "seconds": 2.2, "asset_hint": "пустой/одинокий кадр", "camera": _cam(115, 100, "linear"),
          "grade": {"temperature": -50, "saturation": 55, "exposure": -0.4}, "caption": "{было одиноко}", "caption_style": "subtitle", "caption_position": "bottom",
          "transition_out": "film_dissolve", "transition_seconds": 0.7},
         {"role": "neutral", "kind": "picture", "seconds": 2.0, "asset_hint": "поворотный кадр", "camera": _cam(100, 115, "ease_in_out"), "grade": {"temperature": 0, "saturation": 95},
          "transition_out": "light_leak", "transition_params": {"amount": 0.6}, "transition_seconds": 0.7},
         {"role": "warm", "kind": "picture", "seconds": 2.6, "asset_hint": "тёплый, людный кадр", "camera": _cam(100, 120, "ease_in"),
          "grade": {"creative_look": "Golden Hour", "look_intensity": 110, "temperature": 40, "saturation": 125},
          "effects": [{"id": "light_leaks", "amount": 0.5}], "caption": "{стало тепло}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "cut"}],
     "caption_pattern": "«Сначала здесь не было никого.» → «А потом пришли мы.»",
     "music_hint": "warm_pad", "why_it_works": "выразительный, «сюжетный» грейдинг — тренд 2025; смена температуры заметна даже боковым зрением",
     "source_url": S["grade_trends"]},
    {"id": "kuleshov_contrast", "name_ru": "Эффект Кулешова", "moods": ["dark", "story"],
     "when_to_use": "один и тот же кадр героя меняет смысл от соседнего кадра (угроза — страх, награда — радость)",
     "structure": [
         {"role": "face", "kind": "picture", "seconds": 1.5, "asset_hint": "нейтральный кадр героя", "camera": _cam(110, 118, "linear"), "transition_out": "cut"},
         {"role": "threat", "kind": "picture", "seconds": 1.5, "asset_hint": "угроза", "camera": _cam(100, 130, "punch"),
          "grade": {"temperature": -40, "saturation": 60, "exposure": -0.5}, "effects": [{"id": "camera_shake", "amount": 0.3}], "transition_out": "cut", "sfx": "boom"},
         {"role": "face_again", "kind": "picture", "seconds": 1.5, "asset_hint": "тот же кадр героя", "same_as": 0, "camera": _cam(118, 135, "linear"),
          "effects": [{"id": "vignette", "params": {"amount": -70}}], "caption": "{мысль героя}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "cut"}],
     "caption_pattern": "минимум текста: «Он это видит.»",
     "music_hint": "dark_drone", "why_it_works": "зритель считывает смысл из пары кадров, а не из одного; три кадра: догадка — подтверждение — новое прочтение героя",
     "source_url": S["kuleshov"]},
    {"id": "calm_then_chaos", "name_ru": "Тишина перед бурей", "moods": ["dark", "energetic", "funny"],
     "when_to_use": "резкий контраст ритма: спокойно-спокойно-ХАОС",
     "structure": [
         {"role": "calm", "kind": "picture", "seconds": 2.6, "asset_hint": "мирный кадр", "camera": _cam(100, 106, "linear"),
          "grade": {"saturation": 85, "faded_film": 20}, "caption": "{всё было спокойно}", "caption_style": "subtitle", "caption_position": "bottom",
          "transition_out": "chaos", "transition_params": {"amount": 1}, "transition_seconds": 0.35},
         {"role": "chaos", "kind": "picture", "seconds": 0.8, "asset_hint": "хаос", "camera": _cam(120, 150, "punch"),
          "effects": [{"id": "camera_shake", "params": {"amount": 60, "frequency": 10}}, {"id": "vr_digital_glitch", "amount": 0.6}], "transition_out": "earthquake", "transition_seconds": 0.25, "sfx": "boom"},
         {"role": "chaos", "kind": "picture", "seconds": 0.8, "asset_hint": "ещё хаос", "camera": _cam(150, 110, "punch"),
          "effects": [{"id": "camera_shake", "params": {"amount": 60, "frequency": 10}}, {"id": "rgb_split", "amount": 0.6}], "transition_out": "glitch", "transition_seconds": 0.25},
         {"role": "aftermath", "kind": "card", "seconds": 1.6, "card_style": "glitch", "text_anim": "glitch", "caption": "{что случилось}", "subtitle": ""}],
     "caption_pattern": "«Обычный день на сервере.» → [хаос] → «Никто не ожидал»",
     "music_hint": "dark_drone", "why_it_works": "прерывание шаблона: внезапная смена ритма заново захватывает внимание; длинная спокойная пауза делает удар сильнее",
     "source_url": S["pattern_interrupt"]},
    {"id": "tilt_shift_miniature", "name_ru": "Игрушечный мир", "moods": ["calm", "funny", "dreamy"],
     "when_to_use": "карты, города, виды сверху: мир выглядит как макет",
     "structure": [
         {"role": "world", "kind": "picture", "seconds": 2.6, "asset_hint": "вид сверху / общий план", "camera": _cam(110, 125, "ease_in_out"),
          "grade": {"saturation": 150, "contrast": 20, "exposure": 0.2}, "effects": [{"id": "focus_blur", "params": {"shape": "Linear", "amount": 60}}],
          "caption": "{масштаб мира}", "caption_style": "subtitle", "caption_position": "top", "transition_out": "travel_motion", "transition_params": {"direction": "east", "zoom": 30}, "transition_seconds": 0.6},
         {"role": "world", "kind": "picture", "seconds": 2.6, "asset_hint": "второй общий план", "camera": _cam(125, 110, "ease_in_out"),
          "grade": {"saturation": 150, "contrast": 20, "exposure": 0.2}, "effects": [{"id": "focus_blur", "params": {"shape": "Linear", "amount": 60}}], "transition_out": "cut"}],
     "caption_pattern": "«Весь мир — 2 км» / «Тут живёт 50 000 игроков»",
     "music_hint": "chiptune", "why_it_works": "тилт-шифт превращает знакомое в «игрушку» — простой способ показать масштаб неожиданно",
     "source_url": S["grade_trends"]},
    {"id": "sketch_to_colour", "name_ru": "Из наброска в цвет", "moods": ["story", "calm", "tech"],
     "when_to_use": "показать «как это сделано», концепт → готовая игра",
     "structure": [
         {"role": "sketch", "kind": "picture", "seconds": 2.0, "asset_hint": "готовый кадр (сначала как набросок)", "camera": _cam(115, 108, "linear"),
          "effects": [{"id": "find_edges", "params": {"blend": 0, "invert": True}}, {"id": "black_white"}], "caption": "{идея}", "caption_style": "subtitle", "caption_position": "top",
          "transition_out": "luma_fade", "transition_params": {"softness": 40}, "transition_seconds": 1.0},
         {"role": "colour", "kind": "picture", "seconds": 2.4, "asset_hint": "тот же кадр", "same_as": 0, "camera": _cam(108, 100, "ease_out"),
          "grade": {"saturation": 130, "vibrance": 25}, "caption": "{результат}", "caption_style": "subtitle", "caption_position": "top", "transition_out": "cut", "sfx": "notify"}],
     "caption_pattern": "«Это был просто набросок.» → «Теперь в это играют тысячи»",
     "music_hint": "warm_pad", "why_it_works": "разновидность «до/после», где «до» — линии; переход по яркости проявляет цвет постепенно",
     "source_url": S["before_after"]},
    {"id": "pop_art_grid", "name_ru": "Поп-арт сетка", "moods": ["funny", "energetic", "retro"],
     "when_to_use": "персонаж/предмет-мем, повторение как шутка",
     "structure": [
         {"role": "single", "kind": "picture", "seconds": 1.2, "asset_hint": "персонаж крупно", "camera": _cam(100, 125, "punch"), "transition_out": "stripe", "transition_params": {"stripes": 8}, "transition_seconds": 0.35},
         {"role": "grid", "kind": "picture", "seconds": 2.2, "asset_hint": "тот же персонаж", "same_as": 0, "camera": _cam(100, 108, "linear"),
          "grade": {"saturation": 170, "contrast": 30}, "effects": [{"id": "clone", "params": {"columns": 2, "gap": 10}}, {"id": "posterize", "params": {"levels": 5}}],
          "caption": "{его так много}", "caption_style": "cartoon", "caption_position": "center", "transition_out": "cut", "sfx": "notify"}],
     "caption_pattern": "«Один слайм — мило.» → «Четыре — уже проблема.»",
     "music_hint": "chiptune", "why_it_works": "резкий переход в стилизацию — визуальная шутка и прерывание шаблона, сетка читается даже на миниатюре",
     "source_url": S["pattern_interrupt"]},
    {"id": "single_colour_accent", "name_ru": "Один цвет", "moods": ["dark", "epic"],
     "when_to_use": "выделить главное в кадре: лава, кровь, огонь, знак",
     "structure": [
         {"role": "accent", "kind": "picture", "seconds": 2.4, "asset_hint": "кадр с одним ярким красным/оранжевым объектом", "camera": _cam(100, 130, "ease_in"),
          "effects": [{"id": "color_pass", "params": {"color": "#ff5020", "similarity": 30}}, {"id": "vignette", "amount": 0.3}], "grade": {"contrast": 35},
          "caption": "{на что смотреть}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "burn_alpha", "transition_seconds": 0.7},
         {"role": "full", "kind": "picture", "seconds": 2.0, "asset_hint": "следующий кадр в полном цвете", "camera": _cam(120, 100, "ease_out"),
          "grade": {"creative_look": "Teal & Orange", "look_intensity": 100}, "transition_out": "cut"}],
     "caption_pattern": "«Видишь красное? Не наступай.»",
     "music_hint": "dark_drone", "why_it_works": "один цвет на сером фоне ведёт взгляд точно туда, куда нужно; затем полный цвет — как разрешение",
     "source_url": S["grade_trends"]},
    {"id": "neon_outline", "name_ru": "Неоновый контур", "moods": ["tech", "dark", "energetic"],
     "when_to_use": "кибер, ночь, системный интерфейс, «скрытый мир»",
     "structure": [
         {"role": "neon", "kind": "picture", "seconds": 2.0, "asset_hint": "кадр с чёткими формами", "camera": _cam(100, 118, "ease_in"),
          "grade": {"exposure": -0.8, "saturation": 70}, "effects": [{"id": "edge_glow", "params": {"color": "#3fd8ff", "intensity": 340, "threshold": 20}}],
          "caption": "{скрытое}", "caption_style": "system", "caption_position": "top", "transition_out": "neon_wipe", "transition_params": {"color": "#ff2e8a", "glow": 80}, "transition_seconds": 0.6},
         {"role": "neon", "kind": "picture", "seconds": 2.0, "asset_hint": "второй кадр", "camera": _cam(118, 100, "ease_out"),
          "grade": {"exposure": -0.8, "saturation": 70}, "effects": [{"id": "edge_glow", "params": {"color": "#ff2e8a", "intensity": 340, "threshold": 20}}], "transition_out": "cut"}],
     "caption_pattern": "«СКАНИРОВАНИЕ... найдено 3 объекта»",
     "music_hint": "chiptune", "why_it_works": "неоновые контуры и хром — частые приёмы ретро/кибер-стилистики для соцсетей",
     "source_url": S["retro_motion"]},
    {"id": "dream_float", "name_ru": "Сон наяву", "moods": ["dreamy", "calm"],
     "when_to_use": "мечта, воспоминание, медленная красивая секция между быстрыми",
     "structure": [
         {"role": "dream", "kind": "picture", "seconds": 2.8, "asset_hint": "красивый светлый кадр", "camera": _cam(100, 112, "ease_in_out"),
          "look": "dreamy", "effects": [{"id": "gaussian_blur", "params": {"blurriness": [30, 0]}}, {"id": "light_leaks", "amount": 0.3}],
          "transition_out": "blur_dissolve", "transition_params": {"blur": 70}, "transition_seconds": 1.0},
         {"role": "words", "kind": "card", "seconds": 2.0, "card_style": "minimal", "text_anim": "fade_letters", "caption": "{мечта}", "subtitle": "",
          "transition_out": "blur_dissolve", "transition_params": {"blur": 70}, "transition_seconds": 0.8},
         {"role": "dream", "kind": "picture", "seconds": 2.8, "asset_hint": "второй мягкий кадр", "camera": _cam(112, 100, "ease_in_out"),
          "look": "dreamy", "effects": [{"id": "light_leaks", "amount": 0.5}], "transition_out": "cut"}],
     "caption_pattern": "«Представь мир, где ты главный.»",
     "music_hint": "warm_pad", "why_it_works": "замедление после быстрых секций — смена ритма; мягкий свет и долгие растворения дают «пик» эмоции",
     "source_url": S["peak_end"]},
    {"id": "horror_strobe", "name_ru": "Тревожный стробоскоп", "moods": ["dark"],
     "when_to_use": "хоррор, бэкрумы, «что-то не так»",
     "structure": [
         {"role": "dread", "kind": "picture", "seconds": 2.6, "asset_hint": "пустой коридор/тёмное место", "camera": _cam(100, 118, "linear"),
          "look": "horror_cold", "effects": [{"id": "noise", "amount": 0.4}, {"id": "vignette", "params": {"amount": -75}}],
          "caption": "{тихая фраза}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "flicker", "transition_params": {"flickers": 8}, "transition_seconds": 0.6},
         {"role": "flash", "kind": "picture", "seconds": 1.2, "asset_hint": "существо/угроза", "camera": _cam(120, 145, "punch"),
          "look": "horror_cold", "effects": [{"id": "strobe", "params": {"period": 0.25}}, {"id": "camera_shake", "amount": 0.4}], "transition_out": "dip_to_black", "transition_seconds": 0.4, "sfx": "boom"},
         {"role": "sting", "kind": "card", "seconds": 1.6, "card_style": "glitch", "text_anim": "glitch", "caption": "{оно здесь}", "subtitle": ""}],
     "caption_pattern": "«Ты слышал шаги?» → [вспышка] → «ОНО ЗДЕСЬ»",
     "music_hint": "dark_drone", "why_it_works": "долгая тихая пауза + резкий стробоскоп = джампскейр; приглушённый холодный цвет держит тревогу",
     "source_url": S["pattern_interrupt"]},
    {"id": "movie_trailer", "name_ru": "Кинотрейлер", "moods": ["epic", "story"],
     "when_to_use": "анонс, «в мире, где...», серьёзная подача игры",
     "structure": [
         {"role": "world", "kind": "picture", "seconds": 2.6, "asset_hint": "эпичный общий план", "camera": _cam(100, 115, "ease_in"),
          "grade": {"creative_look": "Teal & Orange", "look_intensity": 120, "contrast": 25}, "effects": [{"id": "crop", "params": {"top": 12, "bottom": 12}}],
          "caption": "В мире, где {условие}...", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "dip_to_black", "transition_seconds": 0.6},
         {"role": "hero", "kind": "picture", "seconds": 2.4, "asset_hint": "герой", "camera": _cam(115, 100, "ease_out"),
          "grade": {"creative_look": "Teal & Orange", "look_intensity": 120, "contrast": 25}, "effects": [{"id": "crop", "params": {"top": 12, "bottom": 12}}],
          "caption": "...один {герой}...", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "dip_to_black", "transition_seconds": 0.6, "sfx": "boom"},
         {"role": "title", "kind": "card", "seconds": 2.2, "card_style": "final", "text_anim": "tracking_in", "caption": "{НАЗВАНИЕ}", "subtitle": "{скоро}"}],
     "caption_pattern": "«В мире, где никто не выходит онлайн...» → «...один игрок остался»",
     "music_hint": "epic", "why_it_works": "Shorts как «интро»: сжатая история целого ролика (Падди Гэллоуэй); летербокс и затемнения — язык трейлера",
     "source_url": S["galloway"]},
    {"id": "detail_magnifier", "name_ru": "Лупа на деталь", "moods": ["funny", "story", "tech"],
     "when_to_use": "пасхалка, скрытая деталь, «а вы заметили?»",
     "structure": [
         {"role": "wide", "kind": "picture", "seconds": 1.8, "asset_hint": "кадр с маленькой интересной деталью", "camera": _cam(100, 108, "linear"),
          "caption": "Ты заметил?", "caption_style": "subtitle", "caption_position": "top", "transition_out": "cut"},
         {"role": "zoom", "kind": "picture", "seconds": 2.4, "asset_hint": "тот же кадр", "same_as": 0, "camera": _cam(108, 108, "linear"),
          "effects": [{"id": "magnify", "params": {"center": [0.6, 0.45], "magnification": [130, 240], "size": 360}}, {"id": "vignette", "amount": 0.3}],
          "caption": "{что там спрятано}", "caption_style": "cartoon", "caption_position": "bottom", "transition_out": "cut", "sfx": "notify"}],
     "caption_pattern": "«Ты заметил?» → «В углу каждой карты — он»",
     "music_hint": "chiptune", "why_it_works": "вопрос + обещание детали — открытая петля, которую закрывают через 2 секунды",
     "source_url": S["open_loops"]},
    {"id": "hero_flare_reveal", "name_ru": "Явление героя", "moods": ["epic"],
     "when_to_use": "появление главного персонажа, босса, логотипа",
     "structure": [
         {"role": "dark", "kind": "picture", "seconds": 2.6, "asset_hint": "герой/босс", "camera": _cam(100, 128, "ease_in"),
          "grade": {"exposure": -0.3, "contrast": 35, "shadows": -30},
          "effects": [{"id": "wonder_glow", "params": {"intensity": [60, 260]}}, {"id": "volumetric_rays", "params": {"intensity": [50, 200]}}],
          "caption": "{имя}", "caption_style": "cartoon", "caption_position": "bottom", "transition_out": "light_sweep", "transition_params": {"width": 260}, "transition_seconds": 0.6, "sfx": "rise"},
         {"role": "title", "kind": "card", "seconds": 2.0, "card_style": "final", "text_anim": "blur_in", "caption": "{титул героя}", "subtitle": ""}],
     "caption_pattern": "«Мать.» → «Королева пауков»",
     "music_hint": "epic", "why_it_works": "свечение и лучи нарастают вместе с камерой — классический «пик», который по правилу «пик-конец» запоминается сильнее всего",
     "source_url": S["peak_end"]},
    {"id": "page_story", "name_ru": "Страницы дневника", "moods": ["story", "retro", "calm"],
     "when_to_use": "хронология, история создания, «глава 1 / глава 2»",
     "structure": [
         {"role": "chapter", "kind": "card", "seconds": 1.6, "card_style": "minimal", "text_anim": "typewriter", "caption": "Глава 1", "subtitle": "{название главы}",
          "transition_out": "page_turn", "transition_seconds": 0.7},
         {"role": "page", "kind": "picture", "seconds": 2.2, "asset_hint": "событие главы 1", "camera": _cam(112, 100, "linear"), "look": "warm_memory",
          "effects": [{"id": "noise", "amount": 0.3}, {"id": "edge_feather", "amount": 0.4}], "caption": "{что произошло}", "caption_style": "subtitle", "caption_position": "bottom",
          "transition_out": "page_peel", "transition_params": {"corner": "Bottom Right"}, "transition_seconds": 0.8},
         {"role": "page", "kind": "picture", "seconds": 2.2, "asset_hint": "событие главы 2", "camera": _cam(100, 112, "linear"), "look": "warm_memory",
          "effects": [{"id": "noise", "amount": 0.3}, {"id": "edge_feather", "amount": 0.4}], "caption": "{что произошло потом}", "caption_style": "subtitle", "caption_position": "bottom",
          "transition_out": "fold_motion", "transition_params": {"direction": "east"}, "transition_seconds": 0.7}],
     "caption_pattern": "«Глава 1. Рождение» → «Глава 2. Голод»",
     "music_hint": "warm_pad", "why_it_works": "цепочка «но/поэтому»: каждая глава — следствие предыдущей (структура Дженни Хойос)",
     "source_url": S["hoyos"]},
    {"id": "portal_twist", "name_ru": "Портал", "moods": ["dreamy", "energetic", "tech"],
     "when_to_use": "переход между мирами/играми, «переносимся в...»",
     "structure": [
         {"role": "here", "kind": "picture", "seconds": 1.8, "asset_hint": "мир А", "camera": _cam(100, 130, "ease_in"),
          "effects": [{"id": "twirl", "params": {"angle": [0, 200], "radius": 50}}], "caption": "{откуда}", "caption_style": "subtitle", "caption_position": "top",
          "transition_out": "vr_mobius_zoom", "transition_params": {"zoom": 60}, "transition_seconds": 0.8, "sfx": "whoosh"},
         {"role": "there", "kind": "picture", "seconds": 2.2, "asset_hint": "мир Б", "camera": _cam(135, 100, "ease_out"),
          "effects": [{"id": "twirl", "params": {"angle": [-160, 0], "radius": 50}}], "caption": "{куда}", "caption_style": "cartoon", "caption_position": "bottom", "transition_out": "cut"}],
     "caption_pattern": "«Закрой глаза...» → «Ты в другой игре»",
     "music_hint": "chiptune", "why_it_works": "закрутка, которая раскручивается в следующем кадре, делает два кадра одним движением — как зум-переход, но вращением",
     "source_url": S["vidpros_trans"]},
    {"id": "tilted_cards", "name_ru": "Карточки в 3D", "moods": ["tech", "calm", "energetic"],
     "when_to_use": "витрина: несколько игр/скриншотов как карточки в пространстве",
     "structure": [
         {"role": "card", "kind": "picture", "seconds": 1.8, "asset_hint": "скриншот 1", "camera": _cam(100, 106, "linear"),
          "effects": [{"id": "rounded_crop", "params": {"radius": 70, "border": 10, "border_color": "#ffffff"}}, {"id": "rotate_3d", "params": {"rot_y": [-22, 10], "rot_x": 6}}],
          "caption": "{название 1}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "flip_motion", "transition_params": {"direction": "east"}, "transition_seconds": 0.5},
         {"role": "card", "kind": "picture", "seconds": 1.8, "asset_hint": "скриншот 2", "camera": _cam(100, 106, "linear"),
          "effects": [{"id": "rounded_crop", "params": {"radius": 70, "border": 10, "border_color": "#ffd23f"}}, {"id": "rotate_3d", "params": {"rot_y": [-22, 10], "rot_x": 6}}],
          "caption": "{название 2}", "caption_style": "subtitle", "caption_position": "bottom", "transition_out": "flip_motion", "transition_params": {"direction": "east"}, "transition_seconds": 0.5}],
     "caption_pattern": "название + одна характеристика: «Spore — эволюция за 5 минут»",
     "music_hint": "chiptune", "why_it_works": "кадр-в-кадре с рамкой и наклоном отделяет «витрину» от полноэкранных сцен и выглядит как интерфейс",
     "source_url": S["split_capcut"]},
    {"id": "glitch_reveal", "name_ru": "Глитч-раскрытие", "moods": ["tech", "dark", "energetic"],
     "when_to_use": "раскрыть название/картинку через «сломанный» сигнал",
     "structure": [
         {"role": "noise", "kind": "picture", "seconds": 1.8, "asset_hint": "главный кадр", "camera": _cam(120, 105, "ease_out"),
          "effects": [{"id": "mosaic", "params": {"horizontal": [80, 10]}}, {"id": "vr_digital_glitch", "params": {"amplitude": [70, 10]}}],
          "transition_out": "glitch", "transition_params": {"amount": 0.8}, "transition_seconds": 0.3, "sfx": "glitch"},
         {"role": "clean", "kind": "picture", "seconds": 2.0, "asset_hint": "тот же кадр", "same_as": 0, "camera": _cam(105, 130, "punch"),
          "caption": "{что это}", "caption_style": "glitch", "caption_position": "center", "transition_out": "cut"}],
     "caption_pattern": "«СИГНАЛ ВОССТАНОВЛЕН» / название игры",
     "music_hint": "dark_drone", "why_it_works": "пиксели собираются в картинку на глазах: зритель ждёт, пока «загрузится» — микро-петля любопытства",
     "source_url": S["open_loops"]},
    {"id": "abrupt_payoff_end", "name_ru": "Резкий финал", "moods": ["funny", "energetic", "story"],
     "when_to_use": "конец любого ролика: обрыв сразу после развязки, без «подписывайтесь»",
     "structure": [
         {"role": "payoff", "kind": "picture", "seconds": 2.0, "asset_hint": "развязка", "camera": _cam(100, 140, "punch"),
          "effects": [{"id": "rgb_split", "params": {"amount": [20, 3]}}], "caption": "{панчлайн}", "caption_style": "cartoon", "caption_position": "center", "transition_out": "cut", "sfx": "boom"},
         {"role": "button", "kind": "card", "seconds": 1.2, "card_style": "final", "text_anim": "scale_pop", "caption": "{название}", "subtitle": ""}],
     "caption_pattern": "панчлайн, который переворачивает начало; затем только название на 1 с",
     "music_hint": "none", "why_it_works": "Дженни Хойос обрывает ролик сразу после развязки: −1 секунда в конце подняла удержание с 83% до 88%; призыв подписаться ломает импульс",
     "source_url": S["hoyos"]},
]

HOOKS = [  # caption/copy patterns for the first 1-2 seconds; recipe = a recipe whose first step stages it
    {"pattern": "POV: {ситуация зрителя}", "recipe": "pov_hook", "why": "ставит зрителя в кадр, узнавание"},
    {"pattern": "Это не должно было работать.", "recipe": "scroll_stop_flash", "why": "противоречие, которое хочется разрешить"},
    {"pattern": "Угадай, {что/где} это", "recipe": "mystery_blur_reveal", "why": "загадка = открытая петля до ответа"},
    {"pattern": "ОШИБКА: {что сломалось}", "recipe": "error_screen_hook", "why": "прерывание шаблона, «сбой» в ленте"},
    {"pattern": "ТОП-3 {чего}. №1 вас удивит", "recipe": "countdown_top3", "why": "листикл: остаются ради последнего пункта"},
    {"pattern": "Да. Это я. Сейчас объясню.", "recipe": "freeze_callout", "why": "начать с конца истории, потом флешбэк"},
    {"pattern": "{А} VS {Б}", "recipe": "versus_card", "why": "встроенный вопрос «кто победит»"},
    {"pattern": "{год}. {место}.", "recipe": "vhs_memory", "why": "ностальгия + точная дата"},
    {"pattern": "Что будет, если {невозможное}?", "recipe": "text_first_hook", "why": "гипотетический вопрос, ответ через 2 с"},
    {"pattern": "Ты заметил?", "recipe": "detail_magnifier", "why": "обещание скрытой детали"},
    {"pattern": "ДО → ПОСЛЕ", "recipe": "before_after_wipe", "why": "контраст читается без звука"},
    {"pattern": "В мире, где {условие}...", "recipe": "movie_trailer", "why": "трейлерная интонация, серьёзность"},
    {"pattern": "{тезис}. {тезис}. {тезис}.", "recipe": "kinetic_manifesto", "why": "ритм трёх коротких слов"},
    {"pattern": "Обычный день на {месте}.", "recipe": "calm_then_chaos", "why": "обманутое ожидание: спокойствие перед ударом"},
]

BY_ID = {r["id"]: r for r in RECIPES}
STEP_KEYS = {"role", "kind", "seconds", "asset_hint", "caption", "subtitle", "caption_style", "caption_position", "camera", "effects", "grade", "look",
             "transition_out", "transition_params", "transition_seconds", "card_style", "text_anim", "speed", "same_as", "sfx", "animated"}


# ------------------------------------------------------------------ validation (scripts/check_ideas.py)
def validate():
    """[problems]: every step goes through the real rich EDL validator; any warning is a problem."""
    from . import vocab
    from .edl import EDL, MUSIC, SFX
    probs = []
    cat = {"still": {"kind": "still", "path": "x.png"}, "anim": {"kind": "animated", "path": "x.gif"}}
    edl = EDL(cat, mode="rich")
    ids = set()
    for r in RECIPES:
        rid = r.get("id")
        for k in ("id", "name_ru", "when_to_use", "structure", "caption_pattern", "music_hint", "why_it_works", "source_url", "moods"):
            if not r.get(k):
                probs.append(f"{rid}: missing {k}")
        if rid in ids:
            probs.append(f"{rid}: duplicate id")
        ids.add(rid)
        if r.get("music_hint") not in MUSIC:
            probs.append(f"{rid}: music_hint '{r.get('music_hint')}' not in edl.MUSIC")
        if r.get("source_url") not in S.values():
            probs.append(f"{rid}: source_url not in ideas.S")
        for m in r.get("moods", []):
            if m not in MOODS:
                probs.append(f"{rid}: unknown mood {m}")
        for i, st in enumerate(r.get("structure", [])):
            where = f"{rid}[{i}]"
            extra = set(st) - STEP_KEYS
            if extra:
                probs.append(f"{where}: unknown keys {sorted(extra)}")
            if "same_as" in st and not (0 <= st["same_as"] < i and r["structure"][st["same_as"]]["kind"] == "picture"):
                probs.append(f"{where}: same_as must point to an earlier picture step")
            if st.get("sfx") and st["sfx"] not in SFX:
                probs.append(f"{where}: sfx '{st['sfx']}' not in edl.SFX")
            if st.get("kind") == "card" and len((st.get("caption") or "").replace("{", "").replace("}", "")) > 40:
                probs.append(f"{where}: card title template longer than 40 chars")
            w = []
            shot = edl.make_shot(_raw(st, "anim" if st.get("animated") else "still"), "s", w)
            if shot is None or shot.kind != st.get("kind"):
                probs.append(f"{where}: did not build a {st.get('kind')} shot")
            probs += [f"{where}: {x}" for x in w]
            if st.get("transition_out") and st["transition_out"] != "cut" and st["transition_out"] not in vocab.RICH_TRANSITIONS:
                probs.append(f"{where}: transition {st['transition_out']} not in vocab")
            if st.get("kind") == "card" and st.get("transition_seconds", 0.5) > st["seconds"] / 2:
                probs.append(f"{where}: transition longer than half the card")
            if st.get("kind") == "picture" and st.get("transition_seconds", 0.5) > st["seconds"] * 0.6 and st.get("transition_out", "cut") != "cut":
                probs.append(f"{where}: transition too long for the shot")
    for h in HOOKS:
        if h["recipe"] not in BY_ID:
            probs.append(f"hook '{h['pattern']}': unknown recipe {h['recipe']}")
    return probs


def _raw(step, asset, caption=None):
    """Recipe step -> raw shot dict for EDL.make_shot (templates kept unless `caption` is given)."""
    raw = {k: v for k, v in step.items() if k not in ("role", "asset_hint", "same_as", "sfx", "animated", "caption", "subtitle")}
    text = step.get("caption", "") if caption is None else caption
    if step.get("kind") == "card":
        raw.update(card_title=text, card_subtitle=step.get("subtitle", ""), asset="")
    else:
        raw["asset"] = asset
        if text:
            raw["caption"] = text
    return raw


def to_shots(recipe, assets, captions=None):
    """Expand a recipe into (raw shots, sfx) for EDL.make_shot.

    assets: picture ids, consumed in order by the picture steps that have no `same_as` (cycled if too few).
    captions: optional list aligned with the steps (None = keep the template). Returns (shots, sfx) where sfx is
    [{"kind", "offset"}] with offset = index of the shot inside the returned list (add your own base, 1-based)."""
    r = BY_ID[recipe] if isinstance(recipe, str) else recipe
    shots, sfx, picked, k = [], [], {}, 0
    for i, st in enumerate(r["structure"]):
        asset = ""
        if st["kind"] == "picture":
            if "same_as" in st:
                asset = picked[st["same_as"]]
            else:
                asset = assets[k % len(assets)]
                k += 1
            picked[i] = asset
        cap = captions[i] if captions and i < len(captions) else None
        shots.append(_raw(st, asset, cap))
        if st.get("sfx"):
            sfx.append({"kind": st["sfx"], "offset": i})
    return shots, sfx


# ------------------------------------------------------------------ prompt text for the model
_SHORT = {"picture": "кадр", "card": "карточка"}


def _step_line(st):
    bits = [f"{_SHORT[st['kind']]} {st['seconds']:g}с"]
    if st.get("same_as") is not None:
        bits.append(f"та же картинка, что №{st['same_as'] + 1}")
    if st.get("camera"):
        c = st["camera"]
        bits.append(f"камера {c['start_scale']:g}→{c['end_scale']:g} {c['easing']}")
    for fx in st.get("effects", []):
        bits.append(fx["id"] if isinstance(fx, dict) else fx)
    if st.get("grade"):
        g = st["grade"]
        bits.append("цвет " + ",".join(f"{k}={v}" for k, v in list(g.items())[:2]))
    if st.get("look"):
        bits.append(f"look {st['look']}")
    if st.get("text_anim"):
        bits.append(f"{st.get('card_style', '')}/{st['text_anim']}")
    out = " ".join(bits)
    if st.get("transition_out", "cut") != "cut":
        out += f" →{st['transition_out']}"
    return out


def recipe_line(r, with_structure=True):
    line = f"• {r['name_ru']} [{r['id']}] — {r['when_to_use']}. Подпись: {r['caption_pattern']}."
    if with_structure:
        line += "\n  " + " | ".join(_step_line(st) for st in r["structure"]) + f" (музыка {r['music_hint']})"
    return line


def ideas_prompt(n=12, seed=None, mood=None, with_structure=True):
    """Compact Russian inspiration block: n recipes (shuffled by seed; mood = tag or list of tags filters first).
    Meant as optional inspiration inside the plan/build prompt, not as a rule."""
    rng = random.Random(seed)
    pool = list(RECIPES)
    if mood:
        moods = {mood} if isinstance(mood, str) else set(mood)
        first = [r for r in pool if moods & set(r["moods"])]
        rest = [r for r in pool if r not in first]
        rng.shuffle(first)
        rng.shuffle(rest)
        pool = first + rest
    else:
        rng.shuffle(pool)
    picked = pool[:max(1, n)]
    head = ("ИДЕИ ДЛЯ МОНТАЖА (необязательно; бери приём целиком или его часть, меняй картинки и тексты под задачу; "
            "«та же картинка» = повтори asset; цифры у камеры — масштаб %):")
    return "\n".join([head] + [recipe_line(r, with_structure) for r in picked])


def hook_ideas(n=None, seed=None):
    """Russian text block with hook formulas for the first 1-2 seconds, each with the recipe that stages it."""
    hooks = list(HOOKS)
    if seed is not None:
        random.Random(seed).shuffle(hooks)
    hooks = hooks[:n] if n else hooks
    lines = ["КРЮЧОК (первые 1-2 с: самое сильное сразу, суть до 3-й секунды, текст читается без звука, 5-10 слов в секунду максимум):"]
    for h in hooks:
        st = BY_ID[h["recipe"]]["structure"][0]
        lines.append(f"• «{h['pattern']}» — {h['why']}; как снять: {_step_line(st)} [{h['recipe']}]")
    return "\n".join(lines)


def moods():
    return {m: [r["id"] for r in RECIPES if m in r["moods"]] for m in MOODS}
