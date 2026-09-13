# ============================================================
# Minecraft Bedrock ↔ Railway ↔ Discord
# bot.py
# ============================================================

import os
import json
import logging
import asyncio
import math
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web


# ============================================================
# CONFIG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

DATA_FILE = Path("data.json")


# ============================================================
# DISCORD
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# DATA
# ============================================================

registered_users = {}

proximity_radius = 15.0

sos_channel_id = None
sos_role_id = None

default_category_id = None
default_lobby_channel_id = None

pending_mc_commands = []

proximity_channels = {}

call_channels = {}

proximity_processing = False

persistent_view_added = False


# ============================================================
# LOAD DATA
# ============================================================

def load_data():
    global registered_users
    global proximity_radius
    global sos_channel_id
    global sos_role_id
    global default_category_id
    global default_lobby_channel_id

    if not DATA_FILE.exists():
        logging.info(
            "ℹ️ ยังไม่มี data.json จะสร้างเมื่อมีการบันทึก"
        )
        return

    try:
        with DATA_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        registered_users = data.get(
            "registered_users",
            {}
        )

        proximity_radius = float(
            data.get(
                "proximity_radius",
                15
            )
        )

        sos_channel_id = data.get(
            "sos_channel_id"
        )

        sos_role_id = data.get(
            "sos_role_id"
        )

        default_category_id = data.get(
            "default_category_id"
        )

        default_lobby_channel_id = data.get(
            "default_lobby_channel_id"
        )

        logging.info(
            f"✅ Data loaded | "
            f"Users={len(registered_users)} | "
            f"Radius={proximity_radius}"
        )

    except Exception:
        logging.exception(
            "❌ Load data error"
        )


# ============================================================
# SAVE DATA
# ============================================================

def save_data():

    data = {
        "registered_users": registered_users,
        "proximity_radius": proximity_radius,
        "sos_channel_id": sos_channel_id,
        "sos_role_id": sos_role_id,
        "default_category_id": default_category_id,
        "default_lobby_channel_id": default_lobby_channel_id
    }

    try:

        with DATA_FILE.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=4
            )

    except Exception:
        logging.exception(
            "❌ Save data error"
        )


load_data()


# ============================================================
# HELPERS
# ============================================================

def normalize_name(name):

    if not name:
        return ""

    return str(name).strip().casefold()


def get_guild(data):

    try:

        guild_id = int(
            data.get(
                "guildId",
                0
            )
        )

    except (TypeError, ValueError):

        guild_id = 0


    if guild_id:

        guild = bot.get_guild(
            guild_id
        )

        if guild:
            return guild


    if bot.guilds:

        return bot.guilds[0]


    return None


def get_category(guild):

    if not guild:
        return None

    if not default_category_id:
        return None

    try:

        channel = guild.get_channel(
            int(default_category_id)
        )

        if isinstance(
            channel,
            discord.CategoryChannel
        ):
            return channel

    except (TypeError, ValueError):

        pass

    return None


def get_lobby(guild):

    if not guild:
        return None

    if not default_lobby_channel_id:
        return None

    try:

        channel = guild.get_channel(
            int(default_lobby_channel_id)
        )

        if isinstance(
            channel,
            discord.VoiceChannel
        ):
            return channel

    except (TypeError, ValueError):

        pass

    return None


# ============================================================
# MOVE MEMBER
# ============================================================

async def move_member(
    member,
    channel
):

    try:

        if not member:
            return False

        if not channel:
            return False


        if (
            member.voice
            and member.voice.channel
            and member.voice.channel.id == channel.id
        ):

            return True


        # Discord สามารถย้ายได้เฉพาะคนที่อยู่ใน Voice แล้ว
        if not member.voice:

            return False


        await member.move_to(
            channel,
            reason="Minecraft Proximity Voice"
        )

        return True


    except discord.Forbidden:

        logging.error(
            f"❌ ไม่มีสิทธิ์ย้ายสมาชิก: {member}"
        )

        return False


    except Exception as e:

        logging.error(
            f"❌ Move error {member}: {e}"
        )

        return False


