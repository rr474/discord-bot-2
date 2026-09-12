# =============================================================
# Minecraft Bedrock ↔ Railway ↔ Discord Voice Chat
# bot.py
# =============================================================

import os
import json
import math
import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands, ui
from discord.ext import commands
from aiohttp import web


# =============================================================
# CONFIG
# =============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", os.getenv("DISCORD_TOKEN", ""))

PORT = int(os.getenv("PORT", "8080"))

# ใส่ Discord Server ID ได้ใน Railway
# เช่น DISCORD_GUILD_ID=1499842090480435363
ENV_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")

ALLOWED_USERS = {
    933529869487321161
}

SHOP_NAME = os.getenv("SHOP_NAME", "memory shop")
SHOP_LINK = os.getenv(
    "SHOP_LINK",
    "https://discord.gg/bm78WmEfvs"
)

DATA_FILE = Path("data.json")


# =============================================================
# LOGGING
# =============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s"
)


# =============================================================
# GLOBAL STATE
# =============================================================

default_voice_channel_id = None
default_category_id = None

sos_channel_id = None
sos_role_id = None

proximity_radius = 15

user_database = {}
xbox_to_discord = {}

player_sessions = {}

active_calls = {}

pending_mc_commands = []

last_position_signature = {}

bot_ready = False


# =============================================================
# DATA SAVE / LOAD
# =============================================================

def load_data():
    global default_voice_channel_id
    global default_category_id
    global sos_channel_id
    global sos_role_id
    global proximity_radius
    global user_database
    global xbox_to_discord

    if not DATA_FILE.exists():
        logging.info("ℹ️ ไม่พบ data.json ใช้ค่าเริ่มต้น")
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        default_voice_channel_id = data.get(
            "default_voice_channel_id"
        )

        default_category_id = data.get(
            "default_category_id"
        )

        sos_channel_id = data.get(
            "sos_channel_id"
        )

        sos_role_id = data.get(
            "sos_role_id"
        )

        proximity_radius = int(
            data.get("proximity_radius", 15)
        )

        user_database = data.get(
            "user_database", {}
        )

        xbox_to_discord = {
            k.lower(): int(v)
            for k, v in data.get(
                "xbox_to_discord", {}
            ).items()
        }

        logging.info("✅ โหลดข้อมูลจาก data.json แล้ว")

    except Exception as e:
        logging.error(
            f"❌ โหลด data.json ไม่สำเร็จ: {e}"
        )


