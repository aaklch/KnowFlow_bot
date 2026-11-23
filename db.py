"""Слой данных: SQLite, поиск по базе знаний, метрики."""
import re
import sqlite3
from datetime import date

DB_PATH = "onboarding.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    name TEXT,
    role TEXT NOT NULL DEFAULT 'newbie',
    hire_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS articles(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT DEFAULT '',
    owner TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS steps(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT NOT NULL,
    day_offset INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS progress(
    user_id INTEGER NOT NULL,
    step_id INTEGER NOT NULL,
    done_at TEXT NOT NULL,
    PRIMARY KEY(user_id, step_id)
);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    rating INTEGER
);
CREATE TABLE IF NOT EXISTS gaps(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# ---- Демонстрационная база знаний: ЗАМЕНИТЕ на реальные данные организации ----
ARTICLES = [
    ("Доступы к рабочим системам",
     "Заявку на доступы (почта, Jira, Confluence, Git) создайте в сервис-деске в первый день. "
     "Срок выдачи - до 1 рабочего дня. Если доступ не появился, напишите наставнику.",
     "доступ доступы учетная запись пароль логин jira confluence git", "ИТ-отдел"),
    ("Подключение к VPN",
     "Установите VPN-клиент из раздела «Софт» на портале, импортируйте профиль из письма "
     "и войдите под корпоративной учётной записью. Для сброса пароля обратитесь в ИТ-отдел.",
     "vpn впн удаленный подключение сеть клиент", "ИТ-отдел"),
    ("Где находится документация",
     "Регламенты и инструкции хранятся в корпоративной вики (Confluence), раздел «Онбординг». "
     "Документация по проектам лежит в репозиториях Git в папке docs.",
     "документация вики wiki регламент инструкция confluence readme", "Тимлид"),
    ("Как работать с задачами",
     "Все задачи ведутся в Jira. Берите задачу из колонки To Do, переводите в In Progress, "
     "после проверки кода - в Review, затем в Done. Статус обновляйте ежедневно.",
     "задача задачи jira статус тикет спринт канбан доска", "Тимлид"),
    ("Правила код-ревью",
     "Каждый pull request проверяет минимум один коллега. Ветку называйте feature/номер-задачи. "
     "Запрос должен быть небольшим и содержать описание изменений и ссылку на задачу.",
     "код ревью review pull request merge ветка git коммит", "Старший разработчик"),
    ("Рабочий график и часы",
     "Рабочий день с 9:00 до 18:00, обед 13:00-14:00. Ежедневная планёрка в 10:00 в мессенджере. "
     "О задержке или отсутствии сообщайте руководителю заранее.",
     "график время часы рабочий день планерка обед опоздание", "HR"),
    ("Отпуск и больничный",
     "Заявление на отпуск подаётся не позднее чем за 14 дней через кадровую службу. "
     "При болезни сообщите руководителю в день заболевания и передайте больничный в HR.",
     "отпуск больничный болезнь заявление отгул выходной", "HR"),
    ("Кто к кому обращается",
     "По рабочим вопросам - к наставнику. По доступам и технике - в ИТ-отдел. "
     "По документам, отпуску и зарплате - в HR. По требованиям к продукту - к руководителю проекта.",
     "контакты кому обратиться вопрос наставник руководитель hr поддержка", "HR"),
    ("Настройка рабочего окружения",
     "Установите IDE, Git, Docker и клиент базы данных. Склонируйте репозиторий проекта "
     "и следуйте README: создайте виртуальное окружение и запустите проект локально.",
     "окружение установка ide docker git настройка проект запуск репозиторий", "Тимлид"),
    ("Информационная безопасность",
     "Не передавайте пароли и коды доступа третьим лицам, не храните рабочие данные в личных облаках. "
     "О подозрительных письмах сообщайте в ИТ-отдел. Блокируйте экран при уходе.",
     "безопасность пароль защита данные фишинг письмо политика", "ИТ-отдел"),
    ("Корпоративная почта и мессенджеры",
     "Рабочая переписка ведётся в корпоративной почте и общем чате команды. "
     "Срочные вопросы - в чат, формальные - письмом. В отпуске включите автоответ.",
     "почта мессенджер чат telegram письмо переписка связь", "ИТ-отдел"),
    ("Испытательный срок",
     "Испытательный срок - 3 месяца. На 30, 60 и 90 день проходят встречи с руководителем "
     "для обратной связи. Цели срока фиксируются в плане адаптации.",
     "испытательный срок оценка цели встреча обратная связь адаптация", "HR"),
]

STEPS = [
    ("Preboarding", -1, "Проверьте адрес офиса, время начала и контакт наставника в письме от HR."),
    ("День 1", 0, "Получите доступы по чек-листу: почта, Jira, Confluence, Git, VPN."),
    ("День 1", 0, "Познакомьтесь с командой и наставником, получите карту команды."),
    ("Неделя 1", 2, "Настройте рабочее окружение и запустите проект локально."),
    ("Неделя 1", 4, "Изучите раздел «Онбординг» в вики и правила код-ревью."),
    ("Месяц 1", 7, "Выполните первую небольшую задачу под контролем наставника."),
    ("Месяц 1", 30, "Пройдите опрос удовлетворённости и встречу с руководителем (30 дней)."),
    ("Испытательный срок", 60, "Встреча с руководителем: промежуточная оценка (60 дней)."),
]


def connect(path: str = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db(path: str = None) -> None:
    con = connect(path)
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0:
        today = date.today().isoformat()
        con.executemany(
            "INSERT INTO articles(title, body, tags, owner, updated_at) VALUES(?,?,?,?,?)",
            [(t, b, g, o, today) for t, b, g, o in ARTICLES])
    if con.execute("SELECT COUNT(*) FROM steps").fetchone()[0] == 0:
        con.executemany("INSERT INTO steps(stage, day_offset, text) VALUES(?,?,?)", STEPS)
    con.commit()
    con.close()


# ---- Пользователи ----
def register_user(tg_id: int, name: str, role: str = "newbie", path: str = None) -> sqlite3.Row:
    con = connect(path)
    con.execute(
        "INSERT OR IGNORE INTO users(telegram_id, name, role, hire_date) VALUES(?,?,?,?)",
        (tg_id, name, role, date.today().isoformat()))
    con.execute("UPDATE users SET name=?, role=? WHERE telegram_id=?", (name, role, tg_id))
    con.commit()
    row = con.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
    con.close()
    return row


def get_user(tg_id: int, path: str = None):
    con = connect(path)
    row = con.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
    con.close()
    return row


def newbies(path: str = None):
    con = connect(path)
    rows = con.execute("SELECT * FROM users WHERE role='newbie'").fetchall()
    con.close()
    return rows


# ---- Поиск по базе знаний (листинг 2.1) ----
STOP = {"как", "что", "где", "кто", "это", "для", "или", "при", "над", "под", "мне", "нам",
        "надо", "нужно", "можно", "если", "когда", "какой", "какие", "есть"}


def _tokens(text: str):
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) > 2 and w not in STOP]


def _stem(word: str) -> str:
    """Грубое усечение для учёта русской морфологии: сравниваем по префиксу."""
    return word[:5]


def search_articles(query: str, limit: int = 3, path: str = None):
    stems = {_stem(w) for w in _tokens(query)}
    if not stems:
        return []
    con = connect(path)
    rows = con.execute("SELECT * FROM articles").fetchall()
    con.close()
    scored = []
    for r in rows:
        text_stems = {_stem(w) for w in _tokens(f"{r['title']} {r['tags']} {r['body']}")}
        title_stems = {_stem(w) for w in _tokens(r["title"])}
        score = len(stems & text_stems) + len(stems & title_stems)
        if score:
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


# ---- Сценарий и прогресс ----
def days_since_hire(user) -> int:
    return (date.today() - date.fromisoformat(user["hire_date"])).days


def plan_for(user_id: int, path: str = None):
    con = connect(path)
    rows = con.execute(
        """SELECT s.*, p.done_at FROM steps s
           LEFT JOIN progress p ON p.step_id=s.id AND p.user_id=?
           ORDER BY s.day_offset, s.id""", (user_id,)).fetchall()
    con.close()
    return rows


def mark_done(user_id: int, step_id: int, path: str = None) -> None:
    con = connect(path)
    con.execute("INSERT OR IGNORE INTO progress(user_id, step_id, done_at) VALUES(?,?,datetime('now'))",
                (user_id, step_id))
    con.commit()
    con.close()


def due_steps(user, path: str = None):
    d = days_since_hire(user)
    return [s for s in plan_for(user["id"], path) if s["done_at"] is None and s["day_offset"] <= d]


# ---- Метрики ----
def log_event(user_id: int, type_: str, rating: int = None, path: str = None) -> int:
    con = connect(path)
    cur = con.execute("INSERT INTO events(user_id, type, rating) VALUES(?,?,?)",
                      (user_id, type_, rating))
    con.commit()
    eid = cur.lastrowid
    con.close()
    return eid


def set_rating(event_id: int, rating: int, path: str = None) -> None:
    con = connect(path)
    con.execute("UPDATE events SET rating=? WHERE id=?", (rating, event_id))
    con.commit()
    con.close()


def add_gap(user_id: int, question: str, path: str = None) -> None:
    con = connect(path)
    con.execute("INSERT INTO gaps(user_id, question) VALUES(?,?)", (user_id, question))
    con.commit()
    con.close()


def stats(path: str = None) -> dict:
    con = connect(path)
    q = lambda sql: con.execute(sql).fetchone()[0]
    answered = q("SELECT COUNT(*) FROM events WHERE type='answered'")
    gaps = q("SELECT COUNT(*) FROM gaps")
    total = answered + gaps
    res = {
        "newbies": q("SELECT COUNT(*) FROM users WHERE role='newbie'"),
        "questions": total,
        "answered": answered,
        "gaps": gaps,
        "coverage": round(100 * answered / total, 1) if total else 0.0,
        "avg_rating": con.execute("SELECT AVG(rating) FROM events WHERE rating IS NOT NULL").fetchone()[0],
        "steps_total": q("SELECT COUNT(*) FROM steps"),
        "steps_done": q("SELECT COUNT(*) FROM progress"),
    }
    con.close()
    return res
