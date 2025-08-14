#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roblox VIP Link Bot (Telegram) — расширенная версия
---------------------------------------------------
Функционал:
• Выдает ссылки на VIP/приватные сервера Roblox (кнопками).
• Обязательная подписка на канал @thespikeacc + кнопка «Я подписался».
• Админ-панель:
  - 🎮 Игры: список игр, редактирование ссылок, добавление новых игр.
  - 📊 Пользователи: список, количество действий, просмотр логов (сообщения и клики).
• SQLite база (bot.db): таблицы games, users, events.
• Подробные комментарии для лёгкой навигации в коде.

Зависимости:
pip install pyTelegramBotAPI python-dotenv
"""

import os
import re
import time
import sqlite3
import logging
from typing import Dict, Optional, List, Tuple

from dotenv import load_dotenv
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)

# ==================== Конфиг/логирование ====================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Укажите его в .env")

# Список админов в .env: ADMIN_IDS=111,222,333
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

# Канал с обязательной подпиской
CHANNEL_USERNAME = "@thespikeacc"   # ← твой канал

# Лог в файл (советую оставить — полезно при фоновом запуске через pythonw.exe)
logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("roblox_vip_bot")

# ==================== Инициализация бота ====================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ==================== База данных (SQLite) ====================
DB_PATH = "bot.db"

def db() -> sqlite3.Connection:
    """Возвращает подключение к БД (каждый вызов — новое подключение с авто-commit)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Создание таблиц при первом запуске."""
    with db() as conn:
        c = conn.cursor()
        # Игры
        c.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # Пользователи
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # События/логи
        c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,  -- это Telegram user_id
            type TEXT NOT NULL,        -- 'message' или 'callback'
            content TEXT NOT NULL,     -- текст сообщения / callback_data
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

def seed_initial_games_if_empty():
    """
    Инициализация начальными играми, если таблица пустая.
    Если есть переменные окружения LINK_..., возьмём оттуда URL.
    """
    defaults = [
        ("Adopt Me",       os.getenv("LINK_ADOPT_ME")),
        ("Grow A Garden",  os.getenv("LINK_GROW_A_GARDEN")),
        ("Murder Mystery 2", os.getenv("LINK_MURDER_MYSTERY_2")),
        ("Jailbreak",      os.getenv("LINK_JAILBREAK")),
        ("Blox Fruits",    os.getenv("LINK_BLOX_FRUITS")),
        ("Pls Donate",     os.getenv("LINK_PLS_DONATE")),
    ]
    with db() as conn:
        c = conn.cursor()
        cnt = c.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        if cnt == 0:
            for title, url in defaults:
                c.execute("INSERT INTO games(title, url) VALUES(?, ?)", (title, url))

def add_game(title: str, url: Optional[str]) -> int:
    with db() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO games(title, url) VALUES(?, ?)", (title.strip(), (url or "").strip() or None))
        return c.lastrowid

def update_game_url(game_id: int, url: str):
    with db() as conn:
        conn.execute("UPDATE games SET url=? WHERE id=?", (url.strip(), game_id))

def get_game(game_id: int) -> Optional[sqlite3.Row]:
    with db() as conn:
        r = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        return r

def list_games(offset: int = 0, limit: int = 20) -> List[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            "SELECT * FROM games ORDER BY id ASC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()

def count_games() -> int:
    with db() as conn:
        return conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]

def upsert_user(message_from):
    """Создаём/обновляем запись о пользователе при любом взаимодействии."""
    try:
        with db() as conn:
            conn.execute(
                """INSERT INTO users(user_id, username, first_name, last_name)
                   VALUES(?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     username=excluded.username,
                     first_name=excluded.first_name,
                     last_name=excluded.last_name
                """,
                (message_from.id, message_from.username, message_from.first_name, message_from.last_name)
            )
    except Exception as e:
        logger.error(f"upsert_user error: {e}")

def log_event(user_id: int, type_: str, content: str):
    """Логируем событие (в БД + лог-файл)."""
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO events(user_id, type, content) VALUES(?,?,?)",
                (user_id, type_, content)
            )
    except Exception as e:
        logger.error(f"log_event error: {e}")

def list_users(offset: int = 0, limit: int = 10) -> List[sqlite3.Row]:
    """Список пользователей с количеством действий."""
    with db() as conn:
        return conn.execute("""
            SELECT u.*, 
                   (SELECT COUNT(*) FROM events e WHERE e.user_id = u.user_id) AS actions_count
            FROM users u
            ORDER BY u.created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

def count_users() -> int:
    with db() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def list_user_events(tg_user_id: int, offset: int = 0, limit: int = 20) -> List[sqlite3.Row]:
    with db() as conn:
        return conn.execute("""
            SELECT * FROM events
            WHERE user_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
        """, (tg_user_id, limit, offset)).fetchall()

def count_user_events(tg_user_id: int) -> int:
    with db() as conn:
        return conn.execute("SELECT COUNT(*) FROM events WHERE user_id=?", (tg_user_id,)).fetchone()[0]

# ==================== Вспомогалки (валидация/лимит) ====================
URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)

