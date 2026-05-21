"""
Telegram bot for DarkZone
"""
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import os
import aiohttp
import io
from dotenv import load_dotenv

from app import create_app, db
from app.models import User, Product, ProductItem, Order, OrderItem, Key, Transaction, Cart, ReferralTransaction, Notification
from app.loyalty_utils import update_user_loyalty_level
from core.security import decrypt_key
from datetime import datetime
import uuid

load_dotenv()

bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
if not bot_token:
    raise ValueError("TELEGRAM_BOT_TOKEN must be set in environment variables")

# Check if token is a placeholder value
if bot_token in ['your-telegram-bot-token', '', 'YOUR_TELEGRAM_BOT_TOKEN']:
    raise ValueError(
        "TELEGRAM_BOT_TOKEN is not configured. Please set a valid Telegram bot token in your .env file.\n"
        "Get your bot token from @BotFather on Telegram."
    )

try:
    bot = Bot(token=bot_token)
except Exception as e:
    raise ValueError(
        f"Invalid TELEGRAM_BOT_TOKEN: {e}\n"
        "Please check that your bot token is correct in the .env file.\n"
        "Get your bot token from @BotFather on Telegram."
    ) from e
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Create Flask app context for database operations
app = create_app()


class OrderStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_payment = State()


def get_main_menu_keyboard():
    """Get main menu keyboard"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Каталог", callback_data="catalog")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🛒 Корзина", callback_data="cart")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="support")]
    ])
    return keyboard


def get_category_keyboard(categories):
    """Get category selection keyboard"""
    buttons = []
    for category in categories:
        buttons.append([InlineKeyboardButton(text=category, callback_data=f"category_{category}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_product_keyboard(product_id, items):
    """Get product keyboard with items"""
    buttons = []
    for item in items:
        buttons.append([InlineKeyboardButton(
            text=f"{item.formatted_duration} - {item.price} ₽",
            callback_data=f"add_to_cart_{item.id}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    with app.app_context():
        user = User.query.filter_by(telegram_id=message.from_user.id).first()
        
        if not user:
            # Create new user
            from app.models import LoyaltyLevel
            username = f"tg_{message.from_user.username or message.from_user.id}"
            user = User(
                username=username,
                email=f"{message.from_user.id}@telegram.temp",
                telegram_id=message.from_user.id,
                balance=0.00,
                role='user'
            )
            user.set_password(str(uuid.uuid4()))  # Random password
            
            # Assign default loyalty level (Гость)
            default_level = LoyaltyLevel.query.filter_by(name='Гость', is_active=True).first()
            if default_level:
                user.loyalty_level_id = default_level.id
            
            db.session.add(user)
            db.session.commit()
        
        await message.answer(
            f"👋 Добро пожаловать в DarkZone, {message.from_user.first_name}!\n\n"
            "Используйте кнопки ниже для навигации:",
            reply_markup=get_main_menu_keyboard()
        )


@dp.message(Command("menu"))
async def cmd_menu(message: types.Message):
    """Handle /menu command"""
    await message.answer(
        "Главное меню:",
        reply_markup=get_main_menu_keyboard()
    )


@dp.message(Command("catalog"))
async def cmd_catalog(message: types.Message):
    """Handle /catalog command"""
    await show_catalog(message)


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    """Handle /profile command"""
    await show_profile(message)


@dp.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    """Handle main menu callback"""
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "catalog")
async def callback_catalog(callback: CallbackQuery):
    """Handle catalog callback"""
    await show_catalog_message(callback.message)
    await callback.answer()


async def show_catalog(message: types.Message):
    """Show catalog"""
    with app.app_context():
        categories = db.session.query(Product.category).distinct().filter(
            Product.status == 'active'
        ).all()
        categories = [c[0] for c in categories if c[0]]
        
        if not categories:
            await message.answer("Каталог пуст.")
            return
        
        keyboard = get_category_keyboard(categories)
        await message.answer("Выберите категорию:", reply_markup=keyboard)


async def show_catalog_message(message: types.Message):
    """Show catalog (for callback)"""
    with app.app_context():
        categories = db.session.query(Product.category).distinct().filter(
            Product.status == 'active'
        ).all()
        categories = [c[0] for c in categories if c[0]]
        
        if not categories:
            await message.edit_text("Каталог пуст.")
            return
        
        keyboard = get_category_keyboard(categories)
        await message.edit_text("Выберите категорию:", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("category_"))
async def callback_category(callback: CallbackQuery):
    """Handle category selection"""
    category = callback.data.replace("category_", "")
    
    with app.app_context():
        products = Product.query.filter_by(category=category, status='active').order_by(
            Product.position, Product.name
        ).all()
        
        if not products:
            await callback.answer("Товары не найдены.", show_alert=True)
            return
        
        text = f"📦 Товары в категории '{category}':\n\n"
        buttons = []
        
        for product in products:
            # `Product.items` is a relationship list (InstrumentedList), not a query.
            min_item = min(product.items, key=lambda x: x.price, default=None)
            price_text = f"от {min_item.price} ₽" if min_item else "Цена не указана"
            text += f"• {product.name} - {price_text}\n"
            buttons.append([InlineKeyboardButton(
                text=product.name,
                callback_data=f"product_{product.id}"
            )])
        
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="catalog")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@dp.callback_query(F.data.startswith("product_"))
async def callback_product(callback: CallbackQuery):
    """Handle product selection"""
    product_id = int(callback.data.replace("product_", ""))
    
    with app.app_context():
        product = Product.query.get(product_id)
        if not product or product.status != 'active':
            await callback.answer("Товар не найден.", show_alert=True)
            return
        
        # `Product.items` is a relationship list, so sort it in Python.
        items = sorted(product.items, key=lambda x: x.duration_days)
        if not items:
            await callback.answer("Тарифы не доступны.", show_alert=True)
            return
        
        text = f"📦 {product.name}\n\n"
        if product.description:
            text += f"{product.description[:200]}\n\n"
        
        text += "Выберите тариф:"
        
        keyboard = get_product_keyboard(product_id, items)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@dp.callback_query(F.data.startswith("add_to_cart_"))
async def callback_add_to_cart(callback: CallbackQuery):
    """Handle add to cart"""
    item_id = int(callback.data.replace("add_to_cart_", ""))
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=callback.from_user.id).first()
        if not user:
            await callback.answer("Ошибка. Используйте /start", show_alert=True)
            return
        
        product_item = ProductItem.query.get(item_id)
        if not product_item or product_item.stock < 1:
            await callback.answer("Товар недоступен.", show_alert=True)
            return
        
        # Add to cart in database
        cart_item = Cart.query.filter_by(user_id=user.id, product_item_id=item_id).first()
        if cart_item:
            cart_item.quantity += 1
        else:
            cart_item = Cart(user_id=user.id, product_item_id=item_id, quantity=1)
            db.session.add(cart_item)
        db.session.commit()
        
        await callback.answer(f"✅ {product_item.product.name} добавлен в корзину!", show_alert=True)


@dp.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery):
    """Handle profile callback"""
    await show_profile_message(callback.message)
    await callback.answer()


async def show_profile(message: types.Message):
    """Show profile"""
    with app.app_context():
        user = User.query.filter_by(telegram_id=message.from_user.id).first()
        if not user:
            await message.answer("Пользователь не найден. Используйте /start")
            return
        
        orders_count = Order.query.filter_by(user_id=user.id).count()
        
        text = (
            f"👤 Профиль\n\n"
            f"Баланс: {user.balance} Ядра\n"
            f"Заказов: {orders_count}\n"
            f"Email: {user.email if user.email else 'Не указан'}\n\n"
            f"Используйте веб-сайт для пополнения баланса и просмотра истории."
        )
        
        await message.answer(text, reply_markup=get_main_menu_keyboard())


async def show_profile_message(message: types.Message):
    """Show profile (for callback)"""
    with app.app_context():
        user = User.query.filter_by(telegram_id=message.from_user.id).first()
        if not user:
            await message.edit_text("Пользователь не найден. Используйте /start")
            return
        
        orders_count = Order.query.filter_by(user_id=user.id).count()
        
        text = (
            f"👤 Профиль\n\n"
            f"Баланс: {user.balance} Ядра\n"
            f"Заказов: {orders_count}\n"
            f"Email: {user.email if user.email else 'Не указан'}\n\n"
            f"Используйте веб-сайт для пополнения баланса и просмотра истории."
        )
        
        await message.edit_text(text, reply_markup=get_main_menu_keyboard())


def get_cart_keyboard(cart_items):
    """Get cart keyboard with items"""
    buttons = []
    for cart_item in cart_items:
        product_item = cart_item.product_item
        buttons.append([InlineKeyboardButton(
            text=f"❌ {product_item.product.name} ({product_item.formatted_duration}) - {cart_item.quantity} шт.",
            callback_data=f"remove_from_cart_{cart_item.id}"
        )])
    if cart_items:
        buttons.append([InlineKeyboardButton(text="💳 Оформить заказ", callback_data="checkout")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data == "cart")
async def callback_cart(callback: CallbackQuery):
    """Handle cart callback"""
    with app.app_context():
        user = User.query.filter_by(telegram_id=callback.from_user.id).first()
        if not user:
            await callback.answer("Ошибка. Используйте /start", show_alert=True)
            return
        
        cart_items = Cart.query.filter_by(user_id=user.id).all()
        
        if not cart_items:
            await callback.message.edit_text(
                "🛒 Корзина пуста.\n\n"
                "Добавьте товары из каталога.",
                reply_markup=get_main_menu_keyboard()
            )
            await callback.answer()
            return
        
        text = "🛒 Ваша корзина:\n\n"
        total = 0.0
        
        for cart_item in cart_items:
            product_item = cart_item.product_item
            if product_item and product_item.product.status == 'active':
                item_total = float(product_item.price) * cart_item.quantity
                total += item_total
                text += f"• {product_item.product.name}\n"
                text += f"  {product_item.formatted_duration} - {cart_item.quantity} шт. × {product_item.price} ₽ = {item_total:.2f} ₽\n\n"
        
        text += f"💰 Итого: {total:.2f} ₽"
        
        keyboard = get_cart_keyboard(cart_items)
        await callback.message.edit_text(text, reply_markup=keyboard)
        await callback.answer()


@dp.callback_query(F.data.startswith("remove_from_cart_"))
async def callback_remove_from_cart(callback: CallbackQuery):
    """Handle remove from cart"""
    cart_item_id = int(callback.data.replace("remove_from_cart_", ""))
    
    with app.app_context():
        user = User.query.filter_by(telegram_id=callback.from_user.id).first()
        if not user:
            await callback.answer("Ошибка. Используйте /start", show_alert=True)
            return
        
        cart_item = Cart.query.get(cart_item_id)
        if cart_item and cart_item.user_id == user.id:
            db.session.delete(cart_item)
            db.session.commit()
            await callback.answer("Товар удален из корзины", show_alert=True)
            
            # Refresh cart view
            await callback_cart(callback)
        else:
            await callback.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data == "checkout")
async def callback_checkout(callback: CallbackQuery):
    """Handle checkout"""
    with app.app_context():
        user = User.query.filter_by(telegram_id=callback.from_user.id).first()
        if not user:
            await callback.answer("Ошибка. Используйте /start", show_alert=True)
            return
        
        cart_items = Cart.query.filter_by(user_id=user.id).all()
        
        if not cart_items:
            await callback.answer("Корзина пуста", show_alert=True)
            return
        
        # Calculate total
        total = 0.0
        items_data = []
        for cart_item in cart_items:
            product_item = cart_item.product_item
            if product_item and product_item.product.status == 'active' and product_item.stock >= cart_item.quantity:
                item_total = float(product_item.price) * cart_item.quantity
                total += item_total
                items_data.append({
                    'product_item': product_item,
                    'quantity': cart_item.quantity
                })
        
        if not items_data:
            await callback.answer("Товары недоступны", show_alert=True)
            return
        
        # Check balance
        if float(user.balance) < total:
            await callback.message.edit_text(
                f"❌ Недостаточно средств на балансе.\n\n"
                f"Требуется: {total:.2f} ₽\n"
                f"Доступно: {float(user.balance):.2f} ₽\n\n"
                f"Пополните баланс на веб-сайте.",
                reply_markup=get_main_menu_keyboard()
            )
            await callback.answer()
            return
        
        # Create order
        order_number = f"ORD-{uuid.uuid4().hex[:12].upper()}"
        order = Order(
            user_id=user.id,
            order_number=order_number,
            status='paid',
            total_amount=total,
            customer_email=user.email,
            customer_telegram_id=callback.from_user.id,
            payment_method='balance',
            completed_at=datetime.utcnow()
        )
        db.session.add(order)
        db.session.flush()
        
        # Create order items and assign keys
        keys_text = ""
        for item_data in items_data:
            product_item = item_data['product_item']
            quantity = item_data['quantity']
            
            for _ in range(quantity):
                key_obj = Key.query.filter_by(
                    product_item_id=product_item.id,
                    status='available'
                ).first()
                
                if not key_obj:
                    db.session.rollback()
                    await callback.answer("Недостаточно ключей на складе", show_alert=True)
                    return
                
                order_item = OrderItem(
                    order_id=order.id,
                    product_item_id=product_item.id,
                    key_id=key_obj.id,
                    price=product_item.price,
                    quantity=1
                )
                db.session.add(order_item)
                key_obj.status = 'sold'
                key_obj.sold_at = datetime.utcnow()
                product_item.stock -= 1
                
                # Decrypt key
                try:
                    decrypted_key = decrypt_key(key_obj.encrypted_key)
                    keys_text += f"\n🔑 {product_item.product.name} ({product_item.formatted_duration}):\n`{decrypted_key}`\n"
                except Exception:
                    keys_text += f"\n🔑 {product_item.product.name} ({product_item.formatted_duration}): Ошибка расшифровки\n"
        
        # Deduct balance
        user.balance -= total
        
        # Update total_spent (use original price before discount)
        # Calculate original total from items
        original_total = sum(float(item['product_item'].price) * item['quantity'] for item in items_data)
        user.total_spent = int(float(user.total_spent) + float(original_total))
        
        # Update user's loyalty level based on new total_spent
        user.update_loyalty_level()
        
        # Create transaction
        transaction = Transaction(
            user_id=user.id,
            order_id=order.id,
            transaction_type='purchase',
            amount=total,
            payment_method='balance',
            status='completed',
            completed_at=datetime.utcnow()
        )
        db.session.add(transaction)
        
        # Clear cart
        Cart.query.filter_by(user_id=user.id).delete()
        
        # Update order status to completed
        order.status = 'completed'
        
        # Process referral commission if user was referred
        user.credit_referral_commission(order, original_total)
        
        db.session.commit()

        
        await callback.message.edit_text(
            f"✅ Заказ #{order_number} успешно оформлен!\n\n"
            f"💰 Сумма: {total:.2f} ₽\n\n"
            f"Ваши ключи:{keys_text}",
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
        await callback.answer()


@dp.callback_query(F.data == "support")
async def callback_support(callback: CallbackQuery):
    """Handle support callback"""
    await callback.message.edit_text(
        "💬 Поддержка\n\n"
        "По всем вопросам обращайтесь через веб-сайт или напишите администратору.",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()


# --- TELEGRAM TO DISCORD NEWS BRIDGE ---

async def send_to_discord_webhook(text=None, files=None, message_url=None):
    """Send message and files to Discord Webhook"""
    webhook_url = os.environ.get('DISCORD_NEWS_WEBHOOK_URL')
    if not webhook_url:
        print("Error: DISCORD_NEWS_WEBHOOK_URL not set in .env")
        return

    async with aiohttp.ClientSession() as session:
        # Prepare form data
        data = aiohttp.FormData()
        
        content = text or ""
        if message_url:
            if content:
                content += f"\n\n[Оригинал в Telegram]({message_url})"
            else:
                content = f"[Оригинал в Telegram]({message_url})"
        
        if content:
            data.add_field('content', content)
        
        if files:
            for i, (file_bytes, filename) in enumerate(files):
                data.add_field(f'file{i}', file_bytes, filename=filename)
        
        try:
            async with session.post(webhook_url, data=data) as response:
                if response.status not in [200, 204]:
                    resp_text = await response.text()
                    print(f"Discord Webhook Error ({response.status}): {resp_text}")
        except Exception as e:
            print(f"Failed to send to Discord Webhook: {e}")


@dp.channel_post()
async def on_channel_post(message: types.Message):
    """Handle posts from Telegram channels"""
    # Only process posts from the target channel
    target_channel = "DarkZone_offshop"
    if message.chat.username != target_channel and str(message.chat.id) != target_channel:
        return

    print(f"Processing new post from channel: {message.chat.username or message.chat.id}")

    text = message.text or message.caption or ""
    files = []
    
    # Message link
    message_url = f"https://t.me/{message.chat.username}/{message.message_id}" if message.chat.username else None

    # Handle Media
    try:
        if message.photo:
            # Get largest photo
            photo = message.photo[-1]
            file_info = await bot.get_file(photo.file_id)
            file_bytes = await bot.download_file(file_info.file_path)
            files.append((file_bytes, "photo.jpg"))
            
        elif message.video:
            if message.video.file_size < 25 * 1024 * 1024: # Discord 25MB limit
                file_info = await bot.get_file(message.video.file_id)
                file_bytes = await bot.download_file(file_info.file_path)
                files.append((file_bytes, message.video.file_name or "video.mp4"))
            else:
                text += "\n\n*(Видео слишком большое для пересылки в Discord)*"
                
        elif message.document:
            if message.document.file_size < 25 * 1024 * 1024:
                file_info = await bot.get_file(message.document.file_id)
                file_bytes = await bot.download_file(file_info.file_path)
                files.append((file_bytes, message.document.file_name or "file"))
            else:
                text += f"\n\n*(Файл '{message.document.file_name}' слишком большой для пересылки)*"
                
        elif message.audio:
            file_info = await bot.get_file(message.audio.file_id)
            file_bytes = await bot.download_file(file_info.file_path)
            files.append((file_bytes, message.audio.file_name or "audio.mp3"))

    except Exception as e:
        print(f"Error downloading media from Telegram: {e}")
        text += f"\n\n*(Ошибка при загрузке медиа: {e})*"

    # Send to Discord
    await send_to_discord_webhook(text=text, files=files, message_url=message_url)


async def main():
    """Main function to run bot"""
    print("Starting Telegram bot...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())