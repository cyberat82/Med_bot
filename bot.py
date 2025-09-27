# 🇷🇺 ПОШАГОВОЕ ОБЪЯСНЕНИЕ ЛОГИКИ РАБОТЫ БОТА:
#
# 1.  **Запуск Бота (`main()`):**
#     - Инициализирует Telegram-бота, загружает токен и ID админ-чата из переменных окружения.
#     - Настраивает логирование для вывода информации в консоль и файл `bot_debug.log`.
#     - Определяет состояния для ConversationHandler, которые управляют потоком диалога с пользователем.
#     - Добавляет обработчик команды `/start`, который является точкой входа в диалог.
#     - Запускает опрос новых обновлений от Telegram (режим long-polling).
#
# 2.  **Начало Диалога (`start()`):**
#     - Отправляет пользователю сообщение с выбором типа записи: "Новая запись" или "Повторная запись".
#     - Переводит диалог в состояние `CHOOSING_SCENARIO`.
#
# 3.  **Обработка Выбора Сценария (`handle_scenario()`):**
#     - Принимает выбор пользователя ("scenario_new" или "scenario_repeat").
#     - Если выбрана "Новая запись":
#         - Инициализирует данные для анкеты пользователя.
#         - Задает первый вопрос анкеты и переводит диалог в состояние `FORM_Q`.
#     - Если выбрана "Повторная запись":
#         - Переходит к предложению дат для записи (`offer_dates`).
#
# 4.  **Обработка Анкеты (`handle_form()`):**
#     - Сохраняет ответ пользователя на текущий вопрос анкеты.
#     - Если есть еще вопросы в анкете, задает следующий вопрос.
#     - Если анкета заполнена:
#         - Добавляет временную метку, ID пользователя и его юзернейм к данным анкеты.
#         - Сохраняет заполненную анкету в Google Sheets.
#         - Если пользователь ответил "да" на вопрос об обращении к другим специалистам, предлагает связаться с администратором и завершает диалог.
#         - В противном случае, переходит к предложению дат (`offer_dates`) и переводит диалог в состояние `ASK_DATE`.
#
# 5.  **Предложение Дат (`offer_dates()`):**
#     - Генерирует кнопки с доступными датами, начиная со следующего дня и учитывая смещение для показа "еще дат".
#     - Позволяет пользователю выбрать дату или запросить больше дат.
#     - Переводит диалог в состояние `ASK_DATE`.
#
# 6.  **Обработка Выбора Даты (`handle_date_selection()`):**
#     - Сохраняет выбранную пользователем дату.
#     - Предлагает пользователю выбрать локацию (Новослободская, Серпуховская, Сокольники).
#     - Переводит диалог в состояние `ASK_LOCATION`.
#
# 7.  **Обработка Выбора Локации и Предложение Времени (`handle_location()`):**
#     - Сохраняет выбранную локацию.
#     - Определяет начальное время для поиска свободных слотов:
#         - Если запись на "завтра", то поиск начинается с 12:00.
#         - В противном случае, поиск начинается с 08:00.
#     - Использует функцию `get_available` из `scraper_json.py` для получения свободных слотов с сайта, учитывая:
#         - Выбранную локацию и дату.
#         - Полный дневной интервал (с учетом `start_time` до 21:00).
#         - Минимальную продолжительность слота (90 минут).
#         - Проверку наличия бронирований в Google Calendar (если есть бронь в другом месте, добавляется 1 час на дорогу).
#     - Генерирует кнопки с доступным временем.
#     - Если слотов нет, выводит соответствующее сообщение и предлагает вернуться к выбору даты или связаться с администратором.
#     - Переводит диалог в состояние `ASK_TIME`.
#
# 8.  **Обработка Выбора Времени (`handle_time()`):**
#     - Сохраняет выбранное время.
#     - Отправляет администратору в Telegram сообщение с деталями новой записи (имя пользователя, ID, дата, время, локация).
#     - Просит пользователя оплатить и отправить скриншот.
#     - Переводит диалог в состояние `HANDLE_SCREENSHOT`.
#
# 9.  **Обработка Скриншота Оплаты (`handle_screenshot()`):**
#     - Получает скриншот оплаты от пользователя.
#     - Пересылает скриншот администратору.
#     - Подтверждает запись пользователю.
#
# 10. **Кнопка "Назад" (`restart` callback):**
#     - Позволяет пользователю вернуться к началу процесса выбора даты и сценария.

# ⬇ Импорт необходимых библиотек
import logging
import os
import requests
from dotenv import load_dotenv
from telegram.ext import ContextTypes, Application, CommandHandler, MessageHandler, CallbackQueryHandler, \
    ConversationHandler

from scraper_universal import get_available, UniversalScraper
from google_utils import is_slot_free, append_row
import json
import uuid
from telegram.constants import ParseMode
from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Update

# Загрузка переменных окружения из файла .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0")) # Group for notifications
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0")) # Admin's private user ID for relay
GCAL_ID = os.getenv("GCAL_ID")
# ADMIN_USERNAME = os.getenv("ADMIN_USERNAME") # Удалена переменная ADMIN_USERNAME

# Проверка наличия токена бота
if not BOT_TOKEN:
    raise RuntimeError("❗ BOT_TOKEN не задан. Проверьте .env файл или переменные окружения.")

# Проверка наличия ADMIN_CHAT_ID
if ADMIN_CHAT_ID == 0:
    raise RuntimeError("❗ ADMIN_CHAT_ID не задан или некорректен. Добавьте его в .env или переменные окружения.")

# Инициализация универсального скрапера
universal_scraper = UniversalScraper()

# Маппинг location_id -> русские названия для уведомлений
LOCATION_TRANSLATIONS = {
    "polyanka_polyanka-1": "Третьяковская",
    "pokrovka_pokrovka-7": "Китай-город", 
    "myasnitskaya-8_myasnitskaya-4": "Лубянка",
    "sokolniki": "Сокольники"
}

# Маппинг location_id -> адреса для уведомлений
LOCATION_ADDRESSES = {
    "polyanka_polyanka-1": "улица Большая Ордынка, дом 34-38, подъезд № 3, этаж 1",
    "pokrovka_pokrovka-7": "Покровка", 
    "myasnitskaya-8_myasnitskaya-4": "Мясницкая улица, дом 8/2, строение 1, отдельный вход со стороны двора под навесом, этаж 3",
    "sokolniki": "Егерская улица, дом 3, этаж 1"
}

# Подробная информация для каждой локации (инструкции, коды доступа)
LOCATION_DETAILS = {
    "myasnitskaya-8_myasnitskaya-4": {
        "alias": "Лубянка",
        "cabinet": "Кабинет М-4",
        "pin": "6374 ENTER✔️",
        "how_to_find": (
            "Из метро Лубянка нужно выходить через выход 4. "
            "Выйдя из метро, пройдите по Мясницкой улице в сторону от центра, "
            "на первом же перекрестке сверните направо в переулок. Пройдите первую арку справа, "
            "входите во вторую (розового цвета). Выйдя из арки во двор, сразу справа увидите наш вход (Psycho Place). "
            "Чтобы открыть его, используйте свой личный код и в конце нажмите # («решётку»). "
            "Внутри входите в правую дверь, она также открывается личным кодом. "
            "Внутри поднимайтесь на 3-й этаж и открывайте дверь в холл своим кодом."
        )
    },
    "polyanka_polyanka-1": {
        "alias": "Третьяковская",
        "cabinet": "Кабинет Р-7",
        "pin": "6374 ENTER✔️",
        "domofon": "30К3833",
        "how_to_find": (
            "Из метро Третьяковская нужно выходить через выход 2. "
            "Выйдя из метро, поверните налево на Большую Ордынку. "
            "Пройдите по Большой Ордынке до дома 34−38 (он находится справа по ходу движения, в глубине двора за забором). "
            "Мы находимся в подъезде № 3 (слева). Код домофона 30К3833. "
            "Внутри подъезда слева дверь с табличкой Psycho Place."
        )
    },
    "pokrovka_pokrovka-7": {
        "alias": "Китай-город",
        "cabinet": "Кабинет П-1",
        "pin": "6374 ENTER✔️",
        "domofon": "41К4612",
        "how_to_find": (
            "Из метро Китай-город нужно выходить через выход 5. "
            "Следуйте по улице Покровка по направлению от центра. "
            "После Девяткина переулка будет нужный дом. Дойдите в нём до арки с синей табличкой номера дома «3/7 строение 1А» и проходите в арку. "
            "Во внутреннем дворе проходите прямо вглубь, немного слева увидите дверь с навесом — это вход. "
            "Если уличная дверь заперта — используйте код 41К4612. Коворкинг Psycho Place."
        )
    },
    "sokolniki": {
        "alias": "Сокольники",
        "cabinet": "Коворкинг U-Lisa",
        "pin": "0125#",
        "how_to_find": (
            "Из метро Сокольники нужно выходить через выход 1 с красной линии (или выход 5 если с БКЛ). "
            "Дойдя до искомого дома, во дворе обойдите выступающую часть здания слева и под навесом увидите дверь с табличкой коворкинга \"U-Lisa\"."
        )
    }
}

