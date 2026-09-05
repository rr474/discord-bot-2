import os
import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import json
import math
import websockets
from datetime import datetime

# =============================================================
# ⚙️ CONFIGURATION
# =============================================================
def parse_int_list(env_var: str) -> list:
    val = os.getenv(env_var, "")
    if not val:
        return []
    return [int(x.strip()) for x in val.split(",") if x.strip().isdigit()]

CONFIG = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN", os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")),
    "PORT": int(os.getenv("PORT", 8080)),
    "ALLOWED_GUILDS": parse_int_list("ALLOWED_GUILDS"),
    "ALLOWED_USERS": parse_int_list("ALLOWED_USERS"),
    "SHOP_INFO": {
        "NAME": os.getenv("SHOP_NAME", "MUMGAME SHOP"),
        "LINK": os.getenv("SHOP_LINK", "https://discord.gg/your-shop-link")
    }
}

# =============================================================
# 🧠 GLOBAL STATE & DATABASE
# =============================================================
default_voice_channel_id = None
default_category_id = None

user_database = {}
player_sessions = {}

# =============================================================
# 🛡️ SECURITY & MESSAGES CHECKER
# =============================================================
def check_access(guild_id: int, user_id: int) -> bool:
    """เช็กว่าเซิร์ฟเวอร์หรือผู้ใช้นี้ได้รับอนุญาตหรือไม่"""
    is_guild_allowed = guild_id in CONFIG["ALLOWED_GUILDS"] if CONFIG["ALLOWED_GUILDS"] else False
    is_user_allowed = user_id in CONFIG["ALLOWED_USERS"] if CONFIG["ALLOWED_USERS"] else False
    return is_guild_allowed or is_user_allowed

def create_thank_you_embed():
    """ Embed ข้อความขอบคุณเมื่อ ID เซิร์ฟเวอร์ถูกต้อง """
    embed = discord.Embed(
        title="🎉 ขอบคุณที่อุดหนุนสินค้า!",
        color=discord.Color.green(),
        description=(
            f"ขอบคุณสำหรับการอุดหนุนระบบ Voice Chat จาก **{CONFIG['SHOP_INFO']['NAME']}** ❤️\n"
            "เซิร์ฟเวอร์ของคุณได้รับการเปิดใช้งานระบบอย่างสมบูรณ์แล้วครับ!"
        )
    )
    embed.set_footer(text=f"บริการโดย {CONFIG['SHOP_INFO']['NAME']}")
    return embed

def create_unauthorized_warning_embed():
    """ Embed แจ้งเตือนเมื่อ ID ไม่ถูก/ไม่อยู่ใน Whitelist (พิมพ์ทับได้) """
    embed = discord.Embed(
        title="⚠️ เตือนการใช้งานระบบ (Unauthorized Warning)",
        color=discord.Color.gold(),
        description=(
            "เซิร์ฟเวอร์ หรือ บัญชีผู้ใช้นี้ **ยังไม่ได้ทำการซื้อลิขสิทธิ์ระบบ Voice Chat อย่างถูกต้อง**\n"
            "*ระบบอนุญาตให้ใช้งานชั่วคราว/พิมพ์ทับได้ แต่โปรดติดต่อลงทะเบียนเพื่อใช้งานระยะยาว*\n\n"
            f"🛒 **สั่งซื้อได้ที่:** [{CONFIG['SHOP_INFO']['NAME']}]({CONFIG['SHOP_INFO']['LINK']})"
        )
    )
    embed.set_footer(text="ระบบแจ้งเตือนใช้งาน")
    return embed

# =============================================================
# 📱 UI COMPONENTS (Modal & Buttons)
# =============================================================
class RegisterModal(ui.Modal, title="ลงทะเบียนข้อมูล Voice Chat"):
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
            "xbox_name": self.xbox_name.value,
            "ic_name": self.ic_name.value
        }
        
        is_authorized = check_access(interaction.guild_id, interaction.user.id)
        msg = f"✅ **บันทึกข้อมูลสำเร็จ!**\n- **Xbox:** `{self.xbox_name.value}`\n- **ชื่อ IC:** `{self.ic_name.value}`\nกรุณาเข้าห้องเสียงเริ่มต้นเพื่อเตรียมพร้อมใช้งาน"
        
        if not is_authorized:
            await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(embed=create_thank_you_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)

class RegistrationView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="ลงทะเบียน / แก้ไขข้อมูล", style=discord.ButtonStyle.green, custom_id="btn_register")
    async def register_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RegisterModal())

    @ui.button(label="ตรวจสอบสถานะ", style=discord.ButtonStyle.primary, custom_id="btn_check_status")
    async def check_status_button(self, interaction: discord.Interaction, button: ui.Button):
        is_authorized = check_access(interaction.guild_id, interaction.user.id)
        user_data = user_database.get(interaction.user.id)
        
        if not user_data:
            msg = "❌ คุณยังไม่ได้ลงทะเบียนในระบบ"
        else:
            msg = f"🔍 **ข้อมูลของคุณ:**\n- **Xbox Gamertag:** `{user_data['xbox_name']}`\n- **ชื่อ IC:** `{user_data['ic_name']}`"

        if not is_authorized:
            await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(embed=create_thank_you_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)