def save_data():
    try:
        data = {
            "default_voice_channel_id":
                default_voice_channel_id,

            "default_category_id":
                default_category_id,

            "sos_channel_id":
                sos_channel_id,

            "sos_role_id":
                sos_role_id,

            "proximity_radius":
                proximity_radius,

            "user_database":
                user_database,

            "xbox_to_discord":
                xbox_to_discord
        }

        with open(
            DATA_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:
        logging.error(
            f"❌ บันทึก data.json ไม่สำเร็จ: {e}"
        )


# =============================================================
# HELPERS
# =============================================================

def check_access(user_id: int):
    return user_id in ALLOWED_USERS


def normalize_xbox(name):
    return str(name).strip().lower()


def get_guild(guild_id=None):
    if guild_id:
        guild = bot.get_guild(int(guild_id))
        if guild:
            return guild

    if ENV_GUILD_ID:
        guild = bot.get_guild(int(ENV_GUILD_ID))
        if guild:
            return guild

    if bot.guilds:
        return bot.guilds[0]

    return None


def create_unauthorized_warning_embed():

    embed = discord.Embed(
        title="⚠️┆ เตือนการใช้งานระบบ",
        color=discord.Color.gold(),
        description=(
            "บัญชีผู้ใช้นี้ **ไม่อยู่ในสิทธิ์การใช้งานระบบ**\n\n"
            f"🛒 ติดต่อสอบถาม: "
            f"[{SHOP_NAME}]({SHOP_LINK})"
        )
    )

    embed.set_footer(
        text="ระบบตรวจสอบสิทธิ์การใช้งาน"
    )

    return embed


def queue_mc_command(command):
    pending_mc_commands.append(command)


# =============================================================
# DISCORD BOT
# =============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =============================================================
# REGISTER MODAL
# =============================================================

class RegisterModal(
    ui.Modal,
    title="📝 ลงทะเบียน Voice Chat"
):

    xbox_name = ui.TextInput(
        label="ชื่อ Xbox Gamertag",
        placeholder="เช่น Rose28303",
        required=True,
        max_length=32
    )

    ic_name = ui.TextInput(
        label="ชื่อตัวละคร IC",
        placeholder="เช่น Rose",
        required=True,
        max_length=32
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        xbox = self.xbox_name.value.strip()
        ic = self.ic_name.value.strip()

        if not xbox:
            await interaction.response.send_message(
                "❌ ชื่อ Xbox ไม่ถูกต้อง",
                ephemeral=True
            )
            return

        key = normalize_xbox(xbox)

        old_data = user_database.get(
            str(interaction.user.id)
        )

        # ลบ mapping เก่า
        if old_data:
            old_xbox = old_data.get("xbox_name")

            if old_xbox:
                xbox_to_discord.pop(
                    normalize_xbox(old_xbox),
                    None
                )

        user_database[str(interaction.user.id)] = {
            "xbox_name": xbox,
            "ic_name": ic
        }

        xbox_to_discord[key] = interaction.user.id

        save_data()

        await interaction.response.send_message(
            (
                "✅ **ลงทะเบียนสำเร็จ!**\n\n"
                f"🎮 Xbox: `{xbox}`\n"
                f"👤 IC: `{ic}`\n\n"
                "เมื่อเข้า Minecraft ระบบจะเชื่อมต่อให้อัตโนมัติ"
            ),
            ephemeral=True
        )


# =============================================================
# REGISTRATION VIEW
# =============================================================

class RegistrationView(ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="ลงทะเบียน / แก้ไขข้อมูล",
        emoji="📝",
        style=discord.ButtonStyle.success,
        custom_id="voice_register"
    )
    async def register(
        self,
        interaction: discord.Interaction,
        button: ui.Button
    ):
        await interaction.response.send_modal(
            RegisterModal()
        )

    @ui.button(
        label="ตรวจสอบสถานะ",
        emoji="🔍",
        style=discord.ButtonStyle.primary,
        custom_id="voice_status"
    )
    async def status(
        self,
        interaction: discord.Interaction,
        button: ui.Button
    ):

        data = user_database.get(
            str(interaction.user.id)
        )

        if not data:
            await interaction.response.send_message(
                "❌ คุณยังไม่ได้ลงทะเบียน",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            (
                "✅ **สถานะการเชื่อมต่อ**\n\n"
                f"🎮 Xbox: `{data['xbox_name']}`\n"
                f"👤 IC: `{data['ic_name']}`"
            ),
            ephemeral=True
        )


# =============================================================
# READY
# =============================================================

@bot.event
async def on_ready():

    global bot_ready

    bot_ready = True

    load_data()

    bot.add_view(
        RegistrationView()
    )

    logging.info(
        f"✅ Bot Online: {bot.user}"
    )

    logging.info(
        f"🏠 Discord Servers: {len(bot.guilds)}"
    )

    if ENV_GUILD_ID:
        logging.info(
            f"🎯 Target Guild: {ENV_GUILD_ID}"
        )

    try:
        synced = await bot.tree.sync()

        logging.info(
            f"⚡ Sync Slash Commands: {len(synced)}"
        )

    except Exception as e:
        logging.error(
            f"❌ Slash Sync Error: {e}"
        )


# =============================================================
# VOICE STATE
# =============================================================

@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):

    xbox_name = None

    for xbox, discord_id in xbox_to_discord.items():

        if int(discord_id) == member.id:
            xbox_name = xbox
            break

    if not xbox_name:
        return

    # ---------------------------------------------------------
    # Discord Mute → Minecraft
    # ---------------------------------------------------------

    if (
        before.self_mute != after.self_mute
        or before.mute != after.mute
    ):

        muted = (
            after.self_mute
            or after.mute
        )

        queue_mc_command({
            "action": "MUTE"
            if muted else "UNMUTE",
            "target": xbox_name
        })

        logging.info(
            f"🎙️ {xbox_name} -> "
            f"{'MUTE' if muted else 'UNMUTE'}"
        )

    # ---------------------------------------------------------
    # ลบห้องที่ระบบสร้างเมื่อว่าง
    # ---------------------------------------------------------

    if (
        before.channel
        and before.channel != after.channel
    ):

        channel = before.channel

        if len(channel.members) != 0:
            return

        managed = False

        if channel.name.startswith(
            ("🔊", "📞", "👥")
        ):
            managed = True

        for session in player_sessions.values():

            if (
                session.get("personal_channel_id")
                == channel.id
            ):
                managed = True
                break

        for call in active_calls.values():

            if call.get("channel_id") == channel.id:
                managed = True
                break

        if managed:

            try:

                await channel.delete(
                    reason="Minecraft Voice system cleanup"
                )

                logging.info(
                    f"🗑️ ลบห้องเสียง: {channel.name}"
                )

            except Exception as e:

                logging.error(
                    f"❌ Delete Voice Error: {e}"
                )


# =============================================================
# SLASH COMMAND
# =============================================================

@bot.tree.command(
    name="setup-panel",
    description="สร้าง Panel เชื่อม Minecraft Voice"
)
async def setup_panel(
    interaction: discord.Interaction
):

    if not check_access(interaction.user.id):

        await interaction.response.send_message(
            embed=create_unauthorized_warning_embed(),
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="⚔️ Minecraft Proximity Voice",
        description=(
            "เชื่อมต่อ **Minecraft Bedrock ↔ Discord Voice**\n\n"
            "📝 ลงทะเบียน Xbox Gamertag\n"
            "🎙️ ระบบไมค์ในเกม\n"
            "📞 โทรเดี่ยว / โทรกลุ่ม\n"
            "📍 ย้ายห้องตามระยะผู้เล่น\n"
            "🚨 ระบบ SOS"
        ),
        color=0x2B2D31
    )

    embed.set_footer(
        text=f"{SHOP_NAME} | Minecraft Voice System"
    )

    await interaction.channel.send(
        embed=embed,
        view=RegistrationView()
    )

    await interaction.response.send_message(
        "✅ สร้าง Panel เรียบร้อย",
        ephemeral=True
    )


# =============================================================
# SET CATEGORY
# =============================================================

@bot.tree.command(
    name="set-voice-category",
    description="ตั้ง Category สำหรับห้อง Voice"
)
async def set_voice_category(
    interaction: discord.Interaction,
    category: discord.CategoryChannel
):

    if not check_access(interaction.user.id):

        await interaction.response.send_message(
            embed=create_unauthorized_warning_embed(),
            ephemeral=True
        )

        return

    global default_category_id

    default_category_id = category.id

    save_data()

    await interaction.response.send_message(
        f"✅ ตั้ง Category เป็น **{category.name}**",
        ephemeral=True
    )


# =============================================================
# SET DEFAULT VOICE
# =============================================================

@bot.tree.command(
    name="set-default-voice",
    description="ตั้งห้อง Lobby"
)
async def set_default_voice(
    interaction: discord.Interaction,
    channel: discord.VoiceChannel
):

    if not check_access(interaction.user.id):

        await interaction.response.send_message(
            embed=create_unauthorized_warning_embed(),
            ephemeral=True
        )

        return

    global default_voice_channel_id
    global default_category_id

    default_voice_channel_id = channel.id

    if channel.category_id:
        default_category_id = channel.category_id

    save_data()

    await interaction.response.send_message(
        f"✅ ตั้ง Lobby เป็น **{channel.name}**",
        ephemeral=True
    )


# =============================================================
# SET SOS
# =============================================================

@bot.tree.command(
    name="set-sos-channel",
    description="ตั้งช่อง SOS"
)
@app_commands.describe(
    channel="ช่องข้อความ SOS",
    role="Role สำหรับแจ้งเตือน"
)
async def set_sos_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    role: discord.Role = None
):

    if not check_access(interaction.user.id):

        await interaction.response.send_message(
            embed=create_unauthorized_warning_embed(),
            ephemeral=True
        )

        return

    global sos_channel_id
    global sos_role_id

    sos_channel_id = channel.id

    sos_role_id = (
        role.id
        if role
        else None
    )

    save_data()

    role_text = (
        role.mention
        if role
        else "@here"
    )

    await interaction.response.send_message(
        (
            "✅ **ตั้ง SOS สำเร็จ**\n"
            f"📢 ช่อง: {channel.mention}\n"
            f"🔔 Role: {role_text}"
        ),
        ephemeral=True
    )