# # Проверка наличия имени пользователя администратора для кнопки "Связаться с администратором"
# if not ADMIN_USERNAME:
#     logging.warning("⚠️ ADMIN_USERNAME не задан. Кнопка 'Связаться с администратором' будет неактивна.")

# Настройка логирования с выводом в файл и консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot_debug.log", encoding="utf-8"), # Логирование в файл
        logging.StreamHandler() # Логирование в консоль
    ]
)

# Состояния для ConversationHandler (каждое число представляет собой уникальное состояние)
CHOOSING_SCENARIO, ASK_DATE, ASK_LOCATION, ASK_TIME, HANDLE_SCREENSHOT, FORM_Q, FORM_DONE, CONFIRM_RESCHEDULE, CONFIRM_CANCEL = range(9)
RESCHEDULE_DATE, RESCHEDULE_TIME = 100, 101  # уникальные значения для новых состояний

# Вопросы анкеты для новых клиентов
FORM_QUESTIONS = [
    "Ваше имя?",
    "Ваш возраст?",
    "Что болит?",
    "Как давно болит?",
    "Что стало причиной боли?",
    "Что уменьшает боль?",
    "В каких положениях боль сильнее/слабее?",
    "Как сейчас решаете проблему с болью?", 
    "Обращались раньше с этой проблемой к другим специалистам? (да/нет)"
]

# Update admin_button to use a URL button
ADMIN_CONTACT_URL = "https://t.me/Diamondo7878"
def admin_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Связаться с администратором", url=ADMIN_CONTACT_URL)]
    ])

# Функция для очистки названий локаций от цифр
def clean_location_name(name):
    """Удаляет цифры из названия локации"""
    if not name:
        return name
    return re.sub(r'\d+', '', name).strip()

# Функция для получения локализованного названия локации
def get_localized_location_name(location_id):
    """Получает русское название локации для уведомлений"""
    return LOCATION_TRANSLATIONS.get(location_id, location_id)

# Функция для получения адреса локации
def get_location_address(location_id):
    """Получает адрес локации для уведомлений"""
    return LOCATION_ADDRESSES.get(location_id, "")

# Функция для получения всех доступных локаций
def get_all_locations():
    """Получает все доступные локации из универсального скрапера"""
    locations = universal_scraper.get_all_locations()
    
    # Загружаем дополнительные локации из PsychoPlace если есть
    try:
        with open("psychoplace_locations.json", "r", encoding="utf-8") as f:
            psycho_locations = json.load(f)
            for key, info in psycho_locations.items():
                if key not in locations:
                    universal_scraper.register_location(key, "psychoplace", info["display_name"])
                    locations[key] = info
    except FileNotFoundError:
        pass
    
    return locations

# --- Custom Main Menu Keyboard ---
# Главное меню с новой структурой кнопок
MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup([
    ["🆕 Новая запись", "🔁 Повторная запись"],
    ["📋 Мои записи"],
    ["📞 Связаться с администратором"]
], resize_keyboard=True, one_time_keyboard=False, input_field_placeholder="Выберите действие")

# Add a helper for the inline reschedule button
INLINE_RESCHEDULE_BUTTON = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔁 Перенести запись", callback_data="reschedule")]
])

# Confirmation keyboard
CONFIRM_KEYBOARD = ReplyKeyboardMarkup([
    ["да", "нет"]
], resize_keyboard=True, one_time_keyboard=True)

APPOINTMENTS_FILE = os.getenv("APPOINTMENTS_FILE", "appointments.json")

def load_appointments():
    try:
        with open(APPOINTMENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_appointments(data):
    with open(APPOINTMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- Вспомогательные функции для истории шагов ---
def push_history(context, step, data=None):
    if 'history' not in context.user_data:
        context.user_data['history'] = []
    context.user_data['history'].append({'step': step, 'data': data or {}})

def pop_history(context):
    if 'history' in context.user_data and context.user_data['history']:
        return context.user_data['history'].pop()
    return None

def clear_history(context):
    context.user_data['history'] = []

# --- Обработчик кнопки 'Назад' ---
async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    # Если мы в режиме переноса записи и нажали "Назад", возвращаемся в главное меню
    if context.user_data.get('mode') == 'reschedule':
        await q.message.reply_text("Перенос записи отменён. Возвращаюсь в главное меню.", reply_markup=MAIN_MENU_KEYBOARD)
        # Очищаем данные режима переноса
        context.user_data.pop('mode', None)
        context.user_data.pop('reschedule_booking_id', None)
        context.user_data.pop('reschedule_date_offset', None)
        context.user_data.pop('new_reschedule_date', None)
        clear_history(context)
        return CHOOSING_SCENARIO
    
    # Обычная логика для других случаев
    last = pop_history(context)
    if not last:
        # Если история пуста — главное меню
        # Просто показываем клавиатуру без текста
        return CHOOSING_SCENARIO
    step = last['step']
    data = last['data']
    if step == 'date':
        context.user_data['date_offset'] = data.get('date_offset', 0)
        await offer_dates(update, context)
        return ASK_DATE
    elif step == 'location':
        # Восстановить дату
        if 'date' in data:
            context.user_data['date'] = data['date']
        await show_location_selection(update, context)
        return ASK_LOCATION
    elif step == 'time':
        # Восстановить дату и локацию
        if 'date' in data:
            context.user_data['date'] = data['date']
        if 'location' in data:
            context.user_data['location'] = data['location']
        await handle_location(update, context)
        return ASK_TIME
    elif step == 'reschedule_date':
        context.user_data['mode'] = 'reschedule'
        context.user_data['reschedule_date_offset'] = data.get('reschedule_date_offset', 0)
        await reschedule_show_dates(update, context)
        return RESCHEDULE_DATE
    elif step == 'reschedule_location':
        context.user_data['mode'] = 'reschedule'
        context.user_data['new_reschedule_date'] = data.get('new_reschedule_date')
        await reschedule_location_handler(update, context)
        return RESCHEDULE_TIME
    elif step == 'reschedule_time':
        context.user_data['mode'] = 'reschedule'
        context.user_data['new_reschedule_date'] = data.get('new_reschedule_date')
        context.user_data['location'] = data.get('location')
        await reschedule_time_handler(update, context)
        return RESCHEDULE_TIME
    else:
        return CHOOSING_SCENARIO

# --- Cancel booking handler (must be defined before ConversationHandler) ---
async def cancel_booking_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, booking_id: str = None, confirmed: bool = False):
    q = update.callback_query
    await q.answer()
    if not confirmed:
        await q.message.reply_text("Действие отменено. Возвращаюсь в главное меню.", reply_markup=MAIN_MENU_KEYBOARD)
        return CHOOSING_SCENARIO

    appointments = load_appointments()
    booking = next((a for a in appointments if a.get("booking_id") == booking_id), None)
    if not booking:
        await q.edit_message_text("Ошибка: запись не найдена.")
        return CHOOSING_SCENARIO
    # Удаляем запись
    appointments = [a for a in appointments if a.get("booking_id") != booking_id]
    save_appointments(appointments)
    # Уведомляем администратора
    user = q.from_user
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=(
            f"❌ Клиент отменил запись!\n"
            f"👤 {user.full_name} (@{user.username or '—'})\n"
            f"🆔 user_id: {user.id}\n"
            f"ID записи: {booking_id}\n"
            f"Дата: {booking.get('date','')}\nВремя: {booking.get('time','')}\nЛокация: {get_localized_location_name(booking.get('location',''))}\n"
            f"Адрес: {get_location_address(booking.get('location',''))}"
        )
    )
    # Подтверждаем клиенту
    await q.message.reply_text("Ваша запись отменена.", reply_markup=MAIN_MENU_KEYBOARD)
    return CHOOSING_SCENARIO

# --- Reschedule booking handlers (must be defined before ConversationHandler) ---
async def reschedule_booking_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, booking_id: str = None, confirmed: bool = False):
    q = update.callback_query
    await q.answer()
    if not confirmed:
        await q.message.reply_text("Действие отменено. Возвращаюсь в главное меню.", reply_markup=MAIN_MENU_KEYBOARD)
        return CHOOSING_SCENARIO
    context.user_data['mode'] = 'reschedule'
    context.user_data['reschedule_booking_id'] = booking_id
    context.user_data['reschedule_date_offset'] = 0
    push_history(context, 'reschedule_date', {'reschedule_date_offset': 0})
    return await reschedule_show_dates(update, context)