USER_LAST_TS: Dict[int, float] = {}
COOLDOWN_SECONDS = 1.0

def validate_url(url: str) -> bool:
    return bool(URL_RE.match(url.strip()))

def rate_limit_ok(user_id: int) -> bool:
    now = time.time()
    last = USER_LAST_TS.get(user_id, 0.0)
    if now - last < COOLDOWN_SECONDS:
        return False
    USER_LAST_TS[user_id] = now
    return True

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ==================== Подписка на канал ====================
def is_subscribed(user_id: int) -> bool:
    """
    Проверка подписки на канал. Для приватных/ограниченных каналов — сделайте бота админом.
    """
    try:
        chat_member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return chat_member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

def subscribe_kb() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой подписки и повторной проверкой."""
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"))
    kb.add(InlineKeyboardButton("🔄 Я подписался", callback_data="sub:check"))
    return kb

# ==================== Клавиатуры (главное/списки) ====================
def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню (список игр) — динамически из БД, по 2 в ряд."""
    kb = InlineKeyboardMarkup(row_width=2)
    buttons: List[InlineKeyboardButton] = []
    for row in list_games(0, 50):  # до 50 игр в меню, при необходимости сделать пагинацию
        buttons.append(InlineKeyboardButton(text=row["title"], callback_data=f"g:{row['id']}"))
    # Разложим по 2 в ряд
    for i in range(0, len(buttons), 2):
        kb.row(*buttons[i:i+2])
    kb.row(
        InlineKeyboardButton("ℹ️ О боте", callback_data="about"),
        InlineKeyboardButton("🧾 Все ссылки", callback_data="list_all"),
    )
    return kb

def links_kb(links: Dict[str, str]) -> InlineKeyboardMarkup:
    """Кнопки-ссылки на игры (и кнопка назад)."""
    kb = InlineKeyboardMarkup()
    for title, url in links.items():
        kb.add(InlineKeyboardButton(f"🔗 {title}", url=url))
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="back_main"))
    return kb

# --- Админ: панель/меню
def admin_root_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 Игры", callback_data="adm:games:0"),
        InlineKeyboardButton("📊 Пользователи", callback_data="adm:users:0")
    )
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="back_main"))
    return kb

def admin_games_kb(page: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    """Список игр с кнопками редактирования + пагинация + добавить игру."""
    kb = InlineKeyboardMarkup(row_width=1)
    offset = page * page_size
    games = list_games(offset, page_size)
    for g in games:
        kb.add(InlineKeyboardButton(f"✏️ {g['title']}", callback_data=f"adm:game:edit:{g['id']}"))

    # Пагинация
    total = count_games()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"adm:games:{page-1}"))
    if offset + page_size < total:
        nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"adm:games:{page+1}"))
    if nav:
        kb.row(*nav)

    kb.add(InlineKeyboardButton("➕ Добавить игру", callback_data="adm:game:add"))
    kb.add(InlineKeyboardButton("🏠 Админ-панель", callback_data="adm:root"))
    return kb

