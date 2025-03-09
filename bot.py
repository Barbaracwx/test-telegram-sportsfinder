from pymongo import MongoClient
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    Application,
    CallbackQueryHandler,
    ContextTypes,  # Import ContextTypes
)
from bson import ObjectId

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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_telegram_id = update.message.from_user.id
    user_first_name = update.message.from_user.first_name or "Unknown"
    user_username = update.message.from_user.username or "Unknown"

    # Check if the user exists in MongoDB
    existing_user = users_collection.find_one({"telegramId": user_telegram_id})

    if not existing_user:
        # First-time user
        welcome_message = (
            f"Welcome {user_first_name} to SportsFinder!\n\n"
            "This is a player matching service for your favourite sports. "
            "To begin, click on the button below to open our web app - "
            "it’ll give you access to view and edit your profile from there!"
        )

        # Create the web app button for first-time users
        keyboard = [[InlineKeyboardButton("My Profile", web_app={'url': 'https://webapp-sportsfinder.vercel.app/'})]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send the welcome message with the button
        await update.message.reply_text(
            welcome_message,
            reply_markup=reply_markup
        )
    else:
        # Returning user
        welcome_message = (
            f"Welcome back, {user_first_name}!\n\n"
            "SportsFinder is a player matching bot for your favourite sports! Click the commands below to edit your profile or match preferences! "
        )

        # Send the welcome message without any buttons
        await update.message.reply_text(welcome_message)

# /matchme function
async def match_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_telegram_id = update.message.from_user.id
    user = users_collection.find_one({"telegramId": user_telegram_id})

    if not user:
        await update.message.reply_text("Please complete your profile first!")
        return
    
    # Check if the profile is complete
    if not is_profile_complete(user):
        await update.message.reply_text("Please complete your profile first!")
        return
    
    # Check if the match preferences are complete
    if not are_preferences_complete(user):
        await update.message.reply_text("Please complete your match preferences first!")
        return

    # Check if the user is already matched
    if user.get("isMatched", False):
        await update.message.reply_text("You are already matched with someone!")
        return

    # Retrieve the user's selected sports from the sports field in MongoDB
    sports_data = user.get("sports", {})  # Get the sports JSON object
    selected_sports = list(sports_data.keys())  # Extract the keys (sports names)

    if not selected_sports:
        await update.message.reply_text("You have not selected any sports in your profile!")
        return

    # Create inline buttons for each sport
    keyboard = [
        [InlineKeyboardButton(sport, callback_data=f"sport_{sport}")] for sport in selected_sports
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Ask the user which sport they want to find a match for
    await update.message.reply_text(
        "Ready for your next game? Which sport are you looking to find a player for:",
        reply_markup=reply_markup
    )

# Callback function when a sport is selected
async def sport_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query

    sport = query.data.split("_")[1]  # Extract the selected sport
    user_telegram_id = query.from_user.id
    user = users_collection.find_one({"telegramId": user_telegram_id})

    if not user:
        await query.edit_message_text("User not found.")
        return
    
    # Send the "Gotcha! Sportsfinding for you..." message
    await query.edit_message_text(f"Gotcha! Sportsfinding your player in {sport}...")

    # Mark the user as wanting to be matched for the selected sport
    users_collection.update_one(
        {"telegramId": user_telegram_id},
        {"$set": {"wantToBeMatched": True, "selectedSport": sport}}
    )

    # Find an ideal match based on users who also want to be matched for the same sport
    potential_match = users_collection.find_one({
        "telegramId": {"$ne": user_telegram_id},  # Not the same user
        "wantToBeMatched": True,  # Only match with users who want to be matched
        "selectedSport": sport  # Match for the same sport
    })

    if not potential_match:
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text=f"No match found for {sport} at the moment. Please wait for a match!"
        )
        return

    # Create a match entry using pymongo, including usernames for both users
    match_document = {
        "userAId": user_telegram_id,
        "userBId": potential_match["telegramId"],
        "userAUsername": user.get("username", "Unknown"),
        "userBUsername": potential_match.get("username", "Unknown"),
        "sport": sport,
        "status": "active"
    }
    matches_collection.insert_one(match_document)

    # Update users as matched in pymongo and reset wantToBeMatched to False
    users_collection.update_many(
        {"telegramId": {"$in": [user_telegram_id, potential_match["telegramId"]]}} ,
        {"$set": {"isMatched": True, "wantToBeMatched": False}}  # Set wantToBeMatched to False after matching
    )

    # Send the match info to the users
    await context.bot.send_message(
        chat_id=user_telegram_id,
        text=f"You have been matched with {potential_match.get('displayName', 'Unknown')} for {sport}! 🎉"
    )
    await context.bot.send_message(
        chat_id=potential_match["telegramId"],
        text=f"You have been matched with {user.get('displayName', 'Unknown')} for {sport}! 🎉"
    )

# /endmatch function
async def end_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        {"telegramId": {"$in": [user_telegram_id, match_document["userAId"], match_document["userBId"]]}},
        {"$set": {"isMatched": False, "wantToBeMatched": False}}  # Reset both flags
    )

    # Send the match end message to both users
    await update.message.reply_text("Your match has ended.")
    
    other_user_id = match_document["userAId"] if match_document["userBId"] == user_telegram_id else match_document["userBId"]
    other_user = users_collection.find_one({"telegramId": other_user_id})
    
    if other_user:
        await context.bot.send_message(
            chat_id=other_user["telegramId"],
            text="The other sports-finder has ended the match."
        )

    # Ask both users for feedback
    feedback_keyboard = [
        [InlineKeyboardButton("Yes", callback_data=f"feedback_yes_{match_document['_id']}")],
        [InlineKeyboardButton("No", callback_data=f"feedback_no_{match_document['_id']}")]
    ]
    feedback_markup = InlineKeyboardMarkup(feedback_keyboard)

    await context.bot.send_message(
        chat_id=user_telegram_id,
        text="Was a game played?",
        reply_markup=feedback_markup
    )
    await context.bot.send_message(
        chat_id=other_user_id,
        text="Was a game played?",
        reply_markup=feedback_markup
    )

