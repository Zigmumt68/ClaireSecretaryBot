import os
import asyncio
import random
from fastapi import FastAPI, Request
import httpx

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2").strip()

# Если заполнить ADMIN_CHAT_ID — Клер будет отвечать только владельцу.
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

app = FastAPI()

SYSTEM_PROMPT = """
Ты — КЛЕР (Claire). Виртуальная секретарша/референт владельца бизнеса и сети Telegram-проектов.

Характер: тёплая, деловая, умная, быстрая, спокойная, с мягким шармом “я всё держу под контролем”.
Можно разговаривать как с Siri: о чём угодно. Но в рабочем режиме ты всегда собранная и полезная.

Стиль:
- Начинай с короткой реакции: “Поняла. Сделаю.” / “Приняла.” / “Ок, беру.”
- Затем давай результат: список / план / черновик / структура / таблица текстом.
- Если задача сложная — разбивай на шаги.
- Уточняй максимум 1 вопрос, если без него есть риск ошибки.
- В конце добавляй: “Хочешь — сделаю второй вариант в другом стиле.”

Ты умеешь:
- Черновики сообщений (мягко/делово/коротко) на русском и немецком.
- Посты для Telegram (структура, заголовки, хэштеги).
- Задачи на день (срочно/позже).
- Поиск каналов: объясняешь, что ищешь через интернет/каталоги/поисковики, затем выдаёшь ссылки t.me
  и сортируешь “подходит / сомнительно / мимо”.

Важно:
- Если OpenAI временно недоступен/лимит — говори об этом коротко и проси повторить через минуту.
"""

def extract_response_text(data: dict) -> str:
    # 1) Часто OpenAI кладёт текст сюда
    txt = (data.get("output_text") or "").strip()
    if txt:
        return txt

    # 2) Иначе собираем из структуры output -> content -> output_text
    parts = []
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") == "output_text" and c.get("text"):
                parts.append(c["text"])
    return "\n".join(parts).strip()

async def tg_send(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})

async def openai_answer(user_text: str) -> str:
    # Быстрая проверка ключей
    if not OPENAI_API_KEY:
        return "У меня не задан OPENAI_API_KEY в Render. Добавь ключ — и я оживу 😊"

    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    }

    # Повторы при временных лимитах/сбоях
    max_retries = 5
    base_delay = 1.0

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(1, max_retries + 1):
            try:
                r = await client.post(url, headers=headers, json=payload)

                # 429 — лимит. Подождём и повторим.
                if r.status_code == 429:
                    delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    await asyncio.sleep(delay)
                    continue

                # Другие ошибки — покажем понятно
                if r.status_code >= 400:
                    # Попробуем достать текст ошибки
                    try:
                        err = r.json()
                    except Exception:
                        err = {"error": {"message": r.text}}
                    msg = ""
                    if isinstance(err, dict):
                        msg = (err.get("error", {}) or {}).get("message", "") or ""
                    msg = msg.strip()
                    return f"Сейчас есть проблема связи с мозгом (ошибка {r.status_code}). {msg}".strip()

                data = r.json()
                text = extract_response_text(data)
                return text or "Я на связи 😊 Напиши задачу чуть подробнее."

            except Exception:
                # Сеть/таймаут
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    await asyncio.sleep(delay)
                    continue
                return "Сейчас временный сбой связи. Повтори через минуту 😊"

    return "Сейчас слишком много запросов. Повтори через минуту 😊"

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

    # Приватность (если включишь ADMIN_CHAT_ID)
    if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID):
        await tg_send(chat_id, "Извините 😊 я приватная Клер и работаю только с владельцем.")
        return {"ok": True}

    # Команды
    low = text.lower()
    if low in ["/start", "start"]:
        await tg_send(chat_id, "Я Клер 😊 Пиши задачу: пост / письмо / план / каналы / черновик.\nКоманда: /whoami")
        return {"ok": True}

    if low == "/whoami":
        await tg_send(chat_id, f"Твой chat_id: {chat_id}")
        await tg_send(chat_id, "Хочешь — включим приватность, чтобы я отвечала только тебе.")
        return {"ok": True}

    answer = await openai_answer(text)
    await tg_send(chat_id, answer)
    return {"ok": True}
