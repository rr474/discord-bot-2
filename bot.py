import os
import json
import math
import asyncio
import logging

import discord
from discord import app_commands, ui
from discord.ext import commands
from aiohttp import web

# =============================================================
# ⚙️ CONFIGURATION & GLOBAL STATE
# =============================================================
CONFIG = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN", os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")),
    "PORT": int(os.getenv("PORT", 8080)),
    "ALLOWED_USERS": [933529869487321161],
    "SHOP_INFO": {
        "NAME": os.getenv("SHOP_NAME", "memory shop"),
        "LINK": os.getenv("SHOP_LINK", "https://discord.gg/bm78WmEfvs")
    }
}

logging.basicConfig(level=logging.INFO)

default_voice_channel_id = None
default_category_id = None
sos_channel_id = None
sos_role_id = None

user_database = {}      # discord_id -> {"xbox_name", "ic_name"}
xbox_to_discord = {}    # xbox_name.lower() -> discord_id
player_sessions = {}    # xbox_name -> {"discord_id", "personal_channel_id", "current_channel_id", "pos"}
active_calls = {}       # call_id -> {"channel_id", "members": [xbox_name]}

proximity_radius = 15
pending_mc_commands = []

def check_access(user_id: int) -> bool:
    return user_id in CONFIG["ALLOWED_USERS"]

