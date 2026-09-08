import os
import json
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from aiohttp import web

# =============================================================
# ⚙️ CONFIGURATION & BOT SETUP
# =============================================================
TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
PORT = int(os.getenv("PORT", 8080))
CONFIG_FILE = "voice_config.json"

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Config Load Error]: {e}")
    return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Config Save Error]: {e}")

SERVER_CONFIG = load_config()

# =============================================================
# 🎛️ UI: DROPDOWN MENU FOR /set-default-voice (STEP-BY-STEP)
# =============================================================
class DefaultVoiceSetupView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=180)
        self.guild = guild
        guild_id_str = str(guild.id)
        
        existing = SERVER_CONFIG.get(guild_id_str, {})
        self.selected_category_id = existing.get("CALL_CATEGORY_ID")
        self.selected_lobby_id = existing.get("LOBBY_CHANNEL_ID")

        # Step 1: Dropdown เลือกหมวดหมู่ก่อน
        categories = [
            discord.SelectOption(
                label=cat.name, 
                value=str(cat.id),
                default=(cat.id == self.selected_category_id)
            )
            for cat in guild.categories[:25]
        ]
        
        if categories:
            self.category_select = discord.ui.Select(
                placeholder="1. เลือกหมวดหมู่ (Category)...",
                options=categories,
                custom_id="select_category",
                row=0
            )
            self.category_select.callback = self.on_category_select
            self.add_item(self.category_select)

        # Step 2: Dropdown เลือกห้องเสียง (จะสร้างหลังจากเลือกหมวดหมู่แล้ว)
        self.lobby_select = None
        self.save_button = None

        # ถ้ามีหมวดหมู่เดิมอยู่แล้ว ให้โหลดห้องในหมวดหมู่นั้นมาแสดง
        if self.selected_category_id:
            self.build_lobby_dropdown(self.selected_category_id)

    def build_lobby_dropdown(self, category_id):
        category = self.guild.get_channel(category_id)
        if not category:
            return

        # ดึงเฉพาะห้องเสียงที่อยู่ใน Category นี้
        voice_channels = [
            discord.SelectOption(
                label=ch.name, 
                value=str(ch.id),
                default=(ch.id == self.selected_lobby_id)
            )
            for ch in category.voice_channels[:25]
        ]

        # ถ้าระบบเคยมี Dropdown ห้องเดิมให้ลบทิ้งก่อน
        if self.lobby_select:
            self.remove_item(self.lobby_select)

        if voice_channels:
            self.lobby_select = discord.ui.Select(
                placeholder="2. เลือกห้องเสียงเริ่มต้น (Lobby Voice)...",
                options=voice_channels,
                custom_id="select_lobby",
                row=1
            )
            self.lobby_select.callback = self.on_lobby_select
            self.add_item(self.lobby_select)

        # ปุ่มบันทึก
        if self.save_button:
            self.remove_item(self.save_button)

        self.save_button = discord.ui.Button(
            label="💾 บันทึกการตั้งค่า", 
            style=discord.ButtonStyle.success, 
            row=2, 
            disabled=not (self.selected_category_id and self.selected_lobby_id)
        )
        self.save_button.callback = self.on_save
        self.add_item(self.save_button)

    async def on_category_select(self, interaction: discord.Interaction):
        self.selected_category_id = int(self.category_select.values[0])
        self.selected_lobby_id = None # รีเซ็ตห้องเริ่มต้นเมื่อเปลี่ยนหมวดหมู่
        
        self.build_lobby_dropdown(self.selected_category_id)

        cat_ch = self.guild.get_channel(self.selected_category_id)
        cat_name = cat_ch.name if cat_ch else "ยังไม่เลือก"

        await interaction.response.edit_message(
            content=f"⚙️ **ตั้งค่าระบบเสียง (Voice System Settings)**\n\n"
                    f"1️⃣ **หมวดหมู่ที่เลือก:** `{cat_name}`\n"
                    f"2️⃣ **ห้องเสียงเริ่มต้น:** *(กรุณาเลือกจากเมนูด้านล่าง)*",
            view=self
        )

    async def on_lobby_select(self, interaction: discord.Interaction):
        self.selected_lobby_id = int(self.lobby_select.values[0])
        if self.save_button:
            self.save_button.disabled = False

        cat_ch = self.guild.get_channel(self.selected_category_id)
        lobby_ch = self.guild.get_channel(self.selected_lobby_id)

        await interaction.response.edit_message(
            content=f"⚙️ **ตั้งค่าระบบเสียง (Voice System Settings)**\n\n"
                    f"1️⃣ **หมวดหมู่ที่เลือก:** `{cat_ch.name if cat_ch else '-'}`\n"
                    f"2️⃣ **ห้องเสียงเริ่มต้น:** `{lobby_ch.name if lobby_ch else '-'}`\n\n"
                    f"*(กดปุ่มบันทึกการตั้งค่าด้านล่าง)*",
            view=self
        )

    async def on_save(self, interaction: discord.Interaction):
        guild_id_str = str(interaction.guild_id)
        SERVER_CONFIG[guild_id_str] = {
            "CALL_CATEGORY_ID": self.selected_category_id,
            "LOBBY_CHANNEL_ID": self.selected_lobby_id
        }
        save_config(SERVER_CONFIG)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=f"✅ **บันทึกการตั้งค่าสำเร็จแล้ว!**\n\n"
                    f"📁 **หมวดหมู่ห้องโทร:** <#{self.selected_category_id}>\n"
                    f"🔊 **ห้องเริ่มต้น:** <#{self.selected_lobby_id}>",
            view=self
        )

