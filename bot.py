import os
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler, ConversationHandler
)
from scraper_selenium import run_scraper  # Импорт функции скрапера

# Загружаем переменные из .env файла
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")  # Webhook для отправки в Google Sheets
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))  # ID администратора

# Список вопросов для анкеты
questions = [
    "Ваше Имя?",
    "Ваш возраст?",
    "Что болит?",
    "Как давно болит?",
    "Как боль появилась?",
    "Что уменьшает боль?",
    "В каких положениях боль сильнее/слабее?",
    "Как сейчас решаете проблему с болью?",
    "Обращались раньше с этой проблемой?",
    "Какие обследования уже делали и результаты?",
    "Есть ли хронические, онко- или другие заболевания?"
]

# Переменные состояний для ConversationHandler
(
    NAME, AGE, PAIN, DURATION, CAUSE, RELIEF, POSITION, SOLUTION,
    HISTORY, EXAMS, CHRONIC, CHOOSE_LOCATION, CHOOSE_DATE, CHOOSE_TIME
) = range(14)

# Сохраняем сессии клиентов, если нужно связать с админом
client_sessions = {}

# Начало опроса
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['answers'] = []
    await update.message.reply_text(questions[0])
    return NAME

# Универсальный обработчик вопросов
async def collect_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q_index = len(context.user_data['answers'])
    context.user_data['answers'].append(update.message.text)
    if q_index + 1 < len(questions):
        await update.message.reply_text(questions[q_index + 1])
        return q_index + 1
    else:
        # Переход к выбору локации после анкеты
        keyboard = [
            [InlineKeyboardButton("Новослободская", callback_data="loc_novoslobodskaya")],
            [InlineKeyboardButton("Серпуховская", callback_data="loc_serpukhovskaya")],
            [InlineKeyboardButton("Сокольники", callback_data="loc_sokolniki")]
        ]
        await update.message.reply_text("Выберите локацию:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSE_LOCATION

# Пользователь выбрал локацию
async def choose_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["location"] = query.data.replace("loc_", "")
    await query.edit_message_text("Введите дату приёма (формат YYYY-MM-DD):")
    return CHOOSE_DATE

# Пользователь ввёл дату
async def choose_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["date"] = update.message.text
    # Кнопки с интервалами
    keyboard = [
        [InlineKeyboardButton("08:00-12:00", callback_data="t_08:00-12:00")],
        [InlineKeyboardButton("12:00-16:00", callback_data="t_12:00-16:00")],
        [InlineKeyboardButton("16:00-20:00", callback_data="t_16:00-20:00")],
        [InlineKeyboardButton("20:00-22:00", callback_data="t_20:00-22:00")],
    ]
    await update.message.reply_text("Выберите удобный интервал времени:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSE_TIME

# Пользователь выбрал время — вызываем скрапер и сохраняем в Google Sheets
async def choose_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    interval = query.data.replace("t_", "")
    start_time, end_time = interval.split("-")
    context.user_data["start_time"] = start_time
    context.user_data["end_time"] = end_time
    location = context.user_data["location"]
    date = context.user_data["date"]

    await query.edit_message_text(f"🔍 Проверяю доступность на {location}, {date} {start_time}-{end_time}...")

    # Вызов Selenium-скрапера
    result = run_scraper(location, date, start_time, end_time)
    if not result:
        # Нет доступных слотов — повторить выбор
        keyboard = [
            [InlineKeyboardButton("08:00-12:00", callback_data="t_08:00-12:00")],
            [InlineKeyboardButton("12:00-16:00", callback_data="t_12:00-16:00")],
            [InlineKeyboardButton("16:00-20:00", callback_data="t_16:00-20:00")],
            [InlineKeyboardButton("20:00-22:00", callback_data="t_20:00-22:00")],
        ]
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Нет доступных слотов в выбранном интервале. Пожалуйста, выберите другой интервал:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSE_TIME

    text = "\n".join(result)
    await context.bot.send_message(chat_id=query.message.chat_id, text=text)

    # Отправка всей анкеты в Google Sheets через webhook
    payload = {
        "chat_id": query.message.chat_id,
        "username": query.from_user.username,
        "answers": context.user_data['answers'],
        "location": location,
        "date": date,
        "start_time": start_time,
        "end_time": end_time
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print("⚠️ Ошибка при отправке в webhook:", e)

    # Если последний ответ содержит "нет" — подходит
    answer_11 = context.user_data['answers'][10].lower()
    if any(x in answer_11 for x in ["нет", "не", "отриц"]):
        await context.bot.send_message(chat_id=query.message.chat_id,
                                       text="✅ Вы подходите для терапии. Выберите удобный слот из предложенных.")
    else:
        await context.bot.send_message(chat_id=query.message.chat_id,
                                       text="Спасибо за ответы! Вас проконсультирует администратор.")
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"Клиент @{query.from_user.username or query.from_user.id} нуждается в консультации.\n" +
                 "\n".join([f"{i+1}. {q} {a}" for i, (q, a) in enumerate(zip(questions, context.user_data['answers']))]) +
                 f"\nЛокация: {location}, Дата: {date}, Время: {start_time}-{end_time}"
        )

    context.user_data.clear()
    return ConversationHandler.END

# Команда /reply от администратора для ответа клиенту
async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Формат: /reply <client_chat_id> <текст>")
        return
    try:
        chat_id = int(context.args[0])
        msg = " ".join(context.args[1:])
        await context.bot.send_message(chat_id=chat_id, text=f"📩 Админ:\n{msg}")
        await update.message.reply_text("✅ Отправлено клиенту.")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")

# Основной запуск Telegram-бота
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            PAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            CAUSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            RELIEF: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            SOLUTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            HISTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            EXAMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            CHRONIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answer)],
            CHOOSE_LOCATION: [CallbackQueryHandler(choose_location, pattern="^loc_")],
            CHOOSE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_date)],
            CHOOSE_TIME: [CallbackQueryHandler(choose_time, pattern="^t_")]
        },
        fallbacks=[],
        per_chat=True
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("reply", admin_reply))
    app.run_polling()

if __name__ == "__main__":
    main()
