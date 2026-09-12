import os
import logging
import discord
from discord.ext import commands
from aiohttp import web
import asyncio
import math

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

registered_users = {}
pending_mc_commands = []
proximity_radius = 15
sos_channel_id = None
sos_role_id = None
default_category_id = None
default_lobby_channel_id = None

# เก็บสถานะช่องเสียงของผู้เล่น {discord_id: voice_channel_id}
player_active_channels = {}

routes = web.RouteTableDef()

@routes.post("/mc-update")
async def handle_mc_update(request):
    global pending_mc_commands, proximity_radius, sos_channel_id, sos_role_id, default_category_id, default_lobby_channel_id
    try:
        data = await request.json()
        msg_type = data.get("type")
        
        guild_id = int(data.get("guildId", 0))
        if not guild_id and bot.guilds:
            guild_id = bot.guilds[0].id

        guild = bot.get_guild(guild_id) if guild_id else None

        # ระบบคำนวณพิกัดเรียลไทม์ (Lobby -> สร้างห้องเดี่ยว หรือ รวมห้องใกล้เพื่อน)
        if msg_type == "POSITIONS_UPDATE" and guild:
            active_players = data.get("players", [])
            player_coords = {}
            
            for p in active_players:
                xbox_name = p.get("xboxName")
                user_info = registered_users.get(xbox_name.lower())
                if user_info:
                    d_id = user_info["discord_id"]
                    member = guild.get_member(d_id)
                    if member and member.voice:
                        player_coords[d_id] = {
                            "xbox_name": xbox_name,
                            "ic_name": user_info["ic_name"],
                            "member": member,
                            "x": p.get("x"),
                            "y": p.get("y"),
                            "z": p.get("z"),
                            "dimension": p.get("dimension")
                        }

            processed_d_ids = set()
            category = guild.get_channel(default_category_id) if default_category_id else None
            lobby_channel = guild.get_channel(default_lobby_channel_id) if default_lobby_channel_id else None

            for d_id, info in player_coords.items():
                if d_id in processed_d_ids:
                    continue

                group = [info]
                processed_d_ids.add(d_id)

                for other_d_id, other_info in player_coords.items():
                    if other_d_id in processed_d_ids:
                        continue
                    
                    if info["dimension"] == other_info["dimension"]:
                        dist = math.sqrt(
                            (info["x"] - other_info["x"])**2 +
                            (info["y"] - other_info["y"])**2 +
                            (info["z"] - other_info["z"])**2
                        )
                        if dist <= proximity_radius:
                            group.append(other_info)
                            processed_d_ids.add(other_d_id)

                # เคสที่ 1: อยู่คนเดียว ไม่ได้ใกล้ใคร -> ส่งไปห้อง Lobby ก่อน หรือ สร้างห้องส่วนตัวให้เล่นคนเดียว
                if len(group) == 1:
                    target_member = group[0]["member"]
                    target_ic = group[0]["ic_name"]
                    
                    current_chan = player_active_channels.get(target_member.id)
                    
                    # ถ้ายังไม่มีห้องส่วนตัว หรือไม่ได้อยู่ห้องส่วนตัว ให้สร้างห้องส่วนตัวให้
                    if not current_chan or (target_member.voice.channel and target_member.voice.channel.id != current_chan):
                        try:
                            # ถ้าตั้งค่าห้อง Lobby ไว้ อาจจะดึงเข้า Lobby ก่อน หรือสร้างห้องส่วนตัวเดี่ยวๆ ทันที
                            if lobby_channel and (not target_member.voice.channel or target_member.voice.channel.id != lobby_channel.id):
                                # เช็คว่าเพิ่งเข้าเกมไหม ถ้าเพิ่งเข้า ให้ไปห้อง Lobby รอ
                                pass
                            
                            new_chan = await guild.create_voice_channel(name=f"🎮 เล่นคนเดียว: {target_ic}", category=category)
                            await target_member.move_to(new_chan)
                            player_active_channels[target_member.id] = new_chan.id
                        except Exception as e:
                            logging.error(f"❌ Move Single Error: {e}")
                
                # เคสที่ 2: เดินไปใกล้เพื่อน -> ดึงมารวมห้องเดียวกัน
                else:
                    channel_name = f"🔊 ใกล้ชิด: {group[0]['ic_name']} และเพื่อน ({len(group)})"
                    
                    try:
                        new_chan = await guild.create_voice_channel(name=channel_name, category=category)
                        for g in group:
                            await g["member"].move_to(new_chan)
                            player_active_channels[g["member"].id] = new_chan.id
                    except Exception as e:
                        logging.error(f"❌ Move Proximity Group Error: {e}")

            # เคลียร์คนที่ออกจากเกม
            current_active_d_ids = set(player_coords.keys())
            for d_id in list(player_active_channels.keys()):
                if d_id not in current_active_d_ids:
                    chan_id = player_active_channels.pop(d_id, None)
                    if chan_id:
                        channel = guild.get_channel(chan_id)
                        if channel:
                            try:
                                await channel.delete()
                            except Exception:
                                pass

        elif msg_type == "START_CALL" and guild:
            call_type = data.get("callType", "single")
            targets = data.get("targets", [])
            
            discord_members = []
            for xbox_name in targets:
                u_info = registered_users.get(xbox_name.lower())
                if u_info:
                    d_id = u_info["discord_id"]
                    m = guild.get_member(d_id)
                    if m and m.voice:
                        discord_members.append(m)
            
            if discord_members:
                category = guild.get_channel(default_category_id) if default_category_id else None
                channel_name = f"📞 สายโทร: {targets[0]}" if call_type == "single" else f"👥 สายโทรกลุ่ม ({len(targets)} คน)"
                
                new_channel = await guild.create_voice_channel(name=channel_name, category=category)
                for member in discord_members:
                    try:
                        await member.move_to(new_channel)
                        player_active_channels[member.id] = new_channel.id
                    except Exception as e:
                        logging.error(f"❌ Move Call Error: {e}")

        elif msg_type == "SET_RADIUS":
            proximity_radius = data.get("radius", 15)

        elif msg_type == "SOS_EMERGENCY" and sos_channel_id:
            sos_channel = bot.get_channel(sos_channel_id)
            if sos_channel:
                embed = discord.Embed(
                    title="🚨 แจ้งเหตุฉุกเฉิน (SOS)",
                    description=f"ผู้เล่น IC: `{data.get('playerName')}` ขอความช่วยเหลือ!",
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

class RegisterModal(discord.ui.Modal, title="ลงทะเบียนข้อมูลผู้เล่น"):
    xbox_name = discord.ui.TextInput(
        label="1. ชื่อ Xbox Gamertag",
        placeholder="เช่น MyXboxName",
        required=True,
        max_length=50
    )
    ic_name = discord.ui.TextInput(
        label="2. ชื่อ IC (In-Character)",
        placeholder="เช่น สมชาย ซ่าสะท้านโลกันตร์",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        x_name = self.xbox_name.value.strip().lower()
        i_name = self.ic_name.value.strip()
        
        registered_users[x_name] = {
            "discord_id": interaction.user.id,
            "ic_name": i_name
        }
        
        embed = discord.Embed(
            title="✅ ลงทะเบียนสำเร็จ!",
            description=f"• **Xbox:** `{self.xbox_name.value}`\n• **ชื่อ IC:** `{i_name}`\n• **Discord:** {interaction.user.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ลงทะเบียนข้อมูล (Xbox & IC)", style=discord.ButtonStyle.green, custom_id="btn_register", emoji="📝")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())

    @discord.ui.button(label="ตรวจสอบสถานะบัญชี", style=discord.ButtonStyle.blurple, custom_id="btn_status", emoji="🔍")
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        found_xbox = "ยังไม่ได้ลงทะเบียน"
        found_ic = "-"
        
        for x_lower, data in registered_users.items():
            if data["discord_id"] == user_id:
                found_xbox = x_lower
                found_ic = data["ic_name"]
                break

        embed = discord.Embed(
            title="🔍 ข้อมูลบัญชีของคุณ",
            description=f"• **Discord:** {interaction.user.mention}\n• **ชื่อ Xbox:** `{found_xbox}`\n• **ชื่อ IC:** `{found_ic}`",
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setup-panel", description="สร้าง Panel ปุ่มกดลงทะเบียน")
async def setup_panel(interaction: discord.Interaction):
    embed = discord.Embed(title="🎙️ ระบบ Proximity Voice และลงทะเบียน", description="กดปุ่มด้านล่างเพื่อลงทะเบียนชื่อ Xbox และชื่อ IC ของคุณ", color=discord.Color.blurple())
    await interaction.channel.send(embed=embed, view=PanelView())
    await interaction.response.send_message("✅ สร้าง Panel เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="set-category", description="ตั้งค่าหมวดหมู่ห้องสร้างเกม/เสียงใกล้เคียง")
async def set_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    global default_category_id
    default_category_id = category.id
    await interaction.response.send_message(f"✅ ตั้งค่าหมวดหมู่ห้องเป็น: **{category.name}** เรียบร้อย", ephemeral=True)

@bot.tree.command(name="set-lobby", description="ตั้งค่าห้องล็อบบี้เริ่มต้นสำหรับผู้เล่นเข้าเกม")
async def set_lobby(interaction: discord.Interaction, channel: discord.VoiceChannel):
    global default_lobby_channel_id
    default_lobby_channel_id = channel.id
    await interaction.response.send_message(f"✅ ตั้งค่าห้อง Lobby เริ่มต้นเป็น: **{channel.name}** เรียบร้อย", ephemeral=True)

@bot.tree.command(name="set-sos-channel", description="ตั้งค่าช่องแจ้งเตือน SOS")
async def set_sos_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global sos_channel_id
    sos_channel_id = channel.id
    await interaction.response.send_message(f"✅ ตั้งค่าช่อง SOS เป็น: {channel.mention}", ephemeral=True)

@bot.tree.command(name="set-sos-role", description="ตั้งค่าเลือกยศแจ้งเตือน SOS")
async def set_sos_role(interaction: discord.Interaction, role: discord.Role):
    global sos_role_id
    sos_role_id = role.id
    await interaction.response.send_message(f"✅ ตั้งค่าเลือกยศ SOS เป็น: {role.mention}", ephemeral=True)

@bot.event
async def on_ready():
    bot.add_view(PanelView())
    await bot.tree.sync()
    logging.info(f"✅ Logged in as {bot.user.name} and Commands Synced!")

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
