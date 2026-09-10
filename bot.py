import os
import json
import math
import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands, ui
from discord.ext import commands

import websockets


# =============================================================
# ⚙️ CONFIG
# =============================================================

CONFIG = {

    "BOT_TOKEN":
        os.getenv(
            "BOT_TOKEN",
            os.getenv(
                "DISCORD_TOKEN",
                "YOUR_BOT_TOKEN_HERE"
            )
        ),

    "PORT":
        int(
            os.getenv(
                "PORT",
                8080
            )
        ),

    "ALLOWED_GUILDS": [
        1499842090480435363
    ],

    "ALLOWED_USERS": [
        933529869487321161
    ],

    "SHOP_INFO": {

        "NAME":
            os.getenv(
                "SHOP_NAME",
                "memory shop"
            ),

        "LINK":
            os.getenv(
                "SHOP_LINK",
                "https://discord.gg/bm78WmEfvs"
            )
    }
}


# =============================================================
# 📝 LOGGING
# =============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# =============================================================
# 💾 DATABASE
# =============================================================

DATABASE_FILE = "database.json"

user_database = {}

player_sessions = {}

default_voice_channel_id = None
default_category_id = None


# =============================================================
# 💾 LOAD DATABASE
# =============================================================

def load_database():

    global user_database

    try:

        if not os.path.exists(
            DATABASE_FILE
        ):

            user_database = {}

            return

        with open(
            DATABASE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            user_database = json.load(file)

        logging.info(
            f"Loaded {len(user_database)} registered users"
        )

    except Exception as e:

        logging.error(
            f"Database Load Error: {e}"
        )

        user_database = {}


# =============================================================
# 💾 SAVE DATABASE
# =============================================================

def save_database():

    try:

        with open(
            DATABASE_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                user_database,
                file,
                ensure_ascii=False,
                indent=4
            )

    except Exception as e:

        logging.error(
            f"Database Save Error: {e}"
        )


load_database()


# =============================================================
# 🛡️ ACCESS
# =============================================================

def check_access(
    guild_id: int,
    user_id: int
):

    return (
        guild_id in CONFIG["ALLOWED_GUILDS"]
        or
        user_id in CONFIG["ALLOWED_USERS"]
    )


# =============================================================
# 🔎 FIND USER BY XBOX
# =============================================================

def find_discord_by_xbox(xbox_name: str):

    target = xbox_name.strip().lower()

    for discord_id, data in user_database.items():

        registered =
            str(
                data.get(
                    "xbox_name",
                    ""
                )
            ).strip().lower()

        if registered == target:

            try:
                return int(discord_id)

            except ValueError:
                return None

    return None


# =============================================================
# 🎨 EMBEDS
# =============================================================

def create_thank_you_embed():

    embed = discord.Embed(

        title="🎉┆ ขอบคุณที่อุดหนุนสินค้า!",

        color=discord.Color.green(),

        description=(
            f"ขอบคุณสำหรับการอุดหนุนระบบ Voice Chat "
            f"จาก **{CONFIG['SHOP_INFO']['NAME']}** ❤️\n\n"
            "ระบบพร้อมใช้งานแล้ว"
        )
    )

    return embed


def create_unauthorized_warning_embed():

    embed = discord.Embed(

        title="⚠️┆ ยังไม่ได้รับอนุญาต",

        color=discord.Color.gold(),

        description=(
            "บัญชีนี้ยังไม่ได้ลงทะเบียนลิขสิทธิ์ Voice Chat\n\n"
            f"🛒 {CONFIG['SHOP_INFO']['LINK']}"
        )
    )

    return embed


# =============================================================
# 📝 REGISTER MODAL
# =============================================================

class RegisterModal(
    ui.Modal,
    title="📝 ลงทะเบียน Voice Chat"
):

    xbox_name = ui.TextInput(

        label="Xbox Gamertag",

        placeholder="ตัวอย่าง: GamerPro1234",

        required=True
    )

    ic_name = ui.TextInput(

        label="ชื่อ IC",

        placeholder="ตัวอย่าง: John_Doe",

        required=True
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        user_database[
            str(interaction.user.id)
        ] = {

            "xbox_name":
                self.xbox_name.value.strip(),

            "ic_name":
                self.ic_name.value.strip()
        }

        save_database()

        await interaction.response.send_message(

            "✅ **ลงทะเบียนสำเร็จ!**\n\n"
            f"🎮 Xbox: `{self.xbox_name.value}`\n"
            f"🎭 IC: `{self.ic_name.value}`",

            ephemeral=True
        )


# =============================================================
# 📝 REGISTER VIEW
# =============================================================

class RegistrationView(ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )


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
                "❌ ยังไม่ได้ลงทะเบียน",
                ephemeral=True
            )

            return

        await interaction.response.send_message(

            "🔍 **ข้อมูลของคุณ**\n\n"
            f"🎮 Xbox: `{data['xbox_name']}`\n"
            f"🎭 IC: `{data['ic_name']}`",

            ephemeral=True
        )


# =============================================================
# 🤖 BOT
# =============================================================

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


# =============================================================
# READY
# =============================================================

@bot.event
async def on_ready():

    logging.info(
        f"✅ Bot Online: {bot.user}"
    )

    bot.add_view(
        RegistrationView()
    )

    try:

        synced = await bot.tree.sync()

        logging.info(
            f"Slash Commands: {len(synced)}"
        )

    except Exception as e:

        logging.error(
            f"Slash Sync Error: {e}"
        )


# =============================================================
# 📋 SETUP PANEL
# =============================================================

@bot.tree.command(
    name="setup-panel",
    description="สร้างแผงลงทะเบียน Voice Chat"
)

async def setup_panel(
    interaction: discord.Interaction
):

    embed = discord.Embed(

        title="🎙️ ระบบ Voice Chat",

        description=(
            "ระบบ Voice Chat สำหรับ Minecraft\n\n"
            "1️⃣ ลงทะเบียน Xbox Gamertag\n"
            "2️⃣ เข้า Discord Voice Lobby\n"
            "3️⃣ เข้า Minecraft\n"
            "4️⃣ ระบบจะเชื่อมบัญชีให้อัตโนมัติ\n\n"
            "📍 ระบบ Proximity Voice จะย้ายห้องตามระยะในเกม"
        ),

        color=discord.Color.blurple()
    )

    await interaction.response.send_message(

        embed=embed,

        view=RegistrationView()
    )


# =============================================================
# 🔊 SET DEFAULT VOICE
# =============================================================

@bot.tree.command(
    name="set-default-voice",
    description="ตั้งห้อง Lobby"
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

    default_voice_channel_id = channel.id
    default_category_id = channel.category_id

    await interaction.response.send_message(

        f"✅ ตั้ง Lobby เป็น **{channel.name}** แล้ว",

        ephemeral=True
    )


# =============================================================
# 🔊 CREATE PLAYER VOICE
# =============================================================

async def handle_player_join_game(
    guild_id: int,
    xbox_name: str
):

    if not default_voice_channel_id:

        logging.warning(
            "[VOICE] ยังไม่ได้ตั้ง Lobby"
        )

        return


    guild = bot.get_guild(
        guild_id
    )

    if not guild:

        logging.warning(
            "[VOICE] Guild ไม่พบ"
        )

        return


    discord_id = find_discord_by_xbox(
        xbox_name
    )


    if not discord_id:

        logging.warning(
            f"[VOICE] ไม่พบ Xbox: {xbox_name}"
        )

        return


    member = guild.get_member(
        discord_id
    )


    if not member:

        logging.warning(
            f"[VOICE] ไม่พบ Discord Member: {discord_id}"
        )

        return


    if xbox_name in player_sessions:

        return


    category = None

    if default_category_id:

        category = guild.get_channel(
            default_category_id
        )


    try:

        personal_channel = (
            await guild.create_voice_channel(

                name=f"🔊 {xbox_name}",

                category=category
            )
        )


        player_sessions[xbox_name] = {

            "discord_id":
                discord_id,

            "personal_channel_id":
                personal_channel.id,

            "current_channel_id":
                personal_channel.id,

            "pos": {

                "x": 0,
                "y": 0,
                "z": 0,

                "dim":
                    "minecraft:overworld"
            },

            "in_call":
                False
        }


        if (
            member.voice
            and
            member.voice.channel
        ):

            await member.move_to(
                personal_channel
            )


        logging.info(
            f"✅ Voice created: {xbox_name}"
        )


    except discord.HTTPException as e:

        logging.error(
            f"Create Voice Error: {e}"
        )


# =============================================================
# 📍 PROXIMITY
# =============================================================

async def handle_proximity_routing(
    guild_id: int,
    player_list: list
):

    guild = bot.get_guild(
        guild_id
    )

    if not guild:
        return


    for player in player_list:

        xbox = player.get(
            "xboxName"
        )

        if xbox not in player_sessions:
            continue


        session = player_sessions[xbox]

        session["pos"] = {

            "x":
                player.get("x", 0),

            "y":
                player.get("y", 0),

            "z":
                player.get("z", 0),

            "dim":
                player.get(
                    "dim",
                    "minecraft:overworld"
                )
        }


    sessions = list(
        player_sessions.items()
    )


    for i in range(
        len(sessions)
    ):

        name1, data1 = sessions[i]


        # ไม่ให้ Proximity ดึงคนที่กำลังโทร
        if data1.get("in_call"):
            continue


        for j in range(
            i + 1,
            len(sessions)
        ):

            name2, data2 = sessions[j]


            if data2.get("in_call"):
                continue


            if (
                data1["pos"]["dim"]
                !=
                data2["pos"]["dim"]
            ):

                continue


            dx = (
                data1["pos"]["x"]
                -
                data2["pos"]["x"]
            )

            dy = (
                data1["pos"]["y"]
                -
                data2["pos"]["y"]
            )

            dz = (
                data1["pos"]["z"]
                -
                data2["pos"]["z"]
            )


            distance = math.sqrt(
                dx * dx +
                dy * dy +
                dz * dz
            )


            if distance > 15:
                continue


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


            channel1 = member1.voice.channel
            channel2 = member2.voice.channel


            if channel1.id == channel2.id:
                continue


            try:

                await member2.move_to(
                    channel1
                )

                data2[
                    "current_channel_id"
                ] = channel1.id


                logging.info(
                    f"[PROXIMITY] "
                    f"{name2} -> {channel1.name}"
                )


            except discord.HTTPException:
                pass


# =============================================================
# 📞 PHONE
# =============================================================

async def handle_phone_call(
    data: dict
):

    msg_type = data.get(
        "type"
    )


    guild_id = int(
        data.get(
            "guildId",
            0
        )
    )


    guild = bot.get_guild(
        guild_id
    )


    if not guild:
        return


    # =========================================================
    # START CALL
    # =========================================================

    if msg_type == "START_PRIVATE_CALL":

        caller = data.get(
            "caller"
        )

        target = data.get(
            "target"
        )


        caller_data = player_sessions.get(
            caller
        )

        target_data = player_sessions.get(
            target
        )


        if not caller_data or not target_data:

            logging.warning(
                "[CALL] ไม่พบ Session"
            )

            return


        caller_data["in_call"] = True
        target_data["in_call"] = True


        try:

            category = None

            if default_category_id:

                category = guild.get_channel(
                    default_category_id
                )


            call_channel = (
                await guild.create_voice_channel(

                    name=f"📞 {caller} ↔ {target}",

                    category=category
                )
            )


            for name in [
                caller,
                target
            ]:

                session = player_sessions.get(
                    name
                )

                if not session:
                    continue


                member = guild.get_member(
                    session["discord_id"]
                )


                if (
                    member
                    and
                    member.voice
                ):

                    await member.move_to(
                        call_channel
                    )


            caller_data[
                "call_channel_id"
            ] = call_channel.id

            target_data[
                "call_channel_id"
            ] = call_channel.id


            logging.info(
                f"📞 Call started: {caller} ↔ {target}"
            )


        except discord.HTTPException as e:

            logging.error(
                f"Call Error: {e}"
            )


    # =========================================================
    # END CALL
    # =========================================================

    elif msg_type == "END_CALL":

        player = data.get(
            "player"
        )

        target = data.get(
            "target"
        )


        names = [
            player,
            target
        ]


        call_channel = None


        for name in names:

            session = player_sessions.get(
                name
            )

            if not session:
                continue


            session["in_call"] = False


            channel_id = session.get(
                "call_channel_id"
            )


            if channel_id:

                call_channel = guild.get_channel(
                    channel_id
                )


        for name in names:

            session = player_sessions.get(
                name
            )

            if not session:
                continue


            member = guild.get_member(
                session["discord_id"]
            )


            personal_id = session.get(
                "personal_channel_id"
            )


            personal = guild.get_channel(
                personal_id
            )


            if (
                member
                and
                personal
                and
                member.voice
            ):

                try:

                    await member.move_to(
                        personal
                    )

                    session[
                        "current_channel_id"
                    ] = personal.id

                except discord.HTTPException:
                    pass


            session.pop(
                "call_channel_id",
                None
            )


        if call_channel:

            try:

                await call_channel.delete()

            except discord.HTTPException:
                pass


    # =========================================================
    # MUTE
    # =========================================================

    elif msg_type == "MUTE_TOGGLE":

        player = data.get(
            "player"
        )

        muted = bool(
            data.get(
                "isMuted",
                False
            )
        )


        session = player_sessions.get(
            player
        )


        if not session:
            return


        member = guild.get_member(
            session["discord_id"]
        )


        if not member:
            return


        try:

            await member.edit(
                mute=muted
            )

        except discord.HTTPException as e:

            logging.error(
                f"Mute Error: {e}"
            )


# =============================================================
# 🚨 SOS
# =============================================================

async def handle_sos_alert(
    data: dict
):

    channel_id = int(
        data.get(
            "sosChannelId",
            0
        )
    )


    channel = bot.get_channel(
        channel_id
    )


    if not isinstance(
        channel,
        discord.TextChannel
    ):

        return


    player = data.get(
        "playerName",
        "Unknown"
    )


    embed = discord.Embed(

        title="🚨 EMERGENCY CALL",

        color=discord.Color.red(),

        timestamp=datetime.now()
    )


    embed.add_field(

        name="👤 ผู้แจ้ง",

        value=(
            f"{player}\n"
            f"IC: {data.get('icName', player)}"
        ),

        inline=False
    )


    embed.add_field(

        name="📍 พิกัด",

        value=(
            f"{data.get('dimension', 'Unknown')}\n"
            f"{data.get('location', 'N/A')}"
        ),

        inline=False
    )


    embed.add_field(

        name="⏰ เวลา",

        value=data.get(
            "time",
            "N/A"
        ),

        inline=False
    )


    await channel.send(
        embed=embed
    )


# =============================================================
# 🌐 WEBSOCKET
# =============================================================

async def ws_handler(
    websocket
):

    logging.info(
        "🌐 Minecraft WebSocket Connected"
    )


    try:

        async for message in websocket:

            try:

                data = json.loads(
                    message
                )


                msg_type = data.get(
                    "type"
                )


                guild_id = int(
                    data.get(
                        "guildId",
                        0
                    )
                )


                logging.info(
                    f"[WS] {msg_type}"
                )


                # PLAYER JOIN
                if msg_type == "PLAYER_JOIN":

                    xbox = data.get(
                        "xboxName"
                    )


                    if xbox:

                        await handle_player_join_game(

                            guild_id,

                            xbox
                        )


                # POSITIONS
                elif msg_type == "POSITIONS_UPDATE":

                    await handle_proximity_routing(

                        guild_id,

                        data.get(
                            "players",
                            []
                        )
                    )


                # PHONE
                elif msg_type in [

                    "START_PRIVATE_CALL",

                    "END_CALL",

                    "MUTE_TOGGLE"

                ]:

                    await handle_phone_call(
                        data
                    )


                # SOS
                elif msg_type == "SOS_EMERGENCY":

                    await handle_sos_alert(
                        data
                    )


            except json.JSONDecodeError:

                logging.error(
                    "❌ Invalid JSON"
                )


            except Exception as e:

                logging.error(
                    f"❌ WS Processing Error: {e}",
                    exc_info=True
                )


    except websockets.exceptions.ConnectionClosed:

        logging.info(
            "❌ Minecraft disconnected"
        )


# =============================================================
# 🌐 WEBSOCKET SERVER
# =============================================================

async def start_websocket():

    logging.info(
        f"📡 WebSocket Server PORT {CONFIG['PORT']}"
    )


    async with websockets.serve(

        ws_handler,

        "0.0.0.0",

        CONFIG["PORT"],

        ping_interval=20,

        ping_timeout=20
    ):

        await asyncio.Future()


# =============================================================
# 🚀 MAIN
# =============================================================

async def main():

    async with bot:

        await asyncio.gather(

            bot.start(
                CONFIG["BOT_TOKEN"]
            ),

            start_websocket()
        )


if __name__ == "__main__":

    asyncio.run(
        main()
      )
