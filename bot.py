import asyncio
import io
import logging
import os
import re
import secrets
from pathlib import Path

import qrcode
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiohttp import web
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / "settings.env")
load_dotenv(Path(__file__).parent / ".env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ["WEBAPP_URL"].rstrip("/")  # https://sizning-domen.uz
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "").strip()  # BotFather /newapp dagi nom
PORT = int(os.getenv("PORT", "8080"))
MAX_IMAGES = int(os.getenv("MAX_IMAGES", "12"))

BASE = Path(__file__).parent
UPLOADS = BASE / "uploads"
WEBAPP = BASE / "webapp"
UPLOADS.mkdir(exist_ok=True)

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# foydalanuvchi_id -> tanlangan rasmlar (file_id)
selected: dict[int, list[str]] = {}
BOT_USERNAME = ""


def make_link(gid: str) -> str:
    if APP_SHORT_NAME:
        return f"https://t.me/{BOT_USERNAME}/{APP_SHORT_NAME}?startapp={gid}"
    return f"{WEBAPP_URL}/?g={gid}"


def make_qr(link: str) -> bytes:
    img = qrcode.make(link, box_size=10, border=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def keyboard(n: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Yaratish ({n} ta rasm)", callback_data="make")],
            [InlineKeyboardButton(text="🗑 Tozalash", callback_data="clear")],
        ]
    )


@dp.message(CommandStart())
async def start(m: Message):
    selected[m.from_user.id] = []
    await m.answer(
        "Salom! 🏛 Sirli xonalar galereyasini yaratamiz.\n\n"
        f"1. Menga rasmlarni yuboring (ko'pi bilan {MAX_IMAGES} ta).\n"
        "2. «Yaratish» tugmasini bosing.\n"
        "3. Men QR kod beraman. Uni kimgadir yuboring, skaner qilsa 3D xonalar ochiladi."
    )


@dp.message(F.photo)
async def got_photo(m: Message):
    items = selected.setdefault(m.from_user.id, [])
    if len(items) >= MAX_IMAGES:
        await m.answer(f"Eng ko'pi bilan {MAX_IMAGES} ta rasm mumkin. «Yaratish»ni bosing.", reply_markup=keyboard(len(items)))
        return
    items.append(m.photo[-1].file_id)
    await m.answer(f"Rasm qabul qilindi: {len(items)} ta.", reply_markup=keyboard(len(items)))


@dp.callback_query(F.data == "clear")
async def clear(c: CallbackQuery):
    selected[c.from_user.id] = []
    await c.answer("Tozalandi")
    await c.message.answer("Ro'yxat tozalandi. Yangi rasmlarni yuboring.")


@dp.callback_query(F.data == "make")
async def make(c: CallbackQuery):
    items = selected.get(c.from_user.id, [])
    if not items:
        await c.answer("Avval rasm yuboring", show_alert=True)
        return
    await c.answer("Yaratilmoqda...")

    gid = secrets.token_urlsafe(8)
    folder = UPLOADS / gid
    folder.mkdir(parents=True)
    for i, file_id in enumerate(items):
        await bot.download(file_id, destination=folder / f"{i}.jpg")

    link = make_link(gid)
    qr = make_qr(link)
    selected[c.from_user.id] = []
    await c.message.answer_photo(
        BufferedInputFile(qr, filename="galereya.png"),
        caption=f"Tayyor! 🎉 {len(items)} ta rasm.\nQR ni yuboring yoki havolani ulashing:\n{link}",
    )


# ---------- Veb-server (Mini App + API) ----------
async def index(_: web.Request):
    page = WEBAPP / "index.html"
    if not page.exists():
        page = BASE / "index.html"
    return web.FileResponse(page)


async def gallery(request: web.Request):
    gid = request.match_info["gid"]
    if not ID_RE.fullmatch(gid):
        raise web.HTTPNotFound()
    folder = UPLOADS / gid
    if not folder.is_dir():
        raise web.HTTPNotFound()
    files = sorted(folder.glob("*.jpg"), key=lambda p: int(p.stem))
    return web.json_response({"images": [f"/uploads/{gid}/{p.name}" for p in files]})


async def start_web():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/gallery/{gid}", gallery)
    app.router.add_static("/uploads", UPLOADS, follow_symlinks=False)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logging.info("Veb-server: http://0.0.0.0:%s", PORT)


async def main():
    global BOT_USERNAME
    logging.basicConfig(level=logging.INFO)
    BOT_USERNAME = (await bot.get_me()).username
    await start_web()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
