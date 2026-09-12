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
    "ALLOWED_GUILDS": [1499842090480435363],
    "ALLOWED_USERS": [933529869487321161],
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

user_database = {}      # discord_id -> {"xbox_name", "ic_name"}
player_sessions = {}    # xbox_name -> {"discord_id", "personal_channel_id", "current_channel_id", "pos"}

# =============================================================
# 🛡️ SECURITY & MESSAGES CHECKER
# =============================================================
def check_access(guild_id: int, user_id: int) -> bool:
    """เช็กว่าเซิร์ฟเวอร์หรือผู้ใช้นี้ได้รับอนุญาตหรือไม่"""
    is_guild_allowed = guild_id in CONFIG["ALLOWED_GUILDS"] if CONFIG["ALLOWED_GUILDS"] else False
    is_user_allowed = user_id in CONFIG["ALLOWED_USERS"] if CONFIG["ALLOWED_USERS"] else False
    return is_guild_allowed or is_user_allowed

def create_thank_you_embed():
    """Embed ข้อความขอบคุณเมื่อ ID เซิร์ฟเวอร์ถูกต้อง"""
    embed = discord.Embed(
        title="🎉┆ ขอบคุณที่อุดหนุนสินค้า!",
        color=discord.Color.green(),
        description=(
            f"ขอบคุณสำหรับการอุดหนุนระบบ Voice Chat จาก **{CONFIG['SHOP_INFO']['NAME']}** ❤️\n"
            "เซิร์ฟเวอร์ของคุณได้รับการเปิดใช้งานระบบอย่างสมบูรณ์แล้วครับ!"
        )
    )
    embed.set_footer(text=f"บริการโดย {CONFIG['SHOP_INFO']['NAME']}")
    return embed

def create_unauthorized_warning_embed():
    """Embed แจ้งเตือนเมื่อ ID ไม่ถูก/ไม่อยู่ใน Whitelist"""
    embed = discord.Embed(
        title="⚠️┆ เตือนการใช้งานระบบ (Unauthorized Warning)",
        color=discord.Color.gold(),
        description=(
            "เซิร์ฟเวอร์ หรือ บัญชีผู้ใช้นี้ **ยังไม่ได้ทำการซื้อลิขสิทธิ์ระบบ Voice Chat อย่างถูกต้อง**\n"
            "*ระบบอนุญาตให้ใช้งานชั่วคราว/พิมพ์ทับได้ แต่โปรดติดต่อลงทะเบียนเพื่อใช้งานระยะยาว*\n\n"
            f"🛒 **สั่งซื้อลิขสิทธิ์ได้ที่:** [{CONFIG['SHOP_INFO']['NAME']}]({CONFIG['SHOP_INFO']['LINK']})"
        )
    )
    embed.set_footer(text="ระบบแจ้งเตือนลิขสิทธิ์การใช้งาน")
    return embed

# =============================================================
# 📱 UI COMPONENTS (Modal & Buttons)
# =============================================================
class RegisterModal(ui.Modal, title="📝 ลงทะเบียนข้อมูล Voice Chat"):
    xbox_name = ui.TextInput(
        label="ชื่อ Xbox Gamertag",
        placeholder="ตัวอย่าง: GamerPro1234",
        required=True
    )
    ic_name = ui.TextInput(
        label="ชื่อตัวละคร (IC)",
        placeholder="ตัวอย่าง: John_Doe",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_database[interaction.user.id] = {
            "xbox_name": self.xbox_name.value.strip(),
            "ic_name": self.ic_name.value.strip()
        }
        
        is_authorized = check_access(interaction.guild_id, interaction.user.id)
        msg = f"✅ **บันทึกข้อมูลสำเร็จ!**\n- **Xbox:** `{self.xbox_name.value.strip()}`\n- **ชื่อ IC:** `{self.ic_name.value.strip()}`\nกรุณาเข้าห้องเสียงเริ่มต้นเพื่อเตรียมพร้อมใช้งาน"
        
        if not is_authorized:
            await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(embed=create_thank_you_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)

class RegistrationView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="ลงทะเบียน / แก้ไขข้อมูล", emoji="📝", style=discord.ButtonStyle.success, custom_id="btn_register")
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RegisterModal())

    @ui.button(label="ตรวจสอบสถานะ", emoji="🔍", style=discord.ButtonStyle.primary, custom_id="btn_check_status")
    async def check_status_button(self, interaction: discord.Interaction, button: ui.Button):
        is_authorized = check_access(interaction.guild_id, interaction.user.id)
        user_data = user_database.get(interaction.user.id)
        
        if not user_data:
            msg = "❌ บัญชีของคุณยังไม่ได้ลงทะเบียนในระบบ"
        else:
            msg = f"✅ บัญชีของคุณเชื่อมต่อกับ Xbox: **{user_data['xbox_name']}** (IC: {user_data['ic_name']}) เรียบร้อยแล้ว"

        if not is_authorized:
            await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

