# Исследование: агентный монтаж видео маленькой локальной LLM

Дата: 2026-11-13. Контекст: Qwen3.5-4B Q4 GGUF + mmproj через `llama-server`, RTX 3050 6 GB, 14 GB RAM; движки FilmCraft (NLE, MCP) и EffectCraft (MCP), тонкий Python-слой из ~14 высокоуровневых инструментов.

Пометки: **[не проверено]** — утверждение взято из вторичного источника или из памяти и не сверено с первоисточником. Номера в квадратных скобках вида [S1] ссылаются на список источников в конце.

---

## 1. Опубликованные подходы к LLM-монтажу

### 1.1 Обзор систем

| Система | Тип | Что видит модель | Как планирует | Как проверяет |
|---|---|---|---|---|
| **LAVE** (U Toronto + Meta, IUI 2024) [S1][S2] | исследовательский прототип, GPT-4 с function calling | текстовые описания клипов (авто-captions от VLM), тайм­лайн как упорядоченный список клипов | plan-and-execute агент: сначала план действий, затем исполнение; 5 функций: Footage Overview, Idea Brainstorming, Video Retrieval, **Storyboarding**, Clip Trimming. Storyboard: если сюжета нет — LLM генерирует его по клипам и *переупорядочивает* их, выдавая посценовое описание | человек правит вручную (direct manipulation); автоматической визуальной проверки нет |
| **ExpressEdit** (KAIST/Yale, IUI 2024) [S3] | прототип | текст команды + скетч на кадре; LLM разбирает временные/пространственные/операционные ссылки | парсинг команды в структуру «когда / где / что сделать» | итерации пользователя |
| **Prompt-Driven Agentic Video Editing** (arXiv 2509.16811, 2025) [S4] | исследовательская система для многочасового видео | персистентный семантический индекс: временная сегментация + сжатие памяти + слияние разных гранулярностей | промежуточные артефакты: **storyboard и сценарий** до сборки | экспертные оценки, QA; авторы заявляют превосходство над Gemini 2.5 Pro baseline |
| **VideoAgent (HKUDS)** (arXiv 2606.23327, MIT) [S5][S6] | open-source мультиагентный фреймворк | intent → набор агентов; Storyboard Agent переводит запрос в визуальные запросы к поиску футажа | граф из 30+ специализированных агентов, оптимизация пайплайна «текстовыми градиентами» | авторы: 87–95 % успешной оркестрации на собственном бенчмарке **[не проверено независимо]**; требует GPT/Gemini API |
| **video-use** (browser-use, MIT, 2026) [S7] | skill для Claude Code/Codex | **транскрипт со словными таймкодами**, упакованный в `takes_packed.md` (~12 KB: на каждый дубль — заголовок с длительностью, строки «диапазон времени, спикер, текст»); по запросу — PNG `timeline_view` (филмстрип + волна + слова) | LLM читает транскрипт → пишет `edl.json` → `render.py` на ffmpeg | **self-eval**: `timeline_view` на каждой склейке готового рендера (скачки, щелчки, перекрытые субтитры), до 3 итераций исправления; 30 мс аудиофейды на склейках |
| **Timeline-Bench** (arXiv 2609.35143, 2026) [S8] | бенчмарк, 56 реальных задач «сырой материал + бриф → готовое видео» | агенты работают кодом (ffmpeg, Python, Remotion, HyperFrames) или GUI DaVinci | — | см. выводы ниже |
| **MoneyPrinterTurbo** (MIT) [S9] | генератор shorts по теме | — | цепочка: сценарий → ключевые слова → сток-футаж → TTS → субтитры → музыка → рендер | нет |
| **FFMPerative-7B** (Llama-2-7B, fine-tune) [S10] | маленькая модель под ffmpeg-инструменты | — | обучена на 500 примерах композиции инструментов | автор предупреждает: проверять выход |

Descript-подобный text-based editing (монтаж правкой транскрипта) — та же идея, что в video-use: **поверхность редактирования = текст со словными таймкодами**, вырезание слова = вырезание интервала. Для разговорного видео это самый надёжный представитель для LLM.

### 1.2 Представления таймлайна для модели

1. **Транскрипт со словными таймкодами** (video-use, Descript). Модель оперирует фразами/ID, а не секундами; секунды подставляет инструмент. Лучший вариант для talking-head, интервью, подкастов.
2. **EDL / JSON-список событий** (`edl.json` в video-use, Editly JSON). Плоский список `[{source, in, out, track, ...}]`. Хорошо читается моделью, но абсолютные таймкоды — источник арифметических ошибок.
3. **OpenTimelineIO** (Apache-2.0, 0.18.1 от 2025-11-09) [S11]: Timeline → Stack → Tracks → Clip/Gap/Transition, нативный формат `.otio` — JSON. Это *формат обмена и хранения*, не формат для генерации моделью: схема многословна (RationalTime, rate, metadata). Автор поста на Medium прямо советует не давать агенту генерировать проектные файлы с нуля — пять минут видео это тысячи строк перекрёстных ID и таймкодов; лучше декларативный компилятор [S12].
4. **Код как таймлайн** (Remotion, HyperFrames, Motion Canvas). Работает для больших моделей (в Timeline-Bench агенты пишут код) — для 4B непригодно.
5. **Высокоуровневые «намерения» через инструменты** (наш текущий путь, LAVE): модель выбирает функцию и enum-параметры, состояние таймлайна держит harness.