# ============================================================
# DELETE CHANNEL
# ============================================================

async def delete_channel(
    guild,
    channel_id
):

    if not guild:
        return

    if not channel_id:
        return

    try:

        channel = guild.get_channel(
            int(channel_id)
        )

        if channel:

            await channel.delete(
                reason="Minecraft Proximity cleanup"
            )

    except discord.NotFound:

        pass

    except discord.Forbidden:

        logging.error(
            f"❌ ไม่มีสิทธิ์ลบห้อง {channel_id}"
        )

    except Exception as e:

        logging.error(
            f"❌ Delete error: {e}"
        )


# ============================================================
# DISTANCE
# ============================================================

def distance(a, b):

    return math.sqrt(
        (a["x"] - b["x"]) ** 2
        + (a["y"] - b["y"]) ** 2
        + (a["z"] - b["z"]) ** 2
    )


# ============================================================
# GROUPS
# ============================================================

def make_groups(players):

    if not players:
        return []


    ids = list(
        players.keys()
    )


    parent = {
        player_id: player_id
        for player_id in ids
    }


    def find(x):

        while parent[x] != x:

            parent[x] = parent[
                parent[x]
            ]

            x = parent[x]

        return x


    def union(a, b):

        root_a = find(a)
        root_b = find(b)

        if root_a != root_b:

            parent[root_b] = root_a


    for i in range(
        len(ids)
    ):

        for j in range(
            i + 1,
            len(ids)
        ):

            a = players[
                ids[i]
            ]

            b = players[
                ids[j]
            ]


            if (
                a["dimension"]
                !=
                b["dimension"]
            ):

                continue


            if (
                distance(a, b)
                <=
                proximity_radius
            ):

                union(
                    ids[i],
                    ids[j]
                )


    grouped = {}


    for player_id in ids:

        root = find(
            player_id
        )


        if root not in grouped:

            grouped[root] = []


        grouped[root].append(
            players[player_id]
        )


    return list(
        grouped.values()
    )


# ============================================================
# SIGNATURE
# ============================================================

def group_signature(group):

    ids = sorted(
        str(
            info["discord_id"]
        )
        for info in group
    )

    return ":".join(ids)


# ============================================================
# PROXIMITY
# ============================================================

async def process_proximity(
    guild,
    active_players
):

    global proximity_channels


    groups = make_groups(
        active_players
    )


    active_signatures = set()


    category = get_category(
        guild
    )


    lobby = get_lobby(
        guild
    )


    for group in groups:

        if not group:
            continue


        signature = group_signature(
            group
        )


        active_signatures.add(
            signature
        )


        channel = None


        channel_id = proximity_channels.get(
            signature
        )


        if channel_id:

            channel = guild.get_channel(
                channel_id
            )


        # ====================================================
        # REUSE ROOM
        # ====================================================

        if channel:

            for info in group:

                await move_member(
                    info["member"],
                    channel
                )

            continue


        # ====================================================
        # CREATE ROOM
        # ====================================================

        if len(group) == 1:

            name = (
                f"🎮・"
                f"{group[0]['ic_name']}"
            )

        else:

            names = [
                info["ic_name"]
                for info in group[:2]
            ]

            name = (
                f"🔊・"
                f"{names[0]} + "
                f"{names[1]}"
            )

            if len(group) > 2:

                name += (
                    f" +{len(group) - 2}"
                )


        try:

            channel = await guild.create_voice_channel(
                name=name[:100],
                category=category,
                reason="Minecraft Proximity Voice"
            )


            proximity_channels[
                signature
            ] = channel.id


            logging.info(
                f"✅ Proximity room created: {name}"
            )


            for info in group:

                await move_member(
                    info["member"],
                    channel
                )


        except discord.Forbidden:

            logging.error(
                "❌ Bot ต้องมี "
                "Manage Channels และ Move Members"
            )


        except Exception as e:

            logging.error(
                f"❌ Create proximity error: {e}"
            )


    # ========================================================
    # CLEAN OLD ROOMS
    # ========================================================

    for signature, channel_id in list(
        proximity_channels.items()
    ):

        if signature in active_signatures:
            continue


        proximity_channels.pop(
            signature,
            None
        )


        channel = guild.get_channel(
            channel_id
        )


        if not channel:
            continue


        members = list(
            channel.members
        )


        if lobby:

            for member in members:

                await move_member(
                    member,
                    lobby
                )


        await delete_channel(
            guild,
            channel_id
        )