# =============================================================
# 📋 UI: PANEL VIEW FOR /setup-panel
# =============================================================
class PanelButtonsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ลงทะเบียน / แก้ไขข้อมูล", style=discord.ButtonStyle.success, emoji="📝", custom_id="panel_register")
    async def register_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📌 กรุณาเปลี่ยนชื่อใน Discord (Server Nickname) ให้ตรงกับชื่อ **Xbox Gamertag** ของคุณในเกมเพื่อเชื่อมต่อระบบเสียง", ephemeral=True)

    @discord.ui.button(label="ตรวจสอบสถานะ", style=discord.ButtonStyle.primary, emoji="🔍", custom_id="panel_status")
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_name = interaction.user.display_name
        await interaction.response.send_message(f"🔍 **ข้อมูลบัญชีของคุณ:**\n• ชื่อในดิสคอร์ด: `{user_name}`\n• สถานะห้องเสียง: {'อยู่ในห้องเสียง' if interaction.user.voice else 'ไม่อยู่ในห้องเสียง'}", ephemeral=True)

# =============================================================
# 📜 SLASH COMMANDS
# =============================================================
@bot.tree.command(name="set-default-voice", description="ตั้งค่าหมวดหมู่และห้องเสียงเริ่มต้นสำหรับย้ายสายโทร")
@app_commands.checks.has_permissions(administrator=True)
async def set_default_voice(interaction: discord.Interaction):
    view = DefaultVoiceSetupView(interaction.guild)
    await interaction.response.send_message(
        content="⚙️ **ตั้งค่าระบบเสียง (Voice System Settings)**\nโปรดเลือก **หมวดหมู่** ก่อน แล้วระบบจะแสดงห้องเสียงในหมวดหมู่นั้นให้เลือก:",
        view=view,
        ephemeral=True
    )

@bot.tree.command(name="setup-panel", description="สร้างพาเนลปุ่มกดลงทะเบียนและตรวจสอบสถานะ")
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🌐 ระบบเชื่อมต่อ Voice Chat ตัวละคร (IC)",
        description="กรุณาตั้งชื่อใน Discord Server ให้ตรงกับชื่อ Xbox Gamertag เพื่อใช้งานระบบสายโทรในเกม\n\n🔍 **ตรวจสอบข้อมูล:** สามารถกดปุ่มตรวจสอบสถานะได้ตลอดเวลา",
        color=discord.Color.blue()
    )
    embed.set_footer(text="⚙️ บริการระบบ Voice Chat | ปลอดภัย ไร้ดีเลย์")
    
    view = PanelButtonsView()
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ สร้างพาเนลสำเร็จเรียบร้อยแล้ว!", ephemeral=True)

