# TITAN Protocol - README Sync Implementation Patch

## Файлы в архиве

### Измененные файлы:
- `.ai/nav_map.json` - обновленная карта навигации (версия 4.1.0)
- `.github/badges/security.json` - динамический security badge
- `.github/README_META.yaml` - метаданные протокола
- `src/agents/multi_agent_orchestrator.py` - интеграция с metrics collector
- `tests/docs/test_readme_snippets.py` - исправленный импорт

### Новые файлы:
- `.pre-commit-config.yaml` - pre-commit хуки для предотвращения дрейфа версий
- `scripts/generate_agent_meta.py` - генератор .meta.yaml из Python AST
- `scripts/generate_nav_map.py` - генератор nav_map.json из meta.yaml
- `tests/compliance/catalog_report.json` - отчет о соответствии
- `tests/docs/__init__.py` - init файл для пакета tests.docs
- `tests/docs/extract_snippets.py` - извлекатель code blocks из README

---

## Команды Git Bash для обновления репозитория

### Шаг 1: Распаковать архив
Распакуйте содержимое архива в корневую директорию проекта (папку `titan-protocol`).
Файлы сохранят структуру директорий.

### Шаг 2: Проверить изменения
```bash
# Перейти в директорию проекта
cd /путь/к/titan-protocol

# Посмотреть статус изменений
git status

# Посмотреть конкретные изменения
git diff
```

### Шаг 3: Добавить и закоммитить изменения
```bash
# Добавить все изменения
git add -A

# Или добавить конкретные файлы
git add .ai/nav_map.json
git add .github/badges/security.json
git add .github/README_META.yaml
git add .pre-commit-config.yaml
git add src/agents/multi_agent_orchestrator.py
git add scripts/generate_agent_meta.py
git add scripts/generate_nav_map.py
git add tests/compliance/catalog_report.json
git add tests/docs/__init__.py
git add tests/docs/extract_snippets.py
git add tests/docs/test_readme_snippets.py

# Создать коммит
git commit -m "feat: Complete README Sync Implementation (ITEM-SYNC-001 through ITEM-SYNC-011)

Implemented Phase 36-40 of TITAN Protocol README Sync Infrastructure:

Phase 36: Version Drift Elimination
- ITEM-SYNC-001: README_META.yaml created (single source of truth)
- ITEM-SYNC-002: nav_map.json version synced to 4.1.0
- ITEM-SYNC-003: readme_meta.schema.json created

Phase 37: TIER_7 Exit Criteria
- ITEM-SYNC-004: TIER_7_EXIT_CRITERIA.md created
- ITEM-SYNC-005: agent_metrics.yaml and AgentMetricsCollector created
- Integrated metrics collection in MultiAgentOrchestrator

Phase 38: Agent Navigation Enhancement
- ITEM-SYNC-006: Agent .meta.yaml files generated (3 modules)
- ITEM-SYNC-007: test_readme_snippets.py with extract_snippets.py

Phase 39: Security & Compliance Integration
- ITEM-SYNC-008: Dynamic security badge generation
- ITEM-SYNC-009: Compliance report auto-generation

Phase 40: Migration Infrastructure
- ITEM-SYNC-010: Unified titan migrate CLI with safety flags
- ITEM-SYNC-011: Deprecation warning system

Additional:
- Added .pre-commit-config.yaml for version drift prevention
- Created scripts/generate_nav_map.py and scripts/generate_agent_meta.py
- All 62 tests passing for multi_agent_orchestrator
- Version sync validated: VERSION=nav_map=META=4.1.0"
```

### Шаг 4: Отправить в репозиторий
```bash
# Отправить в основную ветку
git push origin main

# Или если используете master
git push origin master
```

---

## Дополнительные команды

### Проверка синхронизации версий
```bash
# Проверить, что все версии синхронизированы
VERSION=$(head -1 VERSION)
NAV_VERSION=$(python3 -c "import json; print(json.load(open('.ai/nav_map.json'))['version'])")
META_VERSION=$(python3 -c "import yaml; print(yaml.safe_load(open('.github/README_META.yaml'))['protocol']['version'])")

echo "VERSION file: $VERSION"
echo "nav_map.json: $NAV_VERSION"
echo "README_META.yaml: $META_VERSION"

if [ "$VERSION" = "$NAV_VERSION" ] && [ "$VERSION" = "$META_VERSION" ]; then
    echo "✅ All versions synchronized"
else
    echo "❌ VERSION DRIFT DETECTED"
fi
```

### Запуск тестов
```bash
# Запустить все тесты
python -m pytest tests/ -v

# Запустить тесты конкретного модуля
python -m pytest tests/test_multi_agent_orchestrator.py -v
python -m pytest tests/test_agent_protocol.py -v
python -m pytest tests/docs/ -v
```

### Генерация отчетов
```bash
# Сгенерировать nav_map.json
python scripts/generate_nav_map.py

# Сгенерировать compliance report
python scripts/generate_compliance_report.py --verify

# Сгенерировать security badge (без сканирования)
python scripts/generate_security_badge.py --skip-scan
```

### Установка pre-commit хуков
```bash
# Установить pre-commit (требуется pip install pre-commit)
pre-commit install

# Запустить все хуки вручную
pre-commit run --all-files
```

---

## Структура архива

```
titan-sync-patch/
├── .ai/
│   └── nav_map.json
├── .github/
│   ├── badges/
│   │   └── security.json
│   └── README_META.yaml
├── .pre-commit-config.yaml
├── scripts/
│   ├── generate_agent_meta.py
│   └── generate_nav_map.py
├── src/
│   └── agents/
│       └── multi_agent_orchestrator.py
├── tests/
│   ├── compliance/
│   │   └── catalog_report.json
│   └── docs/
│       ├── __init__.py
│       ├── extract_snippets.py
│       └── test_readme_snippets.py
└── README_GIT_COMMANDS.md
```

---

## Контакты

Если возникнут проблемы с применением патча, проверьте:
1. Структура директорий должна сохраниться при распаковке
2. Файлы должны попасть в корень проекта `titan-protocol/`
3. Права на запись в директорию проекта
