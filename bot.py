import os
import logging
import discord
from discord.ext import commands
from aiohttp import web
import asyncio

# ตั้งค่า Logging
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
            
            # สร้างห้องเสียงชั่วคราว
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
            logging.info(f"📏 ปรับระยะ Proximity เป็น {proximity_radius} บล็อก (จากในเกม)")

        elif msg_type == "SOS_EMERGENCY" and sos_channel_id:
            sos_channel = bot.get_channel(sos_channel_id)
            if sos_channel:
                embed = discord.Embed(
                    title="🚨 แจ้งเหตุฉุกเฉิน (SOS)",
                    description=f"ผู้เล่น `{data.get('playerName')}` ขอความช่วยเหลือ!",
                    color=discord.Color.red()
                )
                embed.add_field(name="📍 พิกัด", value=f"`{data.get('location')}`")
                await sos_channel.send(content=f"🚨 @here **เกิดเหตุฉุกเฉิน!**", embed=embed)

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
                    logging.info(f"🗑️ ลบห้องเสียงร้างอัตโนมัติ: {channel.name}")
            except Exception as e:
                logging.error(f"❌ Delete Channel Error: {e}")

@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user.name}")

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
    logging.info(f"🌐 Web Server started on port {port}")

async def main():
    async with bot:
        await start_web_server()
        TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