# Callback function when feedback is provided
from bson import ObjectId  # Import ObjectId for MongoDB _id handling

# Callback function when feedback is provided
async def feedback_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query

    try:
        # Extract the feedback and match ID from the callback data
        feedback, match_id = query.data.split("_")[1], query.data.split("_")[2]
        user_telegram_id = query.from_user.id

        # Convert match_id to ObjectId
        match_id = ObjectId(match_id)

        # Find the match document
        match_document = matches_collection.find_one({"_id": match_id})

        if not match_document:
            await query.edit_message_text("Match not found.")
            return

        # Determine which user (A or B) provided the feedback
        if user_telegram_id == match_document["userAId"]:
            field_to_update = "gamePlayedA"
        elif user_telegram_id == match_document["userBId"]:
            field_to_update = "gamePlayedB"
        else:
            await query.edit_message_text("You are not part of this match.")
            return

        # Update the match document with the feedback
        matches_collection.update_one(
            {"_id": match_id},
            {"$set": {field_to_update: feedback}}
        )

        # Notify the user that their feedback has been recorded
        await query.edit_message_text(f"Thank you for your feedback! You responded: {feedback}.")

        # Check if both users have provided feedback
        updated_match_document = matches_collection.find_one({"_id": match_id})
        if updated_match_document.get("gamePlayedA") and updated_match_document.get("gamePlayedB"):
            # Both users have provided feedback
            await context.bot.send_message(
                chat_id=match_document["userAId"],
                text="Both users have provided feedback on whether a game was played."
            )
            await context.bot.send_message(
                chat_id=match_document["userBId"],
                text="Both users have provided feedback on whether a game was played."
            )
    except Exception as e:
        # Log the error and notify the user
        print(f"Error in feedback_response: {e}")
        await query.edit_message_text("An error occurred while processing your feedback. Please try again.")

# Function to forward messages between matched users
async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_telegram_id = update.message.from_user.id
    user = users_collection.find_one({"telegramId": user_telegram_id})

    if not user or not user.get("isMatched", False):
        return  # The user is not matched or doesn't exist
    
    # Find the match document for the user
    match_document = matches_collection.find_one({
        "$or": [
            {"userAId": user_telegram_id},
            {"userBId": user_telegram_id}
        ],
        "status": "active"
    })

    if not match_document:
        return  # No active match found

    # Determine the other user in the match
    other_user_id = match_document["userAId"] if match_document["userBId"] == user_telegram_id else match_document["userBId"]

    # Forward the message to the other user
    await context.bot.send_message(
        chat_id=other_user_id,
        text=f"Message from {user.get('displayName', 'Unknown')}: {update.message.text}"
    )

# Helper functions
def is_profile_complete(user):
    """Check if the user's profile is complete."""
    required_fields = ["age", "gender", "location", "sports"]
    return all(user.get(field) for field in required_fields)

def are_preferences_complete(user):
    """Check if the user's match preferences are complete."""
    return bool(user.get("matchPreferences"))

# Register the /start, /matchme, /endmatch command handlers and the message handler for forwarding messages
start_handler = CommandHandler('start', start)
application.add_handler(start_handler)

matchme_handler = CommandHandler('matchme', match_me)
application.add_handler(matchme_handler)

endmatch_handler = CommandHandler('endmatch', end_match)
application.add_handler(endmatch_handler)

message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, forward_message)
application.add_handler(message_handler)

# Register the callback query handler for sport selection
application.add_handler(CallbackQueryHandler(sport_selected, pattern="^sport_"))

# Register the callback query handler for feedback responses
application.add_handler(CallbackQueryHandler(feedback_response, pattern="^feedback_"))

# Start the bot
application.run_polling()