# بوت الستريك

بوت Discord بسيط: أي شخص يرسل 5 رسائل باليوم بالروم العام، البوت يهنّيه ويحسبله ستريك يوم إضافي. الستريك يتجدد كل يوم الساعة 12 الظهر — إذا ما وصل للعدد المطلوب، الستريك يرجع صفر.

## خطوات التشغيل

### 1. إنشاء البوت على Discord
1. روح على https://discord.com/developers/applications
2. اضغط **New Application** وسمّيه متل ما بدك.
3. من تبويب **Bot**:
   - اضغط **Reset Token** وانسخ الـ Token (بتحتاجه بالخطوة 3).
   - فعّل **MESSAGE CONTENT INTENT** و **SERVER MEMBERS INTENT** (تحت Privileged Gateway Intents).
4. من تبويب **OAuth2 → URL Generator**:
   - اختار Scopes: `bot`
   - اختار Permissions: `Send Messages`, `Read Message History`, `View Channels`, `Use External Emojis`, `Embed Links`
   - افتح الرابط اللي بيتولد وادعي البوت على السيرفر حقك.

### 2. تجهيز الآيدي حق الروم العام
- فعّل **Developer Mode** من إعدادات دسكورد (Settings → Advanced).
- دوس كليك يمين على الروم العام واختار **Copy Channel ID**.

### 3. النشر على Railway

الكود صار مضبوط عشان ياخذ التوكن وآيدي الروم من **Environment Variables** بدل ما تكتبهم جوا الكود (أسلم بكثير لأنك رح ترفع الكود على GitHub أو مباشرة على Railway).

**الطريقة 1: رفع من GitHub (الأسهل للتحديثات المستقبلية)**
1. ارفع مجلد المشروع (`bot.py`, `requirements.txt`, `Procfile`, `runtime.txt`) على ريبو GitHub.
2. روح على https://railway.app وسجل دخول (بيقدر تسجل بحساب GitHub مباشرة).
3. اضغط **New Project → Deploy from GitHub repo** واختار الريبو حقك.

**الطريقة 2: رفع مباشر بدون GitHub**
1. روح على https://railway.app وسجل دخول.
2. اضغط **New Project → Empty Project**.
3. من داخل المشروع اضغط **+ New → Empty Service**، بعدين ارفع الملفات (أو استخدم Railway CLI بالأمر `railway up` من داخل مجلد المشروع).

**بعد ما ينعمل Deploy، بأي طريقة:**
1. روح لتبويب **Variables** بالسيرفس، وضيف:
   | Key | Value |
   |---|---|
   | `DISCORD_TOKEN` | التوكن حق البوت |
   | `GENERAL_CHANNEL_ID` | آيدي الروم العام |
   | `TIMEZONE` | `Asia/Amman` (اختياري، هاد الافتراضي أصلاً) |
   | `MESSAGES_REQUIRED` | `5` (اختياري) |
2. روح لتبويب **Settings → Deploy**، وتأكد إنه نوع السيرفس **Worker** مش **Web** (لأن البوت ما بفتح بورت HTTP). Railway بياخذ هاد تلقائيًا من ملف `Procfile`.
3. Railway بيعمل Deploy تلقائيًا، وبتقدر تتابع اللوجز من تبويب **Deployments** للتأكد إنه ظهرت رسالة `✅ البوت شغال باسم ...`.

> ⚠️ ملاحظة مهمة: Railway ما بيحافظ على الملفات المحلية (متل `streaks.json`) بين كل Deploy جديد، إلا إذا فعّلت **Volume** من تبويب Settings وربطته بمسار المشروع. بدون Volume، بيانات الستريك ممكن تنمسح لما تعمل تحديث/إعادة نشر للبوت. إذا حابب أضبطلك هاد الجزء (Volume) خبرني.

### تشغيل محلي (اختياري، للتجربة قبل الرفع)
```bash
pip install -r requirements.txt
export DISCORD_TOKEN="التوكن_هون"
export GENERAL_CHANNEL_ID="123456789012345678"
python bot.py
```

## ملاحظات
- البوت بينشئ ملف `streaks.json` تلقائيًا لتخزين بيانات الستريك، وبيضل يحتفظ فيها حتى لو أعدت تشغيل البوت (طالما الملف موجود - شوف ملاحظة الـ Volume فوق لأجل Railway).
- زر "شو هو الستريك؟" تحت رسالة التهنئة بيفتح شرح مختصر لكل شخص لحاله (رسالة خاصة ephemeral ما بتضل بالشات).
