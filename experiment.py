import random
import sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import Forbidden
import logging

MULTIPLIERS_EASY = [1.2, 1.52, 2.07, 2.5, 3.0]
MULTIPLIERS_HARD = [1.2, 1.52, 2.07, 2.5, 3.5, 4.0, 5.0]

ALLOWED_USER_IDS = [6752577843, 7040537198]
OWNER_USER_ID = [6752577843, 7040537198]
INITIAL_BALANCE = 5000.0

games = {}
user_balances = {}
user_stats = {}
user_preferences = {}

DATABASE = 'bot_data.db'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    
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

def update_user_balance(user_id, balance):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_balances SET balance = ? WHERE user_id = ?', (balance, user_id))
    conn.commit()
    conn.close()


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


def update_user_stats(user_id, total_bet, total_winnings):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_stats SET total_bet = ?, total_winnings = ? WHERE user_id = ?',
                   (total_bet, total_winnings, user_id))
    conn.commit()
    conn.close()

def get_chat_id(update: Update, user_id):
    """Return the correct chat_id (either group chat or DM) based on user preference."""
    if user_preferences.get(user_id) == "dm":
        return user_id  
    elif update.message:
        return update.message.chat_id  
    elif update.callback_query:
        return update.callback_query.message.chat_id  

async def start(update: Update, context):
    """Show game options (Play Game, Show Stats, Check Balance)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    if user_id not in games:
        games[user_id] = {'user_id': user_id}
        
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

async def handle_start_options(update: Update, context):
    """Handle the button options for playing a game, showing stats, or checking balance."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if user_id not in games or games[user_id]['user_id'] != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    if data == "show_stats":
        await user_stats_command(update, context)  
    elif data == "start_game":
        await ask_play_location(update, context)
    elif data == "check_balance":
        await check_balance(update, context)  

    await query.answer()  

async def ask_play_location(update: Update, context):
    """Ask the user where they want to play (DM or group chat)."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    keyboard = [
        [InlineKeyboardButton("Play in DM", callback_data="play_dm"),
        InlineKeyboardButton("Play here", callback_data="play_group_chat")]
    ]

    await send_reply(
        update, context,
        text=f"{player_name}, Do you want to play in DMs or in the group chat?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_play_location_choice(update: Update, context):
    """Handle the user's choice of where to play the game (DM or group chat)."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if user_id not in games or games[user_id]['user_id'] != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return
    
    if data == "play_dm":
        user_preferences[user_id] = "dm"
        await query.answer("You chose to play in DM.")
        
        
        try:
            await context.bot.send_message(
                chat_id=user_id,  
                text="Let's start the game in your DM! Use /tower to begin."
            )
        except Forbidden:
            await query.edit_message_text(
                "It seems I cannot message you directly. Please start a conversation with me in DM first."
            )
        return
    
    elif data == "play_group_chat":
        user_preferences[user_id] = "group"
        await query.answer("You chose to play in the group chat.")
        await tower(update, context)  

    await query.answer()


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

async def tower(update: Update, context):
    """Start the Tower game and prompt for bet amount."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    if user_id not in games:
        games[user_id] = {'bet': 0, 'level': 0, 'mode': None, 'correct_buttons': [], 'status': 'placing_bet', 'user_id': user_id}


    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    
    current_balance = get_user_balance(user_id)
    quarter_balance = current_balance / 4
    half_balance = current_balance / 2

    
    if user_id not in games:
        games[user_id] = {'bet': 0, 'level': 0, 'mode': None, 'correct_buttons': [], 'status': 'placing_bet'}

    
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


async def user_stats_command(update: Update, context):
    """Command to show user stats."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    
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