# =============================================================
# SET RADIUS
# =============================================================

@bot.tree.command(
    name="set-radius",
    description="ตั้งระยะ Proximity Voice"
)
async def set_radius(
    interaction: discord.Interaction,
    radius: int
):

    if not check_access(interaction.user.id):

        await interaction.response.send_message(
            embed=create_unauthorized_warning_embed(),
            ephemeral=True
        )

        return

    global proximity_radius

    if radius < 1 or radius > 500:

        await interaction.response.send_message(
            "❌ ระยะต้องอยู่ระหว่าง 1-500 บล็อก",
            ephemeral=True
        )

        return

    proximity_radius = radius

    save_data()

    await interaction.response.send_message(
        f"✅ Proximity Radius = **{radius} บล็อก**",
        ephemeral=True
    )


# =============================================================
# CREATE PERSONAL CHANNEL
# =============================================================

async def create_personal_channel(
    guild,
    xbox_name
):

    category = None

    if default_category_id:
        category = guild.get_channel(
            default_category_id
        )

    channel = await guild.create_voice_channel(
        name=f"🔊 {xbox_name}",
        category=category,
        reason="Minecraft Voice Personal Channel"
    )

    return channel


# =============================================================
# PLAYER JOIN
# =============================================================

async def handle_player_join_game(
    guild_id,
    discord_id,
    xbox_name
):

    guild = get_guild(guild_id)

    if not guild:
        return

    member = guild.get_member(
        int(discord_id)
    )

    if not member:
        return

    key = normalize_xbox(xbox_name)

    # ---------------------------------------------------------
    # มี session อยู่แล้ว
    # ---------------------------------------------------------

    if key in player_sessions:

        session = player_sessions[key]

        personal_id = session.get(
            "personal_channel_id"
        )

        if personal_id:

            channel = guild.get_channel(
                personal_id
            )

            if channel:

                session["discord_id"] = member.id

                return

    # ---------------------------------------------------------
    # สร้างห้องส่วนตัว
    # ---------------------------------------------------------

    try:

        channel = await create_personal_channel(
            guild,
            xbox_name
        )

        player_sessions[key] = {

            "discord_id":
                member.id,

            "xbox_name":
                xbox_name,

            "personal_channel_id":
                channel.id,

            "current_channel_id":
                channel.id,

            "pos": {
                "x": 0,
                "y": 0,
                "z": 0,
                "dim": "overworld"
            }
        }

        # ย้ายเฉพาะถ้าอยู่ Voice
        if member.voice:

            await member.move_to(
                channel,
                reason="Minecraft Player Join"
            )

        logging.info(
            f"🟢 PLAYER JOIN: {xbox_name}"
        )

    except Exception as e:

        logging.error(
            f"❌ Player Join Error: {e}"
        )


