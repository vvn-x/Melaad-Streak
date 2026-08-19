import discord
from discord.ext import commands, tasks
import os
import asyncpg
from datetime import datetime
from zoneinfo import ZoneInfo

# ==================== الإعدادات ====================
# هاي القيم بتنجيب من Environment Variables (تنضبط من Railway مباشرة).
# لو بدك تشغل الكود محليًا بدون Railway، بتقدر تحط القيم مباشرة بدل os.environ.get(...)
TOKEN = os.environ.get("DISCORD_TOKEN")                              # توكن البوت
GENERAL_CHANNEL_ID = int(os.environ.get("GENERAL_CHANNEL_ID", "0"))  # آيدي الروم العام (يلي فيه بتنحسب الرسائل)
COMMANDS_CHANNEL_ID = int(os.environ.get("COMMANDS_CHANNEL_ID", "0"))  # آيدي شات الأوامر (تفعيل/إلغاء الستريك)
MESSAGES_REQUIRED = int(os.environ.get("MESSAGES_REQUIRED", "10"))   # عدد الرسائل المطلوب باليوم
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Amman"))        # المنطقة الزمنية
RESET_HOUR = int(os.environ.get("RESET_HOUR", "0"))                  # ساعة تصفير الستريك اليومي (0-23)، 0 = 12 بالليل
REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", str((RESET_HOUR - 1) % 24)))  # ساعة إرسال التذكير (افتراضيا قبل التصفير بساعة)

# رابط الاتصال بقاعدة بيانات PostgreSQL (Railway بيضيفه تلقائيًا لما تضيف خدمة Postgres للمشروع)
DATABASE_URL = os.environ.get("DATABASE_URL")

# إيموجي التنبيه بالخاص (الصيغة: <a:الاسم:الآيدي> للأيموجي المتحرك). عدّل الاسم إذا ما ظهر صح بالسيرفر عندك.
REMINDER_EMOJI = os.environ.get("REMINDER_EMOJI", "<a:emoji:1525828157977006201>")
# =====================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


# ==================== قاعدة البيانات (PostgreSQL) ====================
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS streaks (
    user_id        BIGINT  PRIMARY KEY,
    streak         INTEGER NOT NULL DEFAULT 0,
    messages_today INTEGER NOT NULL DEFAULT 0,
    achieved_today BOOLEAN NOT NULL DEFAULT FALSE,
    reminded_today BOOLEAN NOT NULL DEFAULT FALSE,
    locked_today   BOOLEAN NOT NULL DEFAULT FALSE,
    enabled        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class StreakBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.pool: asyncpg.Pool | None = None

    async def setup_hook(self):
        # بينفذ مرة وحدة قبل ما البوت يتصل بديسكورد، مكان مثالي لإنشاء الاتصال بقاعدة البيانات
        self.pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=5)
        async with self.pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
        print("✅ تم الاتصال بقاعدة بيانات PostgreSQL وتجهيز الجدول.")


bot = StreakBot()


# ---------------- استعلامات آمنة (parameterized) ولا تعتمد على كتابة ملف كامل ----------------

async def get_user(user_id: int) -> dict:
    """يرجع بيانات العضو، ولو أول مرة بينشئ صف افتراضي له بعملية واحدة ذرية (upsert)."""
    async with bot.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO streaks (user_id) VALUES ($1)
            ON CONFLICT (user_id) DO UPDATE SET user_id = EXCLUDED.user_id
            RETURNING *;
            """,
            user_id,
        )
    return dict(row)


async def set_enabled(user_id: int, enabled: bool) -> dict:
    async with bot.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO streaks (user_id, enabled) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET enabled = EXCLUDED.enabled
            RETURNING *;
            """,
            user_id, enabled,
        )
    return dict(row)


async def register_message(user_id: int) -> dict:
    """يزيد عدد رسائل اليوم بعملية UPDATE ذرية وحدة، وبنفس الوقت يفحص إذا اكتمل الهدف
    ويحدّث الستريك، كلشي بعملية واحدة آمنة بدون قراءة-ثم-كتابة منفصلة (يمنع تعارض التحديثات).

    ملاحظة: شرط زيادة الستريك مبني على achieved_today الحالية المخزّنة بنفس صف الـ UPDATE
    (مش على قيمة اتجابت مسبقًا بقراءة منفصلة)، عشان لو وصلت أكتر من رسالة بنفس اللحظة
    ما ينزاد الستريك أكتر من مرة لنفس اليوم."""
    async with bot.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE streaks
            SET messages_today = messages_today + 1,
                streak = CASE
                    WHEN NOT achieved_today AND (messages_today + 1) >= $2 THEN streak + 1
                    ELSE streak
                END,
                achieved_today = CASE
                    WHEN (messages_today + 1) >= $2 THEN TRUE
                    ELSE achieved_today
                END
            WHERE user_id = $1
            RETURNING *;
            """,
            user_id, MESSAGES_REQUIRED,
        )
    return dict(row)


async def reset_user(user_id: int) -> dict:
    """تصفير ستريك عضو معيّن (أمر الإدارة)."""
    async with bot.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO streaks (user_id, streak, messages_today, achieved_today, reminded_today, locked_today, enabled)
            VALUES ($1, 0, 0, FALSE, FALSE, TRUE, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET
                streak = 0,
                messages_today = 0,
                achieved_today = FALSE,
                reminded_today = FALSE,
                locked_today = TRUE,
                enabled = TRUE
            RETURNING *;
            """,
            user_id,
        )
    return dict(row)


