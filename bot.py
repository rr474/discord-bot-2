import os
import json
import math
import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands, ui
from discord.ext import commands
import websockets

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

user_database = {}      # discord_id -> {"xbox_name", "ic_name"}
player_sessions = {}    # xbox_name -> {"discord_id", "personal_channel_id", "current_channel_id", "pos"}

# =============================================================
# 🔍 HELPER FUNCTION: MATCH XBOX NAME WITH DISCORD NICKNAME
# =============================================================
def get_member_by_xbox_name(guild: discord.Guild, xbox_name: str) -> discord.Member:
    """ ค้นหาสมาชิกใน Discord ที่มี Nickname หรือ Display Name ตรงกับชื่อ Xbox """
    search_name = xbox_name.strip().lower()
    for member in guild.members:
        nick = (member.nick or member.display_name or member.name).strip().lower()
        if nick == search_name:
            return member
    return None

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
        label="ชื่อ Xbox Gamertag (ชื่อในเกม)",
        placeholder="ตัวอย่าง: GamerPro1234",
        required=True
    )
    ic_name = ui.TextInput(
        label="ชื่อตัวละคร (IC)",
        placeholder="ตัวอย่าง: John_Doe",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        xbox_val = self.xbox_name.value.strip()
        ic_val = self.ic_name.value.strip()
        member = interaction.user
        guild = interaction.guild

        user_database[member.id] = {
            "xbox_name": xbox_val,
            "ic_name": ic_val
        }

        # -------------------------------------------------------------
        # 🏷️ ระบบเปลี่ยนชื่อใน Discord เป็นชื่อ Xbox
        # -------------------------------------------------------------
        nick_change_msg = ""
        if guild:
            if member == guild.owner:
                nick_change_msg = "\n⚠️ **หมายเหตุ:** คุณเป็นเจ้าของเซิร์ฟเวอร์ บอทไม่สามารถเปลี่ยนชื่อให้ได้ กรุณาตั้งชื่อเล่นใน Discord เป็นชื่อ Xbox ด้วยตนเองครับ"
            elif member.top_role >= guild.me.top_role:
                nick_change_msg = f"\n⚠️ **หมายเหตุ:** คุณมียศสูงกว่าหรือเท่ายศของบอท บอทจึงเปลี่ยนชื่อให้ไม่ได้ กรุณาตั้งชื่อเล่นใน Discord เป็น `{xbox_val}` ด้วยตนเองครับ"
            else:
                try:
                    await member.edit(nick=xbox_val)
                    nick_change_msg = f"\n✅ **เปลี่ยนชื่อ Discord เป็น:** `{xbox_val}` เรียบร้อยแล้ว!"
                except discord.Forbidden:
                    nick_change_msg = f"\n⚠️ **หมายเหตุ:** บอทขาดสิทธิ์ `Manage Nicknames` กรุณาเปลี่ยนชื่อใน Discord เป็น `{xbox_val}` ด้วยตนเองครับ"
                except Exception as e:
                    logging.error(f"Error changing nickname: {e}")

        is_authorized = check_access(interaction.guild_id, member.id)
        msg = f"✅ **บันทึกข้อมูลสำเร็จ!**\n- **Xbox Gamertag:** `{xbox_val}`\n- **ชื่อ IC:** `{ic_val}`{nick_change_msg}\n\n👉 กรุณาเข้าห้องเสียงเริ่มต้นเพื่อเตรียมพร้อมใช้งาน"
        
        if not is_authorized:
            await interaction.followup.send(embed=create_unauthorized_warning_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.followup.send(embed=create_thank_you_embed(), ephemeral=True)
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
            msg = f"❌ คุณยังไม่ได้ลงทะเบียนในระบบ\n*(โปรดตั้งชื่อเล่นใน Discord ให้ตรงกับชื่อ Xbox Gamertag: `{interaction.user.display_name}`)*"
        else:
            msg = f"🔍 **ข้อมูลของคุณ:**\n- **Xbox Gamertag:** `{user_data['xbox_name']}`\n- **ชื่อ IC:** `{user_data['ic_name']}`"

        if not is_authorized:
            await interaction.response.send_message(embed=create_unauthorized_warning_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(embed=create_thank_you_embed(), ephemeral=True)
            await interaction.followup.send(msg, ephemeral=True)

# 🚨 SOS Answer View
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

        target_member = get_member_by_xbox_name(guild, self.player_name)
        if target_member and target_member.voice and target_member.voice.channel:
            try:
                await target_member.move_to(staff_member.voice.channel)
                await interaction.response.send_message(f"✅ ดึงตัว **{self.player_name}** เข้าห้องเสียงเรียบร้อยแล้ว!", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.response.send_message(f"❌ ไม่สามารถย้ายผู้เล่นได้: {e}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ ผู้แจ้งไม่ได้เชื่อมต่อห้องเสียงใน Discord ในขณะนี้", ephemeral=True)

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
@bot.tree.command(name="setup-panel", description="สร้างข้อความแนะนำระบบลงทะเบียน Voice Chat")
async def setup_panel(interaction: discord.Interaction):
    is_authorized = check_access(interaction.guild_id, interaction.user.id)

    panel_embed = discord.Embed(
        title="🎙️┆ ระบบสนทนาด้วยเสียง (VOICE CHAT SYSTEM)",
        description=(
            "ยินดีต้อนรับสู่ระบบ Voice Chat อัตโนมัติ! 🌟\n"
            "โปรดทำตามขั้นตอนด้านล่างเพื่อลงทะเบียนและเริ่มใช้งานระบบเสียงภายในเกม\n"
            "──────────────────────────────────"
        ),
        color=discord.Color.from_rgb(88, 101, 242)
    )

    panel_embed.add_field(
        name="📝 **ขั้นตอนที่ 1 : ลงทะเบียนข้อมูล**",
        value="> กดปุ่ม `📝 ลงทะเบียน / แก้ไขข้อมูล` ด้านล่าง\n> กรอกชื่อ **Xbox Gamertag** และ **ชื่อตัวละคร (IC)**\n> ระบบจะเปลี่ยนชื่อเล่นใน Discord ของคุณเป็นชื่อ Xbox อัตโนมัติ",
        inline=False
    )
    
    panel_embed.add_field(
        name="🔊 **ขั้นตอนที่ 2 : เข้าห้องเสียงเริ่มต้น**",
        value="> เข้าไปรอในห้องเสียง **Lobby (ห้องเริ่มต้น)** ที่ทางเซิร์ฟเวอร์กำหนดไว้",
        inline=False
    )

    panel_embed.add_field(
        name="🎮 **ขั้นตอนที่ 3 : เข้าเล่นเกม**",
        value="> เมื่อเข้าเกม ระบบจะทำการ **ดึงคุณไปยังห้องเสียงส่วนตัว** และ **ปรับระดับเสียงตามระยะใกล้-ไกล** โดยอัตโนมัติ!",
        inline=False
    )

    panel_embed.add_field(
        name="🔍 **ตรวจสอบข้อมูล**",
        value="> สามารถกดปุ่ม `🔍 ตรวจสอบสถานะ` ได้ตลอดเวลาเพื่อดูข้อมูลที่ลงทะเบียนไว้",
        inline=False
    )

    panel_embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3081/3081331.png")
    panel_embed.set_footer(
        text=f"⚙️ บริการระบบ Voice Chat โดย {CONFIG['SHOP_INFO']['NAME']} | ปลอดภัย ไร้ดีเลย์",
        icon_url="https://cdn-icons-png.flaticon.com/512/1067/1067357.png"
    )

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
        logging.warning("⚠️ ยังไม่ได้ตั้งค่าห้อง Default Voice Channel (/set-default-voice)")
        return

    guild = bot.get_guild(guild_id)
    if not guild:
        logging.warning(f"⚠️ ไม่พบ Guild ID: {guild_id}")
        return

    # 1. ค้นหา Member จากชื่อ Discord/Nickname (ตรงกับชื่อ Xbox)
    member = get_member_by_xbox_name(guild, xbox_name)

    # หากหาด้วยชื่อไม่พบ ให้ลองหาจาก discord_id หรือ user_database
    if not member and discord_id and discord_id != 0:
        member = guild.get_member(discord_id)

    if not member:
        logging.warning(f"❌ ไม่พบผู้ใช้ใน Discord ที่มีชื่อตรงกับ Xbox: '{xbox_name}'")
        return

    # 2. ตรวจสอบว่าเชื่อมต่อห้องเสียงอยู่หรือไม่
    if not member.voice or not member.voice.channel:
        logging.warning(f"⚠️ ผู้เล่น {xbox_name} ({member.display_name}) ต้องกดเข้าห้องเสียง Lobby ใน Discord ก่อน!")
        return

    category = guild.get_channel(default_category_id) if default_category_id else None

    try:
        # 3. สร้างหรือดึงห้องเสียงส่วนตัวที่มีอยู่เดิม
        personal_channel = None
        if xbox_name in player_sessions and player_sessions[xbox_name].get("personal_channel_id"):
            existing_ch_id = player_sessions[xbox_name]["personal_channel_id"]
            personal_channel = guild.get_channel(existing_ch_id)

        if not personal_channel:
            personal_channel = await guild.create_voice_channel(
                name=f"🔊 {xbox_name}",
                category=category
            )

        # 4. ย้ายผู้เล่นไปยังห้องส่วนตัว
        await member.move_to(personal_channel)
        logging.info(f"✅ ย้ายผู้เล่น {xbox_name} ไปยังห้อง {personal_channel.name} สำเร็จ!")

        # 5. บันทึก Session
        player_sessions[xbox_name] = {
            "discord_id": member.id,
            "personal_channel_id": personal_channel.id,
            "current_channel_id": personal_channel.id,
            "pos": {"x": 0, "y": 0, "z": 0, "dim": "overworld"}
        }
    except discord.Forbidden:
        logging.error("❌ บอทไม่มีสิทธิ์ (Permissions) ในการสร้างห้องหรือย้ายผู้เล่น!")
    except discord.HTTPException as e:
        logging.error(f"❌ เกิดข้อผิดพลาดในการสร้าง/ย้ายห้อง: {e}")

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
# 📞 PHONE CALL AUTOMATION HANDLER
# -------------------------------------------------------------
async def handle_phone_call(data: dict):
    msg_type = data.get("type")
    guild_id = int(data.get("guildId", 0))
    guild = bot.get_guild(guild_id)
    if not guild:
        return

    # 1. สายโทรศัพท์ส่วนตัว -> สร้างห้องเสียงลับเฉพาะ 2 คน
    if msg_type == "START_PRIVATE_CALL":
        caller_name = data.get("caller")
        target_name = data.get("target")

        try:
            call_channel = await guild.create_voice_channel(
                name=f"📞 สายโทร: {caller_name} ↔ {target_name}"
            )

            for name in [caller_name, target_name]:
                member = get_member_by_xbox_name(guild, name)
                if member and member.voice and member.voice.channel:
                    await member.move_to(call_channel)
        except discord.HTTPException as e:
            logging.error(f"Error creating private call channel: {e}")

    # 2. วางสาย -> ลบห้องสายโทรศัพท์ & ย้ายผู้เล่นกลับห้องเดิม
    elif msg_type == "END_CALL":
        player_name = data.get("player")
        member = get_member_by_xbox_name(guild, player_name)
        
        if member and member.voice and member.voice.channel and member.voice.channel.name.startswith("📞"):
            channel = member.voice.channel
            personal_ch_id = player_sessions.get(player_name, {}).get("personal_channel_id")
            
            if personal_ch_id:
                personal_ch = guild.get_channel(personal_ch_id)
                if isinstance(personal_ch, discord.VoiceChannel):
                    try:
                        await member.move_to(personal_ch)
                    except discord.HTTPException:
                        pass

            if len(channel.members) <= 1:
                try:
                    await channel.delete()
                except discord.HTTPException as e:
                    logging.error(f"Error deleting call channel: {e}")

    # 3. สลับเปิด/ปิดไมค์
    elif msg_type == "MUTE_TOGGLE":
        player_name = data.get("player")
        is_muted = data.get("isMuted", False)
        member = get_member_by_xbox_name(guild, player_name)
        
        if member:
            try:
                await member.edit(mute=is_muted)
            except discord.HTTPException as e:
                logging.error(f"Error toggling mute: {e}")

# -------------------------------------------------------------
# 🚨 SOS EMERGENCY ALERT HANDLER
# -------------------------------------------------------------
async def handle_sos_alert(data: dict):
    channel_id = int(data.get("sosChannelId", 0))
    channel = bot.get_channel(channel_id)
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

    await channel.send(embed=embed, view=SOSAnswerView(player_name=player_name))

# =============================================================
# 🌐 WEBSOCKET SERVER
# =============================================================
async def ws_handler(websocket):
    logging.info("🌐 Minecraft Client / Script API Connected via WebSocket")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "PLAYER_JOIN":
                    await handle_player_join_game(
                        int(data.get("guildId", 0)),
                        int(data.get("discordId", 0)),
                        data.get("xboxName", "")
                    )
                elif msg_type == "POSITIONS_UPDATE":
                    await handle_proximity_routing(
                        int(data.get("guildId", 0)),
                        data.get("players", [])
                    )
                elif msg_type in ["START_PRIVATE_CALL", "END_CALL", "MUTE_TOGGLE"]:
                    await handle_phone_call(data)
                elif msg_type == "SOS_EMERGENCY":
                    await handle_sos_alert(data)

            except json.JSONDecodeError:
                logging.error("Received invalid JSON payload")
            except Exception as e:
                logging.error(f"❌ WebSocket Processing Error: {e}")
    except websockets.exceptions.ConnectionClosed:
        logging.info("❌ Minecraft Client Disconnected")

async def start_websocket():
    logging.info(f"📡 เปิด WebSocket Server บนพอร์ต {CONFIG['PORT']}")
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
