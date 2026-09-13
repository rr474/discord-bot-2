import os
import json
import logging
import discord
from discord.ext import commands
from aiohttp import web
import asyncio
import math
from pathlib import Path

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
intents.members = True
intents.guilds = True
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

proximity_radius = 15

sos_channel_id = None
sos_role_id = None

default_category_id = None
default_lobby_channel_id = None

# ห้อง Proximity
# group_signature -> channel_id
proximity_channels = {}

# ห้องโทร
# channel_id -> {"members": [discord_id, ...]}
call_channels = {}

# ป้องกัน request Proximity ซ้อน
proximity_processing = False


# ============================================================
# LOAD / SAVE DATA
# ============================================================

def load_data():
    global registered_users
    global proximity_radius
    global sos_channel_id
    global sos_role_id
    global default_category_id
    global default_lobby_channel_id

    if not DATA_FILE.exists():
        logging.info("ℹ️ ยังไม่มี data.json")
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        registered_users = data.get("registered_users", {})
        proximity_radius = int(data.get("proximity_radius", 15))

        sos_channel_id = data.get("sos_channel_id")
        sos_role_id = data.get("sos_role_id")

        default_category_id = data.get("default_category_id")
        default_lobby_channel_id = data.get("default_lobby_channel_id")

        logging.info(
            f"✅ โหลดข้อมูลสำเร็จ | Users={len(registered_users)} | Radius={proximity_radius}"
        )

    except Exception as e:
        logging.error(f"❌ Load data error: {e}")


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
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=4
            )

    except Exception as e:
        logging.error(f"❌ Save data error: {e}")


load_data()


# ============================================================
# HELPERS
# ============================================================

def normalize_name(name):
    if not name:
        return ""
    return str(name).strip().casefold()


def get_guild_from_data(data):
    try:
        guild_id = int(data.get("guildId", 0))
    except Exception:
        guild_id = 0

    if guild_id:
        guild = bot.get_guild(guild_id)
        if guild:
            return guild

    if bot.guilds:
        return bot.guilds[0]

    return None


def get_category(guild):
    if not default_category_id:
        return None

    try:
        return guild.get_channel(int(default_category_id))
    except Exception:
        return None


def get_lobby(guild):
    if not default_lobby_channel_id:
        return None

    try:
        return guild.get_channel(int(default_lobby_channel_id))
    except Exception:
        return None


async def move_member(member, channel):
    try:
        if not member:
            return False

        if not channel:
            return False

        if member.voice and member.voice.channel:
            if member.voice.channel.id == channel.id:
                return True

        await member.move_to(channel)
        return True

    except discord.Forbidden:
        logging.error(
            f"❌ ไม่มีสิทธิ์ย้าย {member} -> {channel.name}"
        )
        return False

    except Exception as e:
        logging.error(
            f"❌ Move Error {member}: {e}"
        )
        return False


async def delete_channel_safe(guild, channel_id):
    if not channel_id:
        return

    try:
        channel = guild.get_channel(int(channel_id))

        if channel:
            await channel.delete(
                reason="Minecraft Proximity Voice cleanup"
            )

    except discord.NotFound:
        pass

    except discord.Forbidden:
        logging.error(
            f"❌ ไม่มีสิทธิ์ลบห้อง {channel_id}"
        )

    except Exception as e:
        logging.error(
            f"❌ Delete Channel Error: {e}"
        )


# ============================================================
# PROXIMITY GROUP
# ============================================================

def distance(a, b):
    return math.sqrt(
        (a["x"] - b["x"]) ** 2 +
        (a["y"] - b["y"]) ** 2 +
        (a["z"] - b["z"]) ** 2
    )


def make_groups(players):
    """
    สร้างกลุ่มด้วย Union-Find

    ถ้า:
    A ใกล้ B
    B ใกล้ C

    A/B/C จะอยู่กลุ่มเดียวกัน
    """

    if not players:
        return []

    ids = list(players.keys())

    parent = {
        player_id: player_id
        for player_id in ids
    }

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        root_a = find(a)
        root_b = find(b)

        if root_a != root_b:
            parent[root_b] = root_a

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):

            a_id = ids[i]
            b_id = ids[j]

            a = players[a_id]
            b = players[b_id]

            if a["dimension"] != b["dimension"]:
                continue

            try:
                dist = distance(a, b)
            except Exception:
                continue

            if dist <= proximity_radius:
                union(a_id, b_id)

    grouped = {}

    for player_id in ids:
        root = find(player_id)

        if root not in grouped:
            grouped[root] = []

        grouped[root].append(
            players[player_id]
        )

    return list(grouped.values())


def group_signature(group):
    ids = sorted(
        str(info["discord_id"])
        for info in group
    )

    return ":".join(ids)


# ============================================================
# CREATE / REUSE PROXIMITY CHANNEL
# ============================================================

