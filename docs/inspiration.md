# Вдохновение: что делает вертикальный ролик неожиданным (2025–2026)

Короткий конспект исследования для `assemblee/ideas.py`. Задача: дать маленькой модели готовые, **собираемые нашим словарём**
приёмы, чтобы монтаж удивлял, а не повторял «zoom_in + cross_dissolve». Все рецепты проверяются против `vocab.py`
скриптом `scripts/check_ideas.py`.

**Про источники честно.** Независимых исследований удержания для Shorts/Reels почти нет. Большинство цифр в интернете
взяты из блогов, которые цитируют друг друга (например, «65 % досмотревших 3 секунды смотрят 10» якобы от Meta: первоисточник не найден).
Ниже я опираюсь на официальные рекомендации платформ (TikTok), на данные самих авторов (Дженни Хойос, Падди Гэллоуэй), на теорию
кино (Кулешов, Каттинг) и на психологию (правило «пик-конец»). Цифры из маркетинговых блогов помечены как непроверенные.

## 1. Крючок: первые 1–2 секунды

- **TikTok (официально):** крючок в первых 6 секундах, суть («content proposition») в первых 3 секундах, текст на экране
  5–10 слов в секунду, вертикаль 9:16, звук обязателен, «не слишком отполированная», UGC-эстетика лучше рекламной.
  [TikTok Ads: Creative best practices](https://ads.tiktok.com/help/article/creative-best-practices?lang=en),
  [TikTok Creative Codes (PDF)](https://ads.tiktok.com/business/library/Creative_Codes_ENG.pdf).
- **Четыре типа крючка:** звуковой, визуальный, **текстовый** (самый недооценённый), листикл («зритель остаётся ради третьего пункта»).
  Не просить лайков и не заканчивать «смотрите полное видео»: призыв ломает импульс истории.
  [Social Media Examiner: YouTube Shorts Hooks and Curiosity Loops](https://www.socialmediaexaminer.com/youtube-shorts-hooks-and-curiosity-loops-that-explode-your-views/).
- **Дженни Хойос** (Shorts с удержанием около 95 %): крючок должен работать как заголовок и превью длинного ролика, быть **понятным без звука**,
  простыми словами (уровень 5-го класса). Структура: крючок → предвосхищение (≤ 3 с) → переход → развязка; сюжет цепочкой «но / поэтому».
  [Creator Science podcast: Jenny Hoyos](https://creatorscience.com/podcast/jenny-hoyos/).
- **Формулы крючков** (POV, «что будет, если…», противоречие): списки формул у [OpusClip](https://www.opus.pro/blog/youtube-shorts-hook-formulas);
  механика открытых петель (вопрос, который нельзя не дослушать, обязательный «платёж»): [Socialync: open loops](https://www.socialync.io/blog/open-loops-in-content-2026).
- Данные о «решении за 1,3 с» (якобы Meta 2025) и порогах удержания 3 секунд: [Green Frog Labs](https://greenfroglabs.com/blog/anatomy-of-viral-hook),
  [Mean CEO: hook statistics](https://blog.mean.ceo/video-hook-retention-statistics/). **Не проверено**, использовать как направление, не как факт.

**Вывод для модели:** самый сильный кадр или текст сразу, без логотипа и вступления; вопрос или противоречие в подписи;
визуальный «удар» (punch камеры, flash, glitch), чтобы остановить палец. См. `hook_ideas()`.

## 2. Темп и кривая ритма

- **Средняя длина кадра в кино** упала с ~12 с (1930) до ~2,5 с; Джеймс Каттинг: «каждая склейка заставляет перераспределить внимание».
  [Flick Filosopher о работе Каттинга](https://www.flickfilosopher.com/2014/02/people-complain-fast-edits-modern-films-need-know.html).
- **Прерывание шаблона** (смена кадра/зум/текст каждые 2–3 с; разнообразить типы прерываний, иначе утомляет):
  [CapCut: pattern interrupt technique](https://www.capcut.com/create/pattern-interrupt-technique-short-form-video).
  Цифры «82 % удержания при смене каждые 2–3 с» из анализа 5000 роликов (FluxNote): **не проверено**.
- **Контраст ритма важнее постоянной скорости:** быстрая серия → длинная пауза на красивом кадре, «тишина перед бурей».
- **Длина:** анализ Падди Гэллоуэя (≈5400 Shorts, 3,3 млрд просмотров): лучшие ролики 50–60 с, решает процент досмотра;
  Shorts работают как «интро» (сжатая история целого видео). [Тред Гэллоуэя](https://threadreaderapp.com/thread/1646898356419981315.html).
  Хойос: средний ролик ~34 с; обрезка **одной** секунды в конце подняла удержание с 83 % до 88 %.
- **Рейтинги/листиклы:** каждый следующий пункт сильнее предыдущего, плоский список теряет зрителей.
  [GoFaceless: Shorts retention strategy](https://www.gofaceless.ai/en/blog/youtube-shorts-retention-strategy).

**Кривая для 30–60 с:** удар (0–2 с) → контекст (2–5 с) → нарастание с прерываниями каждые 1–3 с → пауза/смена ритма в середине →
пик (самый сильный кадр, свет, бум) → резкий финал или петля.

## 3. Приёмы монтажа

| Приём | Как у нас | Источник |
|---|---|---|
| Вжух-пан (whip) | `whip` + камера едет в ту же сторону, звук whoosh | [VidPros: transitions](https://vidpros.com/best-transitions-for-short-form-videos/) |
| Сдержанность | склейки — основа, эффектные переходы только на крючке и раскрытии | [FrameNotion](https://framenotion.com/blog/best-transitions-for-short-form-video-ads) |
| Зум сквозь кадр | камера ease_in до 170 % → `cross_zoom`/`zoom_blur` → следующий кадр с 170 % вниз | [Videobolt: super zoom](https://blog.videobolt.net/post/how-to-create-super-zoom-effect-in-premiere-pro) |
| Спид-рамп | на картинках: медленно (linear) → тот же кадр с `punch` + тряска; на анимированных — `speed` | [StudioBinder: speed ramp](https://www.studiobinder.com/blog/how-to-speed-ramp-in-premiere/) |
| Флеш на бит | кадры 0,6–0,8 с, `flash` 0,2 с, punch | [BeatSync: flash frames](https://beatsyncpro.ai/blog/trap-music-video-editing-guide-2026.html) |
| Стоп-кадр «Да, это я» | тот же кадр: ч/б + `magnify` + подпись system + звук glitch, затем флешбэк | [Kapwing](https://www.kapwing.com/resources/how-to-do-the-record-scratch-yep-thats-me-meme/), [Know Your Meme](https://knowyourmeme.com/memes/record-scratch-freeze-frame) |
| До / После | один кадр дважды: ч/б + шум → `linear_wipe` → насыщенный; «до» 1–2 с, «после» 2–4 с | [Insense: before/after](https://insense.pro/blog/how-to-make-before-and-after-video) |
| Сравнение / сплит | `split`/`barn_doors` + карточка «VS»; холодная и тёплая стороны | [CapCut: split screen](https://www.capcut.com/create/split-screen-effects-multi-frame-videos) |
| Эффект Кулешова | нейтральный кадр героя → угроза → тот же кадр: смысл меняется | [StudioBinder: Kuleshov](https://www.studiobinder.com/blog/kuleshov-effect/) |
| Петля | последний кадр = первый, камера финала приходит туда, откуда стартует начало; фраза разрезана | [CapCut: seamless loops](https://www.capcut.com/create/seamless-loop-videos-continuity-techniques), [The Social Cat](https://thesocialcat.com/glossary/video-loop-short-form-content) |
| Глитч-раскрытие | `mosaic` [80→10] + `vr_digital_glitch` [70→10] → `glitch` → чистый кадр | прерывание шаблона + петля любопытства |
| Тайна | `gaussian_blur` [60→8] + сильная виньетка, «Угадай…», ответ через `iris_round` | [Socialync](https://www.socialync.io/blog/open-loops-in-content-2026) |

## 4. Кинетическая типографика и подписи

- Скорость и интерполяция анимации текста значимо влияют на понимание и запоминание
  ([симпозиум GRID 2024, RIT Croatia / Загреб](https://www.grid.uns.ac.rs/symposium/download/2024/89.pdf)). Отсюда: короткие тезисы,
  разные `text_anim` для разных тезисов (`tracking_in`, `slide_up`, `blur_in`), не дольше 1,4–1,8 с на тезис.
- Пословные подписи: исследований, что они повышают удержание, **не найдено**; цифры «+25–40 %» без источника. Используем как стиль.
- **Шаблоны подписей, которые работают:** POV; противоречие («Это не должно было работать»); точная дата («2011. Сервер был полон»);
  вопрос + ответ через 2 с; разрезанная фраза для петли; один «удар»-слово капсом («БАМ.»); «ДО / ПОСЛЕ»; «Ты заметил?».
- Читаемость: TikTok — не больше 5–10 слов в секунду; Хойос — простые слова, без жаргона.

## 5. Эстетики и цвет

- **VHS / CRT / ретро:** шум, разъезд каналов, кривизна кинескопа, выключение ТВ в полоску, неоновые контуры. Эстетика выделяется на фоне
  «полированной» ленты и воспринимается как настоящий артефакт.
  [MotionElements: retro aesthetics](https://www.motionelements.com/blog/articles/bringing-the-past-into-the-present-how-retro-aesthetics-are-shaping-video-production-today),
  [Artlist: authentic content](https://artlist.io/blog/authentic-content/). (Цифры роста вовлечённости от AI-блогов — не проверено.)
- **Цвет 2025:** выразительный, «сюжетный» грейдинг, смелые оттенки и стилизованные LUT, рядом — десатурация и плёночные эмуляции.
  [Pixflow: editing trends 2025](https://pixflow.net/blog/top-video-editing-trends-2025/).
- **Цветовые истории:** холод → тепло (одиночество → друзья), один цвет на сером (`color_pass`: лава, опасность), дуотон-поп-арт
  (`tint` + `posterize` + `clone`), трейлер (Teal & Orange + летербокс `crop`), сон (`dreamy`, `bokeh_blur`, `blur_dissolve`).

## 6. Финал

- **Правило «пик-конец»** (Канеман): впечатление определяют самый сильный момент и конец; последние 3 секунды должны быть пиком, а не затуханием.
  [Billion Dollar Boy: final three seconds](https://www.billiondollarboy.com/news/brands-need-to-rethink-the-final-three-seconds-of-social-content).
- Обрыв сразу после развязки (Хойос) или петля в начало. Не «подписывайтесь» (Social Media Examiner).

## Как это использует агент

```python
from assemblee import ideas
ideas.ideas_prompt(n=12, seed=run_seed, mood=["dark", "retro"])  # 12 рецептов по 2 строки, сначала подходящие по настроению
ideas.hook_ideas(n=6, seed=run_seed)                             # формулы первых 2 секунд
shots, sfx = ideas.to_shots("loop_ending", ["spider/01-mother", "spider/04-lava-1"])  # сырые кадры для EDL.make_shot
```

Блок вставляется в промпт plan/build (rich-режим) как **необязательное** вдохновение; `seed` меняется от запуска к запуску, чтобы модель
видела разные рецепты и монтаж не повторялся. Проверка: `python3 scripts/check_ideas.py`; визуальная проверка:
`python3 scripts/demo_ideas.py [recipe_id ...]` (контактные листы и mp4 в `/tmp/assemblee_ideas`).

## Дополнительные источники (просмотрены, мало конкретики)

- [Learnvivo: How to edit viral short-form videos 2025](https://learnvivomedia.com/edit-viral-short-form-videos-2025/)
- [ShortGenius: transitions 2026](https://shortgenius.com/blog/transitions-for-videos)
- [OpusClip: ideal Shorts length](https://www.opus.pro/blog/ideal-youtube-shorts-length-format-retention)
- [vidIQ: Shorts algorithm 2026](https://vidiq.com/blog/post/youtube-shorts-algorithm/)
- [Kapwing: speed ramp](https://kapwing.com/resources/how-to-use-the-speed-ramp-effect)
