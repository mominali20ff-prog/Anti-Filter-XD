import discord
from discord.ext import commands
import asyncio
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict

# ─── Config ───────────────────────────────────────────────────────────────────
TOKEN     = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
PREFIX    = "."
DATA_FILE = "antinuke_data.json"

NUKE_THRESHOLD = 2   # channels deleted to trigger
NUKE_WINDOW    = 5   # seconds window

# ─── Swear word list ──────────────────────────────────────────────────────────
SWEAR_WORDS = [
    "fuck", "shit", "bitch", "bastard", "crap", "piss", "cock",
    "dick", "pussy", "asshole", "motherfucker", "nigger", "nigga",
    "faggot", "retard", "whore", "slut", "cunt", "wanker", "bollocks"
]

# ─── Bot Setup ────────────────────────────────────────────────────────────────
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ─── In-memory state ──────────────────────────────────────────────────────────
guild_settings = {}
deletion_tracker      = defaultdict(list)   # guild_id → [timestamps]
deleted_channels_cache = defaultdict(list)  # guild_id → [channel dicts]
nuke_processing       = set()              # guild_ids currently being handled


# ─── Persistence ──────────────────────────────────────────────────────────────
def load_data():
    global guild_settings
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            raw = json.load(f)
        guild_settings = {int(k): v for k, v in raw.items()}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(guild_settings, f, indent=2)

def get_settings(guild_id: int) -> dict:
    if guild_id not in guild_settings:
        guild_settings[guild_id] = {
            "enabled":     False,
            "whitelist":   [],
            "log_channel": None
        }
    # migrate old records that lack log_channel
    s = guild_settings[guild_id]
    if "log_channel" not in s:
        s["log_channel"] = None
    return s


# ─── Helpers ──────────────────────────────────────────────────────────────────
def is_whitelisted(guild_id: int, user_id: int) -> bool:
    return user_id in get_settings(guild_id).get("whitelist", [])

async def safe_dm(user, embed: discord.Embed):
    try:
        await user.send(embed=embed)
    except Exception:
        pass

async def send_log(guild: discord.Guild, embed: discord.Embed):
    """Send embed to configured log channel AND DM the server owner."""
    settings = get_settings(guild.id)

    # Log channel
    log_ch_id = settings.get("log_channel")
    if log_ch_id:
        log_ch = guild.get_channel(log_ch_id)
        if log_ch:
            try:
                await log_ch.send(embed=embed)
            except Exception:
                pass

    # Always DM the server owner
    try:
        owner = await bot.fetch_user(guild.owner_id)
        if owner:
            owner_embed = embed.copy()
            owner_embed.set_footer(text=f"Server: {guild.name} ({guild.id})")
            await owner.send(embed=owner_embed)
    except Exception:
        pass

async def restore_channels(guild: discord.Guild, channels_data: list):
    for ch in channels_data:
        try:
            category = None
            if ch.get("category_id"):
                category = guild.get_channel(ch["category_id"])
            if ch["type"] == "text":
                await guild.create_text_channel(
                    name=ch["name"],
                    category=category,
                    position=ch.get("position", 0),
                    topic=ch.get("topic") or "",
                )
            elif ch["type"] == "voice":
                await guild.create_voice_channel(
                    name=ch["name"],
                    category=category,
                    position=ch.get("position", 0),
                )
        except Exception as e:
            print(f"[Restore Error] {e}")


