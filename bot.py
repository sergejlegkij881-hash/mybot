import logging
import os
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import psycopg2
from psycopg2.extras import RealDictCursor

# ========================= НАСТРОЙКИ =========================
API_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
logging.basicConfig(level=logging.INFO)

# ========================= КЛАВИАТУРА =========================
kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить товар"), KeyboardButton(text="💳 Внести оплату")],
        [KeyboardButton(text="💰 Мой долг"), KeyboardButton(text="📜 История")]
    ],
    resize_keyboard=True
)

# ========================= БАЗА ДАННЫХ =========================
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS storage (
                    id SERIAL PRIMARY KEY,
                    debt FLOAT DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS history (
                    id SERIAL PRIMARY KEY,
                    entry TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            # Создаём запись если нет
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

def set_debt(amount):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE storage SET debt = %s", (amount,))
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

# ========================= ОБРАБОТЧИКИ =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debt = get_debt()
    await update.message.reply_text(f"✅ Бот запущен!\nТекущий долг: {debt} грн", reply_markup=kb)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_data = context.user_data

    if text == "➕ Добавить товар":
        user_data.clear()
        await update.message.reply_text("Введите товары (название количество*цена) с новой строки:")
        return

    if text == "💳 Внести оплату":
        user_data["mode"] = "pay"
        await update.message.reply_text("Введите сумму оплаты:")
        return

    if text == "💰 Мой долг":
        debt = get_debt()
        await update.message.reply_text(f"💰 Текущий долг: {debt} грн")
        return

    if text == "📜 История":
        history = get_history()
        if history:
            await update.message.reply_text("📜 История (последние 20):\n" + "\n".join(history))
        else:
            await update.message.reply_text("📜 История пуста.")
        return

    if user_data.get("mode") == "pay":
        try:
            val = float(text.replace(',', '.').replace(' ', ''))
            update_debt(-val)
            add_history(f"{datetime.now().strftime('%d.%m')} 💳 Оплата: -{val}")
            debt = get_debt()
            await update.message.reply_text(f"✅ Принято {val} грн.\nОстаток долга: {debt} грн")
        except:
            await update.message.reply_text("❌ Введите число.")
        finally:
            user_data.clear()
        return

    # Добавление товаров
    lines = text.split('\n')
    total_inc = 0
    items_added = []

    for line in lines:
        if '*' not in line:
            continue
        try:
            parts = line.rsplit(maxsplit=1)
            name = parts[0]
            calc = parts[1].replace(',', '.')
            q, p = map(float, calc.split('*'))
            summ = q * p
            total_inc += summ
            items_added.append(f"• {name}: {q} x {p} = {summ}")
        except:
            continue

    if total_inc > 0:
        update_debt(total_inc)
        add_history(f"{datetime.now().strftime('%d.%m')} ➕ Товар: +{total_inc}")
        debt = get_debt()
        res = "➕ Добавлено:\n" + "\n".join(items_added)
        await update.message.reply_text(f"{res}\n\n💰 Итого долг: {debt} грн")
    else:
        await update.message.reply_text("❓ Используйте формат: Название 10*50")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_db()
    await update.message.reply_text("🗑 Все данные удалены.")

def main():
    init_db()
    app = Application.builder().token(API_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
requirements.txt
python-telegram-bot==20.7
psycopg2-binary
Procfile
worker: python bot.py
