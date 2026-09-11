import os
import json
import math
import asyncio
import logging
from pathlib import Path
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput

import websockets

# =========================================================
# CONFIG & PERMISSIONS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", "8080"))
GUILD_ID = int(os.getenv("GUILD_ID", "1499842090480435363"))
ALLOWED_ADMIN_ID = 933529869487321161

SHOP_NAME = "memory shop"
SHOP_LINK = "https://discord.gg/bm78WmEfvs"

DATABASE_FILE = Path("database.json")
DEFAULT_PROXIMITY_RADIUS = 15

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s"
)
log = logging.getLogger("MinecraftVoice")

# =========================================================
# DATABASE
# =========================================================

DEFAULT_DATABASE = {
    "user_database": {},
    "default_voice_channel_id": 0,
    "default_category_id": 0,
    "sos_channel_id": 0,
    "player_sessions": {},
    "active_call_channels": {},
    "groups": {}
}

def load_database():
    if not DATABASE_FILE.exists():
        save_database(DEFAULT_DATABASE.copy())
        return DEFAULT_DATABASE.copy()

    try:
        with open(DATABASE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, value in DEFAULT_DATABASE.items():
            if key not in data:
                data[key] = value.copy() if isinstance(value, dict) else value
        return data
    except Exception as e:
        log.error(f"Database load error: {e}")
        return DEFAULT_DATABASE.copy()

def save_database(data=None):
    global db
    if data is not None:
        db = data
    try:
        with open(DATABASE_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Database save error: {e}")

db = load_database()

# =========================================================
# RUNTIME DATA & BOT INIT
# =========================================================

minecraft_connections = set()
player_voice_ranges = {}

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# PERMISSION CHECKER
# =========================================================

def is_authorized_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.id == ALLOWED_ADMIN_ID

# =========================================================
# UTILS
# =========================================================

def now_string():
    return datetime.now().strftime("%H:%M:%S")

def clean_name(name):
    return str(name).strip()

def get_guild():
    return bot.get_guild(GUILD_ID)

def find_discord_id_by_xbox(xbox_name):
    xbox_name = clean_name(xbox_name)
    for discord_id, info in db["user_database"].items():
        if str(info.get("xboxName", "")).lower() == xbox_name.lower():
            return int(discord_id)
    return None

def get_player_session(xbox_name):
    return db["player_sessions"].get(xbox_name)

def save_player_session(xbox_name, data):
    db["player_sessions"][xbox_name] = data
    save_database()

def distance_between(a, b):
    if not a or not b or a.get("dim") != b.get("dim"):
        return 999999
    dx = float(a.get("x", 0)) - float(b.get("x", 0))
    dy = float(a.get("y", 0)) - float(b.get("y", 0))
    dz = float(a.get("z", 0)) - float(b.get("z", 0))
    return math.sqrt(dx * dx + dy * dy + dz * dz)

async def get_discord_member(xbox_name):
    guild = get_guild()
    if not guild:
        return None
    discord_id = find_discord_id_by_xbox(xbox_name)
    if not discord_id:
        return None
    try:
        member = guild.get_member(discord_id)
        if member:
            return member
        return await guild.fetch_member(discord_id)
    except Exception:
        return None

async def safe_move_member(member, channel):
    if not member or not channel:
        return False
    try:
        if member.voice and member.voice.channel:
            if member.voice.channel.id == channel.id:
                return True
            await member.move_to(channel, reason="Minecraft Proximity Voice")
            return True
    except Exception as e:
        log.warning(f"Move member error {member}: {e}")
    return False

# =========================================================
# VOICE & SOS HANDLERS
# =========================================================

async def create_personal_voice_channel(xbox_name, member):
    guild = get_guild()
    if not guild:
        return None

    session = get_player_session(xbox_name)
    if session and session.get("personal_channel_id"):
        channel = guild.get_channel(int(session["personal_channel_id"]))
        if channel:
            return channel

    category = None
    category_id = int(db.get("default_category_id", 0))
    if category_id:
        category = guild.get_channel(category_id)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=True, speak=True, view_channel=True)
    }
    if member:
        overwrites[member] = discord.PermissionOverwrite(connect=True, speak=True, view_channel=True)

    try:
        channel = await guild.create_voice_channel(
            name=f"🔊 {xbox_name}",
            category=category,
            overwrites=overwrites,
            reason="Minecraft Voice Chat"
        )
        return channel
    except Exception as e:
        log.error(f"Create voice channel error: {e}")
        return None