Вывод для нас: модель должна выдавать **короткий структурированный shot list секции** (ссылки на ассеты по ID, относительные длительности/«доли», enum-стили), а компилятор в Python переводит его в абсолютные таймкоды и команды FilmCraft. OTIO — опционально как экспорт/снапшот для отладки и обмена с Kdenlive/Resolve.

### 1.3 Как планируют

Общий паттерн во всех системах: **сначала storyboard/сценарий (глобально, один раз), потом шоты по секциям, потом исполнение** (LAVE storyboarding, 2509.16811 storyboard+script как промежуточные артефакты, VideoAgent Storyboard Agent, MoneyPrinterTurbo script→keywords). Это совпадает с нашим опытом «per-section plan calls работают».

### 1.4 Как проверяют, и что говорит Timeline-Bench [S8]

- Лучший результат — 26,8 % решённых задач (frontier-модель + курированные инструкции); в среднем 14 %. Computer-use в GUI — 3,6 %: GUI-управление сильно хуже кода/API.
- Агенты тратят 54 % действий на восприятие материала (кадры + транскрипт), 17 % на проверку рендера, только 9 % на сборку; рендерят поздно (72–90 % хода выполнения).
- **Самооценка ненадёжна**: агенты заявляют успех в 93 % прогонов, включая 95,5 % провальных. Проверки рендера ловят технические дефекты, но не темп, сюжет и выбор шотов.
- Технические требования и явные пункты брифа выполняются почти всегда (857/863 по спецификации); проваливают «вкус»: ритм, выбор планов, графику, переходы. Агенты режут в 0,72× темпа референса (держат планы слишком долго).
- Computer-use агенты оставляют хлопушки/дубли и пропускают 41,5 % обязательных реплик, потому что не слышат звук → **транскрипт обязателен**.
- Курированные «редакторские советы» в промпте значимого прироста не дали (15 vs 12).

### 1.5 Что работает именно с маленькими моделями

Прямых работ «агентный видеомонтаж на 4B» не найдено **[пробел в литературе]**. Косвенные данные:
- **α-UMi** «Small LLMs Are Weak Tool Learners» (EMNLP 2024) [S13]: разделение на planner / caller / summarizer (отдельные копии маленькой модели) лучше, чем одна маленькая модель на всё.
- **TinyAgent** (BAIR, EMNLP 2024 demo) [S14]: fine-tune 7B на tool-calling поднял успех с 41,25 % до 83,09 %; плюс Tool RAG — подавать модели только релевантные инструменты.
- FFMPerative-7B: узкий fine-tune на 500 примерах композиции инструментов даёт рабочую модель для ffmpeg-задач [S10].
- Практические отчёты: необученные 7B часто «спрашивают пользователя» вместо вызова инструмента [S15].

Следствия для harness: (а) таймлайн, порядок и арифметику держит код; (б) модель решает только локальные дискретные выборы (какой ассет, какой стиль из enum, какой текст); (в) проверка — сначала программная (длительности, дыры, громкость, покрытие брифа), визуальная VLM — только узкие yes/no вопросы; (г) темп задавать правилами в компиляторе (макс. длина плана по жанру), т.к. даже frontier-модели «тянут» планы.

---

## 2. Open-source инструменты для интеграции

Принцип отбора: всё, что даёт **числа** (таймкоды, биты, громкость, сцены) — в инструменты, модель видит только результат в виде ID/enum/коротких списков.

### 2.1 Рендер, монтаж, форматы

