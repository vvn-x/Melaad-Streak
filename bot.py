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

# ⚠️ مهم: إذا كنت مستضيف البوت على Railway بدون Volume دائم، الملف هاد بينمسح مع كل Deploy/Restart.
# اربط Volume دائم بمشروعك وحط مساره هون (مثلاً "/data/streaks.json") عشان ما تضيع بيانات الأعضاء.
DATA_FILE = os.environ.get("DATA_FILE", "streaks.json")              # ملف تخزين بيانات الستريك

FREEZES_PER_MONTH = int(os.environ.get("FREEZES_PER_MONTH", "1"))    # عدد أيام "التجميد" المسموحة شهريًا لكل عضو

# رتب المراحل: صيغة "عدد_الأيام:آيدي_الرتبة" مفصولة بفواصل، مثال: "7:123456,30:654321"
def _parse_milestones(raw: str):
    milestones = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        day_str, role_str = part.split(":", 1)
        try:
            milestones[int(day_str.strip())] = int(role_str.strip())
        except ValueError:
            continue
    return milestones


STREAK_MILESTONE_ROLES = _parse_milestones(os.environ.get("STREAK_MILESTONES", ""))
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

# لمنع معالجة نفس الرسالة مرتين (بيصير أحيانًا بعد إعادة اتصال البوت بديسكورد)
from collections import deque
_processed_message_ids = deque(maxlen=5000)
_processed_message_ids_set = set()


def already_processed(message_id: int) -> bool:
    if message_id in _processed_message_ids_set:
        return True
    if len(_processed_message_ids) == _processed_message_ids.maxlen:
        oldest = _processed_message_ids[0]
        _processed_message_ids_set.discard(oldest)
    _processed_message_ids.append(message_id)
    _processed_message_ids_set.add(message_id)
    return False


def get_user(user_id):
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "streak": 0,
            "messages_today": 0,
            "achieved_today": False,
            "reminded_today": False,
            "locked_today": False,
            "enabled": True,
        }
    # لو مستخدم قديم ما فيه الحقول الجديدة، نضيفها
    data[uid].setdefault("reminded_today", False)
    data[uid].setdefault("locked_today", False)
    data[uid].setdefault("enabled", True)
    return data[uid]


def build_streak_embed(target, guild):
    user = get_user(target.id)

    embed = discord.Embed(
        title=f"ستريك {target.display_name}",
        color=discord.Color.orange(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="\u200E<a:j16:1534842771373035560> الستريك الحالي", value=str(user["streak"]), inline=True)
    embed.add_field(name="\u200E", value="\u200E", inline=True)
    embed.add_field(
        name="<a:008Cinnamoroll_Excited:1525769555052335155> رسائل اليوم",
        value=f"{user['messages_today']} / {MESSAGES_REQUIRED}",
        inline=True,
    )
    if guild.icon:
        embed.set_footer(text=guild.name, icon_url=guild.icon.url)
    else:
        embed.set_footer(text=guild.name)
    embed.timestamp = datetime.now(TIMEZONE)
    return embed


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

    @discord.ui.button(
        emoji="📊",
        style=discord.ButtonStyle.secondary,
        custom_id="streak_view_button",
    )
    async def streak_view(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_streak_embed(interaction.user, interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------- أمر: تفعيل الستريك للشخص نفسه ----------------
@bot.command(name="enablestreak")
async def enable_streak_cmd(ctx):
    user = get_user(ctx.author.id)
    if user["enabled"]:
        await ctx.send("الستريك مفعل من قبل.")
        return
    user["enabled"] = True
    save_data(data)
    await ctx.send("تم تفعيل الستريك.")


# ---------------- أمر: إلغاء الستريك للشخص نفسه ----------------
@bot.command(name="disablestreak")
async def disable_streak_cmd(ctx):
    user = get_user(ctx.author.id)
    if not user["enabled"]:
        await ctx.send("الستريك ملغي من قبل.")
        return
    user["enabled"] = False
    save_data(data)
    await ctx.send("تم الغاء الستريك بنجاح.")

# ---------------- زر تأكيد تصفير ستريك شخص ----------------
class ConfirmResetView(discord.ui.View):
    def __init__(self, target_id: int, requester_id: int):
        super().__init__(timeout=60)
        self.target_id = target_id
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("هاذا الزر مو لك.", ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(self.target_id)
        data[uid] = {
            "streak": 0,
            "messages_today": 0,
            "achieved_today": False,
            "reminded_today": False,
            "locked_today": True,  # يمنع الشخص من إعادة تحقيق الستريك بنفس اليوم
        }
        save_data(data)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"تم تصفير الستريك الخاص بـ <@{self.target_id}>", view=self
        )
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.secondary, emoji="❌")
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
        await ctx.send("هاذا الأمر خاص للادارة العلياً فقط.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("لم اعثر على هاذا العضو تأكد من الأسم وحاول مرة اخرى.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("طريقة الاستخدام كذا: `!resetstreak @الشخص`")
    else:
        raise error


# ---------------- عند استلام رسالة ----------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if already_processed(message.id):
        return

    if message.channel.id == GENERAL_CHANNEL_ID:
        user = get_user(message.author.id)

        if user.get("enabled", True) and not user["achieved_today"] and not user.get("locked_today", False):
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
                user["locked_today"] = False
            save_data(data)
            print(f"[{now}] تم إعادة تعيين الستريك اليومي.")


@bot.event
async def on_ready():
    print(f"✅ البوت شغال باسم {bot.user}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.playing, name="programed by mist")
    )
    bot.add_view(StreakInfoView())  # يخلي الزر شغال بعد أي ريستارت
    if not daily_reset_check.is_running():
        daily_reset_check.start()
    if not reminder_check.is_running():
        reminder_check.start()


if not TOKEN:
    raise SystemExit("❌ ما في توكن! ضيف DISCORD_TOKEN من إعدادات Variables بمشروع Railway.")

bot.run(TOKEN)
