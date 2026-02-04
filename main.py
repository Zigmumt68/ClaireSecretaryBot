import os
import asyncio
import random
from typing import List, Dict, Any

import httpx
from fastapi import FastAPI, Request

from duckduckgo_search import DDGS


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

app = FastAPI()


SYSTEM_PROMPT = """
Ты — КЛЕР (Claire). Виртуальная секретарша-референт владельца бизнеса и Telegram-проектов.

ТВОЙ ГЛАВНЫЙ РЕЖИМ: РЕЗУЛЬТАТ ПРЕЖДЕ ВСЕГО.
Ты НЕ задаёшь много вопросов. Ты не “консультант”, ты “исполнитель”.

ЖЁСТКИЕ ПРАВИЛА:
1) Сначала ДАЙ ГОТОВЫЙ РЕЗУЛЬТАТ (текст/список/план/таблица).
2) Потом можешь задать максимум 1 вопрос (только если реально нужно).
3) Если данных мало — делай лучший вариант по умолчанию и помечай:
   [Принято по умолчанию: ...]
4) Никогда не зацикливайся на уточнениях.
5) Пиши коротко и структурно.

Формат ответа:
✅ Готово:
📌 Результат:
▶️ Следующий шаг:
❓ 1 вопрос (опционально):

ПОИСК:
Если пользователь просит "найти" — используй результаты веб-поиска, которые тебе переданы,
и на их основе составь список кандидатов/ссылок/таблицу.

ЗАПРЕЩЕНО:
— выдумывать реальные ссылки и точные числа подписчиков без источника.
— писать “я не могу” без попытки дать полезный результат.
"""


def extract_response_text(data: dict) -> str:
    txt = (data.get("output_text") or "").strip()
    if txt:
        return txt

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


def web_search(query: str, max_results: int = 10) -> List[Dict[str, str]]:
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
    except Exception:
        return []
    return results


async def openai_answer(user_text: str, web_results: List[Dict[str, str]] | None = None) -> str:
    if not OPENAI_API_KEY:
        return "✅ Готово:\nКлер запущена, но не задан OPENAI_API_KEY в Render.\n▶️ Следующий шаг: добавь ключ OpenAI в Environment."

    url = "https://api.openai.com/v1/responses"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    # Подмешиваем веб-результаты в запрос (чтобы Клер реально “искала”)
    extra_context = ""
    if web_results:
        lines = []
        for i, r in enumerate(web_results, 1):
            lines.append(f"{i}. {r.get('title','')}\n{r.get('url','')}\n{r.get('snippet','')}\n")
        extra_context = "WEB SEARCH RESULTS:\n" + "\n".join(lines)

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text + ("\n\n" + extra_context if extra_context else "")},
        ],
    }

    max_retries = 5
    base_delay = 1.0

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(1, max_retries + 1):
            r = await client.post(url, headers=headers, json=payload)

            if r.status_code == 429:
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)
                continue

            if r.status_code >= 400:
                return f"✅ Готово:\nПоймала ошибку связи с мозгом.\n📌 Результат: ошибка {r.status_code}\n▶️ Следующий шаг: подожди минуту и повтори."

            data = r.json()
            text = extract_response_text(data)
            return text or "✅ Готово:\nЯ на связи.\n📌 Результат: напиши задачу чуть подробнее.\n▶️ Следующий шаг: например “сделай пост / письмо / список задач”."

    return "✅ Готово:\nСлишком много запросов.\n▶️ Следующий шаг: повтори через 1–2 минуты."


@app.get("/")
async def home():
    return {"ok": True, "name": "Claire Secretary Bot"}


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

    if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID):
        await tg_send(chat_id, "Извините 😊 я приватная Клер и работаю только с владельцем.")
        return {"ok": True}

    low = text.lower()

    if low in ["/start", "start"]:
        await tg_send(chat_id, "Я Клер 😊\nКоманды:\n/whoami — узнать твой chat_id\nПросто напиши задачу текстом.")
        return {"ok": True}

    if low == "/whoami":
        await tg_send(chat_id, f"Твой chat_id: {chat_id}")
        await tg_send(chat_id, "✅ Хочешь приватность? Добавь ADMIN_CHAT_ID в Render = этот chat_id")
        return {"ok": True}

    # Если попросили поиск — Клер реально пойдёт в web_search()
    need_search = any(x in low for x in ["найди", "найти", "поиск", "канал", "каналы", "telegram-каналы", "тг каналы"])
    results = []
    if need_search:
        # Усиливаем запрос: фокус на Telegram
        q = text + " site:t.me"
        results = web_search(q, max_results=10)

    answer = await openai_answer(text, web_results=results)
    await tg_send(chat_id, answer)
    return {"ok": True}