| Инструмент | Лицензия | Что даёт нам | Заметки |
|---|---|---|---|
| **ffmpeg** | LGPL-2.1+ (GPL при сборке с `--enable-gpl`, напр. libx264, vidstab) | `loudnorm` (EBU R128, двухпроходный — целевые -14 LUFS для соцсетей), `ebur128`, `silencedetect`, `scdet`/`select='gt(scene,0.3)'`, `xfade`/`acrossfade`, `sidechaincompress` (ducking музыки под голос), `drawtext`, `subtitles`/`ass` (libass, кириллица), `lut3d`, `zoompan` (Ken Burns), `vidstabdetect/transform`, **`tile`** (контакт-лист из N кадров в одну картинку) | `tile` — ключ к дешёвой vision-проверке: 1 изображение 3×3 вместо 9 вызовов VLM |
| **MoviePy** 2.2.1 (2025-05-21) [S16] | MIT | Python-композиция клипов | медленный (покадрово через numpy); для нас — только прототипы, не продакшн |
| **MLT / melt** (бэкенд Kdenlive и Shotcut) | LGPL-2.1 (часть модулей GPL) **[версия не проверена]** | XML-проект `.mlt` → рендер CLI `melt` | запасной движок/экспорт для ручной доводки в Kdenlive/Shotcut |
| **OpenTimelineIO** 0.18.1 [S11] | Apache-2.0 | канонический JSON таймлайна, адаптеры (CMX3600 EDL, FCP XML и др. — с 0.16 вынесены в отдельные пакеты-плагины **[не проверено]**) | хранить снапшот плана как `.otio` для отладки и обмена с Resolve/Kdenlive |
| **auto-editor** [S17] | Unlicense (public domain) | вырезание тишины/статики, экспорт в Premiere/Resolve/FCP XML, Shotcut | готовый «jump-cut» для talking-head; версия 26.x–27.x **[точная не проверена]** |
| **PySceneDetect** 0.6.x | BSD-3 | `ContentDetector`/`AdaptiveDetector`, список сцен CSV, нарезка | первичная разметка исходников на шоты; нейросетевая альтернатива TransNetV2 (MIT **[не проверено]**) |

### 2.2 Речь, субтитры, ритм

| Инструмент | Лицензия | Что даёт | Русский |
|---|---|---|---|
| **faster-whisper** (CTranslate2) | MIT | `word_timestamps=True`, встроенный Silero VAD; large-v3-turbo в int8 | Whisper хорош на русском; turbo чуть хуже large-v3 (вендорские цифры 5,1 % vs 4,2 % WER **[не проверено]**); есть русские fine-tune turbo (заявлено 9,43 % vs 13,25 % WER у базового, Habr) [S18] |
| **whisper.cpp** 1.8.x (1.8.3 — янв. 2026) [S19] | MIT | CUDA/Vulkan, вывод SRT/VTT/JSON, пословные метки (`-ml 1`, `-owts`) | то же; удобно как отдельный процесс без Python/torch |
| **WhisperX** | BSD-2 **[не проверено]** | forced alignment через wav2vec2 — точнее пословные таймкоды для караоке-субтитров | есть русские wav2vec2-модели |
| **Silero VAD** | MIT | детекция речи, паузы | языконезависим |
| **Beat This!** (CPJKU, 2024) [S20] | MIT (код и веса) | биты и **даунбиты** без DBN-постобработки, SOTA-уровень (F1 94,5 Beatles / 97,5 Ballroom) | — |
| **librosa** | ISC | `beat_track`, onset, RMS-энергия (для «где кульминация трека») | — |
| **madmom** | BSD (код), модели CC BY-NC-SA; DBN, по вторичному источнику, запатентован **[не проверено]** | классический DBN-трекер | не брать для коммерческого |
| **aubio** | GPL-3 | быстрые onset/tempo | лицензионно хуже Beat This!/librosa |
| **demucs** | MIT | разделение голос/музыка (чистка речи, ремикс) | — |
| **pyloudnorm** | MIT | измерение LUFS в Python | — |

Рекомендация: `faster-whisper large-v3-turbo` (или русский fine-tune) → слова с таймкодами → инструмент `captions` сам режет на чанки по 2–4 слова; `Beat This!` → сетка битов → компилятор шотов привязывает склейки к ближайшему биту/даунбиту.

### 2.3 Шаблоны и motion graphics

| Инструмент | Лицензия | Комментарий |
|---|---|---|
| **Remotion** 4.x [S21] | source-available, бесплатно для физлиц и компаний ≤3 человек, иначе платная Company License | мощный, React; для нас — только как внешний генератор оверлеев (WebM/ProRes с альфой) |
| **Motion Canvas** | MIT | TypeScript-анимации; хорошо для инфографики |
| **Revideo** | MIT **[статус поддержки 2026 не проверен]** | форк Motion Canvas с headless-рендером через API |
| **Editly** | MIT | JSON → видео на ffmpeg; малоактивен с 2025 |
| **HyperFrames** (HeyGen) | Apache-2.0 **[по вторичному источнику]** | HTML → видео, используется агентами в Timeline-Bench и video-use |
| **Lottie** (rlottie / python-lottie / LottieFiles) | rlottie — MIT-подобная **[не проверено]**; python-lottie — AGPL-3 **[не проверено]**; анимации LottieFiles — по их Lottie Simple License **[не проверено]** | рендер `.json` → PNG-секвенция/WebM с альфой → оверлей в FilmCraft |

