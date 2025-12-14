import asyncio
import csv
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

API_TOKEN = os.getenv("API_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")

# ---------- Работа с базой данных ----------

def init_db():
    """
    Инициализация базы данных: создание соединения и таблицы tasks,
    если она ещё не существует.
    """
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            user INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Новый',
            category TEXT NOT NULL DEFAULT 'Неважная'
        )
        """
    )
    # Добавляем новые колонки, если они ещё не существуют (миграция для старых БД)
    try:
        cursor.execute("ALTER TABLE tasks ADD COLUMN status TEXT DEFAULT 'Новый'")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует
    
    try:
        cursor.execute("ALTER TABLE tasks ADD COLUMN category TEXT DEFAULT 'Неважная'")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует
    
    # Обновляем старые записи без статуса и категории
    cursor.execute("UPDATE tasks SET status = 'Новый' WHERE status IS NULL")
    cursor.execute("UPDATE tasks SET category = 'Неважная' WHERE category IS NULL")
    
    conn.commit()
    conn.close()

def add_task(text: str, user_id: int, status: str = "Новый", category: str = "Неважная"):
    """
    Добавление новой задачи в таблицу tasks.
    """
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    created_at = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "INSERT INTO tasks(text, user, created_at, status, category) VALUES (?, ?, ?, ?, ?)",
        (text, user_id, created_at, status, category),
    )
    conn.commit()
    conn.close()

def get_tasks(user_id: int):
    """
    Получение всех задач конкретного пользователя.
    Возвращает список кортежей (id, text, created_at, status, category).
    """
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, text, created_at, status, category FROM tasks WHERE user = ? ORDER BY id",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_task(task_id: int, user_id: int):
    """
    Получение конкретной задачи по ID.
    Возвращает кортеж (id, text, created_at, status, category) или None.
    """
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, text, created_at, status, category FROM tasks WHERE id = ? AND user = ?",
        (task_id, user_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row

def update_task(task_id: int, user_id: int, status: str = None, category: str = None):
    """
    Обновление статуса и/или категории задачи.
    """
    conn = sqlite3.connect("tasks.db")
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    
    if category is not None:
        updates.append("category = ?")
        params.append(category)
    
    if updates:
        params.extend([task_id, user_id])
        query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ? AND user = ?"
        cursor.execute(query, params)
        conn.commit()
    
    conn.close()

def export_tasks_to_csv(user_id: int) -> str:
    """
    Выгрузка задач пользователя в CSV-файл.
    Возвращает путь к созданному файлу.
    """
    tasks = get_tasks(user_id)
    filename = f"tasks_{user_id}.csv"
    # создаём CSV-файл с заголовками колонок
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "text", "user", "created_at", "status", "category"])
        for t_id, text, created_at, status, category in tasks:
            writer.writerow([t_id, text, user_id, created_at, status, category])
    return filename

# ---------- Настройка бота и хендлеров ----------

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Словарь для хранения состояний пользователей (ожидание ввода задачи)
user_states = {}
# Словарь для временного хранения текста задач при создании (user_id -> task_text)
pending_tasks = {}

# Создаём клавиатуру с основными командами
def get_main_keyboard():
    """Создаёт главную клавиатуру с кнопками команд."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить задачу"), KeyboardButton(text="📋 Список задач")],
            [KeyboardButton(text="✏️ Редактировать задачу"), KeyboardButton(text="📥 Экспорт CSV")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери команду или используй /start"
    )
    return keyboard

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """
    Обработка команды /start.
    Отправляет приветственное сообщение и показывает клавиатуру с кнопками.
    """
    await message.answer(
        "Привет! Это простой бот для хранения задач.\n\n"
        "Используй кнопки ниже или команды:\n"
        "/add <текст задачи> — добавить задачу\n"
        "/list — показать все задачи\n"
        "/edit — выбрать задачу для изменения статуса и категории\n"
        "/list_csv — получить задачи в виде CSV файла\n\n"
        "Статусы: Новый, Выполнена\n"
        "Категории: Важная, Неважная",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("add"))
async def cmd_add(message: Message):
    """
    Обработка команды /add.
    Ожидает текст задачи после команды и предлагает выбрать статус и категорию.
    """
    user_id = message.from_user.id
    # Очищаем предыдущие состояния
    pending_tasks.pop(user_id, None)
    # текст после команды, например: "/add купить молоко"
    # убираем саму команду и возможные лишние пробелы
    task_text = message.text.replace("/add", "", 1).strip()
    if not task_text:
        await message.answer("Пожалуйста, укажи текст задачи после команды /add.", reply_markup=get_main_keyboard())
        return
    
    # Сохраняем текст задачи временно
    pending_tasks[user_id] = task_text
    user_states[user_id] = "selecting_status"
    
    # Показываем кнопки для выбора статуса
    status_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🆕 Новый", callback_data=f"new_task_status_{user_id}_Новый"),
                InlineKeyboardButton(text="✅ Выполнена", callback_data=f"new_task_status_{user_id}_Выполнена")
            ]
        ]
    )
    await message.answer(
        f"Задача: {task_text}\n\nВыбери статус:",
        reply_markup=status_keyboard
    )