async def handle_player_join_game(xbox_name):
    xbox_name = clean_name(xbox_name)
    if not xbox_name:
        return

    member = await get_discord_member(xbox_name)
    player_voice_ranges.setdefault(xbox_name, DEFAULT_PROXIMITY_RADIUS)

    if not member:
        await send_to_minecraft("PLAYER_JOIN_RESULT", {
            "xboxName": xbox_name, "success": False, "message": "ยังไม่ได้ลงทะเบียน Discord กับ Xbox"
        })
        return

    channel = await create_personal_voice_channel(xbox_name, member)
    if not channel:
        await send_to_minecraft("PLAYER_JOIN_RESULT", {
            "xboxName": xbox_name, "success": False, "message": "สร้างห้องเสียงไม่สำเร็จ"
        })
        return

    save_player_session(xbox_name, {
        "discord_id": member.id,
        "personal_channel_id": channel.id,
        "in_call": False,
        "call_channel_id": 0,
        "radius": player_voice_ranges.get(xbox_name, DEFAULT_PROXIMITY_RADIUS)
    })

    await safe_move_member(member, channel)
    await send_to_minecraft("PLAYER_JOIN_RESULT", {
        "xboxName": xbox_name, "success": True, "message": "เชื่อม Discord สำเร็จ",
        "radius": player_voice_ranges.get(xbox_name, DEFAULT_PROXIMITY_RADIUS)
    })

async def handle_proximity_routing(players):
    if not players:
        return
    guild = get_guild()
    if not guild:
        return

    player_map = {clean_name(p.get("xboxName", "")): p for p in players if p.get("xboxName")}

    for name, player in player_map.items():
        session = get_player_session(name)
        if not session or session.get("in_call"):
            continue

        member = await get_discord_member(name)
        if not member or not member.voice:
            continue

        personal_channel_id = session.get("personal_channel_id")
        personal_channel = guild.get_channel(int(personal_channel_id)) if personal_channel_id else None
        if not personal_channel:
            continue

        radius_a = player_voice_ranges.get(name, DEFAULT_PROXIMITY_RADIUS)
        nearby = []

        for other_name, other_player in player_map.items():
            if other_name == name:
                continue
            other_session = get_player_session(other_name)
            if not other_session or other_session.get("in_call"):
                continue

            radius_b = player_voice_ranges.get(other_name, DEFAULT_PROXIMITY_RADIUS)
            effective_radius = min(radius_a, radius_b)
            if distance_between(player, other_player) <= effective_radius:
                nearby.append(other_name)

        if nearby:
            all_names = sorted([name] + nearby, key=lambda x: x.lower())
            anchor_session = get_player_session(all_names[0])
            if anchor_session and anchor_session.get("personal_channel_id"):
                anchor_channel = guild.get_channel(int(anchor_session["personal_channel_id"]))
                if anchor_channel:
                    await safe_move_member(member, anchor_channel)
        else:
            await safe_move_member(member, personal_channel)

async def handle_sos_emergency(data):
    sos_channel_id = int(db.get("sos_channel_id", 0))
    if not sos_channel_id:
        log.warning("SOS triggered but sos_channel_id is not set.")
        return

    guild = get_guild()
    if not guild:
        return

    channel = guild.get_channel(sos_channel_id)
    if not channel:
        return

    player_name = data.get("playerName", "Unknown")
    location = data.get("location", "Unknown Location")
    dimension = data.get("dimension", "overworld")

    embed = discord.Embed(
        title="🚨 แจ้งเหตุฉุกเฉิน (SOS)",
        description=f"ผู้เล่น **{player_name}** ต้องการความช่วยเหลือด่วน!",
        color=discord.Color.red(),
        timestamp=datetime.now()
    )
    embed.add_field(name="📍 พิกัด", value=f"`{location}`", inline=True)
    embed.add_field(name="🌍 มิติ", value=f"`{dimension}`", inline=True)
    embed.set_footer(text=f"ระบบไมค์ดิส | {SHOP_NAME}")

    await channel.send(content="@everyone", embed=embed)

# =========================================================
# WEBSOCKET PROTOCOL
# =========================================================

async def handle_minecraft_message(data):
    if not isinstance(data, dict):
        return
    packet_type = data.get("type")

    if packet_type in ["MC_CONNECTED", "PLAYER_JOIN"]:
        name = data.get("xboxName")
        if name:
            await handle_player_join_game(name)
        for player in data.get("players", []):
            if isinstance(player, dict) and player.get("xboxName"):
                await handle_player_join_game(player.get("xboxName"))

    elif packet_type == "POSITIONS_UPDATE":
        await handle_proximity_routing(data.get("players", []))

    elif packet_type == "SET_PROXIMITY_RADIUS":
        name, radius = data.get("xboxName"), data.get("radius")
        if name and radius:
            player_voice_ranges[name] = int(radius)
            await send_to_minecraft("PROXIMITY_RADIUS_CHANGED", {"xboxName": name, "radius": radius})

    elif packet_type == "SOS_EMERGENCY":
        await handle_sos_emergency(data)