# ============================================================
# WEB ROUTES
# ============================================================

routes = web.RouteTableDef()


# ============================================================
# MC UPDATE
# ============================================================

@routes.post(
    "/mc-update"
)
async def handle_mc_update(
    request
):

    global proximity_processing
    global proximity_radius
    global sos_channel_id
    global sos_role_id
    global default_category_id
    global default_lobby_channel_id


    try:

        data = await request.json()


        msg_type = data.get(
            "type",
            ""
        )


        logging.info(
            f"📡 MC UPDATE: {msg_type}"
        )


        guild = get_guild(
            data
        )


        if not guild:

            return web.json_response(
                {
                    "status": "error",
                    "message": "Discord Guild not found",
                    "commands": []
                },
                status=400
            )


        # ====================================================
        # POSITION UPDATE
        # ====================================================

        if (
            msg_type
            ==
            "POSITIONS_UPDATE"
        ):

            if proximity_processing:

                return web.json_response(
                    {
                        "status": "busy",
                        "commands": []
                    }
                )


            proximity_processing = True


            try:

                active_players = {}


                for p in data.get(
                    "players",
                    []
                ):

                    xbox = p.get(
                        "xboxName"
                    )


                    if not xbox:
                        continue


                    key = normalize_name(
                        xbox
                    )


                    user = registered_users.get(
                        key
                    )


                    if not user:
                        continue


                    try:

                        discord_id = int(
                            user["discord_id"]
                        )

                    except (
                        KeyError,
                        TypeError,
                        ValueError
                    ):

                        continue


                    member = guild.get_member(
                        discord_id
                    )


                    if not member:
                        continue


                    # ต้องอยู่ใน Discord Voice ก่อน
                    if not member.voice:
                        continue


                    try:

                        x = float(
                            p.get(
                                "x",
                                0
                            )
                        )

                        y = float(
                            p.get(
                                "y",
                                0
                            )
                        )

                        z = float(
                            p.get(
                                "z",
                                0
                            )
                        )

                    except (
                        TypeError,
                        ValueError
                    ):

                        continue


                    active_players[
                        discord_id
                    ] = {

                        "discord_id":
                            discord_id,

                        "xbox_name":
                            xbox,

                        "ic_name":
                            user.get(
                                "ic_name",
                                xbox
                            ),

                        "member":
                            member,

                        "x":
                            x,

                        "y":
                            y,

                        "z":
                            z,

                        "dimension":
                            p.get(
                                "dimension",
                                "minecraft:overworld"
                            )
                    }


                await process_proximity(
                    guild,
                    active_players
                )


            finally:

                proximity_processing = False


        # ====================================================
        # START CALL
        # ====================================================

        elif (
            msg_type
            ==
            "START_CALL"
        ):

            targets = data.get(
                "targets",
                []
            )


            if not targets:

                return web.json_response(
                    {
                        "status": "ok",
                        "commands": []
                    }
                )


            members = []


            for xbox in targets:

                user = registered_users.get(
                    normalize_name(
                        xbox
                    )
                )


                if not user:
                    continue


                try:

                    discord_id = int(
                        user["discord_id"]
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError
                ):

                    continue


                member = guild.get_member(
                    discord_id
                )


                if member:

                    members.append(
                        member
                    )


            # =================================================
            # REMOVE DUPLICATES
            # =================================================

            unique_members = []

            seen = set()


            for member in members:

                if member.id in seen:
                    continue

                seen.add(
                    member.id
                )

                unique_members.append(
                    member
                )


            if not unique_members:

                logging.warning(
                    "⚠️ ไม่มีสมาชิก Discord สำหรับสายนี้"
                )

            else:

                category = get_category(
                    guild
                )


                if len(unique_members) == 2:

                    channel_name = (
                        "📞・สายโทร"
                    )

                else:

                    channel_name = (
                        f"👥・สายกลุ่ม・"
                        f"{len(unique_members)}"
                    )


                try:

                    channel = await guild.create_voice_channel(
                        name=channel_name[:100],
                        category=category,
                        reason="Minecraft Phone"
                    )


                    call_channels[
                        channel.id
                    ] = {

                        "members":
                            [
                                m.id
                                for m in unique_members
                            ]
                    }


                    for member in unique_members:

                        await move_member(
                            member,
                            channel
                        )


                    logging.info(
                        f"📞 Call room created: "
                        f"{channel_name}"
                    )


                except discord.Forbidden:

                    logging.error(
                        "❌ Bot ไม่มีสิทธิ์ "
                        "สร้าง/ย้ายห้องสาย"
                    )


                except Exception as e:

                    logging.error(
                        f"❌ Call room error: {e}"
                    )


        # ====================================================
        # SET RADIUS
        # ====================================================

        elif (
            msg_type
            ==
            "SET_RADIUS"
        ):

            try:

                radius = float(
                    data.get(
                        "radius",
                        15
                    )
                )


                proximity_radius = max(
                    1.0,
                    min(
                        100.0,
                        radius
                    )
                )


                save_data()


                logging.info(
                    f"🎙 Radius = "
                    f"{proximity_radius}"
                )


            except (
                TypeError,
                ValueError
            ) as e:

                logging.error(
                    f"❌ Radius error: {e}"
                )


        # ====================================================
        # TOGGLE MIC
        # ====================================================

        elif (
            msg_type
            ==
            "TOGGLE_MIC"
        ):

            logging.info(
                f"🎙 MIC | "
                f"{data.get('playerName')} | "
                f"{data.get('enabled')}"
            )


        # ====================================================
        # PLAYER LOCATION
        # ====================================================

        elif (
            msg_type
            ==
            "PLAYER_LOCATION"
        ):

            logging.info(
                f"📍 LOCATION | "
                f"{data.get('playerName')} | "
                f"{data.get('location')}"
            )


        # ====================================================
        # SOS
        # ====================================================

        elif (
            msg_type
            ==
            "SOS_EMERGENCY"
        ):

            if sos_channel_id:

                try:

                    channel = bot.get_channel(
                        int(
                            sos_channel_id
                        )
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    channel = None


                if channel:

                    player = data.get(
                        "playerName",
                        "Unknown"
                    )


                    location = data.get(
                        "location",
                        "Unknown"
                    )


                    dimension = data.get(
                        "dimension",
                        "Unknown"
                    )


                    embed = discord.Embed(
                        title="🚨 แจ้งเหตุฉุกเฉิน",
                        description=(
                            f"ผู้เล่น **{player}** "
                            f"ขอความช่วยเหลือ"
                        ),
                        color=discord.Color.red()
                    )


                    embed.add_field(
                        name="📍 พิกัด",
                        value=f"`{location}`",
                        inline=False
                    )


                    embed.add_field(
                        name="🌐 มิติ",
                        value=f"`{dimension}`",
                        inline=False
                    )


                    if sos_role_id:

                        content = (
                            f"🚨 <@&{sos_role_id}> "
                            f"มีเหตุฉุกเฉิน!"
                        )

                    else:

                        content = (
                            "🚨 มีเหตุฉุกเฉิน!"
                        )


                    await channel.send(
                        content=content,
                        embed=embed
                    )


        # ====================================================
        # COMMAND QUEUE
        # ====================================================

        commands_to_send = list(
            pending_mc_commands
        )


        pending_mc_commands.clear()


        return web.json_response(
            {
                "status": "ok",
                "commands": commands_to_send
            }
        )


    except Exception as e:

        logging.exception(
            "❌ MC API ERROR"
        )


        return web.json_response(
            {
                "status": "error",
                "message": str(e),
                "commands": []
            },
            status=400
        )


# ============================================================
# HOME
# ============================================================

@routes.get("/")
async def index(request):

    return web.Response(
        text="Minecraft Discord Bot Server is Running!",
        status=200
    )


# ============================================================
# REGISTER MODAL
# ============================================================

class RegisterModal(
    discord.ui.Modal,
    title="📝 ลงทะเบียน Xbox & IC"
):

    xbox_name = discord.ui.TextInput(
        label="ชื่อ Xbox Gamertag",
        placeholder="MyXboxName",
        required=True,
        max_length=50
    )


    ic_name = discord.ui.TextInput(
        label="ชื่อ IC",
        placeholder="ชื่อใน RP",
        required=True,
        max_length=50
    )


    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        original = (
            self.xbox_name.value.strip()
        )


        ic = (
            self.ic_name.value.strip()
        )


        registered_users[
            normalize_name(original)
        ] = {

            "discord_id":
                interaction.user.id,

            "ic_name":
                ic
        }


        save_data()


        embed = discord.Embed(
            title="✅ ลงทะเบียนสำเร็จ",
            description=(
                f"Discord: "
                f"{interaction.user.mention}\n\n"
                f"Xbox: `{original}`\n"
                f"IC: `{ic}`"
            ),
            color=discord.Color.green()
        )


        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# ============================================================
# PANEL
# ============================================================

class PanelView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    @discord.ui.button(
        label="ลงทะเบียนชื่อ",
        style=discord.ButtonStyle.green,
        custom_id="mc_register",
        emoji="📝"
    )
    async def register_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            RegisterModal()
        )


    @discord.ui.button(
        label="ตรวจสอบสถานะ",
        style=discord.ButtonStyle.blurple,
        custom_id="mc_status",
        emoji="🔍"
    )
    async def status_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        found_xbox = (
            "ยังไม่ได้ลงทะเบียน"
        )

        found_ic = "-"


        for xbox, info in registered_users.items():

            try:

                same = (
                    int(
                        info["discord_id"]
                    )
                    ==
                    interaction.user.id
                )

            except (
                KeyError,
                TypeError,
                ValueError
            ):

                same = False


            if same:

                found_xbox = xbox

                found_ic = info.get(
                    "ic_name",
                    "-"
                )

                break


        embed = discord.Embed(
            title="🔍 ข้อมูลบัญชี",
            description=(
                f"Discord: "
                f"{interaction.user.mention}\n"
                f"Xbox: `{found_xbox}`\n"
                f"IC: `{found_ic}`"
            ),
            color=discord.Color.blurple()
        )


        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(
    interaction: discord.Interaction
):

    return (
        interaction.guild
        and
        interaction.user.guild_permissions.administrator
    )


