import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
from datetime import datetime
import pytz

# ============================================
# PASTE YOUR KEYS HERE
# ============================================
DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"
ODDS_API_KEY = "YOUR_ODDS_API_KEY_HERE"
PICKS_CHANNEL_NAME = "sports-picks"  # Change if your channel name is different
POST_HOUR = 9       # 9 AM
POST_MINUTE = 0
TIMEZONE = "America/Los_Angeles"  # Pacific Time (Santa Cruz, CA)
# ============================================

SPORTS = [
    "basketball_nba",
    "americanfootball_nfl",
    "baseball_mlb",
    "icehockey_nhl",
]

SPORT_EMOJIS = {
    "basketball_nba": "🏀",
    "americanfootball_nfl": "🏈",
    "baseball_mlb": "⚾",
    "icehockey_nhl": "🏒",
}

SPORT_NAMES = {
    "basketball_nba": "NBA",
    "americanfootball_nfl": "NFL",
    "baseball_mlb": "MLB",
    "icehockey_nhl": "NHL",
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


async def fetch_odds(sport):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            return []


def get_best_pick(game):
    """Pick the team with the best (lowest absolute) moneyline odds = favorite."""
    try:
        for bookmaker in game.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    outcomes = market["outcomes"]
                    # Sort by odds (favorites have odds closer to -110 or negative)
                    sorted_outcomes = sorted(outcomes, key=lambda x: x["price"])
                    favorite = sorted_outcomes[0]
                    underdog = sorted_outcomes[-1]
                    return favorite, underdog
    except Exception:
        pass
    return None, None


def format_odds(price):
    if price > 0:
        return f"+{price}"
    return str(price)


async def build_picks_embed(sport):
    games = await fetch_odds(sport)
    emoji = SPORT_EMOJIS[sport]
    name = SPORT_NAMES[sport]

    if not games:
        return None

    embed = discord.Embed(
        title=f"{emoji} {name} Picks of the Day",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Picks based on moneyline odds | Gamble responsibly 🎯")

    count = 0
    for game in games[:5]:  # Max 5 games per sport
        home = game.get("home_team", "?")
        away = game.get("away_team", "?")
        favorite, underdog = get_best_pick(game)

        if not favorite:
            continue

        fav_odds = format_odds(favorite["price"])
        dog_odds = format_odds(underdog["price"]) if underdog else "N/A"

        embed.add_field(
            name=f"🏟️ {away} @ {home}",
            value=(
                f"✅ **Pick: {favorite['name']}** ({fav_odds})\n"
                f"📊 Underdog: {underdog['name'] if underdog else 'N/A'} ({dog_odds})"
            ),
            inline=False,
        )
        count += 1

    if count == 0:
        return None

    return embed


async def post_picks():
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=PICKS_CHANNEL_NAME)
        if not channel:
            print(f"Channel '{PICKS_CHANNEL_NAME}' not found in {guild.name}")
            continue

        await channel.send("# 🎯 Daily Sports Picks\nGood morning! Here are today's suggested picks based on odds:\n")

        any_picks = False
        for sport in SPORTS:
            embed = await build_picks_embed(sport)
            if embed:
                await channel.send(embed=embed)
                any_picks = True
                await asyncio.sleep(1)

        if not any_picks:
            await channel.send("⚠️ No games found today. Check back later!")

        await channel.send("---\n⚠️ *These picks are for entertainment only. Please gamble responsibly.*")


@tasks.loop(minutes=1)
async def daily_picks_task():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    if now.hour == POST_HOUR and now.minute == POST_MINUTE:
        print(f"Posting daily picks at {now}")
        await post_picks()


@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online and ready!")
    daily_picks_task.start()


@bot.command(name="picks")
async def manual_picks(ctx):
    """Manually trigger picks with !picks"""
    await ctx.send("🔍 Fetching today's picks...")
    await post_picks()


bot.run(DISCORD_TOKEN)
