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
            other_user_id = match_document["userBId"]
        elif user_telegram_id == match_document["userBId"]:
            field_to_update = "gamePlayedB"
            other_user_id = match_document["userAId"]
        else:
            await query.edit_message_text("You are not part of this match.")
            return

        # Update the match document with the feedback
        matches_collection.update_one(
            {"_id": match_id},
            {"$set": {field_to_update: feedback}}
        )

        # Notify the user that their feedback has been recorded
        await query.edit_message_text(f"Was the game played? You responded: {feedback}.")

        # Ask follow-up questions based on the response
        if feedback == "yes":
            # Ask about the experience with the bot
            bot_experience_keyboard = [
                [InlineKeyboardButton("⭐ 1", callback_data=f"bot_experience_1_{match_id}")],
                [InlineKeyboardButton("⭐ 2", callback_data=f"bot_experience_2_{match_id}")],
                [InlineKeyboardButton("⭐ 3", callback_data=f"bot_experience_3_{match_id}")],
                [InlineKeyboardButton("⭐ 4", callback_data=f"bot_experience_4_{match_id}")],
                [InlineKeyboardButton("⭐ 5", callback_data=f"bot_experience_5_{match_id}")]
            ]
            bot_experience_markup = InlineKeyboardMarkup(bot_experience_keyboard)
            await context.bot.send_message(
                chat_id=user_telegram_id,
                text="How was your experience using SportsFinder’s bot?",
                reply_markup=bot_experience_markup
            )
        else:
            # Ask why the game wasn't played
            no_game_reasons_keyboard = [
                [InlineKeyboardButton("Couldn’t find a common date", callback_data=f"no_game_reason_1_{match_id}")],
                [InlineKeyboardButton("Match was unresponsive/unwilling to play", callback_data=f"no_game_reason_2_{match_id}")],
                [InlineKeyboardButton("Uncomfortable with other player", callback_data=f"no_game_reason_3_{match_id}")],
                [InlineKeyboardButton("Decided not to play", callback_data=f"no_game_reason_4_{match_id}")],
                [InlineKeyboardButton("Others", callback_data=f"no_game_reason_5_{match_id}")]
            ]
            no_game_reasons_markup = InlineKeyboardMarkup(no_game_reasons_keyboard)
            await context.bot.send_message(
                chat_id=user_telegram_id,
                text="Sorry to hear that! Why wasn’t a game played?",
                reply_markup=no_game_reasons_markup
            )

    except Exception as e:
        # Log the error and notify the user
        print(f"Error in feedback_response: {e}")
        await query.edit_message_text("An error occurred while processing your feedback. Please try again.")

# Callback function for bot experience rating
async def bot_experience_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query

    try:
        # Extract the rating and match ID from the callback data
        rating, match_id = query.data.split("_")[2], query.data.split("_")[3]
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
            field_to_update = "botExperienceA"
        elif user_telegram_id == match_document["userBId"]:
            field_to_update = "botExperienceB"
        else:
            await query.edit_message_text("You are not part of this match.")
            return

        # Update the match document with the bot experience rating
        matches_collection.update_one(
            {"_id": match_id},
            {"$set": {field_to_update: rating}}
        )

        # Notify the user that their feedback has been recorded
        await query.edit_message_text(f"How was your experience using SportsFinder’s bot? You responded: ⭐ {rating}.")

        # Ask about the experience with the matched user
        other_user_id = match_document["userBId"] if user_telegram_id == match_document["userAId"] else match_document["userAId"]
        other_user = users_collection.find_one({"telegramId": other_user_id})
        other_user_display_name = other_user.get("displayName", "Unknown")

        user_experience_keyboard = [
            [InlineKeyboardButton("⭐ 1", callback_data=f"user_experience_1_{match_id}")],
            [InlineKeyboardButton("⭐ 2", callback_data=f"user_experience_2_{match_id}")],
            [InlineKeyboardButton("⭐ 3", callback_data=f"user_experience_3_{match_id}")],
            [InlineKeyboardButton("⭐ 4", callback_data=f"user_experience_4_{match_id}")],
            [InlineKeyboardButton("⭐ 5", callback_data=f"user_experience_5_{match_id}")]
        ]
        user_experience_markup = InlineKeyboardMarkup(user_experience_keyboard)
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text=f"How was your experience with {other_user_display_name}?",
            reply_markup=user_experience_markup
        )

    except Exception as e:
        # Log the error and notify the user
        print(f"Error in bot_experience_response: {e}")
        await query.edit_message_text("An error occurred while processing your feedback. Please try again.")

# Callback function for user experience rating
async def user_experience_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query

    try:
        # Extract the rating and match ID from the callback data
        rating, match_id = query.data.split("_")[2], query.data.split("_")[3]
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
            field_to_update = "userExperienceA"
        elif user_telegram_id == match_document["userBId"]:
            field_to_update = "userExperienceB"
        else:
            await query.edit_message_text("You are not part of this match.")
            return

        # Update the match document with the user experience rating
        matches_collection.update_one(
            {"_id": match_id},
            {"$set": {field_to_update: rating}}
        )

        # Notify the user that their feedback has been recorded
        await query.edit_message_text(f"How was your experience with the matched user? You responded: ⭐ {rating}.")

        # Send a final thank you message
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text="Thank you for your feedback!"
        )

    except Exception as e:
        # Log the error and notify the user
        print(f"Error in user_experience_response: {e}")
        await query.edit_message_text("An error occurred while processing your feedback. Please try again.")

# Callback function for no game reasons
async def no_game_reason_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query

    try:
        # Extract the reason and match ID from the callback data
        callback_data = query.data
        parts = callback_data.split("_", 4)  # Split into 5 parts only
        
        if len(parts) != 5:
            await query.edit_message_text("Invalid callback data format.")
            return

        reason, match_id = parts[3], parts[4]
        user_telegram_id = query.from_user.id

        # Convert match_id to ObjectId
        try:
            match_id = ObjectId(match_id)
        except Exception as e:
            await query.edit_message_text("Invalid match ID.")
            return

        # Find the match document
        match_document = matches_collection.find_one({"_id": match_id})

        if not match_document:
            await query.edit_message_text("Match not found.")
            return

        # Determine which user (A or B) provided the feedback
        if user_telegram_id == match_document["userAId"]:
            field_to_update = "noGameReasonA"
        elif user_telegram_id == match_document["userBId"]:
            field_to_update = "noGameReasonB"
        else:
            await query.edit_message_text("You are not part of this match.")
            return

        # Update the match document with the reason
        matches_collection.update_one(
            {"_id": match_id},
            {"$set": {field_to_update: reason}}
        )

        # Notify the user that their feedback has been recorded
        await query.edit_message_text(f"Why wasn’t a game played? You responded: {reason}.")

        # Send a final thank you message
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text="Thank you for your feedback!"
        )

    except Exception as e:
        # Log the error and notify the user
        print(f"Error in no_game_reason_response: {e}")
        await query.edit_message_text("An error occurred while processing your feedback. Please try again.")

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

# Register the callback query handlers for follow-up questions
application.add_handler(CallbackQueryHandler(bot_experience_response, pattern="^bot_experience_"))
application.add_handler(CallbackQueryHandler(user_experience_response, pattern="^user_experience_"))
application.add_handler(CallbackQueryHandler(no_game_reason_response, pattern="^no_game_reason_"))

# Start the bot
application.run_polling()