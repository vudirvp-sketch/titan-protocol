# TITAN Protocol v1.2.0 Patch Installation Guide

## Содержимое архива

Этот архив содержит все новые и изменённые файлы для TITAN Protocol v1.2.0.

### Новые файлы (созданы):
```
schemas/
├── skill_chain.schema.json          # НОВАЯ схема для цепочек навыков

src/
├── orchestrator/
│   ├── chain_composer.py            # НОВЫЙ композитор цепочек
│   └── universal_router.py          # НОВЫЙ универсальный роутер
├── context/
│   ├── session_memory.py            # НОВАЯ сессионная память
│   └── intent_enricher.py           # НОВЫЙ обогатитель интентов
├── resilience/
│   ├── retry_executor_facade.py     # НОВЫЙ фасад ретри
│   └── __init__.py                  # НОВЫЙ модуль resilience
└── skills/
    ├── skill_graph_adapter.py       # НОВЫЙ адаптер графа навыков
    ├── context_adapter.py           # НОВЫЙ контекстный адаптер
    └── policy_adapter.py            # НОВЫЙ адаптер политик
```

### Изменённые файлы:
```
schemas/
├── validator_schema.json            # обновлён до v1.2.0
├── skill.schema.json                # обновлён до v1.2.0
├── context_bridge.schema.json       # обновлён до v1.2.0
└── event_types.schema.json          # обновлён до v1.2.0

src/
└── interfaces/
    └── plugin_interface.py          # добавлено поле fallback_used

config.yaml                          # добавлены секции v1.2.0 (~200 строк)

outputs/
├── checkpoint_PHASE_0.yaml          # отчёт фазы 0
├── checkpoint_PHASE_1.yaml          # отчёт фазы 1
├── checkpoint_PHASE_2.yaml          # отчёт фазы 2
├── api_compatibility_matrix.md      # матрица совместимости API
└── reconciliation_report.md         # отчёт согласования
```

## Установка

### Способ 1: Распаковка с заменой

```bash
# 1. Перейдите в корневую директорию проекта
cd /path/to/titan-protocol

# 2. Распакуйте архив поверх проекта
tar -xzvf titan-v1.2.0-patch.tar.gz --strip-components=1

# Это сохранит структуру директорий и заменит/добавит все файлы
```

### Способ 2: Ручное копирование

```bash
# Распакуйте архив в отдельную папку
mkdir -p /tmp/titan-patch
tar -xzvf titan-v1.2.0-patch.tar.gz -C /tmp/titan-patch

# Копируйте файлы вручную
cp -r /tmp/titan-patch/titan-v1.2.0-patch/* /path/to/titan-protocol/
```

---

## Git Bash Commands - Обновление репозитория

```bash
# ============================================
# GIT BASH КОМАНДЫ ДЛЯ ОБНОВЛЕНИЯ РЕПОЗИТОРИЯ
# ============================================

# 1. Перейдите в директорию проекта
cd /path/to/titan-protocol

# 2. Проверьте статус репозитория
git status

# 3. Убедитесь, что вы на нужной ветке (например, main или develop)
git branch

# 4. Если нужно, переключитесь на правильную ветку
git checkout main
# или
git checkout develop

# 5. Получите последние изменения (если работаете с удалённым репозиторием)
git pull origin main

# 6. Создайте новую ветку для изменений v1.2.0 (рекомендуется)
git checkout -b feature/titan-v1.2.0-implementation

# 7. Распакуйте архив с патчем
tar -xzvf /path/to/titan-v1.2.0-patch.tar.gz --strip-components=1

# 8. Добавьте все изменённые и новые файлы
git add schemas/skill_chain.schema.json
git add schemas/validator_schema.json
git add schemas/skill.schema.json
git add schemas/context_bridge.schema.json
git add schemas/event_types.schema.json
git add src/orchestrator/chain_composer.py
git add src/orchestrator/universal_router.py
git add src/context/session_memory.py
git add src/context/intent_enricher.py
git add src/resilience/retry_executor_facade.py
git add src/resilience/__init__.py
git add src/skills/skill_graph_adapter.py
git add src/skills/context_adapter.py
git add src/skills/policy_adapter.py
git add src/interfaces/plugin_interface.py
git add config.yaml
git add outputs/

# Или добавьте все изменения сразу:
git add .

# 9. Проверьте, что будет закоммичено
git status

# 10. Сделайте коммит
git commit -m "feat: implement TITAN Protocol v1.2.0 Phase 0-2

- Add skill_chain.schema.json for skill chain definitions
- Implement ChainComposer for chain composition and optimization
- Implement UniversalRouter as single entry point for all requests
- Implement SessionMemory with cross-request context persistence
- Implement IntentEnricher with 6-stage pipeline
- Implement RetryExecutorFacade with multiple named circuits
- Implement SkillGraphAdapter for graph-based skill selection
- Implement ContextAdapter for context transformation
- Implement PolicyAdapter for runtime policy enforcement
- Update schemas to v1.2.0
- Add fallback_used field to ExecutionResult
- Extend config.yaml with v1.2.0 sections
- Add checkpoint reports for phases 0-2"

# 11. Отправьте изменения в удалённый репозиторий
git push origin feature/titan-v1.2.0-implementation

# 12. (Опционально) Создайте Pull Request на GitHub
# Перейдите на https://github.com/vudirvp-sketch/titan-protocol
# и создайте PR из ветки feature/titan-v1.2.0-implementation в main

# ============================================
# АЛЬТЕРНАТИВНО: Прямой коммит в main
# ============================================

# Если не нужна отдельная ветка:
git checkout main
git pull origin main
tar -xzvf /path/to/titan-v1.2.0-patch.tar.gz --strip-components=1
git add .
git commit -m "feat: implement TITAN Protocol v1.2.0 Phase 0-2"
git push origin main
```

---

## Краткие команды (однострочники)

```bash
# Быстрое применение патча и коммит
cd /path/to/titan-protocol && \
tar -xzvf /path/to/titan-v1.2.0-patch.tar.gz --strip-components=1 && \
git add . && \
git commit -m "feat: implement TITAN Protocol v1.2.0 Phase 0-2" && \
git push origin main
```

---

## Статистика изменений

| Компонент | Файлов | Строк кода |
|-----------|--------|------------|
| Schemas | 5 | ~500 |
| Core Components | 9 | ~5200 |
| Config | 1 | ~200 |
| Outputs | 5 | ~500 |
| **Итого** | **20** | **~6400** |

---

## Примечания

1. Все новые компоненты интегрируются с EventBus
2. Все адаптеры реализуют PluginInterface
3. ExecutionResult включает поле fallback_used
4. RetryExecutorFacade предотвращает экспоненциальное умножение запросов
5. Совместимо с существующим кодом (обратная совместимость сохранена)

---

*Архив создан: 2026-04-09*
*TITAN Protocol v1.2.0 Implementation*
