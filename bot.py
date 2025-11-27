import asyncio
import aiosqlite
import os
import qrcode
from io import BytesIO
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from aiogram.types import BufferedInputFile

# === Настройки ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MODERATOR_TG_ID = os.getenv("MODER_ID")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env")
if not MODERATOR_TG_ID:
    raise ValueError("❌ MODER_ID не найден в .env")

try:
    MODERATOR_TG_ID = int(MODERATOR_TG_ID)
except ValueError:
    raise ValueError("❌ MODER_ID должен быть целым числом (ваш Telegram ID")

DB_PATH = "bot.db"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# === Инициализация базы данных ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            role TEXT DEFAULT 'applicant',
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            event_datetime TEXT,
            location TEXT,
            created_by INTEGER,
            post_message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(tg_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            user_id INTEGER,
            event_id INTEGER,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'confirmed',
            FOREIGN KEY(user_id) REFERENCES users(tg_id),
            FOREIGN KEY(event_id) REFERENCES events(id),
            PRIMARY KEY(user_id, event_id)
        )""")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS notification_prefs (
            user_id INTEGER PRIMARY KEY,
            events_enabled BOOLEAN DEFAULT 1,
            news_enabled BOOLEAN DEFAULT 1,
            FOREIGN KEY(user_id) REFERENCES users(tg_id)
        )""")

        await db.commit()


# === Вспомогательные функции ===

def generate_qr(data: str) -> BytesIO:
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


# === Клавиатуры ===

def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 О боте", callback_data="about_bot")
    builder.button(text="👤 Мой профиль", callback_data="my_profile")
    builder.button(text="🔔 Настройки уведомлений", callback_data="notif_settings")
    builder.adjust(1)
    return builder.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_main")
    return builder.as_markup()


