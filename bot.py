import os
import json
import asyncio
import logging
import discord
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
        # เช็กชื่อเล่น (Nickname) หรือชื่อแสดงผล (Display Name)
        nick = (member.nick or member.display_name or member.name).strip().lower()
        if nick == search_name:
            return member
    return None

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

                # -------------------------------------------------------------
                # 1. จัดการการปิด/เปิดไมค์ (MUTE_TOGGLE)
                # -------------------------------------------------------------
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

                # -------------------------------------------------------------
                # 2. แจ้งเตือนฉุกเฉิน (SOS_EMERGENCY)
                # -------------------------------------------------------------
                elif msg_type == "SOS_EMERGENCY":
                    channel_id = int(data.get("sosChannelId"))
                    channel = guild.get_channel(channel_id)
                    if channel:
                        embed = discord.Embed(
                            title="🚨 แจ้งเหตุฉุกเฉิน (SOS) 🚨",
                            color=discord.Color.red()
                        )
                        embed.add_field(name="ผู้แจ้ง", value=data.get("playerName"), inline=True)
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
# 📝 UI Modal สำหรับลงทะเบียนใน Discord (เปลี่ยนชื่อเป็น Xbox)
# =============================================================
class RegisterModal(discord.ui.Modal, title="ลงทะเบียน Voice Chat"):
    xbox_name = discord.ui.TextInput(
        label="ชื่อ Xbox Gamertag (ชื่อในเกม)",
        placeholder="เช่น GamerPro1234",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        xbox_val = self.xbox_name.value.strip()
        member = interaction.user

        try:
            # เปลี่ยน Nickname ของผู้ใช้ใน Discord ให้กลายเป็นชื่อ Xbox
            await member.edit(nick=xbox_val)
            await interaction.response.send_message(
                f"✅ ลงทะเบียนสำเร็จ! เปลี่ยนชื่อในดิสคอร์ดของคุณเป็น **{xbox_val}** แล้วครับ",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"⚠️ ลงทะเบียนสำเร็จ! แต่บอทไม่มีสิทธิ์เปลี่ยนชื่อให้คุณ (กรุณาเปลี่ยนชื่อในดิสคอร์ดให้เป็น **{xbox_val}** ด้วยตนเอง)",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

class RegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ลงทะเบียน Voice Chat", style=discord.ButtonStyle.primary, custom_id="reg_btn")
    async def reg_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterModal())

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_verify(ctx):
    """ คำสั่งตั้งปุ่มลงทะเบียนสำหรับแอดมิน !setup_verify """
    embed = discord.Embed(
        title="📋 ลงทะเบียน Voice Chat",
        description="กดปุ่มด้านล่างเพื่อใส่ชื่อ Xbox Gamertag ของคุณ ระบบจะทำการเปลี่ยนชื่อใน Discord ให้ตรงกับในเกมเพื่อใช้งานระบบไมค์",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=RegisterView())

# =============================================================
# 🚀 MAIN STARTUP
# =============================================================
async def main():
    port = int(os.getenv("PORT", 8080))
    
    # เปิด WebSocket Server
    ws_server = await websockets.serve(ws_handler, "0.0.0.0", port)
    logging.info(f"📡 เปิด WebSocket Server บนพอร์ต {port}")

    # รัน Discord Bot
    token = os.getenv("DISCORD_TOKEN")
    async with bot:
        bot.add_view(RegisterView())
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
