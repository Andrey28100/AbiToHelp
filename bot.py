import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
import os

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 О боте", callback_data="about_bot")
    builder.button(text="👤 О пользователе", callback_data="about_user")
    builder.adjust(1)
    return builder.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="back_to_main")
    return builder.as_markup()


@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    await message.answer("Привет! Выберите раздел:", reply_markup=main_menu_kb())


@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    user = callback.from_user
    chat_id = callback.message.chat.id

    if callback.data == "about_bot":
        text = (
            "🤖 *Этот бот* — участник хакатона!\n"
            "Он может показывать информацию о себе и о вас.\n"
            "Разработан с ❤️ на Python + aiogram."
        )
        await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    elif callback.data == "about_user":
        full_name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
        username = f"@{user.username}" if user.username else "не указан"
        user_id = user.id

        text = (
            "👤 *Ваш профиль:*\n"
            f"Имя: {full_name}\n"
            f"Юзернейм: {username}\n"
            f"ID: `{user_id}`"
        )
        await callback.message.edit_text(text, reply_markup=back_kb(), parse_mode="Markdown")

    elif callback.data == "back_to_main":
        await callback.message.edit_text("Привет! Выберите раздел:", reply_markup=main_menu_kb())

    await callback.answer()


async def main():
    print("Бот с плавным inline-меню запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())