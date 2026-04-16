import logging
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
import psycopg2   # <--- исправлено

API_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
logging.basicConfig(level=logging.INFO)

kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Добавить")],
        [KeyboardButton(text="💬 Мой запрос")],
        [KeyboardButton(text="📅 Сбросить запрос")]
    ],
    resize_keyboard=True
)
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS storage (id SERIAL PRIMARY KEY, debt FLOAT DEFAULT 0);
                CREATE TABLE IF NOT EXISTS history (id SERIAL PRIMARY KEY, entry TEXT, created_at TIMESTAMP DEFAULT NOW());
                CREATE TABLE IF NOT EXISTS products (id SERIAL PRIMARY KEY, name TEXT UNIQUE, default_price FLOAT DEFAULT 0);
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

def get_products():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name, default_price FROM products ORDER BY id")
            return cur.fetchall()

def save_product(name, price):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO products (name, default_price) VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET default_price = EXCLUDED.default_price
            """, (name, price))
        conn.commit()

def delete_product(name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM products WHERE name = %s", (name,))
        conn.commit()

def build_table(products):
    """Строит таблицу-шаблон для заполнения"""
    FREE_ROWS = 5
    header = "Заполни таблицу (кол-во и цену можно менять, 0 = не брал):\n\n"
    line = "{:<16}| {:<6} | {:<7} | {}\n"
    sep  = "-" * 16 + "+" + "-" * 8 + "+" + "-" * 9 + "+" + "-" * 7 + "\n"

    table = header
    table += line.format("Наименование", "Кол-во", "Цена", "Сумма")
    table += sep

    for name, price in products:
        table += line.format(name[:16], "0", str(price), "0")

    # Свободные строки
    for _ in range(FREE_ROWS):
        table += line.format("", "", "", "")

    table += sep
    table += "💰 Итого:                          | 0\n\n"
    table += "✏️ Измени нужные строки и отправь обратно"
    return table

def parse_table(text):
    """Парсит заполненную таблицу и возвращает список (name, qty, price, sum)"""
    items = []
    lines = text.strip().split('\n')
    for line in lines:
        if '|' not in line:
            continue
        parts = [p.strip() for p in line.split('|')]
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        if not name or name.lower() in ('наименование', '💰 итого:', ''):
            continue
        if set(name) <= set('-'):
            continue
        try:
            qty = float(parts[1].replace(',', '.'))
            price = float(parts[2].replace(',', '.'))
        except:
            continue
        if qty == 0:
            continue
        summ = round(qty * price, 2)
        items.append((name, qty, price, summ))
    return items

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debt = get_debt()
    await update.message.reply_text(f"✅ Бот запущен!\nТекущий долг: {debt} грн", reply_markup=kb)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_data = context.user_data

    # ───── ДОБАВИТЬ ТОВАР ─────
    if text == "➕ Добавить товар":
        user_data.clear()
        user_data["mode"] = "table"
        products = get_products()
        table = build_table(products)
        await update.message.reply_text(f"```\n{table}\n```", parse_mode="Markdown")
        return

    # ───── ОПЛАТА ─────
    if text == "💳 Внести оплату":
        user_data.clear()
        user_data["mode"] = "pay"
        await update.message.reply_text("Введите сумму оплаты:")
        return

    # ───── ДОЛГ ─────
    if text == "💰 Мой долг":
        debt = get_debt()
        await update.message.reply_text(f"💰 Текущий долг: {debt} грн")
        return

    # ───── ИСТОРИЯ ─────
    if text == "📜 История":
        history = get_history()
        if history:
            await update.message.reply_text("📜 История:\n" + "\n".join(history))
        else:
            await update.message.reply_text("📜 История пуста.")
        return

    # ───── РЕЖИМ ОПЛАТЫ ─────
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

    # ───── РЕЖИМ ТАБЛИЦЫ ─────
    if user_data.get("mode") == "table":
        items = parse_table(text)
        if not items:
            await update.message.reply_text("❌ Ничего не распознано. Убедись что кол-во > 0.")
            return

        total = 0
        result_lines = []
        line = "{:<16}| {:<6} | {:<7} | {}"

        sep = "-" * 16 + "+" + "-" * 8 + "+" + "-" * 9 + "+" + "-" * 7
        result_lines.append(line.format("Наименование", "Кол-во", "Цена", "Сумма"))
        result_lines.append(sep)

        for name, qty, price, summ in items:
            total += summ
            result_lines.append(line.format(name[:16], str(qty), str(price), str(summ)))
            # Обновляем цену по умолчанию в БД
            save_product(name, price)

        result_lines.append(sep)
        result_lines.append(f"💰 Итого:                          | {round(total, 2)}")

        update_debt(total)
        add_history(f"{datetime.now().strftime('%d.%m')} ➕ Товар: +{round(total, 2)} грн")
        debt = get_debt()

        msg = "```\n" + "\n".join(result_lines) + "\n```"
        msg += f"\n\n✅ Добавлено в долг!\n💰 Общий долг: {debt} грн"

        await update.message.reply_text(msg, parse_mode="Markdown")
        user_data.clear()
        return

    await update.message.reply_text("❓ Нажми кнопку для выбора действия.", reply_markup=kb)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_db()
    await update.message.reply_text("🗑 Все данные удалены.")

async def add_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /добавить Название Цена
    Пример: /добавить 38бл 35
    """
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Формат: /добавить Название Цена\nПример: /добавить 38бл 35")
        return
    try:
        price = float(args[-1].replace(',', '.'))
        name = ' '.join(args[:-1])
        save_product(name, price)
        await update.message.reply_text(f"✅ Товар '{name}' добавлен с ценой {price} грн.")
    except:
        await update.message.reply_text("❌ Ошибка. Формат: /добавить Название Цена")

async def del_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /удалить Название
    Пример: /удалить 38бл
    """
    if not context.args:
        await update.message.reply_text("Формат: /удалить Название\nПример: /удалить 38бл")
        return
    name = ' '.join(context.args)
    delete_product(name)
    await update.message.reply_text(f"🗑 Товар '{name}' удалён из списка.")

async def list_products_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех товаров"""
    products = get_products()
    if not products:
        await update.message.reply_text("📦 Список товаров пуст.\nДобавь через /добавить Название Цена")
        return
    lines = ["📦 Список товаров:\n"]
    for name, price in products:
        lines.append(f"• {name} — {price} грн")
    await update.message.reply_text("\n".join(lines))

def main():
    init_db()
    app = Application.builder().token(API_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("добавить", add_product_cmd))
    app.add_handler(CommandHandler("удалить", del_product_cmd))
    app.add_handler(CommandHandler("товары", list_products_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
