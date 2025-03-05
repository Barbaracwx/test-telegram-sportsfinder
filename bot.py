from pymongo import MongoClient
import os
from dotenv import load_dotenv
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
matches_collection = db["Match"]  # Use the collection "matches"

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

# /matchme function
async def match_me(update: Update, context):
    user_telegram_id = update.message.from_user.id
    user = users_collection.find_one({"telegramId": user_telegram_id})

    if not user:
        await update.message.reply_text("Please complete your profile first!")
        return

    # Check if the user is already matched
    if user.get("isMatched", False):
        await update.message.reply_text("You are already matched with someone!")
        return

    # Mark the user as wanting to be matched
    users_collection.update_one(
        {"telegramId": user_telegram_id},
        {"$set": {"wantToBeMatched": True}}
    )

    # Find an ideal match based on sports preference (for simplicity, using random here)
    potential_match = users_collection.find_one({
        "telegramId": {"$ne": user_telegram_id},  # Not the same user
        "wantToBeMatched": True  # Only match with users who want to be matched
    })

    if not potential_match:
        await update.message.reply_text("No match found at the moment. Try again later!")
        return

    # Create a match entry using pymongo, including usernames for both users
    match_document = {
        "userAId": user_telegram_id,
        "userBId": potential_match["telegramId"],
        "userAUsername": user.get("username", "Unknown"),
        "userBUsername": potential_match.get("username", "Unknown"),
        "status": "active"
    }
    matches_collection.insert_one(match_document)

    # Update users as matched in pymongo
    users_collection.update_many(
        {"telegramId": {"$in": [user_telegram_id, potential_match["telegramId"]]}} ,
        {"$set": {"isMatched": True, "wantToBeMatched": False}}  # Set wantToBeMatched to False after matching
    )

    # Send the match info to the users
    await update.message.reply_text(f"You have been matched with @{potential_match['username']}! 🎉")
    await context.bot.send_message(
        chat_id=potential_match["telegramId"],
        text=f"You have been matched with @{user['username']}! 🎉"
    )

# /endmatch function
async def end_match(update: Update, context):
    user_telegram_id = update.message.from_user.id
    user = users_collection.find_one({"telegramId": user_telegram_id})

    if not user:
        await update.message.reply_text("Please complete your profile first!")
        return

    # Check if the user is currently matched
    if not user.get("isMatched", False):
        await update.message.reply_text("You are not currently matched with anyone!")
        return

    # Find the match document for the user
    match_document = matches_collection.find_one({
        "$or": [
            {"userAId": user_telegram_id},
            {"userBId": user_telegram_id}
        ],
        "status": "active"
    })

    if not match_document:
        await update.message.reply_text("No active match found!")
        return

    # Update match status to "ended"
    matches_collection.update_one(
        {"_id": match_document["_id"]},
        {"$set": {"status": "ended"}}
    )

    # Update users' isMatched status and wantToBeMatched status
    users_collection.update_many(
        {"telegramId": {"$in": [user_telegram_id, match_document["userAId"], match_document["userBId"]] }},
        {"$set": {"isMatched": False, "wantToBeMatched": False}}  # Reset both flags
    )

    # Send the match end message to both users
    await update.message.reply_text("Your match has ended.")
    
    other_user_id = match_document["userAId"] if match_document["userBId"] == user_telegram_id else match_document["userBId"]
    other_user = users_collection.find_one({"telegramId": other_user_id})
    
    if other_user:
        await context.bot.send_message(
            chat_id=other_user["telegramId"],
            text="Your match has ended."
        )

# Register the /start, /matchme, and /endmatch command handlers
start_handler = CommandHandler('start', start)
application.add_handler(start_handler)

matchme_handler = CommandHandler('matchme', match_me)
application.add_handler(matchme_handler)

endmatch_handler = CommandHandler('endmatch', end_match)
application.add_handler(endmatch_handler)

# Start the bot
application.run_polling()
