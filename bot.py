import os
import asyncio
import discord
from discord.ext import commands
from discord import app_commands, Embed, ButtonStyle
from discord.ui import Button, View
from aiohttp import web

# --- CONFIG BOT ---
TOKEN = os.environ.get("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ตัวแปรเก็บข้อมูลระบบ
CONFIG = {
    "sos_channel_id": None,
    "default_voice_channel_id": None,
    "voice_category_id": None
}

player_data = {} # เก็บข้อมูลการเชื่อมต่อผู้เล่น


# --- EMBED และ VIEW ล็อกอินเดิม ---
class LoginPanelViews(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ลงทะเบียน / แก้ไขข้อมูล", style=ButtonStyle.success, emoji="📝", custom_id="login_register_btn")
    async def register_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("กรุณากรอกชื่อ Xbox / Minecraft ID ของคุณในเกม:", ephemeral=True)

    @discord.ui.button(label="ตรวจสอบสถานะ", style=ButtonStyle.primary, emoji="🔍", custom_id="login_status_btn")
    async def status_button(self, interaction: discord.Interaction, button: Button):
        user_id = str(interaction.user.id)
        if user_id in player_data:
            xbox_name = player_data[user_id]
            await interaction.response.send_message(f"✅ บัญชีของคุณเชื่อมต่อกับ Xbox: **{xbox_name}** เรียบร้อยแล้ว", ephemeral=True)
        else:
            await interaction.response.send_message("❌ บัญชีของคุณยังไม่ได้ลงทะเบียนในระบบ", ephemeral=True)


def get_login_embed():
    embed = Embed(
        title="📱 ระบบยืนยันตัวตน Minecraft Proximity Voice",
        description="กรุณากดปุ่มด้านล่างเพื่อเชื่อมต่อบัญชี Discord ของคุณเข้ากับชื่อในเกม Minecraft Bedrock\n\n"
                    "• **ลงทะเบียน / แก้ไขข้อมูล:** เชื่อมชื่อ Xbox Gamertag\n"
                    "• **ตรวจสอบสถานะ:** เช็กว่าบัญชีของคุณเชื่อมต่อสำเร็จหรือไม่",
        color=0x2b2d31
    )
    embed.set_footer(text="Memory Shop | ปลอดภัย รวดเร็ว")
    return embed


# --- SLASH COMMANDS ---
@bot.tree.command(name="setup-panel", description="สร้างแผงเมนูล็อกอินยืนยันตัวตนเดิม")
async def setup_panel(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = get_login_embed()
    view = LoginPanelViews()
    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="set-voice-category", description="เลือกหมวดหมู่ (Category) สำหรับสร้างห้องเสียง Proximity")
@app_commands.describe(category="เลือกหมวดหมู่ที่ต้องการให้บอทสร้างห้องเสียง")
async def set_voice_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    await interaction.response.defer(ephemeral=True)
    CONFIG["voice_category_id"] = category.id
    await interaction.followup.send(f"✅ ตั้งค่าหมวดหมู่ห้องเสียงเป็น: **{category.name}** เรียบร้อยแล้ว", ephemeral=True)


@bot.tree.command(name="set-default-voice", description="ตั้งค่าห้องเสียงหลัก")
@app_commands.describe(channel="เลือกห้องเสียงหลัก")
async def set_default_voice(interaction: discord.Interaction, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True)
    CONFIG["default_voice_channel_id"] = channel.id
    await interaction.followup.send(f"✅ ตั้งค่าห้องเสียงหลักเป็น: **{channel.name}** เรียบร้อยแล้ว", ephemeral=True)


@bot.tree.command(name="set-sos-channel", description="ตั้งค่าช่องแจ้งเตือน SOS")
@app_commands.describe(channel="เลือกช่องข้อความสำหรับรับการแจ้งเตือน SOS")
async def set_sos_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    CONFIG["sos_channel_id"] = channel.id
    await interaction.followup.send(f"✅ ตั้งค่าช่องแจ้งเตือน SOS เป็น: **{channel.name}** เรียบร้อยแล้ว", ephemeral=True)


# --- HTTP SERVER รับข้อมูลจาก MINECRAFT ---
routes = web.RouteTableDef()

@routes.post("/mc-update")
async def handle_mc_update(request):
    try:
        data = await request.json()
        msg_type = data.get("type")

        if msg_type == "SOS_EMERGENCY" and CONFIG["sos_channel_id"]:
            channel = bot.get_channel(CONFIG["sos_channel_id"])
            if channel:
                player_name = data.get("playerName", "Unknown")
                location = data.get("location", "Unknown")
                dim = data.get("dimension", "Overworld")
                
                sos_embed = Embed(
                    title="🚨 แจ้งเหตุฉุกเฉิน (SOS)",
                    description=f"**ผู้เล่น:** {player_name}\n**มิติ:** {dim}\n**พิกัด:** `{location}`",
                    color=0xff0000
                )
                asyncio.run_coroutine_threadsafe(channel.send(embed=sos_embed), bot.loop)

        return web.json_response({"status": "ok"}, status=200)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=400)


async def start_web_server():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    bot.add_view(LoginPanelViews()) # โหลดปุ่มล็อกอินค้างไว้ให้ใช้งานได้ตลอด
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
        
    bot.loop.create_task(start_web_server())


if __name__ == "__main__":
    bot.run(TOKEN)