async def handle_bet_option(update: Update, context):
    """Handle predefined bet options or custom bet."""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data.split('_')

    # Ensure the user is initialized in the games dictionary
    if user_id not in games:
        games[user_id] = {
            'bet': 0,
            'level': 0,
            'mode': None,
            'correct_buttons': [],
            'status': 'placing_bet',
            'last_bet': 0,
            'user_id': user_id  # Properly initialize with 'user_id'
        }

    # Make sure the current user is interacting with their own game
    if games[user_id]['user_id'] != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    game = games[user_id]  # Now, 'user_id' is guaranteed to exist in the dictionary

    # Process the bet options (1/4, 1/2, custom, etc.)
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    current_balance = get_user_balance(user_id)
    last_bet = current_balance if game['last_bet'] == 0 else game['last_bet']

    if data[1] == 'quarter':
        bet = last_bet / 4
    elif data[1] == 'half':
        bet = last_bet / 2
    elif data[1] == 'double':
        bet = last_bet * 2
    elif data[1] == 'custom':
        game['status'] = 'awaiting_custom_bet'
        await send_reply(
            update,
            context,
            text="Please enter your custom bet amount:",
            reply_markup=None
        )
        return

    if bet > current_balance:
        await send_reply(
            update,
            context,
            f"👤 Player: {player_name}\n\n❌ Insufficient balance ❌\n\nYour current balance: *${current_balance:,.2f}*"
        )
        return

    await process_bet(update, context, bet, user_id)



