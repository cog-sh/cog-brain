# Проверка и локальная установка — 2026-11-03

## Реализовано

- Локальный `Brain` API и JSON CLI, которые не импортируют MCP. Существующий executor агента может выполнить несколько операций одной программой и показать модели только итог.
- Автоматический ограниченный контекст с явной проектной областью, признаками снятия и предупреждениями. Lifecycle recall использует локальный lexical backend без ожидания Qdrant.
- Capture с idempotency key, явный просмотр daily, проектные карточки и handoff.
- Общий round-trip YAML, атомарная запись, межпроцессные блокировки и проверка revision при замене тела через API. Неизвестные поля и комментарии сохраняются. Произвольный внешний редактор не участвует в lock-протоколе: его замеченные изменения дают конфликт, но строгая filesystem CAS с ним не обещается.
- Индексатор сохраняет прежние чанки при отказе embeddings, явно сообщает частичные ошибки и сверяет содержимое/состав файлов с manifest вместо одного общего mtime.
- Description и aliases участвуют в retrieval; aliases разрешаются в ссылках; related сохраняет признаки снятия. Pi имеет отдельную конфигурацию от OMP.
- MCP остаётся совместимым адаптером с прежним текстовым содержимым и дополнительным structuredContent/error status.

## Проверки

`tests/test_local_api.py`: 20 тестов, все прошли в установленном tool-окружении. Включены настоящий MCP stdio, реальный локальный Qdrant с подменой только embeddings, отказ embeddings, сохранность YAML, конкурентные append из разных процессов, проектная изоляция, предел контекста, JSON-контракт Codex hook и исполняемые OMP/Pi adapters с восстановлением после compaction.

Также прошли `test_harnesses.py`, `test_graph_ingest.py`, `test_config.py`, skill validator и `git diff --check`. Тесты записи использовали временные vault, а не личные заметки.

## Что установлено локально

- Editable tool: `uv tool install --editable /Users/acidsugarx/CODES/h/cog-brain`.
- Общий skill: `~/.agents/skills/cog-brain/{SKILL.md,notes.md}`.
- Codex: command hooks в `~/.codex/hooks.json` для `SessionStart` и `UserPromptSubmit`, плюс короткий managed block в `~/.codex/AGENTS.md` для автономного CLI recall при отсутствии packet. В Codex 0.166 восстановление после compaction идёт через `SessionStart(compact)`; его `PostCompact` не принимает additionalContext.
- OMP: `~/.omp/agent/hooks/pre/cog-brain-context.ts`.
- Pi: `~/.pi/agent/extensions/cog-brain-context.ts`.
- Пользовательские MCP-записи cog-brain отключены; остальные серверы не отключались. Для установки с сохранением MCP есть `--keep-mcp`.
- Обновлены относящиеся к cog-brain OMP AGENTS/RULES. Старый инфраструктурный hook сохранён как `cog-brain-infra.ts.disabled-code-mode`, чтобы recall не запускал Docker.
- Создана `~/SECOND_BRAIN/cog-brain.md`, привязанная к репозиторию. Обновлены AI-GUIDE, AGENTS и историческая заметка OMP integration, чтобы инструкции соответствовали локальному API и единому пути `daily/`.

У изменённых конфигураций и skill созданы timestamped `.bak-cogbrain-*`. У AI-GUIDE/AGENTS vault сохранены `.before-code-mode`. Перед откатом выбрать резервную копию, сделанную до первого изменения нужного файла: более поздняя копия может уже содержать часть установки.

## Реальные клиентские проверки и ограничения

| Клиент | Наблюдение |
| --- | --- |
| Codex 0.166.0 | До одобрения новых hooks сессия без инструментов ответила `MISSING`. После установки короткого AGENTS fallback обычная read-only сессия на вопрос «С чего продолжить работу над этим проектом?» самостоятельно загрузила общий skill, выполнила `cog-brain context --lexical` и ответила по карточке проекта. Это подтверждает автономный recall через executor. Для загрузки до первого model turn требуется review/enable новых handlers через `/hooks`; trust не обходился и не редактировался программно. |
| Pi 1.1.0 | Default provider вернул `401 api_key_expired`. Проверка через уже настроенный openai-codex provider также упёрлась в `invalid_refresh_token`. Постоянные настройки модели и секреты не менялись. |
| OMP 18.12.6 | Default zai/glm-5.3 вернул `WeakMap keys must be objects or non-registered symbols`; то же воспроизвелось без нашего extension. Одноразовая проверка openai-codex сообщила отсутствие API key. Постоянные настройки провайдера не менялись. |

Автономный executor recall подтверждён реальным model turn Codex. Эти результаты не считаются успешной end-to-end проверкой предварительной hook-инъекции и всех трёх клиентов. Прямой вызов lifecycle bridge и изолированные исполняемые adapters проверены. После одобрения hooks/восстановления авторизации проверочный запрос без инструментов: вернуть `file_path` проектной карточки и точную первую фразу из `Next step`.

## Исторические документы с некорректным YAML

`EWW.md`, `anthropic-prompt-engineering.md`, `📁 templates/daily note_tpl.md` не переписывались. Индексатор сообщает проблемы, lexical retrieval показывает предупреждение и продолжает работу с остальными заметками. Шаблон содержит неотрендеренные template expressions; исходные документы требуют отдельного разбора, а не автоматического удаления текста.

Команда `cog-brain status` показывает текущую свежесть векторного индекса. Локальный автоматический recall не зависит от завершения его перестроения.

Векторный индекс перестроен: 624 корректные заметки синхронизированы, три исторических документа явно отмечены ошибками. Частичный результат возвращает ненулевой exit code, а не ложный успех.