async def get_bot_state(key: str):
    async with bot.pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT value FROM bot_state WHERE key = $1;",
            key,
        )


async def set_bot_state(key: str, value: str):
    async with bot.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_state (key, value)
            VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
            """,
            key, value,
        )


async def daily_reset_all():
    """إعادة تعيين بيانات كل الأعضاء دفعة وحدة بعملية SQL وحدة (بدل ما نلف على كل عضو بالكود)."""
    async with bot.pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE streaks
            SET streak = CASE WHEN achieved_today THEN streak ELSE 0 END,
                messages_today = 0,
                achieved_today = FALSE,
                reminded_today = FALSE,
                locked_today = FALSE;
            """
        )


async def fetch_reminder_candidates():
    """يرجع كل الأعضاء المفعّل عندهم الستريك (enabled) ولسا ما حققوا هدف اليوم وما انبعتلهم تذكير.
    (تمت إضافة شرط enabled = TRUE عشان الأعضاء يلي عملوا /disablestreak ما توصلهم رسائل تذكير بالخاص)."""
    async with bot.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, streak, messages_today
            FROM streaks
            WHERE achieved_today = FALSE
              AND reminded_today = FALSE
              AND enabled = TRUE;
            """
        )
    return rows


async def mark_reminded(user_id: int):
    async with bot.pool.acquire() as conn:
        await conn.execute("UPDATE streaks SET reminded_today = TRUE WHERE user_id = $1;", user_id)


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


async def build_streak_embed(target, guild):
    user = await get_user(target.id)

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
        embed = await build_streak_embed(interaction.user, interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------- أمر: تفعيل الستريك للشخص نفسه (سلاش كوماند - رسالة مخفية) ----------------
@bot.tree.command(name="enablestreak", description="تفعيل الستريك الخاص فيك")
async def enable_streak_cmd(interaction: discord.Interaction):
    # هاد الأمر لازم ينكتب بشات الأوامر فقط (مش بشات الستريك العام)
    if COMMANDS_CHANNEL_ID and interaction.channel.id != COMMANDS_CHANNEL_ID:
        await interaction.response.send_message(
            f"هاذا الأمر لازم تكتبه بشات الأوامر <#{COMMANDS_CHANNEL_ID}> فقط.", ephemeral=True
        )
        return

    user = await get_user(interaction.user.id)
    if user["enabled"]:
        await interaction.response.send_message("الستريك مفعل من قبل.", ephemeral=True)
        return
    await set_enabled(interaction.user.id, True)
    await interaction.response.send_message("تم تفعيل الستريك.", ephemeral=True)


# ---------------- أمر: إلغاء الستريك للشخص نفسه (سلاش كوماند - رسالة مخفية) ----------------
@bot.tree.command(name="disablestreak", description="الغاء الستريك الخاص فيك")
async def disable_streak_cmd(interaction: discord.Interaction):
    # هاد الأمر لازم ينكتب بشات الأوامر فقط (مش بشات الستريك العام)
    if COMMANDS_CHANNEL_ID and interaction.channel.id != COMMANDS_CHANNEL_ID:
        await interaction.response.send_message(
            f"هاذا الأمر لازم تكتبه بشات الأوامر <#{COMMANDS_CHANNEL_ID}> فقط.", ephemeral=True
        )
        return

    user = await get_user(interaction.user.id)
    if not user["enabled"]:
        await interaction.response.send_message("الستريك ملغي من قبل.", ephemeral=True)
        return
    await set_enabled(interaction.user.id, False)
    # نعتبره متذكّر لليوم عشان ما توصله رسالة تذكير بالخاص لهاليوم مباشرة بعد ما ألغى الستريك
    async with bot.pool.acquire() as conn:
        await conn.execute(
            "UPDATE streaks SET reminded_today = TRUE WHERE user_id = $1;", interaction.user.id
        )
    await interaction.response.send_message("تم الغاء الستريك بنجاح.", ephemeral=True)


# ---------------- أمر: عرض أعلى 10 بالستريكات ----------------
@bot.tree.command(name="topstreak", description="عرض اعلى 10 بالستريكات")
async def top_streak_cmd(interaction: discord.Interaction):
    async with bot.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT user_id, streak
            FROM streaks
            ORDER BY streak DESC
            LIMIT 10;
            """
        )

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []
    for i, row in enumerate(rows, start=1):
        medal = medals.get(i)
        line = f"{i}. <@{row['user_id']}> : {row['streak']}"
        if medal:
            line += f" {medal}"
        lines.append(line)

    embed = discord.Embed(
        title="Top Streak",
        description="\n".join(lines) if lines else "ما في بيانات بعد.",
        color=discord.Color.orange(),
    )

    await interaction.response.send_message(embed=embed)


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
        await reset_user(self.target_id)
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
        user = await get_user(message.author.id)

        if user.get("enabled", True) and not user["achieved_today"] and not user.get("locked_today", False):
            updated = await register_message(message.author.id)

            if updated["achieved_today"] and updated["messages_today"] == MESSAGES_REQUIRED:
                await message.channel.send(
                    f"مبروك يا اسطورة {message.author.mention} , وصلت الستريك {updated['streak']} <a:b_NE20:1513171162157416609>",
                    view=StreakInfoView(),
                )

    await bot.process_commands(message)


