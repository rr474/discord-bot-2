import os
import json
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
import websockets

logging.basicConfig(level=logging.INFO)

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.voice_states = True
INTENTS.message_content = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# เก็บสาย WebSocket
ws_clients = set()

# สิทธิ์/ตำแหน่งห้องเสียง
GUILD_ID = 1499842090480435363

def get_member_by_xbox_name(guild, xbox_name):
    """ ค้นหาสมาชิกใน Discord ที่มี Nickname หรือ Display Name ตรงกับชื่อ Xbox """
    search_name = xbox_name.strip().lower()
    for member in guild.members:
        nick = (member.nick or member.display_name or member.name).strip().lower()
        if nick == search_name:
            return member
    return None

# =============================================================
# 📝 UI Modal & View สำหรับลงทะเบียนใน Discord
# =============================================================
class RegisterModal(discord.ui.Modal, title="ลงทะเบียน Voice Chat"):
    xbox_name = discord.ui.TextInput(
        label="ชื่อ Xbox Gamertag (ชื่อในเกม)",
        placeholder="เช่น GamerPro1234",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        # ป้องกันปุ่มขึ้น Interactive Failed ด้วย defer()
        await interaction.response.defer(ephemeral=True)
        
        xbox_val = self.xbox_name.value.strip()
        member = interaction.user
        guild = interaction.guild

        if not guild:
            await interaction.followup.send("⚠️ กรุณาใช้งานคำสั่งนี้ภายในเซิร์ฟเวอร์เท่านั้น", ephemeral=True)
            return

        # 1. เช็กว่าเป็นเจ้าของเซิร์ฟเวอร์ (Server Owner) หรือไม่
        if member == guild.owner:
            await interaction.followup.send(
                f"⚠️ **แจ้งเตือน:** คุณเป็นเจ้าของเซิร์ฟเวอร์ (Server Owner)\n"
                f"บอทไม่มีสิทธิ์เปลี่ยนชื่อให้เจ้าของเซิร์ฟเวอร์ได้ตามระบบความปลอดภัยของ Discord ครับ\n"
                f"👉 กรุณาเปลี่ยนชื่อเล่นในดิสคอร์ดของคุณเป็น **{xbox_val}** ด้วยตนเองนะครับ",
                ephemeral=True
            )
            return

        # 2. เช็กลำดับยศ (Role Hierarchy) ระหว่างผู้ใช้กับบอท
        bot_top_role = guild.me.top_role
        user_top_role = member.top_role

        if user_top_role >= bot_top_role:
            await interaction.followup.send(
                f"⚠️ **แจ้งเตือน:** คุณมียศสูงกว่าหรือเท่ายศของบอท (`{user_top_role.name}` >= `{bot_top_role.name}`)\n"
                f"ระบบ Discord ไม่อนุญาตให้บอทจัดการผู้ใช้ที่มียศสูงกว่าครับ\n"
                f"👉 กรุณาเปลี่ยนชื่อเล่นในดิสคอร์ดของคุณเป็น **{xbox_val}** ด้วยตนเอง หรือติดต่อแอดมินเพื่อย้ายยศบอทขึ้นสูงกว่าครับ",
                ephemeral=True
            )
            return

        # 3. หากยศบอทสูงกว่าปกติ ดำเนินการเปลี่ยนชื่อ
        try:
            await member.edit(nick=xbox_val)
            await interaction.followup.send(
                f"✅ **ลงทะเบียนสำเร็จ!** เปลี่ยนชื่อในดิสคอร์ดของคุณเป็น **{xbox_val}** เรียบร้อยแล้วครับ",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"⚠️ **แจ้งเตือน:** บอทขาดสิทธิ์ `Manage Nicknames` (จัดการชื่อเล่น) ในเซิร์ฟเวอร์นี้\n"
                f"👉 กรุณาเปลี่ยนชื่อเล่นในดิสคอร์ดของคุณเป็น **{xbox_val}** ด้วยตนเองครับ",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

class RegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # timeout=None เพื่อให้ปุ่มใช้งานได้ถาวร

    @discord.ui.button(label="ลงทะเบียน Voice Chat", style=discord.ButtonStyle.primary, custom_id="reg_btn_v1")
    async def reg_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())

# =============================================================
# 🔔 DISCORD EVENTS & SLASH COMMANDS
# =============================================================
@bot.event
async def on_ready():
    logging.info(f"🤖 บอททำงานแล้วในชื่อ: {bot.user}")
    bot.add_view(RegisterView())
    
    # Sync Slash Commands ไปยัง Discord
    try:
        synced = await bot.tree.sync()
        logging.info(f"✅ Sync Slash Commands สำเร็จจำนวน {len(synced)} คำสั่ง")
    except Exception as e:
        logging.error(f"❌ ไม่สามารถ Sync Slash Commands ได้: {e}")

# 📌 คำสั่ง Slash Command เดิมของคุณ (/set-default-voice)
@bot.tree.command(name="set-default-voice", description="ตั้งค่าปุ่มลงทะเบียน Voice Chat")
@app_commands.checks.has_permissions(administrator=True)
async def set_default_voice_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 ลงทะเบียน Voice Chat",
        description="กดปุ่มด้านล่างเพื่อใส่ชื่อ Xbox Gamertag ของคุณ ระบบจะทำการเปลี่ยนชื่อใน Discord ให้ตรงกับในเกมเพื่อใช้งานระบบไมค์",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=RegisterView())