async def send_to_minecraft(packet_type, data=None):
    packet = {"type": packet_type, **(data or {})}
    message = json.dumps(packet, ensure_ascii=False)
    dead = []
    for ws in list(minecraft_connections):
        try:
            await ws.send(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        minecraft_connections.discard(ws)

async def ws_handler(websocket):
    minecraft_connections.add(websocket)
    log.info("Minecraft connected to WebSocket")
    try:
        await websocket.send(json.dumps({"type": "WS_CONNECTED", "serverTime": now_string()}, ensure_ascii=False))
        async for raw_message in websocket:
            try:
                data = json.loads(raw_message)
                await handle_minecraft_message(data)
            except Exception as e:
                log.error(f"Packet error: {e}")
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        minecraft_connections.discard(websocket)

async def start_websocket():
    async with websockets.serve(ws_handler, "0.0.0.0", PORT, ping_interval=20, ping_timeout=20):
        log.info(f"WebSocket running on port {PORT}")
        await asyncio.Future()

# =========================================================
# DISCORD UI & COMMANDS
# =========================================================

class RegistrationModal(Modal, title="ลงทะเบียน Minecraft"):
    xbox_name = TextInput(label="Xbox Gamertag", required=True)
    ic_name = TextInput(label="IC Name", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        xbox = clean_name(self.xbox_name.value)
        ic = clean_name(self.ic_name.value) or xbox
        db["user_database"][str(interaction.user.id)] = {"xboxName": xbox, "icName": ic}
        save_database()
        await interaction.response.send_message(f"ลงทะเบียนสำเร็จ! Xbox: `{xbox}`", ephemeral=True)

class RegistrationView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ลงทะเบียน / แก้ไขข้อมูล", style=discord.ButtonStyle.success, custom_id="minecraft_register")
    async def register(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RegistrationModal())

    @discord.ui.button(label="ตรวจสอบสถานะ", style=discord.ButtonStyle.primary, custom_id="minecraft_status")
    async def check_status(self, interaction: discord.Interaction, button: Button):
        info = db["user_database"].get(str(interaction.user.id))
        if info:
            await interaction.response.send_message(f"📋 **ข้อมูลที่ลงทะเบียนไว้**\n- Xbox: `{info.get('xboxName')}`\n- IC Name: `{info.get('icName')}`", ephemeral=True)
        else:
            await interaction.response.send_message("❌ คุณยังไม่ได้ลงทะเบียน กรุณากดปุ่มลงทะเบียนก่อนครับ", ephemeral=True)

# --- BOT EVENTS ---

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user}")
    bot.add_view(RegistrationView())
    
    # ล้าง Command เก่าและ Sync ใหม่เฉพาะใน Guild เพื่อแก้ปัญหา Command Duplicate / CommandNotFound
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        log.info("Commands successfully synced to Guild!")
    except Exception as e:
        log.error(f"Sync error: {e}")

# --- SLASH COMMANDS (PERMISSION LOCKED) ---

@bot.tree.command(name="setup-panel", description="สร้าง Panel ลงทะเบียน (Admin Only)")
async def setup_panel(interaction: discord.Interaction):
    if not is_authorized_admin(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
        return

    embed = discord.Embed(
        title="📱 Minecraft Voice Chat",
        description="กดปุ่มด้านล่างเพื่อลงทะเบียนเชื่อมต่อ Xbox Gamertag กับ Discord",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"บริการระบบ Voice Chat โดย {SHOP_NAME} | ปลอดภัย ไร้ดีเลย์")
    await interaction.channel.send(embed=embed, view=RegistrationView())
    await interaction.response.send_message("สร้าง Panel เรียบร้อย", ephemeral=True)

@bot.tree.command(name="set-sos-channel", description="ตั้งค่าห้องรับการแจ้งเตือน SOS (Admin Only)")
@app_commands.describe(channel="เลือกช่องข้อความที่ต้องการส่งแจ้งเตือน SOS")
async def set_sos_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_authorized_admin(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
        return

    db["sos_channel_id"] = channel.id
    save_database()
    await interaction.response.send_message(f"✅ ตั้งค่าห้องแจ้งเตือน SOS เป็น {channel.mention} เรียบร้อยแล้ว", ephemeral=True)

@bot.tree.command(name="set-default-category", description="ตั้งค่าหมวดหมู่สำหรับสร้างห้องเสียง (Admin Only)")
@app_commands.describe(category="เลือกหมวดหมู่ Category")
async def set_default_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    if not is_authorized_admin(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
        return

    db["default_category_id"] = category.id
    save_database()
    await interaction.response.send_message(f"✅ ตั้งค่า Category สร้างห้องเสียงเป็น **{category.name}** เรียบร้อยแล้ว", ephemeral=True)

# =========================================================
# MAIN ENTRY
# =========================================================

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Missing BOT_TOKEN")
    asyncio.create_task(start_websocket())
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
