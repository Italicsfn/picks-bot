import os
import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
from datetime import datetime, timedelta
import pytz

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

# Store today's picks for results tracking
todays_picks = []

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def american_to_prob(odds):
    """Convert American odds to implied probability %"""
    if odds < 0:
        prob = (-odds) / (-odds + 100) * 100
    else:
        prob = 100 / (odds + 100) * 100
    return round(prob, 1)


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


async def fetch_odds(sport):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                return await resp.json()
            return []


async def fetch_scores(sport):
    """Fetch completed game scores"""
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/scores"
    params = {
        "apiKey": ODDS_API_KEY,
        "daysFrom": 1,
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
        game_id = game.get("id", "")
        favorite, underdog = get_best_pick(game)

        if not favorite:
            continue

        fav_odds = format_odds(favorite["price"])
        dog_odds = format_odds(underdog["price"]) if underdog else "N/A"
        fav_prob = american_to_prob(favorite["price"])
        dog_prob = american_to_prob(underdog["price"]) if underdog else 0

        # Store pick for results tracking
        todays_picks.append({
            "sport": sport,
            "game_id": game_id,
            "home": home,
            "away": away,
            "pick": favorite["name"],
            "odds": favorite["price"],
            "prob": fav_prob,
        })

        embed.add_field(
            name=f"🏟️ {away} @ {home}",
            value=(
                f"✅ **Pick: {favorite['name']}** ({fav_odds})\n"
                f"📈 Hit Probability: **{fav_prob}%**\n"
                f"📊 Underdog: {underdog['name'] if underdog else 'N/A'} ({dog_odds}) — {dog_prob}%"
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
    for game in games[:2]:
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
                    price = outcome["price"]
                    prob = american_to_prob(price)
                    side = outcome["name"]
                    prop_lines.append(
                        f"**{player}** {label} {side} {point} ({format_odds(price)}) — {prob}%"
                    )

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


async def build_results_embed(sport):
    scores = await fetch_scores(sport)
    emoji = SPORT_EMOJIS[sport]
    name = SPORT_NAMES[sport]

    if not scores:
        return None

    completed = [g for g in scores if g.get("completed")]
    if not completed:
        return None

    embed = discord.Embed(
        title=f"{emoji} {name} Yesterday's Results",
        color=discord.Color.green(),
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Pick results from yesterday's games")

    count = 0
    for game in completed[:5]:
        home = game.get("home_team", "?")
        away = game.get("away_team", "?")
        game_id = game.get("id", "")
        scores_data = game.get("scores", [])

        if not scores_data or len(scores_data) < 2:
            continue

        # Find winner
        team1 = scores_data[0]
        team2 = scores_data[1]
        try:
            score1 = float(team1.get("score", 0))
            score2 = float(team2.get("score", 0))
            winner = team1["name"] if score1 > score2 else team2["name"]
            score_str = f"{team1['name']} {int(score1)} - {int(score2)} {team2['name']}"
        except Exception:
            continue

        # Check if we had a pick on this game
        pick_info = next((p for p in todays_picks if p["game_id"] == game_id), None)

        if pick_info:
            hit = pick_info["pick"] == winner
            result_emoji = "✅ HIT" if hit else "❌ MISS"
            pick_text = f"{result_emoji} — Picked **{pick_info['pick']}** ({format_odds(pick_info['odds'])}) | {pick_info['prob']}% prob"
        else:
            pick_text = f"🏆 Winner: **{winner}**"

        embed.add_field(
            name=f"🏟️ {score_str}",
            value=pick_text,
            inline=False,
        )
        count += 1

    if count == 0:
        return None

    return embed


async def post_picks():
    todays_picks.clear()
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


@bot.command(name="results")
async def manual_results(ctx):
    """Show yesterday's results and whether picks hit"""
    await ctx.send("🔍 Fetching yesterday's results...")
    any_results = False
    for sport in SPORTS:
        embed = await build_results_embed(sport)
        if embed:
            await ctx.send(embed=embed)
            any_results = True
            await asyncio.sleep(1)
    if not any_results:
        await ctx.send("⚠️ No completed games found from yesterday yet.")


bot.run(DISCORD_TOKEN)