# =============================================================
# PLAYER LEAVE
# =============================================================

async def handle_player_leave_game(
    guild_id,
    xbox_name
):

    guild = get_guild(guild_id)

    if not guild:
        return

    key = normalize_xbox(xbox_name)

    session = player_sessions.pop(
        key,
        None
    )

    if not session:
        return

    member = guild.get_member(
        int(session["discord_id"])
    )

    # กลับ Lobby
    if (
        member
        and default_voice_channel_id
    ):

        lobby = guild.get_channel(
            default_voice_channel_id
        )

        if lobby:

            try:

                await member.move_to(
                    lobby,
                    reason="Minecraft Player Leave"
                )

            except Exception as e:

                logging.error(
                    f"❌ Lobby Move Error: {e}"
                )

    personal_id = session.get(
        "personal_channel_id"
    )

    if personal_id:

        channel = guild.get_channel(
            personal_id
        )

        if channel:

            try:

                if len(channel.members) == 0:

                    await channel.delete(
                        reason="Minecraft Player Leave"
                    )

            except Exception as e:

                logging.error(
                    f"❌ Personal Channel Delete Error: {e}"
                )

    logging.info(
        f"🔴 PLAYER LEAVE: {xbox_name}"
    )


# =============================================================
# PROXIMITY ENGINE
# =============================================================

def distance_between(a, b):

    return math.sqrt(
        (a["x"] - b["x"]) ** 2
        + (a["y"] - b["y"]) ** 2
        + (a["z"] - b["z"]) ** 2
    )