# =============================================================
# 🌐 REST API ENDPOINT
# =============================================================
async def handle_api(request):
    try:
        data = await request.json()
        req_type = data.get("type")
        guild_id = data.get("guildId")

        if not guild_id:
            return web.json_response({"status": "error", "message": "Missing guildId"}, status=400)

        guild = bot.get_guild(int(guild_id))
        if not guild:
            return web.json_response({"status": "error", "message": "Guild not found"}, status=404)

        config = SERVER_CONFIG.get(str(guild_id))
        if not config:
            return web.json_response({"status": "error", "message": "Please set /set-default-voice first"}, status=400)

        category_id = config.get("CALL_CATEGORY_ID")
        category = guild.get_channel(category_id)

        if req_type == "START_PRIVATE_CALL":
            caller_name = data.get("caller")
            target_name = data.get("target")

            voice_channel = await guild.create_voice_channel(
                name=f"📞-{caller_name} & {target_name}",
                category=category
            )

            caller_member = discord.utils.find(lambda m: m.display_name.lower() == caller_name.lower() or m.name.lower() == caller_name.lower(), guild.members)
            target_member = discord.utils.find(lambda m: m.display_name.lower() == target_name.lower() or m.name.lower() == target_name.lower(), guild.members)

            if caller_member and caller_member.voice:
                await caller_member.move_to(voice_channel)

            if target_member and target_member.voice:
                await target_member.move_to(voice_channel)

            return web.json_response({"status": "ok", "channel_id": str(voice_channel.id)})

        elif req_type == "END_CALL":
            player_name = data.get("player")
            member = discord.utils.find(lambda m: m.display_name.lower() == player_name.lower() or m.name.lower() == player_name.lower(), guild.members)

            if member and member.voice and member.voice.channel:
                current_channel = member.voice.channel
                lobby_id = config.get("LOBBY_CHANNEL_ID")
                lobby_channel = guild.get_channel(lobby_id)

                if current_channel.category_id == category_id and current_channel.name.startswith("📞-"):
                    for m in current_channel.members:
                        if lobby_channel:
                            await m.move_to(lobby_channel)
                    await current_channel.delete()

            return web.json_response({"status": "ok"})

        elif req_type == "MUTE_TOGGLE":
            player_name = data.get("player")
            is_muted = data.get("isMuted", False)
            member = discord.utils.find(lambda m: m.display_name.lower() == player_name.lower() or m.name.lower() == player_name.lower(), guild.members)

            if member and member.voice:
                await member.edit(mute=is_muted)

            return web.json_response({"status": "ok"})

        elif req_type == "SOS_EMERGENCY":
            sos_channel_id = data.get("sosChannelId")
            sos_channel = guild.get_channel(int(sos_channel_id)) if sos_channel_id else None
            if sos_channel:
                embed = discord.Embed(title="🚨 แจ้งเหตุฉุกเฉิน (SOS)", color=discord.Color.red())
                embed.add_field(name="ผู้เล่น (IC)", value=data.get("icName"), inline=True)
                embed.add_field(name="Xbox Gamertag", value=data.get("playerName"), inline=True)
                embed.add_field(name="มิติ (Dimension)", value=data.get("dimension"), inline=True)
                embed.add_field(name="พิกัด (Location)", value=data.get("location"), inline=True)
                embed.add_field(name="เวลา", value=data.get("time"), inline=True)
                await sos_channel.send(content="@everyone 🚨 เกิดเหตุฉุกเฉิน!", embed=embed)

            return web.json_response({"status": "ok"})

    except Exception as e:
        print(f"[API Error]: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)

    return web.json_response({"status": "ignored"})

# =============================================================
# 🚀 BOT EVENTS & SERVER RUNNER
# =============================================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    bot.add_view(PanelButtonsView()) # ลงทะเบียน View ปุ่มกดถาวร
    try:
        synced = await bot.tree.sync()
        print(f"✅ Sync คำสั่งสำเร็จจำนวน {len(synced)} คำสั่ง")
    except Exception as e:
        print(f"❌ Sync คำสั่งล้มเหลว: {e}")

async def start_services():
    app = web.Application()
    app.router.add_post("/api", handle_api)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    
    await asyncio.gather(
        site.start(),
        bot.start(TOKEN)
    )

if __name__ == "__main__":
    asyncio.run(start_services())
