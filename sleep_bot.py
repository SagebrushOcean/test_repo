import os
import sqlite3
from telebot import types, TeleBot
from datetime import datetime, timedelta

bot = TeleBot(os.getenv("TG_TOKEN"))

def check_duration(start_time, end_time):
    duration = end_time - start_time
    if timedelta(days=1) < duration:
        return True
    return False

def timedelta_into_str(timedelta_total_seconds):
    return f"{round(timedelta_total_seconds//3600,0)} часов, {round(timedelta_total_seconds%3600//60,0)} минут, {round(timedelta_total_seconds%3600%60,0)} секунд"

def adapt_datetime_iso(val):
    """Adapt datetime.datetime to timezone-naive ISO 8601 date."""
    return val.isoformat()

def convert_datetime(val):
    """Convert ISO 8601 datetime to datetime.datetime object."""
    return datetime.fromisoformat(val.decode())

sqlite3.register_adapter(datetime, adapt_datetime_iso)
sqlite3.register_converter("datetime", convert_datetime)

with sqlite3.connect('sleep_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as con:
    cursor = con.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            current_record INTEGER DEFAULT NULL,
            is_asleep BOOLEAN DEFAULT False);
        CREATE TABLE IF NOT EXISTS sleep_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            sleep_time DATETIME,
            wake_time DATETIME DEFAULT NULL,
            duration FLOAT DEFAULT NULL,
            quality INTEGER DEFAULT "оценка не была внесена",
            notes TEXT DEFAULT "заметок нет")
        """
    )
    con.commit()

@bot.message_handler(commands=["start"])
def start(message):
    user_name = message.from_user.first_name
    user_id = message.from_user.id
    with sqlite3.connect('sleep_bot.db') as con:
        cursor = con.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO users (id,name)
                VALUES (?, ?);
                """,
                (user_id, user_name)
            )
            con.commit()
        except sqlite3.IntegrityError:
            pass
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    button1 = types.KeyboardButton('/sleep')
    button2 = types.KeyboardButton('/wake')
    markup.add(button1, button2)
    bot.send_message(message.chat.id,
                     f'Привет, {user_name}! Я бот, который помогает отслеживать параметры сна. Используйте команды /sleep и /wake, чтобы отметить начало и окончание сна и команды /quality и /notes для оценки его качества.',
                     reply_markup=markup)

