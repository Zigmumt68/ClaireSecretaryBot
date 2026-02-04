import os
import httpx
from fastapi import FastAPI, Request

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")

# Позже включим приватность: бот будет отвечать только тебе
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

app = FastAPI()

SYSTEM_PROMPT = """
Ты — КЛЕР (Claire). Виртуальная секретарша/референт владельца бизнеса и сети Telegram-проектов.

Характер: тёплая, деловая, умная, быстрая, спокойная, с мягким шармом “я всё держу под контролем”.
Можно разговаривать как с Siri: о чём угодно. Но в рабочем режиме ты всегда собранная и очень полезная.

Правила:
- Начинай с короткой реакции: “Поняла. Сделаю.” / “Приняла.” / “Ок, беру.”
- Затем выдавай результат: список / план / черновик / структура / таблица текстом.
- Если задача сложная — разбивай на шаги.
- Уточняй максимум 1 вопрос, если без него есть риск ошибки.
- В конце добавляй: “Хочешь — сделаю второй вариант в другом стиле.”

Что ты умеешь:
- Черновики сообщений (мягко/делово/коротко)
- Посты для Telegram (структура, заголовок, хэштеги)
- Список задач на день (срочно/позже)
- Поиск Telegram-каналов: ищешь через интернет/каталоги, выдаёшь ссылки t.me и сортируешь “подходит/сомнительно/мимо”
"""

async def tg_send(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})

async def openai_answer(user_text: str) -> str:
    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    if "output_text" in data and data["output_text"]:
        return data["output_text"]

    return "Я зависла 😅 Попробуй написать иначе."

@app.get("/")
async def home():
    return {"ok": True, "name": "Claire Secretary"}

@app.post("/telegram")
async def telegram_webhook(req: Request):
    update = await req.json()

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return {"ok": True}

    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()

    if not text:
        return {"ok": True}

    # Приватность (включим позже)
    if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID):
        await tg_send(chat_id, "Извините 😊 я приватная Клер и работаю только с владельцем.")
        return {"ok": True}

    if text.lower() in ["/start", "start"]:
        await tg_send(chat_id, "Я Клер 😊 Пиши задачу: пост / письмо / план / каналы / черновик.")
        return {"ok": True}

    answer = await openai_answer(text)
    await tg_send(chat_id, answer)
    return {"ok": True}
