import random
import sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden
import logging

MULTIPLIERS_EASY = [1.2, 1.52, 2.07, 2.5, 3.0]
MULTIPLIERS_HARD = [1.2, 1.52, 2.07, 2.5, 3.5, 4.0, 5.0]
MULTIPLIERS_SPECIAL = [1.5, 2.0, 2.5, 3.0, 6.0]

ALLOWED_USER_IDS = [6752577843, 7040537198]
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
    data = query.data

    if data == "play_dm":
        user_preferences[user_id] = "dm"
        # Acknowledge the user about the game being moved to DM
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
                "It seems I cannot message you directly. Please start a conversation with me in DM first."
            )
        return
    
    elif data == "play_group_chat":
        user_preferences[user_id] = "group"
        await query.answer("You chose to play in the group chat.")
        await tower(update, context)  # Start the game in the group chat

    await query.answer()


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


# /tower command to start the game and offer bet options
async def tower(update: Update, context):
    """Start the Tower game and prompt for bet amount."""
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
        games[user_id] = {'bet': 0, 'level': 0, 'mode': None, 'correct_buttons': [], 'status': 'placing_bet'}

    # Display buttons for betting options: 1/4, 1/2, or custom bet
    keyboard = [
        [InlineKeyboardButton(f"Bet 1/4 (${quarter_balance:,.2f})", callback_data=f"bet_quarter_{user_id}"),
         InlineKeyboardButton(f"Bet 1/2 (${half_balance:,.2f})", callback_data=f"bet_half_{user_id}")],
        [InlineKeyboardButton("Enter Custom Bet", callback_data=f"bet_custom_{user_id}")]
    ]

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
        f"👤 Player: {player_name}\n\n💸 Your current balance: *${balance:,.2f}*"
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
        f"💸 Current Balance: *${balance:,.2f}*\n"
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

    # Check if the game state already exists for the user; initialize if not
    if user_id not in games:
        # Initialize game state for the user with default values
        games[user_id] = {
            'bet': 0,
            'level': 0,
            'mode': None,
            'correct_buttons': [],
            'status': 'placing_bet',
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
            f"👤 Player: {player_name}\n\n❌ Insufficient balance ❌\n\nYour current balance: *${current_balance:,.2f}*"
        )
        return

    # If balance is sufficient, process the bet
    await process_bet(update, context, bet, user_id)