@bot.message_handler(commands=["sleep"])
def sleep(message):
    user_id = message.from_user.id
    with sqlite3.connect('sleep_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as con:
        cursor = con.cursor()
        if cursor.execute("""SELECT is_asleep FROM users WHERE id = ?""",(user_id,)).fetchone()[0]:
            bot.send_message(message.chat.id,
                             "Похоже вы забыли сообщить прошлое время пробуждения. Если это действительно так, используйте /delete чтобы удалить неполную запись из базы данных.")
        else:
            cursor.execute(
            """
            INSERT INTO sleep_records (user_id,sleep_time)
            VALUES (?, ?);
            """,
            (user_id, datetime.now())
            )
            current_record = cursor.lastrowid
            cursor.execute(
                """
                UPDATE users SET current_record = ?, is_asleep = ? WHERE id = ?;
                """,
                (current_record, True, user_id)
            )
            con.commit()
            bot.send_message(message.chat.id, "Начали отсчёт сна, когда проснетесь, сообщите командой /wake")

@bot.message_handler(commands=["wake"])
def wake(message):
    user_id = message.from_user.id
    with sqlite3.connect('sleep_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as con:
        cursor = con.cursor()
        if cursor.execute("""SELECT is_asleep FROM users WHERE id = ?""",(user_id,)).fetchone()[0]:
            wake_time = datetime.now()
            sleep_time = cursor.execute(
                """
                SELECT sleep_time FROM sleep_records
                WHERE record_id = (SELECT current_record FROM users WHERE id = ?);
                """,
                (user_id,)).fetchone()[0]
            sleep_duration = wake_time - sleep_time
            cursor.execute(
                """
                UPDATE sleep_records SET wake_time = ?, duration = ?
                WHERE record_id = (SELECT current_record FROM users WHERE id = ?);
                """,
                (wake_time, sleep_duration.total_seconds(), user_id)
            )
            cursor.execute(
                """
                UPDATE users SET is_asleep = ? WHERE id = ?;
                """,
                (False, user_id)
            )
            con.commit()
            if check_duration(sleep_time, wake_time):
                bot.send_message(message.chat.id,
                                 "Ваша продолжительность сна больше 24 часов. Вы уверены, что не пропускали команды? Если пропускали, нажмите /delete чтобы удалить некорректные данные из базы.")
            else:
                bot.send_message(message.chat.id, f"Доброе утро, Вы спали: {timedelta_into_str(sleep_duration.total_seconds())}.")
                bot.send_message(message.chat.id,
                                 "Пожалуйста, оцените качество сна целым числом от 1 до 10 с помощью команды /quality")
        else:
            bot.send_message(message.chat.id, "Вы не указали время начала сна")


@bot.message_handler(commands=["quality"])
def quality(message):
    user_id = message.from_user.id
    with sqlite3.connect('sleep_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as con:
        cursor = con.cursor()
        if cursor.execute("""SELECT is_asleep FROM users WHERE id = ?""",(user_id,)).fetchone()[0]:
            bot.send_message(message.chat.id, "Вы забыли команду /wake")
        elif isinstance(cursor.execute("""SELECT quality FROM sleep_records
                WHERE record_id = (SELECT current_record FROM users WHERE id = ?);""",
                (user_id,)).fetchone()[0],int):
            bot.send_message(message.chat.id,"Вы уже вносили оценку качества сна. Чтобы заменить последнюю оценку используйте команду /change_quality")
        else:
            try:
                int(message.text.split()[1])
                cursor.execute(
                    """
                    UPDATE sleep_records SET quality = ?
                    WHERE record_id = (SELECT current_record FROM users WHERE id = ?);
                    """,
                    (message.text.split()[1], user_id)
                )
                con.commit()
                bot.send_message(message.chat.id,
                                 "Оценка качества сохранена. Оставьте заметку о качестве сна командой /notes")
            except (IndexError,ValueError):
                bot.send_message(message.chat.id, "Команда ожидается в виде '/quality вставьте своё число'")


@bot.message_handler(commands=["notes"])
def notes(message):
    user_id = message.from_user.id
    with sqlite3.connect('sleep_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as con:
        cursor = con.cursor()
        if cursor.execute("""SELECT is_asleep FROM users WHERE id = ?""",(user_id,)).fetchone()[0]:
            bot.send_message(message.chat.id, "Вы забыли команду /wake")
        elif cursor.execute("""SELECT notes FROM sleep_records
                WHERE record_id = (SELECT current_record FROM users WHERE id = ?);""",
                (user_id,)).fetchone()[0] != 'заметок нет':
            bot.send_message(message.chat.id,"Вы уже вносили заметку о качестве сна. Чтобы заменить последнюю заметку используйте команду /change_notes")
        else:
            try:
                cursor.execute(
                    """
                    UPDATE sleep_records SET notes = ?
                    WHERE record_id = (SELECT current_record FROM users WHERE id = ?);
                    """,
                    (message.text.split(" ",1)[1], user_id)
                )
                con.commit()
                bot.send_message(message.chat.id, "Заметка сохранена.")
                bot.send_message(message.chat.id,"Вы можете использовать команду /average чтобы узнать среднюю продолжительность и качество своего сна, а также команду /date дд.мм.гггг чтобы посмотреть параметры сна за конкретный день.")
            except IndexError:
                bot.send_message(message.chat.id, "Команда ожидается в виде '/notes вставьте свой текст'")


@bot.message_handler(commands=["delete"])
def delete(message):
    user_id = message.from_user.id
    with sqlite3.connect('sleep_bot.db') as con:
        cursor = con.cursor()
        cursor.execute(
            """
            DELETE FROM sleep_records 
            WHERE record_id = (SELECT current_record FROM users WHERE id = ?);
            """,
            (user_id,)
        )
        cursor.execute(
            """
            UPDATE users SET is_asleep = ? WHERE id = ?;
            """,
            (False, user_id)
        )
        con.commit()
    bot.send_message(message.chat.id, "Последние данные удалены. Используйте команду /sleep, чтобы начать отсчет времени сна.")

@bot.message_handler(commands=["change_quality"])
def change_quality(message):
    user_id = message.from_user.id
    try:
        int(message.text.split()[1])
        with sqlite3.connect('sleep_bot.db') as con:
            cursor = con.cursor()
            cursor.execute(
                """
                UPDATE sleep_records SET quality = ? 
                WHERE record_id = (SELECT current_record FROM users WHERE id = ?);
                """,
                (message.text.split()[1], user_id)
            )
            con.commit()
        bot.send_message(message.chat.id, "Оценка качества сна успешно обновлена.")
    except (IndexError,ValueError):
        bot.send_message(message.chat.id, "Команда ожидается в виде '/change_quality вставьте своё число'")

@bot.message_handler(commands=["change_notes"])
def change_notes(message):
    user_id = message.from_user.id
    try:
        with sqlite3.connect('sleep_bot.db') as con:
            cursor = con.cursor()
            cursor.execute(
                """
                UPDATE sleep_records SET notes = ? 
                WHERE record_id = (SELECT current_record FROM users WHERE id = ?);
                """,
                (message.text.split(" ", 1)[1], user_id)
            )
            con.commit()
        bot.send_message(message.chat.id, "Заметка о качестве сна успешно обновлена.")
    except IndexError:
        bot.send_message(message.chat.id, "Команда ожидается в виде '/change_notes вставьте свой текст'")

@bot.message_handler(commands=["average"])
def average(message):
    user_id = message.from_user.id
    with sqlite3.connect('sleep_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as con:
        cursor = con.cursor()
        average_quality = cursor.execute("""
            SELECT avg(quality) FROM sleep_records WHERE quality != 'оценка не была внесена'
            """).fetchone()[0]
        average_duration = cursor.execute("""
            SELECT avg(duration) FROM sleep_records """).fetchone()[0]
    bot.send_message(message.chat.id,f"Средняя продолжительность вашего сна: {timedelta_into_str(average_duration)}")
    if average_quality is None:
        bot.send_message(message.chat.id, f"Среднее качество вашего сна: вы ни разу не оценили свой сон")
    else:
        bot.send_message(message.chat.id,f"Среднее качество вашего сна: {round(average_quality, 1)} из 10")

@bot.message_handler(commands=["date"])
def daate(message):
    check = True
    user_id = message.from_user.id
    try:
        input_date = message.text.split()[-1].split(".")
        with sqlite3.connect('sleep_bot.db', detect_types=sqlite3.PARSE_DECLTYPES) as con:
            cursor = con.cursor()
            for i in cursor.execute("""SELECT record_id, wake_time FROM sleep_records WHERE user_id = ?""",(user_id,)).fetchall():
                if i[1].year == int(input_date[-1]) and i[1].month == int(input_date[1]) and i[1].day == int(input_date[0]):
                    check = False
                    data_tmp = cursor.execute("""SELECT * FROM sleep_records WHERE record_id = ?""",(i[0],)).fetchone()
                    try:
                        bot.send_message(message.chat.id,
                                     f"Параметры сна за {message.text.split()[-1]}\nВремя отхода ко сну: {data_tmp[2].strftime("%X")}\nВремя подъема: {data_tmp[3].strftime("%X")}\nПродолжительность сна: {timedelta_into_str(data_tmp[4])}\nКачество сна: {data_tmp[5]}\nЗаметка: {data_tmp[6]}")
                    except IndexError:
                        bot.send_message(message.chat.id, "В этот день Вы ввели не все параметры.")
            if check:
                bot.send_message(message.chat.id, "Данных за эту дату не найдено.")
    except (IndexError, ValueError):
        bot.send_message(message.chat.id, "Команда ожидается в виде '/date вставьте свою дату'")


bot.polling(none_stop=True, interval=0)