# =============================================================
# 🤖 BOT INITIALIZATION
# =============================================================
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ บอท Python ทำงานแล้วในชื่อ: {bot.user}")
    bot.add_view(RegistrationView())
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Sync Slash Commands แบบ Global สำเร็จ! ทั้งหมด {len(synced)} คำสั่ง")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการ Sync คำสั่ง: {e}")

# =============================================================
# 💻 SLASH COMMANDS
# =============================================================
@bot.tree.command(name="setup-panel", description="สร้างข้อความแนะนำระบบลงทะเบียน Voice Chat")
async def setup_panel(interaction: discord.Interaction):
    is_authorized = check_access(interaction.guild_id, interaction.user.id)

    panel_embed = discord.Embed(
        title="ระบบสนทนาด้วยเสียง (Voice Chat)",
        color=discord.Color.blue(),
        description=(
            "คำแนะนำการใช้งานอย่างละเอียด:\n\n"
            "1. กดปุ่ม **'ลงทะเบียน / แก้ไขข้อมูล'** ด้านล่าง\n"
            "2. กรอกชื่อ Xbox และชื่อตัวละคร (IC) ของคุณ\n"
            "3. เมื่อลงทะเบียนเสร็จสิ้น ให้เข้าไปรอในห้องเสียงล็อบบี้ (Lobby)\n"
            "4. ระบบจะทำการย้ายห้องของคุณโดยอัตโนมัติเมื่อพบคุณเข้าเกม"
        )
    )
    
    # ส่ง Embed หลักลงช่องแชทพร้อม Response ตอบกลับทันทีเพื่อแก้ "แอปพลิเคชันไม่ตอบสนอง"
    await interaction.response.send_message(embed=panel_embed, view=RegistrationView())
    
    if not is_authorized:
        await interaction.followup.send(embed=create_unauthorized_warning_embed(), ephemeral=True)
    else:
        await interaction.followup.send(embed=create_thank_you_embed(), ephemeral=True)

@bot.tree.command(name="set-default-voice", description="กำหนดห้องเริ่มต้น (Lobby) สำหรับผู้เล่น")
@app_commands.describe(channel="เลือกห้องเสียงเริ่มต้น")
async def set_default_voice(interaction: discord.Interaction, channel: discord.VoiceChannel):
    global default_voice_channel_id, default_category_id
    is_authorized = check_access(interaction.guild_id, interaction.user.id)

    default_voice_channel_id = channel.id
    default_category_id = channel.category_id

    msg = f"✅ กำหนดห้องเสียงเริ่มต้นเป็น: **{channel.name}** เรียบร้อยแล้ว!"

    if not is_authorized:
        await interaction.response.send_message(
            content=f"⚠️ {msg}",
            embed=create_unauthorized_warning_embed(),
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            content=f"✅ {msg}",
            embed=create_thank_you_embed(),
            ephemeral=True
        )

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

async def handle_sos_alert(data: dict):
    channel_id = int(data.get("sosChannelId", 0))
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    embed = discord.Embed(
        title="🚨 EMERGENCY CALL (แจ้งเหตุฉุกเฉิน)",
        color=discord.Color.red(),
        timestamp=datetime.now()
    )
    embed.add_field(name="👤 ผู้แจ้ง", value=f"{data.get('playerName')} ({data.get('icName')})", inline=True)
    embed.add_field(name="📍 โลก / พิกัด", value=f"{data.get('dimension')} | {data.get('location')}", inline=True)
    embed.add_field(name="⏰ เวลา", value=f"{data.get('time')}", inline=False)

    await channel.send(embed=embed)

# =============================================================
# 🌐 WEBSOCKET SERVER
# =============================================================
async def ws_handler(websocket):
    async for message in websocket:
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "PLAYER_JOIN":
                await handle_player_join_game(
                    int(data["guildId"]),
                    int(data["discordId"]),
                    data["xboxName"]
                )
            elif msg_type == "POSITIONS_UPDATE":
                await handle_proximity_routing(
                    int(data["guildId"]),
                    data["players"]
                )
            elif msg_type == "SOS_EMERGENCY":
                await handle_sos_alert(data)

        except Exception as e:
            print(f"❌ WebSocket Processing Error: {e}")

async def start_websocket():
    print(f"📡 เปิด WebSocket Server บนพอร์ต {CONFIG['PORT']}")
    async with websockets.serve(ws_handler, "0.0.0.0", CONFIG["PORT"]):
        await asyncio.Future()

# =============================================================
# 🚀 MAIN RUNNER
# =============================================================
async def main():
    async with bot:
        await asyncio.gather(
            bot.start(CONFIG["BOT_TOKEN"]),
            start_websocket()
        )

if __name__ == "__main__":
    asyncio.run(main())
