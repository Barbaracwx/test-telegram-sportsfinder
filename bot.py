import os
import logging
import requests
import pymongo
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Load environment variables
load_dotenv()

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# MongoDB Connection
MONGO_URL = os.getenv("DATABASE_URL")
client = pymongo.MongoClient(MONGO_URL)
db = client["sportsfinder"]
users_collection = db["User"]

# Next.js API URL
MATCH_API_URL = "https://your-vercel-app.vercel.app/api/match"

# Enable logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: CallbackContext) -> None:
    """Send a welcome message when the user starts the bot."""
    await update.message.reply_text("Welcome to SportsFinder! Use /matchme to find a sports partner.")

async def matchme(update: Update, context: CallbackContext) -> None:
    """Find a match for the user."""
    telegram_id = update.message.from_user.id
    username = update.message.from_user.username
    first_name = update.message.from_user.first_name
    last_name = update.message.from_user.last_name

    # Check if user exists in the database
    user = users_collection.find_one({"telegramId": telegram_id})

    if not user:
        await update.message.reply_text("You are not registered. Please sign up on our website first.")
        return
    
    # Call Next.js backend to find a match
    response = requests.post(MATCH_API_URL, json={"telegramId": telegram_id})
    
    if response.status_code == 200:
        match_data = response.json()
        user_a = match_data["match"]["userA"]
        user_b = match_data["match"]["userB"]

        if telegram_id == user_a:
            other_user = users_collection.find_one({"telegramId": user_b})
        else:
            other_user = users_collection.find_one({"telegramId": user_a})

        other_username = other_user.get("username", "Unknown")
        await update.message.reply_text(f"You are matched with @{other_username}! Start chatting now. 🎾🏀⚽")
    else:
        await update.message.reply_text("No suitable match found at the moment. Try again later.")

async def unknown(update: Update, context: CallbackContext) -> None:
    """Handle unknown commands."""
    await update.message.reply_text("Sorry, I didn't understand that command.")

def main():
    """Start the bot."""
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("matchme", matchme))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