async def reschedule_show_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['mode'] = 'reschedule'
    offset = context.user_data.get('reschedule_date_offset', 0)
    today = dt.date.today()
    
    # Генерируем даты, начиная с текущего смещения
    start_day = max(1, 1 + offset)  # Минимум завтра (день 1)
    dates = [today + dt.timedelta(days=i) for i in range(start_day, start_day + 6)]  # Показываем 6 дат
    
    # Создаем кнопки для каждой даты в удобном формате (по 3 в ряд)
    date_buttons = []
    for i in range(0, len(dates), 3):  # Группируем по 3 даты в ряд
        row = []
        for j in range(i, min(i + 3, len(dates))):
            date = dates[j]
            # Красивый формат даты: "4 авг", "5 авг"
            date_text = date.strftime("%d %b").replace(" 0", " ")
            row.append(InlineKeyboardButton(date_text, callback_data=f"reschedule_date_{date.strftime('%d-%m-%Y')}"))
        date_buttons.append(row)
    
    # Создаем навигационные кнопки
    nav_buttons = []
    
    # Кнопка "Предыдущие даты" - показываем только если есть куда идти назад
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅ Предыдущие даты", callback_data="reschedule_prev_dates"))
    
    # Кнопка "Следующие даты" - всегда доступна
    nav_buttons.append(InlineKeyboardButton("➡ Следующие даты", callback_data="reschedule_next_dates"))
    
    # Собираем все кнопки
    buttons = date_buttons
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Добавляем кнопку "Назад"
    buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="reschedule_back")])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    q = update.callback_query
    await q.edit_message_text("Выберите новую дату для переноса:", reply_markup=reply_markup)
    push_history(context, 'reschedule_date', {'reschedule_date_offset': offset})
    return RESCHEDULE_DATE

async def reschedule_more_dates_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data['mode'] = 'reschedule'
    context.user_data['reschedule_date_offset'] = context.user_data.get('reschedule_date_offset', 0) + 3
    return await reschedule_show_dates(update, context)

# Обработчик кнопки "⬅ Предыдущие даты" для reschedule
async def reschedule_prev_dates_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data['mode'] = 'reschedule'
    current_offset = context.user_data.get('reschedule_date_offset', 0)
    # Не позволяем уйти в отрицательные значения (прошедшие даты)
    new_offset = max(0, current_offset - 3)
    context.user_data['reschedule_date_offset'] = new_offset
    return await reschedule_show_dates(update, context)

async def reschedule_back_to_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к выбору дат в режиме переноса записи"""
    q = update.callback_query
    await q.answer()
    context.user_data['mode'] = 'reschedule'
    # Очищаем выбранную дату и локацию, чтобы вернуться к выбору дат
    context.user_data.pop('new_reschedule_date', None)
    context.user_data.pop('location', None)
    return await reschedule_show_dates(update, context)

async def reschedule_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет перенос записи и возвращает в главное меню"""
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("Перенос записи отменён.", reply_markup=MAIN_MENU_KEYBOARD)
    # Очищаем данные режима переноса
    context.user_data.pop('mode', None)
    context.user_data.pop('reschedule_booking_id', None)
    context.user_data.pop('reschedule_date_offset', None)
    context.user_data.pop('new_reschedule_date', None)
    context.user_data.pop('location', None)
    clear_history(context)
    return CHOOSING_SCENARIO

async def reschedule_date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("reschedule_date_"):
        date_str = q.data.replace("reschedule_date_", "")
        context.user_data['new_reschedule_date'] = date_str
        push_history(context, 'reschedule_location', {'new_reschedule_date': date_str})
        # После выбора даты — спрашиваем локацию
        all_locations = get_all_locations()
        buttons = []
        
        # Добавляем локации LisaRent
        for loc_key, loc_info in all_locations.items():
            if loc_info.get("type") == "lisarent":
                display_name = loc_info.get("display_name", loc_key.title())
                buttons.append([InlineKeyboardButton(f"📍 {display_name}", callback_data=f"reschedule_loc_{loc_key}")])
        
        # Добавляем локации PsychoPlace
        for loc_key, loc_info in all_locations.items():
            if loc_info.get("type") == "psychoplace":
                display_name = loc_info.get("display_name", loc_key.title())
                buttons.append([InlineKeyboardButton(f"📍 {display_name}", callback_data=f"reschedule_loc_{loc_key}")])
        
        buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="reschedule_back")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await q.edit_message_text(f"Вы выбрали дату: {date_str}\nВыберите новую локацию:", reply_markup=reply_markup)
        return RESCHEDULE_TIME
    else:
        await q.edit_message_text("Ошибка выбора даты.")
        return RESCHEDULE_DATE

async def reschedule_location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("reschedule_loc_"):
        location = q.data.replace("reschedule_loc_", "")
        context.user_data['location'] = location
        
        # Получаем читаемое название локации и очищаем от цифр
        all_locations = get_all_locations()
        raw_display_name = all_locations.get(location, {}).get('display_name', location)
        clean_display_name = clean_location_name(raw_display_name)
        
        # Объединяем выбор локации и поиск в одно сообщение
        search_msg = await q.message.reply_text(f"⏳ Подождите, идёт поиск доступных слотов в локации {clean_display_name}...")
        
        # Удаляем кнопки выбора локации из чата
        try:
            await q.delete_message()
        except Exception as e:
            logging.warning(f"Не удалось удалить сообщение с локациями: {e}")
        
        date_str = context.user_data.get('new_reschedule_date')
        booking_id = context.user_data.get('reschedule_booking_id')
        appointments = load_appointments()
        booking = next((a for a in appointments if a.get("booking_id") == booking_id), None)
        if not booking:
            await q.edit_message_text(
                "Ошибка: запись не найдена.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ В главное меню", callback_data="reschedule_cancel")]
                ])
            )
            return RESCHEDULE_TIME
        date_iso = dt.datetime.strptime(date_str, "%d-%m-%Y").strftime("%Y-%m-%d")
        # Получаем слоты с учётом Google Calendar
        try:
            slots = get_available(location, date_iso, "08:00", "21:00", min_len=90, gcal_id=GCAL_ID)
        except Exception as e:
            logging.error(f"Error loading schedule for {location}: {e}")
            # Удаляем сообщение поиска
            try:
                await search_msg.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=f"❌ Ошибка загрузки расписания для локации {clean_display_name}.\n"
                     "Попробуйте позже или выберите другую локацию.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Выбрать другую дату", callback_data="reschedule_back_to_dates_from_no_slots")],
                    [InlineKeyboardButton("❌ Отменить перенос", callback_data="reschedule_cancel")]
                ])
            )
            return RESCHEDULE_TIME
        
        if not slots:
            # Удаляем сообщение поиска
            try:
                await search_msg.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=f"На {date_str} в {clean_display_name} нет доступных времён. Попробуйте другую дату или локацию.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Выбрать другую дату", callback_data="reschedule_back_to_dates_from_no_slots")],
                    [InlineKeyboardButton("❌ Отменить перенос", callback_data="reschedule_cancel")]
                ])
            )
            return RESCHEDULE_TIME
        # Убираем дубликаты и сортируем времена
        times = sorted(set(beg for cab, beg, end in slots), key=lambda t: t)
        context.user_data['reschedule_times'] = times
        # Только инлайн-кнопки времени, без plain text
        buttons = [[InlineKeyboardButton(t, callback_data=f"reschedule_time_{t}")] for t in times]
        buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="reschedule_back")])
        reply_markup = InlineKeyboardMarkup(buttons)
        # Удаляем сообщение поиска
        try:
            await search_msg.delete()
        except Exception:
            pass
        
        push_history(context, 'reschedule_time', {'new_reschedule_date': date_str, 'location': location})
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text="Выберите новое время:",
            reply_markup=reply_markup
        )
        return RESCHEDULE_TIME
    else:
        await q.edit_message_text("Ошибка выбора локации.")
        return RESCHEDULE_TIME

async def reschedule_time_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("reschedule_time_"):
        time_str = q.data.replace("reschedule_time_", "")
        
        # Показываем сообщение обработки
        processing_msg = await q.message.reply_text("⏳ Подождите, переносим вашу запись...")
        
        # Удаляем кнопки выбора времени из чата
        try:
            await q.delete_message()
        except Exception as e:
            logging.warning(f"Не удалось удалить сообщение с временами: {e}")
        
        booking_id = context.user_data.get('reschedule_booking_id')
        new_date = context.user_data.get('new_reschedule_date')
        location = context.user_data.get('location')
        appointments = load_appointments()
        updated = False
        for a in appointments:
            if a.get("booking_id") == booking_id:
                a["date"] = new_date
                a["time"] = time_str
                a["location"] = location
                updated = True
        save_appointments(appointments)
        # Удаляем сообщение обработки
        try:
            await processing_msg.delete()
        except Exception as e:
            logging.warning(f"Не удалось удалить сообщение обработки: {e}")
        
        user = q.from_user
        if updated:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"🔁 Клиент перенёс запись!\n"
                    f"👤 {user.full_name} (@{user.username or '—'})\n"
                    f"🆔 user_id: {user.id}\n"
                    f"📅 Дата: {new_date}\n"
                    f"⏰ Время: {time_str}\n"
                    f"📍 Локация: {get_localized_location_name(location)}\n"
                    f"🏠 Адрес: {get_location_address(location)}"
                )
            )
            # Единый шаблон подтверждения для клиента
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=confirm_booking_message(new_date, time_str, location),
                reply_markup=MAIN_MENU_KEYBOARD
            )
        else:
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="Ошибка: запись не найдена.",
                reply_markup=MAIN_MENU_KEYBOARD
            )
        return CHOOSING_SCENARIO
    else:
        await q.edit_message_text("Ошибка выбора времени.")
        return RESCHEDULE_TIME