async def move_member_to(
    member,
    channel,
    session
):

    if not member:
        return

    if not channel:
        return

    if (
        member.voice
        and member.voice.channel
        and member.voice.channel.id == channel.id
    ):
        session["current_channel_id"] = channel.id
        return

    try:

        await member.move_to(
            channel,
            reason="Minecraft Proximity Voice"
        )

        session["current_channel_id"] = channel.id

    except Exception as e:

        logging.error(
            f"❌ Move Voice Error "
            f"{member} -> {channel}: {e}"
        )


async def handle_proximity_routing(
    guild_id,
    players
):

    guild = get_guild(guild_id)

    if not guild:
        return

    online_keys = set()

    # ---------------------------------------------------------
    # Update players
    # ---------------------------------------------------------

    for player in players:

        xbox_name = player.get(
            "xboxName"
        )

        if not xbox_name:
            continue

        key = normalize_xbox(
            xbox_name
        )

        online_keys.add(key)

        discord_id = xbox_to_discord.get(
            key
        )

        if not discord_id:
            continue

        if key not in player_sessions:

            await handle_player_join_game(
                guild_id,
                discord_id,
                xbox_name
            )

        session = player_sessions.get(
            key
        )

        if not session:
            continue

        session["pos"] = {
            "x": float(player.get("x", 0)),
            "y": float(player.get("y", 0)),
            "z": float(player.get("z", 0)),
            "dim": player.get(
                "dim",
                "overworld"
            )
        }

    # ---------------------------------------------------------
    # Remove sessions not online
    # ---------------------------------------------------------

    for key in list(
        player_sessions.keys()
    ):

        if key not in online_keys:

            # ยังไม่ลบทันที
            # เพราะ request อาจตก
            pass

    # ---------------------------------------------------------
    # Build proximity groups
    # ---------------------------------------------------------

    sessions = []

    for key, session in player_sessions.items():

        pos = session.get("pos")

        if not pos:
            continue

        sessions.append(
            (
                key,
                session
            )
        )

    # ---------------------------------------------------------
    # สร้าง graph ว่าใครอยู่ใกล้ใคร
    # ---------------------------------------------------------

    groups = []

    visited = set()

    for i, (key, session) in enumerate(
        sessions
    ):

        if key in visited:
            continue

        group = []
        queue = [key]

        visited.add(key)

        while queue:

            current = queue.pop(0)

            current_session = player_sessions.get(
                current
            )

            if not current_session:
                continue

            group.append(current)

            current_pos = current_session.get(
                "pos"
            )

            if not current_pos:
                continue

            for other_key, other_session in sessions:

                if other_key in visited:
                    continue

                other_pos = other_session.get(
                    "pos"
                )

                if not other_pos:
                    continue

                if (
                    current_pos["dim"]
                    != other_pos["dim"]
                ):
                    continue

                dist = distance_between(
                    current_pos,
                    other_pos
                )

                if dist <= proximity_radius:

                    visited.add(
                        other_key
                    )

                    queue.append(
                        other_key
                    )

        groups.append(group)

    # ---------------------------------------------------------
    # Move groups
    # ---------------------------------------------------------

    for group in groups:

        if not group:
            continue

        # กลุ่ม 1 คน → ห้องส่วนตัว
        if len(group) == 1:

            key = group[0]

            session = player_sessions.get(
                key
            )

            if not session:
                continue

            channel = guild.get_channel(
                session.get(
                    "personal_channel_id"
                )
            )

            member = guild.get_member(
                int(session["discord_id"])
            )

            if channel and member:

                await move_member_to(
                    member,
                    channel,
                    session
                )

            continue

        # -----------------------------------------------------
        # กลุ่มหลายคน
        # -----------------------------------------------------

        group_channel = None

        # หา channel เดิมของคนในกลุ่ม
        for key in group:

            session = player_sessions.get(
                key
            )

            if not session:
                continue

            channel_id = session.get(
                "current_channel_id"
            )

            if not channel_id:
                continue

            channel = guild.get_channel(
                channel_id
            )

            if (
                channel
                and channel.name.startswith(
                    "👥"
                )
            ):

                group_channel = channel
                break

        # ถ้ายังไม่มี สร้างใหม่
        if not group_channel:

            category = None

            if default_category_id:

                category = guild.get_channel(
                    default_category_id
                )

            try:

                group_channel = await guild.create_voice_channel(
                    name=f"👥 Proximity ({len(group)})",
                    category=category,
                    reason="Minecraft Proximity Group"
                )

            except Exception as e:

                logging.error(
                    f"❌ Create Group Channel Error: {e}"
                )

                continue

        # ย้ายสมาชิกทุกคน
        for key in group:

            session = player_sessions.get(
                key
            )

            if not session:
                continue

            member = guild.get_member(
                int(session["discord_id"])
            )

            if member:

                await move_member_to(
                    member,
                    group_channel,
                    session
                )

        # -----------------------------------------------------
        # ตั้ง current channel
        # -----------------------------------------------------

        for key in group:

            if key in player_sessions:

                player_sessions[key][
                    "current_channel_id"
                ] = group_channel.id


