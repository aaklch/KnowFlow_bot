"""Цифровой ассистент для онбординга (Telegram, aiogram 3.x)."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

import db

TOKEN = os.getenv("BOT_TOKEN")
MENTOR_ID = int(os.getenv("MENTOR_ID", "0"))  # Telegram ID наставника (узнать у @userinfobot)
REMIND_EVERY_SEC = 24 * 60 * 60

dp = Dispatcher()

BTN_PLAN, BTN_ASK, BTN_HELP = "📋 Мой план", "❓ Спросить", "ℹ️ Помощь"
MENU = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_PLAN), KeyboardButton(text=BTN_ASK)],
              [KeyboardButton(text=BTN_HELP)]],
    resize_keyboard=True)


def is_mentor(tg_id: int) -> bool:
    return tg_id == MENTOR_ID


def plan_view(user):
    rows = db.plan_for(user["id"])
    lines, buttons = ["План адаптации:\n"], []
    for s in rows:
        mark = "✅" if s["done_at"] else "⬜"
        lines.append(f"{mark} [{s['stage']}] {s['text']}")
        if not s["done_at"]:
            buttons.append([InlineKeyboardButton(
                text=f"Выполнено: {s['text'][:30]}…", callback_data=f"done:{s['id']}")])
    done = sum(1 for s in rows if s["done_at"])
    lines.append(f"\nПрогресс: {done} из {len(rows)}")
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("start"))
async def cmd_start(m: Message):
    role = "mentor" if is_mentor(m.from_user.id) else "newbie"
    db.register_user(m.from_user.id, m.from_user.full_name, role)
    await m.answer(
        f"Здравствуйте, {m.from_user.first_name}! Я помощник по адаптации.\n"
        "Задайте вопрос обычным сообщением или откройте свой план адаптации.",
        reply_markup=MENU)


@dp.message(Command("help"))
@dp.message(F.text == BTN_HELP)
async def cmd_help(m: Message):
    text = ("Что я умею:\n• отвечать на вопросы по базе знаний (просто напишите вопрос);\n"
            "• показывать план адаптации (📋 Мой план);\n"
            "• напоминать о невыполненных шагах (/remind);\n"
            "• передавать наставнику вопросы, на которые нет ответа.")
    if is_mentor(m.from_user.id):
        text += "\n\nКоманда наставника: /stats - статистика."
    await m.answer(text)


@dp.message(F.text == BTN_ASK)
async def ask_hint(m: Message):
    await m.answer("Напишите ваш вопрос, например: «как подключиться к VPN?»")


@dp.message(F.text == BTN_PLAN)
@dp.message(Command("plan"))
async def show_plan(m: Message):
    user = db.get_user(m.from_user.id) or db.register_user(m.from_user.id, m.from_user.full_name)
    text, kb = plan_view(user)
    db.log_event(user["id"], "plan_open")
    await m.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("done:"))
async def step_done(c: CallbackQuery):
    user = db.get_user(c.from_user.id)
    db.mark_done(user["id"], int(c.data.split(":")[1]))
    db.log_event(user["id"], "step_done")
    text, kb = plan_view(user)
    await c.message.edit_text(text, reply_markup=kb)
    await c.answer("Шаг отмечен")


@dp.message(Command("remind"))
async def remind_me(m: Message):
    user = db.get_user(m.from_user.id)
    if not user:
        return await m.answer("Сначала нажмите /start")
    await send_reminder(m.bot, user, force=True)


async def send_reminder(bot: Bot, user, force: bool = False):
    due = db.due_steps(user)
    if not due:
        if force:
            await bot.send_message(user["telegram_id"], "Все шаги на сегодня выполнены 👍")
        return
    text = "Напоминание. Не выполнены шаги плана:\n" + "\n".join(f"• {s['text']}" for s in due)
    await bot.send_message(user["telegram_id"], text)
    db.log_event(user["id"], "reminder")


async def reminder_loop(bot: Bot):
    while True:
        await asyncio.sleep(REMIND_EVERY_SEC)
        for u in db.newbies():
            try:
                await send_reminder(bot, u)
            except Exception as e:  # пользователь мог заблокировать бота
                logging.warning("reminder failed: %s", e)


@dp.message(Command("stats"))
async def cmd_stats(m: Message):
    if not is_mentor(m.from_user.id):
        return await m.answer("Команда доступна только наставнику.")
    s = db.stats()
    rating = f"{s['avg_rating']:.2f}" if s["avg_rating"] is not None else "нет оценок"
    await m.answer(
        "Статистика ассистента:\n"
        f"Новичков: {s['newbies']}\n"
        f"Вопросов всего: {s['questions']}\n"
        f"Закрыто ботом: {s['answered']} ({s['coverage']} %)\n"
        f"Пробелов в базе знаний: {s['gaps']}\n"
        f"Средняя оценка ответов (0-1): {rating}\n"
        f"Шагов плана выполнено: {s['steps_done']}")


@dp.message(Command("gaps"))
async def cmd_gaps(m: Message):
    if not is_mentor(m.from_user.id):
        return await m.answer("Команда доступна только наставнику.")
    con = db.connect()
    rows = con.execute("SELECT question, created_at FROM gaps ORDER BY id DESC LIMIT 10").fetchall()
    con.close()
    await m.answer("Вопросы без ответа:\n" + ("\n".join(f"• {r['question']}" for r in rows) or "пока нет"))


@dp.callback_query(F.data.startswith("rate:"))
async def rate(c: CallbackQuery):
    _, eid, val = c.data.split(":")
    db.set_rating(int(eid), int(val))
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer("Спасибо за оценку!")


@dp.message(F.text & ~F.text.startswith("/"))
async def question(m: Message):
    user = db.get_user(m.from_user.id) or db.register_user(m.from_user.id, m.from_user.full_name)
    found = db.search_articles(m.text, limit=3)
    if found:
        eid = db.log_event(user["id"], "answered")
        top = found[0]
        text = f"{top['title']}\n\n{top['body']}\n\nВладелец материала: {top['owner']}"
        if len(found) > 1:
            text += "\n\nПохожие темы: " + "; ".join(a["title"] for a in found[1:])
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="👍 Помогло", callback_data=f"rate:{eid}:1"),
            InlineKeyboardButton(text="👎 Не помогло", callback_data=f"rate:{eid}:0")]])
        await m.answer(text, reply_markup=kb)
    else:
        db.add_gap(user["id"], m.text)
        db.log_event(user["id"], "gap")
        await m.answer("Не нашёл ответа в базе знаний. Я передал вопрос наставнику, "
                       "он ответит и дополнит базу.")
        if MENTOR_ID:
            await m.bot.send_message(
                MENTOR_ID, f"Вопрос без ответа от {m.from_user.full_name}:\n{m.text}")


async def main():
    if not TOKEN:
        raise SystemExit("Задайте переменную окружения BOT_TOKEN")
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    bot = Bot(TOKEN)
    asyncio.create_task(reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