# Обработчик команды /start - начальная точка входа в диалог
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Очищаем все данные пользователя для чистого старта
    context.user_data.clear()
    logging.info(f"🚀 User {update.effective_user.id} started the bot (context cleared)")
    
    if update.message:
        await update.message.reply_text(
            "👋 Добро пожаловать! Выберите действие:",
            reply_markup=MAIN_MENU_KEYBOARD
        )
        return CHOOSING_SCENARIO
    elif update.callback_query:
        q = update.callback_query
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text="👋 Добро пожаловать! Выберите действие:",
            reply_markup=MAIN_MENU_KEYBOARD
        )
        return CHOOSING_SCENARIO

# Обработчик выбора сценария (новая или повторная запись)
async def handle_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer() # Отправляем подтверждение о получении колбэка
        logging.info(f"✅ CallbackQuery answered successfully for {q.data}.")
    except Exception as e:
        logging.error(f"❌ Failed to answer CallbackQuery for {q.data}: {e}")
    
    context.user_data['scenario'] = q.data # Сохраняем выбранный сценарий

    if q.data == "scenario_new":
        # Если выбрана новая запись, начинаем заполнение анкеты
        context.user_data['form'] = [] # Инициализация списка для ответов анкеты
        context.user_data['form_q'] = 0 # Установка счетчика вопросов
        await q.edit_message_text(FORM_QUESTIONS[0]) # Задаем первый вопрос
        return FORM_Q # Переход в состояние заполнения анкеты
    
    # Если выбрана повторная запись, сразу предлагаем даты
    return await offer_dates(update, context)

# Обработчик заполнения анкеты
async def handle_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text # Получаем ответ пользователя
    q_num = context.user_data.get('form_q', 0) # Получаем текущий номер вопроса
    context.user_data['form'].append(answer) # Добавляем ответ в список

    if q_num + 1 < len(FORM_QUESTIONS):
        # Если есть еще вопросы, задаем следующий
        context.user_data['form_q'] = q_num + 1
        await update.message.reply_text(FORM_QUESTIONS[q_num + 1])
        return FORM_Q
    else:
        # Если анкета заполнена
        user = update.effective_user
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Формируем данные для сохранения в Google Sheets
        form_data = [
            timestamp,
            str(user.id),
            user.username or "—",
            *context.user_data['form']  # Разворачиваем ответы из анкеты
        ]
        append_row(form_data) # Сохраняем данные в Google Sheets
        
        if answer.strip().lower() == 'да':
            # Если пользователь обращался к другим специалистам, предлагаем связаться с админом
            await update.message.reply_text(
                "Спасибо! Пожалуйста, свяжитесь с администратором для уточнения деталей:",
                reply_markup=admin_button()
            )
            return ConversationHandler.END # Завершаем диалог
        else:
            # В противном случае, предлагаем выбрать день для записи
            await offer_dates(update, context)
            return ASK_DATE # Переход в состояние выбора даты

# Асинхронная функция для предложения дат
async def offer_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    offset = context.user_data.get('date_offset', 0)
    print(f"DEBUG: offer_dates called with offset {offset}")
    logging.info(f"DEBUG: offer_dates called with offset {offset}")
    today = dt.date.today()
    
    # Генерируем даты, начиная с текущего смещения
    # Убеждаемся, что не показываем прошедшие даты
    start_day = max(1, 1 + offset)  # Минимум завтра (день 1)
    dates = [today + dt.timedelta(days=i) for i in range(start_day, start_day + 6)]  # Показываем 6 дат
    
    # Создаем кнопки для каждой даты в удобном формате (по 3 в ряд)
    date_buttons = []
    for i in range(0, len(dates), 3):  # Группируем по 3 даты в ряд
        row = []
        for j in range(i, min(i + 3, len(dates))):
            date = dates[j]
            # Красивый формат даты: "4 авг", "5 авг"
            date_text = date.strftime("%d %b").replace(" 0", " ")
            row.append(InlineKeyboardButton(date_text, callback_data=f"date_{date.strftime('%d-%m-%Y')}"))
        date_buttons.append(row)
    
    # Создаем навигационные кнопки
    nav_buttons = []
    
    # Кнопка "Предыдущие даты" - показываем только если есть куда идти назад
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅ Предыдущие даты", callback_data="prev_dates"))
    
    # Кнопка "Следующие даты" - всегда доступна
    nav_buttons.append(InlineKeyboardButton("➡ Следующие даты", callback_data="next_dates"))
    
    # Собираем все кнопки
    buttons = date_buttons
    if nav_buttons:
        buttons.append(nav_buttons)

    reply_markup_dates = InlineKeyboardMarkup(buttons)

    # Отправляем новое сообщение или редактируем существующее в зависимости от источника вызова
    if update.message: # Если это обычное сообщение (например, после заполнения формы)
        logging.info("➡️ offer_dates: Source is Message. Sending new date selection message.")
        await update.message.reply_text("Выберите день для записи:", reply_markup=reply_markup_dates)
    elif update.callback_query: # Если это колбэк (например, кнопка "Назад" или "Показать ещё даты")
        q = update.callback_query
        logging.info(f"➡️ offer_dates: Source is CallbackQuery (data: {q.data}). Attempting to edit/send message for date selection.")
        try:
            await q.answer() # Отправляем подтверждение о получении колбэка
        except Exception as e:
            logging.error(f"❌ Failed to answer CallbackQuery for {q.data}: {e}")

        try:
            await q.edit_message_text(text="Выберите день для записи:", reply_markup=reply_markup_dates)
            logging.info("✅ Date selection message edited successfully by offer_dates (from CallbackQuery). ")
        except Exception as e:
            logging.error(f"❌ Failed to edit message by offer_dates: {e}. Sending new message instead.")
            await context.bot.send_message(chat_id=q.message.chat_id, text="Выберите день для записи:", reply_markup=reply_markup_dates)
            logging.info("✅ New date selection message sent successfully by offer_dates (from CallbackQuery).")

    push_history(context, 'date')
    return ASK_DATE

# Вспомогательная функция для отображения кнопок выбора локации
async def show_location_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("➡️ show_location_selection: Function called to display location buttons.")
    
    # Получаем все доступные локации
    locations = get_all_locations()
    
    # Группируем локации по типу для удобного отображения
    keyboard = []
    
    # Сначала добавляем локации LisaRent
    for loc_key, loc_info in locations.items():
        if loc_info.get("type") == "lisarent":
            display_name = loc_info.get("display_name", loc_key.title())
            keyboard.append([InlineKeyboardButton(f"📍 {display_name}", callback_data=f"loc_{loc_key}")])
    
    # Затем добавляем локации PsychoPlace
    for loc_key, loc_info in locations.items():
        if loc_info.get("type") == "psychoplace":
            display_name = loc_info.get("display_name", loc_key.title())
            keyboard.append([InlineKeyboardButton(f"📍 {display_name}", callback_data=f"loc_{loc_key}")])
    
    # Добавляем кнопку "Назад"
    keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_dates")])
    
    reply_markup_locations = InlineKeyboardMarkup(keyboard)

    if update.message:
        logging.info("➡️ show_location_selection: Source is Message. Sending new location selection message.")
        await update.message.reply_text("Выберите локацию:", reply_markup=reply_markup_locations)
    elif update.callback_query:
        q = update.callback_query
        logging.info(f"➡️ show_location_selection: Source is CallbackQuery (data: {q.data}). Attempting to edit/send message for location selection.")
        try:
            await q.answer()
        except Exception as e:
            logging.error(f"❌ Failed to answer CallbackQuery for {q.data}: {e}")
        
        try:
            await q.edit_message_text(text="Выберите локацию:", reply_markup=reply_markup_locations)
            logging.info("✅ Location selection message edited successfully by show_location_selection (from CallbackQuery).")
        except Exception as e:
            logging.error(f"❌ Failed to edit message by show_location_selection: {e}. Sending new message instead.")
            await context.bot.send_message(chat_id=q.message.chat_id, text="Выберите локацию:", reply_markup=reply_markup_locations)
            logging.info("✅ New location selection message sent successfully by show_location_selection (from CallbackQuery).")
    
    push_history(context, 'location')
    return ASK_LOCATION

# Обработчик кнопки "➡ Следующие даты" (переименованная "Показать ещё даты")
async def handle_more_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if context.user_data.get('mode') == 'reschedule':
        context.user_data['reschedule_date_offset'] = context.user_data.get('reschedule_date_offset', 0) + 3
        return await reschedule_show_dates(update, context)
    else:
        context.user_data['date_offset'] = context.user_data.get('date_offset', 0) + 3
        return await offer_dates(update, context)

