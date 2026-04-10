# TITAN Protocol - Repository Update Instructions

## Обновление от 2026-04-11

Этот пакет содержит исправления после завершения планов A, B, C.

---

## 📦 Содержимое пакета

```
titan-protocol-fix/
├── VERSION                        # Обновлённая версия 5.2.0
├── CHANGELOG.md                   # Обновлённый ченджлог
├── checkpoint_PHASE_A.yaml        # Недостающий чекпоинт
├── scripts/
│   └── cleanup_repository.sh      # Скрипт очистки
└── docs/
    └── REPOSITORY_UPDATE.md       # Этот файл
```

---

## 🚀 Инструкция по установке

### Шаг 1: Скопируйте файлы

Просто скопируйте папку `titan-protocol-fix` в корень вашего репозитория
и согласитесь на замену файлов при слиянии.

**Windows (PowerShell):**
```powershell
Copy-Item -Path "titan-protocol-fix\*" -Destination "путь\к\вашему\репозиторию" -Recurse -Force
```

**Linux/Mac:**
```bash
cp -r titan-protocol-fix/* /путь/к/вашему/репозиторию/
```

---

## 📋 Git Bash команды

### Полный цикл обновления репозитория

```bash
# === НАЧАЛО ОБНОВЛЕНИЯ ===

# 1. Перейдите в директорию репозитория
cd /путь/к/вашему/titan-protocol

# 2. Проверьте текущий статус
git status

# 3. Убедитесь, что находитесь на ветке main
git branch
# Если не на main:
git checkout main

# 4. Получите последние изменения (если репозиторий клонирован)
git pull origin main

# 5. Добавьте новые файлы из пакета
# (файлы уже скопированы на шаге 1)

# 6. Сделайте файл скрипта исполняемым
chmod +x scripts/cleanup_repository.sh

# 7. Запустите скрипт очистки (опционально)
./scripts/cleanup_repository.sh

# 8. Проверьте изменения
git status

# 9. Добавьте все изменения
git add -A

# 10. Создайте коммит
git commit -m "release: v5.2.0 - canonical patterns complete

- Added checkpoint_PHASE_A.yaml (was missing)
- Updated VERSION to 5.2.0
- Updated CHANGELOG.md with corrections
- Added cleanup script for duplicate removal
- Documented path corrections and assumption fixes
- Test count corrected to 3117"

# 11. Отправьте изменения в удалённый репозиторий
git push origin main

# === КОНЕЦ ОБНОВЛЕНИЯ ===
```

---

## 🗑️ Удаление устаревших файлов

### Автоматическое удаление (рекомендуется)

```bash
# Запустите скрипт очистки
./scripts/cleanup_repository.sh
```

### Ручное удаление

```bash
# Удалить дубликат utils/ (canonical = src/utils/)
rm -rf utils/

# Удалить Python кэш
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete

# Удалить временные файлы
find . -type f -name "*.bak" -delete
find . -type f -name "*~" -delete
find . -type f -name ".DS_Store" -delete
```

---

## ✅ Проверка после обновления

```bash
# Проверить наличие критических файлов
ls -la VERSION
ls -la checkpoint_PHASE_A.yaml
ls -la checkpoint_PHASE_B.yaml
ls -la checkpoint_PHASE_C.yaml
ls -la .ai/nav_map.json
ls -la .ai/shortcuts.yaml
ls -la .ai/path_corrections.yaml

# Проверить версию
cat VERSION
# Должно вывести: 5.2.0

# Проверить, что дубликат utils/ удалён
ls utils/ 2>/dev/null && echo "ВНИМАНИЕ: utils/ всё ещё существует!" || echo "OK: utils/ удалён"

# Проверить, что src/utils/ на месте
ls -la src/utils/

# Проверить чекпоинты
grep "status: COMPLETED" checkpoint_PHASE_A.yaml
grep "status: COMPLETED" checkpoint_PHASE_B.yaml
grep "status: COMPLETED" checkpoint_PHASE_C.yaml
```

---

## 📊 Что было исправлено

### Добавлено
| Файл | Описание |
|------|----------|
| `checkpoint_PHASE_A.yaml` | Недостающий чекпоинт для плана A |
| `scripts/cleanup_repository.sh` | Скрипт очистки дубликатов |

### Обновлено
| Файл | Изменения |
|------|-----------|
| `VERSION` | 5.1.0 → 5.2.0 |
| `CHANGELOG.md` | Добавлены секции v5.2.0 с исправлениями |

### К удалению
| Путь | Причина |
|------|---------|
| `utils/` | Дубликат `src/utils/` |

---

## ⚠️ Важные замечания

1. **НЕ удаляйте** `src/classification/` — содержит IntentClassifierV1
2. **НЕ удаляйте** `src/mode/` — содержит ModeSelector
3. **НЕ удаляйте** `adapters/` — это корневой пакет, не дубликат

---

## 🔗 Ссылки

- Репозиторий: https://github.com/vudirvp-sketch/titan-protocol
- Планы: TITAN_PROTOCOL_PLAN_A/B/C.md
- Отчёт: .ai/preflight_report.yaml
