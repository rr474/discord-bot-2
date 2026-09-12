import os
import json
import math
import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands, ui
from discord.ext import commands
from aiohttp import web

# =============================================================
# ⚙️ CONFIGURATION
# =============================================================
CONFIG = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN", os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")),
    "PORT": int(os.getenv("PORT", 8080)),
    "ALLOWED_USERS": [933529869487321161], # อนุญาตเฉพาะ ID นี้เท่านั้น
    "SHOP_INFO": {
        "NAME": os.getenv("SHOP_NAME", "memory shop"),
        "LINK": os.getenv("SHOP_LINK", "https://discord.gg/bm78WmEfvs")
    }
}

logging.basicConfig(level=logging.INFO)

# =============================================================
# 🧠 GLOBAL STATE & DATABASE
# =============================================================
default_voice_channel_id = None
default_category_id = None
sos_channel_id = None
sos_role_id = None

user_database = {}      # discord_id -> {"xbox_name", "ic_name"}
xbox_to_discord = {}    # xbox_name.lower() -> discord_id
player_sessions = {}    # xbox_name -> {"discord_id", "personal_channel_id", "current_channel_id", "pos"}

pending_mc_commands = []

# =============================================================
# 🛡️ SECURITY & ACCESS CHECKER
# =============================================================
def check_access(user_id: int) -> bool:
    return user_id in CONFIG["ALLOWED_USERS"]

def create_unauthorized_warning_embed():
    embed = discord.Embed(
        title="⚠️┆ เตือนการใช้งานระบบ (Unauthorized Warning)",
        color=discord.Color.gold(),
        description=(
            "บัญชีผู้ใช้นี้ **ไม่อยู่ในสิทธิ์การใช้งานระบบ** (อนุญาตเฉพาะ ID ที่กำหนดไว้เท่านั้น)\n\n"
            f"🛒 **ติดต่อสอบถามสั่งซื้อ:** [{CONFIG['SHOP_INFO']['NAME']}]({CONFIG['SHOP_INFO']['LINK']})"
        )
    )
    embed.set_footer(text="ระบบตรวจสอบสิทธิ์การใช้งาน")
    return embed

# =============================================================
# 📱 UI COMPONENTS
# =============================================================
class RegisterModal(ui.Modal, title="📝 ลงทะเบียนข้อมูล Voice Chat"):
    xbox_name = ui.TextInput(label="ชื่อ Xbox Gamertag", placeholder="เช่น Rose28303", required=True)
    ic_name = ui.TextInput(label="ชื่อตัวละคร (IC)", placeholder="เช่น Rose", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        x_name = self.xbox_name.value.strip()
        ic = self.ic_name.value.strip()

        user_database[interaction.user.id] = {"xbox_name": x_name, "ic_name": ic}
        xbox_to_discord[x_name.lower()] = interaction.user.id

        await interaction.response.send_message(
            f"✅ **ลงทะเบียนสำเร็จ!**\n- **Xbox:** `{x_name}`\n- **ชื่อ IC:** `{ic}`",
            ephemeral=True
        )

        if interaction.guild_id:
            await handle_player_join_game(interaction.guild_id, interaction.user.id, x_name)

class RegistrationView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="ลงทะเบียน / แก้ไขข้อมูล", emoji="📝", style=discord.ButtonStyle.success, custom_id="btn_register")
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RegisterModal())

    @ui.button(label="ตรวจสอบสถานะ", emoji="🔍", style=discord.ButtonStyle.primary, custom_id="btn_check_status")
    async def check_status_button(self, interaction: discord.Interaction, button: ui.Button):
        user_data = user_database.get(interaction.user.id)
        if not user_data:
            await interaction.response.send_message("❌ บัญชีของคุณยังไม่ได้ลงทะเบียนในระบบ", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"✅ บัญชีเชื่อมต่อกับ Xbox: **{user_data['xbox_name']}** (IC: {user_data['ic_name']})",
                ephemeral=True
            )