# Обработчик кнопки "⬅ Предыдущие даты"
async def handle_prev_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if context.user_data.get('mode') == 'reschedule':
        current_offset = context.user_data.get('reschedule_date_offset', 0)
        # Не позволяем уйти в отрицательные значения (прошедшие даты)
        new_offset = max(0, current_offset - 3)
        context.user_data['reschedule_date_offset'] = new_offset
        return await reschedule_show_dates(update, context)
    else:
        current_offset = context.user_data.get('date_offset', 0)
        # Не позволяем уйти в отрицательные значения (прошедшие даты)
        new_offset = max(0, current_offset - 3)
        context.user_data['date_offset'] = new_offset
        return await offer_dates(update, context)

# Обработчик выбора даты
async def handle_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q is not None:
        await q.answer()
        if q.data.startswith("date_"):
            date_str = q.data.replace("date_", "")
            context.user_data["date"] = dt.datetime.strptime(date_str, "%d-%m-%Y").strftime("%d/%m/%Y")
            context.user_data['date_offset'] = 0  # Reset offset after date selection
            # После выбора даты — спрашиваем локацию
            all_locations = get_all_locations()
            buttons = []
            
            # Добавляем локации LisaRent
            for loc_key, loc_info in all_locations.items():
                if loc_info.get("type") == "lisarent":
                    display_name = loc_info.get("display_name", loc_key.title())
                    buttons.append([InlineKeyboardButton(f"📍 {display_name}", callback_data=f"loc_{loc_key}")])
            
            # Добавляем локации PsychoPlace
            for loc_key, loc_info in all_locations.items():
                if loc_info.get("type") == "psychoplace":
                    display_name = loc_info.get("display_name", loc_key.title())
                    buttons.append([InlineKeyboardButton(f"📍 {display_name}", callback_data=f"loc_{loc_key}")])
            
            buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_dates")])
            reply_markup = InlineKeyboardMarkup(buttons)
            await q.edit_message_text(f"Вы выбрали дату: {date_str}\nВыберите локацию:", reply_markup=reply_markup)
            return ASK_LOCATION
        else:
            await q.edit_message_text("Введите дату вручную в формате дд/мм/гггг:")
            return ASK_DATE
    else:
        # Handle text message (manual date entry)
        date_text = update.message.text.strip()
        try:
            dt.datetime.strptime(date_text, "%d/%m/%Y")
            context.user_data["date"] = date_text
            context.user_data['date_offset'] = 0  # Reset offset after date selection
            # После выбора даты — спрашиваем локацию
            all_locations = get_all_locations()
            buttons = []
            
            # Добавляем локации LisaRent
            for loc_key, loc_info in all_locations.items():
                if loc_info.get("type") == "lisarent":
                    display_name = loc_info.get("display_name", loc_key.title())
                    buttons.append([InlineKeyboardButton(f"📍 {display_name}", callback_data=f"loc_{loc_key}")])
            
            # Добавляем локации PsychoPlace
            for loc_key, loc_info in all_locations.items():
                if loc_info.get("type") == "psychoplace":
                    display_name = loc_info.get("display_name", loc_key.title())
                    buttons.append([InlineKeyboardButton(f"📍 {display_name}", callback_data=f"loc_{loc_key}")])
            
            buttons.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_dates")])
            reply_markup = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(f"Вы выбрали дату: {date_text}\nВыберите локацию:", reply_markup=reply_markup)
            return ASK_LOCATION
        except Exception:
            await update.message.reply_text("Пожалуйста, введите дату в формате дд/мм/гггг:")
            return ASK_DATE

# Обработчик выбора локации и предложения временных слотов
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer() # Отправляем подтверждение о получении колбэка
    location = q.data.replace("loc_", "")
    context.user_data["location"] = location # Сохраняем выбранную локацию

    # Получаем читаемое название локации и очищаем от цифр
    all_locations = get_all_locations()
    raw_display_name = all_locations.get(location, {}).get('display_name', location)
    clean_display_name = clean_location_name(raw_display_name)
    
    # Объединяем выбор локации и поиск в одно сообщение
    search_msg = await q.message.reply_text(f"⏳ Подождите, идёт поиск доступных слотов в локации {clean_display_name}...")
    
    # Удаляем кнопки выбора локации из чата
    try:
        await q.delete_message()
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение с локациями: {e}")

    date_str = context.user_data["date"]
    selected_date = dt.datetime.strptime(date_str, "%d/%m/%Y").date()
    date_iso = selected_date.strftime("%Y-%m-%d") # Форматируем дату для Google Calendar
    logging.info(f"🔍 Checking availability for {location} on {date_iso}") # Логируем проверку доступности

    start_time = "08:00" # Начальное время для поиска слотов по умолчанию
    # Если запись на завтра, начинаем поиск с 12:00
    if selected_date == dt.date.today() + dt.timedelta(days=1):
        start_time = "12:00"
        logging.info(f"🗓️ Booking for tomorrow, setting start time to {start_time}") # Логируем изменение начального времени

    # Интервал для проверки доступности (полный день, скорректированный для завтрашней записи)
    intervals = [
        (start_time, "21:00"),
    ]
    seen = set() # Множество для отслеживания уже добавленных временных слотов (чтобы избежать дубликатов)
    reply_markup = [] # Список для кнопок с временными слотов
    for start, end in intervals:
        logging.info(f"⏰ Checking interval {start}-{end}") # Логируем текущий интервал
        # Получаем доступные слоты с сайта, учитывая Google Calendar и время на дорогу
        try:
            slots = get_available(location, date_iso, start, end, min_len=90, gcal_id=GCAL_ID)
            logging.info(f"📅 Found {len(slots)} slots from website for {start}-{end}") # Логируем количество слотов с сайта
        except Exception as e:
            logging.error(f"Error loading schedule for {location}: {e}")
            # Редактируем сообщение поиска для показа ошибки
            try:
                await search_msg.edit_text(
                    text=f"❌ Ошибка загрузки расписания для локации {location}.\n"
                         "Попробуйте позже или выберите другую локацию.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Назад", callback_data="back_to_dates")],
                        [InlineKeyboardButton("📞 Связаться с администратором", url=ADMIN_CONTACT_URL)]
                    ])
                )
            except Exception as edit_error:
                logging.warning(f"Не удалось отредактировать сообщение поиска: {edit_error}")
                # Fallback - отправляем новое сообщение и удаляем старое
                await context.bot.send_message(
                    chat_id=q.message.chat_id,
                    text=f"❌ Ошибка загрузки расписания для локации {location}.\n"
                         "Попробуйте позже или выберите другую локацию.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Назад", callback_data="back_to_dates")],
                        [InlineKeyboardButton("📞 Связаться с администратором", url=ADMIN_CONTACT_URL)]
                    ])
                )
                try:
                    await search_msg.delete()
                except Exception:
                    pass
            return ASK_DATE
        
        row = []
        for cab, beg, end_time in slots:
            if beg not in seen:
                # Добавляем слот только если он еще не был добавлен
                seen.add(beg)
                # Каждая кнопка теперь будет в своем собственном ряду для отображения в одном столбце
                reply_markup.append([InlineKeyboardButton(beg, callback_data=f"time_{beg}")])
        # Убрал if row: reply_markup.append(row) так как кнопки добавляются по одной

    if not reply_markup:
        # Если после всех проверок не найдено ни одного свободного слота
        logging.info("⚠️ No available slots found after checking both systems")
        # Редактируем сообщение поиска для показа ошибки
        try:
            await search_msg.edit_text(
                text="К сожалению, на выбранную дату нет свободных слотов. Пожалуйста, выберите другую дату, перенесите запись или свяжитесь с администратором.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Назад", callback_data="back_to_dates")],
                    [InlineKeyboardButton("🔁 Перенести запись", callback_data="reschedule")],
                    [InlineKeyboardButton("📞 Связаться с администратором", callback_data="call_admin")]
                ])
            )
        except Exception as e:
            logging.warning(f"Не удалось отредактировать сообщение поиска: {e}")
            # Fallback - отправляем новое сообщение и удаляем старое
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="К сожалению, на выбранную дату нет свободных слотов. Пожалуйста, выберите другую дату, перенесите запись или свяжитесь с администратором.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Назад", callback_data="back_to_dates")],
                    [InlineKeyboardButton("🔁 Перенести запись", callback_data="reschedule")],
                    [InlineKeyboardButton("📞 Связаться с администратором", callback_data="call_admin")]
                ])
            )
            try:
                await search_msg.delete()
            except Exception:
                pass
        return ASK_DATE
    
    # Добавляем кнопки "Назад" и "Связаться с администратором" в конец списка
    reply_markup.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_dates")])
    reply_markup.append([InlineKeyboardButton("📞 Связаться с администратором", url=ADMIN_CONTACT_URL)])

    # Редактируем сообщение поиска вместо создания нового
    try:
        await search_msg.edit_text(
            text="Выберите удобное время:",
            reply_markup=InlineKeyboardMarkup(reply_markup)
        )
    except Exception as e:
        logging.warning(f"Не удалось отредактировать сообщение поиска: {e}")
        # Fallback - отправляем новое сообщение
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text="Выберите удобное время:",
            reply_markup=InlineKeyboardMarkup(reply_markup)
        )
    return ASK_TIME # Переход в состояние выбора времени