async def process_proximity(guild, active_players):
    global proximity_channels

    groups = make_groups(active_players)

    active_signatures = set()

    category = get_category(guild)
    lobby = get_lobby(guild)

    for group in groups:

        if not group:
            continue

        signature = group_signature(group)

        active_signatures.add(signature)

        channel_id = proximity_channels.get(signature)

        channel = None

        if channel_id:
            channel = guild.get_channel(channel_id)

        # ====================================================
        # ห้องเดิมยังอยู่
        # ====================================================

        if channel:

            for info in group:
                member = info["member"]

                if member.voice:
                    if member.voice.channel:
                        if member.voice.channel.id == channel.id:
                            continue

                await move_member(
                    member,
                    channel
                )

            continue

        # ====================================================
        # สร้างห้องใหม่
        # ====================================================

        if len(group) == 1:

            ic_name = group[0]["ic_name"]

            channel_name = (
                f"🎮・{ic_name}"
            )

        else:

            names = [
                info["ic_name"]
                for info in group[:2]
            ]

            channel_name = (
                f"🔊・{names[0]} + {names[1]}"
            )

            if len(group) > 2:
                channel_name += (
                    f" +{len(group) - 2}"
                )

        try:

            new_channel = await guild.create_voice_channel(
                name=channel_name[:100],
                category=category,
                reason="Minecraft Proximity Voice"
            )

            proximity_channels[
                signature
            ] = new_channel.id

            logging.info(
                f"✅ สร้าง Proximity Room: {channel_name}"
            )

            for info in group:

                member = info["member"]

                await move_member(
                    member,
                    new_channel
                )

        except discord.Forbidden:

            logging.error(
                "❌ Bot ไม่มีสิทธิ์ Manage Channels / Move Members"
            )

        except Exception as e:

            logging.error(
                f"❌ Create Proximity Room Error: {e}"
            )

    # ========================================================
    # ลบห้องที่ไม่มีกลุ่มแล้ว
    # ========================================================

    old_signatures = list(
        proximity_channels.keys()
    )

    for signature in old_signatures:

        if signature in active_signatures:
            continue

        channel_id = proximity_channels.pop(
            signature,
            None
        )

        if not channel_id:
            continue

        channel = guild.get_channel(
            channel_id
        )

        if not channel:
            continue

        # ถ้ายังมีสมาชิกอยู่ ให้ส่ง Lobby ก่อน
        members_to_move = []

        for member in channel.members:
            members_to_move.append(member)

        if lobby:

            for member in members_to_move:

                await move_member(
                    member,
                    lobby
                )

        await delete_channel_safe(
            guild,
            channel_id
        )


# ============================================================
# MC API
# ============================================================

routes = web.RouteTableDef()