Вывод: раз есть EffectCraft, шаблоны (lower thirds, title cards, счётчики) лучше делать **параметризованными пресетами EffectCraft**, где модель выбирает `template_id` из enum и подставляет только текст. Внешние JS-движки — лишняя зависимость (Node + Chromium ≈ ОЗУ, которой мало).

### 2.4 Медиа-источники с лицензиями

| Источник | Лицензия контента | API | Риски |
|---|---|---|---|
| **Freesound** (SFX) | per-sound: CC0 / CC BY / CC BY-NC | APIv2, токен; фильтр `license:"Creative Commons 0"` | хранить автора и лицензию в манифесте; NC не брать |
| **Free Music Archive** | per-track CC (BY, BY-SA, BY-NC, ND…) | публичного API сейчас нет **[не проверено]** | фильтровать CC BY / CC0 |
| **Pixabay** (музыка, SFX, фото, видео) | Pixabay Content License (без атрибуции, коммерция ок) | API для фото/видео; музыка через API **[не проверено]** | YouTube Content ID claims возможны даже при законном использовании; сертификат лицензии — для оспаривания [S22] |
| **Incompetech (Kevin MacLeod)** | CC BY 4.0 | нет | нужна атрибуция |
| **Openverse** | CC/PD-агрегатор | `GET https://api.openverse.org/v1/images/?q=..&license_type=commercial,modification`, поле `attribution`; анонимно — лимиты, с токеном выше [S23] | точные лимиты **[не проверены]** |
| **Wikimedia Commons** | CC BY-SA / PD и др. | MediaWiki API: `action=query&prop=imageinfo&iiprop=url|extmetadata` → `LicenseShortName`, `Artist` | BY-SA требует атрибуции и share-alike |
| **Pexels / Pixabay видео** | собственные лицензии, бесплатно | API с ключом | — |

Обязательно: инструмент `fetch_asset` пишет `credits.json` (источник, автор, лицензия, URL) — финальные титры/описание генерируются из него кодом.

### 2.5 Обработка изображений и голос

| Инструмент | Лицензия | Что даёт | Заметки |
|---|---|---|---|
| **rembg** | MIT (библиотека); модели: u2net/isnet **[не проверено]**, BiRefNet MIT **[не проверено]**, **BRIA RMBG 1.4/2.0 — CC BY-NC** [S24] | вырезание фона для стикеров/«выноса» объекта | для видео покадрово медленно; брать `isnet-general-use` или `birefnet-general-lite` |
| **Real-ESRGAN** / `realesrgan-ncnn-vulkan` | BSD-3 / MIT | 2–4× апскейл картинок и кадров (`realesr-animevideov3` — быстрая для видео) | на 3050 работает через Vulkan; запускать, когда LLM выгружена или на малых разрешениях |
| **Piper** (OHF-Voice/piper1-gpl) [S25] | **GPL-3.0** (старый rhasspy/piper был MIT, архивирован в окт. 2025); голоса — каждая своя лицензия | быстрый CPU-TTS; русские голоса `ru_RU` (denis, dmitri, irina, ruslan **[список не проверен]**) | GPL — запускать как отдельный процесс (CLI/HTTP), не линковать |
| **Silero TTS** v4/v5 ru [S26] | CC BY-NC(-SA) 4.0 — **некоммерческое** | лучшее качество русского среди лёгких моделей, SSML, ударения | ок для учебного/личного проекта; для коммерции — договор с Silero |
| **Coqui XTTS v2** | CPML — некоммерческое | клонирование голоса, есть русский | тяжёлый (GPU), конфликт VRAM с LLM |
| **Qwen3-TTS**, **Kokoro** | Apache-2.0 | поддержка русского **[не проверено]** | проверить перед выбором |
| **RHVoice** | LGPL/GPL **[не проверено]** | классический русский синтез, очень быстрый | запасной вариант |

Для озвучки на русском: Silero (качество, NC) или Piper (свобода лицензии, GPL-процесс). Длительность фразы TTS измеряет инструмент и сам растягивает/подгоняет шоты — модель не считает секунды.

---

## 3. Как выжать максимум из маленькой локальной модели

### 3.1 Особенности Qwen3.5 small (важно для llama.cpp)