# Process bet logic and display difficulty options
async def process_bet(update: Update, context, bet, user_id):
    """Process the bet, check balance, and ask for difficulty selection."""
    user = update.message.from_user if update.message else update.callback_query.from_user

    current_balance = get_user_balance(user_id)

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    if bet > current_balance:
        await send_reply(update, context, f"👤 Player: {player_name}\n\n❌ Insufficient balance ❌\n\nYour current balance is: *${current_balance:,.2f}*")
        return

    new_balance = current_balance - bet
    update_user_balance(user_id, new_balance)

    total_bet, total_winnings = get_user_stats(user_id)
    total_bet += bet
    update_user_stats(user_id, total_bet, total_winnings)

    games[user_id]['bet'] = bet
    games[user_id]['last_bet'] = bet
    games[user_id]['level'] = 0
    games[user_id]['mode'] = None
    games[user_id]['correct_buttons'] = []
    games[user_id]['status'] = 'placing_bet'

    # Define the keyboard here, where user_id is available
    keyboard = [
        [InlineKeyboardButton("Easy (5 levels)", callback_data=f'easy_{user_id}'),
         InlineKeyboardButton("Hard (8 levels)", callback_data=f'hard_{user_id}')],
        [InlineKeyboardButton("🍁 Season Mode", callback_data=f'special_{user_id}')],  # Special mode
        [InlineKeyboardButton("Cancel Bet", callback_data=f'cancel_{user_id}')]
    ]

    await send_reply(
        update,
        context,
        f"👤 Player: {player_name}\n\n💸 You bet: ${bet:,.2f}\n🔐 Choose difficulty level or cancel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )




# Handle Cashout action
async def handle_cashout(update: Update, context):
    """Handle the cashout button press and end the game."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    game = games.get(user_id)

    if not game or game['status'] != 'playing':
        await query.answer("The game has already ended.")
        return

    level = game['level']
    bet = game['bet']

    # Get player's name (username or full name)
    player_name = f"@{user.username}" if user.username else user.full_name

    # Calculate the total winnings (bet * current multiplier)
    if level == 0:
        total_winnings = bet  # If they cash out at level 0, they just get their bet back
    else:
        total_winnings = bet * game['multipliers'][level - 1]  # Total winnings at the current level

    # Log the cashout action
    logger.info(f"User {user_id} cashing out. Winnings: ${total_winnings:.2f}, bet: ${bet:.2f}, current balance: ${get_user_balance(user_id):.2f}")

    # Get user's current balance and add total winnings to it
    current_balance = get_user_balance(user_id)
    new_balance = current_balance + total_winnings
    update_user_balance(user_id, new_balance)

    # Log the new balance after cashout
    logger.info(f"User {user_id} new balance after cashout: ${new_balance:.2f}")

    # Update the user's stats (add the total winnings to the total_winnings in the stats)
    total_bet, total_winnings_stat = get_user_stats(user_id)
    update_user_stats(user_id, total_bet, total_winnings - bet)

    # Send a message to the user confirming their cashout with total winnings
    await send_reply(
        update, context,
        text=f"👤 Player: {player_name}\n\n💰 You've cashed out!\n🎉 Total winnings: *${total_winnings:,.2f}*\n💸 Your new balance is *${new_balance:,.2f}*"
    )

    # Mark the game as cashed out and disable further interactions
    game['status'] = 'cashed_out'
    game['level_buttons'] = disable_all_buttons(game['level_buttons'])

    # Disable all buttons after cashout
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(game['level_buttons']))

# Set difficulty and start the game
async def set_difficulty(update: Update, context):
    """Set difficulty and start the game."""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data.split('_')  # Split the callback data
    
    # Ensure the user_id in callback data matches the user interacting
    if int(data[1]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # Ensure the user is interacting with their own game session
    if games[user_id].get('user_id') != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # Ensure a valid bet exists
    if 'bet' not in games[user_id]:
        await query.answer("No active bet found. Please start a new game.", show_alert=True)
        return

    # Determine the player's name for messaging
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Capture the selected mode (easy, hard, special)
    mode = data[0]
    games[user_id]['mode'] = mode
    bet_amount = games[user_id]['bet']

    # Set the multipliers based on the selected mode
    if mode == 'easy':
        games[user_id]['multipliers'] = MULTIPLIERS_EASY
    elif mode == 'hard':
        games[user_id]['multipliers'] = MULTIPLIERS_HARD
    elif mode == 'special':
        games[user_id]['multipliers'] = MULTIPLIERS_SPECIAL  # For special mode
    else:
        await query.answer("Invalid mode selected", show_alert=True)
        return

    # Create the level buttons based on the selected difficulty
    games[user_id]['level_buttons'] = await create_level_buttons(user_id)
    games[user_id]['status'] = 'playing'

    # Enable buttons for the first level
    games[user_id]['level_buttons'] = enable_buttons_for_level(games[user_id]['level_buttons'], 0, user_id)

    # Update the message to reflect the start of the game
    await query.edit_message_text(
        f"🏢 Towers | 🍁 Fall season\n👤 Player: {player_name}\n\nMode: {mode.capitalize()}\n💸 Bet amount: *${bet_amount:,.2f}*\n🎉 Let's start the game!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(games[user_id]['level_buttons'])
    )

# Create level buttons with bet * multiplier values
async def create_level_buttons(user_id):
    """Create initial level buttons with bet * multiplier values."""
    game = games[user_id]
    bet = game['bet']
    multipliers = game['multipliers']
    mode = game['mode']  # Use the mode to determine the number of buttons per row

    buttons = []
    
    # Determine how many buttons per row based on the mode
    if mode == 'easy':
        num_buttons = 2  # Easy mode has 2 buttons per row
    elif mode == 'hard':
        num_buttons = 3  # Hard mode has 3 buttons per row
    elif mode == 'special':
        num_buttons = 4  # Special mode has 4 buttons per row
    else:
        num_buttons = 3  # Default to 3 in case of issues

    for level in range(len(multipliers)):
        row = []
        correct_button = random.randint(0, num_buttons - 1)  # Random correct button
        game['correct_buttons'].append(correct_button)  # Store the correct button for each level

        for i in range(num_buttons):
            amount = bet * multipliers[level]
            row.append(InlineKeyboardButton(f"${amount:,.2f}", callback_data=f"choice_{level}_{i}_{user_id}"))

        buttons.append(row)

    return buttons


# Update the keyboard for difficulty selection
keyboard = [
    [InlineKeyboardButton("Easy (5 levels)", callback_data=f'easy_{user_id}'),
     InlineKeyboardButton("Hard (8 levels)", callback_data=f'hard_{user_id}')],
    [InlineKeyboardButton("Special (8 levels)", callback_data=f'special_{user_id}')],  # Special mode
    [InlineKeyboardButton("Cancel Bet", callback_data=f'cancel_{user_id}')]
]


# Handle the player's choice and update the game state
async def handle_choice(update: Update, context):
    """Handle the player's choice and update the game."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split('_')
    user = query.from_user

    # Handle 'choice' separately
    if len(data) < 4:
        await query.answer("Invalid data received.", show_alert=True)
        return

    # Check if the button interaction is from the correct user
    if int(data[3]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    game = games.get(user_id)
    if not game or game['status'] != 'playing':
        await query.edit_message_text("The game has ended or you're not in a game session.")
        return

    # Handle level and button selection
    level, chosen_button = map(int, data[1:3])

    if level != game['level']:
        await query.answer(f"You're on level {game['level']}! Please make a selection for the correct level.", show_alert=True)
        return

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name


    correct_button = game['correct_buttons'][level]

    if chosen_button == correct_button:
        # Correct choice logic (No changes needed here)
        game['level_buttons'][level][chosen_button] = InlineKeyboardButton("✅", callback_data="disabled")
        for i in range(len(game['level_buttons'][level])):
            if i != chosen_button:
                game['level_buttons'][level][i] = InlineKeyboardButton("❌", callback_data="disabled")

        game['level'] += 1

        # Calculate the current winnings based on the level
        current_winnings = game['bet'] * game['multipliers'][game['level'] - 1]
        logger.info(f"User {user_id} chose correctly. Current winnings: ${current_winnings:.2f}")

        # Check if player completed all levels
        if game['level'] >= len(game['multipliers']):
            winnings = game['bet'] * game['multipliers'][-1]
            current_balance = get_user_balance(user_id)
            new_balance = current_balance + winnings
            update_user_balance(user_id, new_balance)
            logger.info(f"User {user_id} completed all levels. Winnings: ${winnings:.2f}, new balance: ${new_balance:.2f}")

            await send_reply(
                update,
                context,
                text=f"👤 Player: {user.first_name}\n\n🎉 Congratulations! You've completed all levels!\n💸 You won: *${winnings:,.2f}*"
            )
            game['status'] = 'completed'
        else:
            # Enable the buttons for the next level
            game['status'] = 'playing'
            game['level_buttons'] = enable_buttons_for_level(game['level_buttons'], game['level'], user_id)

        # Add the cashout button after the first correct answer
        if game['level'] == 1:
            game['level_buttons'].append(
                [InlineKeyboardButton(f"💰 Cashout (${current_winnings:,.2f})", callback_data=f"cashout_{user_id}")]
            )

    else:
        # If the player chose incorrectly, log the loss and confirm no extra balance deduction
        logger.info(f"User {user_id} lost at level {level}. No further deductions. Bet: ${game['bet']:.2f}, current balance: ${get_user_balance(user_id):.2f}")
        
        game['level_buttons'][level][chosen_button] = InlineKeyboardButton("Your choice ❌", callback_data="disabled")
        game['level_buttons'][level][correct_button] = InlineKeyboardButton("Correct Choice ✅", callback_data="disabled")
        game['status'] = 'ended'

        # Send a message with "Try Again" button
        await send_reply(
            update,
            context,
            text=f"👤 Player: {player_name}\n\n❌ YOU LOST ❌\n\nYour new balance: *${get_user_balance(user_id):,.2f}*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again❓", callback_data=f"try_again_{user_id}")]])
        )

        # Disable all buttons after the game ends
        game['level_buttons'] = disable_all_buttons(game['level_buttons'])

    # Edit the message with updated buttons
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(game['level_buttons']))

