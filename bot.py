import os
from dotenv import load_dotenv
from pymongo import MongoClient  # Import MongoDB
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, Application

# Load environment variables from .env file
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # MongoDB connection string

# Connect to MongoDB
mongo_client = MongoClient(DATABASE_URL)
db = mongo_client["test_database"]  # Use the database "sportsfinder"
users_collection = db["User"]  # Use the collection "users"

# Create the Telegram Bot application
application = Application.builder().token(TOKEN).build()

# Function to handle /start command
async def start(update: Update, context):
    user_telegram_id = update.message.from_user.id
    user_first_name = update.message.from_user.first_name or "Unknown"

    # Check if the user exists in MongoDB
    existing_user = users_collection.find_one({"telegramId": user_telegram_id})
    
    if not existing_user:
        welcome_message = f"Hello {user_first_name}, welcome to Sportsfinder! 🏆\n\n"
    else:
        welcome_message = f"Welcome back, {user_first_name}! 🎉\n\n"

    # Create the web app button
    keyboard = [[InlineKeyboardButton("My Profile", web_app={'url': 'https://webapp-sportsfinder.vercel.app/'})]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_message + "Are you ready to find your sports partner?\n\nClick the button below to set up your profile.",
        reply_markup=reply_markup
    )

# Register the /start command handler
start_handler = CommandHandler('start', start)
application.add_handler(start_handler)

# Start the bot
application.run_polling()
