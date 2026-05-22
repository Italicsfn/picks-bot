import os
import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
from datetime import datetime
import pytz

# ============================================
# PASTE YOUR KEYS HERE
# ============================================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
PICKS_CHANNEL_NAME = "sports-picks"
POST_HOUR = 9
POST_MINUTE = 0
TIMEZONE = "America/Los_Angeles"
# ============================================

SPORTS = [
    "basketball_nba",
    "americanfootball_nfl",
    "baseball_mlb",
    "icehockey_nhl",
]

PROP_SPORTS = {
    "basketball_nba": "basketball_nba",
    "americanfootball_nfl": "americanfootball_nfl",
    "baseball_mlb": "baseball_mlb",
    "icehockey_nhl": "icehockey_nhl",
}

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

PROP_MARKETS = {
    "basketball_nba": ["player_points", "player_rebounds", "player_assists"],
    "americanfootball_nfl": ["player_pass_tds", "player_pass_yds", "player_rush_yds", "player_reception_yds"],
    "baseball_mlb": ["batter_hits", "pitcher_strikeouts"],
    "icehockey_nhl": ["player_goals", "player_assists"],
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


async def fetch_player_props(sport, event_id, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


def get_best_pick(game):
    try:
        for bookmaker in game.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    outcomes = market["outcomes"]
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


def get_prop_label(market_key):
    labels = {
        "player_points": "Points",
        "player_rebounds": "Rebounds",
        "player_assists": "Assists",
        "player_pass_tds": "Pass TDs",
        "player_pass_yds": "Pass Yards",
        "player_rush_yds": "Rush Yards",
        "player_reception_yds": "Rec Yards",
        "batter_hits": "Hits",
        "pitcher_strikeouts": "Strikeouts",
        "player_goals": "Goals",
    }
    return labels.get(market_key, market_key)


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
    for game in games[:5]:
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


async def build_props_embed(sport):
    games = await fetch_odds(sport)
    emoji = SPORT_EMOJIS[sport]
    name = SPORT_NAMES[sport]
    markets = PROP_MARKETS.get(sport, [])

    if not games or not markets:
        return None

    embed = discord.Embed(
        title=f"{emoji} {name} Player Props of the Day",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Player props | Gamble responsibly 🎯")

    count = 0
    for game in games[:2]:  # Only first 2 games to save API calls
        event_id = game.get("id")
        home = game.get("home_team", "?")
        away = game.get("away_team", "?")

        if not event_id:
            continue

        props_data = await fetch_player_props(sport, event_id, markets)
        if not props_data:
            continue

        prop_lines = []
        for bookmaker in props_data.get("bookmakers", [])[:1]:
            for market in bookmaker.get("markets", [])[:3]:
                label = get_prop_label(market["key"])
                for outcome in market.get("outcomes", [])[:2]:
                    player = outcome.get("description", outcome.get("name", "?"))
                    point = outcome.get("point", "")
                    price = format_odds(outcome["price"])
                    side = outcome["name"]
                    prop_lines.append(f"**{player}** {label} {side} {point} ({price})")

        if prop_lines:
            embed.add_field(
                name=f"🏟️ {away} @ {home}",
                value="\n".join(prop_lines[:6]),
                inline=False,
            )
            count += 1
            await asyncio.sleep(0.5)

    if count == 0:
        return None

    return embed


async def post_picks():
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=PICKS_CHANNEL_NAME)
        if not channel:
            continue

        await channel.send("# 🎯 Daily Sports Picks\nGood morning! Here are today's suggested picks based on odds:\n")

        for sport in SPORTS:
            embed = await build_picks_embed(sport)
            if embed:
                await channel.send(embed=embed)
                await asyncio.sleep(1)

        await channel.send("---\n⚠️ *These picks are for entertainment only. Please gamble responsibly.*")


async def post_props():
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=PICKS_CHANNEL_NAME)
        if not channel:
            continue

        await channel.send("# 🎰 Daily Player Props\nHere are today's player prop suggestions:\n")

        for sport in SPORTS:
            embed = await build_props_embed(sport)
            if embed:
                await channel.send(embed=embed)
                await asyncio.sleep(1)

        await channel.send("---\n⚠️ *Props are for entertainment only. Please gamble responsibly.*")


@tasks.loop(minutes=1)
async def daily_picks_task():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    if now.hour == POST_HOUR and now.minute == POST_MINUTE:
        await post_picks()
        await asyncio.sleep(60)
        await post_props()


@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online and ready!")
    daily_picks_task.start()


@bot.command(name="picks")
async def manual_picks(ctx):
    await ctx.send("🔍 Fetching today's picks...")
    await post_picks()


@bot.command(name="props")
async def manual_props(ctx):
    await ctx.send("🔍 Fetching today's player props...")
    await post_props()


bot.run(DISCORD_TOKEN)
