import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# ==================== الإعدادات ====================
# هاي القيم بتنجيب من Environment Variables (تنضبط من Railway مباشرة).
# لو بدك تشغل الكود محليًا بدون Railway، بتقدر تحط القيم مباشرة بدل os.environ.get(...)
TOKEN = os.environ.get("DISCORD_TOKEN")                              # توكن البوت
GENERAL_CHANNEL_ID = int(os.environ.get("GENERAL_CHANNEL_ID", "0"))  # آيدي الروم العام
MESSAGES_REQUIRED = int(os.environ.get("MESSAGES_REQUIRED", "5"))    # عدد الرسائل المطلوب باليوم
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Amman"))        # المنطقة الزمنية
DATA_FILE = "streaks.json"                                           # ملف تخزين بيانات الستريك
# =====================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------- تخزين البيانات ----------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()


def get_user(user_id):
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"streak": 0, "messages_today": 0, "achieved_today": False}
    return data[uid]


# ---------------- زر شرح فكرة الستريك ----------------
class StreakInfoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # يخلي الزر شغال حتى بعد إعادة تشغيل البوت

    @discord.ui.button(
        emoji="❓",
        style=discord.ButtonStyle.secondary,
        custom_id="streak_info_button",
    )
    async def streak_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        explanation = (
            "فكرة الستريك\n"
            f"لازم ترسل {MESSAGES_REQUIRED} رسائل يوميا بالشات العام ليحسب لك ستريك\n"
            "اذا ما ارسلت 5 رسائل في يوم الستريك بينقطع وبيروح منك"
        )
        await interaction.response.send_message(explanation, ephemeral=True)


# ---------------- عند استلام رسالة ----------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id == GENERAL_CHANNEL_ID:
        user = get_user(message.author.id)

        if not user["achieved_today"]:
            user["messages_today"] += 1

            if user["messages_today"] >= MESSAGES_REQUIRED:
                user["achieved_today"] = True
                user["streak"] += 1
                save_data(data)

                await message.channel.send(
                    f"مبروك يا اسطورة {message.author.mention} , وصلت الستريك {user['streak']} <a:b_NE20:1513171162157416609>",
                    view=StreakInfoView(),
                )
            else:
                save_data(data)

    await bot.process_commands(message)


# ---------------- إعادة التصفير اليومية الساعة 12 ظهرًا ----------------
last_reset_date = None


@tasks.loop(seconds=30)
async def daily_reset_check():
    global last_reset_date
    now = datetime.now(TIMEZONE)

    if now.hour == 12 and now.minute == 0:
        today_str = now.strftime("%Y-%m-%d")
        if last_reset_date != today_str:
            last_reset_date = today_str
            for uid, user in data.items():
                if not user["achieved_today"]:
                    user["streak"] = 0
                user["messages_today"] = 0
                user["achieved_today"] = False
            save_data(data)
            print(f"[{now}] تمت إعادة تعيين الستريك اليومي.")


@bot.event
async def on_ready():
    print(f"✅ البوت شغال باسم {bot.user}")
    bot.add_view(StreakInfoView())  # يخلي الزر شغال بعد أي ريستارت
    if not daily_reset_check.is_running():
        daily_reset_check.start()


if not TOKEN:
    raise SystemExit("❌ ما في توكن! ضيف DISCORD_TOKEN من إعدادات Variables بمشروع Railway.")

bot.run(TOKEN)