# Обработчик кнопки "Добавить задачу"
@dp.message(F.text == "➕ Добавить задачу")
async def handle_add_task_button(message: Message):
    """Обработчик кнопки 'Добавить задачу'."""
    user_id = message.from_user.id
    # Очищаем предыдущие состояния
    pending_tasks.pop(user_id, None)
    user_states[user_id] = "waiting_for_task"
    await message.answer(
        "Введи текст задачи, которую хочешь добавить:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True
        )
    )

@dp.message(Command("list"))
async def cmd_list(message: Message):
    """
    Обработка команды /list.
    Показывает все задачи пользователя в виде текста с статусом и категорией.
    """
    user_id = message.from_user.id
    user_states.pop(user_id, None)  # Сбрасываем состояние
    pending_tasks.pop(user_id, None)  # Очищаем временные данные
    tasks = get_tasks(user_id)
    if not tasks:
        await message.answer("У тебя пока нет задач.", reply_markup=get_main_keyboard())
        return
    
    lines = []
    for t_id, text, created_at, status, category in tasks:
        status_emoji = "✅" if status == "Выполнена" else "🆕"
        category_emoji = "🔴" if category == "Важная" else "⚪"
        lines.append(f"{t_id}. {status_emoji} {category_emoji} {text}\n   Статус: {status} | Категория: {category} | Создано: {created_at}")
    
    await message.answer("\n\n".join(lines), reply_markup=get_main_keyboard())

# Обработчик кнопки "Список задач"
@dp.message(F.text == "📋 Список задач")
async def handle_list_button(message: Message):
    """Обработчик кнопки 'Список задач'."""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    pending_tasks.pop(user_id, None)
    await cmd_list(message)

@dp.message(Command("edit"))
async def cmd_edit(message: Message):
    """
    Обработка команды /edit.
    Показывает список задач с inline-кнопками для выбора и редактирования.
    """
    user_id = message.from_user.id
    user_states.pop(user_id, None)  # Сбрасываем состояние
    pending_tasks.pop(user_id, None)  # Очищаем временные данные
    tasks = get_tasks(user_id)
    if not tasks:
        await message.answer("У тебя пока нет задач для редактирования.", reply_markup=get_main_keyboard())
        return
    
    # Создаём inline-кнопки для каждой задачи
    keyboard = []
    for t_id, text, created_at, status, category in tasks:
        status_emoji = "✅" if status == "Выполнена" else "🆕"
        category_emoji = "🔴" if category == "Важная" else "⚪"
        button_text = f"{t_id}. {status_emoji} {category_emoji} {text[:30]}"
        if len(text) > 30:
            button_text += "..."
        keyboard.append([InlineKeyboardButton(
            text=button_text,
            callback_data=f"task_{t_id}"
        )])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer("Выбери задачу для редактирования:", reply_markup=reply_markup)

# Обработчик кнопки "Редактировать задачу"
@dp.message(F.text == "✏️ Редактировать задачу")
async def handle_edit_button(message: Message):
    """Обработчик кнопки 'Редактировать задачу'."""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    pending_tasks.pop(user_id, None)
    await cmd_edit(message)

async def show_task_edit_menu(callback: CallbackQuery, task_id: int):
    """
    Вспомогательная функция для отображения меню редактирования задачи.
    """
    task = get_task(task_id, callback.from_user.id)
    
    if not task:
        await callback.answer("Задача не найдена!", show_alert=True)
        return
    
    t_id, text, created_at, status, category = task
    
    # Создаём кнопки для изменения статуса
    status_keyboard = []
    status_keyboard.append([
        InlineKeyboardButton(
            text="✅ Выполнена" if status == "Выполнена" else "Выполнена",
            callback_data=f"status_{t_id}_Выполнена"
        ),
        InlineKeyboardButton(
            text="🆕 Новый" if status == "Новый" else "Новый",
            callback_data=f"status_{t_id}_Новый"
        )
    ])
    
    # Создаём кнопки для изменения категории
    status_keyboard.append([
        InlineKeyboardButton(
            text="🔴 Важная" if category == "Важная" else "Важная",
            callback_data=f"category_{t_id}_Важная"
        ),
        InlineKeyboardButton(
            text="⚪ Неважная" if category == "Неважная" else "Неважная",
            callback_data=f"category_{t_id}_Неважная"
        )
    ])
    
    status_keyboard.append([
        InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_list")
    ])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=status_keyboard)
    
    status_emoji = "✅" if status == "Выполнена" else "🆕"
    category_emoji = "🔴" if category == "Важная" else "⚪"
    
    await callback.message.edit_text(
        f"Задача #{t_id}: {status_emoji} {category_emoji} {text}\n\n"
        f"Текущий статус: {status}\n"
        f"Текущая категория: {category}\n\n"
        f"Выбери действие:",
        reply_markup=reply_markup
    )

