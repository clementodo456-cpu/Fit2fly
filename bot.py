import os
import logging
from io import BytesIO
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from collage_generator import create_collage, validate_hex_color

load_dotenv()

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation States
COLLECT_PHOTOS, SELECT_LAYOUT, SELECT_SPACING, SELECT_BG, CUSTOM_HEX, SELECT_FIT = range(6)

MAX_PHOTOS = 9
MIN_PHOTOS = 2
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_MIME_TYPES = ["image/jpeg", "image/png", "image/webp"]

def get_user_session(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Helper to ensure user session context is initialized safely."""
    if "photos" not in context.user_data:
        context.user_data["photos"] = []
    if "settings" not in context.user_data:
        context.user_data["settings"] = {
            "layout": "Auto Grid",
            "spacing": 10,
            "bg_color": "White",
            "fit_mode": "Cover",
        }
    return context.user_data

def clear_user_session(context: ContextTypes.DEFAULT_TYPE):
    """Safely clear user session and photo buffers."""
    if "photos" in context.user_data:
        for bio in context.user_data["photos"]:
            try:
                bio.close()
            except Exception:
                pass
    context.user_data.clear()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    clear_user_session(context)
    welcome_text = (
        "🖼️ Welcome to Photo Collage Bot!\n\n"
        "Combine multiple photos into one beautiful collage.\n"
        "📸 Send your photos\n"
        "🔲 Choose a grid layout\n"
        "🎨 Customize the background\n"
        "✨ Get your finished collage\n\n"
        "Tap Create Collage to begin."
    )
    keyboard = [
        [InlineKeyboardButton("🖼️ Create Collage", callback_data="create_collage")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="show_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "🖼️ How to create a collage:\n\n"
        "1️⃣ Tap Create Collage.\n"
        "2️⃣ Send 2–9 photos.\n"
        "3️⃣ Tap Done.\n"
        "4️⃣ Choose your layout.\n"
        "5️⃣ Select spacing and background.\n"
        "6️⃣ Choose Cover or Fit.\n"
        "7️⃣ Receive your finished collage.\n\n"
        "Supported formats: JPG, PNG, WEBP.\n"
        "Maximum size: 10 MB per image.\n"
        "Maximum photos: 9."
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(help_text)
    else:
        await update.message.reply_text(help_text)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /about command."""
    about_text = (
        "ℹ️ About Fit2flybot (@Fit2flybot)\n\n"
        "A simple, privacy-focused Telegram bot that combines your photos into grid collages.\n"
        "• Photos are stored in memory and deleted immediately after generation.\n"
        "• Built with Python & Pillow."
    )
    await update.message.reply_text(about_text)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command."""
    clear_user_session(context)
    cancel_text = "❌ Collage creation cancelled. Tap /start to begin again."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(cancel_text)
    else:
        await update.message.reply_text(cancel_text)
    return ConversationHandler.END

async def initiate_collage_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start photo collection flow."""
    query = update.callback_query
    await query.answer()

    session = get_user_session(context)
    session["photos"] = []

    msg_text = (
        "📸 Send 2–9 photos.\n"
        "You can send them one after another. When you're finished, tap ✅ Done."
    )
    keyboard = [
        [InlineKeyboardButton("✅ Done", callback_data="photos_done")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    await query.edit_message_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return COLLECT_PHOTOS

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process incoming user photos and documents."""
    session = get_user_session(context)
    photos = session["photos"]

    if len(photos) >= MAX_PHOTOS:
        await update.message.reply_text("⚠️ You have already reached the limit of 9 photos. Tap ✅ Done to proceed.")
        return COLLECT_PHOTOS

    # Extract Telegram File object & Size
    file_obj = None
    file_size = 0
    mime_type = "image/jpeg"

    if update.message.photo:
        photo = update.message.photo[-1]
        file_obj = await photo.get_file()
        file_size = photo.file_size or 0
    elif update.message.document:
        doc = update.message.document
        mime_type = doc.mime_type or ""
        file_size = doc.file_size or 0

        if mime_type not in ALLOWED_MIME_TYPES:
            await update.message.reply_text("❌ Unsupported image format. Please send JPG, PNG, or WEBP images.")
            return COLLECT_PHOTOS

        file_obj = await doc.get_file()

    if not file_obj:
        await update.message.reply_text("⚠️ Could not read image file. Please try sending it again.")
        return COLLECT_PHOTOS

    if file_size > MAX_FILE_SIZE:
        await update.message.reply_text("❌ This image is too large. Maximum size: 10 MB per photo.")
        return COLLECT_PHOTOS

    try:
        bio = BytesIO()
        await file_obj.download_to_memory(out=bio)
        bio.seek(0)
        photos.append(bio)

        count = len(photos)
        keyboard = [
            [InlineKeyboardButton("↩️ Remove Last", callback_data="remove_last")],
            [InlineKeyboardButton("✅ Done", callback_data="photos_done")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
        ]
        await update.message.reply_text(
            f"📸 Photos received: {count}/{MAX_PHOTOS}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error downloading photo: {e}")
        await update.message.reply_text("⚠️ I couldn't process this image. Please try another one.")

    return COLLECT_PHOTOS

async def remove_last_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove the last uploaded photo."""
    query = update.callback_query
    await query.answer()

    session = get_user_session(context)
    photos = session["photos"]

    if photos:
        removed_bio = photos.pop()
        removed_bio.close()
        await query.edit_message_text(f"🗑️ Removed last photo. Photos remaining: {len(photos)}/{MAX_PHOTOS}")
    else:
        await query.edit_message_text("⚠️ No photos left to remove.")

    keyboard = [
        [InlineKeyboardButton("✅ Done", callback_data="photos_done")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    if photos:
        keyboard.insert(0, [InlineKeyboardButton("↩️ Remove Last", callback_data="remove_last")])

    await query.message.reply_text(
        f"📸 Photos received: {len(photos)}/{MAX_PHOTOS}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return COLLECT_PHOTOS

async def photos_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check photo count and prompt layout selection."""
    query = update.callback_query
    await query.answer()

    session = get_user_session(context)
    photos = session["photos"]

    if len(photos) < MIN_PHOTOS:
        await query.edit_message_text(
            f"❌ You need to send at least {MIN_PHOTOS} photos. You have sent {len(photos)}.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        )
        return COLLECT_PHOTOS

    return await show_layout_options(update, context)

async def show_layout_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available grid layouts."""
    keyboard = [
        [InlineKeyboardButton("Auto Grid", callback_data="layout_Auto Grid")],
        [InlineKeyboardButton("1 × 2", callback_data="layout_1x2"), InlineKeyboardButton("2 × 2", callback_data="layout_2x2")],
        [InlineKeyboardButton("2 × 3", callback_data="layout_2x3"), InlineKeyboardButton("3 × 3", callback_data="layout_3x3")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg_text = "🔲 Choose your collage layout:"

    if update.callback_query:
        await update.callback_query.edit_message_text(msg_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg_text, reply_markup=reply_markup)

    return SELECT_LAYOUT

async def handle_layout_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save selected layout and proceed to spacing selection."""
    query = update.callback_query
    await query.answer()

    session = get_user_session(context)
    layout = query.data.replace("layout_", "")
    session["settings"]["layout"] = layout

    keyboard = [
        [InlineKeyboardButton("No spacing (0 px)", callback_data="spacing_0")],
        [InlineKeyboardButton("5 px", callback_data="spacing_5")],
        [InlineKeyboardButton("10 px (Default)", callback_data="spacing_10")],
        [InlineKeyboardButton("20 px", callback_data="spacing_20")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    await query.edit_message_text("↔️ Choose spacing/gutter between photos:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_SPACING

async def handle_spacing_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save spacing and proceed to background selection."""
    query = update.callback_query
    await query.answer()

    session = get_user_session(context)
    spacing_val = int(query.data.replace("spacing_", ""))
    session["settings"]["spacing"] = spacing_val

    keyboard = [
        [InlineKeyboardButton("White (Default)", callback_data="bg_White")],
        [InlineKeyboardButton("Black", callback_data="bg_Black")],
        [InlineKeyboardButton("Gray", callback_data="bg_Gray")],
        [InlineKeyboardButton("Custom HEX", callback_data="bg_Custom")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    await query.edit_message_text("🎨 Choose background color:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_BG

async def handle_bg_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save background color or request custom HEX code."""
    query = update.callback_query
    await query.answer()

    session = get_user_session(context)
    bg_choice = query.data.replace("bg_", "")

    if bg_choice == "Custom":
        await query.edit_message_text(
            "🎨 Send a custom HEX color code (e.g., #FF5733 or FF5733):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])
        )
        return CUSTOM_HEX

    session["settings"]["bg_color"] = bg_choice
    return await show_fit_options(update, context)

async def handle_custom_hex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate and set custom HEX background color."""
    text = update.message.text.strip()
    session = get_user_session(context)

    try:
        validated_hex = validate_hex_color(text)
        session["settings"]["bg_color"] = validated_hex
        return await show_fit_options(update, context)
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid HEX color code. Please send a valid code like #FF5733 or #FFFFFF:"
        )
        return CUSTOM_HEX

async def show_fit_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt user to choose image fit mode."""
    keyboard = [
        [InlineKeyboardButton("🖼️ Cover (Crop to fill cell)", callback_data="fit_Cover")],
        [InlineKeyboardButton("📐 Fit (Preserve full image)", callback_data="fit_Fit")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg_text = "🖼️ Choose Image Fit mode:"

    if update.callback_query:
        await update.callback_query.edit_message_text(msg_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg_text, reply_markup=reply_markup)

    return SELECT_FIT

async def handle_fit_choice_and_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save fit mode and execute collage generation."""
    query = update.callback_query
    await query.answer()

    session = get_user_session(context)
    fit_mode = query.data.replace("fit_", "")
    session["settings"]["fit_mode"] = fit_mode

    await query.edit_message_text("⏳ Creating your collage...")

    photos = session["photos"]
    settings = session["settings"]

    try:
        collage_stream = create_collage(
            image_bytes_list=photos,
            layout_str=settings["layout"],
            spacing=settings["spacing"],
            bg_color_input=settings["bg_color"],
            fit_mode=settings["fit_mode"]
        )

        caption_text = (
            "✅ Collage created successfully!\n"
            f"📸 Photos: {len(photos)}\n"
            f"🔲 Layout: {settings['layout']}\n"
            f"↔️ Spacing: {settings['spacing']} px\n"
            f"🎨 Background: {settings['bg_color']}\n"
            f"🖼️ Fit: {settings['fit_mode']}"
        )

        keyboard = [
            [InlineKeyboardButton("🔄 Create Another", callback_data="create_collage")],
            [InlineKeyboardButton("✏️ Change Settings", callback_data="change_settings")]
        ]

        await query.message.reply_photo(
            photo=collage_stream,
            caption=caption_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error creating collage: {e}", exc_info=True)
        await query.message.reply_text("⚠️ Something went wrong while creating your collage. Please try again.")
    finally:
        clear_user_session(context)

    return ConversationHandler.END

async def handle_change_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows user to change settings for a new collage attempt."""
    query = update.callback_query
    await query.answer()
    return await show_layout_options(update, context)

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN environment variable not set.")
        return

    application = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(initiate_collage_creation, pattern="^create_collage$"),
            CommandHandler("start", start_command)
        ],
        states={
            COLLECT_PHOTOS: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo_upload),
                CallbackQueryHandler(remove_last_photo, pattern="^remove_last$"),
                CallbackQueryHandler(photos_done, pattern="^photos_done$"),
            ],
            SELECT_LAYOUT: [
                CallbackQueryHandler(handle_layout_choice, pattern="^layout_")
            ],
            SELECT_SPACING: [
                CallbackQueryHandler(handle_spacing_choice, pattern="^spacing_")
            ],
            SELECT_BG: [
                CallbackQueryHandler(handle_bg_choice, pattern="^bg_")
            ],
            CUSTOM_HEX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_hex)
            ],
            SELECT_FIT: [
                CallbackQueryHandler(handle_fit_choice_and_generate, pattern="^fit_")
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CallbackQueryHandler(cancel_command, pattern="^cancel_action$"),
            CommandHandler("start", start_command)
        ],
        allow_reentry=True
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    application.add_handler(CallbackQueryHandler(help_command, pattern="^show_help$"))
    application.add_handler(CallbackQueryHandler(initiate_collage_creation, pattern="^create_collage$"))
    application.add_handler(CallbackQueryHandler(handle_change_settings, pattern="^change_settings$"))

    application.add_handler(conv_handler)

    logger.info("Fit2flybot starting in long polling mode...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
