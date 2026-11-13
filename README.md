# assemblee

Локальный ИИ-монтажёр: маленькая модель (Qwen3.5-4B со зрением, llama.cpp) монтирует вертикальные ролики
из картинок и брифов через настоящие open-source движки **FilmCraft** (NLE) и **EffectCraft** (моушн-графика),
а веб-монитор показывает в реальном времени, что агент сейчас делает.

## Как это устроено

Модель принимает только решения, всё ремесло и арифметику делает обвязка:

| Фаза | Кто | Что |
|---|---|---|
| explore | обвязка | читает брифы, строит каталог картинок (описания делает модель-зрение, кэш по mtime) |
| plan | модель | раскадровка: 3–8 секций, цель, длительность, музыка, стиль (JSON-схема) |
| build | модель ×N слотов | кадры каждой секции параллельно; id картинок — enum в схеме, выдумать нельзя |
| — | обвязка | минимальное время на чтение подписи, подгонка секций под длительность, нормализация значений |
| polish | модель | список правок (JSON-действия): эффекты, звуки, порядок, музыка |
| review | обвязка + зрение | сборка, рендер каждого кадра с текстом, модель-зрение судит «читается/нет», модель чинит |
| export | обвязка | компиляция EDL → FilmCraft → H.264 |

Монтаж хранится как **EDL** (данные), а таймлайн FilmCraft каждый раз собирается из него заново
(`assemblee/compiler.py`). Поэтому модель может переставлять и удалять кадры, а не только дописывать в конец.

Подробности и источники: [docs/research.md](docs/research.md), протокол событий: [docs/events.md](docs/events.md),
настройка сервера модели: [docs/llm-tuning.md](docs/llm-tuning.md).

## Запуск

```sh
scripts/make_audio.sh                 # один раз: синтезировать музыку и звуки (.cache/audio)
scripts/serve_llm.sh start agent      # 4B + зрение на :8011
python3 web/server.py --runs runs --port 8765 &   # монитор: http://127.0.0.1:8765
python3 -m assemblee run --assets ~/Рабочий\ стол/refs \
    --brief ~/Рабочий\ стол/"Last Online — GDD.md" \
    --task "Сделай необычный вертикальный питч трёх наших игр" --seconds 60
scripts/serve_llm.sh stop
```

Проверки без модели: `scripts/smoke_compile.py` (движки), `scripts/dry_run.py` (весь агент с поддельной LLM),
`scripts/fake_run.py` (демо-поток событий для UI).

## Картинки из интернета (`assemblee/fetch.py`)

Если своих картинок нет, обвязка находит их сама: `gather(task, llm, dest)` просит модель разбить задачу на
2–5 смысловых групп и 3–8 поисковых запросов **на английском**, ищет в **Openverse** (CC/PD, по умолчанию
только лицензии, разрешающие коммерческое использование и изменение) и **Wikimedia Commons**, скачивает
(≤ 15 МБ, короткая сторона ≥ 600 px, JPEG/PNG/WebP, проверка Pillow, отсев почти-дубликатов по dHash),
затем модель-зрение проверяет каждую картинку на соответствие сцене и удаляет лишние. Результат — папка
`<dest>/<группа>/<slug>.jpg`, готовая для `assets.load_or_build`; каталог уже заполнен описаниями, второй раз
ничего не описывается.

```sh
scripts/serve_llm.sh start agent
scripts/fetch_demo.py "сделай ролик про семью" --dest /tmp/family     # + контактный лист <dest>/.contact_sheet.jpg
python3 -m assemblee run --assets /tmp/family --task "сделай ролик про семью" --seconds 30
```

```python
from assemblee import fetch
fetch.search_images("family dinner", 10, orientation="vertical")         # нормализованные результаты
fetch.download(results, "/tmp/x", max_images=10, group="dinner")          # + /tmp/x/credits.json
fetch.gather(task, llm, "/tmp/x", per_query=6, max_total=30, on_event=lambda t, d: log.emit(t, **d))
```

- **Титры обязательны:** `<dest>/credits.json` — по записи на файл (asset id → provider, title, page_url,
  image_url, license, license_url, author, attribution, license_clear). Для CC BY / BY-SA указывайте `attribution`.
- `<dest>/.rejected.json` — отбракованные зрением (с описанием), повторный запуск их не скачивает.
- `on_event(type, data)` шлёт `tool_call`/`tool_result`/`warning` в формате [docs/events.md](docs/events.md)
  (имена: `plan_image_queries`, `search_images`, `download_images`, `download_image`, `check_image`, `gather_images`).
- Лимиты: Openverse анонимно 20 запросов/мин и 200/день (запросы разнесены на 3 с), `upload.wikimedia.org`
  отвечает 429 скриптам, поэтому файлы Commons берутся как миниатюры стандартных размеров с
  `thumb.wikimedia.org`, по одному. Локальный SearXNG (`providers=(..., "searxng")`, 127.0.0.1:8081)
  подключается только явно и только если доступен; его результаты с лицензией `unknown`.

## Зависимости

Python 3.12 + Pillow + aiohttp, ffmpeg, бинарники FilmCraft 0.20.1 и EffectCraft 0.24.1 (пути в
`assemblee/config.py`, переопределяются переменными `ASSEMBLEE_*`), llama.cpp `llama-server` с Vulkan/CUDA.