# Handle the 'Try Again' button press and restart the game for the user
# Handle the 'Try Again' button press and restart the game for the user
async def handle_try_again(update: Update, context):
    """Handle the 'Try Again' button press and restart the game for the user."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    # Ensure the correct user is interacting
    if int(data[2]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # Retrieve the last bet amount
    game = games.get(user_id)
    if not game or 'last_bet' not in game:
        await send_reply(
            update,
            context,
            text="No previous bet found. Please start a new game."
        )
        return

    last_bet = game['last_bet']  # Get the last bet

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Create buttons for bet options based on the last bet
    quarter_bet = last_bet / 4
    half_bet = last_bet / 2
    double_bet = last_bet * 2

    # Create the buttons for the new bet options
    keyboard = [
        [InlineKeyboardButton(f"Bet 1/4 (${quarter_bet:,.2f})", callback_data=f"bet_quarter_{user_id}"),
         InlineKeyboardButton(f"Bet 1/2 (${half_bet:,.2f})", callback_data=f"bet_half_{user_id}"),
         InlineKeyboardButton(f"Bet 2x (${double_bet:,.2f})", callback_data=f"bet_double_{user_id}")],
        [InlineKeyboardButton("Enter Custom Bet", callback_data=f"bet_custom_{user_id}")]
    ]

    # Prompt the user to place a new bet based on the last bet
    await send_reply(
        update,
        context,
        text=(
            f"👤 Player: {player_name}\n\n💸 Your last bet was *${last_bet:,.2f}*.\n"
            f"💵 Choose your next bet amount or enter a custom bet."
        ),
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

    # Log the refund
    logger.info(f"User {user_id} cancelled the bet of ${bet_amount:.2f}, refunded to balance. New balance: ${new_balance:.2f}")

    # Reset the game state for this user
    games[user_id] = {}

    # Respond to the user with a confirmation message and update UI
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    await send_reply(
        update,
        context,
        text=f"👤 Player: {player_name}\n\n❌ BET CANCELED ❌\n\nYour balance has been refunded. Current balance: *${new_balance:,.2f}*"
    )

    # Disable any active buttons to prevent further interaction
    await query.edit_message_reply_markup(reply_markup=None)

    # Acknowledge the query to prevent loading animation
    await query.answer()


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

# Receive and process the custom bet amount
async def receive_bet(update: Update, context):
    """Receive the custom bet amount if selected."""
    if update.message:
        user_id = update.message.from_user.id  # User ID from the message
        user = update.message.from_user  # Get the user from the message
    else:
        return  # Safeguard: If there's no message, exit early

    # Check if the user is in the game phase expecting a custom bet
    if user_id not in games or games[user_id].get('status') != 'awaiting_custom_bet':
        return  # Ignore messages if the game is not in the custom bet-placing phase

    # Get player's name (username or full name)
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    try:
        # Convert the message text to a float to interpret it as a bet amount
        bet = float(update.message.text)

        # Validate bet amount
        if bet > get_user_balance(user_id):
            await send_reply(update, context, f"👤 Player: {player_name}\n\n❌ Insufficient balance ❌\nYour current balance: *${get_user_balance(user_id):,.2f}*")
            return
        elif bet <= 0:
            await send_reply(update, context, "Please enter a valid bet amount greater than 0.")
            return

        # Proceed with bet processing after receiving the custom bet
        await process_bet(update, context, bet, user_id)

    except ValueError:
        # Only send the error message if the bot is in the custom betting phase
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
    app.add_handler(CommandHandler("shutdown", shutdown))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bet))

    app.add_handler(CallbackQueryHandler(handle_play_location_choice, pattern='^play_dm|play_group_chat'))
    app.add_handler(CallbackQueryHandler(handle_start_options, pattern='^show_stats|start_game|check_balance'))
    app.add_handler(CallbackQueryHandler(handle_bet_option, pattern='^bet_'))
    app.add_handler(CallbackQueryHandler(set_difficulty, pattern='^easy_|hard_|special_'))
    app.add_handler(CallbackQueryHandler(cancel_bet, pattern='^cancel_'))
    app.add_handler(CallbackQueryHandler(handle_choice, pattern='^choice_'))
    app.add_handler(CallbackQueryHandler(handle_cashout, pattern='^cashout_'))

    app.add_handler(CallbackQueryHandler(handle_try_again, pattern='^try_again_'))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