class SOSAnswerView(ui.View):
    def __init__(self, player_name: str):
        super().__init__(timeout=None)
        self.player_name = player_name

    @ui.button(label="📞 ติดต่อผู้เล่น (ดึงเข้าสาย)", style=discord.ButtonStyle.danger, custom_id="btn_sos_answer")
    async def answer_sos(self, interaction: discord.Interaction, button: ui.Button):
        guild = interaction.guild
        staff_member = interaction.user

        if not isinstance(staff_member, discord.Member) or not staff_member.voice or not staff_member.voice.channel:
            await interaction.response.send_message("❌ คุณต้องเชื่อมต่อห้องเสียงใน Discord ก่อนกดรับสาย!", ephemeral=True)
            return

        if self.player_name in player_sessions:
            target_discord_id = player_sessions[self.player_name].get("discord_id")
            target_member = guild.get_member(target_discord_id) if target_discord_id else None

            if target_member and target_member.voice and target_member.voice.channel:
                try:
                    await target_member.move_to(staff_member.voice.channel)
                    await interaction.response.send_message(f"✅ ดึงตัว **{self.player_name}** เข้าห้องเสียงเรียบร้อยแล้ว!", ephemeral=True)
                except discord.HTTPException as e:
                    await interaction.response.send_message(f"❌ ไม่สามารถย้ายผู้เล่นได้: {e}", ephemeral=True)
            else:
                await interaction.response.send_message("❌ ผู้แจ้งไม่ได้เชื่อมต่อห้องเสียงใน Discord ในขณะนี้", ephemeral=True)
        else:
            await interaction.response.send_message("❌ ไม่พบข้อมูลการเชื่อมโยงบัญชีของผู้แจ้งในระบบ", ephemeral=True)

# =============================================================
# 🤖 BOT INITIALIZATION
# =============================================================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info(f"✅ บอท Python ทำงานแล้วในชื่อ: {bot.user}")
    
    bot.add_view(RegistrationView())
    
    try:
        synced = await bot.tree.sync()
        logging.info(f"✅ Sync Slash Commands แบบ Global สำเร็จ! ทั้งหมด {len(synced)} คำสั่ง")
    except Exception as e:
        logging.error(f"❌ เกิดข้อผิดพลาดในการ Sync คำสั่ง: {e}")

# =============================================================
# 💻 SLASH COMMANDS
# =============================================================
@bot.tree.command(name="setup-panel", description="สร้างแผงเมนูล็อกอินยืนยันตัวตน")
async def setup_panel(interaction: discord.Interaction):
    is_authorized = check_access(interaction.guild_id, interaction.user.id)

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
        await interaction.followup.send("❌ บอทไม่มีสิทธิ์ส่งข้อความในช่องนี้ โปรดตรวจสอบการอนุญาตสิทธิ์ Send Messages / Embed Links", ephemeral=True)
        return

    if not is_authorized:
        await interaction.followup.send(embed=create_unauthorized_warning_embed(), ephemeral=True)

@bot.tree.command(name="set-voice-category", description="กำหนดหมวดหมู่ (Category) สำหรับสร้างห้องเสียง Proximity")
@app_commands.describe(category="เลือกหมวดหมู่ที่ต้องการให้บอทใช้สร้างห้องเสียง")
async def set_voice_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    global default_category_id
    is_authorized = check_access(interaction.guild_id, interaction.user.id)

    await interaction.response.defer(ephemeral=True)
    default_category_id = category.id
    msg = f"✅ กำหนดหมวดหมู่ห้องเสียงเป็น: **{category.name}** เรียบร้อยแล้ว!"

    if not is_authorized:
        await interaction.followup.send(content=f"⚠️ {msg}", embed=create_unauthorized_warning_embed(), ephemeral=True)
    else:
        await interaction.followup.send(content=f"✅ {msg}", embed=create_thank_you_embed(), ephemeral=True)

@bot.tree.command(name="set-default-voice", description="กำหนดห้องเริ่มต้น (Lobby) สำหรับผู้เล่น")
@app_commands.describe(channel="เลือกห้องเสียงเริ่มต้น")
async def set_default_voice(interaction: discord.Interaction, channel: discord.VoiceChannel):
    global default_voice_channel_id, default_category_id
    is_authorized = check_access(interaction.guild_id, interaction.user.id)

    await interaction.response.defer(ephemeral=True)
    default_voice_channel_id = channel.id
    if channel.category_id:
        default_category_id = channel.category_id

    msg = f"✅ กำหนดห้องเสียงเริ่มต้นเป็น: **{channel.name}** เรียบร้อยแล้ว!"

    if not is_authorized:
        await interaction.followup.send(content=f"⚠️ {msg}", embed=create_unauthorized_warning_embed(), ephemeral=True)
    else:
        await interaction.followup.send(content=f"✅ {msg}", embed=create_thank_you_embed(), ephemeral=True)

