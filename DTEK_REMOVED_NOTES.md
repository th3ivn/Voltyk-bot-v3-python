# DTEK Emergency Monitoring — Видалений функціонал

Дата видалення: 2026-03-22

Весь функціонал моніторингу аварійних відключень DTEK та перевірки адреси
був **повністю видалений** з бота. Цей файл описує як він працював і що
потрібно відновити, щоб все знову запрацювало.

---

## Що було видалено

### Файли — видалені повністю

| Файл | Призначення |
|------|-------------|
| `bot/services/emergency_monitor.py` | Фоновий сервіс моніторингу DTEK |
| `bot/handlers/address_check.py` | Хендлер кнопки "Перевірити адресу" |
| `bot/handlers/settings/emergency.py` | Хендлер налаштувань аварійного моніторингу |
| `bot/handlers/admin/dtek_debug.py` | Адмін-команда `/dtek_debug` (скриншоти) |
| `bot/handlers/admin/dtek_spy.py` | Адмін-команда `/dtek_spy` (перехоплення AJAX) |
| `debug_dtek_form.py` | Standalone Playwright debug скрипт |

### Зміни у файлах, що залишились

| Файл | Що було видалено |
|------|-----------------|
| `bot/app.py` | імпорт + запуск `emergency_monitor_loop`, виклик `stop_emergency_monitor` |
| `bot/handlers/__init__.py` | імпорт + реєстрація `address_check_router` |
| `bot/handlers/admin/__init__.py` | імпорт + реєстрація `dtek_debug_router`, `dtek_spy_router` |
| `bot/handlers/settings/router.py` | імпорт + реєстрація `emergency_router` |
| `bot/db/models.py` | класи `UserEmergencyConfig`, `UserEmergencyState`, relationships на `User`, поля `notify_emergency_off`/`notify_emergency_on` з `UserNotificationSettings` |
| `bot/db/queries.py` | 5 функцій + їх імпорти |
| `bot/states/fsm.py` | `EmergencySetupSG`, `AddressCheckSG` |
| `bot/keyboards/inline.py` | 6 emergency keyboard функцій + 3 address check keyboard функцій + кнопки в меню |
| `bot/formatter/messages.py` | рядок `🚨 Аварії:` в `format_live_status_message` |
| `bot/handlers/settings/alerts.py` | `"emergency_off"` і `"emergency_on"` з `field_map` в `notif_toggle` |

---

## Як це працювало

### Архітектура

```
Користувач → Налаштування → 🚨 Аварійні вимк. → вводить адресу
                                                      ↓
                                              зберігається в БД
                                                      ↓
                              emergency_monitor_loop (кожні 5 хв)
                                  ↓                       ↓
                            Playwright              aiohttp (кеш)
                                  ↓                       ↓
                         DTEK autocomplete       POST /ua/ajax
                                  ↓
                         перехоплює /ua/ajax відповідь
                                  ↓
                         порівнює з попереднім станом
                                  ↓
                      сповіщення якщо щось змінилось
```

### Сайти DTEK (по регіонах)

```python
_DTEK_SUBDOMAINS = {
    "kyiv": "kem",        # https://www.dtek-kem.com.ua/ua/shutdowns
    "kyiv-region": "krem", # https://www.dtek-krem.com.ua/ua/shutdowns
    "dnipro": "dnem",     # https://www.dtek-dnem.com.ua/ua/shutdowns
    "odesa": "oem",       # https://www.dtek-oem.com.ua/ua/shutdowns
}
```

### AJAX endpoint

```
POST https://www.dtek-{sub}.com.ua/ua/ajax
Content-Type: application/x-www-form-urlencoded

method=getHomeNum
&data[0][name]=city&data[0][value]={м. Вишгород}
&data[1][name]=street&data[1][value]={вул. Грушевського}
&data[2][name]=updateFact&data[2][value]={22.03.2026 19:50}

Headers:
  x-csrf-token: {token}
  x-requested-with: XMLHttpRequest
  Cookie: {Incapsula session cookies}
```

### Захист від ботів

DTEK використовує **Incapsula** — потрібен справжній Chromium (Playwright).
Без нього отримуєш 403 або порожню відповідь.

**Обхід:**
1. Playwright відкриває сторінку `shutdowns`
2. Заповнює форму через autocomplete (місто → вулиця → будинок)
3. Перехоплює відповідь на `/ua/ajax`
4. Зберігає cookies + CSRF token у `_session_cache`
5. Наступні запити — через aiohttp з тими ж cookies (без Playwright)
6. Кеш живе 1 годину, потім знову Playwright

### Структура відповіді DTEK

```json
{
  "data": [
    {
      "houseNum": "1",
      "sub_type_reason": "ЧЕРГА_1.1",
      "showCurOutageParam": {
        "startDate": "22.03.2026 08:00",
        "endDate": "22.03.2026 12:00"
      }
    }
  ]
}
```