# ============================================================
# SETUP PANEL
# ============================================================

@bot.tree.command(
    name="setup-panel",
    description="สร้าง Panel ลงทะเบียน Xbox และ IC"
)
async def setup_panel(
    interaction: discord.Interaction
):

    if not is_admin(interaction):

        return await interaction.response.send_message(
            "❌ ต้องเป็นแอดมิน",
            ephemeral=True
        )


    embed = discord.Embed(
        title="🎙️ Minecraft Proximity Voice",
        description=(
            "ลงทะเบียน Xbox และ IC "
            "เพื่อเชื่อม Minecraft กับ Discord\n\n"
            "📝 ลงทะเบียนชื่อ\n"
            "🔍 ตรวจสอบสถานะ"
        ),
        color=discord.Color.blurple()
    )


    embed.set_footer(
        text="Memory Shop Roleplay System"
    )


    await interaction.channel.send(
        embed=embed,
        view=PanelView()
    )


    await interaction.response.send_message(
        "✅ สร้าง Panel แล้ว",
        ephemeral=True
    )


# ============================================================
# CATEGORY
# ============================================================

@bot.tree.command(
    name="set-category",
    description="ตั้ง Category ห้องเกม"
)
@app_commands.describe(
    category="Category สำหรับห้อง Proximity/Call"
)
async def set_category(
    interaction: discord.Interaction,
    category: discord.CategoryChannel
):

    if not is_admin(interaction):

        return await interaction.response.send_message(
            "❌ ต้องเป็นแอดมิน",
            ephemeral=True
        )


    global default_category_id


    default_category_id = (
        category.id
    )


    save_data()


    await interaction.response.send_message(
        f"✅ Category = **{category.name}**",
        ephemeral=True
    )