@routes.post("/mc-update")
async def handle_mc_update(request):

    global proximity_radius
    global sos_channel_id
    global sos_role_id
    global default_category_id
    global default_lobby_channel_id
    global proximity_processing

    try:

        data = await request.json()

        msg_type = data.get(
            "type",
            ""
        )

        guild = get_guild_from_data(
            data
        )

        if not guild:

            logging.error(
                "❌ ไม่พบ Discord Guild"
            )

            return web.json_response(
                {
                    "status": "error",
                    "message": "Guild not found"
                },
                status=400
            )

        # ====================================================
        # POSITION UPDATE
        # ====================================================

        if msg_type == "POSITIONS_UPDATE":

            if proximity_processing:

                return web.json_response(
                    {
                        "status": "busy",
                        "commands": []
                    },
                    status=200
                )

            proximity_processing = True

            try:

                players = data.get(
                    "players",
                    []
                )

                active_players = {}

                for p in players:

                    xbox_name = p.get(
                        "xboxName"
                    )

                    if not xbox_name:
                        continue

                    key = normalize_name(
                        xbox_name
                    )

                    user_info = registered_users.get(
                        key
                    )

                    if not user_info:
                        continue

                    discord_id = int(
                        user_info["discord_id"]
                    )

                    member = guild.get_member(
                        discord_id
                    )

                    if not member:
                        continue

                    # ต้องอยู่ใน Voice ถึงจะย้ายห้อง
                    if not member.voice:
                        continue

                    try:
                        x = float(
                            p.get("x", 0)
                        )

                        y = float(
                            p.get("y", 0)
                        )

                        z = float(
                            p.get("z", 0)
                        )

                    except Exception:
                        continue

                    active_players[
                        discord_id
                    ] = {
                        "discord_id": discord_id,
                        "xbox_name": xbox_name,
                        "ic_name": user_info.get(
                            "ic_name",
                            xbox_name
                        ),
                        "member": member,
                        "x": x,
                        "y": y,
                        "z": z,
                        "dimension": p.get(
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

        elif msg_type == "START_CALL":

            call_type = data.get(
                "callType",
                "single"
            )

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

            discord_members = []

            for xbox_name in targets:

                key = normalize_name(
                    xbox_name
                )

                info = registered_users.get(
                    key
                )

                if not info:
                    continue

                try:
                    discord_id = int(
                        info["discord_id"]
                    )
                except Exception:
                    continue

                member = guild.get_member(
                    discord_id
                )

                if not member:
                    continue

                discord_members.append(
                    member
                )

            # เอาคนซ้ำออก
            unique_members = []

            seen = set()

            for member in discord_members:

                if member.id in seen:
                    continue

                seen.add(member.id)

                unique_members.append(
                    member
                )

            if not unique_members:

                logging.warning(
                    "⚠️ START_CALL ไม่มีสมาชิก Discord ที่พบ"
                )

            else:

                category = get_category(
                    guild
                )

                if call_type == "single":

                    channel_name = (
                        f"📞・สายโทร・{targets[0]}"
                    )

                else:

                    channel_name = (
                        f"👥・สายกลุ่ม・{len(unique_members)}"
                    )

                try:

                    new_channel = await guild.create_voice_channel(
                        name=channel_name[:100],
                        category=category,
                        reason="Minecraft Phone Call"
                    )

                    call_channels[
                        new_channel.id
                    ] = {
                        "members": [
                            member.id
                            for member in unique_members
                        ]
                    }

                    for member in unique_members:

                        await move_member(
                            member,
                            new_channel
                        )

                    logging.info(
                        f"📞 สร้างห้องโทร: {channel_name}"
                    )

                except Exception as e:

                    logging.error(
                        f"❌ Create Call Error: {e}"
                    )

        # ====================================================
        # SET RADIUS
        # ====================================================

        elif msg_type == "SET_RADIUS":

            try:

                new_radius = float(
                    data.get(
                        "radius",
                        15
                    )
                )

                if new_radius < 1:
                    new_radius = 1

                if new_radius > 100:
                    new_radius = 100

                proximity_radius = new_radius

                save_data()

                logging.info(
                    f"🎙️ Proximity Radius = {proximity_radius}"
                )

            except Exception as e:

                logging.error(
                    f"❌ SET_RADIUS Error: {e}"
                )

        # ====================================================
        # TOGGLE MIC
        # ====================================================

        elif msg_type == "TOGGLE_MIC":

            player_name = data.get(
                "playerName",
                "Unknown"
            )

            enabled = bool(
                data.get(
                    "enabled",
                    True
                )
            )

            logging.info(
                f"🎙️ MIC {player_name} = {enabled}"
            )

        # ====================================================
        # SOS
        # ====================================================

        elif msg_type == "SOS_EMERGENCY":

            if sos_channel_id:

                sos_channel = bot.get_channel(
                    int(sos_channel_id)
                )

                if sos_channel:

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
                        "Unknown"
                    )

                    embed = discord.Embed(
                        title="🚨 แจ้งเหตุฉุกเฉิน",
                        description=(
                            f"ผู้เล่น **{player_name}** "
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
                            f"**มีเหตุฉุกเฉิน!**"
                        )

                    else:

                        content = (
                            "🚨 **มีเหตุฉุกเฉิน!**"
                        )

                    await sos_channel.send(
                        content=content,
                        embed=embed
                    )

        # ====================================================
        # MC COMMAND QUEUE
        # ====================================================

        commands_to_send = list(
            pending_mc_commands
        )

        pending_mc_commands.clear()

        return web.json_response(
            {
                "status": "ok",
                "commands": commands_to_send
            },
            status=200
        )

    except Exception as e:

        logging.exception(
            "❌ MC API Error"
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
        text=(
            "Minecraft Discord Bot Server is Running!"
        ),
        status=200
    )


# ============================================================
# REGISTER MODAL
# ============================================================

class RegisterModal(
    discord.ui.Modal,
    title="📝 ลงทะเบียนข้อมูลผู้เล่น"
):

    xbox_name = discord.ui.TextInput(
        label="ชื่อ Xbox Gamertag",
        placeholder="เช่น MyXboxName",
        required=True,
        max_length=50
    )

    ic_name = discord.ui.TextInput(
        label="ชื่อ IC",
        placeholder="เช่น สมชาย",
        required=True,
        max_length=50
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        x_name_original = self.xbox_name.value.strip()
        x_name = normalize_name(
            x_name_original
        )

        i_name = self.ic_name.value.strip()

        registered_users[x_name] = {
            "discord_id": interaction.user.id,
            "ic_name": i_name
        }

        save_data()

        embed = discord.Embed(
            title="✅ ลงทะเบียนสำเร็จ",
            description=(
                f"ยินดีต้อนรับ "
                f"{interaction.user.mention}\n\n"
                f"• Xbox: `{x_name_original}`\n"
                f"• IC: `{i_name}`"
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# ============================================================
# PANEL VIEW
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
        custom_id="btn_register",
        emoji="📝"
    )
    async def register_button(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            RegisterModal()
        )

    @discord.ui.button(
        label="ตรวจสอบสถานะ",
        style=discord.ButtonStyle.blurple,
        custom_id="btn_status",
        emoji="🔍"
    )
    async def status_button(
        self,
        interaction,
        button
    ):

        user_id = interaction.user.id

        found_xbox = "ยังไม่ได้ลงทะเบียน"
        found_ic = "-"

        for xbox, info in registered_users.items():

            if int(
                info["discord_id"]
            ) == user_id:

                found_xbox = xbox
                found_ic = info["ic_name"]

                break

        embed = discord.Embed(
            title="🔍 ข้อมูลบัญชี",
            description=(
                f"• Discord: {interaction.user.mention}\n"
                f"• Xbox: `{found_xbox}`\n"
                f"• IC: `{found_ic}`"
            ),
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


# ============================================================
# SETUP PANEL
# ============================================================

@bot.tree.command(
    name="setup-panel",
    description="สร้าง Panel ลงทะเบียน Xbox & IC"
)
async def setup_panel(
    interaction: discord.Interaction
):

    embed = discord.Embed(
        title="🎙️ ระบบ Proximity Voice",
        description=(
            "ลงทะเบียนชื่อ Xbox และชื่อ IC "
            "เพื่อเชื่อม Minecraft กับ Discord\n\n"
            "📝 ลงทะเบียนชื่อ\n"
            "🔍 ตรวจสอบสถานะ\n"
            "🎙️ ใช้งาน Proximity Voice"
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
        "✅ สร้าง Panel เรียบร้อย",
        ephemeral=True
    )


# ============================================================
# SET CATEGORY
# ============================================================

@bot.tree.command(
    name="set-category",
    description="ตั้ง Category สำหรับห้อง Proximity / โทร"
)
async def set_category(
    interaction: discord.Interaction,
    category: discord.CategoryChannel
):

    global default_category_id

    default_category_id = category.id

    save_data()

    await interaction.response.send_message(
        f"✅ ตั้ง Category เป็น **{category.name}**",
        ephemeral=True
    )


# ============================================================
# SET LOBBY
# ============================================================

@bot.tree.command(
    name="set-lobby",
    description="ตั้งห้อง Lobby"
)
async def set_lobby(
    interaction: discord.Interaction,
    channel: discord.VoiceChannel
):

    global default_lobby_channel_id

    default_lobby_channel_id = channel.id

    save_data()

    await interaction.response.send_message(
        f"✅ ตั้ง Lobby เป็น **{channel.name}**",
        ephemeral=True
    )


# ============================================================
# SET SOS CHANNEL
# ============================================================

@bot.tree.command(
    name="set-sos-channel",
    description="ตั้งช่องแจ้งเตือน SOS"
)
async def set_sos_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):

    global sos_channel_id

    sos_channel_id = channel.id

    save_data()

    await interaction.response.send_message(
        f"✅ ตั้งช่อง SOS เป็น {channel.mention}",
        ephemeral=True
    )


# ============================================================
# SET SOS ROLE
# ============================================================

@bot.tree.command(
    name="set-sos-role",
    description="ตั้งยศสำหรับแจ้ง SOS"
)
async def set_sos_role(
    interaction: discord.Interaction,
    role: discord.Role
):

    global sos_role_id

    sos_role_id = role.id

    save_data()

    await interaction.response.send_message(
        f"✅ ตั้งยศ SOS เป็น {role.mention}",
        ephemeral=True
    )


# ============================================================
# SET RADIUS DISCORD COMMAND
# ============================================================

@bot.tree.command(
    name="set-radius",
    description="ตั้งระยะ Proximity Voice"
)
async def set_radius(
    interaction: discord.Interaction,
    radius: float
):

    global proximity_radius

    radius = max(
        1,
        min(radius, 100)
    )

    proximity_radius = radius

    save_data()

    await interaction.response.send_message(
        f"🎙️ ตั้งระยะ Proximity เป็น **{radius} blocks**",
        ephemeral=True
    )


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():

    bot.add_view(
        PanelView()
    )

    try:

        await bot.tree.sync()

    except Exception as e:

        logging.error(
            f"❌ Slash Command Sync Error: {e}"
        )

    logging.info(
        f"✅ Logged in as {bot.user} | Guilds: {len(bot.guilds)}"
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
        f"🌐 Web Server started on port {port}"
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
            "❌ ไม่พบ DISCORD_BOT_TOKEN ใน Railway Variables"
        )

    await bot.start(
        token
    )


if __name__ == "__main__":

    asyncio.run(
        main()
  )
