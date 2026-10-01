<div align="center">

# ⚡ FlashTemp Catcher

**Generate a temporary email and grab the verification link or OTP code automatically, then copy it straight to your clipboard.**

![Python](https://img.shields.io/badge/python-3.8%2B-blue?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/built%20with-Playwright-2EAD33?logo=playwright&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

[English](#-english) • [العربية](#-العربية)

</div>

---

## 🇬🇧 English

### What is it?

`flashtemp_catcher.py` is a Python script that automates [flashtemp.email](https://flashtemp.email):

1. Opens the site and clicks **Generate** exactly once.
2. Locks the generated address and copies it to your clipboard.
3. Switches to **read-only mode** (no reload, no second Generate) so the address never changes.
4. Watches the inbox. When a new message arrives it opens it and extracts either:
   - a **verification / activation link**, or
   - a numeric / alphanumeric **OTP code**.
5. Copies the result to your clipboard, plays a sound, and closes the browser.

It works with **any sender** (Google, Facebook, Instagram, X, TikTok, Discord, Claude...). Detection is based on the wording around a code and on link/button text, never on who sent the email.

### ✨ Features

- 🕶️ **Headless by default**: no browser window, only your terminal.
- 🚀 **Fast**: blocks images, fonts, media and ad trackers; one JS round-trip per DOM scan; polls every 0.25 s.
- 🔑 **Smart OTP detection**: 4–8 digits, `123-456`, spaced digits, alphanumeric codes, prefixed codes (`FB-12345`); ignores dates, prices, phone numbers and order IDs.
- 🔗 **Smart link scoring**: ranks links by URL keywords and visible button text; skips unsubscribe / privacy / app-store links.
- 🌍 **Arabic support**: Arabic keywords (كود، رمز، تأكيد...) and Arabic-Indic digit conversion.
- 📋 **Clipboard + sound + desktop notification** the moment the result is ready.
- 🪟 Scans all tabs and iframes, since some messages open in a new tab.

### 📦 Installation

```bash
git clone https://github.com/<your-username>/flashtemp-catcher.git
cd flashtemp-catcher

pip install -r requirements.txt
playwright install chromium
```

> **Linux only:** install a clipboard tool: `sudo apt install xclip`
>
> **Optional:** `pip install plyer` for desktop notifications.

### ▶️ Usage

```bash
python flashtemp_catcher.py            # hidden browser (default)
python flashtemp_catcher.py --show     # show the browser window (debugging)
python flashtemp_catcher.py --debug    # extra detection logs
python flashtemp_catcher.py --no-sound # silent mode
```

**Typical flow**

1. Run the script and wait for `>>> Email (locked): ...`
2. Paste the email (`Ctrl+V`) into the site you're signing up on.
3. Leave the script running.
4. When the message arrives, the code/link is printed and copied. Paste it (`Ctrl+V`). Done. ✅

Press `Ctrl+C` to stop at any time.

### ⚙️ Configuration

Edit the constants at the top of `flashtemp_catcher.py`:

| Setting | Default | Description |
|---|---|---|
| `POLL_INTERVAL_SEC` | `0.25` | Inbox polling interval (seconds) |
| `GENERATE_WAIT_TIMEOUT_SEC` | `25` | Max wait for the Generate button |
| `EMAIL_WAIT_TIMEOUT_SEC` | `60` | Max wait for the email after Generate |
| `MESSAGE_OPEN_WAIT_SEC` | `8` | Max wait for message content after opening a row |
| `FALLBACK_GRACE_SEC` | `8` | Delay before accepting a keyword-less link |
| `MAX_ROW_RETRIES` | `3` | Retries if clicking a message row fails |
| `INBOX_MAX_WAIT_SEC` | `0` | Give up after N seconds (`0` = wait forever) |
| `HEADLESS` | `True` | Hidden browser |
| `PLAY_SOUND` | `True` | Success sound |
| `PREFER_CODE_OVER_LINK` | `False` | If a message has both: `False` = link, `True` = code |
| `BLOCK_HEAVY_RESOURCES` | `True` | Block images/ads for speed (set `False` if the site misbehaves) |
| `CLICK_INBOX_REFRESH` | `False` | Disabled because Refresh may generate a new email |

### 🔢 Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Unexpected error |
| `2` | Email didn't appear / timed out waiting for a message |
| `3` | Playwright timeout |
| `4` | Playwright error (browser may have been closed) |
| `130` | Stopped by the user (`Ctrl+C`) |

### 🩺 Troubleshooting

- **"Generate button not found"** → run with `--show`; the site layout may have changed, a captcha may be present, or try `BLOCK_HEAVY_RESOURCES = False`.
- **Nothing copied to clipboard** → on Linux install `xclip`; otherwise copy from the terminal.
- **Code not detected** → run with `--debug` and check `flashtemp_catcher_error.png` if it was saved.
- **Wrong link picked** → change `PREFER_CODE_OVER_LINK` or tune the keyword lists at the top of the file.

### ⚠️ Notes & Disclaimer

- The script depends on the current layout of flashtemp.email. If the site changes, the selector lists at the top of the file may need updating.
- Temporary inboxes are **public-ish**: anyone who knows the address can read it. Use them only for tests and throw-away accounts, **never** for banking, work, or anything important.
- Use this tool in line with the terms of service of flashtemp.email and of every site you sign up on. You are responsible for how you use it.
- This project is not affiliated with flashtemp.email.
- Nothing is stored on your machine except the optional error screenshot.

### 🤝 Contributing

Issues and pull requests are welcome. If the site layout changes and something breaks, please open an issue with the `--debug` output.

### 📄 License

[MIT](LICENSE)

---

<div dir="rtl">

## 🇪🇬 العربية

### إيه ده؟

**FlashTemp Catcher** سكربت بايثون بيشغّل موقع الإيميلات المؤقتة [flashtemp.email](https://flashtemp.email) لوحده:

1. يفتح الموقع ويدوس **Generate** مرة واحدة بس.
2. يثبّت الإيميل وينسخه على الحافظة علطول.
3. يشتغل في وضع "قراءة فقط" (مفيش Reload ولا Generate تاني) عشان الإيميل مايتغيرش.
4. يراقب الـ Inbox، وأول ما توصل رسالة جديدة يفتحها ويطلّع منها **لينك التفعيل** أو **كود التحقق (OTP)**.
5. ينسخ النتيجة، يشغّل صوت نجاح، ويقفل المتصفح.

مش فارق مين اللي باعت الرسالة (جوجل، فيسبوك، انستجرام، ديسكورد...)، السكربت بيحكم من الكلام اللي حوالين الكود ومن نص الأزرار.

### ✨ المميزات

- 🕶️ بيشتغل مخفي (Headless)، مفيش نافذة متصفح.
- 🚀 سريع جدًا: بيحجب الصور والإعلانات والخطوط، وبيفحص كل 0.25 ثانية.
- 🔑 اكتشاف ذكي للأكواد (4–8 أرقام، `123-456`، حروف وأرقام...) وبيتجاهل التواريخ والأسعار وأرقام التليفونات.
- 🔗 تقييم ذكي للينكات بناءً على الكلمات في الرابط ونص الزرار.
- 🌍 بيدعم الكلمات العربي (كود، رمز، تأكيد، تحقق) والأرقام العربية.
- 📋 نسخ تلقائي للحافظة + صوت + إشعار.

### 📦 التثبيت

</div>

```bash
git clone https://github.com/<your-username>/flashtemp-catcher.git
cd flashtemp-catcher
pip install -r requirements.txt
playwright install chromium
# لينكس فقط:
sudo apt install xclip
```

<div dir="rtl">

### ▶️ التشغيل

</div>

```bash
python flashtemp_catcher.py            # التشغيل العادي (مخفي)
python flashtemp_catcher.py --show     # يظهر المتصفح
python flashtemp_catcher.py --debug    # تفاصيل زيادة
python flashtemp_catcher.py --no-sound # بدون صوت
```

<div dir="rtl">

**خطوات الاستخدام**

1. شغّل السكربت واستنى لحد ما يظهر `>>> Email (locked): ...`
2. اعمل Paste (`Ctrl+V`) للإيميل في الموقع اللي بتسجل فيه.
3. سيب السكربت شغال.
4. أول ما الرسالة توصل هيطبع الكود أو اللينك وينسخه، اعمل Paste وخلاص ✅

لإيقاف السكربت: `Ctrl+C`.

### ⚠️ تنبيه

- السكربت معتمد على شكل موقع flashtemp.email الحالي، ولو الموقع اتغير ممكن تحتاج تعدّل الـ selectors.
- الإيميلات المؤقتة أي حد يعرف العنوان يقدر يقرأ الرسائل، فاستخدمها للتجارب والحسابات المؤقتة بس، **مش** للبنوك أو الشغل أو أي حاجة مهمة.
- استخدم الأداة بما يتوافق مع شروط استخدام الموقع. المسؤولية عليك.
- المشروع غير تابع لموقع flashtemp.email.

</div>