async def process_bet(update: Update, context, bet, user_id):
    """Process the bet, check balance, and ask for difficulty selection."""
    user = update.message.from_user if update.message else update.callback_query.from_user

    
    current_balance = get_user_balance(user_id)

    logger.info(f"User {user_id} current balance before placing bet: ${current_balance:.2f}")

    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    if bet > current_balance:
        await send_reply(update, context, f"👤 Player: {player_name}\n\n❌ Insufficient balance ❌\n\nYour current balance is: *${current_balance:,.2f}*")
        return

    
    new_balance = current_balance - bet
    update_user_balance(user_id, new_balance)  
    
    logger.info(f"User {user_id} placing bet of ${bet:.2f}, new balance after bet: ${new_balance:.2f}")

    
    total_bet, total_winnings = get_user_stats(user_id)

    
    total_bet += bet
    update_user_stats(user_id, total_bet, total_winnings)

    
    games[user_id]['bet'] = bet
    games[user_id]['last_bet'] = bet  
    games[user_id]['level'] = 0
    games[user_id]['mode'] = None
    games[user_id]['correct_buttons'] = []
    games[user_id]['status'] = 'placing_bet'

    logger.info(f"Game initialized for user {user_id} with bet: ${bet:.2f}")

    
    keyboard = [
        [InlineKeyboardButton("Easy (5 levels)", callback_data=f'easy_{user_id}'),
         InlineKeyboardButton("Hard (8 levels)", callback_data=f'hard_{user_id}')],
        [InlineKeyboardButton("Cancel Bet", callback_data=f'cancel_{user_id}')]
    ]

    await send_reply(
        update,
        context,
        f"👤 Player: {player_name}\n\n💸 You bet: ${bet:,.2f}\n🔐 Choose difficulty level or cancel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_cashout(update: Update, context):
    """Handle the cashout button press and end the game."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    game = games.get(user_id)

    if user_id not in games or games[user_id]['user_id'] != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return
    
    if not game or game['status'] != 'playing':
        await query.answer("The game has already ended.")
        return

    level = game['level']
    bet = game['bet']

    
    player_name = f"@{user.username}" if user.username else user.full_name

    
    if level == 0:
        total_winnings = bet 
    else:
        total_winnings = bet * game['multipliers'][level - 1]  

    
    logger.info(f"User {user_id} cashing out. Winnings: ${total_winnings:.2f}, bet: ${bet:.2f}, current balance: ${get_user_balance(user_id):.2f}")

    
    current_balance = get_user_balance(user_id)
    new_balance = current_balance + total_winnings
    update_user_balance(user_id, new_balance)

    
    logger.info(f"User {user_id} new balance after cashout: ${new_balance:.2f}")

    
    total_bet, total_winnings_stat = get_user_stats(user_id)
    update_user_stats(user_id, total_bet, total_winnings - bet)

    
    await send_reply(
        update, context,
        text=f"👤 Player: {player_name}\n\n💰 You've cashed out!\n🎉 Total winnings: *${total_winnings:,.2f}*\n💸 Your new balance is *${new_balance:,.2f}*"
    )

    
    game['status'] = 'cashed_out'
    game['level_buttons'] = disable_all_buttons(game['level_buttons'])

    
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(game['level_buttons']))


async def set_difficulty(update: Update, context):
    """Set difficulty and start the game."""
    query = update.callback_query
    user = query.from_user
    user_id = user.id
    data = query.data.split('_')

    if int(data[1]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    
    if 'bet' not in games[user_id]:
        await query.answer("No active bet found. Please start a new game.", show_alert=True)
        return

    
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

   
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

    games[user_id]['level_buttons'] = await create_level_buttons(user_id)
    games[user_id]['status'] = 'playing'

    
    games[user_id]['level_buttons'] = enable_buttons_for_level(games[user_id]['level_buttons'], 0, user_id)

    
    await query.edit_message_text(
        f"👤 Player: {player_name}\n\n🏢 Towers mode: {mode.capitalize()}\n💸 Bet amount: *${bet_amount:,.2f}*\n🎉 Let's start the game!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(games[user_id]['level_buttons'])
    )

async def create_level_buttons(user_id):
    """Create initial level buttons with bet * multiplier values."""
    game = games[user_id]
    bet = game['bet']
    multipliers = game['multipliers']

    buttons = []
    for level in range(len(multipliers)):
        row = []
        correct_button = random.randint(0, 2)  
        game['correct_buttons'].append(correct_button)  

        for i in range(3):
            amount = bet * multipliers[level]
            row.append(InlineKeyboardButton(f"${amount:,.2f}", callback_data=f"choice_{level}_{i}_{user_id}"))

        buttons.append(row)

    return buttons

async def handle_choice(update: Update, context):
    """Handle the player's choice and update the game."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split('_')
    user = query.from_user

    if int(data[3]) != user_id or games[user_id]['user_id'] != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return
    
    if len(data) < 4:
        await query.answer("Invalid data received.", show_alert=True)
        return

    
    if int(data[3]) != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    game = games.get(user_id)
    if not game or game['status'] != 'playing':
        await query.edit_message_text("The game has ended or you're not in a game session.")
        return

    
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
        
        game['level_buttons'][level][chosen_button] = InlineKeyboardButton("✅", callback_data="disabled")
        for i in range(len(game['level_buttons'][level])):
            if i != chosen_button:
                game['level_buttons'][level][i] = InlineKeyboardButton("❌", callback_data="disabled")

        game['level'] += 1

        
        current_winnings = game['bet'] * game['multipliers'][game['level'] - 1]
        logger.info(f"User {user_id} chose correctly. Current winnings: ${current_winnings:.2f}")

        
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
            
            game['status'] = 'playing'
            game['level_buttons'] = enable_buttons_for_level(game['level_buttons'], game['level'], user_id)

        
        if game['level'] == 1:
            game['level_buttons'].append(
                [InlineKeyboardButton(f"💰 Cashout (${current_winnings:,.2f})", callback_data=f"cashout_{user_id}")]
            )

    else:
        
        logger.info(f"User {user_id} lost at level {level}. No further deductions. Bet: ${game['bet']:.2f}, current balance: ${get_user_balance(user_id):.2f}")
        
        game['level_buttons'][level][chosen_button] = InlineKeyboardButton("Your choice ❌", callback_data="disabled")
        game['level_buttons'][level][correct_button] = InlineKeyboardButton("Correct Choice ✅", callback_data="disabled")
        game['status'] = 'ended'

        
        await send_reply(
            update,
            context,
            text=f"👤 Player: {player_name}\n\n❌ YOU LOST ❌\n\nYour new balance: *${get_user_balance(user_id):,.2f}*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again❓", callback_data=f"try_again_{user_id}")]])
        )

        
        game['level_buttons'] = disable_all_buttons(game['level_buttons'])

    
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(game['level_buttons']))

