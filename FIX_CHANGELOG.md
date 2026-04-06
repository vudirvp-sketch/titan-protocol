# TITAN Protocol - Bug Fixes Changelog

## Исправленные проблемы

### 1. SEV-1: Дисбаланс кодовых блоков в PROTOCOL.base.md
**Файл:** `PROTOCOL.base.md`  
**Проблема:** Незакрытый код-блок на последней строке файла  
**Исправление:** Удалён лишний ``` в конце файла (строка 934)

```diff
- Architecture: deterministic, verifiable, rollback-safe, session-resumable, production-grade.
- ```
+ Architecture: deterministic, verifiable, rollback-safe, session-resumable, production-grade.
```

---

### 2. SEV-2: Regex lastIndex Bug в security.js
**Файл:** `skills/validators/security.js`  
**Проблема:** Глобальные regex с флагом /g не сбрасывают lastIndex между итерациями, что приводит к пропуску совпадений  
**Исправление:** Добавлен `pattern.lastIndex = 0` перед каждым вызовом `test()`

```javascript
// FIX: Reset lastIndex for global regex
pattern.lastIndex = 0;
if (pattern.test(line)) {
  // ...
}
```

---

### 3. SEV-3: Deprecated datetime.utcnow() в test_navigation.py
**Файл:** `scripts/test_navigation.py`  
**Проблема:** Использование устаревшего `datetime.utcnow()`, deprecated в Python 3.12  
**Исправление:** Заменено на `datetime.now(timezone.utc)`

```python
# Before:
"timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z"

# After:
"timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z")
```

---

### 4. SEV-3: Захардкоженные модели в enhanced_llm_query.py
**Файл:** `scripts/enhanced_llm_query.py`  
**Проблема:** Placeholder имена моделей без предупреждения  
**Исправления:**
1. Добавлен импорт `timezone`
2. Добавлены TODO комментарии для placeholder моделей
3. Добавлено WARNING о необходимости замены перед production
4. Исправлен deprecated `datetime.utcnow()` → `datetime.now(timezone.utc)`

```python
# Added import:
from datetime import datetime, timezone

# Added warning:
alternative_models: List[str] = field(default_factory=lambda: [
    "primary",  # TODO: Replace with actual model identifier
    "alternative-1",  # TODO: Replace with actual model identifier
    "alternative-2"  # TODO: Replace with actual model identifier
])
# WARNING: Default model names are placeholders.
# Set alternative_models to actual model identifiers before production use
```

---

### 5. SEV-4: Regex Escape в no-todos.js
**Файл:** `skills/validators/no-todos.js`  
**Проблема:** Неправильное создание RegExp из существующего объекта pattern  
**Исправление:** Использование `pattern.source` вместо передачи объекта RegExp

```javascript
// Before:
const matches = content.match(new RegExp(pattern, 'g'));

// After:
const flags = pattern.flags || 'g';
const globalPattern = new RegExp(pattern.source, flags);
const matches = content.match(globalPattern);
```

---

## Статистика исправлений

| Severity | Найдено | Исправлено |
|----------|---------|------------|
| SEV-1 (Critical) | 1 | 1 |
| SEV-2 (High) | 1 | 1 |
| SEV-3 (Medium) | 2 | 2 |
| SEV-4 (Low) | 1 | 1 |
| **Итого** | **5** | **5** |

---

## Команды для применения исправлений

```bash
# Распаковать архив в корне репозитория
cd titan-protocol
unzip -o titan_protocol_fixed_files.zip

# Проверить изменения
git diff

# Закоммитить
git add -A
git commit -m "fix: resolve 5 identified bugs from analysis

- SEV-1: Remove unclosed code block in PROTOCOL.base.md
- SEV-2: Reset regex lastIndex in security.js validator
- SEV-3: Replace deprecated datetime.utcnow() with timezone-aware version
- SEV-3: Add warnings for placeholder model names in enhanced_llm_query.py
- SEV-4: Fix regex pattern source extraction in no-todos.js"

# Отправить на GitHub
git push origin main
```
