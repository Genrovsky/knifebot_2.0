import os
import csv
import psycopg2
from datetime import date

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# =====================================================
# CONFIG (через переменные окружения)
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://your-app.justrunmy.app
PORT = int(os.getenv("PORT", 8080))

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 5432)),
}

# Telegram ID
ADMINS = [111111111]
MASTERS = [222222222]

# =====================================================
# DATABASE
# =====================================================

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# =====================================================
# ROLES
# =====================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

def is_master(user_id: int) -> bool:
    return user_id in MASTERS

# =====================================================
# STATES (ADD ORDER)
# =====================================================

(
    TITLE, MODEL, STEEL, FINISH,
    HANDLE_MAT, HANDLE_MOUNT,
    DEADLINE, PHOTO
) = range(8)

# =====================================================
# COMMANDS
# =====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if is_admin(uid):
        text = (
            "👑 Администратор\n\n"
            "/add — добавить заказ\n"
            "/orders — все заказы\n"
            "/export — экспорт CSV"
        )
    elif is_master(uid):
        text = (
            "🛠 Мастер\n\n"
            "/orders — список заказов"
        )
    else:
        text = "⛔ Нет доступа"

    await update.message.reply_text(text)

# =====================================================
# ADD ORDER FLOW
# =====================================================

async def add_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    await update.message.reply_text("Название заказа:")
    return TITLE

async def set_title(update, context):
    context.user_data["title"] = update.message.text
    await update.message.reply_text("Модель ножа:")
    return MODEL

async def set_model(update, context):
    context.user_data["model"] = update.message.text
    await update.message.reply_text("Марка стали:")
    return STEEL

async def set_steel(update, context):
    context.user_data["steel"] = update.message.text
    await update.message.reply_text("Финиш клинка:")
    return FINISH

async def set_finish(update, context):
    context.user_data["finish"] = update.message.text
    await update.message.reply_text("Материал рукояти:")
    return HANDLE_MAT

async def set_handle_mat(update, context):
    context.user_data["handle_material"] = update.message.text
    await update.message.reply_text("Тип монтажа рукояти:")
    return HANDLE_MOUNT

async def set_handle_mount(update, context):
    context.user_data["handle_mount"] = update.message.text
    await update.message.reply_text("Дедлайн (YYYY-MM-DD):")
    return DEADLINE

async def set_deadline(update, context):
    context.user_data["deadline"] = update.message.text
    await update.message.reply_text("Прикрепи фото или /skip")
    return PHOTO

async def set_photo(update, context):
    context.user_data["photo"] = update.message.photo[-1].file_id
    return await save_order(update, context)

async def skip_photo(update, context):
    context.user_data["photo"] = None
    return await save_order(update, context)

async def save_order(update, context):
    d = context.user_data

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO orders
        (title, model, steel, blade_finish, handle_material, handle_mount, deadline, photo_file_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        d["title"],
        d["model"],
        d["steel"],
        d["finish"],
        d["handle_material"],
        d["handle_mount"],
        d["deadline"],
        d["photo"]
    ))
    conn.commit()
    conn.close()

    # уведомление мастеру
    for m in MASTERS:
        await context.bot.send_message(
            chat_id=m,
            text=f"🆕 Новый заказ: {d['title']}\n📅 Дедлайн: {d['deadline']}"
        )

    await update.message.reply_text("✅ Заказ добавлен")
    return ConversationHandler.END

# =====================================================
# ORDERS LIST
# =====================================================

async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, deadline, status
        FROM orders
        ORDER BY deadline
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Пока заказов нет")
        return

    for oid, title, deadline, status in rows:
        overdue = "⚠️ ПРОСРОЧЕН\n" if deadline and deadline < date.today() else ""
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("👁", callback_data=f"view:{oid}"),
                InlineKeyboardButton("🔄", callback_data=f"status:{oid}"),
                InlineKeyboardButton("❌", callback_data=f"del:{oid}")
            ]
        ])

        await update.message.reply_text(
            f"{overdue}#{oid} — {title}\n📅 {deadline} | {status}",
            reply_markup=kb
        )

# =====================================================
# CALLBACKS
# =====================================================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action, oid = q.data.split(":")
    oid = int(oid)

    conn = get_conn()
    cur = conn.cursor()

    if action == "view":
        cur.execute("SELECT * FROM orders WHERE id=%s", (oid,))
        o = cur.fetchone()

        text = (
            f"🧾 {o[1]}\n"
            f"Модель: {o[2]}\n"
            f"Сталь: {o[3]}\n"
            f"Финиш: {o[4]}\n"
            f"Рукоять: {o[5]}\n"
            f"Монтаж: {o[6]}\n"
            f"Дедлайн: {o[7]}\n"
            f"Статус: {o[8]}"
        )

        if o[9]:
            await q.message.reply_photo(o[9], caption=text)
        else:
            await q.message.reply_text(text)

    elif action == "status":
        cur.execute("""
            UPDATE orders
            SET status = CASE
                WHEN status='new' THEN 'in_work'
                WHEN status='in_work' THEN 'done'
                ELSE 'new'
            END
            WHERE id=%s
        """, (oid,))
        conn.commit()
        await q.message.reply_text("🔄 Статус обновлён")

    elif action == "del" and is_admin(q.from_user.id):
        cur.execute("DELETE FROM orders WHERE id=%s", (oid,))
        conn.commit()
        await q.message.reply_text("❌ Заказ удалён")

    conn.close()

# =====================================================
# EXPORT CSV
# =====================================================

async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders")
    rows = cur.fetchall()
    conn.close()

    with open("orders.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id","title","model","steel","finish",
            "handle_material","handle_mount",
            "deadline","status","photo","created_at"
        ])
        writer.writerows(rows)

    await update.message.reply_document(InputFile("orders.csv"))

# =====================================================
# MAIN (WEBHOOK)
# =====================================================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("orders", orders))
    app.add_handler(CommandHandler("export", export))

    # add order conversation
    conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_order)],
        states={
            TITLE: [MessageHandler(filters.TEXT, set_title)],
            MODEL: [MessageHandler(filters.TEXT, set_model)],
            STEEL: [MessageHandler(filters.TEXT, set_steel)],
            FINISH: [MessageHandler(filters.TEXT, set_finish)],
            HANDLE_MAT: [MessageHandler(filters.TEXT, set_handle_mat)],
            HANDLE_MOUNT: [MessageHandler(filters.TEXT, set_handle_mount)],
            DEADLINE: [MessageHandler(filters.TEXT, set_deadline)],
            PHOTO: [
                MessageHandler(filters.PHOTO, set_photo),
                CommandHandler("skip", skip_photo)
            ],
        },
        fallbacks=[]
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(callbacks))

    # webhook
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook"
    )

if __name__ == "__main__":
    main()