- `sub_type_reason` → номер черги (regex: `r"ЧЕРГА_(\d+\.\d+)"`)
- `showCurOutageParam` → є? значить аварія активна
- `startDate`/`endDate` → час аварійного відключення

### База даних

**Таблиця `user_emergency_config`** — адреса користувача:
```sql
user_id   INTEGER (FK → users.id)
city      VARCHAR(128)   -- NULL для Києва
street    VARCHAR(255)
house     VARCHAR(32)
updated_at DATETIME
```

**Таблиця `user_emergency_state`** — поточний стан:
```sql
user_id     INTEGER (FK → users.id)
status      VARCHAR(16)   -- "none" або "active"
start_date  VARCHAR(32)   -- рядок від DTEK
end_date    VARCHAR(32)
detected_at DATETIME
updated_at  DATETIME
```

**Поля в `user_notification_settings`:**
- `notify_emergency_off BOOLEAN` — сповіщати коли аварія починається
- `notify_emergency_on BOOLEAN` — сповіщати коли аварія закінчується

---

## Що потрібно для відновлення

### Крок 1 — Відновити видалені файли

Взяти з git history (commit до цього):
```bash
git log --oneline  # знайти commit перед видаленням
git show {commit}:bot/services/emergency_monitor.py > bot/services/emergency_monitor.py
git show {commit}:bot/handlers/address_check.py > bot/handlers/address_check.py
git show {commit}:bot/handlers/settings/emergency.py > bot/handlers/settings/emergency.py
git show {commit}:bot/handlers/admin/dtek_debug.py > bot/handlers/admin/dtek_debug.py
git show {commit}:bot/handlers/admin/dtek_spy.py > bot/handlers/admin/dtek_spy.py
```

### Крок 2 — Відновити зміни у файлах

**`bot/app.py`** — у `on_startup` додати:
```python
from bot.services.emergency_monitor import emergency_monitor_loop
# ... у _bg_tasks.extend([...]):
asyncio.create_task(emergency_monitor_loop(bot)),
```
У `on_shutdown` додати:
```python
from bot.services.emergency_monitor import stop_emergency_monitor
stop_emergency_monitor()
```

**`bot/handlers/__init__.py`** — додати:
```python
from bot.handlers.address_check import router as address_check_router
# у register_all_handlers:
dp.include_router(address_check_router)
```

**`bot/handlers/admin/__init__.py`** — додати:
```python
from bot.handlers.admin.dtek_debug import router as dtek_debug_router
from bot.handlers.admin.dtek_spy import router as dtek_spy_router
router.include_router(dtek_debug_router)
router.include_router(dtek_spy_router)
```

**`bot/handlers/settings/router.py`** — додати:
```python
from bot.handlers.settings.emergency import router as emergency_router
router.include_router(emergency_router)
```

**`bot/db/models.py`** — відновити:
- Класи `UserEmergencyConfig` і `UserEmergencyState`
- На `User`: relationships `emergency_config` і `emergency_state`
- На `UserNotificationSettings`: поля `notify_emergency_off` і `notify_emergency_on`

**`bot/db/queries.py`** — відновити 5 функцій:
- `get_users_with_emergency_address`
- `upsert_user_emergency_config`
- `delete_user_emergency_config`
- `upsert_user_emergency_state`
- `get_user_emergency_state`

**`bot/states/fsm.py`** — відновити:
```python
class EmergencySetupSG(StatesGroup):
    waiting_for_city = State()
    waiting_for_street = State()
    waiting_for_house = State()

class AddressCheckSG(StatesGroup):
    waiting_for_region = State()
    waiting_for_address = State()
```

**`bot/keyboards/inline.py`** — відновити:
- 6 функцій `get_emergency_*`
- 3 функції `get_address_check_*`
- Кнопку в головному меню: `[_btn("🔍 Перевірити адресу", "address_check_start")]`
- Кнопку в налаштуваннях: `[_btn("🚨 Аварійні вимк.", "settings_emergency")]`

**`bot/formatter/messages.py`** — у `format_live_status_message` відновити:
```python
has_emergency = bool(
    getattr(user, "emergency_config", None)
    and user.emergency_config
    and user.emergency_config.street
)
# ...
msg += f"🚨 Аварії: {'моніторинг ✅' if has_emergency else 'не налаштовано'}\n"
```

**`bot/handlers/settings/alerts.py`** — у `field_map` в `notif_toggle` відновити:
```python
"emergency_off": "notify_emergency_off",
"emergency_on": "notify_emergency_on",
```

### Крок 3 — Міграція БД

Міграція вже є: `alembic/versions/0007_emergency_outage.py`
Вона автоматично запуститься при старті (через `_run_migrations()` в `app.py`).

### Крок 4 — Залежності

Playwright вже є в `pyproject.toml`. Нічого додавати не треба.

---

## Причина видалення

Функціонал визнаний занадто складним для підтримки. DTEK змінює верстку/захист,
що регулярно ламає Playwright-скрейпінг. Вирішено прибрати до простішого рішення.
