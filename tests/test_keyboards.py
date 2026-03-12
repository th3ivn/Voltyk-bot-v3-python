from src.bot.keyboards.inline import (
    get_main_menu,
    get_queue_keyboard,
    get_region_keyboard,
    get_wizard_notify_target_keyboard,
)


def test_region_keyboard_layout():
    kb = get_region_keyboard()
    rows = kb.inline_keyboard
    # Row 1: Київ | Київщина
    assert len(rows[0]) == 2
    assert rows[0][0].text == "Київ"
    assert rows[0][1].text == "Київщина"
    # Row 2: Дніпропетровщина | Одещина
    assert len(rows[1]) == 2
    assert rows[1][0].text == "Дніпропетровщина"
    assert rows[1][1].text == "Одещина"
    # Row 3: Suggest region
    assert "Запропонувати регіон" in rows[2][0].text


def test_queue_keyboard_non_kyiv():
    kb = get_queue_keyboard("dnipro")
    rows = kb.inline_keyboard
    # 12 queues in 4 rows of 3 + back button row
    assert len(rows) == 5
    assert rows[0][0].text == "1.1"
    assert rows[-1][0].text == "← Назад"


def test_queue_keyboard_kyiv_page1():
    kb = get_queue_keyboard("kyiv", 1)
    rows = kb.inline_keyboard
    # 12 queues in 3 rows of 4 + "Інші черги →" + "← Назад"
    assert len(rows) == 5
    assert rows[0][0].text == "1.1"
    assert "Інші черги" in rows[3][0].text
    assert rows[4][0].text == "← Назад"


def test_queue_keyboard_kyiv_page5():
    kb = get_queue_keyboard("kyiv", 5)
    rows = kb.inline_keyboard
    # 6 queues: 55.1-60.1 (2 rows of 4, but only 6 items) + back
    assert rows[-1][0].text == "← Назад"
    assert rows[-1][0].callback_data == "queue_page_4"


def test_notify_target_keyboard():
    kb = get_wizard_notify_target_keyboard()
    rows = kb.inline_keyboard
    assert len(rows) == 2
    assert rows[0][0].text == "📱 У цьому боті"
    assert rows[1][0].text == "📺 У Telegram-каналі"


def test_main_menu_no_channel():
    kb = get_main_menu("no_channel", False)
    rows = kb.inline_keyboard
    assert len(rows) == 3  # No channel pause/resume button
    assert rows[0][0].text == "Графік"
    assert rows[0][1].text == "Допомога"


def test_main_menu_with_channel():
    kb = get_main_menu("active", False)
    rows = kb.inline_keyboard
    assert len(rows) == 4  # Has channel pause button
    assert "зупинити канал" in rows[3][0].text.lower()


def test_main_menu_channel_paused():
    kb = get_main_menu("active", True)
    rows = kb.inline_keyboard
    assert len(rows) == 4
    assert "відновити" in rows[3][0].text.lower()
