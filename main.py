"""
ربات تلگرام ثبت مشخصات ویلا با aiogram 3.x
پشتیبانی کامل از لوکیشن زنده (Live Location) روی نقشه تلگرام
"""
import os
import sys
import json
import logging
import sqlite3
from datetime import datetime
from typing import List

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command, ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    Location,
    ChatMemberUpdated,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_GROUP_ID_STR = os.getenv("ADMIN_GROUP_ID", "").strip()
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "").strip()

if not BOT_TOKEN:
    logging.warning("BOT_TOKEN is not set in environment or .env file!")

try:
    ADMIN_GROUP_ID = int(ADMIN_GROUP_ID_STR) if ADMIN_GROUP_ID_STR else 0
except ValueError:
    ADMIN_GROUP_ID = 0

ADMIN_IDS: List[int] = []
if ADMIN_IDS_STR:
    for item in ADMIN_IDS_STR.split(","):
        item = item.strip()
        if item.lstrip("-").isdigit():
            ADMIN_IDS.append(int(item))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DB_PATH = "villas.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS villas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            owner_phone TEXT,
            owner_name TEXT,
            villa_name TEXT,
            location TEXT,
            lat REAL,
            lon REAL,
            area TEXT,
            bedrooms TEXT,
            capacity TEXT,
            amenities TEXT,
            price_weekday TEXT,
            price_weekend TEXT,
            price_holiday TEXT,
            price_extra TEXT,
            photos_json TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """
    )
    cursor.execute("PRAGMA table_info(villas)")
    cols = {row[1] for row in cursor.fetchall()}
    if "lat" not in cols:
        cursor.execute("ALTER TABLE villas ADD COLUMN lat REAL")
    if "lon" not in cols:
        cursor.execute("ALTER TABLE villas ADD COLUMN lon REAL")
    conn.commit()
    conn.close()

def save_villa(data: dict) -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO villas (
            owner_id, owner_phone, owner_name, villa_name, location, lat, lon,
            area, bedrooms, capacity, amenities, price_weekday,
            price_weekend, price_holiday, price_extra, photos_json,
            status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data.get("owner_id"),
            data.get("owner_phone"),
            data.get("owner_name"),
            data.get("villa_name"),
            data.get("location"),
            data.get("lat"),
            data.get("lon"),
            data.get("area"),
            data.get("bedrooms"),
            data.get("capacity"),
            data.get("amenities"),
            data.get("price_weekday"),
            data.get("price_weekend"),
            data.get("price_holiday"),
            data.get("price_extra"),
            json.dumps(data.get("photos", []), ensure_ascii=False),
            "pending",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    villa_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return villa_id

def update_villa_status(villa_id: int, status: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE villas SET status = ? WHERE id = ?", (status, villa_id))
    conn.commit()
    conn.close()

def get_villa_by_id(villa_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM villas WHERE id = ?", (villa_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_villa_columns():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(villas)")
    cols = [row[1] for row in cursor.fetchall()]
    conn.close()
    return cols

class VillaForm(StatesGroup):
    phone = State()
    full_name = State()
    villa_name = State()
    location = State()
    location_pin = State()
    area = State()
    bedrooms = State()
    capacity = State()
    amenities = State()
    price_weekday = State()
    price_weekend = State()
    price_holiday = State()
    price_extra = State()
    photos = State()
    confirm = State()

router = Router()

def get_contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="ارسال شماره تماس", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def get_location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 ارسال لوکیشن از نقشه", request_location=True)],
            [KeyboardButton(text="رد کردن ارسال لوکیشن")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def get_location_confirm_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="تایید لوکیشن")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def get_photos_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="اتمام ارسال تصاویر")]],
        resize_keyboard=True,
    )

def get_confirm_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="تایید نهایی و ثبت ویلا")],
            [KeyboardButton(text="انصراف و شروع مجدد")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def build_map_links(lat: float, lon: float) -> str:
    return (
        "🗺 لینک‌های نقشه:\n"
        f"• Google Maps: https://maps.google.com/?q={lat},{lon}\n"
        f"• Neshan: https://neshan.org/maps/@{lat},{lon},17z\n"
        f"• Balad: https://balad.ir/location?latitude={lat}&longitude={lon}&zoom=17\n"
        f"• OsmAnd/OpenStreetMap: https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}"
    )

def build_location_line(data: dict) -> str:
    lat, lon = data.get("lat"), data.get("lon")
    if lat is not None and lon is not None:
        return f"📍 لوکیشن: {lat:.6f}, {lon:.6f}"
    return "📍 لوکیشن: ارسال نشده"

def build_summary_text(data: dict) -> str:
    photos = data.get("photos", [])
    lat, lon = data.get("lat"), data.get("lon")
    map_links = build_map_links(lat, lon) if (lat is not None and lon is not None) else ""
    return (
        "مشخصات ثبت‌شده ویلا:\n"
        "-------------------------\n"
        f"نام مالک: {data.get('owner_name', '-')}\n"
        f"شماره تماس: {data.get('owner_phone', '-')}\n"
        f"نام / عنوان ویلا: {data.get('villa_name', '-')}\n"
        f"موقعیت مکانی و آدرس: {data.get('location', '-')}\n"
        f"{build_location_line(data)}\n"
        f"{map_links}\n"
        f"متراژ کل و بنا: {data.get('area', '-')}\n"
        f"تعداد اتاق خواب: {data.get('bedrooms', '-')}\n"
        f"ظرفیت استاندارد و حداکثر: {data.get('capacity', '-')}\n"
        f"امکانات و ویژگی‌ها: {data.get('amenities', '-')}\n"
        f"قیمت روزهای عادی (وسط هفته): {data.get('price_weekday', '-')}\n"
        f"قیمت آخر هفته (پنج‌شنبه/جمعه): {data.get('price_weekend', '-')}\n"
        f"قیمت تعطیلات خاص و عید: {data.get('price_holiday', '-')}\n"
        f"هزینه نفر اضافه: {data.get('price_extra', '-')}\n"
        f"تعداد تصاویر پیوست: {len(photos)}"
    )

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "سلام! به سامانه ثبت مشخصات ویلا خوش آمدید.\n\n"
        "لطفاً برای شروع فرآیند، با زدن دکمه زیر شماره تماس همراه خود را ارسال کنید:"
    )
    await message.answer(welcome_text, reply_markup=get_contact_keyboard())
    await state.set_state(VillaForm.phone)

@router.message(VillaForm.phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    phone_number = message.contact.phone_number
    await state.update_data(owner_phone=phone_number, owner_id=message.from_user.id)
    await message.answer(
        "لطفاً نام و نام خانوادگی مالک یا نماینده ویلا را وارد نمایید:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(VillaForm.full_name)

@router.message(VillaForm.phone, F.text)
async def process_phone_text(message: Message, state: FSMContext):
    phone_number = (message.text or "").strip()
    if len(phone_number) < 10:
        await message.answer(
            "لطفاً یک شماره تماس معتبر وارد کنید یا از دکمه «ارسال شماره تماس» استفاده کنید.",
            reply_markup=get_contact_keyboard(),
        )
        return
    await state.update_data(owner_phone=phone_number, owner_id=message.from_user.id)
    await message.answer(
        "لطفاً نام و نام خانوادگی مالک یا نماینده ویلا را وارد نمایید:",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(VillaForm.full_name)

@router.message(VillaForm.full_name, F.text)
async def process_full_name(message: Message, state: FSMContext):
    await state.update_data(owner_name=(message.text or "").strip())
    await message.answer("نام یا عنوان اختصاصی ویلا را وارد نمایید (مثال: ویلا استخردار کاج):")
    await state.set_state(VillaForm.villa_name)

@router.message(VillaForm.villa_name, F.text)
async def process_villa_name(message: Message, state: FSMContext):
    await state.update_data(villa_name=(message.text or "").strip())
    await message.answer(
        "حالا موقعیت مکانی دقیق ویلا را روی نقشه تلگرام ارسال کنید 📍\n\n"
        "با دکمه «ارسال لوکیشن از نقشه» می‌توانید پین لوکیشن را روی نقشه انتخاب کنید "
        "یا لوکیشن زنده (Live Location) خود را بفرستید.\n"
        "همچنین می‌توانید آدرس متنی را تایپ کنید یا ارسال لوکیشن را رد کنید.",
        reply_markup=get_location_keyboard(),
    )
    await state.set_state(VillaForm.location)

@router.message(VillaForm.location, F.location)
async def process_location_message(message: Message, state: FSMContext):
    loc: Location = message.location
    is_live = bool(loc.live_period)  # live location has live_period set
    await state.update_data(lat=loc.latitude, lon=loc.longitude)
    prefix = "🔄 لوکیشن زنده دریافت شد!" if is_live else "✅ لوکیشن با موفقیت ذخیره شد!"
    await message.answer(
        f"{prefix}\n"
        f"مختصات: {loc.latitude:.6f}, {loc.longitude:.6f}\n\n"
        f"{build_map_links(loc.latitude, loc.longitude)}\n\n"
        "اگر آدرس متنی هم دارید (شهر، منطقه، آدرس)، آن را وارد نمایید؛ "
        "در غیر این صورت بنویسید «ندارم»:"
    )
    await state.set_state(VillaForm.location_pin)

@router.message(VillaForm.location, F.text == "رد کردن ارسال لوکیشن")
async def process_location_skip(message: Message, state: FSMContext):
    await message.answer(
        "لوکیشن ثبت نشد. لطفاً آدرس متنی موقعیت ویلا (شهر، منطقه، آدرس یا محدوده) را وارد نمایید:"
    )
    await state.set_state(VillaForm.location_pin)

@router.message(VillaForm.location, F.text)
async def process_location_text(message: Message, state: FSMContext):
    await state.update_data(location=(message.text or "").strip())
    await message.answer(
        "عالی! حالا در صورت تمایل، لوکیشن دقیق را هم از نقشه تلگرام ارسال کنید 📍 "
        "(دکمه «ارسال لوکیشن از نقشه» یا لوکیشن زنده). اگر ندارید بنویسید «ندارم»:",
        reply_markup=get_location_keyboard(),
    )
    await state.set_state(VillaForm.location_pin)

@router.edited_message(VillaForm.location, F.edited_location)
@router.edited_message(VillaForm.location_pin, F.edited_location)
async def process_live_location_update(message: Message, state: FSMContext):
    """بروزرسانی مختصات هنگام ارسال لوکیشن زنده (Live Location) توسط تلگرام."""
    loc: Location = message.location
    await state.update_data(lat=loc.latitude, lon=loc.longitude)
    await message.answer(
        f"🔄 لوکیشن زنده بروزرسانی شد!\n"
        f"مختصات لحظه‌ای: {loc.latitude:.6f}, {loc.longitude:.6f}\n\n"
        f"{build_map_links(loc.latitude, loc.longitude)}\n\n"
        "برای ادامه، دکمه «تایید لوکیشن» را بزنید یا آدرس متنی را وارد کنید:",
        reply_markup=get_location_confirm_keyboard(),
    )

@router.message(VillaForm.location_pin, F.location)
async def process_location_pin(message: Message, state: FSMContext):
    loc: Location = message.location
    is_live = bool(loc.live_period)
    await state.update_data(lat=loc.latitude, lon=loc.longitude)
    prefix = "🔄 لوکیشن زنده دریافت شد!" if is_live else "✅ لوکیشن ذخیره شد!"
    await message.answer(
        f"{prefix}\n"
        f"مختصات: {loc.latitude:.6f}, {loc.longitude:.6f}\n\n"
        f"{build_map_links(loc.latitude, loc.longitude)}\n\n"
        "برای ادامه، دکمه «تایید لوکیشن» را بزنید یا آدرس متنی را وارد کنید:",
        reply_markup=get_location_confirm_keyboard(),
    )
    await state.set_state(VillaForm.location_pin)

@router.message(VillaForm.location_pin, F.text == "تایید لوکیشن")
async def process_location_pin_confirm(message: Message, state: FSMContext):
    await message.answer(
        "متراژ کل زمین و زیربنا را وارد نمایید (مثال: ۵۰۰ متر زمین، ۱۸۰ متر بنا):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(VillaForm.area)

@router.message(VillaForm.location_pin, F.text)
async def process_location_pin_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text and text != "ندارم":
        await state.update_data(location=text)
    await message.answer(
        "متراژ کل زمین و زیربنا را وارد نمایید (مثال: ۵۰۰ متر زمین، ۱۸۰ متر بنا):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(VillaForm.area)

@router.message(VillaForm.area, F.text)
async def process_area(message: Message, state: FSMContext):
    await state.update_data(area=(message.text or "").strip())
    await message.answer("تعداد اتاق خواب و نوع تخت‌ها را بنویسید (مثال: ۲ خواب با تخت دونفره):")
    await state.set_state(VillaForm.bedrooms)

@router.message(VillaForm.bedrooms, F.text)
async def process_bedrooms(message: Message, state: FSMContext):
    await state.update_data(bedrooms=(message.text or "").strip())
    await message.answer("ظرفیت استاندارد و حداکثر ظرفیت پذیرش را مشخص فرمایید (مثال: ۴ نفر پایه + تا ۲ نفر اضافه):")
    await state.set_state(VillaForm.capacity)

@router.message(VillaForm.capacity, F.text)
async def process_capacity(message: Message, state: FSMContext):
    await state.update_data(capacity=(message.text or "").strip())
    await message.answer(
        "امکانات و ویژگی‌های خاص ویلا را ذکر کنید:\n"
        "(مثال: استخر آبگرم، بیلیارد، سیستم صوتی، باربیکیو، پارکینگ، نگهبانی، وای‌فای)"
    )
    await state.set_state(VillaForm.amenities)

@router.message(VillaForm.amenities, F.text)
async def process_amenities(message: Message, state: FSMContext):
    await state.update_data(amenities=(message.text or "").strip())
    await message.answer("قیمت اجاره برای هر شب در روزهای وسط هفته (شنبه تا سه‌شنبه) به تومان:")
    await state.set_state(VillaForm.price_weekday)

@router.message(VillaForm.price_weekday, F.text)
async def process_price_weekday(message: Message, state: FSMContext):
    await state.update_data(price_weekday=(message.text or "").strip())
    await message.answer("قیمت اجاره برای هر شب در آخر هفته‌ها (چهارشنبه و پنج‌شنبه) به تومان:")
    await state.set_state(VillaForm.price_weekend)

@router.message(VillaForm.price_weekend, F.text)
async def process_price_weekend(message: Message, state: FSMContext):
    await state.update_data(price_weekend=(message.text or "").strip())
    await message.answer("قیمت اجاره برای ایام تعطیلات خاص و عید نوروز به تومان:")
    await state.set_state(VillaForm.price_holiday)

@router.message(VillaForm.price_holiday, F.text)
async def process_price_holiday(message: Message, state: FSMContext):
    await state.update_data(price_holiday=(message.text or "").strip())
    await message.answer("هزینه اقامت به ازای هر نفر اضافه به تومان:")
    await state.set_state(VillaForm.price_extra)

@router.message(VillaForm.price_extra, F.text)
async def process_price_extra(message: Message, state: FSMContext):
    await state.update_data(price_extra=(message.text or "").strip(), photos=[])
    instruction = (
        "اکنون تصاویر ویلا را ارسال کنید (حداکثر ۱۰ تصویر).\n\n"
        "عکس‌ها را یکی‌یکی یا چندتایی بفرستید. پس از اتمام ارسال، دکمه «اتمام ارسال تصاویر» یا دستور /done را ارسال کنید."
    )
    await message.answer(instruction, reply_markup=get_photos_keyboard())
    await state.set_state(VillaForm.photos)

@router.message(VillaForm.photos, F.photo)
async def process_photo_item(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if len(photos) >= 10:
        await message.answer(
            "حداکثر سقف مجاز (۱۰ تصویر) دریافت شده است. لطفاً دکمه «اتمام ارسال تصاویر» را بزنید."
        )
        return

    file_id = message.photo[-1].file_id
    photos.append(file_id)
    await state.update_data(photos=photos)

    await message.answer(
        f"تصویر شماره {len(photos)} ذخیره شد.\n"
        "در صورت تمایل تصویر بعدی را ارسال کنید یا «اتمام ارسال تصاویر» را بزنید.",
        reply_markup=get_photos_keyboard(),
    )

@router.message(VillaForm.photos, Command("done"))
async def process_photos_done_command(message: Message, state: FSMContext):
    await _finish_photos(message, state)

@router.message(VillaForm.photos, F.text == "اتمام ارسال تصاویر")
async def process_photos_done_button(message: Message, state: FSMContext):
    await _finish_photos(message, state)

async def _finish_photos(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    if not photos:
        await message.answer(
            "حداقل باید یک عکس از ویلا ارسال نمایید!",
            reply_markup=get_photos_keyboard(),
        )
        return

    summary = build_summary_text(data)
    confirm_msg = (
        f"{summary}\n\n"
        "لطفاً مشخصات فوق را به دقت بررسی فرمایید. در صورت تأیید روی دکمه «تایید نهایی و ثبت ویلا» بزنید."
    )
    await message.answer(confirm_msg, reply_markup=get_confirm_keyboard())
    await state.set_state(VillaForm.confirm)

@router.message(VillaForm.confirm, F.text == "انصراف و شروع مجدد")
async def process_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "ثبت ویلا لغو شد. برای شروع دوباره دستور /start را ارسال کنید.",
        reply_markup=ReplyKeyboardRemove(),
    )

@router.message(VillaForm.confirm, F.text == "تایید نهایی و ثبت ویلا")
async def process_confirm(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    villa_id = save_villa(data)
    photos = data.get("photos", [])
    lat, lon = data.get("lat"), data.get("lon")

    await message.answer(
        f"ویلای شما با کد رهگیری #{villa_id} با موفقیت ثبت شد!\n"
        "اطلاعات برای بررسی و تایید کارشناسان ارسال گردید. نتیجه به زودی به اطلاع شما خواهد رسید.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()

    if ADMIN_GROUP_ID:
        try:
            media_group = [
                InputMediaPhoto(
                    media=photo_id,
                    caption=(f"تصاویر ارسالی ویلا #{villa_id}" if i == 0 else None),
                )
                for i, photo_id in enumerate(photos[:10])
            ]
            if media_group:
                await bot.send_media_group(chat_id=ADMIN_GROUP_ID, media=media_group)

            # ارسال پین لوکیشن مستقیماً روی نقشه تلگرام برای ادمین‌ها
            if lat is not None and lon is not None:
                await bot.send_location(chat_id=ADMIN_GROUP_ID, latitude=lat, longitude=lon)

            map_links = build_map_links(lat, lon) if (lat is not None and lon is not None) else "📍 لوکیشن ارسال نشده است."

            summary_text = (
                f"درخواست ثبت ویلا جدید (کد: #{villa_id})\n"
                "-------------------------\n"
                f"{build_summary_text(data)}\n"
                "-------------------------\n"
                f"{map_links}\n"
                "-------------------------\n"
                "وضعیت کنونی: در انتظار بررسی"
            )

            admin_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="تایید ویلا", callback_data=f"villa_action:approve:{villa_id}"),
                        InlineKeyboardButton(text="رد درخواست", callback_data=f"villa_action:reject:{villa_id}"),
                    ]
                ]
            )

            await bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=summary_text,
                reply_markup=admin_kb,
            )
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به گروه ادمین: {e}")

@router.callback_query(F.data.startswith("villa_action:"))
async def handle_admin_action(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await callback.answer("شما دسترسی لازم برای انجام این عملیات را ندارید.", show_alert=True)
        return

    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("داده نامعتبر است.")
        return

    action = parts[1]
    try:
        villa_id = int(parts[2])
    except ValueError:
        await callback.answer("شناسه ویلا نامعتبر است.")
        return

    villa = get_villa_by_id(villa_id)
    if not villa:
        await callback.answer("ویلا در دیتابیس یافت نشد!", show_alert=True)
        return

    admin_mention = callback.from_user.full_name or f"Admin ({user_id})"

    if action == "approve":
        update_villa_status(villa_id, "approved")
        status_text = f"تایید شده توسط {admin_mention}"
        user_notify = f"تبریک! ویلای شما با کد #{villa_id} توسط مدیریت تایید و در لیست قرار گرفت."
    elif action == "reject":
        update_villa_status(villa_id, "rejected")
        status_text = f"رد شده توسط {admin_mention}"
        user_notify = f"متاسفانه درخواست ثبت ویلای شما با کد #{villa_id} توسط مدیریت پذیرفته نشد."
    else:
        await callback.answer("عملیات ناشناخته.")
        return

    current_text = callback.message.text or ""
    if "وضعیت کنونی:" in current_text:
        lines = current_text.splitlines()
        updated_lines = []
        for line in lines:
            if line.startswith("وضعیت کنونی:"):
                updated_lines.append(f"وضعیت نهایی: {status_text}")
            else:
                updated_lines.append(line)
        new_text = "\n".join(updated_lines)
    else:
        new_text = current_text + f"\n\nوضعیت نهایی: {status_text}"

    try:
        await callback.message.edit_text(text=new_text, reply_markup=None)
    except Exception as e:
        logger.warning(f"عدم امکان ویرایش پیام ادمین: {e}")

    await callback.answer("عملیات با موفقیت ثبت شد.")

    owner_id = villa[1]
    if owner_id:
        try:
            await bot.send_message(chat_id=owner_id, text=user_notify)
        except Exception as e:
            logger.info(f"ارسال پیام به مالک ناموفق بود: {e}")

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER))
async def on_new_chat_member(event: ChatMemberUpdated, bot: Bot):
    if ADMIN_GROUP_ID and event.chat.id != ADMIN_GROUP_ID:
        return
    user = event.new_chat_member.user
    if user.is_bot:
        return

    bot_info = await bot.get_me()
    deep_link = f"https://t.me/{bot_info.username}?start=register_villa"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏡 ثبت اقامتگاه در ربات", url=deep_link)]
        ]
    )

    group_text = (
        f"سلام {user.full_name} عزیز! 🌸\n"
        f"به مرکز رزرواسیون خوش آمدید.\n"
        f"لطفاً چند دقیقه وقت بگذارید و مشخصات اقامتگاه خود را ثبت نمایید."
    )

    try:
        await bot.send_message(chat_id=event.chat.id, text=group_text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error sending group welcome: {e}")

    pv_text = (
        f"سلام {user.full_name} جان! 🌺\n\n"
        f"به تیم میزبانان «تعطیلات رویایی شمال» خوش آمدید.\n"
        f"لطفاً با زدن دکمه زیر یا ارسال /start، مشخصات ویلا، قیمت و عکس‌ها را ثبت کنید تا در سامانه ما منتشر شود."
    )
    try:
        await bot.send_message(chat_id=user.id, text=pv_text, reply_markup=kb)
    except Exception as e:
        logger.info(f"Could not send PV to user {user.id} (user has not started bot): {e}")


async def main():
    if not BOT_TOKEN:
        print("خطا: BOT_TOKEN در فایل .env تعریف نشده است!", file=sys.stderr)
        return

    init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("ربات با موفقیت راه‌اندازی شد و در حال دریافت پیام‌هاست...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member"])

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("ربات متوقف شد.")
