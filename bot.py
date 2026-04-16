import logging
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import psycopg2

API_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Клавиатура (без кнопки "Добавить товар" — товары вводятся текстом)
kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💳 Внести оплату")],
        [KeyboardButton(text="💰 Мой долг"), KeyboardButton(text="📜 История")]
    ],
    resize_keyboard=True
)

# === РАБОТА С БАЗОЙ ===
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS storage (id SERIAL PRIMARY KEY, debt FLOAT DEFAULT 0);
                CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, entry TEXT, created_at TIMESTAMP DEFAULT NOW());
            """)
            cur.execute("INSERT INTO storage (debt) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM storage)")
        conn.commit()

def get_debt():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT debt FROM storage LIMIT 1")
            return cur.fetchone()[0]

def update_debt(amount):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE storage SET debt = debt + %s", (amount,))
        conn.commit()

def add_history(entry):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO history (entry) VALUES (%s)", (entry,))
        conn.commit()

def get_history():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT entry FROM history ORDER BY created_at DESC LIMIT 20")
            return [row[0] for row in cur.fetchall()]

def reset_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE storage SET debt = 0")
            cur.execute("DELETE FROM history")
        conn.commit()

# === ОБРАБОТЧИКИ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debt = get_debt()
    await update.message.reply_text(
        f"✅ Бот запущен!\nТекущий долг: {debt} грн\n\n"
        "📌 Отправь список товаров в формате:\n"
        "Название количество*цена\n"
        "Например:\n"
        "Фасовка 80*90\n"
        "Кофе 2500*0.80\n"
        "Майка 38 40*38",
        reply_markup=kb
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_data = context.user_data

    # === ОПЛАТА ===
    if text == "💳 Внести оплату":
        user_data.clear()
        user_data["mode"] = "pay"
        await update.message.reply_text("Введите сумму оплаты (число):")
        return

    # === ДОЛГ ===
    if text == "💰 Мой долг":
        debt = get_debt()
        await update.message.reply_text(f"💰 Текущий долг: {debt} грн")
        return

    # === ИСТОРИЯ ===
    if text == "📜 История":
        history = get_history()
        if history:
            await update.message.reply_text("📜 История:\n" + "\n".join(history))
        else:
            await update.message.reply_text("📜 История пуста.")
        return

    # === РЕЖИМ ОПЛАТЫ ===
    if user_data.get("mode") == "pay":
        try:
            val = float(text.replace(',', '.').replace(' ', ''))
            update_debt(-val)
            add_history(f"{datetime.now().strftime('%d.%m')} 💳 Оплата: -{val}")
            debt = get_debt()
            await update.message.reply_text(
                f"✅ Принято {val} грн.\n"
                f"💰 Сумма оплаты: {val} грн\n"
                f"📋 Остаток долга: {debt} грн"
            )
        except:
            await update.message.reply_text("❌ Введите число (например, 500).")
        finally:
            user_data.clear()
        return

    # === ОСНОВНОЙ РЕЖИМ: ПАРСИНГ ТОВАРОВ (ФОРМАТ "Название кол-во*цена") ===
    lines = text.split('\n')
    items = []
    total = 0.0
    result_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.rsplit(' ', 1)
        if len(parts) != 2:
            await update.message.reply_text(f"❌ Ошибка в строке: {line}\nФормат: Название количество*цена")
            return
        name = parts[0]
        try:
            qty_str, price_str = parts[1].split('*')
            qty = float(qty_str.replace(',', '.'))
            price = float(price_str.replace(',', '.'))
            summ = round(qty * price, 2)
            total += summ
            items.append((name, qty, price, summ))
            result_lines.append(f"- {name}: {qty} x {price} = {summ}")
        except:
            await update.message.reply_text(f"❌ Ошибка в строке: {line}\nНужно: количество*цена (например, 80*90)")
            return

    if not items:
        await update.message.reply_text("❌ Не найдено ни одной позиции. Отправьте список в формате:\nНазвание количество*цена")
        return

    # Сохраняем в долг и историю
    update_debt(total)
    add_history(f"{datetime.now().strftime('%d.%m')} ➕ Товары: +{total} грн")
    new_debt = get_debt()

    response = (
        "➕ Добавлено:\n" + "\n".join(result_lines) +
        f"\n\n💰 Сумма чека: {total} грн" +
        f"\n📋 Итого долг: {new_debt} грн"
    )
    await update.message.reply_text(response, reply_markup=kb)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_db()
    await update.message.reply_text("🗑 Все данные (долг и история) удалены.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}", exc_info=True)
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ Произошла внутренняя ошибка. Попробуйте позже.")

def main():
    if not API_TOKEN or not DATABASE_URL:
        logger.error("Не заданы BOT_TOKEN или DATABASE_URL")
        return

    init_db()
    app = Application.builder().token(API_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