# =============================================================
# 🤖 BOT INITIALIZATION & EVENTS
# =============================================================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info(f"✅ บอททำงานเรียบร้อยในชื่อ: {bot.user}")
    bot.add_view(RegistrationView())
    try:
        synced = await bot.tree.sync()
        logging.info(f"✅ Sync Commands ทั้งหมด {len(synced)} คำสั่ง")
    except Exception as e:
        logging.error(f"❌ Error Syncing Commands: {e}")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # 1. ระบบ Mute/Unmute Sync
    xbox_name = None
    for x_name, d_id in xbox_to_discord.items():
        if d_id == member.id:
            xbox_name = x_name
            break

    if xbox_name and (before.self_mute != after.self_mute or before.mute != after.mute):
        is_muted = after.self_mute or after.mute
        action = "MUTE" if is_muted else "UNMUTE"
        pending_mc_commands.append({
            "action": action,
            "target": xbox_name
        })

    # 2. ระบบลบห้องเสียงที่บอทสร้างขึ้นอัตโนมัติเมื่อไม่มีคนอยู่ (Auto Delete Empty Channel)
    if before.channel and before.channel != after.channel:
        old_channel = before.channel
        
        # ตรวจสอบว่าเป็นห้อง Proximity ที่ถูกสร้างโดยบอทหรือไม่
        is_bot_created = False
        target_xbox_name = None

        for x_name, session in list(player_sessions.items()):
            if session.get("personal_channel_id") == old_channel.id:
                is_bot_created = True
                target_xbox_name = x_name
                break

        # หากเป็นห้องที่บอทสร้าง และปัจจุบันไม่มีสมาชิกเหลืออยู่เลย
        if is_bot_created and len(old_channel.members) == 0:
            try:
                await old_channel.delete()
                logging.info(f"🗑️ ลบห้องเสียงว่างอัตโนมัติ: {old_channel.name} (ไม่มีคนอยู่แล้ว)")

                # เคลียร์ข้อมูล Session ของผู้ใช้
                if target_xbox_name in player_sessions:
                    player_sessions[target_xbox_name]["personal_channel_id"] = None
                    player_sessions[target_xbox_name]["current_channel_id"] = None
            except Exception as e:
                logging.error(f"❌ Error deleting empty channel {old_channel.name}: {e}")

# =============================================================
# 💻 SLASH COMMANDS
# =============================================================
@bot.tree.command(name="setup-panel", description="สร้างแผงเมนูล็อกอินยืนยันตัวตน")
async def setup_panel(interaction: discord.Interaction):
    if not check_access(interaction.user.id):
        await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    panel_embed = discord.Embed(
        title="📱 ระบบยืนยันตัวตน Minecraft Proximity Voice",
        description=(
            "กรุณากดปุ่มด้านล่างเพื่อเชื่อมต่อบัญชี Discord ของคุณเข้ากับชื่อในเกม Minecraft Bedrock\n\n"
            "• **ลงทะเบียน / แก้ไขข้อมูล:** เชื่อมชื่อ Xbox Gamertag\n"
            "• **ตรวจสอบสถานะ:** เช็กว่าบัญชีของคุณเชื่อมต่อสำเร็จหรือไม่"
        ),
        color=0x2b2d31
    )
    panel_embed.set_footer(text=f"{CONFIG['SHOP_INFO']['NAME']} | ปลอดภัย รวดเร็ว")

    try:
        await interaction.channel.send(embed=panel_embed, view=RegistrationView())
        await interaction.followup.send("✅ สร้าง Panel สำเร็จ!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ บอทไม่มีสิทธิ์ส่งข้อความในช่องนี้", ephemeral=True)