async def handle_try_again(update: Update, context):
    """Handle the 'Try Again' button press and restart the game for the user."""
    query = update.callback_query
    user_id = query.from_user.id
    user = query.from_user
    data = query.data.split('_')

    
    if int(data[2]) != user_id or games[user_id]['user_id'] != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return

    
    game = games.get(user_id)
    if not game or 'last_bet' not in game:
        await send_reply(
            update,
            context,
            text="No previous bet found. Please start a new game."
        )
        return

    last_bet = game['last_bet']  

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

    
    await send_reply(
        update,
        context,
        text=(
            f"👤 Player: {player_name}\n\n💸 Your last bet was *${last_bet:,.2f}*.\n"
            f"💵 Choose your next bet amount or enter a custom bet."
        ),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cancel_bet(update: Update, context):
    """Cancel the bet and reset the game without modifying the user's balance."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split('_')
    user = query.from_user

    if user_id not in games or games[user_id]['user_id'] != user_id:
        await query.answer("You cannot interact with this game.", show_alert=True)
        return


    game = games.get(user_id)
    if not game or game['status'] != 'placing_bet':
        await query.answer("No active bet to cancel.", show_alert=True)
        return

    bet_amount = game.get('bet', 0)  

    
    current_balance = get_user_balance(user_id)
    new_balance = current_balance + bet_amount
    update_user_balance(user_id, new_balance)

    
    logger.info(f"User {user_id} cancelled the bet of ${bet_amount:.2f}, refunded to balance. New balance: ${new_balance:.2f}")

    
    games[user_id] = {}

    
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    await send_reply(
        update,
        context,
        text=f"👤 Player: {player_name}\n\n❌ BET CANCELED ❌\n\nYour balance has been refunded. Current balance: *${new_balance:,.2f}*"
    )

    
    await query.edit_message_reply_markup(reply_markup=None)

    
    await query.answer()



def disable_all_buttons(buttons):
    return [[InlineKeyboardButton(button.text, callback_data="disabled") for button in row] for row in buttons]


def enable_buttons_for_level(buttons, level, user_id):
    """Enable buttons for the current level and keep others unchanged."""
    for i, row in enumerate(buttons):
        for j, button in enumerate(row):
            if i == level:
                buttons[i][j] = InlineKeyboardButton(button.text, callback_data=button.callback_data)
    return buttons


async def receive_bet(update: Update, context):
    """Receive the custom bet amount if selected."""
    if update.message:
        user_id = update.message.from_user.id  
        user = update.message.from_user  
    else:
        return  

    
    if user_id not in games or games[user_id].get('status') != 'awaiting_custom_bet':
        return  

    
    if user.username:
        player_name = f"@{user.username}"
    else:
        player_name = user.full_name or user.first_name

    try:
        
        bet = float(update.message.text)

        
        if bet > get_user_balance(user_id):
            await send_reply(update, context, f"👤 Player: {player_name}\n\n❌ Insufficient balance ❌\nYour current balance: *${get_user_balance(user_id):,.2f}*")
            return
        elif bet <= 0:
            await send_reply(update, context, "Please enter a valid bet amount greater than 0.")
            return

        
        await process_bet(update, context, bet, user_id)

    except ValueError:
        # Only send the error message if the bot is in the custom betting phase
        await send_reply(update, context, "Please enter a valid number.")


async def add_balance(update: Update, context):
    """Add balance to a user's account (admin-only command)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    
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


async def reset_balances(update: Update, context):
    """Reset all user balances to the default value (admin-only command)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    
    if user_id not in ALLOWED_USER_IDS:
        await send_reply(update, context, "You are not authorized to use this command.")
        return


    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_balances SET balance = ?', (INITIAL_BALANCE,))
    conn.commit()
    conn.close()

    
    await send_reply(update, context, f"All user balances have been reset to the default: *${INITIAL_BALANCE:,.2f}*")


async def reset_stats(update: Update, context):
    """Reset all user stats to zero (admin-only command)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    
    if user_id not in ALLOWED_USER_IDS:
        await send_reply(update, context, "You are not authorized to use this command.")
        return

    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_stats SET total_bet = 0, total_winnings = 0')
    conn.commit()
    conn.close()

    
    await send_reply(update, context, "All user stats have been reset to zero.")

# Shutdown command
async def shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shutdown the bot (owner-only command)."""
    user = update.message.from_user if update.message else update.callback_query.from_user
    user_id = user.id

    
    if user_id != OWNER_USER_ID:
        await send_reply(update, context, "You are not authorized to shut down the bot.")
        return
    
    await send_reply(update, context, "Shutting down the bot. Goodbye!")

    
    await context.application.stop()

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

    print("Tower games is now online")
    app.run_polling()

if __name__ == "__main__":
    main()