- Архитектура **гибридная**: по стороннему зеркалу карточки 4B — 32 слоя, `8 × (3 × Gated DeltaNet → FFN, 1 × Gated Attention → FFN)` [S27] **[сверить с Qwen/Qwen3.5-4B]**. Следствия: (а) KV-кэш есть только у ~1/4 слоёв → длинный контекст дешёв по VRAM, можно держать 2–4 слота; (б) рекуррентное состояние нельзя «откатить» на произвольную позицию → переиспользование префикса кэша работает через **context checkpoints** (`--ctx-checkpoints`, по умолчанию 32 на слот, `--checkpoint-min-step` 8192) [S28]. Держите неизменный префикс (system + описания инструментов) и **append-only** историю: любая правка середины промпта = полный пересчёт.
- Small-модели (0.8B–9B) по умолчанию идут **без thinking**; включение — `--chat-template-kwargs '{"enable_thinking":true}'`, но флаг работает, только если шаблон читает переменную [S29][S30]. Новые флаги сервера: `--reasoning on|off|auto`, `--reasoning-budget N` (0 — сразу закрыть мысли), `--reasoning-budget-message` [S28].
- Известные баги: Qwen3.5-9B с thinking пишет tool calls **внутри** `<think>` или XML-текстом и останавливается [S31]; парсинг tool calls ломался и с выключенным thinking (build 8576) [S32]. Формат вызова Qwen3.5 — XML-подобный `qwen3_coder` (`<tool_call><function=..><parameter=..>`), его парсит llama.cpp при `--jinja`.
- Сэмплинг thinking-режима по карточке: `temperature 1.0, top_p 0.95, top_k 20, min_p 0, presence_penalty 1.5` [S27]. Для исполнителя-tool-caller практика — temperature 0.2–0.6 **[эмпирика, не из карточки]**.
- Не квантовать KV агрессивно (`-ctk q4_0`) — документация llama.cpp прямо предупреждает о деградации tool calling [S33].

### 3.2 Ограниченный вывод: native tools или json_schema

- Нативные tools (`--jinja`, OpenAI-совместимый `tools`) — удобно, но для Qwen3.5 в llama.cpp хрупко (см. баги выше). `parallel_tool_calls` выключен по умолчанию [S33].
- **Надёжнее для 4B**: обычный chat completion с полем `json_schema` (или `response_format` с JSON schema) — генерация жёстко ограничена грамматикой, невалидного JSON физически не бывает [S28]. Схема «действия» — дискриминированный `oneOf` по `tool` c enum-полями, `maxItems`, `minimum/maximum`. Это убирает петли и обрезание (мы видели их на большом плане): ограничивайте `maxItems` (например ≤ 8 шотов на секцию) и `maxLength` строк.
- Цена: «Let Me Speak Freely?» (EMNLP 2024) — строгий JSON-режим снижает качество *рассуждений* (GSM8K у GPT-3.5: 76,6 % → 49,25 %), но *улучшает* классификацию/выбор из вариантов; вариант «сначала свободный текст, потом конвертация в формат» сохраняет качество [S34]. JSONSchemaBench сравнивает движки constrained decoding, включая llama.cpp [S35].
- Практический рецепт: в схеме первым полем короткий `"why"` (`maxLength` ~200) — модель «думает» внутри JSON, затем решения. Для планирования storyboard — свободный текст/markdown с thinking, затем второй дешёвый вызов «перелей в схему».

### 3.3 Thinking vs non-thinking

| Шаг | Режим | Почему |
|---|---|---|
| Storyboard всего ролика (1 раз) | thinking, `--reasoning-budget` ~1000–2000, 9B если помещается | глобальные решения, нужен «вкус» |
| План секции (shot list) | non-thinking + json_schema с полем `why` | локальный выбор из enum; thinking + tools у Qwen3.5 нестабильны |
| Исполнение (вызов инструментов) | non-thinking, детерминированно; лучше вообще без LLM — компилятор | порядок и арифметика — код |
| Vision-проверка | non-thinking, ответ — enum `yes/no/unsure` + короткая причина | стабильнее и быстрее |

### 3.4 Скорость

- **Слоты**: `-np 2..4` + `--kv-unified` (по умолчанию) — планировать секции параллельно (секции независимы после storyboard). У гибридной модели KV мал, параллелизм дешёвый; ограничитель — compute 3050.
- **Prompt cache**: `cache_prompt: true` (по умолчанию), `--cache-ram` (по умолчанию 8192 MiB — при 14 GB RAM снизить до 2048–4096), `--cache-idle-slots`. Фиксировать `id_slot` за ролью (planner/vision), чтобы префиксы не вытесняли друг друга [S28].
- **Спекулятивное декодирование**: для Qwen3.5 работает только после PR #19493 «Speculative checkpointing» (апр. 2026) — флаги `--spec-use-checkpoints on --ctx-checkpoints 16` [S36]. Пользователь в обсуждении #22473 получил **регрессию** с Qwen3.5-0.8B как draft к 27B, а n-gram-спекуляция была лучше [S37]. Для 4B + 0.8B на одной 6-GB карте выигрыш маловероятен. Пробовать **`--spec-type ngram-mod`** (без доп. модели, общий пул для всех слотов, ~16 MB) — JSON-вывод с повторяющимися ключами хорошо предсказуем [S38]. Обязательно мерить acceptance.
- `-fa on`, полная выгрузка 4B на GPU (`-ngl 99`); mmproj на GPU (`--mmproj-offload`, по умолчанию). Ограничить токены изображения `--image-max-tokens` (например 256–512) — для yes/no хватает.

