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
    ConversationHandler,
    ContextTypes,  # Import ContextTypes
)
from bson import ObjectId
import json
import datetime
from telegram.ext import JobQueue
import asyncio


# Load environment variables from .env file
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # MongoDB connection string

# Connect to MongoDB
mongo_client = MongoClient(DATABASE_URL)
db = mongo_client["test_database"]  # Use the database "sportsfinder"
users_collection = db["User"]  # Use the collection "users"
matches_collection = db["Match"]  # Use the collection "matches"
feedback_collection = db["Feedback"]  # Use the collection "Feedback"

# Create the Telegram Bot application
application = Application.builder().token(TOKEN).build()

# Mapping reason numbers to their full text descriptions
NO_GAME_REASONS = {
    "1": "Couldn’t find a common date",
    "2": "Match was unresponsive/unwilling to play",
    "3": "Uncomfortable with other player",
    "4": "Decided not to play",
    "5": "Others"
}

SMART_MATCH_WAIT_TIME = 60  # 1 hour in seconds (this is in seconds)

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
            f"Welcome to SportsFinder!\n\n"
            "This is a player matching service for your favourite sports. "
            "To begin, click on the button below to open our web app - "
            "it’ll give you access to view and edit your profile from there!"
        )

        # Create the web app button for first-time users
        keyboard = [[InlineKeyboardButton("My Profile", web_app={'url': 'https://test-webapp-sportsfinder.vercel.app/'})]]
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

# Function to handle /editprofile command
async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_first_name = update.message.from_user.first_name or "Unknown"
    user_username = update.message.from_user.username or "Unknown"
    user_telegram_id = update.message.from_user.id

    # Fetch the user's document from MongoDB
    user = users_collection.find_one({"telegramId": user_telegram_id})
    # Use the displayName from MongoDB, or fallback to first_name if not available
    user_display_name = user.get("displayName", update.message.from_user.first_name or "Unknown")

    
    # Craft the message with a personalized greeting and the web app button
    edit_profile_message = (
        f"Hi {user_display_name}! Click on the respective buttons below to edit bio or match preferences!"
    )
    
    # Create the web app button for editing profile
    keyboard = [
        [InlineKeyboardButton("Edit Profile", web_app={'url': 'https://test-webapp-profile-sportsfinder.vercel.app/'})],
        [InlineKeyboardButton("Edit Match Preferences", web_app={'url': 'https://test-webapp-matchpreferences-sportsfinder.vercel.app/'})]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the message with the button
    await update.message.reply_text(
        edit_profile_message,
        reply_markup=reply_markup
    )

# Function to handle /matchpreferences command
async def match_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_first_name = update.message.from_user.first_name or "Unknown"
    user_username = update.message.from_user.username or "Unknown"

    # Create a message for the user with a link to the web app to view/edit their match preferences
    message = (
        f"Hi {user_first_name}, you can click on the button below to open the web app! "
        "It’ll give you access to view and edit your match preferences from there!"
    )

    # Create the web app button
    keyboard = [[InlineKeyboardButton("Edit Match Preferences", web_app={'url': 'https://webapp-matchpreferences-sportsfinder.vercel.app/'})]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the message with the button
    await update.message.reply_text(
        message,
        reply_markup=reply_markup
    )

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
    if not await are_preferences_complete(update, user):
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

# Modify the sport_selected function to ask about Smart-Match
async def sport_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query

    sport = query.data.split("_")[1]  # Extract the selected sport
    user_telegram_id = query.from_user.id
    user = users_collection.find_one({"telegramId": user_telegram_id})

    if not user:
        await query.edit_message_text("User not found.")
        return
    
    # Ask about Smart-Match
    smart_match_keyboard = [
        [InlineKeyboardButton("On", callback_data=f"smartmatch_on_{sport}")],
        [InlineKeyboardButton("Off", callback_data=f"smartmatch_off_{sport}")]
    ]
    smart_match_markup = InlineKeyboardMarkup(smart_match_keyboard)
    
    await query.edit_message_text(
        f"Do you want Smart-Match on for {sport}?\n\n"
        "If no one is found within 1 hour, your match preference opens up to all options until you find a match.",
        reply_markup=smart_match_markup
    )

    # Add new callback handler for Smart-Match response
async def smart_match_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    _, smart_match_setting, sport = data.split("_")
    user_telegram_id = query.from_user.id
    
    # Update user's Smart-Match preference and start time
    users_collection.update_one(
        {"telegramId": user_telegram_id},
        {
            "$set": {
                "wantToBeMatched": True,
                "selectedSport": sport,
                "smartMatch": smart_match_setting == "on",
                "matchStartTime": datetime.datetime.now()
            }
        }
    )
    
    await query.edit_message_text(
        f"Got it! Smart-Match is turned {smart_match_setting} for {sport}. "
        f"Sportsfinding your player in {sport}..."
    )
    
    # Start the matching process
    await find_match(user_telegram_id, sport, context, smart_match_setting == "on")

# Modified matching function
async def find_match(user_telegram_id, sport, context, is_smart_match):
    user = users_collection.find_one({"telegramId": user_telegram_id})
    
    if not user:
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text="User not found."
        )
        return
    
    # First try to find a match with preferences
    match_found = await try_find_match(user_telegram_id, sport, context, use_preferences=True)
    
    if not match_found and is_smart_match:
        # If no match found and Smart-Match is on, schedule a check for later
        context.job_queue.run_once(
            smart_match_check,
            SMART_MATCH_WAIT_TIME,
            chat_id=user_telegram_id,
            name=f"smartmatch_{user_telegram_id}",
            data={
                "sport": sport,
                "start_time": datetime.datetime.now()
            }
        )
        
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text=f"No match found for {sport} at the moment. Please hang tight! If we can’t find a suitable match within an hour, we’ll try again with more flexible preferences."
        )