@bot.tree.command(name="set-voice-category", description="กำหนดหมวดหมู่ (Category) สำหรับสร้างห้องเสียง Proximity")
async def set_voice_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    if not check_access(interaction.user.id):
        await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
        return

    global default_category_id
    await interaction.response.defer(ephemeral=True)
    default_category_id = category.id
    await interaction.followup.send(f"✅ กำหนดหมวดหมู่ห้องเสียงเป็น: **{category.name}** เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="set-default-voice", description="กำหนดห้องเริ่มต้น (Lobby) สำหรับผู้เล่น")
async def set_default_voice(interaction: discord.Interaction, channel: discord.VoiceChannel):
    if not check_access(interaction.user.id):
        await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
        return

    global default_voice_channel_id, default_category_id
    await interaction.response.defer(ephemeral=True)
    default_voice_channel_id = channel.id
    if channel.category_id:
        default_category_id = channel.category_id
    await interaction.followup.send(f"✅ กำหนดห้องเสียงเริ่มต้นเป็น: **{channel.name}** เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="set-sos-channel", description="กำหนดช่องส่งการแจ้งเตือน SOS ฉุกเฉิน")
async def set_sos_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not check_access(interaction.user.id):
        await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
        return

    global sos_channel_id
    await interaction.response.defer(ephemeral=True)
    sos_channel_id = channel.id
    await interaction.followup.send(f"✅ ตั้งค่าห้องแจ้งเตือน SOS เป็น {channel.mention} เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="set-sos-role", description="กำหนด Role ที่จะได้รับการแท็กเมื่อมีการกด SOS")
async def set_sos_role(interaction: discord.Interaction, role: discord.Role):
    if not check_access(interaction.user.id):
        await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
        return

    global sos_role_id
    await interaction.response.defer(ephemeral=True)
    sos_role_id = role.id
    await interaction.followup.send(f"✅ ตั้งค่าแท็ก SOS เป็น Role: {role.mention} เรียบร้อยแล้ว!", ephemeral=True)

# =============================================================
# 🔊 VOICE ROUTING & LEAVE HANDLER LOGIC
# =============================================================
async def handle_player_join_game(guild_id: int, discord_id: int, xbox_name: str):
    guild = bot.get_guild(guild_id)
    if not guild:
        return

    member = guild.get_member(discord_id)
    if not member or not member.voice or not member.voice.channel:
        return

    if xbox_name in player_sessions and guild.get_channel(player_sessions[xbox_name]["personal_channel_id"]):
        return

    category = guild.get_channel(default_category_id) if default_category_id else None

    try:
        personal_channel = await guild.create_voice_channel(name=f"🔊 {xbox_name}", category=category)
        await member.move_to(personal_channel)

        player_sessions[xbox_name] = {
            "discord_id": discord_id,
            "personal_channel_id": personal_channel.id,
            "current_channel_id": personal_channel.id,
            "pos": {"x": 0, "y": 0, "z": 0, "dim": "overworld"}
        }
    except Exception as e:
        logging.error(f"❌ Error Creating Voice Channel: {e}")

async def handle_player_leave_game(guild_id: int, xbox_name: str):
    """เมื่อผู้เล่นออกจากเกม: ย้ายกลับห้องเริ่มต้น + ลบห้องเสียงส่วนตัว"""
    if xbox_name not in player_sessions:
        return

    session_data = player_sessions.pop(xbox_name, None)
    if not session_data:
        return

    guild = bot.get_guild(guild_id)
    if not guild:
        return

    discord_id = session_data.get("discord_id")
    personal_channel_id = session_data.get("personal_channel_id")

    # 1. ย้ายผู้เล่นกลับไปห้องเริ่มต้น (Lobby)
    if default_voice_channel_id:
        default_channel = guild.get_channel(default_voice_channel_id)
        if default_channel and isinstance(default_channel, discord.VoiceChannel):
            member = guild.get_member(discord_id)
            if member and member.voice:
                try:
                    await member.move_to(default_channel)
                    logging.info(f"↩️ ย้าย {xbox_name} กลับห้องเริ่มต้นแล้ว")
                except Exception as e:
                    logging.error(f"❌ ไม่สามารถย้ายผู้เล่นกลับห้องเริ่มต้นได้: {e}")

    # 2. ลบห้องเสียงส่วนตัว
    if personal_channel_id:
        p_channel = guild.get_channel(personal_channel_id)
        if p_channel and len(p_channel.members) == 0:
            try:
                await p_channel.delete()
                logging.info(f"🗑️ ลบห้องเสียงส่วนตัวของ {xbox_name} เรียบร้อยแล้ว")
            except Exception as e:
                logging.error(f"❌ ไม่สามารถลบห้องส่วนตัวได้: {e}")

async def handle_proximity_routing(guild_id: int, player_list: list):
    PROXIMITY_RADIUS = 15
    guild = bot.get_guild(guild_id)
    if not guild:
        return

    for p in player_list:
        xbox_name = p.get("xboxName")
        if not xbox_name:
            continue

        if xbox_name not in player_sessions:
            discord_id = xbox_to_discord.get(xbox_name.lower())
            if discord_id:
                await handle_player_join_game(guild_id, discord_id, xbox_name)

        if xbox_name in player_sessions:
            player_sessions[xbox_name]["pos"] = {"x": p["x"], "y": p["y"], "z": p["z"], "dim": p["dim"]}

    sessions = list(player_sessions.items())
    for i in range(len(sessions)):
        for j in range(i + 1, len(sessions)):
            p1_name, p1_data = sessions[i]
            p2_name, p2_data = sessions[j]

            if p1_data["pos"]["dim"] != p2_data["pos"]["dim"]:
                continue

            dist = math.sqrt(
                (p1_data["pos"]["x"] - p2_data["pos"]["x"]) ** 2 +
                (p1_data["pos"]["y"] - p2_data["pos"]["y"]) ** 2 +
                (p1_data["pos"]["z"] - p2_data["pos"]["z"]) ** 2
            )

            p2_member = guild.get_member(p2_data["discord_id"])
            if not p2_member or not p2_member.voice:
                continue

            if dist <= PROXIMITY_RADIUS:
                if p2_data["current_channel_id"] != p1_data["current_channel_id"]:
                    target_channel = guild.get_channel(p1_data["current_channel_id"])
                    if target_channel:
                        await p2_member.move_to(target_channel)
                        p2_data["current_channel_id"] = target_channel.id
            else:
                if (p2_data["current_channel_id"] != p2_data["personal_channel_id"] and 
                    p1_data["current_channel_id"] != p2_data["current_channel_id"]):
                    personal_channel = guild.get_channel(p2_data["personal_channel_id"])
                    if personal_channel:
                        await p2_member.move_to(personal_channel)
                        p2_data["current_channel_id"] = personal_channel.id

# =============================================================
# 🚨 SOS EMERGENCY HANDLER
# =============================================================
async def handle_sos_alert(data: dict):
    channel_target_id = sos_channel_id or int(data.get("sosChannelId", 0))
    channel = bot.get_channel(channel_target_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        return

    player_name = data.get("playerName", "Unknown")
    role_mention = f"<@&{sos_role_id}>" if sos_role_id else "@everyone"

    embed = discord.Embed(
        title="🚨 EMERGENCY CALL (แจ้งเหตุฉุกเฉิน)",
        color=discord.Color.red(),
        timestamp=datetime.now()
    )
    embed.add_field(name="👤 ผู้แจ้ง", value=f"{player_name} ({data.get('icName', player_name)})", inline=True)
    embed.add_field(name="📍 พิกัด", value=f"{data.get('dimension', 'Overworld')} | {data.get('location', 'N/A')}", inline=True)
    embed.set_footer(text="ระบบแจ้งเหตุฉุกเฉินจากโทรศัพท์มือถือในเกม")

    await channel.send(content=f"⚠️ {role_mention}", embed=embed)

# =============================================================
# 🌐 HTTP API SERVER
# =============================================================
routes = web.RouteTableDef()

@routes.post("/mc-update")
async def handle_mc_update(request):
    global pending_mc_commands
    try:
        data = await request.json()
        msg_type = data.get("type")
        guild_id = int(data.get("guildId", 0))

        if not guild_id and bot.guilds:
            guild_id = bot.guilds[0].id

        if msg_type == "PLAYER_JOIN":
            xbox_name = data.get("xboxName")
            discord_id = xbox_to_discord.get(xbox_name.lower()) if xbox_name else None
            if discord_id and guild_id:
                await handle_player_join_game(guild_id, discord_id, xbox_name)

        elif msg_type == "PLAYER_LEAVE":
            xbox_name = data.get("xboxName")
            if xbox_name and guild_id:
                await handle_player_leave_game(guild_id, xbox_name)

        elif msg_type == "POSITIONS_UPDATE":
            if guild_id:
                await handle_proximity_routing(guild_id, data.get("players", []))

        elif msg_type == "SOS_EMERGENCY":
            await handle_sos_alert(data)

        cmds_to_send = list(pending_mc_commands)
        pending_mc_commands.clear()

        return web.json_response({"status": "ok", "commands": cmds_to_send}, status=200)

    except Exception as e:
        logging.error(f"❌ API Processing Error: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400)

async def start_web_server():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", CONFIG["PORT"])
    await site.start()

async def main():
    await start_web_server()
    async with bot:
        await bot.start(CONFIG["BOT_TOKEN"])

if __name__ == "__main__":
    asyncio.run(main())