### 3.5 Дизайн промптов и инструментов для 4B

1. **Мало инструментов на шаг**: давать модели только инструменты текущей фазы (Tool RAG из TinyAgent [S14]); в фазе «план секции» — вообще один инструмент/одна схема.
2. **Enum вместо свободных значений**: `motion ∈ {static, push_in, pull_out, pan_left, pan_right}`, `look ∈ {...}`, `transition ∈ {cut, crossfade, whip, dip_black}`; ассеты — по коротким ID (`a07`), а не путям.
3. **Относительные величины**: модель даёт `weight` / `beats` (сколько тактов держать план), инструмент переводит в секунды по сетке битов и длине секции.
4. **1–2 коротких примера** (few-shot) правильного вызова прямо в system; примеры должны быть того же формата, что и схема.
5. **Состояние — в виде короткой сводки**, которую генерирует harness («секция 2/5, 4 шота, 12,4 с, свободно 3,1 с; осталось: CTA-карточка»), а не весь таймлайн.
6. **Ошибки инструментов — короткие и исправимые**: «asset a99 не существует; доступны a01..a12» + повтор шага; лимит 2 повтора, затем fallback по правилу.
7. Русский язык: отвечает и пишет титры на русском; ключи схем и enum — английские (меньше токенов, стабильнее).

### 3.6 Самокритика и vision-ревью

- Timeline-Bench: модели почти всегда считают свою работу успешной (93 %) [S8] → **критик должен быть внешним и узким**: программные проверки (дыры/перекрытия, длительность vs цель, LUFS, субтитры не выходят за safe-area, каждый пункт брифа покрыт) + VLM-вопросы с enum-ответами.
- Кадры для VLM — **контакт-лист** (ffmpeg `tile`, 3×3 с подписанными таймкодами) или одиночный кадр с конкретным вопросом: «Читается ли текст "…" на этом кадре? yes/no», «Есть ли чёрный/пустой кадр?», «Лицо обрезано краем? yes/no».
- Паттерн video-use: проверять **склейки** рендера (кадр до/после), до 3 итераций [S7].
- Темп: правило в компиляторе (например, для shorts план 1,5–3 с; Timeline-Bench: агенты режут в 0,72× медленнее референса [S8]).

### 3.7 Planner (крупнее) vs executor (меньше)

- Подтверждено α-UMi: разделение ролей помогает малым моделям [S13]. У нас: **9B = планировщик storyboard** (1–2 вызова на ролик, можно с частичной выгрузкой на CPU — медленно, но вызовов мало), **4B = план секций + vision**, **0.8B/2B** — классификация/теги ассетов, генерация коротких подписей **[эмпирика]**.
- На 6 GB 9B Q4 (~5,5 GB **[оценка]**) + mmproj + 4B одновременно не поместятся → либо последовательная смена моделей (выгрузка/загрузка, несколько секунд с NVMe), либо 9B частично на CPU. Режим «router» llama-server для нескольких моделей **[не проверено в этой работе]**.

---

## 4. Рекомендуемая архитектура harness (решения)

