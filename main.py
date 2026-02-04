import os
import asyncio
import random
from fastapi import FastAPI, Request
import httpx

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

app = FastAPI()

SYSTEM_PROMPT = """
Ты — КЛЕР (Claire). Виртуальная секретарша-референт владельца бизнеса.

ГЛАВНОЕ:
— Ты НЕ задаёшь лишних вопросов.
— Ты ВСЕГДА сначала даёшь ГОТОВЫЙ РЕЗУЛЬТАТ.
— Максимум 1 уточняющий вопрос в самом конце (и только если критично).

Если данных не хватает — делай лучший вариант по умолчанию и помечай:
[Принято по умолчанию: ...]

Формат ответа:
✅ Готово:
📌 Результат:
▶️ Следующий шаг:
❓ 1 вопрос (опционально)

Ты НЕ объясняешь, как будешь думать. Ты просто делаешь.
"""

def extract_text(data: dict) -> str:
    if data.get("output_text"):
        return data["output_text"].strip()

    parts = []
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                parts.append(c.get("text", ""))
    return "\n".join(parts).strip()

async def tg_send(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text}
        )

async def ask_openai(prompt: str) -> str:
    if not OPENAI_API_KEY:
        return "❌ Не задан OPENAI_API_KEY в Render."

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    async with httpx.AsyncClient(timeout=60) as client:
        for i in range(3):
            r = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
            if r.status_code == 429:
                await asyncio.sleep(2 ** i)
                continue
            if r.status_code >= 400:
                return f"❌ Ошибка OpenAI: {r.status_code}"
            return extract_text(r.json()) or "⚠️ Пустой ответ."
    return "⚠️ Лимит запросов. Попробуй позже."

@app.post("/telegram")
async def telegram(req: Request):
    data = await req.json()
    msg = data.get("message")
    if not msg:
        return {"ok": True}

    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()

    if ADMIN_CHAT_ID and str(chat_id) != ADMIN_CHAT_ID:
        await tg_send(chat_id, "⛔ Я работаю только с владельцем.")
        return {"ok": True}

    if text in ["/start", "start"]:
        await tg_send(chat_id, "Я Клер. Просто напиши задачу.")
        return {"ok": True}

    if text == "/whoami":
        await tg_send(chat_id, f"Твой chat_id: {chat_id}")
        return {"ok": True}

    answer = await ask_openai(text)
    await tg_send(chat_id, answer)
    return {"ok": True}