def event_register_kb(event_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Зарегистрироваться", callback_data=f"reg_{event_id}")
    return builder.as_markup()


def event_registered_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Зарегистрировано", callback_data="noop")
    return builder.as_markup()


def notif_toggle_kb(events_on: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    status = "✅ Включены" if events_on else "❌ Выключены"
    builder.button(text=f"Мероприятия: {status}", callback_data="toggle_events")
    builder.button(text="⬅️ Назад", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()


# === Обработчики ===

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (tg_id, full_name, username)
            VALUES (?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                full_name = excluded.full_name,
                username = excluded.username
        """, (user.id, user.full_name, user.username))
        await db.execute("INSERT OR IGNORE INTO notification_prefs (user_id) VALUES (?)", (user.id,))
        await db.commit()

    await message.answer(
        "🎓 Добро пожаловать в бот поддержки абитуриентов!\n\n"
        "Здесь вы можете:\n"
        "• Получить QR-пропуск на мероприятия\n"
        "• Узнать о событиях университета\n"
        "• Настроить уведомления",
        reply_markup=main_menu_kb()
    )


@dp.message(Command("add_event"))
async def cmd_add_event(message: types.Message):
    if message.from_user.id != MODERATOR_TG_ID:
        await message.answer("⚠️ Только модератор может добавлять мероприятия.")
        return

    parts = message.text.split(" | ")
    if len(parts) != 4:
        await message.answer(
            "❗ Неверный формат.\n"
            "Используйте:\n"
            "/add_event Название | Описание | Дата (ГГГГ-ММ-ДД ЧЧ:ММ) | Место"
        )
        return

    title, description, event_datetime, location = [p.strip() for p in parts]

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO events (title, description, event_datetime, location, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (title, description, event_datetime, location, message.from_user.id))
        event_id = cursor.lastrowid
        await db.commit()

    event_tag = f"#event_{event_id}"
    post_text = (
        f"🎉 <b>{title}</b>\n\n"
        f"{description}\n\n"
        f"📅 {event_datetime}\n"
        f"📍 {location}\n\n"
        f"{event_tag}"
    )
    sent_msg = await message.answer(post_text, parse_mode="HTML")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE events SET post_message_id = ? WHERE id = ?", (sent_msg.message_id, event_id))
        await db.commit()

    await sent_msg.edit_reply_markup(reply_markup=event_register_kb(event_id))
    await message.answer(f"✅ Мероприятие создано! ID: {event_id}")

    # Рассылка (опционально — для демо)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT u.tg_id FROM users u
            JOIN notification_prefs np ON u.tg_id = np.user_id
            WHERE np.events_enabled = 1
        """)
        users = await cursor.fetchall()

    for (tg_id,) in users:
        try:
            await bot.send_message(
                tg_id,
                f"📬 <b>Новое мероприятие!</b>\n\n{post_text}",
                parse_mode="HTML",
                reply_markup=event_register_kb(event_id)
            )
        except Exception:
            pass  # пользователь неактивен


@dp.message(Command("moder"))
async def cmd_moder(message: types.Message):
    if message.from_user.id != MODERATOR_TG_ID:
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="mod_stats")
    builder.button(text="📨 Рассылка (демо)", callback_data="mod_broadcast_demo")
    builder.adjust(1)
    await message.answer("🛠 Панель модератора:", reply_markup=builder.as_markup())


@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    user = callback.from_user
    data = callback.data

    # === Регистрация на мероприятие ===
    if data.startswith("reg_"):
        try:
            event_id = int(data.split("_", 1)[1])
        except ValueError:
            await callback.answer("❌ Некорректный ID мероприятия.", show_alert=True)
            return

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT title FROM events WHERE id = ?", (event_id,))
            event = await cursor.fetchone()
            if not event:
                await callback.answer("❌ Мероприятие не найдено.", show_alert=True)
                return

            cursor = await db.execute(
                "SELECT 1 FROM registrations WHERE user_id = ? AND event_id = ?",
                (user.id, event_id)
            )
            if await cursor.fetchone():
                await callback.answer("✅ Вы уже зарегистрированы!", show_alert=True)
                return

            # Сохраняем регистрацию
            await db.execute(
                "INSERT INTO registrations (user_id, event_id) VALUES (?, ?)",
                (user.id, event_id)
            )
            await db.commit()

        # ✅ Генерируем и отправляем QR-пропуск
        qr_payload = f"{user.id}:{event_id}"
        qr_img = generate_qr(qr_payload)  # BytesIO
        qr_bytes = qr_img.getvalue()

        # Создаём файл для отправки
        photo_file = BufferedInputFile(
            file=qr_bytes,
            filename="qr_pass.png"
        )

        caption = (
            f"🎉 <b>Регистрация успешна!</b>\n\n"
            f"Вот ваш QR-пропуск на мероприятие:\n"
            f"<b>{event[0]}</b> (ID: {event_id})\n\n"
            f"Покажите этот код при входе."
        )

        # Отправляем QR как новое сообщение
        await callback.message.answer_photo(
            photo=photo_file,
            caption=caption,
            parse_mode="HTML"
        )

        # Меняем кнопку на "✅ Зарегистрировано"
        await callback.message.edit_reply_markup(reply_markup=event_registered_kb())
        await callback.answer("✅ Регистрация подтверждена!", show_alert=True)
        return

    if data == "noop":
        await callback.answer()
        return

    # === О боте ===
    if data == "about_bot":
        text = (
            "🤖 <b>Бот абитуриента</b>\n\n"
            "Помогает новым студентам:\n"
            "• Ориентироваться в кампусе\n"
            "• Регистрироваться на мероприятия\n"
            "• Получать QR-пропуска\n\n"
            "Разработан для хакатона университета."
        )
        await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")
        await callback.answer()
        return

    # === Мой профиль + QR ===
    if data == "my_profile":
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT full_name, username, role FROM users WHERE tg_id = ?",
                (user.id,)
            )
            row = await cursor.fetchone()
            if not row:
                await callback.message.edit_text("❌ Профиль не найден. Напишите /start.")
                return

        full_name, username, role = row
        role_name = {"applicant": "Абитуриент", "curator": "Куратор", "moderator": "Модератор"}.get(role, role)
        text = (
            f"👤 <b>Ваш профиль</b>\n\n"
            f"Имя: {full_name}\n"
            f"Роль: {role_name}\n"
            f"ID: <code>{user.id}</code>"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="📄 Мои регистрации", callback_data="my_registrations")
        builder.button(text="🎫 Получить QR-пропуск", callback_data="get_qr_all")
        builder.button(text="⬅️ Назад", callback_data="back_to_main")
        builder.adjust(1)
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await callback.answer()
        return

    if data == "my_registrations":
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT e.title, e.event_datetime FROM events e
                JOIN registrations r ON e.id = r.event_id
                WHERE r.user_id = ?
            """, (user.id,))
            rows = await cursor.fetchall()

        if not rows:
            text = "📭 Вы ещё не зарегистрированы ни на одно мероприятие."
        else:
            text = "✅ Ваши регистрации:\n\n"
            for title, dt in rows:
                text += f"• {title} ({dt})\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="my_profile")
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        await callback.answer()
        return

    if data == "get_qr_all":
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT event_id FROM registrations WHERE user_id = ?
            """, (user.id,))
            events = await cursor.fetchall()

        if not events:
            await callback.answer("❌ У вас нет регистраций для QR-пропуска.", show_alert=True)
            return

        # Берём первое мероприятие (можно позже сделать выбор из списка)
        event_id = events[0][0]
        qr_payload = f"{user.id}:{event_id}"  # Это то, что будет в QR
        qr_img = generate_qr(qr_payload)

        caption = (
            f"🎫 <b>QR-пропуск</b>\n\n"
            f"Скан этого кода подтвердит вашу регистрацию на мероприятие ID <code>{event_id}</code>.\n"
            f"Ваш Telegram ID: <code>{user.id}</code>"
        )

        await callback.message.answer_photo(
            photo=qr_img,
            caption=caption,
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # === Настройки уведомлений ===
    if data == "notif_settings":
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT events_enabled FROM notification_prefs WHERE user_id = ?",
                (user.id,)
            )
            row = await cursor.fetchone()
            if not row:
                await callback.answer("❌ Настройки не найдены.")
                return
            events_on = bool(row[0])

        await callback.message.edit_text(
            "🔔 <b>Настройки уведомлений</b>",
            reply_markup=notif_toggle_kb(events_on),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    if data == "toggle_events":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE notification_prefs
                SET events_enabled = 1 - events_enabled
                WHERE user_id = ?
            """, (user.id,))
            await db.commit()

        # Теперь НЕ вызываем handle_callback, а просто перерисовываем настройки
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT events_enabled FROM notification_prefs WHERE user_id = ?",
                (user.id,)
            )
            row = await cursor.fetchone()
            events_on = bool(row[0]) if row else True

        await callback.message.edit_text(
            "🔔 <b>Настройки уведомлений</b>",
            reply_markup=notif_toggle_kb(events_on),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # === Панель модератора ===
    if data == "mod_stats":
        async with aiosqlite.connect(DB_PATH) as db:
            users = await (await db.execute("SELECT COUNT(*) FROM users")).fetchone()
            events = await (await db.execute("SELECT COUNT(*) FROM events")).fetchone()
            regs = await (await db.execute("SELECT COUNT(*) FROM registrations")).fetchone()
        text = (
            "📊 <b>Статистика</b>\n\n"
            f"Пользователей: {users[0]}\n"
            f"Мероприятий: {events[0]}\n"
            f"Регистраций: {regs[0]}"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="⬅️ Назад", callback_data="back_to_moder")
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await callback.answer()
        return

    if data == "mod_broadcast_demo":
        await callback.message.edit_text("📨 Рассылка запущена (демо-режим).", parse_mode="HTML")
        await callback.answer()
        return

    if data == "back_to_moder":
        builder = InlineKeyboardBuilder()
        builder.button(text="📊 Статистика", callback_data="mod_stats")
        builder.button(text="📨 Рассылка (демо)", callback_data="mod_broadcast_demo")
        builder.adjust(1)
        await callback.message.edit_text("🛠 Панель модератора:", reply_markup=builder.as_markup())
        await callback.answer()
        return

    # === Назад в главное меню ===
    if data == "back_to_main":
        await callback.message.edit_text(
            "🎓 Добро пожаловать в бот поддержки абитуриентов!\n\n"
            "Здесь вы можете:\n"
            "• Получить QR-пропуск на мероприятия\n"
            "• Узнать о событиях университета\n"
            "• Настроить уведомления",
            reply_markup=main_menu_kb()
        )
        await callback.answer()
        return

    await callback.answer()


# === Запуск ===
async def main():
    await init_db()
    print("✅ Бот запущен. База данных: bot.db")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())