1. **Таймлайн принадлежит коду.** Единственный источник истины — Python-объект проекта (секции → шоты → дорожки), сериализуемый в OTIO для отладки. FilmCraft/EffectCraft получают команды только от компилятора, модель их не видит.
2. **Пайплайн из фиксированных фаз** (машина состояний, не свободный ReAct-цикл): `ingest → index → storyboard → section plans → compile → render preview → critique → fix → final render`. В каждой фазе модель видит 1–3 инструмента.
3. **Ingest/index без LLM**: PySceneDetect (шоты), faster-whisper large-v3-turbo с word timestamps (речь), Beat This! (биты/даунбиты музыки), ffmpeg `ebur128` (громкость), 0.8B/2B или 4B-vision даёт каждому шоту/ассету короткий тег-описание (1 вызов на ассет, контакт-лист 2×2). Результат — `index.json` с короткими ID.
4. **Storyboard один раз**: 9B (или 4B с thinking, `--reasoning-budget` ~1500), вывод — markdown со списком секций (цель, длительность в долях, настроение, текст на экране, музыка). Затем дешёвый вызов «перелей в схему» с `json_schema` (≤ 8 секций).
5. **План секции = один вызов 4B non-thinking с `json_schema`**: `{why, shots[≤8]: {asset_id enum, beats 1..8, motion enum, look enum, text?, transition_in enum}}`. Enum'ы `asset_id` подставлять динамически из индекса — модель не может сослаться на несуществующий файл. Секции планировать параллельно в 2 слотах.
6. **Вся арифметика в компиляторе**: биты → секунды, подгонка суммы к длительности секции, обрезка in/out по сценам, ducking под голос (`sidechaincompress`), нормализация до -14 LUFS (`loudnorm` 2 прохода), субтитры из слов по 2–4 слова, safe-area. Правило темпа (макс. длина плана по жанру) — тоже в компиляторе.
7. **Не полагаться на нативный tool-call парсер Qwen3.5 в llama.cpp** для критичных шагов: использовать `json_schema`-ограниченные ответы и свой диспетчер. Нативные tools — только в свободном «чат-режиме» с пользователем.
8. **Критик двухуровневый**: (а) программные проверки (дыры, длительность, LUFS, покрытие брифа, отсутствие повторов ассета подряд); (б) VLM 4B отвечает enum'ом на узкие вопросы по контакт-листу превью (ffmpeg `tile`, 480p) и по кадрам на склейках. Не спрашивать «хорошо ли получилось?» — самооценка ненадёжна. Максимум 2 итерации исправлений на секцию, затем fallback-правило (например, заменить шот на соседний по тегу).
9. **Исправления локальные**: критик возвращает `{section, shot, problem enum}`; перепланируется только эта секция (тот же вызов из п. 5 с подсказкой проблемы), остальной таймлайн не трогается — append-only история и стабильный префикс сохраняют кэш.
10. **Конфиг llama-server (4B)**: `-m Qwen3.5-4B-Q4_K_M.gguf --mmproj mmproj.gguf -ngl 99 -fa on -c 32768 -np 2 --jinja --reasoning off --cache-ram 3072 --image-max-tokens 512`, KV в f16 или q8_0 (не q4_0). Для storyboard — отдельный запрос с `chat_template_kwargs: {"enable_thinking": true}` и budget. Проверять, читает ли шаблон `enable_thinking`.
11. **Спекуляция — только после замера**: начать с `--spec-type ngram-mod` (без draft-модели); draft 0.8B для 4B, скорее всего, не окупится на 6 GB [S37]. Метрика — tokens/s на реальных section-plan запросах.
12. **Распределение VRAM по фазам**: LLM и тяжёлые модели (Whisper на GPU, Real-ESRGAN, rembg) не держать одновременно — ingest (Whisper/Beat This!/rembg) идёт до загрузки LLM либо на CPU (faster-whisper int8 на CPU, Piper на CPU). 9B подгружать только для storyboard.
13. **Шаблоны графики — пресеты EffectCraft** с enum `template_id` и текстовыми слотами; Remotion/Lottie — только как офлайн-генераторы оверлеев с альфой, при необходимости.
14. **Озвучка**: Silero v5 ru (качество; некоммерческая лицензия) или Piper ru_RU (GPL, отдельный процесс). Длительность реплики измеряет инструмент и сам растягивает секцию.
15. **Лицензии ассетов как данные**: `fetch_asset` (Openverse `license_type=commercial`, Wikimedia `extmetadata`, Freesound CC0, Pixabay) пишет `credits.json`; без записи лицензии ассет не попадает в индекс.
16. **Журнал и eval-набор**: каждый вызов модели (промпт, схема, ответ, время) — в лог событий (`docs/events.md`), плюс 10–20 эталонных задач-брифов с программными тестами по образцу Timeline-Bench для регресс-проверки промптов и моделей. Позже из удачных логов — LoRA-fine-tune 4B под наши схемы (TinyAgent: 41 % → 83 % на 7B [S14]).

---

## Источники

