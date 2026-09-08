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

# โหลดค่า Configuration ที่เคยบันทึกไว้
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Config Load Error]: {e}")
    return {}

# บันทึกค่า Configuration ลงไฟล์ JSON
def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Config Save Error]: {e}")

SERVER_CONFIG = load_config()

# =============================================================
# 🎛️ UI: DROPDOWN MENU FOR /set-default-voice
# =============================================================
class DefaultVoiceSetupView(discord.ui.View):
    def __init__(self, guild: discord.Guild):
        super().__init__(timeout=180)
        self.guild = guild
        guild_id_str = str(guild.id)
        
        # ดึงค่าเดิมถ้ามีอยู่แล้ว
        existing = SERVER_CONFIG.get(guild_id_str, {})
        self.selected_lobby_id = existing.get("LOBBY_CHANNEL_ID")
        self.selected_category_id = existing.get("CALL_CATEGORY_ID")

        # 1. Dropdown เลือกห้องเสียงเริ่มต้น
        voice_channels = [
            discord.SelectOption(
                label=ch.name, 
                value=str(ch.id),
                default=(ch.id == self.selected_lobby_id)
            )
            for ch in guild.voice_channels[:25]
        ]
        
        if voice_channels:
            self.lobby_select = discord.ui.Select(
                placeholder="1. เลือกห้องเสียงเริ่มต้น (Lobby Voice)...",
                options=voice_channels,
                custom_id="select_lobby",
                row=0
            )
            self.lobby_select.callback = self.on_lobby_select
            self.add_item(self.lobby_select)

        # 2. Dropdown เลือกหมวดหมู่
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
                placeholder="2. เลือกหมวดหมู่ที่จะสร้างห้องโทร (Call Category)...",
                options=categories,
                custom_id="select_category",
                row=1
            )
            self.category_select.callback = self.on_category_select
            self.add_item(self.category_select)

        # ปุ่มบันทึกการตั้งค่า
        self.save_button = discord.ui.Button(
            label="💾 บันทึกการตั้งค่า", 
            style=discord.ButtonStyle.success, 
            row=2, 
            disabled=not (self.selected_lobby_id and self.selected_category_id)
        )
        self.save_button.callback = self.on_save
        self.add_item(self.save_button)

    async def on_lobby_select(self, interaction: discord.Interaction):
        self.selected_lobby_id = int(self.lobby_select.values[0])
        await self.update_view_message(interaction)

    async def on_category_select(self, interaction: discord.Interaction):
        self.selected_category_id = int(self.category_select.values[0])
        await self.update_view_message(interaction)

    async def update_view_message(self, interaction: discord.Interaction):
        if self.selected_lobby_id and self.selected_category_id:
            self.save_button.disabled = False
        
        lobby_ch = self.guild.get_channel(self.selected_lobby_id)
        cat_ch = self.guild.get_channel(self.selected_category_id)
        
        lobby_name = lobby_ch.name if lobby_ch else "ยังไม่เลือก"
        category_name = cat_ch.name if cat_ch else "ยังไม่เลือก"

        await interaction.response.edit_message(
            content=f"⚙️ **ตั้งค่าระบบเสียง (Voice System Settings)**\n\n"
                    f"1️⃣ **ห้องเสียงเริ่มต้น:** `{lobby_name}`\n"
                    f"2️⃣ **หมวดหมู่ห้องโทร:** `{category_name}`\n\n"
                    f"*(เลือกให้ครบทั้ง 2 ข้อแล้วกดปุ่มบันทึกด้านล่าง)*",
            view=self
        )

    async def on_save(self, interaction: discord.Interaction):
        guild_id_str = str(interaction.guild_id)
        SERVER_CONFIG[guild_id_str] = {
            "LOBBY_CHANNEL_ID": self.selected_lobby_id,
            "CALL_CATEGORY_ID": self.selected_category_id
        }
        save_config(SERVER_CONFIG)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=f"✅ **บันทึกการตั้งค่าสำเร็จแล้ว!**\n\n"
                    f"🔊 **ห้องเริ่มต้น:** <#{self.selected_lobby_id}>\n"
                    f"📁 **หมวดหมู่สร้างห้อง:** <#{self.selected_category_id}>",
            view=self
        )

# Slash Command: /set-default-voice
@bot.tree.command(name="set-default-voice", description="ตั้งค่าห้องเสียงเริ่มต้นและหมวดหมู่สำหรับย้ายสายโทร")
@app_commands.checks.has_permissions(administrator=True)
async def set_default_voice(interaction: discord.Interaction):
    view = DefaultVoiceSetupView(interaction.guild)
    await interaction.response.send_message(
        content="⚙️ **ตั้งค่าระบบเสียง (Voice System Settings)**\nโปรดเลือก **ห้องเริ่มต้น** และ **หมวดหมู่** จากเมนูด้านล่าง:",
        view=view,
        ephemeral=True
    )

# =============================================================
# 🌐 REST API ENDPOINT (RECEIVE DATA FROM MINECRAFT ADDON)
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

        # 1. รับสายและย้ายเข้าห้องโทร
        if req_type == "START_PRIVATE_CALL":
            caller_name = data.get("caller")
            target_name = data.get("target")

            # สร้างห้องสายโทรย่อยภายใต้ Category ที่ระบุ
            voice_channel = await guild.create_voice_channel(
                name=f"📞-{caller_name} & {target_name}",
                category=category
            )

            # ค้นหาผู้เล่นตาม Display Name หรือ Username
            caller_member = discord.utils.find(lambda m: m.display_name.lower() == caller_name.lower() or m.name.lower() == caller_name.lower(), guild.members)
            target_member = discord.utils.find(lambda m: m.display_name.lower() == target_name.lower() or m.name.lower() == target_name.lower(), guild.members)

            if caller_member and caller_member.voice:
                await caller_member.move_to(voice_channel)

            if target_member and target_member.voice:
                await target_member.move_to(voice_channel)

            return web.json_response({"status": "ok", "channel_id": str(voice_channel.id)})

        # 2. วางสาย ลบห้อง และย้ายกลับห้องเริ่มต้น
        elif req_type == "END_CALL":
            player_name = data.get("player")
            member = discord.utils.find(lambda m: m.display_name.lower() == player_name.lower() or m.name.lower() == player_name.lower(), guild.members)

            if member and member.voice and member.voice.channel:
                current_channel = member.voice.channel
                lobby_id = config.get("LOBBY_CHANNEL_ID")
                lobby_channel = guild.get_channel(lobby_id)

                # หากอยู่ในห้องโทร ให้ย้ายสมาชิกทุกคนในห้องกลับไปห้องเริ่มต้น แล้วลบห้องโทร
                if current_channel.category_id == category_id and current_channel.name.startswith("📞-"):
                    for m in current_channel.members:
                        if lobby_channel:
                            await m.move_to(lobby_channel)
                    await current_channel.delete()

            return web.json_response({"status": "ok"})

        # 3. จัดการ Mute / Unmute
        elif req_type == "MUTE_TOGGLE":
            player_name = data.get("player")
            is_muted = data.get("isMuted", False)
            member = discord.utils.find(lambda m: m.display_name.lower() == player_name.lower() or m.name.lower() == player_name.lower(), guild.members)

            if member and member.voice:
                await member.edit(mute=is_muted)

            return web.json_response({"status": "ok"})

        # 4. SOS แจ้งเตือนฉุกเฉิน
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
    try:
        # บังคับ Sync คำสั่งสำหรับทุก Server ที่บอทอยู่
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