def create_unauthorized_warning_embed():
    embed = discord.Embed(
        title="⚠️┆ เตือนการใช้งานระบบ (Unauthorized Warning)",
        color=discord.Color.gold(),
        description=(
            "บัญชีผู้ใช้นี้ **ไม่อยู่ในสิทธิ์การใช้งานระบบ**\n\n"
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
    
    for guild in bot.guilds:
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
    
    synced = await bot.tree.sync()
    logging.info(f"⚡ Sync คำสั่ง Slash Commands แบบ Global สำเร็จ ({len(synced)} คำสั่ง)")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
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

    if before.channel and before.channel != after.channel:
        old_channel = before.channel
        if len(old_channel.members) == 0:
            is_bot_created = False

            for x_name, session in list(player_sessions.items()):
                if session.get("personal_channel_id") == old_channel.id:
                    is_bot_created = True
                    session["personal_channel_id"] = None
                    session["current_channel_id"] = None
                    break

            for call_id, call_data in list(active_calls.items()):
                if call_data.get("channel_id") == old_channel.id:
                    is_bot_created = True
                    del active_calls[call_id]
                    break

            if is_bot_created or old_channel.name.startswith(("🔊", "📞", "👥")):
                try:
                    await old_channel.delete()
                    logging.info(f"🗑️ ลบห้องเสียงว่างอัตโนมัติ: {old_channel.name}")
                except Exception as e:
                    logging.error(f"❌ ไม่สามารถลบห้องเสียงได้: {e}")

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

@bot.tree.command(name="set-sos-channel", description="ตั้งค่าช่องแจ้งเตือนเหตุฉุกเฉิน (SOS) และเลือกยศที่จะแท็ก")
@app_commands.describe(channel="เลือกช่องข้อความแจ้งเตือน SOS", role="เลือกยศ/Role ที่จะให้แท็กแจ้งเตือน (ไม่ใส่จะใช้ @here)")
async def set_sos_channel(interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role = None):
    if not check_access(interaction.user.id):
        await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
        return

    global sos_channel_id, sos_role_id
    await interaction.response.defer(ephemeral=True)
    
    sos_channel_id = channel.id
    sos_role_id = role.id if role else None

    msg = f"✅ **ตั้งค่าช่องแจ้งเตือน SOS เรียบร้อย!**\n- **ช่องข้อความ:** {channel.mention}"
    msg += f"\n- **ยศ/Role ที่แจ้งเตือน:** {role.mention if role else '`@here`'}"
    await interaction.followup.send(msg, ephemeral=True)

# =============================================================
# 🔊 VOICE ROUTING & CALL LOGIC
# =============================================================
async def create_call_channel(guild: discord.Guild, call_type: str, members_xbox: list):
    category = guild.get_channel(default_category_id) if default_category_id else None
    channel_name = f"📞 โทรเดี่ยว: {members_xbox[0]}" if call_type == "single" else f"👥 โทรกลุ่ม ({len(members_xbox)} คน)"
    
    channel = await guild.create_voice_channel(name=channel_name, category=category)
    call_id = f"call_{len(active_calls) + 1}"
    active_calls[call_id] = {"channel_id": channel.id, "members": members_xbox}

    for x_name in members_xbox:
        d_id = xbox_to_discord.get(x_name.lower())
        if d_id:
            member = guild.get_member(d_id)
            if member and member.voice:
                try:
                    await member.move_to(channel)
                except Exception as e:
                    logging.error(f"❌ Move Error: {e}")

async def handle_player_join_game(guild_id: int, discord_id: int, xbox_name: str):
    guild = bot.get_guild(guild_id)
    if not guild: return
    member = guild.get_member(discord_id)
    if not member or not member.voice or not member.voice.channel: return

    if xbox_name in player_sessions and player_sessions[xbox_name].get("personal_channel_id"):
        p_chan = guild.get_channel(player_sessions[xbox_name]["personal_channel_id"])
        if p_chan:
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
    if xbox_name not in player_sessions: return
    session_data = player_sessions.pop(xbox_name, None)
    if not session_data: return

    guild = bot.get_guild(guild_id)
    if not guild: return

    discord_id = session_data.get("discord_id")
    personal_channel_id = session_data.get("personal_channel_id")

    if default_voice_channel_id:
        default_channel = guild.get_channel(default_voice_channel_id)
        if default_channel and isinstance(default_channel, discord.VoiceChannel):
            member = guild.get_member(discord_id)
            if member and member.voice:
                try: await member.move_to(default_channel)
                except Exception as e: logging.error(f"❌ Error moving back: {e}")

    if personal_channel_id:
        p_channel = guild.get_channel(personal_channel_id)
        if p_channel and len(p_channel.members) == 0:
            try: await p_channel.delete()
            except Exception as e: logging.error(f"❌ Error deleting channel: {e}")

async def handle_proximity_routing(guild_id: int, player_list: list):
    global proximity_radius
    guild = bot.get_guild(guild_id)
    if not guild: return

    for p in player_list:
        xbox_name = p.get("xboxName")
        if not xbox_name: continue
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

            if p1_data["pos"]["dim"] != p2_data["pos"]["dim"]: continue

            dist = math.sqrt(
                (p1_data["pos"]["x"] - p2_data["pos"]["x"]) ** 2 +
                (p1_data["pos"]["y"] - p2_data["pos"]["y"]) ** 2 +
                (p1_data["pos"]["z"] - p2_data["pos"]["z"]) ** 2
            )

            p1_member = guild.get_member(p1_data["discord_id"])
            p2_member = guild.get_member(p2_data["discord_id"])

            if dist <= proximity_radius:
                if p2_member and p2_member.voice and p1_data.get("current_channel_id"):
                    if p2_data.get("current_channel_id") != p1_data.get("current_channel_id"):
                        target_channel = guild.get_channel(p1_data["current_channel_id"])
                        if target_channel:
                            try:
                                await p2_member.move_to(target_channel)
                                p2_data["current_channel_id"] = target_channel.id
                            except Exception as e:
                                logging.error(f"❌ Cannot move p2: {e}")
            else:
                if p2_member and p2_member.voice and p2_data.get("personal_channel_id"):
                    if p2_data.get("current_channel_id") != p2_data.get("personal_channel_id"):
                        personal_channel = guild.get_channel(p2_data["personal_channel_id"])
                        if personal_channel:
                            try:
                                await p2_member.move_to(personal_channel)
                                p2_data["current_channel_id"] = personal_channel.id
                            except Exception as e:
                                logging.error(f"❌ Cannot move p2 back: {e}")

# =============================================================
# 🌐 HTTP API SERVER
# =============================================================
routes = web.RouteTableDef()

@routes.post("/mc-update")
async def handle_mc_update(request):
    global pending_mc_commands, proximity_radius, sos_channel_id, sos_role_id
    try:
        data = await request.json()
        msg_type = data.get("type")
        guild_id = int(data.get("guildId", 0))

        if not guild_id and bot.guilds:
            guild_id = bot.guilds[0].id

        guild = bot.get_guild(guild_id) if guild_id else None

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

        elif msg_type == "SET_RADIUS":
            new_radius = int(data.get("radius", 15))
            proximity_radius = new_radius
            logging.info(f"📏 ปรับระยะ Proximity Radius เป็น {proximity_radius} บล็อก")

        elif msg_type == "START_CALL" and guild:
            call_type = data.get("callType", "single")
            targets = data.get("targets", [])
            await create_call_channel(guild, call_type, targets)

        elif msg_type == "TOGGLE_MUTE" and guild:
            x_name = data.get("sender")
            is_muted = data.get("isMuted", False)
            d_id = xbox_to_discord.get(x_name.lower()) if x_name else None
            if d_id:
                member = guild.get_member(d_id)
                if member:
                    try:
                        await member.edit(mute=is_muted)
                    except Exception as e:
                        logging.error(f"❌ Mute Edit Error: {e}")

        elif msg_type == "SOS_EMERGENCY":
            if sos_channel_id:
                sos_channel = bot.get_channel(sos_channel_id)
                if sos_channel:
                    player_name = data.get("playerName", "Unknown")
                    location = data.get("location", "Unknown")
                    dimension = data.get("dimension", "overworld")
                    time_str = data.get("time", "")

                    embed = discord.Embed(
                        title="🚨 แจ้งเหตุฉุกเฉิน (SOS Emergency)",
                        description=f"มีการกดขอความช่วยเหลือฉุกเฉินจากในเกม!",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="👤 ผู้เล่น", value=f"`{player_name}`", inline=True)
                    embed.add_field(name="📍 พิกัด", value=f"`{location}`", inline=True)
                    embed.add_field(name="🌍 มิติ (Dimension)", value=f"`{dimension}`", inline=True)
                    embed.set_footer(text=f"เวลา: {time_str}")

                    role_mention = f"<@&{sos_role_id}>" if sos_role_id else "@here"
                    await sos_channel.send(content=f"🚨 {role_mention} **เกิดเหตุฉุกเฉิน!**", embed=embed)

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