# ============================================================
# LOBBY
# ============================================================

@bot.tree.command(
    name="set-lobby",
    description="ตั้งห้อง Lobby"
)
@app_commands.describe(
    channel="Voice Lobby"
)
async def set_lobby(
    interaction: discord.Interaction,
    channel: discord.VoiceChannel
):

    if not is_admin(interaction):

        return await interaction.response.send_message(
            "❌ ต้องเป็นแอดมิน",
            ephemeral=True
        )


    global default_lobby_channel_id


    default_lobby_channel_id = (
        channel.id
    )


    save_data()


    await interaction.response.send_message(
        f"✅ Lobby = **{channel.name}**",
        ephemeral=True
    )


# ============================================================
# SOS CHANNEL
# ============================================================

@bot.tree.command(
    name="set-sos-channel",
    description="ตั้งช่อง SOS"
)
async def set_sos_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    if not is_admin(interaction):

        return await interaction.response.send_message(
            "❌ ต้องเป็นแอดมิน",
            ephemeral=True
        )


    global sos_channel_id


    sos_channel_id = (
        channel.id
    )


    save_data()


    await interaction.response.send_message(
        f"✅ SOS = {channel.mention}",
        ephemeral=True
    )


# ============================================================
# SOS ROLE
# ============================================================

@bot.tree.command(
    name="set-sos-role",
    description="ตั้ง Role SOS"
)
async def set_sos_role(
    interaction: discord.Interaction,
    role: discord.Role
):

    if not is_admin(interaction):

        return await interaction.response.send_message(
            "❌ ต้องเป็นแอดมิน",
            ephemeral=True
        )


    global sos_role_id


    sos_role_id = (
        role.id
    )


    save_data()


    await interaction.response.send_message(
        f"✅ SOS Role = {role.mention}",
        ephemeral=True
    )