# ---------------- تذكير خاص قبل انقطاع الستريك ----------------
REMINDER_STATE_KEY = "last_reminder_date"


@tasks.loop(seconds=30)
async def reminder_check():
    now = datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")

    reminder_threshold = now.replace(hour=REMINDER_HOUR, minute=0, second=0, microsecond=0)

    # نخزن تاريخ آخر تذكير داخل PostgreSQL (bot_state) بدل متغير بالذاكرة، عشان لو صار
    # Restart / Redeploy بنفس اليوم بعد ما انبعتت التذكيرات، ما ننبعت تذكيرات مكررة من جديد.
    last_reminder_date = await get_bot_state(REMINDER_STATE_KEY)

    # بدل ما نشيك تطابق دقيق بالدقيقة (كان ممكن يفوت لو تأخر البوت شوي)، نشيك إذا الوقت عدى وقت التذكير
    # ولسا ما انبعث تذكير اليوم
    if now >= reminder_threshold and last_reminder_date != today_str:
        await set_bot_state(REMINDER_STATE_KEY, today_str)

        candidates = await fetch_reminder_candidates()
        for row in candidates:
            uid = row["user_id"]
            remaining = max(0, MESSAGES_REQUIRED - row["messages_today"])
            if remaining <= 0:
                continue

            # نستخدم fetch_user (طلب مباشر من الـ API) بدل الاعتماد على guild.get_member
            # يلي بيعتمد على الـ Members Cache وممكن يرجع None للعضو حتى لو كان موجود فعليًا
            # بالسيرفر، فتفوت رسالة التذكير بدون أي خطأ ظاهر.
            try:
                member = await bot.fetch_user(uid)
                await member.send(
                    f"تنبيه ! متبقي لك {remaining} رسائل فقط ليكتمل الستريك اليوم "
                    f"( الستريك الحالي : {row['streak']} ) {REMINDER_EMOJI}"
                )
            except (discord.Forbidden, discord.NotFound):
                pass  # الخاص مقفول عنده أو المستخدم غير موجود

            await mark_reminded(uid)

        print(f"[{now}] تم إرسال تذكيرات الستريك.")


# ---------------- إعادة التصفير اليومية ----------------
@tasks.loop(seconds=30)
async def daily_reset_check():
    now = datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")

    reset_threshold = now.replace(
        hour=RESET_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )

    # نخزن تاريخ آخر تصفير داخل PostgreSQL بدل الذاكرة.
    # بهذا الشكل Restart / Redeploy ما يعيد التصفير مرة ثانية بنفس اليوم.
    last_reset_date = await get_bot_state("last_streak_reset_date")

    if now >= reset_threshold and last_reset_date != today_str:
        await daily_reset_all()
        await set_bot_state("last_streak_reset_date", today_str)
        print(f"[{now}] تم إعادة تعيين الستريك اليومي.")


@bot.event
async def on_ready():
    print(f"✅ البوت شغال باسم {bot.user}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.playing, name="programed by mist")
    )
    bot.add_view(StreakInfoView())  # يخلي الزر شغال بعد أي ريستارت
    try:
        synced = await bot.tree.sync()
        print(f"✅ تم تسجيل {len(synced)} أوامر سلاش.")
    except Exception as e:
        print(f"⚠️ صار خطأ بتسجيل أوامر السلاش: {e}")
    if not daily_reset_check.is_running():
        daily_reset_check.start()
    if not reminder_check.is_running():
        reminder_check.start()


if not TOKEN:
    raise SystemExit("❌ ما في توكن! ضيف DISCORD_TOKEN من إعدادات Variables بمشروع Railway.")

if not DATABASE_URL:
    raise SystemExit("❌ ما في رابط قاعدة بيانات! ضيف DATABASE_URL من إعدادات Variables (بعد ما تضيف خدمة PostgreSQL بمشروع Railway).")

bot.run(TOKEN)
