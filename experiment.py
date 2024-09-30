import random
import sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden

MULTIPLIERS_EASY = [1.2, 1.52, 2.07, 2.5, 3.0]
MULTIPLIERS_HARD = [1.2, 1.52, 2.07, 2.5, 3.5, 4.0, 5.0]

ALLOWED_USER_IDS = [6752577843]

OWNER_USER_ID = 6752577843

INITIAL_BALANCE = 5000.0  

games = {}
user_balances = {}
user_stats = {}
user_preferences = {}

DATABASE = 'bot_data.db'

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
        await query.answer("You chose to play in DM.")
        await tower(update, context)  # Start the game in DM
    elif data == "play_group_chat":
        user_preferences[user_id] = "group"
        await query.answer("You chose to play in the group chat.")
        await tower(update, context)  # Start the game in group chat

    await query.answer()

# Helper function to reply to the user's message
async def send_reply(update, context, text, reply_markup=None):
    """Send a reply to the correct chat (group chat or DM)."""
    try:
        if update.message:
            chat_id = update.message.chat_id
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        elif update.callback_query:
            chat_id = update.callback_query.message.chat_id
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except Forbidden:
        print(f"Cannot send message to user {update.message.from_user.id}. They may have blocked the bot.")



# /tower command to start the game and offer bet options
async def tower(update: Update, context):
    """Start the Tower game and prompt for bet amount."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

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
        text=f"👤 Player: {user.first_name}\n💸 Current balance: *${current_balance:,.2f}*\nChoose your bet amount:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



# /check_balance command to check user's balance
async def check_balance(update: Update, context):
    """Check and display the user's current balance."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    balance = get_user_balance(user_id)
    await send_reply(
        update,
        context,
        f"👤 Player: {user.first_name}\n\n💸 Your current balance: *${balance:,.2f}*"
    )


# /stats command to show user's stats
async def user_stats_command(update: Update, context):
    """Command to show user stats."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    # Get user's current stats and balance from the database
    total_bet, total_winnings = get_user_stats(user_id)
    balance = get_user_balance(user_id)
    net_gain = total_winnings - total_bet

    await send_reply(
        update,
        context,
        f"👤 Player: {user.first_name}\n\n"
        f"📊 *Your Stats* 📊\n"
        f"💸 Current Balance: *${balance:,.2f}*\n"
        f"💰 Total Bet: *${total_bet:,.2f}*\n"
        f"🎉 Total Won: *${total_winnings:,.2f}*\n"
        f"📈 Net Gain/Loss: *{'+' if net_gain >= 0 else '-'}${abs(net_gain):,.2f}*"
    )


# Handle Cashout action
async def handle_cashout(update: Update, context):
    """Handle the cashout button press and end the game."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    # Ensure that the callback data and user ID match
    if int(data[1]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    game = games.get(user_id)
    if not game or game['status'] != 'playing':
        await query.answer("The game has already ended.")
        return

    # Get player's name (username or full name)
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Calculate the total winnings (this includes the original bet + winnings)
    if game['level'] == 0:
        winnings = game['bet']
    else:
        winnings = game['bet'] * game['multipliers'][game['level'] - 1]

    # Calculate the net winnings (this is what the player actually won, excluding the original bet)
    net_winnings = winnings - game['bet']

    # Get user's current stats from the database
    total_bet, total_winnings = get_user_stats(user_id)

    # Update user's total winnings in stats
    total_winnings += net_winnings
    update_user_stats(user_id, total_bet, total_winnings)

    # Add the net winnings to the user's balance
    current_balance = get_user_balance(user_id)
    new_balance = current_balance + net_winnings
    update_user_balance(user_id, new_balance)

    # Send a message to the user confirming their cashout and showing only the net winnings
    await send_reply(
        update,
        context,
        text=f"👤 Player: {player_name}\n\n💰 You've cashed out!\n📈 Net gain: *${net_winnings:,.2f}*!\n💸 Your new balance is *${new_balance:,.2f}*"
    )

    # Mark the game as cashed out and disable further interactions
    game['status'] = 'cashed_out'
    game['level_buttons'] = disable_all_buttons(game['level_buttons'])

    # Disable all buttons after cashout
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(game['level_buttons']))



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
            f"Successfully added ${amount:,.2f} to user {player_name}. New balance: ${new_balance:,.2f}"
        )
    except ValueError:
        await send_reply(update, context, "Invalid input. Please provide numeric values.")