# Background job for Smart-Match check
async def smart_match_check(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_telegram_id = job.chat_id
    sport = job.data["sport"]
    start_time = job.data["start_time"]
    
    user = users_collection.find_one({"telegramId": user_telegram_id})
    
    if not user or not user.get("wantToBeMatched", False) or user.get("isMatched", False):
        return  # User is no longer looking for a match
    
    # Check if user still has Smart-Match on
    if not user.get("smartMatch", False):
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text=f"Smart-Match is no longer active for {sport}."
        )
        return

    # Notify user that preferences are being loosened!
    await context.bot.send_message(
        chat_id=user_telegram_id,
        text=f"⏳ Couldn't find a strict match for {sport} after 1 hour. Now expanding search to all available players with Smart-Match ON!"
    )
    
    # Try to find a match without considering preferences
    await try_find_match(user_telegram_id, sport, context, use_preferences=False)

# Unified matching function
async def try_find_match(user_telegram_id, sport, context, use_preferences=True):
    user = users_collection.find_one({"telegramId": user_telegram_id})
    
    if not user:
        return False
    
    if use_preferences:
        # Get user's preferences for the sport
        match_preferences = user.get("matchPreferences", {})
        if isinstance(match_preferences, str):
            try:
                match_preferences = json.loads(match_preferences)
            except json.JSONDecodeError:
                match_preferences = {}
        
        sport_preferences = match_preferences.get(sport, {})
        age_range = sport_preferences.get("ageRange", [1, 100])
        gender_preference = sport_preferences.get("genderPreference", "No preference")
        skill_levels = sport_preferences.get("skillLevels", [])
        location_preferences = set(sport_preferences.get("locationPreferences", []))
    else:
        # For Smart-Match, use very broad preferences
        age_range = [1, 100]
        gender_preference = "No preference"
        skill_levels = []
        location_preferences = set()
    
    # Find potential matches
    query = {
        "telegramId": {"$ne": user_telegram_id},
        "wantToBeMatched": True,
        "selectedSport": sport,
        "isMatched": False,
        "smartMatch": True
    }
    
    for potential_match in users_collection.find(query):
        # Check if we should consider preferences
        if use_preferences:
            # Get potential match's preferences for the sport
            potential_match_preferences = potential_match.get("matchPreferences", {})
            if isinstance(potential_match_preferences, str):
                try:
                    potential_match_preferences = json.loads(potential_match_preferences)
                except json.JSONDecodeError:
                    potential_match_preferences = {}
            
            potential_sport_preferences = potential_match_preferences.get(sport, {})
            potential_location_preferences = set(potential_sport_preferences.get("locationPreferences", []))
            
            # Check if potential match would accept this user
            potential_age_range = potential_sport_preferences.get("ageRange", [1, 100])
            potential_gender_preference = potential_sport_preferences.get("genderPreference", "No preference")
            potential_skill_levels = potential_sport_preferences.get("skillLevels", [])
            
            # Get user's data
            user_age = int(user.get("age", 0))
            user_gender = user.get("gender")
            user_sports = user.get("sports", {})
            user_skill_level = user_sports.get(sport, "Unknown")
            
            # Check if potential match would accept this user
            potential_gender_condition = (potential_gender_preference in ["No preference", "Either"] or 
                                        user_gender == potential_gender_preference)
            potential_age_condition = (potential_age_range[0] <= user_age <= potential_age_range[1])
            potential_skill_condition = (not potential_skill_levels or 
                                       user_skill_level in potential_skill_levels)
            
            if not (potential_gender_condition and potential_age_condition and potential_skill_condition):
                continue  # Skip if potential match wouldn't accept this user
        
        # Get potential match's data
        potential_match_age = int(potential_match.get("age", 0))
        potential_match_gender = potential_match.get("gender")
        potential_match_sports = potential_match.get("sports", {})
        potential_match_skill_level = potential_match_sports.get(sport, "Unknown")
        
        # Check if user would accept this match (only when using preferences)
        if use_preferences:
            gender_condition = (gender_preference in ["No preference", "Either"] or 
                              potential_match_gender == gender_preference)
            age_condition = (age_range[0] <= potential_match_age <= age_range[1])
            skill_condition = (not skill_levels or 
                             potential_match_skill_level in skill_levels)
            location_condition = (not location_preferences or 
                                len(location_preferences.intersection(potential_location_preferences)) > 0)
            
            if not (gender_condition and age_condition and skill_condition and location_condition):
                continue  # Skip if user wouldn't accept this match
        
        # If we get here, we have a match!
        match_document = {
            "userAId": user_telegram_id,
            "userBId": potential_match["telegramId"],
            "userAUsername": user.get("username", "Unknown"),
            "userBUsername": potential_match.get("username", "Unknown"),
            "sport": sport,
            "status": "active",
            "usedSmartMatch": not use_preferences  # Track if this was a Smart-Match
        }
        matches_collection.insert_one(match_document)
        
        # Update both users
        users_collection.update_many(
            {"telegramId": {"$in": [user_telegram_id, potential_match["telegramId"]]}},
            {"$set": {"isMatched": True, "wantToBeMatched": False, "smartMatch": False}}
        )
        
        # Notify both users
        await context.bot.send_message(
            chat_id=user_telegram_id,
            text=f"You have been matched with {potential_match.get('displayName', 'Unknown')} "
                 f"({potential_match_age}, {potential_match_gender}) for {sport}! 🎉\n"
                 f"You can now start chatting via this bot, type your messages below!"
        )
        
        await context.bot.send_message(
            chat_id=potential_match["telegramId"],
            text=f"You have been matched with {user.get('displayName', 'Unknown')} "
                 f"({user_age}, {user_gender}) for {sport}! 🎉\n"
                 f"You can now start chatting via this bot, type your messages below!" +
                 ("\n\nNote: This match was made with relaxed preferences using Smart-Match." if not use_preferences else "")
        )
        
        return True
    
    return False