@dp.callback_query(F.data.startswith("task_"))
async def process_task_selection(callback: CallbackQuery):
    """
    Обработка выбора задачи. Показывает кнопки для изменения статуса и категории.
    """
    task_id = int(callback.data.split("_")[1])
    await show_task_edit_menu(callback, task_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("status_"))
async def process_status_change(callback: CallbackQuery):
    """
    Обработка изменения статуса задачи.
    """
    parts = callback.data.split("_")
    task_id = int(parts[1])
    new_status = parts[2]
    
    task = get_task(task_id, callback.from_user.id)
    if not task:
        await callback.answer("Задача не найдена!", show_alert=True)
        return
    
    update_task(task_id, callback.from_user.id, status=new_status)
    await callback.answer(f"Статус изменён на: {new_status}")
    
    # Обновляем сообщение
    await show_task_edit_menu(callback, task_id)

@dp.callback_query(F.data.startswith("category_"))
async def process_category_change(callback: CallbackQuery):
    """
    Обработка изменения категории задачи.
    """
    parts = callback.data.split("_")
    task_id = int(parts[1])
    new_category = parts[2]
    
    task = get_task(task_id, callback.from_user.id)
    if not task:
        await callback.answer("Задача не найдена!", show_alert=True)
        return
    
    update_task(task_id, callback.from_user.id, category=new_category)
    await callback.answer(f"Категория изменена на: {new_category}")
    
    # Обновляем сообщение
    await show_task_edit_menu(callback, task_id)

# Обработчик выбора статуса при создании новой задачи
@dp.callback_query(F.data.startswith("new_task_status_"))
async def process_new_task_status(callback: CallbackQuery):
    """
    Обработка выбора статуса при создании новой задачи.
    """
    parts = callback.data.split("_")
    user_id = int(parts[3])
    selected_status = parts[4]
    
    # Проверяем, что это тот же пользователь
    if callback.from_user.id != user_id:
        await callback.answer("Это не твоя задача!", show_alert=True)
        return
    
    task_text = pending_tasks.get(user_id)
    if not task_text:
        await callback.answer("Текст задачи не найден. Начни заново.", show_alert=True)
        user_states.pop(user_id, None)
        await callback.message.edit_text("Произошла ошибка. Попробуй добавить задачу заново.")
        return
    
    # Сохраняем выбранный статус
    user_states[user_id] = {"status": selected_status, "text": task_text}
    
    # Показываем кнопки для выбора категории
    category_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 Важная", callback_data=f"new_task_category_{user_id}_Важная"),
                InlineKeyboardButton(text="⚪ Неважная", callback_data=f"new_task_category_{user_id}_Неважная")
            ]
        ]
    )
    
    status_emoji = "✅" if selected_status == "Выполнена" else "🆕"
    await callback.message.edit_text(
        f"Задача: {task_text}\n"
        f"Статус: {status_emoji} {selected_status}\n\n"
        f"Выбери категорию:",
        reply_markup=category_keyboard
    )
    await callback.answer(f"Статус: {selected_status}")

# Обработчик выбора категории при создании новой задачи
@dp.callback_query(F.data.startswith("new_task_category_"))
async def process_new_task_category(callback: CallbackQuery):
    """
    Обработка выбора категории при создании новой задачи.
    """
    parts = callback.data.split("_")
    user_id = int(parts[3])
    selected_category = parts[4]
    
    # Проверяем, что это тот же пользователь
    if callback.from_user.id != user_id:
        await callback.answer("Это не твоя задача!", show_alert=True)
        return
    
    user_state = user_states.get(user_id)
    if not user_state or not isinstance(user_state, dict):
        await callback.answer("Данные не найдены. Начни заново.", show_alert=True)
        user_states.pop(user_id, None)
        pending_tasks.pop(user_id, None)
        await callback.message.edit_text("Произошла ошибка. Попробуй добавить задачу заново.")
        return
    
    task_text = user_state.get("text")
    selected_status = user_state.get("status", "Новый")
    
    # Сохраняем задачу
    add_task(task_text, user_id, status=selected_status, category=selected_category)
    
    # Очищаем временные данные
    user_states.pop(user_id, None)
    pending_tasks.pop(user_id, None)
    
    status_emoji = "✅" if selected_status == "Выполнена" else "🆕"
    category_emoji = "🔴" if selected_category == "Важная" else "⚪"
    
    await callback.message.edit_text(
        f"✅ Задача добавлена!\n\n"
        f"Задача: {task_text}\n"
        f"Статус: {status_emoji} {selected_status}\n"
        f"Категория: {category_emoji} {selected_category}"
    )
    await callback.answer(f"Задача добавлена!")
    
    # Отправляем подтверждение с клавиатурой
    await callback.message.answer("Что дальше?", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "back_to_list")
