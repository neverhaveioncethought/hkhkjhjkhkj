import random
import sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden
import logging

MULTIPLIERS_EASY = [1.2, 1.52, 2.0, 2.5, 3.0]
MULTIPLIERS_HARD = [1.2, 1.52, 2.0, 2.5, 3.5, 4.0, 5.0]
MULTIPLIERS_EXTREME = [1.2, 1.52, 2.07, 2.5, 3.5, 4.5, 6.0, 8.0, 10.0]

ALLOWED_USER_IDS = [6752577843]
OWNER_USER_ID = 6752577843
INITIAL_BALANCE = 5000.0

games = {}
user_balances = {}
user_stats = {}
user_preferences = {}

DATABASE = 'bot_data.db'

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Helper function to initialize the SQLite database
def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Create tables for user balances and stats
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_balances (
            user_id INTEGER PRIMARY KEY,
            balance REAL NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER PRIMARY KEY,
            total_bet REAL NOT NULL,
            total_winnings REAL NOT NULL
        )
    ''')

    conn.commit()
    conn.close()

# Helper function to get a user's balance from the database
def get_user_balance(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute('SELECT balance FROM user_balances WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result:
        balance = result[0]
    else:
        balance = INITIAL_BALANCE
        cursor.execute('INSERT INTO user_balances (user_id, balance) VALUES (?, ?)', (user_id, balance))

    conn.commit()
    conn.close()
    return balance

# Helper function to update a user's balance in the database
def update_user_balance(user_id, balance):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_balances SET balance = ? WHERE user_id = ?', (balance, user_id))
    conn.commit()
    conn.close()

# Helper function to get a user's stats from the database
def get_user_stats(user_id):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute('SELECT total_bet, total_winnings FROM user_stats WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result:
        total_bet, total_winnings = result
    else:
        total_bet = 0.0
        total_winnings = 0.0
        cursor.execute('INSERT INTO user_stats (user_id, total_bet, total_winnings) VALUES (?, ?, ?)',
                       (user_id, total_bet, total_winnings))

    conn.commit()
    conn.close()
    return total_bet, total_winnings

# Helper function to update a user's stats in the database
def update_user_stats(user_id, total_bet, total_winnings):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_stats SET total_bet = ?, total_winnings = ? WHERE user_id = ?',
                   (total_bet, total_winnings, user_id))
    conn.commit()
    conn.close()

# Helper function to get chat_id based on user preference
def get_chat_id(update: Update, user_id):
    """Return the correct chat_id (either group chat or DM) based on user preference."""
    if user_preferences.get(user_id) == "dm":
        return user_id  # Send to DM
    elif update.message:
        return update.message.chat_id  # Group chat
    elif update.callback_query:
        return update.callback_query.message.chat_id  # Callback in group chat

# /start command to show game options
async def start(update: Update, context):
    """Show game options (Play Game, Show Stats, Check Balance)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    intro_message = (
        "*Welcome to the Towers Game bot!*\n\n"
        "In Towers, you'll bet a certain amount and choose a difficulty level. "
        "If you make the right choices, you'll win big!\n\n"
        "To get started:\n"
        "- Use /tower to start a game\n"
        "- Use /balance to view your balance\n"
        "- Use /stats to view your stats\n"
        "- Use /leaderboard to view the leaderboard\n"
    )

    keyboard = [
        [InlineKeyboardButton("🎮 Play Game", callback_data="start_game")],
        [InlineKeyboardButton("📊 Show Stats", callback_data="show_stats")],
        [InlineKeyboardButton("💰 Check Balance", callback_data="check_balance")]
    ]

    await send_reply(update, context, intro_message, reply_markup=InlineKeyboardMarkup(keyboard))

# Handle button actions from /start command
async def handle_start_options(update: Update, context):
    """Handle the button options for playing a game, showing stats, or checking balance."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "show_stats":
        await user_stats_command(update, context)  # Call the stats command
    elif data == "start_game":
        # After clicking "Play Game", ask if they want to play in DM or group chat
        await ask_play_location(update, context)
    elif data == "check_balance":
        await check_balance(update, context)  # Call the function to check balance

    await query.answer()  # Acknowledge the query to stop loading

# Ask user whether they want to play in DM or group chat after clicking "Play Game"
async def ask_play_location(update: Update, context):
    """Ask the user where they want to play (DM or group chat)."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Ask user whether they want to play in DMs or group chat
    keyboard = [
        [InlineKeyboardButton("Play in DM", callback_data="play_dm"),
        InlineKeyboardButton("Play here", callback_data="play_group_chat")]
    ]

    await send_reply(
        update, context,
        text=f"{player_name}, Do you want to play in DMs or in the group chat?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Handle the user's choice of DM or Group Chat
async def handle_play_location_choice(update: Update, context):
    """Handle the user's choice of where to play the game (DM or group chat)."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    if data == "play_dm":
        user_preferences[user_id] = "dm"
        await query.answer("You chose to play in DM.")
        
        # Try to send a message in DM
        try:
            await context.bot.send_message(
                chat_id=user_id,  # This sends the message to the user's DM
                text="Let's start the game in your DM! Use /tower to begin."
            )
        except Forbidden:
            # If the bot is forbidden from sending a DM, ask the user to start a conversation with the bot
            await query.edit_message_text(
                f"{player_name}, it seems I cannot message you directly. Please start a conversation with me in DM first."
            )
        return

    elif data == "play_group_chat":
        user_preferences[user_id] = "group"
        await query.answer("You chose to play in the group chat.")

        # Now call the tower function to display betting options, editing the same message
        await tower(update, context, query=query)  # Pass the query to edit the message directly
        return

async def add_admin(update: Update, context):
    """Allow the bot owner to add a new admin by user ID."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    if user_id != OWNER_USER_ID:
        await send_reply(update, context, "You are not authorized to add admins.")
        return

    if len(context.args) != 1:
        await send_reply(update, context, "Usage: /add_admin <user_id>")
        return

    try:
        new_admin_id = int(context.args[0])
        if new_admin_id not in ALLOWED_USER_IDS:
            ALLOWED_USER_IDS.append(new_admin_id)
            await send_reply(update, context, f"User {new_admin_id} has been added as an admin.")
        else:
            await send_reply(update, context, f"User {new_admin_id} is already an admin.")
    except ValueError:
        await send_reply(update, context, "Please provide a valid user ID.")

# /remove_admin command to remove an admin (admin-only command)
async def remove_admin(update: Update, context):
    """Admin command to remove another admin from the list of authorized admins."""
    user_id = update.message.from_user.id

    # Check if the user is an admin
    if user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    # Ensure the command has the correct number of arguments
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /remove_admin <user_id>")
        return

    try:
        target_user_id = int(context.args[0])

        # Check if the target user is an admin
        if target_user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text(f"User {target_user_id} is not an admin.")
            return

        # Prevent the user from removing themselves
        if target_user_id == user_id:
            await update.message.reply_text("You cannot remove yourself from the admin list.")
            return

        # Remove the target user from the admin list
        ALLOWED_USER_IDS.remove(target_user_id)
        await update.message.reply_text(f"Successfully removed user {target_user_id} from the admin list.")

    except ValueError:
        await update.message.reply_text("Invalid user ID. Please provide a numeric user ID.")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")
        
# Helper function to reply to the user's message
async def send_reply(update, context, text, reply_markup=None):
    try:
        if update.message:
            chat_id = update.message.chat_id
            await context.bot.send_message(chat_id=chat_id, text=text, reply_to_message_id=update.message.message_id,
                                           reply_markup=reply_markup, parse_mode="Markdown")
        elif update.callback_query:
            chat_id = update.callback_query.message.chat_id
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        print(f"Error sending message: {e}")

ALLOWED_USER_IDS = [6752577843]  # List of admin user IDs (make sure it's populated correctly)



# /tower command to start the game and offer bet options
async def tower(update: Update, context, query=None):
    """Start the Tower game and prompt for bet amount, editing the same message if triggered from a callback query."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Get user balance from the database
    current_balance = get_user_balance(user_id)
    quarter_balance = current_balance / 4
    half_balance = current_balance / 2

    # Store initial game state in memory if it doesn't exist
    if user_id not in games:
        games[user_id] = {
            'bet': 0,
            'level': 0,
            'mode': None,
            'correct_buttons': [],
            'status': 'placing_bet',
            'initiated_by': user_id  # Store the user who initiated the game
        }
    # Display buttons for betting options: 1/4, 1/2, or custom bet
    keyboard = [
        [InlineKeyboardButton(f"Bet 1/4 (${quarter_balance:,.2f})", callback_data=f"bet_quarter_{user_id}"),
         InlineKeyboardButton(f"Bet 1/2 (${half_balance:,.2f})", callback_data=f"bet_half_{user_id}")],
        [InlineKeyboardButton("Enter Custom Bet", callback_data=f"bet_custom_{user_id}")]
    ]

    # If this was triggered from a callback query, edit the existing message
    if query:
        await query.edit_message_text(
            text=f"👤 Player: {player_name}\n💸 Current balance: *${current_balance:,.2f}*\n💵 Choose your bet amount:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        # If not, send a new message (e.g., when triggered by a command)
        await send_reply(
            update,
            context,
            text=f"👤 Player: {player_name}\n💸 Current balance: *${current_balance:,.2f}*\n💵 Choose your bet amount:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )





# /check_balance command to check user's balance
async def check_balance(update: Update, context):
    """Check and display the user's current balance."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    balance = get_user_balance(user_id)
    await send_reply(
        update,
        context,
        f"👤 Player: {player_name}\n\n🏦 Your current balance: *${balance:,.2f}*"
    )

# /stats command to show user's stats
async def user_stats_command(update: Update, context):
    """Command to show user stats."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Get user's current stats and balance from the database
    total_bet, total_winnings = get_user_stats(user_id)
    balance = get_user_balance(user_id)
    net_gain = total_winnings - total_bet

    await send_reply(
        update,
        context,
        f"👤 Player: {player_name}\n\n"
        f"📊 *Your Stats* 📊\n"
        f"🏦 Current Balance: *${balance:,.2f}*\n"
        f"💰 Total Bet: *${total_bet:,.2f}*\n"
        f"🎉 Total Won: *${total_winnings:,.2f}*\n"
        f"📈 Net Gain/Loss: *{'+' if net_gain >= 0 else '-'}${abs(net_gain):,.2f}*"
    )

# Handle bet options (1/4, 1/2 of the current balance or last bet, or custom)
async def handle_bet_option(update: Update, context):
    """Handle predefined bet options or custom bet."""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data.split('_')

    if int(data[2]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return
    
    # Check if the game state already exists for the user; initialize if not
    if user_id not in games:
        # Properly initialize the game state with all required keys
        games[user_id] = {
            'bet': 0,
            'level': 0,
            'mode': None,
            'correct_buttons': [],
            'status': 'placing_bet',
            'initiated_by': user_id,
            'last_bet': 0  # Set last_bet to 0 initially
        }

    game = games[user_id]  # Get the game state

    # Check if 'last_bet' exists in the game state, and initialize it if missing
    if 'last_bet' not in game:
        game['last_bet'] = 0

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name


    # Get the user's current balance from the database
    current_balance = get_user_balance(user_id)

    # For new bets, use the current balance if no last bet exists
    last_bet = current_balance if game['last_bet'] == 0 else game['last_bet']

    # Determine the new bet amount based on the button clicked
    if data[1] == 'quarter':
        bet = last_bet / 4  # Bet 1/4 of the last bet
    elif data[1] == 'half':
        bet = last_bet / 2  # Bet 1/2 of the last bet
    elif data[1] == 'double':
        bet = last_bet * 2  # Bet double the last bet
    elif data[1] == 'custom':
        # Set the game status to awaiting custom bet
        game['status'] = 'awaiting_custom_bet'
        await send_reply(
            update,
            context,
            text="Please enter your custom bet amount:",
            reply_markup=None  # Remove any buttons while waiting for input
        )
        return

    # Ensure the bet is correctly validated against the user's balance
    if bet > current_balance:
        await send_reply(
            update,
            context,
            f"👤 Player: {player_name}\n\n❌ Insufficient balance ❌\n\n🏦 Your current balance: *${current_balance:,.2f}*"
        )
        return

    # If balance is sufficient, process the bet
    await process_bet(update, context, bet, user_id)


# /leaderboard command to show top players by total wagered amount
async def leaderboard(update: Update, context):
    """Command to show leaderboard of top players by total wagered amount."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Fetch top players by total wagered amount (total_bet)
    cursor.execute('SELECT user_id, total_bet FROM user_stats ORDER BY total_bet DESC LIMIT 10')
    results = cursor.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("No leaderboard data available.")
        return

    # Create a leaderboard display
    leaderboard_text = "*🏆 Most Wagered 🏆*\n\n"
    medals = ['🥇', '🥈', '🥉']  # Medals for 1st, 2nd, and 3rd places

    for index, (user_id, total_bet) in enumerate(results, start=1):
        try:
            # Fetch user data from Telegram
            user_info = await context.bot.get_chat(user_id)
            username = f"@{user_info.username}" if user_info.username else user_info.full_name
        except:
            # If the user is not found or an error occurs, fall back to displaying a default username
            username = f"Player ({user_id})"

        # Add medal for top 3 places
        medal = medals[index - 1] if index <= 3 else ''  # Add a medal for top 3 users

        # Add each user to the leaderboard text
        leaderboard_text += f"{medal} {index}. {username}: *${total_bet:,.2f}* wagered\n"

    # Send the leaderboard as a message
    await update.message.reply_text(leaderboard_text, parse_mode="Markdown")


async def reset_leaderboard(update: Update, context):
    """Admin command to reset the leaderboard (total wagered amount)."""
    user_id = update.message.from_user.id

    # Check if the user is an admin
    if user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    # Reset the total_bet in the user_stats table
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_stats SET total_bet = 0')
    conn.commit()
    conn.close()

    await update.message.reply_text("Leaderboard has been reset.")

# Process the bet and start a new game after the betting options
async def process_bet(update: Update, context, bet, user_id):
    """Process the bet, check balance, and ask for difficulty selection."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    current_balance = get_user_balance(user_id)

    if bet > current_balance:
        await send_reply(update, context, f"👤 Player: {user.first_name}\n\n❌ Insufficient balance ❌")
        return

    new_balance = current_balance - bet
    update_user_balance(user_id, new_balance)

    total_bet, total_winnings = get_user_stats(user_id)
    total_bet += bet
    update_user_stats(user_id, total_bet, total_winnings)

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Reset game state to start fresh
    games[user_id]['bet'] = bet
    games[user_id]['last_bet'] = bet
    games[user_id]['level'] = 0  # Ensure level is reset
    games[user_id]['mode'] = None
    games[user_id]['correct_buttons'] = []
    games[user_id]['status'] = 'placing_bet'

    # Betting options (difficulty)
# Betting options (difficulty)
    keyboard = [
        [InlineKeyboardButton("Easy (5 levels)", callback_data=f'easy_{user_id}'),
        InlineKeyboardButton("Hard (7 levels)", callback_data=f'hard_{user_id}')],
        [InlineKeyboardButton("Extreme (9 levels)", callback_data=f'extreme_{user_id}')],  # Correct callback data
        [InlineKeyboardButton("Cancel Bet", callback_data=f'cancel_{user_id}')]
    ]


    # Check if the update is from a message or a callback query
    if update.callback_query:
        # Edit the existing message if this was a callback query
        await update.callback_query.edit_message_text(
            text=f"👤 Player: {player_name}\n\n💸 You bet: *${bet:,.2f}*\n🔐 Choose difficulty level or cancel.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    else:
        # If this was a regular message, send a new message
        await send_reply(
            update,
            context,
            text=f"👤 Player: {player_name}\n\n💸 You bet: *${bet:,.2f}*\n🔐 Choose difficulty level or cancel.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )



# Handle Cashout action
async def handle_cashout(update: Update, context):
    """Handle the cashout button press and end the game."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    game = games.get(user_id)

    if not game or game['status'] != 'playing':
        await query.answer("The game has already ended.", show_alert=True)
        return

    # Calculate winnings
    level = game['level']
    bet = game['bet']
    total_winnings = bet * game['multipliers'][level - 1] if level > 0 else bet

    player_name = f"@{user.username}" if user.username else user.full_name

    # Update user's balance
    current_balance = get_user_balance(user_id)
    new_balance = current_balance + total_winnings
    update_user_balance(user_id, new_balance)

    # Update user stats
    total_bet, total_winnings_stat = get_user_stats(user_id)
    update_user_stats(user_id, total_bet, total_winnings - bet)

    # Add the 'Play Again' button after cashing out
    keyboard = [
        [InlineKeyboardButton("Play Again❓", callback_data=f"play_again_{user_id}")]
    ]

    # Send a message with total winnings and new balance, including the 'Play Again' button
    await query.edit_message_text(
        text=f"👤 Player: {player_name}\n🎉 You cashed out with *${total_winnings:,.2f}*!\n💸 Your new balance is *${new_balance:,.2f}*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

    # Mark the game as ended
    game['status'] = 'cashed_out'


# Set difficulty and start the game
async def set_difficulty(update: Update, context):
    """Set difficulty and start the game."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    # Fetch the game state from the games dictionary
    game = games.get(user_id)

    # Check if game exists and is properly initialized
    if not game or 'initiated_by' not in game:
        await query.answer("Game state is invalid. Please restart the game.", show_alert=True)
        return

    # Validate that the user interacting is the same as the one who started the game
    if user_id != game['initiated_by']:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # If the correct user is interacting, proceed with setting difficulty
    mode = data[0]  # This should be 'easy', 'hard', or 'extreme'
    game['mode'] = mode
    bet_amount = game['bet']

    if mode == 'easy':
        game['multipliers'] = MULTIPLIERS_EASY
    elif mode == 'hard':
        game['multipliers'] = MULTIPLIERS_HARD
    elif mode == 'extreme':
        game['multipliers'] = MULTIPLIERS_EXTREME
    else:
        await query.answer("Invalid mode selected", show_alert=True)
        return

    # Proceed with creating level buttons and updating the game state
    game['level_buttons'] = await create_level_buttons(user_id)
    game['status'] = 'playing'

    # Enable buttons for the first level
    game['level_buttons'] = enable_buttons_for_level(game['level_buttons'], 0, user_id)

    # Display the bet amount and start the game
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    await query.edit_message_text(
        text=f"🏢 Towers  | 🍁 Fall Season\n👤 Player: {player_name}\n\nMode: {mode.capitalize()}\n💸 Bet amount: *${bet_amount:,.2f}*\n🎉 Good luck!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(game['level_buttons'])
    )



# Create level buttons with bet * multiplier values
async def create_level_buttons(user_id):
    """Create initial level buttons with bet * multiplier values."""
    game = games[user_id]
    bet = game['bet']
    multipliers = game['multipliers']

    buttons = []
    for level in range(len(multipliers)):
        row = []
        if game['mode'] == 'easy':
            num_buttons = 2
        elif game['mode'] == 'hard':
            num_buttons = 3
        elif game['mode'] == 'extreme':
            num_buttons = 4

        correct_button = random.randint(0, num_buttons - 1)  # Random correct button based on mode
        game['correct_buttons'].append(correct_button)  # Store the correct button for each level

        for i in range(num_buttons):
            amount = bet * multipliers[level]
            row.append(InlineKeyboardButton(f"${amount:,.2f}", callback_data=f"choice_{level}_{i}_{user_id}"))

        buttons.append(row)

    return buttons


# Handle the player's choice and update the game state
async def handle_choice(update: Update, context):
    """Handle the player's choice and update the game."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    # Fetch the game state for the current user
    game = games.get(user_id)

    # If no game exists, tell the user to start a new game
    if not game:
        await query.answer("No active game found.", show_alert=True)
        return

    # Check if the user interacting is not the one who started the game
    if user_id != game['initiated_by']:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    
    level, chosen_button = map(int, data[1:3])

    # Ensure the player is making a choice on the correct level
    if level != game['level']:
        await query.answer(f"You're on level {game['level']}! Please make a selection for the correct level.", show_alert=True)
        return

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    correct_button = game['correct_buttons'][level]

    if chosen_button == correct_button:
        # Player chose correctly
        game['level_buttons'][level][chosen_button] = InlineKeyboardButton("✅", callback_data="disabled")  # Mark correct choice
        for i in range(len(game['level_buttons'][level])):
            if i != chosen_button:
                game['level_buttons'][level][i] = InlineKeyboardButton("❌", callback_data="disabled")  # Mark other buttons as incorrect

        game['level'] += 1  # Move to the next level
        current_winnings = game['bet'] * game['multipliers'][game['level'] - 1]  # Calculate winnings for the current level

        # Check if the player has completed all levels
        if game['level'] >= len(game['multipliers']):
            winnings = game['bet'] * game['multipliers'][-1]
            current_balance = get_user_balance(user_id)
            new_balance = current_balance + winnings
            update_user_balance(user_id, new_balance)

            await query.edit_message_text(
                text=f"👤 Player: {player_name}\n\n🎉 Congratulations! You've completed all levels!\n💸 You won: *${winnings:,.2f}*",
                parse_mode='Markdown'
            )
            game['status'] = 'completed'
        else:
            # Update to enable buttons for the next level
            game['status'] = 'playing'
            game['level_buttons'] = enable_buttons_for_level(game['level_buttons'], game['level'], user_id)

        # Add a cashout button after the first correct answer
        if game['level'] == 1:
            game['level_buttons'].append(
                [InlineKeyboardButton(f"💰 Cashout (${current_winnings:,.2f})", callback_data=f"cashout_{user_id}")]
            )

    else:
        # Player chose incorrectly
        game['level_buttons'][level][chosen_button] = InlineKeyboardButton("Your choice ❌", callback_data="disabled")  # Mark incorrect choice
        game['level_buttons'][level][correct_button] = InlineKeyboardButton("Correct Choice ✅", callback_data="disabled")  # Mark correct button
        game['status'] = 'ended'

        # Add "Try Again" button after the player loses
        # Ensure that "Try Again" button appears below the existing buttons
        try_again_button = [InlineKeyboardButton("Try Again ❓", callback_data=f"try_again_{user_id}")]
        game['level_buttons'].append(try_again_button)

        # Update the message with the loss information and the "Try Again" button
        await query.edit_message_text(
            text=f"👤 Player: {player_name}\n\n❌ YOU LOST ❌\n\nYour new balance: *${get_user_balance(user_id):,.2f}*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(game['level_buttons'])
        )

    # Edit the message with the updated buttons after choice
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(game['level_buttons']))



# Handle the 'Play Again' button press and restart the game for the user
async def handle_play_again(update: Update, context):
    """Handle the 'Play Again' button press and start a new game."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    if int(data[2]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # Reset relevant parts of the game state for a new game
    games[user_id] = {
        'bet': 0,
        'level': 0,
        'mode': None,
        'correct_buttons': [],
        'status': 'placing_bet',
        'initiated_by': user_id,
        'last_bet': 0  # Reset the last bet for the new game
    }

    # Show betting options again
    current_balance = get_user_balance(user_id)
    quarter_balance = current_balance / 4
    half_balance = current_balance / 2

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    keyboard = [
        [InlineKeyboardButton(f"Bet 1/4 (${quarter_balance:,.2f})", callback_data=f"bet_quarter_{user_id}"),
         InlineKeyboardButton(f"Bet 1/2 (${half_balance:,.2f})", callback_data=f"bet_half_{user_id}")],
        [InlineKeyboardButton("Enter Custom Bet", callback_data=f"bet_custom_{user_id}")]
    ]

    # Edit the message to show betting options for the new game
    await query.edit_message_text(
        text=f"👤 Player: {player_name}\n\n💸 Current balance: *${current_balance:,.2f}*\n💵 Choose your bet amount to start a new game:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# Handle the 'Try Again' button press and reset the game state
async def handle_try_again(update: Update, context):
    """Handle the 'Try Again' button press and restart the game for the user."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    if int(data[2]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # Reset relevant parts of the game state
    game = games.get(user_id)
    if game:
        game['level'] = 0  # Reset level to start the game fresh
        game['correct_buttons'] = []  # Clear out old correct buttons
        game['status'] = 'placing_bet'  # Ensure the status is reset

    last_bet = game.get('last_bet', 0)

    # Show betting options again
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    quarter_bet = last_bet / 4
    half_bet = last_bet / 2
    double_bet = last_bet * 2

    keyboard = [
        [InlineKeyboardButton(f"Bet 1/4 (${quarter_bet:,.2f})", callback_data=f"bet_quarter_{user_id}"),
         InlineKeyboardButton(f"Bet 1/2 (${half_bet:,.2f})", callback_data=f"bet_half_{user_id}"),
         InlineKeyboardButton(f"Bet 2x (${double_bet:,.2f})", callback_data=f"bet_double_{user_id}")],
        [InlineKeyboardButton("Enter Custom Bet", callback_data=f"bet_custom_{user_id}")]
    ]

    # Edit the same message to show betting options
    await query.edit_message_text(
        text=f"👤 Player: {player_name}\n\n💸 Your last bet was *${last_bet:,.2f}*.\n💵 Choose your next bet amount or enter a custom bet.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



# Cancel the bet and reset the game
async def cancel_bet(update: Update, context):
    """Cancel the bet and reset the game without modifying the user's balance."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split('_')
    user = query.from_user

    # Get the user's bet from the game state
    game = games.get(user_id)
    if not game or game['status'] != 'placing_bet':
        await query.answer("No active bet to cancel.", show_alert=True)
        return

    bet_amount = game.get('bet', 0)  # Retrieve the bet amount from the game state

    # Refund the bet to the user's balance
    current_balance = get_user_balance(user_id)
    new_balance = current_balance + bet_amount
    update_user_balance(user_id, new_balance)

    # Log the refund and reset the game state
    games[user_id] = {}  # Reset the game state for this user

    # Respond to the user with a confirmation message and update UI
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Inform the user that the bet has been canceled and reset
    await query.edit_message_text(
        text=f"👤 Player: {player_name}\n\n❌ BET CANCELED ❌\n\nYour bet has been refunded. Current balance: *${new_balance:,.2f}*",
        parse_mode='Markdown'
    )




# Disable all buttons
def disable_all_buttons(buttons):
    return [[InlineKeyboardButton(button.text, callback_data="disabled") for button in row] for row in buttons]

# Enable buttons for the current level
def enable_buttons_for_level(buttons, level, user_id):
    """Enable buttons for the current level and keep others unchanged."""
    for i, row in enumerate(buttons):
        for j, button in enumerate(row):
            if i == level:
                buttons[i][j] = InlineKeyboardButton(button.text, callback_data=button.callback_data)
    return buttons


# Receive and process the custom bet
# Function that processes receiving a custom bet amount
async def receive_bet(update: Update, context):
    """Receive the custom bet amount if selected."""
    if update.message:
        user_id = update.message.from_user.id  # Get the user ID from the message
        user = update.message.from_user  # Get the user object
    else:
        return  # Exit early if there's no message

    # Fetch the game state
    game = games.get(user_id)

    # Ensure the game state exists and is awaiting a custom bet
    if not game or game['status'] != 'awaiting_custom_bet':
        return  # Ignore messages if the game is not in the custom bet phase

    # Get the user's current balance
    current_balance = get_user_balance(user_id)

    try:
        # Convert the message text to a float to interpret it as a bet amount, and handle commas
        bet = float(update.message.text.replace(',', ''))

        # Validate bet amount
        if bet > current_balance:
            await send_reply(update, context, f"👤 Player: {user.first_name}\n\n❌ Insufficient balance ❌\n🏦 Your current balance: *${current_balance:,.2f}*")
            return
        elif bet <= 0:
            await send_reply(update, context, "Please enter a valid bet amount greater than 0.")
            return

        # Proceed with bet processing after receiving the custom bet
        await process_bet(update, context, bet, user_id)

    except ValueError:
        # Handle invalid number format (e.g., non-numeric input)
        await send_reply(update, context, "Please enter a valid number.")

# Add balance to the user's account
async def add_balance(update: Update, context):
    """Add balance to a user's account (admin-only command)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    # Check if the user is authorized to add balance
    if user_id not in ALLOWED_USER_IDS:
        await send_reply(update, context, "You are not authorized to use this command.")
        return

    if len(context.args) < 2:
        await send_reply(update, context, "Usage: /add_balance <user_id> <amount>")
        return

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    try:
        target_user_id = int(context.args[0])
        amount = float(context.args[1])

        if amount <= 0:
            await send_reply(update, context, "Amount must be greater than zero.")
            return

        # Update the target user's balance
        current_balance = get_user_balance(target_user_id)
        new_balance = current_balance + amount
        update_user_balance(target_user_id, new_balance)

        await send_reply(
            update,
            context,
            f"Successfully added ${amount:,.2f} to user {target_user_id}. New balance: ${new_balance:,.2f}"
        )
    except ValueError:
        await send_reply(update, context, "Invalid input. Please provide numeric values.")

# Command to reset all user balances (restricted to allowed admins)
async def reset_balances(update: Update, context):
    """Reset all user balances to the default value (admin-only command)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    # Check if the user is authorized to reset balances (admin-only command)
    if user_id not in ALLOWED_USER_IDS:
        await send_reply(update, context, "You are not authorized to use this command.")
        return

    # Reset all user balances to the default value in the database
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_balances SET balance = ?', (INITIAL_BALANCE,))
    conn.commit()
    conn.close()

    # Send a confirmation message
    await send_reply(update, context, f"All user balances have been reset to the default: *${INITIAL_BALANCE:,.2f}*")

# Command to reset all user stats (restricted to allowed admins)
async def reset_stats(update: Update, context):
    """Reset all user stats to zero (admin-only command)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    # Check if the user is authorized to reset stats (admin-only command)
    if user_id not in ALLOWED_USER_IDS:
        await send_reply(update, context, "You are not authorized to use this command.")
        return

    # Reset all user stats (total_bet and total_winnings) to zero in the database
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_stats SET total_bet = 0, total_winnings = 0')
    conn.commit()
    conn.close()

    # Send a confirmation message
    await send_reply(update, context, "All user stats have been reset to zero.")

# Shutdown command
async def shutdown(update: Update, context):
    """Shutdown the bot (owner-only command)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    # Check if the user is the bot owner
    if user_id != OWNER_USER_ID:
        await send_reply(update, context, "You are not authorized to shut down the bot.")
        return

    # Send a confirmation message before shutting down
    await send_reply(update, context, "Shutting down the bot. Goodbye!")

    # Stop the bot's application
    context.application.stop()

# Main function
def main():
    init_db()

    TOKEN = "7852301454:AAEQ7oi4R-24dVqB3a6Anq0-YHng2dG_DPA"
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tower", tower))
    app.add_handler(CommandHandler("add_balance", add_balance))
    app.add_handler(CommandHandler("stats", user_stats_command))
    app.add_handler(CommandHandler("balance", check_balance))
    app.add_handler(CommandHandler("reset_balances", reset_balances))
    app.add_handler(CommandHandler("reset_stats", reset_stats))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("reset_leaderboard", reset_leaderboard))
    app.add_handler(CommandHandler("add_admin", add_admin))
    app.add_handler(CommandHandler("remove_admin", remove_admin))
    app.add_handler(CommandHandler("shutdown", shutdown))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bet))

    app.add_handler(CallbackQueryHandler(handle_play_location_choice, pattern='^play_dm|play_group_chat'))
    app.add_handler(CallbackQueryHandler(handle_start_options, pattern='^show_stats|start_game|check_balance'))
    app.add_handler(CallbackQueryHandler(handle_bet_option, pattern='^bet_'))
    app.add_handler(CallbackQueryHandler(set_difficulty, pattern='^easy_|^hard_|^extreme_'))
    app.add_handler(CallbackQueryHandler(cancel_bet, pattern='^cancel_'))
    app.add_handler(CallbackQueryHandler(handle_choice, pattern='^choice_'))
    app.add_handler(CallbackQueryHandler(handle_cashout, pattern='^cashout_'))



    app.add_handler(CallbackQueryHandler(handle_try_again, pattern='^try_again_'))
    app.add_handler(CallbackQueryHandler(handle_play_again, pattern='^play_again_'))


    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
