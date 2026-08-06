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
MESSAGES_REQUIRED = int(os.environ.get("MESSAGES_REQUIRED", "10"))   # عدد الرسائل المطلوب باليوم
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Amman"))        # المنطقة الزمنية
RESET_HOUR = int(os.environ.get("RESET_HOUR", "0"))                  # ساعة تصفير الستريك اليومي (0-23)، 0 = 12 بالليل
REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", str((RESET_HOUR - 1) % 24)))  # ساعة إرسال التذكير (افتراضيا قبل التصفير بساعة)
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
        data[uid] = {
            "streak": 0,
            "messages_today": 0,
            "achieved_today": False,
            "reminded_today": False,
        }
    # لو مستخدم قديم ما فيه الحقل الجديد، نضيفه
    data[uid].setdefault("reminded_today", False)
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
            "اذا ما ارسلت الرسائل المطلوبة بيوم الستريك بينقطع وبيروح منك"
        )
        await interaction.response.send_message(explanation, ephemeral=True)


# ---------------- أمر: عرض الستريك الشخصي ----------------
@bot.command(name="streak")
async def streak_cmd(ctx):
    user = get_user(ctx.author.id)

    embed = discord.Embed(
        title=f"ستريك {ctx.author.display_name}",
        color=discord.Color.orange(),
    )
    embed.add_field(name="🔥 الستريك الحالي", value=str(user["streak"]), inline=True)
    embed.add_field(
        name="📨 رسائل اليوم",
        value=f"{user['messages_today']} / {MESSAGES_REQUIRED}",
        inline=True,
    )

    await ctx.send(embed=embed)


# ---------------- زر تأكيد تصفير ستريك شخص ----------------
class ConfirmResetView(discord.ui.View):
    def __init__(self, target_id: int, requester_id: int):
        super().__init__(timeout=60)
        self.target_id = target_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("هاد الزر مو إلك.", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(self.target_id)
        data[uid] = {
            "streak": 0,
            "messages_today": 0,
            "achieved_today": False,
            "reminded_today": False,
        }
        save_data(data)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"تم تصفير الستريك الخاص بـ <@{self.target_id}>", view=self
        )
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="تم إلغاء العملية", view=self)
        self.stop()


# ---------------- أمر إداري: تصفير ستريك شخص ----------------
@bot.command(name="resetstreak")
@commands.has_permissions(administrator=True)
async def reset_streak_cmd(ctx, member: discord.Member):
    view = ConfirmResetView(target_id=member.id, requester_id=ctx.author.id)
    await ctx.send(
        f"هل تريد التأكيد على تصفير الستريك الخاص بـ {member.mention}",
        view=view,
    )


@reset_streak_cmd.error
async def reset_streak_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("هاد الأمر للإداريين بس.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("ما لقيت هيك عضو، تأكد من المنشن أو الاسم.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("استخدم الأمر هيك: `!resetstreak @الشخص`")
    else:
        raise error


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


# ---------------- تذكير خاص قبل انقطاع الستريك ----------------
last_reminder_date = None


@tasks.loop(seconds=30)
async def reminder_check():
    global last_reminder_date
    now = datetime.now(TIMEZONE)

    if now.hour == REMINDER_HOUR and now.minute == 0:
        today_str = now.strftime("%Y-%m-%d")
        if last_reminder_date != today_str:
            last_reminder_date = today_str

            for uid, user in data.items():
                if not user["achieved_today"] and not user.get("reminded_today", False):
                    remaining = max(0, MESSAGES_REQUIRED - user["messages_today"])
                    if remaining <= 0:
                        continue
                    member = None
                    for guild in bot.guilds:
                        member = guild.get_member(int(uid))
                        if member:
                            break
                    if member:
                        try:
                            await member.send(
                                f"⏰ تنبيه! باقيلك {remaining} رسالة بس عشان يكمل ستريكك اليوم "
                                f"(الستريك الحالي: {user['streak']}). لا تخليه ينقطع 🔥"
                            )
                        except discord.Forbidden:
                            pass  # الخاص مقفول عنده
                    user["reminded_today"] = True

            save_data(data)
            print(f"[{now}] تم إرسال تذكيرات الستريك.")


# ---------------- إعادة التصفير اليومية ----------------
last_reset_date = None


@tasks.loop(seconds=30)
async def daily_reset_check():
    global last_reset_date
    now = datetime.now(TIMEZONE)

    if now.hour == RESET_HOUR and now.minute == 0:
        today_str = now.strftime("%Y-%m-%d")
        if last_reset_date != today_str:
            last_reset_date = today_str
            for uid, user in data.items():
                if not user["achieved_today"]:
                    user["streak"] = 0
                user["messages_today"] = 0
                user["achieved_today"] = False
                user["reminded_today"] = False
            save_data(data)
            print(f"[{now}] تمت إعادة تعيين الستريك اليومي.")


@bot.event
async def on_ready():
    print(f"✅ البوت شغال باسم {bot.user}")
    bot.add_view(StreakInfoView())  # يخلي الزر شغال بعد أي ريستارت
    if not daily_reset_check.is_running():
        daily_reset_check.start()
    if not reminder_check.is_running():
        reminder_check.start()


if not TOKEN:
    raise SystemExit("❌ ما في توكن! ضيف DISCORD_TOKEN من إعدادات Variables بمشروع Railway.")

bot.run(TOKEN)