# ============================================================
# RADIUS
# ============================================================

@bot.tree.command(
    name="set-radius",
    description="ตั้งระยะ Proximity"
)
@app_commands.describe(
    radius="ระยะ 1-100 blocks"
)
async def set_radius(
    interaction: discord.Interaction,
    radius: float
):

    if not is_admin(interaction):

        return await interaction.response.send_message(
            "❌ ต้องเป็นแอดมิน",
            ephemeral=True
        )


    global proximity_radius


    proximity_radius = max(
        1.0,
        min(
            100.0,
            radius
        )
    )


    save_data()


    await interaction.response.send_message(
        f"🎙️ Radius = "
        f"**{proximity_radius:g} blocks**",
        ephemeral=True
    )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    global persistent_view_added


    if not persistent_view_added:

        bot.add_view(
            PanelView()
        )

        persistent_view_added = True


    try:

        await bot.tree.sync()

        logging.info(
            "✅ Slash Commands Synced"
        )

    except Exception as e:

        logging.error(
            f"❌ Command Sync Error: {e}"
        )


    logging.info(
        f"✅ Bot Online: "
        f"{bot.user} | "
        f"Guilds={len(bot.guilds)}"
    )


# ============================================================
# WEB SERVER
# ============================================================

async def start_web_server():

    app = web.Application()


    app.add_routes(
        routes
    )


    runner = web.AppRunner(
        app
    )


    await runner.setup()


    port = int(
        os.environ.get(
            "PORT",
            "8080"
        )
    )


    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )


    await site.start()


    logging.info(
        f"🌐 Web Server : {port}"
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    await start_web_server()


    token = os.environ.get(
        "DISCORD_BOT_TOKEN"
    )


    if not token:

        raise RuntimeError(
            "DISCORD_BOT_TOKEN "
            "ไม่ถูกตั้งใน Railway Variables"
        )


    await bot.start(
        token
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    asyncio.run(
        main()
      )