@bot.tree.command(name="set-sos-channel", description="กำหนดช่องส่งการแจ้งเตือน SOS ฉุกเฉิน")
@app_commands.describe(channel="เลือกช่องข้อความรับการแจ้งเตือน SOS")
async def set_sos_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global sos_channel_id
    is_authorized = check_access(interaction.guild_id, interaction.user.id)

    await interaction.response.defer(ephemeral=True)
    sos_channel_id = channel.id
    msg = f"✅ ตั้งค่าห้องแจ้งเตือน SOS เป็น {channel.mention} เรียบร้อยแล้ว!"

    if not is_authorized:
        await interaction.followup.send(content=f"⚠️ {msg}", embed=create_unauthorized_warning_embed(), ephemeral=True)
    else:
        await interaction.followup.send(content=f"✅ {msg}", embed=create_thank_you_embed(), ephemeral=True)

# =============================================================
# 🔊 VOICE CHAT LOGIC ENGINE
# =============================================================
async def handle_player_join_game(guild_id: int, discord_id: int, xbox_name: str):
    if not default_voice_channel_id:
        return

    guild = bot.get_guild(guild_id)
    if not guild:
        return

    member = guild.get_member(discord_id)
    if not member or not member.voice:
        return

    category = guild.get_channel(default_category_id) if default_category_id else None

    try:
        personal_channel = await guild.create_voice_channel(
            name=f"🔊 {xbox_name}",
            category=category
        )
        await member.move_to(personal_channel)

        player_sessions[xbox_name] = {
            "discord_id": discord_id,
            "personal_channel_id": personal_channel.id,
            "current_channel_id": personal_channel.id,
            "pos": {"x": 0, "y": 0, "z": 0, "dim": "overworld"}
        }
    except discord.HTTPException as e:
        logging.error(f"Error handling player join: {e}")

async def handle_proximity_routing(guild_id: int, player_list: list):
    PROXIMITY_RADIUS = 15
    guild = bot.get_guild(guild_id)
    if not guild:
        return

    for p in player_list:
        xbox_name = p.get("xboxName")
        if xbox_name in player_sessions:
            player_sessions[xbox_name]["pos"] = {
                "x": p["x"], "y": p["y"], "z": p["z"], "dim": p["dim"]
            }

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

# -------------------------------------------------------------
# 🚨 SOS EMERGENCY ALERT HANDLER
# -------------------------------------------------------------
async def handle_sos_alert(data: dict):
    channel_target_id = sos_channel_id or int(data.get("sosChannelId", 0))
    channel = bot.get_channel(channel_target_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        return

    player_name = data.get("playerName", "Unknown")

    embed = discord.Embed(
        title="🚨 EMERGENCY CALL (แจ้งเหตุฉุกเฉิน)",
        color=discord.Color.red(),
        timestamp=datetime.now()
    )
    embed.add_field(name="👤 ผู้แจ้ง", value=f"{player_name} ({data.get('icName', player_name)})", inline=True)
    embed.add_field(name="📍 โลก / พิกัด", value=f"{data.get('dimension', 'Overworld')} | {data.get('location', 'N/A')}", inline=True)
    embed.add_field(name="⏰ เวลา", value=f"{data.get('time', 'N/A')}", inline=False)
    embed.set_footer(text="กดปุ่มด้านล่างเพื่อรับสายและดึงผู้เล่นเข้าห้องเสียงฉุกเฉิน")

    await channel.send(content="@everyone", embed=embed, view=SOSAnswerView(player_name=player_name))

# =============================================================
# 🌐 HTTP SERVER (สำหรับรับ HTTPS Request จาก Minecraft)
# =============================================================
routes = web.RouteTableDef()

@routes.post("/mc-update")
async def handle_mc_update(request):
    try:
        data = await request.json()
        msg_type = data.get("type")
        guild_id = int(data.get("guildId", CONFIG["ALLOWED_GUILDS"][0] if CONFIG["ALLOWED_GUILDS"] else 0))

        if msg_type == "PLAYER_JOIN":
            await handle_player_join_game(
                guild_id,
                int(data.get("discordId", 0)),
                data.get("xboxName")
            )
        elif msg_type == "POSITIONS_UPDATE":
            await handle_proximity_routing(
                guild_id,
                data.get("players", [])
            )
        elif msg_type == "SOS_EMERGENCY":
            await handle_sos_alert(data)

        return web.json_response({"status": "ok"}, status=200)
    except Exception as e:
        logging.error(f"❌ HTTP Processing Error: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400)

async def start_web_server():
    logging.info(f"📡 เปิด HTTP Web Server บนพอร์ต {CONFIG['PORT']}")
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", CONFIG["PORT"])
    await site.start()

# =============================================================
# 🚀 MAIN RUNNER
# =============================================================
async def main():
    await start_web_server()
    async with bot:
        await bot.start(CONFIG["BOT_TOKEN"])

if __name__ == "__main__":
    asyncio.run(main())