async def back_to_list(callback: CallbackQuery):
    """
    Возврат к списку задач.
    """
    tasks = get_tasks(callback.from_user.id)
    if not tasks:
        await callback.message.edit_text("У тебя пока нет задач для редактирования.")
        await callback.answer()
        return
    
    keyboard = []
    for t_id, text, created_at, status, category in tasks:
        status_emoji = "✅" if status == "Выполнена" else "🆕"
        category_emoji = "🔴" if category == "Важная" else "⚪"
        button_text = f"{t_id}. {status_emoji} {category_emoji} {text[:30]}"
        if len(text) > 30:
            button_text += "..."
        keyboard.append([InlineKeyboardButton(
            text=button_text,
            callback_data=f"task_{t_id}"
        )])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await callback.message.edit_text("Выбери задачу для редактирования:", reply_markup=reply_markup)
    await callback.answer()

@dp.message(Command("list_csv"))
async def cmd_list_csv(message: Message):
    """
    Обработка команды /list_csv.
    Формирует CSV-файл с задачами пользователя и отправляет его.
    """
    user_id = message.from_user.id
    user_states.pop(user_id, None)  # Сбрасываем состояние
    pending_tasks.pop(user_id, None)  # Очищаем временные данные
    tasks = get_tasks(user_id)
    if not tasks:
        await message.answer("У тебя пока нет задач для выгрузки.", reply_markup=get_main_keyboard())
        return
    
    try:
        filepath = export_tasks_to_csv(user_id)
        # отправляем файл как документ
        doc = FSInputFile(filepath)
        await message.answer_document(
            document=doc,
            caption="Вот твои задачи в формате CSV.",
        )
        # удаляем временный файл после отправки
        os.remove(filepath)
    except Exception as e:
        await message.answer(f"Произошла ошибка при создании файла: {e}", reply_markup=get_main_keyboard())

# Обработчик кнопки "Экспорт CSV"
@dp.message(F.text == "📥 Экспорт CSV")
async def handle_export_button(message: Message):
    """Обработчик кнопки 'Экспорт CSV'."""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    pending_tasks.pop(user_id, None)
    await cmd_list_csv(message)

# Обработчик кнопки "Отмена"
@dp.message(F.text == "❌ Отмена")
async def handle_cancel_button(message: Message):
    """Обработчик кнопки 'Отмена'."""
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    pending_tasks.pop(user_id, None)
    await message.answer("Отменено.", reply_markup=get_main_keyboard())

# Обработчик текстовых сообщений (для ввода задачи)
@dp.message(F.text)
async def handle_text_message(message: Message):
    """
    Обработчик всех текстовых сообщений.
    Если пользователь находится в состоянии ожидания задачи, сохраняет её.
    """
    user_id = message.from_user.id
    
    # Проверяем, ожидается ли ввод задачи
    if user_states.get(user_id) == "waiting_for_task":
        task_text = message.text.strip()
        if task_text:
            # Сохраняем текст задачи временно
            pending_tasks[user_id] = task_text
            user_states[user_id] = "selecting_status"
            
            # Показываем кнопки для выбора статуса
            status_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🆕 Новый", callback_data=f"new_task_status_{user_id}_Новый"),
                        InlineKeyboardButton(text="✅ Выполнена", callback_data=f"new_task_status_{user_id}_Выполнена")
                    ]
                ]
            )
            await message.answer(
                f"Задача: {task_text}\n\nВыбери статус:",
                reply_markup=status_keyboard
            )
        else:
            await message.answer("Текст задачи не может быть пустым. Попробуй ещё раз или нажми '❌ Отмена'.")
        return
    
    # Если сообщение не было обработано другими хендлерами, показываем подсказку
    await message.answer(
        "Используй кнопки внизу экрана или команды для работы с ботом.\n"
        "Нажми /start для справки.",
        reply_markup=get_main_keyboard()
    )

async def main():
    """
    Точка входа приложения.
    Инициализирует базу данных и запускает бота.
    """
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

