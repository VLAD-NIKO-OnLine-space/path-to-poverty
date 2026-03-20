"""
Path to Poverty — Telegram Stars donation bot.
Webhook mode for Render / production hosting.
"""

import os
import json
import logging
from pathlib import Path

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    PreCheckoutQuery,
    MenuButtonWebApp,
    WebAppInfo,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
)
from aiogram.filters import CommandStart
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN is required in .env")
if not BASE_URL:
    raise SystemExit("BASE_URL is required in .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_FILE = Path(__file__).parent / "stars.json"
WEBAPP_FILE = Path(__file__).parent / "webapp.html"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bot")

# ─── Simple JSON database ────────────────────────────────────────────


def load_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    return {}


def save_db(db: dict):
    DB_FILE.write_text(json.dumps(db, indent=2), encoding="utf-8")


def get_stars(user_id: int) -> int:
    db = load_db()
    return db.get(str(user_id), 0)


def add_star(user_id: int, count: int = 1) -> int:
    db = load_db()
    key = str(user_id)
    db[key] = db.get(key, 0) + count
    save_db(db)
    return db[key]


# ─── Bot handlers ────────────────────────────────────────────────────


@dp.message(CommandStart())
async def cmd_start(message: Message):
    webapp_url = f"{BASE_URL}/webapp"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⭐ Open Path to Poverty",
            web_app=WebAppInfo(url=webapp_url),
        )]
    ])

    name = message.from_user.first_name
    count = get_stars(message.from_user.id)
    text = (
        f"👋 Hey <b>{name}</b>!\n\n"
        "⭐ Welcome to <b>Path to Poverty</b>\n\n"
        "🎯 Goal: donate <b>1,000,000</b> stars\n"
        "📉 Every star brings you one step closer to absolute poverty\n\n"
        "💡 <i>From rich to rags — one tap at a time</i>\n\n"
        + ("🆕 You have not donated yet. Time to start!" if count == 0 else f"🔥 You have already donated <b>{count}</b> star{'s' if count != 1 else ''}! Keep going!")
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=MenuButtonWebApp(text="⭐ Donate", web_app=WebAppInfo(url=webapp_url)),
    )


@dp.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def on_payment(message: Message):
    user_id = message.from_user.id
    amount = message.successful_payment.total_amount
    total = add_star(user_id, amount)
    log.info(f"⭐ User {user_id} donated {amount} star(s) (total: {total})")
    await message.answer(
        f"⭐ Thank you! You've donated <b>{total}</b> star{'s' if total != 1 else ''} total.\n\n"
        f"{'Keep going!' if total < 10 else '🏆 True dedication to poverty!'}",
        parse_mode="HTML",
    )


# ─── Web server (serves webapp + API) ────────────────────────────────


async def handle_webapp(request: web.Request) -> web.Response:
    html = WEBAPP_FILE.read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html")


async def handle_stars(request: web.Request) -> web.Response:
    user_id = request.query.get("id", "0")
    count = get_stars(int(user_id)) if user_id.isdigit() else 0
    return web.json_response({"count": count})


async def handle_invoice(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "bad request"}, status=400)

    amount = int(data.get("amount", 1))
    amount = max(1, min(amount, 10000))  # clamp

    link = await bot.create_invoice_link(
        title=f"⭐ Donate {amount} Star{'s' if amount > 1 else ''}",
        description=f"{amount} star{'s' if amount > 1 else ''} closer to poverty",
        payload=f"star_donation_{amount}",
        currency="XTR",
        prices=[LabeledPrice(label="Stars", amount=amount)],
    )

    return web.json_response({"invoice_url": link})


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


# ─── Startup / Shutdown ──────────────────────────────────────────────


async def on_startup(app: web.Application):
    webhook_url = f"{BASE_URL}{WEBHOOK_PATH}"
    try:
        await bot.set_webhook(webhook_url)
        log.info(f"🔗 Webhook set: {webhook_url}")
        log.info(f"📱 Webapp URL: {BASE_URL}/webapp")
    except Exception as e:
        log.error(f"❌ Failed to set webhook: {e}")


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    log.info("🛑 Bot stopped")


# ─── Main ─────────────────────────────────────────────────────────────


def main():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/webapp", handle_webapp)
    app.router.add_get("/api/stars", handle_stars)
    app.router.add_post("/api/invoice", handle_invoice)

    # Webhook handler
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=WEBHOOK_PATH)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    log.info(f"🤖 Starting bot on port {PORT}")
    web.run_app(app, host="0.0.0.0", port=PORT)


main()