# Handler for /endsearch command
async def end_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_telegram_id = update.message.from_user.id
    user = users_collection.find_one({"telegramId": user_telegram_id})
    
    if not user:
        await update.message.reply_text("Please complete your profile first!")
        return
    
    # Check if user is currently in a match
    if user.get("isMatched", False):
        await update.message.reply_text("You are currently in a match. Please use /endmatch to end your current match first.")
        return
    
    # Check if user is currently searching for matches
    if not user.get("wantToBeMatched", False):
        await update.message.reply_text("You are not currently searching for any matches.")
        return
    
    # Get the sports the user is currently searching for (as string)
    sports_selected_str = user.get("selectedSport", "")
    
    # Debug logging for sportsSelected
    print(f"[DEBUG] sportsSelected value: {sports_selected_str}")  # Log the value
    print(f"[DEBUG] sportsSelected type: {type(sports_selected_str)}")  # Log the type

    if not sports_selected_str:
        print(f"[DEBUG] sportsSelected is empty for user {user_telegram_id}")  # Debug log
        await update.message.reply_text("You are not currently searching for any sports.")
        return
    
    # Create inline keyboard with the single sport option
    # (assuming sportsSelected contains just one sport as a string)
    keyboard = [
        [InlineKeyboardButton(sports_selected_str, callback_data=f"endsearch_{sports_selected_str}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "You are currently searching for matches! Click the button below to stop searching:",
        reply_markup=reply_markup
    )

# Callback handler for end search selection
async def end_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_telegram_id = query.from_user.id
    data = query.data
    
    sport = data.split("_")[1]
    
    # Update MongoDB - set wantToBeMatched to false
    users_collection.update_one(
        {"telegramId": user_telegram_id},
        {"$set": {"wantToBeMatched": False, "smartMatch": False}}
    )
    
    await query.edit_message_text(f"OK, you have ended the search for {sport}.")

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
        {"$set": {"isMatched": False, "wantToBeMatched": False, "smartMatch": False}}  # Reset both flags
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

        # the other user
        other_user_id = match_document["userBId"] if user_telegram_id == match_document["userAId"] else match_document["userAId"]
        other_user = users_collection.find_one({"telegramId": other_user_id})
        other_user_display_name = other_user.get("displayName", "Unknown")

        # Notify the user that their feedback has been recorded
        await query.edit_message_text(f"How was your experience with {other_user_display_name}? You responded: ⭐ {rating}.")

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
        
        reason_text = NO_GAME_REASONS.get(reason, "Unknown reason")

        # Update the match document with the reason
        matches_collection.update_one(
            {"_id": match_id},
            {"$set": {field_to_update: reason}}
        )

        # Notify the user that their feedback has been recorded
        await query.edit_message_text(f"Why wasn’t a game played? You responded: {reason_text}.")

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
    required_fields = ["age", "gender", "sports"]
    return all(user.get(field) for field in required_fields)

async def are_preferences_complete(update: Update, user):
    """Check if the user's match preferences include all their sports."""
    
    # Extract user's sports and matchPreferences (ensuring matchPreferences is always a dictionary)
    sports = user.get("sports", [])  # Ensure we have a list of sports
    print("all sports user selected: ", sports, type(sports))
    
    # Retrieve the current user's match preferences for the selected sport
    match_preferences = user.get("matchPreferences", {})

    # Convert from string to dictionary 
    if isinstance(match_preferences, str):
        try:
            match_preferences = json.loads(match_preferences)  # Convert JSON string to dictionary
        except json.JSONDecodeError:
            print("Error: matchPreference is not a valid JSON format.")
            await update.message.reply_text("Your match preferences are not in a valid format. Please update them.")
            return False  # Return False if the JSON is invalid

    print("match preferences of the user", match_preferences, type(match_preferences))

    # Find sports that are missing from matchPreferences
    missing_sports = [sport for sport in sports if sport not in match_preferences]
    print("missing sports: ", missing_sports)

    # If there are missing sports, inform the user to complete their preferences
    if missing_sports:
        missing_sports_list = ", ".join(missing_sports)
        await update.message.reply_text(
            f"You haven’t selected match preferences for {missing_sports_list}! Use /profile to add in your match preferences before finding a match!"

        )
        return False  # Not all sports have match preferences

    return True  # All sports have match preferences

#for feedback
# Define states for the feedback conversation
FEEDBACK = 1

# Command handler for /feedback
async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_telegram_id = int(update.message.from_user.id)  # Ensure it's an integer
    user = users_collection.find_one({"telegramId": user_telegram_id})

    # Check if the user is in a match
    if user.get("isMatched", False):
        await update.message.reply_text(
            "You are currently in a match. End the match before providing feedback."
        )
        return  # Do not start the feedback conversation
    
    print("/feedback command triggered")  # Debugging print
    await update.message.reply_text("Provide any feedback/ reports here! Every response is greatly appreciated and every single one of them will be read! Type below:")
    context.user_data["feedback_state"] = FEEDBACK  # Debugging: Track state in user_data
    return FEEDBACK  # Move to the FEEDBACK state

# Message handler for receiving feedback
async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_username = update.message.from_user.username or "Unknown"

    """Receive the user's feedback and acknowledge it."""
    print("User sent feedback")  # Debugging print
    print(f"Current state: {context.user_data.get('feedback_state')}")  # Debugging print
    user_feedback = update.message.text  # Get the user's message
    user_telegram_id = update.message.from_user.id

    # Save the feedback to MongoDB
    feedback_collection.insert_one({
        "telegramId": user_telegram_id,
        "username": user_username,
        "feedback": user_feedback,
        "timestamp": datetime.datetime.now()
    })

    # Acknowledge the feedback
    await update.message.reply_text("Thanks for your feedback!")
    return ConversationHandler.END  # End the conversation

# Fallback handler to cancel the conversation
async def cancel_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the feedback conversation."""
    print("Feedback process cancelled")  # Debugging print
    await update.message.reply_text("Feedback process cancelled.")
    return ConversationHandler.END

# Define the setup_handlers function
def setup_handlers(application):
    # Feedback conversation handler
    feedback_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_command)],  # Start with /feedback
        states={
            FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback)],  # Wait for user input
        },
        fallbacks=[CommandHandler("cancel", cancel_feedback)],
    )

    # Add the feedback conversation handler to the application
    application.add_handler(feedback_conv_handler)
    # Add the Smart-Match callback handler
    application.add_handler(CallbackQueryHandler(smart_match_response, pattern="^smartmatch_"))

# Call the setup_handlers function to add the feedback conversation handler
setup_handlers(application)

# Register the /start, /matchme, /endmatch command handlers and the message handler for forwarding messages
start_handler = CommandHandler('start', start)
application.add_handler(start_handler)

editprofile_handler = CommandHandler('profile', edit_profile)
application.add_handler(editprofile_handler)

matchpreferences_handler = CommandHandler('matchpreferences', match_preferences)
application.add_handler(matchpreferences_handler)

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

#/endsearch
application.add_handler(CommandHandler('endsearch', end_search))
application.add_handler(CallbackQueryHandler(end_search_callback, pattern="^endsearch_"))

# smart match
application.add_handler(CallbackQueryHandler(smart_match_response, pattern="^smartmatch_"))

# Start the bot
application.run_polling()