# Handle Cashout action
# Handle Cashout action
async def handle_cashout(update: Update, context):
    """Handle the cashout button press and end the game."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    # Ensure that the callback data and user ID match
    if int(data[1]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    game = games.get(user_id)
    if not game or game['status'] != 'playing':
        await query.answer("The game has already ended.")
        return

    # Get player's name (username or full name)
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Calculate the total winnings (this includes the original bet + winnings)
    if game['level'] == 0:
        winnings = game['bet']
    else:
        winnings = game['bet'] * game['multipliers'][game['level'] - 1]

    # Calculate the net winnings (this is what the player actually won, excluding the original bet)
    net_winnings = winnings - game['bet']

    # Get user's current stats from the database
    total_bet, total_winnings = get_user_stats(user_id)

    # Update user's total winnings in stats
    total_winnings += net_winnings
    update_user_stats(user_id, total_bet, total_winnings)

    # Add the net winnings to the user's balance
    current_balance = get_user_balance(user_id)
    new_balance = current_balance + net_winnings
    update_user_balance(user_id, new_balance)

    # Send a message to the user confirming their cashout and showing only the net winnings
    await send_reply(
        update,
        context,
        text=f"👤 Player: {player_name}\n\n💰 You've cashed out!\n📈 Net gain: *${net_winnings:,.2f}*!\n💸 Your new balance is *${new_balance:,.2f}*"
    )

    # Mark the game as cashed out and disable further interactions
    game['status'] = 'cashed_out'
    game['level_buttons'] = disable_all_buttons(game['level_buttons'])

    # Disable all buttons after cashout
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(game['level_buttons']))





# Handle bet options (1/4, 1/2 of the current balance or last bet, or custom)
async def handle_bet_option(update: Update, context):
    """Handle predefined bet options or custom bet."""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data.split('_')

    # Get the user's current balance from the database
    current_balance = get_user_balance(user_id)

    # Determine the bet amount based on the button clicked
    if data[1] == 'quarter':
        bet = current_balance / 4  # Bet exactly 1/4 of the current balance
    elif data[1] == 'half':
        bet = current_balance / 2  # Bet exactly 1/2 of the current balance
    elif data[1] == 'custom':
        # Set the game status to awaiting custom bet
        games[user_id]['status'] = 'awaiting_custom_bet'
        await send_reply(
            update,
            context,
            text="Please enter your custom bet amount:",
            reply_markup=None  # Remove any buttons while waiting for input
        )
        return

    # Ensure the bet is correctly validated against the current balance
    if bet > current_balance:
        await send_reply(
            update,
            context,
            f"❌ Insufficient balance.\nYour current balance: *${current_balance:,.2f}*"
        )
        return
    else:
        # If balance is sufficient, process the bet
        await process_bet(update, context, bet, user_id)








# Cancel the bet and reset the game
async def cancel_bet(update: Update, context):
    """Cancel the bet and reset the game without modifying the user's balance."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split('_')
    user = query.from_user



    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name
    # Ensure the cancel action is for the right user
    if int(data[1]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # Ensure a game exists and the status allows cancellation
    game = games.get(user_id)
    if not game or game['status'] != 'placing_bet':
        await query.answer("No active bet to cancel.", show_alert=True)
        return

    # Reset the game state for this user
    games[user_id] = {}

    # Respond to the user with a confirmation message and update UI
    await send_reply(
        update,
        context,
        text=f"👤 Player: {player_name}\n\n❌BET CANCELED❌\n\nYour balance remains *${user_balances[user_id]:,.2f}*"
    )

    # Disable any active buttons to prevent further interaction
    await query.edit_message_reply_markup(reply_markup=None)

    # Acknowledge the query to prevent loading animation
    await query.answer()




# Handle the 'Try Again' button press and restart the game for the user
async def handle_try_again(update: Update, context):
    """Handle the 'Try Again' button press and restart the game for the user."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    if int(data[2]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # Retrieve the last bet amount
    last_bet = games[user_id].get('last_bet', 0)

    if last_bet == 0:
        await send_reply(
            update,
            context,
            text="No previous bet found. Please start a new game."
        )
        return

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Calculate new bet options based on the last bet
    quarter_bet = last_bet / 4
    half_bet = last_bet / 2
    double_bet = last_bet * 2  # 2x Bet option

    # Create the buttons for the new bet options, including the 2x Bet
    keyboard = [
        [InlineKeyboardButton(f"Bet 1/4 (${quarter_bet:,.2f})", callback_data=f"bet_quarter_{user_id}"),
         InlineKeyboardButton(f"Bet 1/2 (${half_bet:,.2f})", callback_data=f"bet_half_{user_id}"),
         InlineKeyboardButton(f"Bet 2x (${double_bet:,.2f})", callback_data=f"bet_double_{user_id}")],  # Add 2x Bet option
        [InlineKeyboardButton("Enter Custom Bet", callback_data=f"bet_custom_{user_id}")]
    ]

    # Prompt the user to place a new bet based on the last bet
    await send_reply(
        update,
        context,
        text=(
            f"👤 Player: {player_name}\n\n💸 Your last bet was *${last_bet:,.2f}*.\n"
            f"Choose your next bet amount or enter a custom bet."
        ),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )




# Process bet logic and display difficulty options
async def process_bet(update: Update, context, bet, user_id):
    """Process the bet, check balance, and ask for difficulty selection."""
    user = update.message.from_user if update.message else update.callback_query.from_user

    # Get the user's current balance from the database
    current_balance = get_user_balance(user_id)

    if bet > current_balance:
        await send_reply(update, context, f"❌ Insufficient balance. Your current balance is: *${current_balance:,.2f}*")
        return

    # Deduct the bet from the user's balance
    new_balance = current_balance - bet
    update_user_balance(user_id, new_balance)  # Update the balance in the database

    # Get user's current stats from the database
    total_bet, total_winnings = get_user_stats(user_id)

    # Update the total bet in the stats
    total_bet += bet
    update_user_stats(user_id, total_bet, total_winnings)

    # Store the bet and initialize the game state
    games[user_id] = {
        'bet': bet,  # Store the current bet
        'level': 0,
        'mode': None,
        'correct_buttons': [],
        'status': 'placing_bet',
        'last_bet': bet  # Store the bet for future reference (used for Try Again)
    }

    # Display difficulty selection buttons
    keyboard = [
        [InlineKeyboardButton("Easy (5 levels)", callback_data=f'easy_{user_id}'),
         InlineKeyboardButton("Hard (8 levels)", callback_data=f'hard_{user_id}')],
        [InlineKeyboardButton("Cancel Bet", callback_data=f'cancel_{user_id}')]
    ]

    await send_reply(
        update,
        context,
        f"👤 Player: {user.first_name}\n\n💸 You bet: ${bet:,.2f}\n🔐 Choose difficulty level or cancel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# 👤 Player: {player_name}\n\n
#    if user.username:
#        player_name = f"@{user.username}"
#    else:
#        player_name = user.full_name or user.first_name


# Set difficulty and start the game
# Set difficulty and start the game
async def set_difficulty(update: Update, context):
    """Set difficulty and start the game."""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data.split('_')

    if int(data[1]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    # Check if the bet exists in the game session
    if 'bet' not in games[user_id]:
        await query.answer("No active bet found. Please start a new game.", show_alert=True)
        return

    # Get the player's name (username or full name)
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    # Set the difficulty mode and initialize the game state
    mode = data[0]
    games[user_id]['mode'] = mode
    bet_amount = games[user_id]['bet']

    if mode == 'easy':
        games[user_id]['multipliers'] = MULTIPLIERS_EASY
    elif mode == 'hard':
        games[user_id]['multipliers'] = MULTIPLIERS_HARD
    else:
        await query.answer("Invalid mode selected", show_alert=True)
        return

    # Deduct the bet from the user's balance
    current_balance = get_user_balance(user_id)
    new_balance = current_balance - bet_amount
    update_user_balance(user_id, new_balance)

    games[user_id]['level_buttons'] = await create_level_buttons(user_id)
    games[user_id]['status'] = 'playing'

    # Enable buttons for the first level
    games[user_id]['level_buttons'] = enable_buttons_for_level(games[user_id]['level_buttons'], 0, user_id)

    # Display the bet amount and start the game
    await query.edit_message_text(
        f"👤 Player: {player_name}\n\n🏢 Towers mode: {mode.capitalize()}\n💸 Bet amount: *${bet_amount:,.2f}*\n🎉 Let's start the game!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(games[user_id]['level_buttons'])
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
        correct_button = random.randint(0, 2)  # Random correct button (0 to 2)
        game['correct_buttons'].append(correct_button)  # Store the correct button for each level

        for i in range(3):
            amount = bet * multipliers[level]
            row.append(InlineKeyboardButton(f"${amount:,.2f}", callback_data=f"choice_{level}_{i}_{user_id}"))

        buttons.append(row)

    return buttons


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
        # If the user chose correctly
        game['level_buttons'][level][chosen_button] = InlineKeyboardButton("✅", callback_data="disabled")
        for i in range(len(game['level_buttons'][level])):
            if i != chosen_button:
                game['level_buttons'][level][i] = InlineKeyboardButton("❌", callback_data="disabled")

        game['level'] += 1

        # Calculate the current winnings based on the level
        current_winnings = game['bet'] * game['multipliers'][game['level'] - 1]

        # If the user completed all levels
        if game['level'] >= len(game['multipliers']):
            winnings = game['bet'] * game['multipliers'][-1]
            current_balance = get_user_balance(user_id)
            new_balance = current_balance + winnings
            update_user_balance(user_id, new_balance)

            await send_reply(
                update,
                context,
                text=f"👤 Player: {player_name}\n\n🎉 Congratulations! You've completed all levels!\n💸 You won: *${winnings:,.2f}*"
            )
            game['status'] = 'completed'
        else:
            # Enable the buttons for the next level
            game['level_buttons'] = enable_buttons_for_level(game['level_buttons'], game['level'], user_id)

        # Add the cashout button after the first correct answer
        if game['level'] == 1:  # Add the cashout button after the first correct answer
            game['level_buttons'].append(
                [InlineKeyboardButton(f"💰 Cashout (${current_winnings:,.2f})", callback_data=f"cashout_{user_id}")]
            )

    else:
        # If the user chose incorrectly
        game['level_buttons'][level][chosen_button] = InlineKeyboardButton("Your choice ❌", callback_data="disabled")
        game['level_buttons'][level][correct_button] = InlineKeyboardButton("Correct Choice ✅", callback_data="disabled")
        game['status'] = 'ended'

        # Send a message with "Try Again" button
        await send_reply(
            update,
            context,
            text=f"👤 Player: {player_name}\n❌ YOU LOST ❌\n\nYour new balance: *${get_user_balance(user_id):,.2f}*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again❓", callback_data=f"try_again_{user_id}")]])
        )

        # Disable all buttons after the game ends (disable interaction on the original buttons)
        game['level_buttons'] = disable_all_buttons(game['level_buttons'])

    # Edit the message with updated buttons (showing correct and incorrect choices)
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(game['level_buttons']))






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
        if bet > user_balances[user_id]:
            await send_reply(update, context, f"👤 Player: {player_name}\n\n❌ Insufficient balance ❌\nYour current balance: *${user_balances[user_id]:,.2f}*")
            return
        elif bet <= 0:
            await send_reply(update, context, "Please enter a valid bet amount greater than 0.")
            return

        # Proceed with bet processing after receiving the custom bet
        await process_bet(update, context, bet, user_id)

    except ValueError:
        # Only send the error message if the bot is in the custom betting phase
        await send_reply(update, context, "Please enter a valid number.")



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
    app.add_handler(CallbackQueryHandler(set_difficulty, pattern='^easy_|hard_'))
    app.add_handler(CallbackQueryHandler(cancel_bet, pattern='^cancel_'))
    app.add_handler(CallbackQueryHandler(handle_choice, pattern='^choice_'))
    app.add_handler(CallbackQueryHandler(handle_cashout, pattern='^cashout_'))

    app.add_handler(CallbackQueryHandler(handle_try_again, pattern='^try_again_'))


    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
