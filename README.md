# TITAN Protocol - Phase 2 Implementation (SAE)

Этот архив содержит файлы для реализации Phase 2 TITAN Self-Awareness Engine (SAE).

## Содержимое архива

```
titan-phase2/
├── .ai/
│   └── context_graph.json          # Пример файла контекстного графа
├── src/
│   ├── navigation/
│   │   └── context_graph_builder.py # ITEM-SAE-003: Генератор context_graph.json
│   └── context/
│       └── context_graph_events.py  # ITEM-SAE-010: EventBus интеграция
├── scripts/
│   ├── generate_context_graph.py    # CLI для генерации context_graph
│   └── sync_versions.py             # ITEM-SAE-001: Синхронизация версий
└── tests/
    └── test_sae_modules.py          # Тесты для SAE модулей
```

## Как установить файлы

### Способ 1: Распаковать и скопировать

```bash
# 1. Распакуйте архив в корень проекта
unzip titan-phase2-implementation.zip -d /путь/к/titan-protocol/

# 2. Скопируйте файлы в соответствующие директории
cd /путь/к/titan-protocol/
cp -r titan-phase2/src/navigation/context_graph_builder.py src/navigation/
cp -r titan-phase2/src/context/context_graph_events.py src/context/
cp -r titan-phase2/scripts/*.py scripts/
cp -r titan-phase2/tests/test_sae_modules.py tests/
mkdir -p .ai
cp titan-phase2/.ai/context_graph.json .ai/
```

### Способ 2: Git Bash команды

```bash
# Перейдите в корень репозитория
cd /путь/к/titan-protocol

# Проверьте текущую ветку
git branch

# Создайте новую ветку для Phase 2
git checkout -b feature/sae-phase2-implementation

# Добавьте новые файлы
git add src/navigation/context_graph_builder.py
git add src/context/context_graph_events.py
git add scripts/generate_context_graph.py
git add scripts/sync_versions.py
git add tests/test_sae_modules.py
git add .ai/context_graph.json

# Проверьте статус
git status

# Закоммитьте изменения
git commit -m "feat(sae): implement Phase 2 SAE modules

- ITEM-SAE-003: Add ContextGraphBuilder for context_graph.json generation
- ITEM-SAE-010: Add EventBus integration for ContextGraph
- ITEM-SAE-001: Add version synchronization script
- Add comprehensive tests for SAE modules
- Add example context_graph.json"

# Отправьте в удаленный репозиторий
git push origin feature/sae-phase2-implementation
```

## Что уже реализовано в репозитории

Большая часть Phase 2 уже реализована:

### ✅ ITEM-SAE-003: Context Graph Schema
- `src/context/context_graph.py` - полная реализация
- `schemas/context_graph.schema.json` - JSON схема

### ✅ ITEM-SAE-004: Trust Score Engine
- `src/context/trust_engine.py` - полная реализация

### ✅ ITEM-SAE-005: Version Vector System
- `src/context/version_vectors.py` - VectorClockManager, StaleDetector

### ✅ ITEM-SAE-006: AST Checksum System
- `src/context/semantic_checksum.py` - SemanticChecksum
- `src/context/checksum_cache.py` - ChecksumCache

### ✅ ITEM-SAE-007: Semantic Drift Detector
- `src/context/drift_detector.py` - DriftDetector
- `src/context/change_tracker.py` - ChangeTracker

### ✅ ITEM-SAE-008: EXEC Stage Pruning
- `src/context/summarization.py` - RecursiveSummarizer
- `src/context/pruning_policy.py` - PruningPolicy

### ✅ ITEM-SAE-010: EventBus Integration
- `src/events/context_events.py` - события и хендлеры

### ✅ ITEM-SAE-011: Profile Router Integration
- `src/context/profile_router.py` - ContextAwareProfileRouter

## Новые файлы в этом архиве

### context_graph_builder.py
Скрипт для автоматической генерации context_graph.json из анализа репозитория.

```bash
python scripts/generate_context_graph.py . .ai/context_graph.json
```

### context_graph_events.py
Расширяет ContextGraph для эмиссии событий в EventBus.

```python
from src.context.context_graph_events import create_context_graph_with_events

graph = create_context_graph_with_events(session_id="my-session")
# События будут автоматически отправляться в EventBus
```

### sync_versions.py
Синхронизация версий между VERSION файлом и другими файлами проекта.

```bash
# Проверка
python scripts/sync_versions.py --check

# Исправление
python scripts/sync_versions.py --fix
```

### test_sae_modules.py
Комплексные тесты для всех SAE модулей.

```bash
# Запуск тестов
pytest tests/test_sae_modules.py -v
```

## Запуск тестов

```bash
# Все тесты SAE
pytest tests/test_sae_modules.py -v

# Конкретный класс тестов
pytest tests/test_sae_modules.py::TestContextGraph -v
pytest tests/test_sae_modules.py::TestTrustEngine -v
pytest tests/test_sae_modules.py::TestVersionVector -v

# С покрытием кода
pytest tests/test_sae_modules.py --cov=src/context --cov-report=html
```

## Генерация context_graph.json

```bash
# Из корня проекта
python scripts/generate_context_graph.py . .ai/context_graph.json

# С исключением директорий
python scripts/generate_context_graph.py . .ai/context_graph.json --exclude node_modules venv build
```

## Обновление после слияния

После слияния ветки в main, обновите версию:

```bash
# Обновите VERSION файл
echo "5.1.0" > VERSION

# Синхронизируйте версии
python scripts/sync_versions.py --fix

# Закоммитьте
git add .
git commit -m "chore: bump version to 5.1.0"
git push origin main
```

## Статус реализации

| ITEM | Описание | Статус |
|------|----------|--------|
| ITEM-SAE-001 | Version Synchronization | ✅ Новый файл |
| ITEM-SAE-003 | Context Graph Schema | ✅ Уже реализовано |
| ITEM-SAE-004 | Trust Score Engine | ✅ Уже реализовано |
| ITEM-SAE-005 | Version Vector System | ✅ Уже реализовано |
| ITEM-SAE-006 | AST Checksum System | ✅ Уже реализовано |
| ITEM-SAE-007 | Semantic Drift Detector | ✅ Уже реализовано |
| ITEM-SAE-008 | EXEC Stage Pruning | ✅ Уже реализовано |
| ITEM-SAE-010 | EventBus Integration | ✅ Расширено |
| ITEM-SAE-011 | Profile Router Integration | ✅ Уже реализовано |

---

**Версия**: 5.1.0  
**Дата**: 2026-04-09  
**Статус**: Phase 2 - Завершена
