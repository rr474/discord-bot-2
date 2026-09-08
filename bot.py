import asyncio
import json
from aiohttp import web
import discord
from discord.ext import commands

# --- CONFIGURATION ---
TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"  # ใส่ Discord Bot Token ของคุณ
PORT = 8080  # พอร์ทสำหรับ aiohttp webserver (Railway จะต่อผ่าน Port นี้)

# ตั้งค่า Intents สำหรับ Discord Bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- aiohttp Web Handlers ---

async def handle_positions(request):
    """ รับพิกัดผู้เล่นจาก Minecraft Add-on """
    try:
        data = await request.json()
        players = data.get("players", [])
        guild_id = data.get("guildId")

        # ตัวอย่าง: วนลูปประมวลผลพิกัดผู้เล่น
        for p in players:
            xbox_name = p.get("xboxName")
            ic_name = p.get("icName")
            x, y, z = p.get("x"), p.get("y"), p.get("z")
            dimension = p.get("dim")

            # TODO: นำพิกัด X, Y, Z ไปคำนวณระยะห่างระหว่างผู้เล่นเพื่อย้าย Voice Channel หรือปรับระดับเสียง (PyNaCl)
            # print(f"📍 [{dimension}] {ic_name} ({xbox_name}): X={x}, Y={y}, Z={z}")

        return web.json_response({"status": "success", "received": len(players)})
    except Exception as e:
        print(f"[Error Positions]: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=400)


async def handle_sos(request):
    """ รับแจ้งเหตุฉุกเฉิน (SOS) จาก Minecraft แล้วส่งลง Discord """
    try:
        data = await request.json()
        sos_channel_id = int(data.get("sosChannelId"))
        ic_name = data.get("icName", "ไม่ระบุ")
        player_name = data.get("playerName", "ไม่ระบุ")
        location = data.get("location", "ไม่ระบุ")

        channel = bot.get_channel(sos_channel_id)
        if channel:
            embed = discord.Embed(
                title="🚨 แจ้งเหตุฉุกเฉิน (SOS) จากในเกม!",
                color=0xFF0000
            )
            embed.add_field(name="👤 ชื่อ IC", value=ic_name, inline=True)
            embed.add_field(name="🎮 บัญชี Xbox", value=player_name, inline=True)
            embed.add_field(name="📍 พิกัดสถานที่", value=location, inline=False)
            embed.set_footer(text="ระบบแจ้งเหตุฉุกเฉิน Minecraft")
            
            await channel.send(embed=embed)
            return web.json_response({"status": "ok"})
        else:
            return web.json_response({"status": "error", "message": "Channel not found"}, status=404)

    except Exception as e:
        print(f"[Error SOS]: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)


async def handle_health_check(request):
    """ ให้ Minecraft หรือ Railway เช็คสถานะความพร้อมของเซิร์ฟเวอร์ """
    return web.json_response({"status": "online", "message": "Bot & HTTP Server Ready"})


# --- ตั้งค่า Web Application ---
app = web.Application()
app.router.add_get('/', handle_health_check)
app.router.add_post('/api/positions', handle_positions)
app.router.add_post('/api/sos', handle_sos)


# --- BOT EVENTS & MAIN RUNNER ---
@bot.event
async def on_ready():
    print(f"✅ บอท Discord ออนไลน์แล้วในชื่อ: {bot.user.name}")


async def main():
    async with bot:
        # ตั้งค่า aiohttp Runner
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        print(f"🌐 HTTP API Server กำลังทำงานที่พอร์ท {PORT}")

        # รัน Discord Bot
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 ปิดการทำงานของบอท...")