# Обработчик выбора времени
async def handle_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer() # Отправляем подтверждение о получении колбэка
    time_selected = q.data.replace("time_", "")
    context.user_data["time"] = time_selected # Сохраняем выбранное время
    
    # Показываем сообщение обработки
    processing_msg = await q.message.reply_text("⏳ Подождите, создаём вашу запись...")
    
    # Удаляем кнопки выбора времени из чата
    try:
        await q.delete_message()
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение с временами: {e}")
    
    user = q.from_user
    date_text = context.user_data["date"]
    location = context.user_data["location"]

    # Определяем тип клиента (новый или повторный)
    client_type_info = ""
    if context.user_data.get('scenario') == "scenario_repeat":
        client_type_info = "🔁 Повторный клиент хочет записаться:\n"
    else:
        client_type_info = "📌 Новый клиент хочет записаться:\n"

    # --- ДОБАВЛЕНИЕ В appointments.json ---
    try:
        appointments = load_appointments()
        booking_id = str(uuid.uuid4())
        booking_obj = {
            "user_id": str(user.id),
            "username": user.username or "—",
            "date": date_text,
            "time": time_selected,
            "location": location,
            "booking_id": booking_id,
            "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        appointments.append(booking_obj)
        save_appointments(appointments)
        logging.info(f"✅ Booking saved to appointments.json: {booking_obj}")
    except Exception as e:
        logging.error(f"❌ Failed to save booking to appointments.json: {e}")

    # Отправляем сообщение администратору с деталями записи (без ID)
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=(
            f"{client_type_info}"
            f"👤 {user.full_name} (@{user.username or '—'})\n"
            f"🆔 user_id: {user.id}\n"
            f"📅 Дата: {date_text}\n"
            f"⏰ Время: {time_selected}\n"
            f"📍 Локация: {get_localized_location_name(location)}\n"
            f"🏠 Адрес: {get_location_address(location)}"
        )
    )

    # Удаляем сообщение обработки
    try:
        await processing_msg.delete()
    except Exception as e:
        logging.warning(f"Не удалось удалить сообщение обработки: {e}")
    
    # Получаем информацию о локации
    location_name = get_localized_location_name(location)
    location_address = get_location_address(location)
    
    # Формируем подробное сообщение с информацией о записи и инструкциями по оплате
    message_text = (
        f"🔍 Подтверждение записи!\n\n"
        f"📅 Дата: {date_text}\n"
        f"⏰ Время: {time_selected}\n"
        f"📍 Локация: {location_name}\n"
        f"🏢 Адрес: {location_address}\n\n"
        f"💳 Для завершения резервации, пожалуйста, переведите 1200₽ по номеру\n"
        f"+7 (925) 780-62-03 на Т-Банк — это необходимо для оплаты брони кабинета.\n"
        f"В комментарии к переводу укажите \"возврат долга\".\n\n"
        f"❗️ В случае отмены или переноса записи возможен лишь частичный возврат денежных средств, согласно правилам арендодателя.\n"
        f"Для возврата свяжитесь с администратором.\n\n"
        f"📎 После оплаты отправьте, пожалуйста, в этот чат файл или скриншот, подтверждающий перевод"
    )
    
    # Отправляем подробное сообщение с инструкциями
    await context.bot.send_message(
        chat_id=q.message.chat_id,
        text=message_text,
        reply_markup=admin_button(),
        parse_mode=ParseMode.MARKDOWN
    )
    return HANDLE_SCREENSHOT

# Обработчик файлов подтверждения оплаты (любые типы файлов)
async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    file = None
    file_type_name = ""
    
    # Определяем тип файла и получаем объект файла
    if update.message.document:
        file = update.message.document
        file_type_name = "документ"
        logging.info(f"📄 Received document from {user.username or user.full_name}: {file.file_name}")
    elif update.message.photo:
        file = update.message.photo[-1]  # Самое большое изображение
        file_type_name = "фото"
        logging.info(f"🖼️ Received photo from {user.username or user.full_name}")
    else:
        # Если пришло что-то другое (не документ и не фото)
        await update.message.reply_text(
            "❌ Пожалуйста, отправьте файл в виде документа или фото.",
            reply_markup=MAIN_MENU_KEYBOARD
        )
        return CHOOSING_SCENARIO

    # Проверяем размер файла (максимум 1 МБ = 1048576 байт)
    if file.file_size and file.file_size > 1048576:
        await update.message.reply_text(
            "⚠️ Файл слишком большой. Пожалуйста, отправьте файл размером не более 1 МБ.",
            reply_markup=MAIN_MENU_KEYBOARD
        )
        return CHOOSING_SCENARIO

    # Формируем подпись для админа
    file_name = getattr(file, 'file_name', 'файл')
    caption_text = f"💳 Подтверждение оплаты от {user.full_name} (@{user.username or '—'})\n📎 {file_type_name.title()}: {file_name}"

    # Пересылаем файл администратору
    try:
        if update.message.photo:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=file.file_id,
                caption=caption_text
            )
        elif update.message.document:
            await context.bot.send_document(
                chat_id=ADMIN_CHAT_ID,
                document=file.file_id,
                caption=caption_text
            )
        logging.info(f"✅ Payment proof forwarded to admin: {file_type_name} from {user.username or user.full_name}")
    except Exception as e:
        logging.error(f"❌ Failed to forward payment proof to admin: {e}", exc_info=True)
        await update.message.reply_text(
            "Произошла ошибка при отправке подтверждения администратору. Пожалуйста, попробуйте еще раз или свяжитесь с администратором.",
            reply_markup=MAIN_MENU_KEYBOARD
        )
        return CHOOSING_SCENARIO

    # Отправляем персонализированное подтверждение резервации
    confirmation_message = generate_reservation_confirmation(context)
    await update.message.reply_text(
        confirmation_message,
        reply_markup=MAIN_MENU_KEYBOARD
    )
    
    # Очищаем данные пользователя после завершения бронирования
    context.user_data.clear()
    
    return CHOOSING_SCENARIO

