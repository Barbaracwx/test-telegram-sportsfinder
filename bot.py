import os
from dotenv import load_dotenv
from pymongo import MongoClient  # Import MongoDB
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, Application
import requests  # To make the HTTP request to your Next.js API

# Load environment variables from .env file
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # MongoDB connection string
MATCH_API_URL = os.getenv("MATCH_API_URL")  # URL for your Next.js match API

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
        welcome_message = f"Hello {user_first_name}, welcome to Sportsfinder!\n\n"
    else:
        welcome_message = f"Welcome back, {user_first_name}! \n\n"

    # Create the web app button
    keyboard = [[InlineKeyboardButton("My Profile", web_app={'url': 'https://webapp-sportsfinder.vercel.app/'})]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_message + "Are you ready to find your sports partner?\n\nClick the button below to set up your profile.",
        reply_markup=reply_markup
    )

# Function to handle /matchme command
async def matchme(update: Update, context):
    user_telegram_id = update.message.from_user.id
    
    # Fetch the user's details from MongoDB
    user = users_collection.find_one({"telegramId": user_telegram_id})
    
    if not user:
        await update.message.reply_text("You must complete your profile first using /start.")
        return
    
    # Check if the user is already matched
    if user.get("isMatched", False):
        await update.message.reply_text("You are already matched with someone!")
        return

    # Prepare data to send to Next.js API
    payload = {
        "telegramId": user_telegram_id
    }

    # Make a POST request to your Next.js API
    response = requests.post(MATCH_API_URL, json=payload)

    # Handle the response from Next.js API
    if response.status_code == 200:
        match_data = response.json()
        if "match" in match_data:
            match = match_data["match"]
            user_b_telegram_id = match["userB"]

            # Get the username of the matched user
            matched_user = users_collection.find_one({"telegramId": user_b_telegram_id})
            matched_user_name = matched_user["username"] if matched_user else "Unknown"

            # Notify both users about the match
            await update.message.reply_text(f"You have been matched with @{matched_user_name}! Start chatting!")
            
            # Update both users as matched in MongoDB
            users_collection.update_many(
                {"telegramId": {"$in": [user_telegram_id, user_b_telegram_id]}},
                {"$set": {"isMatched": True}}
            )
        else:
            await update.message.reply_text("No matches found. Please try again later.")
    else:
        await update.message.reply_text("Error finding a match. Please try again later.")

# Register the /start and /matchme command handlers
start_handler = CommandHandler('start', start)
application.add_handler(start_handler)

matchme_handler = CommandHandler('matchme', matchme)
application.add_handler(matchme_handler)

# Start the bot
application.run_polling()
