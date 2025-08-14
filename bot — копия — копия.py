#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roblox VIP Link Bot (Telegram)
--------------------------------
• Выдает ссылки на приватные/VIP-серверы для популярных Roblox игр в виде кнопок.
• Удобный интерфейс через Inline-кнопки.
• Администраторы могут обновлять ссылки без перезапуска бота.
• Все ссылки отображаются в виде кнопок, а не текстовых ссылок.
"""
import os
import re
import time
import logging
from typing import Dict, Optional
from dotenv import load_dotenv
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)

# -------------------- Проверка подписки на канал --------------------
CHANNEL_USERNAME = "@thespikeacc"  # Замени на свой канал

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

def is_subscribed(user_id: int) -> bool:
    """
    Проверяет, подписан ли пользователь на канал.
    Возвращает True, если подписан, иначе False.
    """
    try:
        chat_member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        print("Ошибка проверки подписки:", e)
        return False

@bot.message_handler(commands=["start"])
def cmd_start(message):
    """
    Обрабатывает команду /start.
    Если пользователь не подписан — отправляет кнопку на подписку.
    Если подписан — показывает главное меню.
    """
    if not is_subscribed(message.from_user.id):
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("✅ Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"))
        bot.send_message(
            message.chat.id,
            "🚫 Для использования бота нужно подписаться на наш канал!",
            reply_markup=kb
        )
        return
    
    # Если подписан — показываем главное меню
    bot.send_message(message.chat.id, "Добро пожаловать! Вы подписаны ✅", reply_markup=main_menu_kb())


# -------------------- Загрузка конфигурации --------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Укажите его в .env")

# ID администраторов, разделенные запятой в .env
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

# -------------------- Логирование --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("roblox_vip_bot")

# -------------------- Инициализация бота --------------------
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# -------------------- Список игр --------------------
# Название игры -> slug (используется для ключей в переменных окружения)
GAME_SLUGS: Dict[str, str] = {
    "Adopt Me": "ADOPT_ME",
    "Grow A Garden": "GROW_A_GARDEN",
    "Murder Mystery 2": "MURDER_MYSTERY_2",
    "Jailbreak": "JAILBREAK",
    "Blox Fruits": "BLOX_FRUITS",
    "Pls Donate": "PLS_DONATE",
}

# -------------------- Регулярка для проверки URL --------------------
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)

# -------------------- Антиспам --------------------
USER_LAST_TS: Dict[int, float] = {}
COOLDOWN_SECONDS = 1.0

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    return user_id in ADMIN_IDS

def env_key_for_slug(slug: str) -> str:
    """Формируем ключ переменной окружения для ссылки."""
    return f"LINK_{slug}"

def get_link_by_slug(slug: str) -> Optional[str]:
    """Получить ссылку по slug из переменных окружения."""
    return os.getenv(env_key_for_slug(slug))

def set_link_by_slug(slug: str, url: str) -> None:
    """Сохранить ссылку в переменные окружения (в памяти процесса)."""
    os.environ[env_key_for_slug(slug)] = url

def validate_url(url: str) -> bool:
    """Проверка, что строка является корректным URL."""
    return bool(URL_RE.match(url))

def rate_limit_ok(user_id: int) -> bool:
    """Простая проверка кулдауна между командами."""
    now = time.time()
    last = USER_LAST_TS.get(user_id, 0.0)
    if now - last < COOLDOWN_SECONDS:
        return False
    USER_LAST_TS[user_id] = now
    return True

def main_menu_kb() -> InlineKeyboardMarkup:
    """Клавиатура главного меню с выбором игры."""
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for title, slug in GAME_SLUGS.items():
        buttons.append(InlineKeyboardButton(text=title, callback_data=f"game:{slug}"))
    for i in range(0, len(buttons), 2):
        kb.row(*buttons[i:i+2])
    kb.row(
        InlineKeyboardButton("ℹ️ О боте", callback_data="about"),
        InlineKeyboardButton("🧾 Все ссылки", callback_data="list_all"),
    )
    return kb

def links_kb(links: Dict[str, str]) -> InlineKeyboardMarkup:
    """Создание клавиатуры с кнопками-ссылками для игр."""
    kb = InlineKeyboardMarkup()
    for title, url in links.items():
        kb.add(InlineKeyboardButton(f"🔗 {title}", url=url))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_main"))
    return kb

def admin_menu_kb() -> InlineKeyboardMarkup:
    """Клавиатура панели администратора для изменения ссылок."""
    kb = InlineKeyboardMarkup(row_width=2)
    for title, slug in GAME_SLUGS.items():
        kb.insert(InlineKeyboardButton(f"✏️ {title}", callback_data=f"admin:set:{slug}"))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_main"))
    return kb

def title_by_slug(slug: str) -> str:
    """Получить название игры по slug."""
    for title, s in GAME_SLUGS.items():
        if s == slug:
            return title
    return slug

# -------------------- Команды бота --------------------
@bot.message_handler(commands=["start"])
def cmd_start(message: Message):
    """Команда /start — показывает главное меню."""
    if not rate_limit_ok(message.from_user.id):
        return
    bot.send_message(message.chat.id, "<b>Привет!</b>\nВыбери игру ниже 👇", reply_markup=main_menu_kb())

@bot.message_handler(commands=["links"])
def cmd_links(message: Message):
    """Команда /links — показывает кнопки со всеми доступными ссылками."""
    if not rate_limit_ok(message.from_user.id):
        return
    links = {title: url for title, slug in GAME_SLUGS.items() if (url := get_link_by_slug(slug))}
    if not links:
        bot.send_message(message.chat.id, "⚠️ Ссылки пока не заданы.")
        return
    bot.send_message(message.chat.id, "<b>Ссылки на все игры:</b>", reply_markup=links_kb(links))

@bot.message_handler(commands=["admin"])
def cmd_admin(message: Message):
    """Команда /admin — панель администратора."""
    if not rate_limit_ok(message.from_user.id):
        return
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Команда доступна только администраторам.")
        return
    bot.send_message(message.chat.id, "<b>Панель администратора</b>", reply_markup=admin_menu_kb())

# -------------------- Обработка нажатий кнопок --------------------
@bot.callback_query_handler(func=lambda c: True)
def on_callback(call: CallbackQuery):
    """Обработка всех callback-запросов от кнопок."""
    data = call.data or ""
    if data.startswith("game:"):
        # Пользователь выбрал игру
        slug = data.split(":", 1)[1]
        title = title_by_slug(slug)
        url = get_link_by_slug(slug)
        if url:
            bot.send_message(call.message.chat.id, f"<b>{title}</b>\nЕсли ссылка не открывается — попробуйте позже.", reply_markup=links_kb({title: url}))
        else:
            bot.send_message(call.message.chat.id, f"⚠️ Ссылка для <b>{title}</b> не задана.")
    elif data == "about":
        bot.send_message(call.message.chat.id, "Этот бот выдаёт VIP-ссылки на Roblox сервера.")
    elif data == "list_all":
        # Показать все ссылки кнопками
        links = {title: url for title, slug in GAME_SLUGS.items() if (url := get_link_by_slug(slug))}
        if not links:
            bot.send_message(call.message.chat.id, "⚠️ Ссылки пока не заданы.")
        else:
            bot.send_message(call.message.chat.id, "<b>Ссылки на все игры:</b>", reply_markup=links_kb(links))
    elif data.startswith("admin:set:"):
        # Админ выбирает игру для изменения ссылки
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, text="Только для админов")
            return
        slug = data.split(":")[-1]
        title = title_by_slug(slug)
        msg = bot.send_message(call.message.chat.id, f"✏️ Отправьте новую ссылку для <b>{title}</b>. Отправьте 'отмена' для отмены.")
        bot.register_next_step_handler(msg, handle_new_link_input, slug)
    elif data == "back_main":
        # Вернуться в главное меню
        bot.edit_message_text("Выбери игру ниже 👇", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=main_menu_kb())

# -------------------- Обработка ввода новой ссылки --------------------
def handle_new_link_input(message: Message, slug: str):
    """Обработка ввода новой ссылки администратором."""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Нет прав.")
        return
    text = (message.text or "").strip()
    if text.lower() == "отмена":
        bot.send_message(message.chat.id, "Отменено.", reply_markup=admin_menu_kb())
        return
    if not validate_url(text):
        msg = bot.send_message(message.chat.id, "❌ Это не похоже на ссылку. Попробуйте ещё раз или 'отмена'.")
        bot.register_next_step_handler(msg, handle_new_link_input, slug)
        return
    set_link_by_slug(slug, text)
    bot.send_message(message.chat.id, f"✅ Ссылка обновлена для <b>{title_by_slug(slug)}</b>.", reply_markup=admin_menu_kb())

# -------------------- Запуск бота --------------------
if __name__ == "__main__":
    logger.info("Бот запущен.")
    bot.infinity_polling(timeout=60, long_polling_timeout=50)
