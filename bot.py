import os
import discord
from aiohttp import web
from discord.ext import commands

# ตั้งค่า Discord Bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Route สำหรับรับข้อมูล HTTP POST จาก Minecraft
routes = web.RouteTableDef()


@routes.post("/mc-update")
async def handle_mc_update(request):
  try:
    data = await request.json()
    msg_type = data.get("type")

    if msg_type == "POSITIONS_UPDATE":
      players = data.get("players", [])
      # จัดการพิกัดตำแหน่งของผู้เล่นในนี้
      # print(f"Received positions: {players}")

    elif msg_type == "SOS_EMERGENCY":
      player_name = data.get("playerName")
      location = data.get("location")
      # สามารถสั่งให้บอทส่งข้อความแจ้งเตือนลงช่อง Discord ได้ที่นี่

    return web.json_response({"status": "ok"}, status=200)
  except Exception as e:
    return web.json_response({"status": "error", "message": str(e)}, status=400)


async function start_web_server():
  app = web.Application()
  app.add_routes(routes)
  runner = web.AppRunner(app)
  await runner.setup()
  port = int(os.environ.get("PORT", 8080))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


@bot.event
async def on_ready():
  print(f"Bot online: {bot.user}")
  # เริ่มต้น Web Server พร้อมกับบอท
  bot.loop.create_task(start_web_server())


# ใส่ Token บอทของคุณที่นี่
bot.run("YOUR_BOT_TOKEN")
