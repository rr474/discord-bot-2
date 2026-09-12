import os
import logging
import discord
from discord.ext import commands
from aiohttp import web
import asyncio

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

xbox_to_discord = {}
pending_mc_commands = []
proximity_radius = 15
sos_channel_id = None
sos_role_id = None
default_category_id = None
default_lobby_channel_id = None  # เก็บ ID ห้อง Lobby เริ่มต้น

# -------------------------------------------------------------
# 🌐 AIOHTTP WEB SERVER (รับ Request จาก Minecraft)
# -------------------------------------------------------------
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

        if msg_type == "START_CALL" and guild:
            call_type = data.get("callType", "single")
            targets = data.get("targets", [])
            
            discord_members = []
            for x_name in targets:
                d_id = xbox_to_discord.get(x_name.lower())
                if d_id:
                    m = guild.get_member(d_id)
                    if m: discord_members.append(m)
            
            category = guild.get_channel(default_category_id) if default_category_id else None
            channel_name = f"📞 สายโทร: {targets[0]}" if call_type == "single" else f"👥 สายโทรกลุ่ม ({len(targets)} คน)"
            
            channel = await guild.create_voice_channel(name=channel_name, category=category)
            
            for member in discord_members:
                if member.voice:
                    try:
                        await member.move_to(channel)
                    except Exception as e:
                        logging.error(f"❌ Move Call Error: {e}")

        elif msg_type == "TOGGLE_MUTE" and guild:
            x_name = data.get("sender")
            is_muted = data.get("isMuted", False)
            d_id = xbox_to_discord.get(x_name.lower()) if x_name else None
            if d_id:
                member = guild.get_member(d_id)
                if member and member.voice:
                    try:
                        await member.edit(mute=is_muted)
                    except Exception as e:
                        logging.error(f"❌ Mute Error: {e}")

        elif msg_type == "SET_RADIUS":
            proximity_radius = data.get("radius", 15)

        elif msg_type == "SOS_EMERGENCY" and sos_channel_id:
            sos_channel = bot.get_channel(sos_channel_id)
            if sos_channel:
                embed = discord.Embed(
                    title="🚨 แจ้งเหตุฉุกเฉิน (SOS)",
                    description=f"ผู้เล่น `{data.get('playerName')}` ขอความช่วยเหลือ!",
                    color=discord.Color.red()
                )
                embed.add_field(name="📍 พิกัด", value=f"`{data.get('location')}`")
                embed.add_field(name="🌐 มิติ", value=f"`{data.get('dimension')}`")
                
                role_mention = f"<@&{sos_role_id}>" if sos_role_id else "@here"
                await sos_channel.send(content=f"🚨 {role_mention} **เกิดเหตุฉุกเฉินในเซิร์ฟเวอร์!**", embed=embed)

        cmds_to_send = list(pending_mc_commands)
        pending_mc_commands.clear()
        return web.json_response({"status": "ok", "commands": cmds_to_send}, status=200)

    except Exception as e:
        logging.error(f"❌ API Error: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400)

@routes.get("/")
async def index(request):
    return web.Response(text="Minecraft Discord Bot Server is Running!", status=200)

# -------------------------------------------------------------
# 📝 INTERACTIVE MODAL & VIEW (ระบบลงทะเบียนผ่านปุ่ม Panel)
# -------------------------------------------------------------
class RegisterModal(discord.ui.Modal, title="ลงทะเบียน / แก้ไขข้อมูล Xbox"):
    xbox_name = discord.ui.TextInput(
        label="ชื่อ Xbox Gamertag ของคุณ",
        placeholder="เช่น MyNameMinecraft",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        name = self.xbox_name.value.strip()
        xbox_to_discord[name.lower()] = interaction.user.id
        await interaction.response.send_message(f"✅ ผูกบัญชีสำเร็จ! ดิสคอร์ดของคุณเชื่อมกับ Xbox: **{name}** เรียบร้อยแล้ว", ephemeral=True)

class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ลงทะเบียน / แก้ไขข้อมูล", style=discord.ButtonStyle.green, custom_id="btn_register", emoji="📝")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())

    @discord.ui.button(label="ตรวจสอบสถานะ", style=discord.ButtonStyle.blurple, custom_id="btn_status", emoji="🔍")
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        registered_xbox = "ยังไม่ได้ลงทะเบียน"
        for x_name, d_id in xbox_to_discord.items():
            if d_id == user_id:
                registered_xbox = x_name
                break
        
        await interaction.response.send_message(f"🔍 **ข้อมูลบัญชีของคุณ:**\n• Discord: {interaction.user.mention}\n• Xbox ที่ผูกไว้: **{registered_xbox}**", ephemeral=True)

# -------------------------------------------------------------
# 🎛️ DISCORD SLASH COMMANDS
# -------------------------------------------------------------
@bot.tree.command(name="setup-panel", description="สร้าง Panel ปุ่มกดสำหรับลงทะเบียนและตรวจสอบสถานะ")
async def setup_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎙️ ระบบจัดการเสียงและบัญชี Minecraft",
        description="กดปุ่มด้านล่างเพื่อลงทะเบียนชื่อ Xbox หรือตรวจสอบสถานะการเชื่อมต่อของคุณ",
        color=discord.Color.blurple()
    )
    await interaction.channel.send(embed=embed, view=PanelView())
    await interaction.response.send_message("✅ สร้าง Panel เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="set-default-voice", description="ตั้งค่าห้อง Lobby เริ่มต้น")
async def set_default_voice(interaction: discord.Interaction, channel: discord.VoiceChannel):
    global default_lobby_channel_id
    default_lobby_channel_id = channel.id
    await interaction.response.send_message(f"✅ ตั้งค่าห้อง Lobby เริ่มต้นเป็น: **{channel.name}** เรียบร้อย", ephemeral=True)

@bot.tree.command(name="set-category", description="ตั้งค่าหมวดหมู่ (Category) ที่จะให้บอทสร้างห้องโทรศัพท์")
async def set_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    global default_category_id
    default_category_id = category.id
    await interaction.response.send_message(f"✅ ตั้งค่าหมวดหมู่ห้องโทรเป็น: **{category.name}** เรียบร้อย", ephemeral=True)

@bot.tree.command(name="set-sos-channel", description="ตั้งค่าช่องแจ้งเตือน SOS")
async def set_sos_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global sos_channel_id
    sos_channel_id = channel.id
    await interaction.response.send_message(f"✅ ตั้งค่าช่อง SOS เป็น: {channel.mention}", ephemeral=True)

@bot.tree.command(name="set-sos-role", description="ตั้งค่าเลือกยศที่จะให้แท็กตอนเกิดเหตุ SOS")
async def set_sos_role(interaction: discord.Interaction, role: discord.Role):
    global sos_role_id
    sos_role_id = role.id
    await interaction.response.send_message(f"✅ ตั้งค่าเลือกยศแจ้งเตือน SOS เป็น: {role.mention}", ephemeral=True)

# -------------------------------------------------------------
# 🗑️ AUTO DELETE VOICE CHANNEL
# -------------------------------------------------------------
@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel and before.channel != after.channel:
        channel = before.channel
        if (channel.name.startswith("📞") or channel.name.startswith("👥")) and len(channel.members) == 0:
            try:
                await asyncio.sleep(5)
                if len(channel.members) == 0:
                    await channel.delete()
            except Exception as e:
                logging.error(f"❌ Delete Channel Error: {e}")

@bot.event
async def on_ready():
    bot.add_view(PanelView())
    await bot.tree.sync()
    logging.info(f"✅ Logged in as {bot.user.name} and Commands Synced!")

@bot.command(name="register")
async def register_xbox(ctx, xbox_name: str):
    xbox_to_discord[xbox_name.lower()] = ctx.author.id
    await ctx.send(f"✅ ผูกบัญชีสำเร็จ! เชื่อมกับ Xbox: **{xbox_name}** แล้ว")

# -------------------------------------------------------------
# 🚀 START SERVER
# -------------------------------------------------------------
async def start_web_server():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    async with bot:
        await start_web_server()
        TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