# =============================================================
# CALL SYSTEM
# =============================================================

async def create_call_channel(
    guild,
    call_type,
    members_xbox
):

    if not members_xbox:
        return

    category = None

    if default_category_id:

        category = guild.get_channel(
            default_category_id
        )

    if call_type == "single":

        name = (
            f"📞 โทรเดี่ยว "
            f"{members_xbox[0]}"
        )

    else:

        name = (
            f"👥 โทรกลุ่ม "
            f"({len(members_xbox)} คน)"
        )

    try:

        channel = await guild.create_voice_channel(
            name=name,
            category=category,
            reason="Minecraft Phone Call"
        )

    except Exception as e:

        logging.error(
            f"❌ Call Channel Error: {e}"
        )

        return

    call_id = (
        f"call_{channel.id}"
    )

    active_calls[call_id] = {
        "channel_id": channel.id,
        "members": members_xbox
    }

    for xbox_name in members_xbox:

        key = normalize_xbox(
            xbox_name
        )

        discord_id = xbox_to_discord.get(
            key
        )

        if not discord_id:
            continue

        member = guild.get_member(
            int(discord_id)
        )

        if not member:
            continue

        try:

            await member.move_to(
                channel,
                reason="Minecraft Phone Call"
            )

        except Exception as e:

            logging.error(
                f"❌ Call Move Error: {e}"
            )

    return call_id


# =============================================================
# HTTP API
# =============================================================

routes = web.RouteTableDef()


@routes.get("/")
async def root(request):

    return web.json_response({
        "status": "online",
        "service": "Minecraft Discord Voice Bridge",
        "bot": str(bot.user) if bot.user else None,
        "radius": proximity_radius
    })


@routes.get("/health")
async def health(request):

    return web.json_response({
        "status": "ok",
        "bot_ready": bot_ready,
        "radius": proximity_radius
    })