- [S1] LAVE, arXiv 2402.10294 — [arxiv.org/abs/2402.10294](https://arxiv.org/abs/2402.10294)
- [S2] LAVE, страница проекта — [dgp.toronto.edu/~bryanw/lave](https://dgp.toronto.edu/~bryanw/lave)
- [S3] ExpressEdit, arXiv 2403.17693 — [arxiv.org/abs/2403.17693](https://arxiv.org/abs/2403.17693)
- [S4] Prompt-Driven Agentic Video Editing System, arXiv 2509.16811 — [arxiv.org/abs/2509.16811](https://arxiv.org/abs/2509.16811)
- [S5] VideoAgent: All-in-One Framework, arXiv 2606.23327 — [arxiv.org/pdf/2606.23327](https://arxiv.org/pdf/2606.23327)
- [S6] HKUDS/VideoAgent — [github.com/HKUDS/VideoAgent](https://github.com/HKUDS/VideoAgent)
- [S7] browser-use/video-use — [github.com/browser-use/video-use](https://github.com/browser-use/video-use)
- [S8] Timeline-Bench, arXiv 2609.35143 — [arxiv.org/html/2609.35143v1](https://arxiv.org/html/2609.35143v1)
- [S9] MoneyPrinterTurbo — [github.com/harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)
- [S10] FFMPerative-7B — [huggingface.co/remyxai/ffmperative-7b](https://huggingface.co/remyxai/ffmperative-7b)
- [S11] OpenTimelineIO на PyPI — [pypi.org/project/OpenTimelineIO](https://pypi.org/project/OpenTimelineIO/)
- [S12] «How I automate 95% of my video workflow with AI coding agents» — [medium.com](https://medium.com/google-cloud/how-i-automate-95-of-my-video-workflow-with-ai-coding-agents-90dd4a87c53f)
- [S13] Small LLMs Are Weak Tool Learners (α-UMi), arXiv 2401.07324 — [arxiv.org/abs/2401.07324](https://arxiv.org/abs/2401.07324)
- [S14] TinyAgent, arXiv 2409.00608 — [arxiv.org/html/2409.00608v1](https://arxiv.org/html/2409.00608v1), [BAIR blog](https://bair.berkeley.edu/blog/2024/05/29/tiny-agent/)
- [S15] Local LLMs fail at tool calling (dev.to) — [dev.to/kuroko1t/...](https://dev.to/kuroko1t/what-happens-when-local-llms-fail-at-tool-calling-testing-7-models-with-a-rust-coding-agent-cep)
- [S16] MoviePy на PyPI — [pypi.org/project/moviepy](https://pypi.org/project/moviepy/)
- [S17] auto-editor — [github.com/wyattblue/auto-editor](https://github.com/wyattblue/auto-editor)
- [S18] Русский fine-tune whisper turbo (Habr) — [habr.com/ru/articles/1042574](https://habr.com/ru/articles/1042574/)
- [S19] whisper.cpp 1.8.3 (Phoronix) — [phoronix.com](https://phoronix.com/news/whisper-cpp-1.8.3-12x-perf)
- [S20] Beat This!, arXiv 2407.21658 — [arxiv.org/abs/2407.21658](https://arxiv.org/abs/2407.21658), [github.com/CPJKU/beat_this](https://github.com/CPJKU/beat_this)
- [S21] Remotion License — [remotion.dev/docs/license](https://www.remotion.dev/docs/license)
- [S22] Pixabay и Content ID (вторичный источник) — [hellothematic.com/thematic-vs-pixabay](https://hellothematic.com/thematic-vs-pixabay/)
- [S23] Openverse API — [api.openverse.org/v1](https://api.openverse.org/v1/)
- [S24] BRIA RMBG-2.0 — [huggingface.co/briaai/RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0)
- [S25] OHF-Voice/piper1-gpl — [github.com/OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl)
- [S26] Silero models — [github.com/snakers4/silero-models](https://github.com/snakers4/silero-models)
- [S27] Qwen3.5 карточка (зеркало) — [friendli.ai/models/Kotokin/MMV1](https://friendli.ai/models/Kotokin/MMV1); официальная — [huggingface.co/Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) (не открывалась)
- [S28] llama.cpp server README — [github.com/ggml-org/llama.cpp/.../tools/server/README.md](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [S29] Unsloth Qwen3.5-9B-GGUF: reasoning on/off — [huggingface.co/unsloth/Qwen3.5-9B-GGUF/discussions/2](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/discussions/2)
- [S30] llama.cpp issue #20182 (enable_thinking) — [github.com/ggml-org/llama.cpp/issues/20182](https://github.com/ggml-org/llama.cpp/issues/20182)
- [S31] llama.cpp issue #20837 (tool calls внутри thinking) — [github.com/ggml-org/llama.cpp/issues/20837](https://github.com/ggml-org/llama.cpp/issues/20837)
- [S32] llama.cpp issue #21158 (парсинг tool calls Qwen3.5) — [github.com/ggml-org/llama.cpp/issues/21158](https://github.com/ggml-org/llama.cpp/issues/21158)
- [S33] llama.cpp function-calling.md — [github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md)
- [S34] Let Me Speak Freely?, arXiv 2408.02442 — [arxiv.org/abs/2408.02442](https://arxiv.org/abs/2408.02442)
- [S35] JSONSchemaBench, arXiv 2501.10868 — [arxiv.org/abs/2501.10868](https://arxiv.org/abs/2501.10868)
- [S36] Speculative checkpointing (PR #19493, разбор) — [note.com/hacklog_stealth](https://note.com/hacklog_stealth/n/n1e1231b4869f?hl=en-US), [github.com/ggml-org/llama.cpp/pull/19493](https://github.com/ggml-org/llama.cpp/pull/19493)
- [S37] llama.cpp discussion #22473 (draft Qwen3.5-0.8B → регрессия) — [github.com/ggml-org/llama.cpp/discussions/22473](https://github.com/ggml-org/llama.cpp/discussions/22473)
- [S38] llama.cpp speculative.md — [github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