# 📌 คำสั่งสำรองแบบ Slash Command (/setup_verify)
@bot.tree.command(name="setup_verify", description="ตั้งค่าปุ่มลงทะเบียน Voice Chat สำหรับผู้ใช้")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verify_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 ลงทะเบียน Voice Chat",
        description="กดปุ่มด้านล่างเพื่อใส่ชื่อ Xbox Gamertag ของคุณ ระบบจะทำการเปลี่ยนชื่อใน Discord ให้ตรงกับในเกมเพื่อใช้งานระบบไมค์",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=RegisterView())

# 📌 คำสั่งแบบพิมพ์ Prefix (!setup_verify)
@bot.command()
@commands.has_permissions(administrator=True)
async def setup_verify(ctx):
    embed = discord.Embed(
        title="📋 ลงทะเบียน Voice Chat",
        description="กดปุ่มด้านล่างเพื่อใส่ชื่อ Xbox Gamertag ของคุณ ระบบจะทำการเปลี่ยนชื่อใน Discord ให้ตรงกับในเกมเพื่อใช้งานระบบไมค์",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=RegisterView())

# =============================================================
# 🌐 WEBSOCKET SERVER
# =============================================================
async def ws_handler(websocket):
    logging.info("🌐 Minecraft Client / Script API Connected via WebSocket")
    ws_clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                guild_id = int(data.get("guildId", GUILD_ID))
                guild = bot.get_guild(guild_id)

                if not guild:
                    continue

                # 1. ระบบสั่งเปิด/ปิดไมค์
                if msg_type == "MUTE_TOGGLE":
                    player_name = data.get("player")
                    is_muted = data.get("isMuted", False)
                    
                    member = get_member_by_xbox_name(guild, player_name)
                    if member and member.voice:
                        try:
                            await member.edit(mute=is_muted)
                            logging.info(f"🔊 สลับสถานะไมค์ของ {member.display_name}: Mute={is_muted}")
                        except Exception as e:
                            logging.error(f"❌ ไม่สามารถสลับสถานะไมค์ได้: {e}")

                # 2. ระบบแจ้งเตือน SOS
                elif msg_type == "SOS_EMERGENCY":
                    channel_id = int(data.get("sosChannelId"))
                    channel = guild.get_channel(channel_id)
                    if channel:
                        embed = discord.Embed(
                            title="🚨 แจ้งเหตุฉุกเฉิน (SOS) 🚨",
                            color=discord.Color.red()
                        )
                        embed.add_field(name="ชื่อ IC", value=data.get("icName", "ไม่ระบุ"), inline=True)
                        embed.add_field(name="บัญชี Xbox", value=data.get("playerName"), inline=True)
                        embed.add_field(name="มิติ", value=data.get("dimension"), inline=True)
                        embed.add_field(name="พิกัด", value=data.get("location"), inline=False)
                        embed.add_field(name="เวลา", value=data.get("time"), inline=True)
                        await channel.send(embed=embed)

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logging.error(f"❌ Error handling WS Message: {e}")

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        ws_clients.remove(websocket)
        logging.info("🚪 Minecraft Client Disconnected")

# =============================================================
# 🚀 MAIN STARTUP
# =============================================================
async def main():
    port = int(os.getenv("PORT", 8080))
    token = os.getenv("DISCORD_TOKEN")

    if not token:
        logging.error("❌ ไม่พบ DISCORD_TOKEN ใน Variables! กรุณาตั้งค่าใน Railway")
        return

    # เปิด WebSocket Server
    await websockets.serve(ws_handler, "0.0.0.0", port)
    logging.info(f"📡 เปิด WebSocket Server บนพอร์ต {port}")

    # รัน Discord Bot
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