# ─── Events ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    load_data()
    print(f"✅  Logged in as {bot.user} ({bot.user.id})")
    print("─" * 40)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    guild = channel.guild
    settings = get_settings(guild.id)
    if not settings["enabled"]:
        return
    if guild.id in nuke_processing:
        return

    # Cache deleted channel info
    ch_data = {
        "name":        channel.name,
        "type":        "text"  if isinstance(channel, discord.TextChannel)  else
                       "voice" if isinstance(channel, discord.VoiceChannel) else "other",
        "category_id": channel.category_id,
        "position":    channel.position,
        "topic":       getattr(channel, "topic", None),
    }
    deleted_channels_cache[guild.id].append(ch_data)

    now = datetime.utcnow()
    deletion_tracker[guild.id].append(now)
    window_start = now - timedelta(seconds=NUKE_WINDOW)
    deletion_tracker[guild.id] = [t for t in deletion_tracker[guild.id] if t >= window_start]

    if len(deletion_tracker[guild.id]) <= NUKE_THRESHOLD:
        return

    # ── NUKE DETECTED ────────────────────────────────────────────────────────
    nuke_processing.add(guild.id)
    await asyncio.sleep(0.8)   # let audit log populate

    try:
        actor = None
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
            candidate = entry.user
            if candidate is None or candidate.bot:
                continue
            if candidate.id == guild.owner_id:
                continue
            if is_whitelisted(guild.id, candidate.id):
                continue
            actor = candidate
            break

        if actor is None:
            nuke_processing.discard(guild.id)
            return

        print(f"[AntiNuke] Triggered! Actor: {actor} in {guild.name}")

        deletion_tracker[guild.id].clear()
        to_restore = list(deleted_channels_cache[guild.id])
        deleted_channels_cache[guild.id].clear()

        # DM the bad actor
        await safe_dm(actor, discord.Embed(
            title="🚨 You have been banned",
            description=(
                f"You were **banned** from **{guild.name}** for mass-deleting channels.\n"
                f"This was detected by the AntiNuke system."
            ),
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        ))

        # Ban
        try:
            await guild.ban(actor, reason="[AntiNuke] Mass channel deletion.", delete_message_days=0)
        except Exception as e:
            print(f"[AntiNuke] Ban failed: {e}")

        # Restore
        await restore_channels(guild, to_restore)

        # Build log embed → send to log channel + DM owner
        log_embed = discord.Embed(
            title="🛡️ AntiNuke — Mass Deletion Detected",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        log_embed.add_field(name="🔨 Action",   value="User Banned + Channels Restored", inline=False)
        log_embed.add_field(name="👤 Actor",    value=f"{actor.mention} (`{actor.id}`)",  inline=True)
        log_embed.add_field(name="🏠 Server",   value=guild.name,                         inline=True)
        log_embed.add_field(
            name="📋 Restored Channels",
            value=", ".join(f"#{c['name']}" for c in to_restore) or "None",
            inline=False
        )
        await send_log(guild, log_embed)

    except Exception as e:
        print(f"[AntiNuke] Error: {e}")
    finally:
        nuke_processing.discard(guild.id)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    settings = get_settings(message.guild.id)
    if not settings["enabled"]:
        await bot.process_commands(message)
        return

    member = message.author if isinstance(message.author, discord.Member) \
             else message.guild.get_member(message.author.id)
    if member is None:
        await bot.process_commands(message)
        return

    # Skip server owner and whitelisted users
    if member.id == message.guild.owner_id or is_whitelisted(message.guild.id, member.id):
        await bot.process_commands(message)
        return

    # ── Anti-mention ──────────────────────────────────────────────────────────
    triggered_mention = message.mention_everyone or bool(message.role_mentions)
    if triggered_mention:
        try:
            await message.delete()
        except Exception:
            pass

        warn_embed = discord.Embed(
            title="⚠️ Warning — Unauthorized Mention",
            description=(
                f"You pinged **@everyone**, **@here**, or a role in **{message.guild.name}** "
                f"without permission.\n\nYou have been **timed out for 10 minutes**."
            ),
            color=discord.Color.yellow(),
            timestamp=datetime.utcnow()
        )
        await safe_dm(member, warn_embed)

        try:
            await member.timeout(timedelta(minutes=10), reason="[AntiMod] Unauthorized mention.")
        except Exception as e:
            print(f"[AntiMod] Timeout failed: {e}")

        log_embed = discord.Embed(
            title="⚠️ AntiMod — Unauthorized Mention",
            color=discord.Color.yellow(),
            timestamp=datetime.utcnow()
        )
        log_embed.add_field(name="🔨 Action",  value="Message Deleted + 10min Timeout", inline=False)
        log_embed.add_field(name="👤 User",    value=f"{member.mention} (`{member.id}`)", inline=True)
        log_embed.add_field(name="📝 Content", value=f"```{message.content[:300]}```",   inline=False)
        log_embed.add_field(name="📍 Channel", value=message.channel.mention,            inline=True)
        await send_log(message.guild, log_embed)
        return

    # ── Swear word filter ─────────────────────────────────────────────────────
    lower = message.content.lower()
    if any(sw in lower for sw in SWEAR_WORDS):
        try:
            await message.delete()
        except Exception:
            pass

        sw_embed = discord.Embed(
            title="🤬 Language Warning",
            description=(
                f"Your message in **{message.guild.name}** was removed for "
                f"containing inappropriate language. Please keep it respectful!"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        await safe_dm(member, sw_embed)

        log_embed = discord.Embed(
            title="🤬 Swear Filter — Message Removed",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        log_embed.add_field(name="🔨 Action",  value="Message Deleted + DM Warning", inline=False)
        log_embed.add_field(name="👤 User",    value=f"{member.mention} (`{member.id}`)", inline=True)
        log_embed.add_field(name="📝 Content", value=f"```{message.content[:300]}```",   inline=False)
        log_embed.add_field(name="📍 Channel", value=message.channel.mention,            inline=True)
        await send_log(message.guild, log_embed)
        return

    await bot.process_commands(message)


# ─── Commands ─────────────────────────────────────────────────────────────────

# .antinuke (status)
@bot.group(name="antinuke", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def antinuke(ctx):
    settings = get_settings(ctx.guild.id)
    status   = "✅ Enabled" if settings["enabled"] else "❌ Disabled"
    wl       = settings["whitelist"]
    wl_str   = ", ".join(f"<@{uid}>" for uid in wl) or "None"
    log_ch   = f"<#{settings['log_channel']}>" if settings.get("log_channel") else "Not set"

    embed = discord.Embed(title="🛡️ AntiNuke Status", color=discord.Color.blurple(), timestamp=datetime.utcnow())
    embed.add_field(name="Status",       value=status,  inline=True)
    embed.add_field(name="Log Channel",  value=log_ch,  inline=True)
    embed.add_field(name="Trigger",      value=f">{NUKE_THRESHOLD} deletions in {NUKE_WINDOW}s", inline=True)
    embed.add_field(name="Whitelist",    value=wl_str,  inline=False)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)


# .antinuke enable
@antinuke.command(name="enable")
@commands.has_permissions(administrator=True)
async def antinuke_enable(ctx):
    s = get_settings(ctx.guild.id)
    s["enabled"] = True
    save_data()
    embed = discord.Embed(
        title="✅ AntiNuke Enabled",
        description=(
            "All protections are now **active**.\n\n"
            "🔴 **AntiNuke** — Mass channel deletion → Ban + restore\n"
            "🟡 **AntiMod** — @everyone / @here / role pings → Delete + DM + 10min timeout\n"
            "🟠 **Swear Filter** — Profanity → Delete + DM warning\n\n"
            "All actions are logged to the owner's DMs and your log channel."
        ),
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)


# .antinuke disable
@antinuke.command(name="disable")
@commands.has_permissions(administrator=True)
async def antinuke_disable(ctx):
    s = get_settings(ctx.guild.id)
    s["enabled"] = False
    save_data()
    embed = discord.Embed(
        title="❌ AntiNuke Disabled",
        description="All protections have been **deactivated**.",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)


# .antinuke setlog #channel
@antinuke.command(name="setlog")
@commands.has_permissions(administrator=True)
async def antinuke_setlog(ctx, channel: discord.TextChannel):
    s = get_settings(ctx.guild.id)
    s["log_channel"] = channel.id
    save_data()
    embed = discord.Embed(
        title="📋 Log Channel Set",
        description=(
            f"All AntiNuke/AntiMod/Swear filter logs will be sent to {channel.mention}.\n"
            f"The server owner will also receive every log via DM."
        ),
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)


# .antinuke whitelist
@antinuke.group(name="whitelist", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def antinuke_whitelist(ctx):
    s  = get_settings(ctx.guild.id)
    wl = s["whitelist"]
    wl_str = "\n".join(f"• <@{uid}> (`{uid}`)" for uid in wl) or "No users whitelisted."
    embed = discord.Embed(title="📋 Whitelist", description=wl_str, color=discord.Color.blurple(), timestamp=datetime.utcnow())
    await ctx.send(embed=embed)


# .antinuke whitelist add @user
@antinuke_whitelist.command(name="add")
@commands.has_permissions(administrator=True)
async def whitelist_add(ctx, member: discord.Member):
    s = get_settings(ctx.guild.id)
    if member.id in s["whitelist"]:
        await ctx.send(f"⚠️ {member.mention} is already whitelisted.")
        return
    s["whitelist"].append(member.id)
    save_data()
    embed = discord.Embed(
        title="✅ Whitelist Updated",
        description=f"{member.mention} can now bypass all AntiNuke protections.",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)


# .antinuke whitelist remove @user
@antinuke_whitelist.command(name="remove")
@commands.has_permissions(administrator=True)
async def whitelist_remove(ctx, member: discord.Member):
    s = get_settings(ctx.guild.id)
    if member.id not in s["whitelist"]:
        await ctx.send(f"⚠️ {member.mention} is not whitelisted.")
        return
    s["whitelist"].remove(member.id)
    save_data()
    embed = discord.Embed(
        title="🗑️ Whitelist Updated",
        description=f"{member.mention} has been **removed** from the whitelist.",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)


# ─── Error handler ────────────────────────────────────────────────────────────
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need **Administrator** permission to use this command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Member not found. Please mention a valid user.")
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send("❌ Channel not found. Please mention a valid text channel.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"[Error] {error}")


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(TOKEN)
