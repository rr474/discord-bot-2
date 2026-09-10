# ============================================================
# Minecraft Bedrock ↔ Railway ↔ Discord Voice Chat
# bot.py
# ============================================================

import os
import json
import math
import asyncio
import logging
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands, ui
from discord.ext import commands
import websockets


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("DISCORD_TOKEN")

PORT = int(os.getenv("PORT", "8080"))

GUILD_ID = int(
    os.getenv(
        "GUILD_ID",
        "1499842090480435363"
    )
)

ALLOWED_USERS = [
    933529869487321161
]

SHOP_NAME = os.getenv(
    "SHOP_NAME",
    "memory shop"
)

SHOP_LINK = os.getenv(
    "SHOP_LINK",
    "https://discord.gg/bm78WmEfvs"
)

# สามารถใส่ Channel ID จริงใน Railway Variables ได้
SOS_CHANNEL_ID = int(
    os.getenv("SOS_CHANNEL_ID", "0")
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("MinecraftVoice")


# ============================================================
# FILE DATABASE
# ============================================================

DATABASE_FILE = Path("database.json")


user_database = {}

default_voice_channel_id = None
default_category_id = None

player_sessions = {}

minecraft_clients = set()

active_call_channels = {}

database_lock = asyncio.Lock()


# ============================================================
# DATABASE
# ============================================================

def load_database():
    global user_database
    global default_voice_channel_id
    global default_category_id

    if not DATABASE_FILE.exists():
        logger.info("📁 ไม่พบ database.json — สร้างฐานข้อมูลใหม่")
        return

    try:
        with open(DATABASE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        user_database = data.get("users", {})

        settings = data.get("settings", {})

        default_voice_channel_id = settings.get(
            "default_voice_channel_id"
        )

        default_category_id = settings.get(
            "default_category_id"
        )

        logger.info(
            f"📁 โหลดฐานข้อมูลสำเร็จ | ผู้ใช้ {len(user_database)} คน"
        )

    except Exception as e:
        logger.error(
            f"❌ โหลด database.json ไม่สำเร็จ: {e}"
        )


async def save_database():
    async with database_lock:
        try:
            data = {
                "users": user_database,
                "settings": {
                    "default_voice_channel_id":
                        default_voice_channel_id,

                    "default_category_id":
                        default_category_id
                }
            }

            with open(
                DATABASE_FILE,
                "w",
                encoding="utf-8"
            ) as f:
                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=4
                )

        except Exception as e:
            logger.error(
                f"❌ บันทึก database.json ไม่สำเร็จ: {e}"
            )


# โหลดทันที
load_database()


# ============================================================
# ACCESS
# ============================================================

def check_access(
    guild_id: int | None,
    user_id: int
) -> bool:

    if user_id in ALLOWED_USERS:
        return True

    if guild_id == GUILD_ID:
        return True

    return False


# ============================================================
# FIND DISCORD USER BY XBOX
# ============================================================

def find_discord_id_by_xbox(
    xbox_name: str
):
    """
    Minecraft ส่ง Xbox Gamertag มา
    แล้วค้นหา Discord ID จากข้อมูลที่ผู้ใช้ลงทะเบียนไว้
    """

    target = str(
        xbox_name
    ).strip().lower()

    if not target:
        return None

    for user_id, data in user_database.items():

        registered_xbox = str(
            data.get("xbox_name", "")
        ).strip().lower()

        if registered_xbox == target:

            try:
                return int(user_id)

            except (
                ValueError,
                TypeError
            ):
                return None

    return None


# ============================================================
# SHOP EMBEDS
# ============================================================

def create_thank_you_embed():

    embed = discord.Embed(
        title="🎉┆ ขอบคุณที่อุดหนุนสินค้า!",
        color=discord.Color.green(),
        description=(
            f"ขอบคุณสำหรับการอุดหนุนระบบ Voice Chat "
            f"จาก **{SHOP_NAME}** ❤️\n\n"
            "เซิร์ฟเวอร์ของคุณได้รับการเปิดใช้งานระบบแล้ว"
        )
    )

    embed.set_footer(
        text=f"บริการโดย {SHOP_NAME}"
    )

    return embed


def create_unauthorized_warning_embed():

    embed = discord.Embed(
        title="⚠️┆ แจ้งเตือนการใช้งานระบบ",
        color=discord.Color.gold(),
        description=(
            "บัญชีหรือเซิร์ฟเวอร์นี้ยังไม่ได้ลงทะเบียน "
            "สำหรับระบบ Voice Chat\n\n"
            f"🛒 ติดต่อ {SHOP_NAME}\n"
            f"🔗 {SHOP_LINK}"
        )
    )

    embed.set_footer(
        text="ระบบตรวจสอบสิทธิ์ Voice Chat"
    )

    return embed


# ============================================================
# REGISTRATION MODAL
# ============================================================

class RegisterModal(
    ui.Modal,
    title="📝 ลงทะเบียน Voice Chat"
):

    xbox_name = ui.TextInput(
        label="ชื่อ Xbox Gamertag",
        placeholder="ตัวอย่าง: GamerPro1234",
        required=True,
        max_length=64
    )

    ic_name = ui.TextInput(
        label="ชื่อตัวละคร IC",
        placeholder="ตัวอย่าง: John_Doe",
        required=True,
        max_length=64
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        user_id = str(
            interaction.user.id
        )

        user_database[user_id] = {
            "xbox_name": str(
                self.xbox_name.value
            ).strip(),

            "ic_name": str(
                self.ic_name.value
            ).strip()
        }

        await save_database()

        authorized = check_access(
            interaction.guild_id,
            interaction.user.id
        )

        msg = (
            "✅ **บันทึกข้อมูลสำเร็จ!**\n\n"
            f"🎮 Xbox: `{self.xbox_name.value}`\n"
            f"👤 IC: `{self.ic_name.value}`\n\n"
            "เมื่อเข้า Minecraft ระบบจะจับคู่ "
            "Xbox กับ Discord ให้อัตโนมัติ"
        )

        if authorized:

            await interaction.response.send_message(
                embed=create_thank_you_embed(),
                ephemeral=True
            )

            await interaction.followup.send(
                msg,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                embed=create_unauthorized_warning_embed(),
                ephemeral=True
            )

            await interaction.followup.send(
                msg,
                ephemeral=True
            )


# ============================================================
# REGISTRATION VIEW
# ============================================================

class RegistrationView(
    ui.View
):

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="ลงทะเบียน / แก้ไขข้อมูล",
        emoji="📝",
        style=discord.ButtonStyle.success,
        custom_id="voice_register"
    )
    async def register_button(
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
    async def status_button(
        self,
        interaction: discord.Interaction,
        button: ui.Button
    ):

        user_id = str(
            interaction.user.id
        )

        data = user_database.get(
            user_id
        )

        if not data:

            await interaction.response.send_message(
                "❌ คุณยังไม่ได้ลงทะเบียน",
                ephemeral=True
            )

            return

        xbox = data.get(
            "xbox_name",
            "-"
        )

        ic = data.get(
            "ic_name",
            "-"
        )

        authorized = check_access(
            interaction.guild_id,
            interaction.user.id
        )

        embed = discord.Embed(
            title="🔍 ข้อมูล Voice Chat",
            color=(
                discord.Color.green()
                if authorized
                else discord.Color.orange()
            )
        )

        embed.add_field(
            name="🎮 Xbox Gamertag",
            value=f"`{xbox}`",
            inline=False
        )

        embed.add_field(
            name="👤 ชื่อ IC",
            value=f"`{ic}`",
            inline=False
        )

        embed.add_field(
            name="🔐 สถานะ",
            value=(
                "🟢 พร้อมใช้งาน"
                if authorized
                else "🟠 ยังไม่ได้รับสิทธิ์"
            ),
            inline=False
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# ============================================================
# SOS VIEW
# ============================================================

class SOSAnswerView(
    ui.View
):

    def __init__(
        self,
        player_name: str
    ):

        super().__init__(
            timeout=None
        )

        self.player_name = player_name

    @ui.button(
        label="ติดต่อผู้เล่น",
        emoji="📞",
        style=discord.ButtonStyle.danger,
        custom_id="sos_answer"
    )
    async def answer_sos(
        self,
        interaction: discord.Interaction,
        button: ui.Button
    ):

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "❌ ใช้งานได้เฉพาะในเซิร์ฟเวอร์",
                ephemeral=True
            )
            return

        staff_member = interaction.user

        if not isinstance(
            staff_member,
            discord.Member
        ):

            await interaction.response.send_message(
                "❌ ไม่พบข้อมูลสมาชิก",
                ephemeral=True
            )

            return

        if (
            not staff_member.voice
            or not staff_member.voice.channel
        ):

            await interaction.response.send_message(
                "❌ กรุณาเข้าห้องเสียง Discord ก่อน",
                ephemeral=True
            )

            return

        session = player_sessions.get(
            self.player_name
        )

        if not session:

            await interaction.response.send_message(
                "❌ ไม่พบผู้เล่นในระบบ Voice Chat",
                ephemeral=True
            )

            return

        discord_id = session.get(
            "discord_id"
        )

        member = (
            guild.get_member(discord_id)
            if discord_id
            else None
        )

        if not member:

            await interaction.response.send_message(
                "❌ ไม่พบ Discord ของผู้เล่น",
                ephemeral=True
            )

            return

        try:

            await member.move_to(
                staff_member.voice.channel
            )

            await interaction.response.send_message(
                f"✅ ดึง **{self.player_name}** "
                "เข้าห้องเสียงเรียบร้อยแล้ว",
                ephemeral=True
            )

        except discord.HTTPException as e:

            await interaction.response.send_message(
                f"❌ ย้ายผู้เล่นไม่สำเร็จ: {e}",
                ephemeral=True
            )


# ============================================================
# DISCORD BOT
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.voice_states = True
intents.messages = True
intents.message_content = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    logger.info(
        "========================================"
    )

    logger.info(
        f"✅ Discord Bot Online: {bot.user}"
    )

    logger.info(
        f"🆔 Bot ID: {bot.user.id}"
    )

    logger.info(
        f"🌐 Guild ID: {GUILD_ID}"
    )

    logger.info(
        f"📡 WebSocket Port: {PORT}"
    )

    logger.info(
        "========================================"
    )

    # เพิ่ม Persistent View
    try:
        bot.add_view(
            RegistrationView()
        )

        logger.info(
            "✅ Registration Panel พร้อมใช้งาน"
        )

    except Exception as e:

        logger.error(
            f"❌ เพิ่ม RegistrationView ไม่สำเร็จ: {e}"
        )

    # Sync commands
    try:

        synced = await bot.tree.sync()

        logger.info(
            f"✅ Slash Commands Sync แล้ว: "
            f"{len(synced)} commands"
        )

    except Exception as e:

        logger.error(
            f"❌ Slash Command Sync Error: {e}"
        )


# ============================================================
# SETUP PANEL
# ============================================================

@bot.tree.command(
    name="setup-panel",
    description="สร้างแผงลงทะเบียน Voice Chat"
)
async def setup_panel(
    interaction: discord.Interaction
):

    authorized = check_access(
        interaction.guild_id,
        interaction.user.id
    )

    embed = discord.Embed(
        title="🎙️┆ VOICE CHAT SYSTEM",
        color=discord.Color.blurple(),
        description=(
            "ระบบ Voice Chat สำหรับ Minecraft Bedrock\n\n"
            "ลงทะเบียน Xbox Gamertag เพื่อเชื่อมต่อ "
            "กับ Discord Voice อัตโนมัติ"
        )
    )

    embed.add_field(
        name="📝 ขั้นตอนที่ 1",
        value=(
            "กดปุ่ม **ลงทะเบียน / แก้ไขข้อมูล**\n"
            "แล้วกรอก Xbox Gamertag และชื่อ IC"
        ),
        inline=False
    )

    embed.add_field(
        name="🔊 ขั้นตอนที่ 2",
        value=(
            "เข้า Discord Voice Lobby "
            "ที่แอดมินกำหนด"
        ),
        inline=False
    )

    embed.add_field(
        name="🎮 ขั้นตอนที่ 3",
        value=(
            "เข้า Minecraft\n"
            "ระบบจะจับคู่ Xbox ↔ Discord "
            "ให้อัตโนมัติ"
        ),
        inline=False
    )

    embed.add_field(
        name="📡 ระบบ",
        value=(
            "• Proximity Voice\n"
            "• โทรส่วนตัว\n"
            "• Mute / Unmute\n"
            "• SOS\n"
            "• Minecraft ↔ Discord"
        ),
        inline=False
    )

    embed.set_footer(
        text=f"Voice Chat System • {SHOP_NAME}"
    )

    await interaction.response.send_message(
        embed=embed,
        view=RegistrationView()
    )

    if not authorized:

        await interaction.followup.send(
            embed=create_unauthorized_warning_embed(),
            ephemeral=True
        )


# ============================================================
# SET DEFAULT VOICE
# ============================================================

@bot.tree.command(
    name="set-default-voice",
    description="กำหนด Discord Voice Lobby"
)
@app_commands.describe(
    channel="เลือกห้อง Voice Lobby"
)
async def set_default_voice(
    interaction: discord.Interaction,
    channel: discord.VoiceChannel
):

    global default_voice_channel_id
    global default_category_id

    authorized = check_access(
        interaction.guild_id,
        interaction.user.id
    )

    default_voice_channel_id = channel.id
    default_category_id = (
        channel.category_id
    )

    await save_database()

    msg = (
        f"✅ ตั้ง Voice Lobby เป็น "
        f"**{channel.name}** แล้ว"
    )

    if authorized:

        await interaction.response.send_message(
            msg,
            ephemeral=True
        )

    else:

        await interaction.response.send_message(
            embed=create_unauthorized_warning_embed(),
            content=msg,
            ephemeral=True
        )


# ============================================================
# VOICE STATUS
# ============================================================

@bot.tree.command(
    name="voice-status",
    description="ตรวจสอบสถานะ Minecraft Voice Chat"
)
async def voice_status(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="📡 Voice Chat Status",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="👥 ผู้เล่นที่เชื่อมต่อ",
        value=f"`{len(player_sessions)}` คน",
        inline=True
    )

    embed.add_field(
        name="🌐 Minecraft Connections",
        value=f"`{len(minecraft_clients)}`",
        inline=True
    )

    if default_voice_channel_id:

        channel = interaction.guild.get_channel(
            int(default_voice_channel_id)
        ) if interaction.guild else None

        embed.add_field(
            name="🔊 Lobby",
            value=(
                channel.mention
                if channel
                else "ไม่พบห้อง"
            ),
            inline=False
        )

    else:

        embed.add_field(
            name="🔊 Lobby",
            value="❌ ยังไม่ได้ตั้ง",
            inline=False
        )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# CREATE PERSONAL CHANNEL
# ============================================================

async def handle_player_join_game(
    guild_id: int,
    discord_id: int,
    xbox_name: str
):

    if not default_voice_channel_id:

        logger.warning(
            f"⚠️ ยังไม่ได้ตั้ง Voice Lobby | {xbox_name}"
        )

        return

    guild = bot.get_guild(
        guild_id
    )

    if not guild:

        logger.warning(
            f"❌ ไม่พบ Guild {guild_id}"
        )

        return

    member = guild.get_member(
        discord_id
    )

    if not member:

        logger.warning(
            f"❌ ไม่พบ Discord Member "
            f"{discord_id} สำหรับ {xbox_name}"
        )

        return

    # ถ้ามี session อยู่แล้ว
    if xbox_name in player_sessions:

        logger.info(
            f"ℹ️ {xbox_name} มี Session อยู่แล้ว"
        )

        return

    category = None

    if default_category_id:

        category = guild.get_channel(
            int(default_category_id)
        )

    try:

        personal_channel = (
            await guild.create_voice_channel(
                name=f"🔊 {xbox_name}",
                category=category
            )
        )

        player_sessions[xbox_name] = {

            "discord_id": discord_id,

            "personal_channel_id":
                personal_channel.id,

            "current_channel_id":
                personal_channel.id,

            "pos": {
                "x": 0,
                "y": 0,
                "z": 0,
                "dim": "overworld"
            },

            "in_call": False
        }

        # ถ้าอยู่ Voice อยู่แล้วให้ย้าย
        if member.voice:

            await member.move_to(
                personal_channel
            )

        logger.info(
            f"🎮 PLAYER JOIN: {xbox_name} "
            f"↔ Discord {discord_id}"
        )

    except discord.HTTPException as e:

        logger.error(
            f"❌ สร้าง Voice Channel ไม่สำเร็จ: {e}"
        )


# ============================================================
# PROXIMITY VOICE
# ============================================================

async def handle_proximity_routing(
    guild_id: int,
    player_list: list
):

    PROXIMITY_RADIUS = 15

    guild = bot.get_guild(
        guild_id
    )

    if not guild:
        return

    # --------------------------------------------------------
    # UPDATE POSITIONS
    # --------------------------------------------------------

    for p in player_list:

        xbox_name = str(
            p.get("xboxName", "")
        ).strip()

        if xbox_name not in player_sessions:
            continue

        try:

            player_sessions[xbox_name]["pos"] = {

                "x": float(p.get("x", 0)),

                "y": float(p.get("y", 0)),

                "z": float(p.get("z", 0)),

                "dim": str(
                    p.get(
                        "dim",
                        "overworld"
                    )
                )
            }

        except Exception:

            continue

    sessions = list(
        player_sessions.items()
    )

    # --------------------------------------------------------
    # PROXIMITY
    # --------------------------------------------------------

    for i in range(
        len(sessions)
    ):

        name1, data1 = sessions[i]

        # คนที่อยู่ในสายโทรศัพท์
        # ไม่ให้ Proximity ดึงออก
        if data1.get(
            "in_call",
            False
        ):
            continue

        for j in range(
            i + 1,
            len(sessions)
        ):

            name2, data2 = sessions[j]

            if data2.get(
                "in_call",
                False
            ):
                continue

            pos1 = data1["pos"]
            pos2 = data2["pos"]

            # คนละ Dimension
            if pos1["dim"] != pos2["dim"]:
                continue

            distance = math.sqrt(
                (
                    pos1["x"] -
                    pos2["x"]
                ) ** 2

                +

                (
                    pos1["y"] -
                    pos2["y"]
                ) ** 2

                +

                (
                    pos1["z"] -
                    pos2["z"]
                ) ** 2
            )

            member1 = guild.get_member(
                data1["discord_id"]
            )

            member2 = guild.get_member(
                data2["discord_id"]
            )

            if not member1 or not member2:
                continue

            if not member1.voice or not member2.voice:
                continue

            # ------------------------------------------------
            # อยู่ใกล้กัน
            # ------------------------------------------------

            if distance <= PROXIMITY_RADIUS:

                target_channel_id = (
                    data1["current_channel_id"]
                )

                current_channel_id = (
                    data2["current_channel_id"]
                )

                if (
                    target_channel_id
                    != current_channel_id
                ):

                    target_channel = (
                        guild.get_channel(
                            target_channel_id
                        )
                    )

                    if target_channel:

                        try:

                            await member2.move_to(
                                target_channel
                            )

                            data2[
                                "current_channel_id"
                            ] = target_channel.id

                            logger.debug(
                                f"🔊 {name2} → "
                                f"{name1} "
                                f"({distance:.1f} blocks)"
                            )

                        except discord.HTTPException:
                            pass

            # ------------------------------------------------
            # อยู่ไกลกัน
            # ------------------------------------------------

            else:

                personal_id = (
                    data2.get(
                        "personal_channel_id"
                    )
                )

                current_id = (
                    data2.get(
                        "current_channel_id"
                    )
                )

                if (
                    personal_id
                    and current_id
                    != personal_id
                ):

                    personal_channel = (
                        guild.get_channel(
                            personal_id
                        )
                    )

                    if personal_channel:

                        try:

                            await member2.move_to(
                                personal_channel
                            )

                            data2[
                                "current_channel_id"
                            ] = personal_channel.id

                        except discord.HTTPException:
                            pass


# ============================================================
# PRIVATE CALL
# ============================================================

async def start_private_call(
    guild,
    caller_name: str,
    target_name: str
):

    caller_data = player_sessions.get(
        caller_name
    )

    target_data = player_sessions.get(
        target_name
    )

    if not caller_data or not target_data:

        logger.warning(
            "❌ ไม่พบ Session สำหรับ Private Call"
        )

        return

    try:

        category = None

        if default_category_id:

            category = guild.get_channel(
                int(default_category_id)
            )

        call_channel = (
            await guild.create_voice_channel(
                name=(
                    f"📞 {caller_name} ↔ "
                    f"{target_name}"
                ),
                category=category
            )
        )

        call_channel_id = call_channel.id

        active_call_channels[
            call_channel_id
        ] = {
            "members": [
                caller_name,
                target_name
            ]
        }

        caller_data[
            "in_call"
        ] = True

        target_data[
            "in_call"
        ] = True

        caller_data[
            "call_channel_id"
        ] = call_channel_id

        target_data[
            "call_channel_id"
        ] = call_channel_id

        caller_member = guild.get_member(
            caller_data["discord_id"]
        )

        target_member = guild.get_member(
            target_data["discord_id"]
        )

        if caller_member:

            await caller_member.move_to(
                call_channel
            )

        if target_member:

            await target_member.move_to(
                call_channel
            )

        logger.info(
            f"📞 CALL START: "
            f"{caller_name} ↔ {target_name}"
        )

    except discord.HTTPException as e:

        logger.error(
            f"❌ สร้าง Call Channel ไม่สำเร็จ: {e}"
        )


# ============================================================
# END PRIVATE CALL
# ============================================================

async def end_private_call(
    guild,
    player_name: str
):

    data = player_sessions.get(
        player_name
    )

    if not data:
        return

    call_channel_id = data.get(
        "call_channel_id"
    )

    if not call_channel_id:
        return

    call_info = active_call_channels.get(
        call_channel_id
    )

    if not call_info:
        return

    members = list(
        call_info.get(
            "members",
            []
        )
    )

    # ย้ายทุกคนกลับ Personal Channel
    for name in members:

        session = player_sessions.get(
            name
        )

        if not session:
            continue

        session[
            "in_call"
        ] = False

        session[
            "call_channel_id"
        ] = None

        personal_id = session.get(
            "personal_channel_id"
        )

        if not personal_id:
            continue

        personal_channel = (
            guild.get_channel(
                personal_id
            )
        )

        member = guild.get_member(
            session["discord_id"]
        )

        if (
            member
            and personal_channel
        ):

            try:

                await member.move_to(
                    personal_channel
                )

                session[
                    "current_channel_id"
                ] = personal_channel.id

            except discord.HTTPException:
                pass

    # ลบห้องโทร
    channel = guild.get_channel(
        call_channel_id
    )

    if channel:

        try:

            await channel.delete()

        except discord.HTTPException:
            pass

    active_call_channels.pop(
        call_channel_id,
        None
    )

    logger.info(
        f"📞 CALL END: {player_name}"
    )


# ============================================================
# MUTE
# ============================================================

async def toggle_player_mute(
    guild,
    player_name: str,
    is_muted: bool
):

    data = player_sessions.get(
        player_name
    )

    if not data:
        return

    member = guild.get_member(
        data["discord_id"]
    )

    if not member:
        return

    try:

        await member.edit(
            mute=is_muted
        )

        logger.info(
            f"🎙️ {player_name} "
            f"Muted={is_muted}"
        )

    except discord.HTTPException as e:

        logger.error(
            f"❌ Mute Error: {e}"
        )


# ============================================================
# FIND SOS CHANNEL
# ============================================================

def find_sos_channel(
    guild,
    channel_id: int
):

    # 1. ID ที่ส่งมา
    if channel_id:

        channel = guild.get_channel(
            channel_id
        )

        if isinstance(
            channel,
            discord.TextChannel
        ):
            return channel

    # 2. ID จาก Railway Variable
    if SOS_CHANNEL_ID:

        channel = guild.get_channel(
            SOS_CHANNEL_ID
        )

        if isinstance(
            channel,
            discord.TextChannel
        ):
            return channel

    # 3. ค้นหาจากชื่อ
    possible_names = [
        "sos",
        "🚨・sos",
        "🚨-sos",
        "แจ้งเหตุ",
        "แจ้งเหตุฉุกเฉิน",
        "emergency"
    ]

    for channel in guild.text_channels:

        if channel.name.lower() in [
            name.lower()
            for name in possible_names
        ]:

            return channel

    return None


# ============================================================
# SOS
# ============================================================

async def handle_sos_alert(
    data: dict
):

    guild_id = int(
        data.get(
            "guildId",
            GUILD_ID
        )
    )

    guild = bot.get_guild(
        guild_id
    )

    if not guild:
        return

    try:

        requested_channel_id = int(
            data.get(
                "sosChannelId",
                0
            )
        )

    except (
        ValueError,
        TypeError
    ):

        requested_channel_id = 0

    channel = find_sos_channel(
        guild,
        requested_channel_id
    )

    if not channel:

        logger.error(
            "❌ ไม่พบ SOS Text Channel"
        )

        return

    player_name = data.get(
        "playerName",
        "Unknown"
    )

    ic_name = data.get(
        "icName",
        player_name
    )

    dimension = data.get(
        "dimension",
        "overworld"
    )

    location = data.get(
        "location",
        "N/A"
    )

    time_now = data.get(
        "time",
        datetime.now().strftime(
            "%H:%M:%S"
        )
    )

    embed = discord.Embed(
        title="🚨 EMERGENCY CALL",
        color=discord.Color.red(),
        timestamp=datetime.now(),
        description=(
            f"**{player_name}** "
            "ได้ส่งสัญญาณฉุกเฉินจาก Minecraft"
        )
    )

    embed.add_field(
        name="👤 ผู้แจ้ง",
        value=(
            f"{player_name}\n"
            f"IC: {ic_name}"
        ),
        inline=True
    )

    embed.add_field(
        name="🌍 โลก",
        value=dimension,
        inline=True
    )

    embed.add_field(
        name="📍 พิกัด",
        value=location,
        inline=False
    )

    embed.add_field(
        name="⏰ เวลา",
        value=time_now,
        inline=False
    )

    embed.set_footer(
        text="กดปุ่มเพื่อติดต่อผู้เล่น"
    )

    await channel.send(
        embed=embed,
        view=SOSAnswerView(
            player_name
        )
    )

    logger.info(
        f"🚨 SOS: {player_name}"
    )


# ============================================================
# HANDLE MINECRAFT MESSAGE
# ============================================================

async def handle_minecraft_message(
    websocket,
    data: dict
):

    msg_type = data.get(
        "type"
    )

    # --------------------------------------------------------
    # PLAYER JOIN
    # --------------------------------------------------------

    if msg_type == "PLAYER_JOIN":

        guild_id = int(
            data.get(
                "guildId",
                GUILD_ID
            )
        )

        xbox_name = str(
            data.get(
                "xboxName",
                ""
            )
        ).strip()

        if not xbox_name:

            logger.warning(
                "⚠️ PLAYER_JOIN ไม่มี Xbox Name"
            )

            return

        # สำคัญ:
        # ไม่ใช้ discordId จาก Minecraft
        discord_id = find_discord_id_by_xbox(
            xbox_name
        )

        if discord_id is None:

            logger.warning(
                f"⚠️ ไม่พบ Discord "
                f"ที่ลงทะเบียน Xbox: {xbox_name}"
            )

            await send_to_minecraft(
                websocket,
                {
                    "type": "PLAYER_JOIN_RESULT",
                    "success": False,
                    "xboxName": xbox_name,
                    "message": (
                        "ไม่พบ Xbox Gamertag "
                        "ในระบบ Discord"
                    )
                }
            )

            return

        await handle_player_join_game(
            guild_id,
            discord_id,
            xbox_name
        )

        await send_to_minecraft(
            websocket,
            {
                "type": "PLAYER_JOIN_RESULT",
                "success": True,
                "xboxName": xbox_name,
                "message": (
                    "เชื่อมต่อ Discord สำเร็จ"
                )
            }
        )

        return

    # --------------------------------------------------------
    # POSITIONS
    # --------------------------------------------------------

    if msg_type == "POSITIONS_UPDATE":

        guild_id = int(
            data.get(
                "guildId",
                GUILD_ID
            )
        )

        players = data.get(
            "players",
            []
        )

        if isinstance(
            players,
            list
        ):

            await handle_proximity_routing(
                guild_id,
                players
            )

        return

    # --------------------------------------------------------
    # PRIVATE CALL
    # --------------------------------------------------------

    if msg_type == "START_PRIVATE_CALL":

        guild_id = int(
            data.get(
                "guildId",
                GUILD_ID
            )
        )

        guild = bot.get_guild(
            guild_id
        )

        if not guild:
            return

        caller = str(
            data.get(
                "caller",
                ""
            )
        ).strip()

        target = str(
            data.get(
                "target",
                ""
            )
        ).strip()

        if caller and target:

            await start_private_call(
                guild,
                caller,
                target
            )

        return

    # --------------------------------------------------------
    # END CALL
    # --------------------------------------------------------

    if msg_type == "END_CALL":

        guild_id = int(
            data.get(
                "guildId",
                GUILD_ID
            )
        )

        guild = bot.get_guild(
            guild_id
        )

        if not guild:
            return

        player_name = str(
            data.get(
                "player",
                ""
            )
        ).strip()

        if player_name:

            await end_private_call(
                guild,
                player_name
            )

        return

    # --------------------------------------------------------
    # MUTE
    # --------------------------------------------------------

    if msg_type == "MUTE_TOGGLE":

        guild_id = int(
            data.get(
                "guildId",
                GUILD_ID
            )
        )

        guild = bot.get_guild(
            guild_id
        )

        if not guild:
            return

        player_name = str(
            data.get(
                "player",
                ""
            )
        ).strip()

        is_muted = bool(
            data.get(
                "isMuted",
                False
            )
        )

        await toggle_player_mute(
            guild,
            player_name,
            is_muted
        )

        return

    # --------------------------------------------------------
    # SOS
    # --------------------------------------------------------

    if msg_type == "SOS_EMERGENCY":

        await handle_sos_alert(
            data
        )

        return


# ============================================================
# SEND TO MINECRAFT
# ============================================================

async def send_to_minecraft(
    websocket,
    data: dict
):

    try:

        await websocket.send(
            json.dumps(
                data,
                ensure_ascii=False
            )
        )

    except Exception as e:

        logger.error(
            f"❌ ส่งข้อมูลกลับ Minecraft ไม่สำเร็จ: {e}"
        )


# ============================================================
# WEBSOCKET HANDLER
# ============================================================

async def ws_handler(
    websocket
):

    minecraft_clients.add(
        websocket
    )

    remote = getattr(
        websocket,
        "remote_address",
        None
    )

    logger.info(
        f"🌐 Minecraft Connected: {remote}"
    )

    try:

        await send_to_minecraft(
            websocket,
            {
                "type": "WS_CONNECTED",
                "success": True,
                "message": (
                    "Minecraft ↔ Railway ↔ Discord "
                    "เชื่อมต่อแล้ว"
                )
            }
        )

        async for message in websocket:

            try:

                if isinstance(
                    message,
                    bytes
                ):

                    message = message.decode(
                        "utf-8"
                    )

                data = json.loads(
                    message
                )

                if not isinstance(
                    data,
                    dict
                ):

                    continue

                await handle_minecraft_message(
                    websocket,
                    data
                )

            except json.JSONDecodeError:

                logger.error(
                    "❌ Minecraft ส่ง JSON ไม่ถูกต้อง"
                )

            except Exception as e:

                logger.error(
                    f"❌ WebSocket Message Error: {e}"
                )

    except websockets.exceptions.ConnectionClosed:

        logger.info(
            f"🔌 Minecraft Disconnected: {remote}"
        )

    except Exception as e:

        logger.error(
            f"❌ WebSocket Error: {e}"
        )

    finally:

        minecraft_clients.discard(
            websocket
        )

        logger.info(
            f"🔌 Minecraft Connection Removed: {remote}"
        )


# ============================================================
# WEBSOCKET SERVER
# ============================================================

async def start_websocket():

    logger.info(
        f"📡 เปิด WebSocket Server "
        f"0.0.0.0:{PORT}"
    )

    async with websockets.serve(
        ws_handler,
        "0.0.0.0",
        PORT,
        ping_interval=20,
        ping_timeout=20
    ):

        logger.info(
            "✅ WebSocket Server พร้อมรับ Minecraft"
        )

        await asyncio.Future()


# ============================================================
# MAIN
# ============================================================

async def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "❌ ไม่พบ BOT_TOKEN ใน Railway Variables"
        )

    logger.info(
        "🚀 Starting Minecraft Voice System..."
    )

    await asyncio.gather(
        bot.start(BOT_TOKEN),
        start_websocket()
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "🛑 Bot stopped"
        )

    except Exception as e:

        logger.error(
            f"💥 Fatal Error: {e}"
      )