def admin_users_kb(page: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    """Список пользователей (с количеством действий) + пагинация."""
    kb = InlineKeyboardMarkup(row_width=1)
    offset = page * page_size
    users = list_users(offset, page_size)
    for u in users:
        uname = f"@{u['username']}" if u['username'] else f"id{u['user_id']}"
        kb.add(InlineKeyboardButton(f"👤 {uname} • действий: {u['actions_count']}", callback_data=f"adm:user:{u['user_id']}:0"))
    # Пагинация
    total = count_users()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"adm:users:{page-1}"))
    if offset + page_size < total:
        nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"adm:users:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.add(InlineKeyboardButton("🏠 Админ-панель", callback_data="adm:root"))
    return kb

def admin_user_logs_kb(tg_user_id: int, page: int = 0, page_size: int = 20) -> InlineKeyboardMarkup:
    """Пагинация по логам конкретного пользователя."""
    kb = InlineKeyboardMarkup(row_width=2)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"adm:user:{tg_user_id}:{page-1}"))
    # Есть ли следующая страница?
    total = count_user_events(tg_user_id)
    if (page + 1) * page_size < total:
        nav.append(InlineKeyboardButton("➡️ Далее", callback_data=f"adm:user:{tg_user_id}:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.add(InlineKeyboardButton("📋 К пользователям", callback_data="adm:users:0"))
    kb.add(InlineKeyboardButton("🏠 Админ-панель", callback_data="adm:root"))
    return kb

# ==================== Состояния для пошаговых действий (в памяти) ====================
"""
PENDING_ACTIONS: запоминаем, что сейчас делает админ:
- { admin_id: {"type": "add_game_title" / "add_game_url", "data": {...}} }
- { admin_id: {"type": "edit_game_url", "data": {"game_id": 1}} }
"""
PENDING_ACTIONS: Dict[int, Dict] = {}

# ==================== Команды ====================
@bot.message_handler(commands=["start"])
def cmd_start(message: Message):
    # Регистрируем/обновляем пользователя и пишем лог
    upsert_user(message.from_user)
    log_event(message.from_user.id, "message", "/start")

    # Проверка подписки
    if not is_subscribed(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 Для использования бота нужно подписаться на наш канал!", reply_markup=subscribe_kb())
        return

    if not rate_limit_ok(message.from_user.id):
        return

    bot.send_message(message.chat.id, "<b>Привет!</b>\nВыбери игру ниже 👇", reply_markup=main_menu_kb())

@bot.message_handler(commands=["links"])
def cmd_links(message: Message):
    upsert_user(message.from_user)
    log_event(message.from_user.id, "message", "/links")

    if not is_subscribed(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 Для использования этой команды нужно подписаться на канал!", reply_markup=subscribe_kb())
        return

    if not rate_limit_ok(message.from_user.id):
        return

    # Собираем ссылки по всем играм (только те, у которых есть URL)
    rows = list_games(0, 1000)
    links = {r["title"]: r["url"] for r in rows if r["url"]}
    if not links:
        bot.send_message(message.chat.id, "⚠️ Ссылки пока не заданы.")
        return

    bot.send_message(message.chat.id, "<b>Ссылки на все игры:</b>", reply_markup=links_kb(links))

@bot.message_handler(commands=["admin"])
def cmd_admin(message: Message):
    upsert_user(message.from_user)
    log_event(message.from_user.id, "message", "/admin")

    if not is_subscribed(message.from_user.id):
        bot.send_message(message.chat.id, "🚫 Для доступа к админ-панели нужно подписаться на канал!", reply_markup=subscribe_kb())
        return

    if not rate_limit_ok(message.from_user.id):
        return

    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Команда доступна только администраторам.")
        return

    bot.send_message(message.chat.id, "<b>Админ-панель</b> — выберите раздел:", reply_markup=admin_root_kb())

# ==================== Callback-обработчики ====================
@bot.callback_query_handler(func=lambda c: c.data == "sub:check")
def cb_check_subscription(call: CallbackQuery):
    # Логируем клик
    upsert_user(call.from_user)
    log_event(call.from_user.id, "callback", "sub:check")

    if is_subscribed(call.from_user.id):
        bot.send_message(call.message.chat.id, "✅ Отлично! Доступ открыт.", reply_markup=main_menu_kb())
    else:
        bot.send_message(call.message.chat.id, "❌ Вы всё ещё не подписаны. Пожалуйста, подпишитесь и попробуйте снова.", reply_markup=subscribe_kb())

@bot.callback_query_handler(func=lambda c: True)
def on_callback(call: CallbackQuery):
    data = call.data or ""

    # Всегда логируем клики и апсертим пользователя
    upsert_user(call.from_user)
    log_event(call.from_user.id, "callback", data)

    # Для всех веток, кроме «about» или чисто справочных, требуем подписку
    if data not in ("about",) and not is_subscribed(call.from_user.id):
        bot.send_message(call.message.chat.id, "🚫 Для использования бота нужно подписаться на наш канал!", reply_markup=subscribe_kb())
        return

    # ---------- Пользовательская часть ----------
    if data.startswith("g:"):
        # Пользователь выбрал игру
        game_id = int(data.split(":")[1])
        row = get_game(game_id)
        if row and row["url"]:
            bot.send_message(
                call.message.chat.id,
                f"<b>{row['title']}</b>\nЕсли ссылка не открывается — попробуйте позже.",
                reply_markup=links_kb({row["title"]: row["url"]})
            )
        else:
            bot.send_message(call.message.chat.id, "⚠️ Ссылка для этой игры пока не задана.")

    elif data == "about":
        bot.send_message(call.message.chat.id, "Этот бот выдаёт VIP-ссылки на Roblox сервера (приватные комнаты для игры с друзьями).")

    elif data == "list_all":
        rows = list_games(0, 1000)
        links = {r["title"]: r["url"] for r in rows if r["url"]}
        if not links:
            bot.send_message(call.message.chat.id, "⚠️ Ссылки пока не заданы.")
        else:
            bot.send_message(call.message.chat.id, "<b>Ссылки на все игры:</b>", reply_markup=links_kb(links))

    elif data == "back_main":
        try:
            bot.edit_message_text("Выбери игру ниже 👇", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=main_menu_kb())
        except Exception:
            bot.send_message(call.message.chat.id, "Выбери игру ниже 👇", reply_markup=main_menu_kb())

    # ---------- Админ-панель ----------
    elif data == "adm:root":
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Только для админов")
            return
        bot.send_message(call.message.chat.id, "<b>Админ-панель</b> — выберите раздел:", reply_markup=admin_root_kb())

    # Раздел «Игры» с пагинацией
    elif data.startswith("adm:games:"):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Только для админов")
            return
        page = int(data.split(":")[2])
        bot.send_message(call.message.chat.id, "<b>🎮 Игры</b>", reply_markup=admin_games_kb(page))

    elif data == "adm:game:add":
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Только для админов")
            return
        # Шаг 1: запросим название игры
        PENDING_ACTIONS[call.from_user.id] = {"type": "add_game_title", "data": {}}
        bot.send_message(call.message.chat.id, "🆕 Введите <b>название игры</b>:\n(или напишите <code>отмена</code>)")

    elif data.startswith("adm:game:edit:"):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Только для админов")
            return
        game_id = int(data.split(":")[3])
        row = get_game(game_id)
        if not row:
            bot.send_message(call.message.chat.id, "Игра не найдена.")
            return
        # Предложим ввести новую ссылку
        PENDING_ACTIONS[call.from_user.id] = {"type": "edit_game_url", "data": {"game_id": game_id}}
        bot.send_message(call.message.chat.id, f"✏️ Введите <b>новую ссылку</b> для <b>{row['title']}</b>:\n(или <code>отмена</code>)")

    # Раздел «Пользователи» с пагинацией
    elif data.startswith("adm:users:"):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Только для админов")
            return
        page = int(data.split(":")[2])
        bot.send_message(call.message.chat.id, "<b>📊 Пользователи</b>", reply_markup=admin_users_kb(page))

    # Логи конкретного пользователя (с пагинацией)
    elif data.startswith("adm:user:"):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Только для админов")
            return
        _, _, user_id_str, page_str = data.split(":")
        tg_user_id = int(user_id_str)
        page = int(page_str)
        # Покажем часть логов
        page_size = 20
        offset = page * page_size
        events = list_user_events(tg_user_id, offset, page_size)
        total = count_user_events(tg_user_id)

        if not events:
            bot.send_message(call.message.chat.id, "Логи пусты.")
        else:
            lines = [f"<b>Логи пользователя {tg_user_id}</b> (всего {total}):"]
            for e in events:
                lines.append(f"• [{e['created_at']}] <i>{e['type']}</i>: {telebot.util.escape(e['content']) if hasattr(telebot, 'util') else e['content']}")
            bot.send_message(call.message.chat.id, "\n".join(lines), reply_markup=admin_user_logs_kb(tg_user_id, page))

# ==================== Обработка пошаговых действий (админ) ====================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def any_text_logger(message: Message):
    """
    1) Логируем любое текстовое сообщение.
    2) Если у пользователя есть активное "ожидание шага" из админ-панели — обрабатываем его.
    """
    # Всегда апсертим пользователя и пишем лог
    upsert_user(message.from_user)
    log_event(message.from_user.id, "message", message.text or "")

    # Обработка активных шагов только для админов
    state = PENDING_ACTIONS.get(message.from_user.id)
    if not state or not is_admin(message.from_user.id):
        return  # для обычных сообщений ничего не делаем

    text = (message.text or "").strip()

    # Общее слово для отмены
    if text.lower() == "отмена":
        PENDING_ACTIONS.pop(message.from_user.id, None)
        bot.reply_to(message, "❎ Действие отменено.")
        return

    # --- Добавление игры: шаг 1 — ввод названия
    if state["type"] == "add_game_title":
        # Сохраним название и спросим ссылку
        state["type"] = "add_game_url"
        state["data"]["title"] = text
        bot.reply_to(message, "🔗 Теперь отправьте <b>ссылку</b> (URL) на VIP/приватный сервер для этой игры:\n(или <code>отмена</code>)")
        return

    # --- Добавление игры: шаг 2 — ввод ссылки
    if state["type"] == "add_game_url":
        if not validate_url(text):
            bot.reply_to(message, "❌ Это не похоже на ссылку. Отправьте корректный URL или напишите <code>отмена</code>.")
            return
        title = state["data"]["title"]
        game_id = add_game(title, text)
        PENDING_ACTIONS.pop(message.from_user.id, None)
        bot.reply_to(message, f"✅ Игра <b>{title}</b> добавлена (id={game_id}).", reply_markup=admin_games_kb(0))
        return

    # --- Редактирование ссылки игры
    if state["type"] == "edit_game_url":
        game_id = state["data"]["game_id"]
        if not validate_url(text):
            bot.reply_to(message, "❌ Это не похоже на ссылку. Отправьте корректный URL или напишите <code>отмена</code>.")
            return
        update_game_url(game_id, text)
        row = get_game(game_id)
        PENDING_ACTIONS.pop(message.from_user.id, None)
        bot.reply_to(message, f"✅ Ссылка обновлена для <b>{row['title']}</b>.", reply_markup=admin_games_kb(0))
        return

# ==================== Точка входа ====================
if __name__ == "__main__":
    # Инициализация БД и начальных данных
    init_db()
    seed_initial_games_if_empty()

    logger.info("Бот запущен.")
    # Надёжный polling (не падает при единичных сетевых ошибках)
    bot.infinity_polling(timeout=60, long_polling_timeout=50)