# Обработчик команды /menu для принудительного возврата в главное меню
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно возвращает пользователя в главное меню"""
    # Очищаем все данные пользователя
    context.user_data.clear()
    
    if update.message:
        # Показываем клавиатуру через send_message
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Главное меню:",
            reply_markup=MAIN_MENU_KEYBOARD
        )
    elif update.callback_query:
        await update.callback_query.answer()
        # Показываем клавиатуру через send_message
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Главное меню:",
            reply_markup=MAIN_MENU_KEYBOARD
        )
    return CHOOSING_SCENARIO

# Обработчик команды для вызова администратора
async def call_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Чтобы связаться с администратором, нажмите на кнопку ниже:"
    if update.message:
        await update.message.reply_text(text, reply_markup=admin_button())
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=admin_button())
    return ConversationHandler.END

# Обработчик команды для переноса записи
async def reschedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=(
            f"🔁 Клиент хочет перенести запись (через /reschedule):\n"
            f"👤 {user.full_name} (@{user.username or '—'})\n"
            f"🆔 user_id: {user.id}"
        )
    )
    # Clear previous booking data except for scenario
    context.user_data.clear()
    context.user_data['scenario'] = "scenario_repeat"
    context.user_data['date_offset'] = 0
    # Show the original date selection UI
    await offer_dates(update, context)
    return ASK_DATE

# Function to ask for cancellation confirmation
async def ask_cancel_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Вы уверены, что хотите отменить запись? (да/нет)",
            reply_markup=CONFIRM_KEYBOARD
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "Вы уверены, что хотите отменить запись? (да/нет)",
            reply_markup=CONFIRM_KEYBOARD
        )
    return CONFIRM_CANCEL

# Global /cancel handler for outside ConversationHandler
async def global_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Mimic the '❌ Отменить запись' button by calling main_menu_handler with the same text
    class FakeMessage:
        def __init__(self, orig):
            self.__dict__.update(orig.__dict__)
            self.text = "❌ Отменить запись"
    fake_update = update
    fake_update.message = FakeMessage(update.message)
    return await main_menu_handler(fake_update, context)

# Обработчик команды для вызова главной меню
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logging.info(f"DEBUG: main_menu_handler triggered with text: {text}")
    context.user_data['notified_chat_closed'] = False
    if text == "🆕 Новая запись":
        context.user_data['scenario'] = "scenario_new"
        context.user_data['form'] = []
        context.user_data['form_q'] = 0
        context.user_data['date_offset'] = 0
        await update.message.reply_text(FORM_QUESTIONS[0], reply_markup=ReplyKeyboardRemove())
        return FORM_Q
    elif text == "🔁 Повторная запись":
        context.user_data['scenario'] = "scenario_repeat"
        context.user_data['date_offset'] = 0
        await offer_dates(update, context)
        return ASK_DATE
    elif text == "📋 Мои записи":
        user = update.effective_user
        appointments = load_appointments()
        user_bookings = [a for a in appointments if a.get("user_id") == str(user.id)]
        if not user_bookings:
            await update.message.reply_text("У вас нет активных записей.", reply_markup=MAIN_MENU_KEYBOARD)
            return CHOOSING_SCENARIO
        for i, booking in enumerate(user_bookings):
            address = get_location_address(booking['location'])
            text = (
                f"📅 <b>Дата:</b> {booking['date']}\n"
                f"⏰ <b>Время:</b> {booking['time']}\n"
                f"📍 <b>Локация:</b> {get_localized_location_name(booking['location'])}"
            )
            if address:
                text += f"\n🏠 <b>Адрес:</b> {address}"
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Перенести запись", callback_data=f"ask_reschedule_{booking['booking_id']}"),
                    InlineKeyboardButton("Отменить запись", callback_data=f"ask_cancel_{booking['booking_id']}")
                ]
            ])
            
            # Отправляем каждую запись
            await update.message.reply_text(text, reply_markup=buttons, parse_mode="HTML")
        
        # После всех записей отправляем главное меню отдельным сообщением
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📋 Ваши записи выше. Выберите действие:",
            reply_markup=MAIN_MENU_KEYBOARD
        )
        return CHOOSING_SCENARIO
    elif text == "📞 Связаться с администратором":
        return await call_admin_command(update, context)
    else:
        # Не отправляем сообщение, просто возвращаем состояние
        return CHOOSING_SCENARIO

# Confirmation handlers
async def confirm_reschedule_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip().lower()
    logging.info(f"confirm_reschedule_handler triggered, answer: {answer}, user_id: {update.effective_user.id}")
    if answer == "да":
        # Remove confirmation keyboard when proceeding
        await update.message.reply_text("Перенос записи подтверждён.", reply_markup=ReplyKeyboardRemove())
        return await reschedule_command(update, context)
    else:
        await update.message.reply_text("Перенос записи отменён.", reply_markup=MAIN_MENU_KEYBOARD)
        return CHOOSING_SCENARIO

async def confirm_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip().lower()
    logging.info(f"confirm_cancel_handler triggered, answer: {answer}, user_id: {update.effective_user.id}")
    if answer == "да":
        user = update.effective_user
        date = context.user_data.get('date', '—')
        time = context.user_data.get('time', '—')
        location = context.user_data.get('location', '—')
        scenario = context.user_data.get('scenario', '—')
        booking_id = context.user_data.get('booking_id', '—') # Get booking_id for cancellation
        # Notify admin
        try:
            logging.info(f"Notifying admin about cancellation for user_id={user.id}")
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=(
                    f"❌ Клиент отменил запись!\n"
                    f"👤 {user.full_name} (@{user.username or '—'})\n"
                    f"🆔 user_id: {user.id}\n"
                    f"Тип: {'Повторная' if scenario == 'scenario_repeat' else 'Новая'} запись\n"
                    f"Дата: {date}\n"
                    f"Время: {time}\n"
                    f"Локация: {get_localized_location_name(location)}\n"
                    f"Адрес: {get_location_address(location)}\n"
                    f"ID записи: {booking_id}"
                )
            )
            logging.info(f"Admin notified about cancellation for user_id={user.id}")
        except Exception as e:
            logging.error(f"Failed to notify admin about cancellation: {e}")
        # Remove the confirmation keyboard
        await update.message.reply_text(
            "Ваша запись отменена. Администратор получил уведомление.",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.clear()
        # Show the main menu
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Главное меню:",
            reply_markup=MAIN_MENU_KEYBOARD
        )
        return CHOOSING_SCENARIO
    else:
        await update.message.reply_text("Отмена записи отменена.", reply_markup=MAIN_MENU_KEYBOARD)
        return CHOOSING_SCENARIO

# Inline button confirmation for reschedule
async def inline_reschedule_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data['pending_action'] = 'reschedule'
    await q.message.reply_text("Вы уверены, что хотите перенести запись? (да/нет)", reply_markup=CONFIRM_KEYBOARD)
    return CONFIRM_RESCHEDULE

# Inline button confirmation for cancel
async def inline_cancel_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data['pending_action'] = 'cancel'
    await q.message.reply_text("Вы уверены, что хотите отменить запись? (да/нет)", reply_markup=CONFIRM_KEYBOARD)
    return CONFIRM_CANCEL

# --- Подтверждение для отмены/переноса ---
async def confirm_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith('confirm_cancel_'):
        booking_id = data.replace('confirm_cancel_', '')
        # Запустить отмену
        await cancel_booking_handler(update, context, booking_id=booking_id, confirmed=True)
        return CHOOSING_SCENARIO
    elif data.startswith('confirm_reschedule_'):
        booking_id = data.replace('confirm_reschedule_', '')
        context.user_data['mode'] = 'reschedule'
        context.user_data['reschedule_booking_id'] = booking_id
        context.user_data['reschedule_date_offset'] = 0
        await reschedule_booking_handler(update, context, booking_id=booking_id, confirmed=True)
        return RESCHEDULE_DATE
    elif data == 'cancel_action':
        await q.message.reply_text("Действие отменено. Возвращаюсь в главное меню.", reply_markup=MAIN_MENU_KEYBOARD)
        return CHOOSING_SCENARIO

# --- Модификация инлайн-кнопок для отмены/переноса ---
# В main_menu_handler:
#   InlineKeyboardButton("Перенести запись", callback_data=f"ask_reschedule_{booking['booking_id']}")
#   InlineKeyboardButton("Отменить запись", callback_data=f"ask_cancel_{booking['booking_id']}")

# --- Новый handler для ask_reschedule_ и ask_cancel_ ---
async def ask_confirm_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith('ask_cancel_'):
        booking_id = data.replace('ask_cancel_', '')
        buttons = [
            [InlineKeyboardButton("✅ Да", callback_data=f"confirm_cancel_{booking_id}"),
             InlineKeyboardButton("❌ Нет", callback_data="cancel_action")]
        ]
        await q.edit_message_text("❓ Вы уверены, что хотите отменить запись?", reply_markup=InlineKeyboardMarkup(buttons))
    elif data.startswith('ask_reschedule_'):
        booking_id = data.replace('ask_reschedule_', '')
        buttons = [
            [InlineKeyboardButton("✅ Да", callback_data=f"confirm_reschedule_{booking_id}"),
             InlineKeyboardButton("❌ Нет", callback_data="cancel_action")]
        ]
        await q.edit_message_text("❓ Вы уверены, что хотите перенести запись?", reply_markup=InlineKeyboardMarkup(buttons))

# --- Изменить main_menu_handler: инлайн-кнопки для записей ---
# Вместо callback_data=f"reschedule_{booking['booking_id']}" и f"cancel_{booking['booking_id']}"
# теперь f"ask_reschedule_{booking['booking_id']}" и f"ask_cancel_{booking['booking_id']}"

# --- Изменить ConversationHandler: добавить CallbackQueryHandler(ask_confirm_action, pattern="^ask_(cancel|reschedule)_") и CallbackQueryHandler(confirm_action_handler, pattern="^(confirm_cancel_|confirm_reschedule_|cancel_action)")

# --- Изменить cancel_booking_handler и reschedule_booking_handler: принимать booking_id и confirmed, если confirmed=False — не выполнять действие, а только через подтверждение ---

# --- Relay admin replies to user ---
async def relay_admin_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return
    relay_user_id = context.bot_data.get('relay_user_id')
    if not context.bot_data.get('relay_active') or not relay_user_id:
        await update.message.reply_text("Чат с клиентом завершён. Чтобы начать новый, дождитесь нового запроса от клиента.")
        return
    if update.message.text and update.message.text.strip() == '/endchat':
        await end_chat(update, context, from_admin=True)
        return
    if update.message.text:
        await context.bot.send_message(
            chat_id=relay_user_id,
            text=f"💬 Сообщение от администратора:\n{update.message.text}"
        )
    elif update.message.photo:
        await context.bot.send_photo(
            chat_id=relay_user_id,
            photo=update.message.photo[-1].file_id,
            caption="🖼️ Фото от администратора"
        )
    elif update.message.document:
        await context.bot.send_document(
            chat_id=relay_user_id,
            document=update.message.document.file_id,
            caption="📄 Документ от администратора"
        )

# --- End chat relay and show menu ---
async def end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, from_admin=None):
    if from_admin is None:
        from_admin = (update.effective_user.id == ADMIN_CHAT_ID)
    relay_user_id = context.bot_data.get('relay_user_id')
    logging.info(f"DEBUG: end_chat called by {'admin' if from_admin else 'user'}, relay_user_id={relay_user_id}")
    context.bot_data['relay_active'] = False
    context.bot_data['relay_user_id'] = None
    if from_admin:
        if relay_user_id:
            await context.bot.send_message(
                chat_id=relay_user_id,
                text="Чат с администратором завершён.",
                reply_markup=MAIN_MENU_KEYBOARD
            )
        await update.message.reply_text("Чат с клиентом завершён.")
    else:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text="Клиент завершил чат."
        )
        await update.message.reply_text(
            "Чат с администратором завершён.",
            reply_markup=MAIN_MENU_KEYBOARD
        )

async def handle_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['date_offset'] = 0
    return await start(update, context)

# --- Relay user messages to admin ---
async def relay_user_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    relay_user_id = context.bot_data.get('relay_user_id')
    relay_active = context.bot_data.get('relay_active')
    if not relay_active or relay_user_id != update.effective_user.id:
        return
    if update.message.text and update.message.text.strip() == '/endchat':
        await end_chat(update, context, from_admin=False)
        return
    if update.message.text:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=f"💬 Сообщение от клиента:\n{update.message.text}"
        )
    elif update.message.photo:
        await context.bot.send_photo(
            chat_id=ADMIN_USER_ID,
            photo=update.message.photo[-1].file_id,
            caption="🖼️ Фото от клиента"
        )
    elif update.message.document:
        await context.bot.send_document(
            chat_id=ADMIN_USER_ID,
            document=update.message.document.file_id,
            caption="📄 Документ от клиента"
        )

async def getchatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"Chat ID: {chat.id}")

# --- Единый шаблон подтверждения для клиента ---
def confirm_booking_message(date, time, location):
    localized_location = get_localized_location_name(location)
    address = get_location_address(location)
    
    message = (
        f"✅ Ваша запись подтверждена!\n"
        f"📅 Дата: {date}\n"
        f"⏰ Время: {time}\n"
        f"📍 Локация: {localized_location}"
    )
    
    if address:
        message += f"\n🏠 Адрес: {address}"
    
    return message

# --- Персонализированное сообщение подтверждения резервации ---
def generate_reservation_confirmation(context):
    """Генерирует подробное сообщение подтверждения резервации с инструкциями по доступу"""
    date = context.user_data.get('date', '—')
    time = context.user_data.get('time', '—')
    location = context.user_data.get('location', '')
    
    # Получаем базовую информацию о локации
    localized_location = get_localized_location_name(location)
    address = get_location_address(location)
    
    # Получаем подробную информацию
    details = LOCATION_DETAILS.get(location, {})
    
    # Формируем основную часть сообщения
    message = (
        f"✅ Ваша запись успешно создана!\n\n"
        f"📅 Дата: {date}\n"
        f"⏰ Время: {time}\n"
        f"📍 Локация: {details.get('alias', localized_location)}\n"
        f"🏢 Адрес: {address}\n"
    )
    
    # Добавляем информацию о кабинете
    if 'cabinet' in details:
        message += f"🏛 Кабинет: {details['cabinet']}\n"
    
    # Добавляем код домофона (если есть)
    if 'domofon' in details:
        message += f"🔑 Код уличного домофона: {details['domofon']}\n"
    
    # Добавляем PIN-код для входа
    if 'pin' in details:
        message += f"🔐 PIN-код для входа: {details['pin']}\n"
    
    # Добавляем инструкции по поиску
    if 'how_to_find' in details:
        message += f"\n📌 Как найти:\n{details['how_to_find']}\n"
    
    return message

# Главная функция для запуска бота
def main():
    # Создание экземпляра приложения бота с увеличенными тайм-аутами
    from telegram.request import HTTPXRequest
    from telegram.ext import filters
    
    # Настройка HTTP-клиента с увеличенными тайм-аутами
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=20.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=10.0
    )
    
    app = Application.builder().token(BOT_TOKEN).request(request).build()
    
    # Add global handler for '❌ Отменить запись' button (handled by ConversationHandler state)
    # app.add_handler(MessageHandler(filters.Regex("^❌ Отменить запись$"), main_menu_handler))
    
    # Добавляем обработчики для команд меню вне ConversationHandler
    # ВАЖНО: CommandHandler для /start должен быть ВНЕ ConversationHandler, 
    # чтобы работать даже после удаления чата
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(MessageHandler(filters.Chat(ADMIN_CHAT_ID) & ~filters.COMMAND, relay_admin_to_user))
    app.add_handler(CallbackQueryHandler(call_admin_command, pattern="^call_admin$"))
    
    # Определение ConversationHandler для управления диалогом
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^(🆕 Новая запись|🔁 Повторная запись|📋 Мои записи|📞 Связаться с администратором)$"), main_menu_handler)
        ],
        states={
            # Состояние выбора сценария (новая/повторная запись)
            CHOOSING_SCENARIO: [
                CommandHandler("menu", menu_command),
                MessageHandler(filters.Regex("^(🆕 Новая запись|🔁 Повторная запись|📋 Мои записи|📞 Связаться с администратором)$"), main_menu_handler),
                CallbackQueryHandler(ask_confirm_action, pattern="^ask_(cancel|reschedule)_"),
                CallbackQueryHandler(confirm_action_handler, pattern="^(confirm_cancel_|confirm_reschedule_|cancel_action)"),
                CallbackQueryHandler(cancel_booking_handler, pattern="^cancel_"),
                CallbackQueryHandler(reschedule_booking_handler, pattern="^reschedule_"),
                CallbackQueryHandler(handle_scenario, pattern="^scenario_")
            ],
            # Состояние заполнения анкеты (ожидаем текстовый ответ)
            FORM_Q: [
                CommandHandler("menu", menu_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_form)
            ],
            # Состояние выбора даты
            ASK_DATE: [
                CommandHandler("menu", menu_command),
                CallbackQueryHandler(handle_date_selection, pattern="^date_"),
                CallbackQueryHandler(handle_more_dates, pattern="^next_dates$"),
                CallbackQueryHandler(handle_prev_dates, pattern="^prev_dates$"),
                CallbackQueryHandler(handle_restart, pattern="^restart$"),
                CallbackQueryHandler(offer_dates, pattern="^back_to_dates$"),
                MessageHandler(filters.TEXT, handle_date_selection)
            ],
            # Состояние выбора локации
            ASK_LOCATION: [
                CommandHandler("menu", menu_command),
                CallbackQueryHandler(handle_location, pattern="^loc_"),
                CallbackQueryHandler(offer_dates, pattern="^back_to_dates$")
            ],
            # Состояние выбора времени
            ASK_TIME: [
                CommandHandler("menu", menu_command),
                CallbackQueryHandler(handle_time, pattern="^time_"),
                CallbackQueryHandler(show_location_selection, pattern="^back_to_dates$")
            ],
            # Состояние ожидания файла подтверждения оплаты
            HANDLE_SCREENSHOT: [
                CommandHandler("menu", menu_command),
                MessageHandler(filters.PHOTO | filters.Document.ALL, handle_screenshot)
            ],
            CONFIRM_RESCHEDULE: [
                CommandHandler("menu", menu_command),
                MessageHandler(filters.Regex("^(да|нет)$"), confirm_reschedule_handler)
            ],
            CONFIRM_CANCEL: [
                CommandHandler("menu", menu_command),
                MessageHandler(filters.Regex("^(да|нет)$"), confirm_cancel_handler)
            ],
            RESCHEDULE_DATE: [
                CommandHandler("menu", menu_command),
                CallbackQueryHandler(reschedule_date_handler, pattern="^reschedule_date_"),
                CallbackQueryHandler(reschedule_more_dates_handler, pattern="^reschedule_next_dates$"),
                CallbackQueryHandler(reschedule_prev_dates_handler, pattern="^reschedule_prev_dates$"),
                CallbackQueryHandler(reschedule_cancel, pattern="^reschedule_back$")
            ],
            RESCHEDULE_TIME: [
                CommandHandler("menu", menu_command),
                CallbackQueryHandler(reschedule_time_handler, pattern="^reschedule_time_"),
                CallbackQueryHandler(reschedule_location_handler, pattern="^reschedule_loc_"),
                CallbackQueryHandler(reschedule_back_to_dates, pattern="^reschedule_back$"),
                CallbackQueryHandler(reschedule_show_dates, pattern="^reschedule_back_to_dates_from_no_slots$"),
                CallbackQueryHandler(reschedule_cancel, pattern="^reschedule_cancel$")
            ],
        },
        fallbacks=[
            CommandHandler("start", start),  # /start в любом состоянии сбрасывает FSM
            CommandHandler("menu", menu_command)  # /menu тоже сбрасывает FSM
        ],
        per_message=False  # Отключаем отслеживание per_message для CallbackQueryHandler
    )
    
    app.add_handler(conv) # Добавляем ConversationHandler в приложение
    # Add relay_user_to_admin handler for user chat relay (after ConversationHandler)
    app.add_handler(MessageHandler(
        filters.ALL & ~filters.Chat(ADMIN_CHAT_ID) & ~filters.COMMAND,
        relay_user_to_admin
    ))
    logging.info("🤖 Бот запущен.") # Логируем запуск бота
    app.run_polling() # Запускаем опрос обновлений от Telegram

# Запуск бота при выполнении файла
if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logging.exception("❌ Ошибка при запуске бота") # Логируем ошибки при запуске

