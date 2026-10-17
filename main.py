"""
Villa Intake Bot (aiogram 3.x) — ربات ثبت ویلا
- aiohttp keep-alive web server for Render alongside aiogram long polling.
- FSM registration flow -> sqlite (pending) -> admin approval -> publish.
"""
import asyncio
import logging
import os
import sqlite3

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    FSInputFile,
    InputMediaPhoto,
)
from aiogram import BaseMiddleware
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "8080"))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0") or 0)
PUBLIC_GROUP_ID = int(os.getenv("PUBLIC_GROUP_ID", "0") or 0)
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
DB_PATH = os.getenv("DB_PATH", "villa.db")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("villa-bot")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ----------------------------- Database -----------------------------
def db_init() -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS villas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            owner_name TEXT,
            owner_phone TEXT,
            location_text TEXT,
            latitude REAL,
            longitude REAL,
            area TEXT,
            bedrooms TEXT,
            capacity TEXT,
            amenities TEXT,
            price_normal TEXT,
            price_weekend TEXT,
            price_holiday TEXT,
            extra_person_fee TEXT,
            photos TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    con.commit()
    con.close()


def db_insert(data: dict) -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.execute(
        """
        INSERT INTO villas (user_id, title, owner_name, owner_phone, location_text,
            latitude, longitude, area, bedrooms, capacity, amenities,
            price_normal, price_weekend, price_holiday, extra_person_fee, photos)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            data.get("user_id"),
            data.get("title"),
            data.get("owner_name"),
            data.get("owner_phone"),
            data.get("location_text"),
            data.get("latitude"),
            data.get("longitude"),
            data.get("area"),
            data.get("bedrooms"),
            data.get("capacity"),
            data.get("amenities"),
            data.get("price_normal"),
            data.get("price_weekend"),
            data.get("price_holiday"),
            data.get("extra_person_fee"),
            ",".join(data.get("photos", [])),
        ),
    )
    con.commit()
    villa_id = cur.lastrowid
    con.close()
    return villa_id


def db_set_status(villa_id: int, status: str) -> None:
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE villas SET status=? WHERE id=?", (status, villa_id))
    con.commit()
    con.close()


def db_get(villa_id: int) -> dict:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM villas WHERE id=?", (villa_id,)).fetchone()
    con.close()
    return dict(row) if row else {}


# ----------------------------- FSM -----------------------------
class VillaForm(StatesGroup):
    title = State()
    owner_name = State()
    owner_phone = State()
    location = State()
    area = State()
    bedrooms = State()
    capacity = State()
    amenities = State()
    price_normal = State()
    price_weekend = State()
    price_holiday = State()
    extra_person_fee = State()
    photos = State()


CANCEL_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="لغو ❌")]], resize_keyboard=True
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="ثبت ویلای جدید 🏡")]], resize_keyboard=True
    )


# ----------------------------- Admin check -----------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def is_group_admin(bot_obj: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot_obj.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def check_admin(cb: CallbackQuery, bot_obj: Bot) -> bool:
    if is_admin(cb.from_user.id):
        return True
    if ADMIN_GROUP_ID:
        return await is_group_admin(bot_obj, ADMIN_GROUP_ID, cb.from_user.id)
    return False


# ----------------------------- Keep-alive web server -----------------------------
async def health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def run_web_server() -> None:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Keep-alive web server started on port %s", PORT)


# ----------------------------- /start -----------------------------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "سلام! 👋\nبه ربات ثبت ویلای خوش آمدید.\n"
        "برای ثبت ویلای خود روی دکمه زیر بزنید.",
        reply_markup=main_menu(),
    )


@dp.message(Command("cancel"))
@dp.message(F.text == "لغو ❌")
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("عملیات لغو شد.", reply_markup=main_menu())


@dp.message(F.text == "ثبت ویلای جدید 🏡")
async def start_form(message: Message, state: FSMContext) -> None:
    await state.set_data({"photos": []})
    await state.set_state(VillaForm.title)
    await message.answer(
        "🏡 نام و عنوان ویلارا وارد کنید:", reply_markup=CANCEL_KB
    )


# ----------------------------- Registration flow -----------------------------
@dp.message(VillaForm.title)
async def ask_owner_name(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text)
    await state.set_state(VillaForm.owner_name)
    await message.answer("👤 نام و نام خانوادگی مالک را وارد کنید:")


@dp.message(VillaForm.owner_name)
async def ask_owner_phone(message: Message, state: FSMContext) -> None:
    await state.update_data(owner_name=message.text)
    await state.set_state(VillaForm.owner_phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="اشتراک شماره تلفن 📞", request_contact=True)],
            [KeyboardButton(text="لغو ❌")],
        ],
        resize_keyboard=True,
    )
    await message.answer("📞 شماره تماس مالک را ارسال کنید:", reply_markup=kb)


@dp.message(VillaForm.owner_phone, F.contact)
async def got_contact(message: Message, state: FSMContext) -> None:
    await state.update_data(owner_phone=message.contact.phone_number)
    await ask_location(message, state)


@dp.message(VillaForm.owner_phone)
async def got_phone_text(message: Message, state: FSMContext) -> None:
    await state.update_data(owner_phone=message.text)
    await ask_location(message, state)


async def ask_location(message: Message, state: FSMContext) -> None:
    await state.set_state(VillaForm.location)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="اشتراک لوکیشن 📍", request_location=True)],
            [KeyboardButton(text="لغو ❌")],
        ],
        resize_keyboard=True,
    )
    await message.answer(
        "📍 لوکیشن ویلارا بفرستید (یا آدرس متنی بنویسید):", reply_markup=kb
    )


@dp.message(VillaForm.location, F.location)
async def got_location(message: Message, state: FSMContext) -> None:
    await state.update_data(
        latitude=message.location.latitude,
        longitude=message.location.longitude,
        location_text=f"{message.location.latitude},{message.location.longitude}",
    )
    await ask_area(message, state)


@dp.message(VillaForm.location)
async def got_location_text(message: Message, state: FSMContext) -> None:
    await state.update_data(location_text=message.text, latitude=None, longitude=None)
    await ask_area(message, state)


async def ask_area(message: Message, state: FSMContext) -> None:
    await state.set_state(VillaForm.area)
    await message.answer(
        "📐 متراژ ویلرا وارد کنید:", reply_markup=CANCEL_KB
    )


@dp.message(VillaForm.area)
async def ask_bedrooms(message: Message, state: FSMContext) -> None:
    await state.update_data(area=message.text)
    await state.set_state(VillaForm.bedrooms)
    await message.answer("🛏 تعداد اتاق خواب را وارد کنید:")


@dp.message(VillaForm.bedrooms)
async def ask_capacity(message: Message, state: FSMContext) -> None:
    await state.update_data(bedrooms=message.text)
    await state.set_state(VillaForm.capacity)
    await message.answer("👨‍👩‍👧‍👦 ظرفیت ویلارا وارد کنید:")


@dp.message(VillaForm.capacity)
async def ask_amenities(message: Message, state: FSMContext) -> None:
    await state.update_data(capacity=message.text)
    await state.set_state(VillaForm.amenities)
    await message.answer(
        "🏊 امکانات ویلارا بنویسید (مثلاً: استخر، سونا، جکوزی، باربیکیو):"
    )


@dp.message(VillaForm.amenities)
async def ask_price_normal(message: Message, state: FSMContext) -> None:
    await state.update_data(amenities=message.text)
    await state.set_state(VillaForm.price_normal)
    await message.answer("💰 قیمت روز عادی (تومان):")


@dp.message(VillaForm.price_normal)
async def ask_price_weekend(message: Message, state: FSMContext) -> None:
    await state.update_data(price_normal=message.text)
    await state.set_state(VillaForm.price_weekend)
    await message.answer("💰 قیمت روز پایان هفته (تومان):")


@dp.message(VillaForm.price_weekend)
async def ask_price_holiday(message: Message, state: FSMContext) -> None:
    await state.update_data(price_weekend=message.text)
    await state.set_state(VillaForm.price_holiday)
    await message.answer("💰 قیمت روزهای تعطیل (تومان):")


@dp.message(VillaForm.price_holiday)
async def ask_extra_fee(message: Message, state: FSMContext) -> None:
    await state.update_data(price_holiday=message.text)
    await state.set_state(VillaForm.extra_person_fee)
    await message.answer("💰 هزینه هر نفر اضافه (تومان):")


@dp.message(VillaForm.extra_person_fee)
async def ask_photos(message: Message, state: FSMContext) -> None:
    await state.update_data(extra_person_fee=message.text)
    await state.set_state(VillaForm.photos)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="اتمام عکس‌ها ✅")], [KeyboardButton(text="لغو ❌")]],
        resize_keyboard=True,
    )
    await message.answer(
        "📸 عکس‌های ویلارا بفرستید (می‌توانید چند عکس بفرستید) و در پایان دکمه «اتمام عکس‌ها» را بزنید.",
        reply_markup=kb,
    )


# ----------------------------- Photos -----------------------------
@dp.message(VillaForm.photos, F.photo)
async def collect_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"✅ عکس {len(photos)} دریافت شد. عکس بعدی را بفرستید یا «اتمام عکس‌ها» را بزنید.")


@dp.message(VillaForm.photos, F.text == "اتمام عکس‌ها ✅")
async def finish_photos(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        await message.answer("⚠️ حداقل یک عکس لازم است.")
        return
    await finalize_submission(message, state, data)


@dp.message(VillaForm.photos)
async def photos_other(message: Message) -> None:
    await message.answer("📸 لطفاً عکس بفرستید یا دکمه «اتمام عکس‌ها ✅» را بزنید.")


# ----------------------------- Finalize -----------------------------
async def finalize_submission(message: Message, state: FSMContext, data: dict) -> None:
    await state.clear()
    data["user_id"] = message.from_user.id
    villa_id = db_insert(data)
    lat, lon = data.get("latitude"), data.get("longitude")
    map_links = ""
    if lat and lon:
        map_links = (
            f"\n🗺 <a href='https://www.google.com/maps?q={lat},{lon}'>گوگل مپ</a>"
            f" | <a href='https://maps.apple.com/?q={lat},{lon}'>اپل مپ</a>"
        )

    admin_caption = (
        f"🆔 کد ثبت: <b>{villa_id}</b>\n"
        f"🏡 عنوان: <b>{data.get('title')}</b>\n"
        f"👤 مالک: {data.get('owner_name')}\n"
        f"📞 تلفن: {data.get('owner_phone')}\n"
        f"📍 موقعیت: {data.get('location_text')}{map_links}\n"
        f"📐 متراژ: {data.get('area')} | 🛏 اتاق: {data.get('bedrooms')} | "
        f"👨‍👩‍👧 ظرفیت: {data.get('capacity')}\n"
        f"🏊 امکانات: {data.get('amenities')}\n"
        f"💰 عادی: {data.get('price_normal')} | آخر هفته: {data.get('price_weekend')} | "
        f"تعطیل: {data.get('price_holiday')} | نفر اضافه: {data.get('extra_person_fee')}\n"
        f"🆔 کاربر: <a href='tg://user?id={data['user_id']}'>{data['user_id']}</a>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید", callback_data=f"approve_{villa_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"reject_{villa_id}"),
            ]
        ]
    )

    photos = data.get("photos", [])
    target = ADMIN_GROUP_ID or (ADMIN_IDS and next(iter(ADMIN_IDS)))
    if target:
        try:
            if len(photos) == 1:
                await bot.send_photo(
                    target, photos[0], caption=admin_caption, reply_markup=kb
                )
            else:
                media = [InputMediaPhoto(media=photos[0], caption=admin_caption)]
                media += [InputMediaPhoto(media=p) for p in photos[1:10]]
                await bot.send_media_group(target, media=media)
                await bot.send_message(
                    target, "برای تصمیم‌گیری از دکمه‌های زیر استفاده کنید:", reply_markup=kb
                )
        except Exception as e:
            logger.error("Failed to send to admin group: %s", e)

    await message.answer(
        f"✅ ویلای شما با کد <b>{villa_id}</b> ثبت شد و در انتظار بررسی است.\n"
        "پس از تأیید، در گروه منتشر خواهد شد و از طریق پیوی مطلع می‌شوید.",
        reply_markup=main_menu(),
    )


# ----------------------------- Approve / Reject -----------------------------
async def publish_dossier(villa: dict) -> int:
    photos = villa["photos"].split(",") if villa["photos"] else []
    lat, lon = villa.get("latitude"), villa.get("longitude")
    map_links = ""
    if lat and lon:
        map_links = (
            f"\n🗺 <a href='https://www.google.com/maps?q={lat},{lon}'>گوگل مپ</a>"
            f" | <a href='https://maps.apple.com/?q={lat},{lon}'>اپل مپ</a>"
        )
    caption = (
        f"🏡 <b>{villa['title']}</b>\n"
        f"📍 {villa['location_text']}{map_links}\n"
        f"📐 متراژ: {villa['area']} | 🛏 اتاق: {villa['bedrooms']} | 👨‍👩‍👧 ظرفیت: {villa['capacity']}\n"
        f"🏊 امکانات: {villa['amenities']}\n"
        f"💰 روز عادی: {villa['price_normal']} | آخر هفته: {villa['price_weekend']} | "
        f"تعطیل: {villa['price_holiday']} | نفر اضافه: {villa['extra_person_fee']}\n"
        f"📞 رزرو: {villa['owner_phone']}"
    )
    target = PUBLIC_GROUP_ID or ADMIN_GROUP_ID
    if not target:
        return 0
    if len(photos) == 1:
        await bot.send_photo(target, photos[0], caption=caption)
    else:
        media = [InputMediaPhoto(media=photos[0], caption=caption)]
        media += [InputMediaPhoto(media=p) for p in photos[1:10]]
        await bot.send_media_group(target, media=media)
    return target


@dp.callback_query(F.data.startswith("approve_") | F.data.startswith("reject_"))
async def on_decision(cb: CallbackQuery) -> None:
    if not await check_admin(cb, bot):
        await cb.answer("⛔️ شما دسترسی ندارید.", show_alert=True)
        return

    action, villa_id = cb.data.split("_", 1)
    villa_id = int(villa_id)
    status = "approved" if action == "approve" else "rejected"
    db_set_status(villa_id, status)
    villa = db_get(villa_id)
    if not villa:
        await cb.answer("❌ رکورد یافت نشد.", show_alert=True)
        return

    admin_name = cb.from_user.full_name
    if status == "approved":
        try:
            target = await publish_dossier(villa)
            if target:
                await cb.message.answer(f"✅ ویلا #{villa_id} در گروه منتشر شد.")
        except Exception as e:
            logger.error("Publish failed: %s", e)
            await cb.message.answer(f"⚠️ انتشار ویلا #{villa_id} ناموفق بود.")
        notify = (
            f"✅ ویلای شما «{villa['title']}» با کد {villa_id} تأیید و منتشر شد."
        )
    else:
        notify = f"❌ ویلای شما «{villa['title']}» با کد {villa_id} رد شد."

    # Edit admin message with admin name
    try:
        base_text = cb.message.caption or cb.message.text or ""
        await cb.message.edit_caption(
            caption=f"{base_text}\n\n{'✅ تأیید' if status=='approved' else '❌ رد'} توسط: {admin_name}"
        ) if cb.message.caption else await cb.message.edit_text(
            text=f"{base_text}\n\n{'✅ تأیید' if status=='approved' else '❌ رد'} توسط: {admin_name}"
        )
    except Exception:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    # Notify owner in PV
    try:
        await bot.send_message(villa["user_id"], notify)
    except Exception as e:
        logger.error("Notify owner failed: %s", e)

    await cb.answer("انجام شد ✅")


# ----------------------------- chat_member welcome -----------------------------
@dp.chat_member()
async def on_chat_member(event) -> None:
    old = event.old_chat_member
    new = event.new_chat_member
    if old.status == "left" and new.status in ("member", "administrator", "creator"):
        if event.chat.id in (PUBLIC_GROUP_ID, ADMIN_GROUP_ID):
            try:
                await bot.send_message(
                    event.chat.id,
                    f"سلام {new.user.first_name} عزیز 👋\n"
                    "به گروه خوش آمدید! برای ثبت ویلای خودتان از دکمه زیر شروع کنید:",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="ثبت ویلای جدید 🏡", url=f"https://t.me/{(await bot.me()).username}")]
                        ]
                    ),
                )
                await bot.send_message(
                    new.user.id,
                    "سلام! 👋 خوش آمدید.\n"
                    "برای ثبت ویلای خود روی /start بزنید.",
                )
            except Exception as e:
                logger.error("Welcome failed: %s", e)


async def on_startup() -> None:
    db_init()
    logger.info("DB ready. Polling started.")


async def main() -> None:
    await run_web_server()
    await on_startup()
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "chat_member"],
        )
    finally:
        pass


if __name__ == "__main__":
    asyncio.run(main())