@routes.post("/mc-update")
async def mc_update(request):

    global pending_mc_commands
    global proximity_radius
    global sos_channel_id
    global sos_role_id

    try:

        data = await request.json()

        msg_type = data.get(
            "type"
        )

        guild_id = data.get(
            "guildId"
        )

        if guild_id:

            try:
                guild_id = int(
                    guild_id
                )
            except:
                guild_id = None

        guild = get_guild(
            guild_id
        )

        logging.info(
            f"📡 MC → {msg_type}"
        )

        # =====================================================
        # PLAYER JOIN
        # =====================================================

        if msg_type == "PLAYER_JOIN":

            xbox_name = data.get(
                "xboxName"
            )

            if xbox_name:

                discord_id = xbox_to_discord.get(
                    normalize_xbox(
                        xbox_name
                    )
                )

                if (
                    discord_id
                    and guild
                ):

                    await handle_player_join_game(
                        guild.id,
                        discord_id,
                        xbox_name
                    )

        # =====================================================
        # PLAYER LEAVE
        # =====================================================

        elif msg_type == "PLAYER_LEAVE":

            xbox_name = data.get(
                "xboxName"
            )

            if xbox_name and guild:

                await handle_player_leave_game(
                    guild.id,
                    xbox_name
                )

        # =====================================================
        # POSITIONS
        # =====================================================

        elif msg_type == "POSITIONS_UPDATE":

            if guild:

                await handle_proximity_routing(
                    guild.id,
                    data.get(
                        "players",
                        []
                    )
                )

        # =====================================================
        # SET RADIUS
        # =====================================================

        elif msg_type == "SET_RADIUS":

            try:

                new_radius = int(
                    data.get(
                        "radius",
                        15
                    )
                )

                if 1 <= new_radius <= 500:

                    proximity_radius = new_radius

                    save_data()

                    logging.info(
                        f"📏 Radius = "
                        f"{proximity_radius}"
                    )

            except Exception as e:

                logging.error(
                    f"❌ Radius Error: {e}"
                )

        # =====================================================
        # START CALL
        # =====================================================

        elif msg_type == "START_CALL":

            if guild:

                call_type = data.get(
                    "callType",
                    "single"
                )

                targets = data.get(
                    "targets",
                    []
                )

                await create_call_channel(
                    guild,
                    call_type,
                    targets
                )

        # =====================================================
        # END CALL
        # =====================================================

        elif msg_type == "END_CALL":

            call_id = data.get(
                "callId"
            )

            call = active_calls.pop(
                call_id,
                None
            )

            if call and guild:

                channel = guild.get_channel(
                    call["channel_id"]
                )

                if channel:

                    try:

                        await channel.delete(
                            reason="Minecraft End Call"
                        )

                    except:
                        pass

        # =====================================================
        # MUTE
        # =====================================================

        elif msg_type == "TOGGLE_MUTE":

            sender = data.get(
                "sender"
            )

            is_muted = bool(
                data.get(
                    "isMuted",
                    False
                )
            )

            if sender and guild:

                discord_id = xbox_to_discord.get(
                    normalize_xbox(sender)
                )

                if discord_id:

                    member = guild.get_member(
                        int(discord_id)
                    )

                    if member:

                        try:

                            await member.edit(
                                mute=is_muted,
                                reason="Minecraft Microphone Toggle"
                            )

                        except Exception as e:

                            logging.error(
                                f"❌ Discord Mute Error: {e}"
                            )

        # =====================================================
        # SOS
        # =====================================================

        elif msg_type == "SOS_EMERGENCY":

            if sos_channel_id:

                channel = bot.get_channel(
                    int(sos_channel_id)
                )

                if channel:

                    player_name = data.get(
                        "playerName",
                        "Unknown"
                    )

                    location = data.get(
                        "location",
                        "Unknown"
                    )

                    dimension = data.get(
                        "dimension",
                        "overworld"
                    )

                    time_str = data.get(
                        "time",
                        ""
                    )

                    embed = discord.Embed(
                        title="🚨 SOS EMERGENCY",
                        description=(
                            "มีผู้เล่นส่งสัญญาณขอความช่วยเหลือจาก Minecraft"
                        ),
                        color=discord.Color.red()
                    )

                    embed.add_field(
                        name="👤 ผู้เล่น",
                        value=f"`{player_name}`",
                        inline=True
                    )

                    embed.add_field(
                        name="📍 พิกัด",
                        value=f"`{location}`",
                        inline=True
                    )

                    embed.add_field(
                        name="🌍 มิติ",
                        value=f"`{dimension}`",
                        inline=True
                    )

                    embed.set_footer(
                        text=f"เวลา: {time_str}"
                    )

                    mention = (
                        f"<@&{sos_role_id}>"
                        if sos_role_id
                        else "@here"
                    )

                    await channel.send(
                        content=(
                            f"🚨 {mention} "
                            f"**มีเหตุฉุกเฉิน!**"
                        ),
                        embed=embed
                    )

        # =====================================================
        # SEND COMMANDS BACK TO MC
        # =====================================================

        commands_to_send = list(
            pending_mc_commands
        )

        pending_mc_commands.clear()

        return web.json_response({
            "status": "ok",
            "type": msg_type,
            "radius": proximity_radius,
            "commands": commands_to_send
        })

    except Exception as e:

        logging.exception(
            "❌ API ERROR"
        )

        return web.json_response(
            {
                "status": "error",
                "message": str(e),
                "commands": []
            },
            status=400
        )


# =============================================================
# WEB SERVER
# =============================================================

async def start_web_server():

    app = web.Application()

    app.add_routes(
        routes
    )

    runner = web.AppRunner(
        app
    )

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    logging.info(
        f"🌐 HTTP Server : {PORT}"
    )


# =============================================================
# MAIN
# =============================================================

async def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "❌ ไม่พบ BOT_TOKEN ใน Environment Variables"
        )

    await start_web_server()

    async with bot:

        await bot.start(
            BOT_TOKEN
        )


if __name__ == "__main__":

    asyncio.run(
        main()
          )
