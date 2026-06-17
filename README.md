# 🛡️ AntiNuke Discord Bot

A powerful server protection bot with AntiNuke, AntiMod, and swear word filtering — deployable to Railway.

---

## ⚙️ Setup (Railway Deployment)

### 1. Fork / upload this project to GitHub

### 2. Create a new Railway project
- Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
- Select your repo

### 3. Set environment variable
In Railway → your service → **Variables** tab, add:
```
DISCORD_TOKEN = your_bot_token_here
```

### 4. Railway auto-detects Python
Railway will automatically install `requirements.txt` and run `bot.py`. No extra config needed.

### 5. Required Bot Permissions
When inviting your bot to a server, enable:
- ✅ Administrator (easiest — covers everything)

Or individually:
- ✅ Ban Members
- ✅ Manage Channels
- ✅ Moderate Members (for timeout)
- ✅ View Audit Log
- ✅ Manage Messages
- ✅ Send Messages
- ✅ Read Message History

### 6. Privileged Intents (Discord Developer Portal)
Go to your app → **Bot** → enable:
- ✅ Server Members Intent
- ✅ Message Content Intent

---

## 📋 Commands

All commands require **Administrator** permission.

| Command | Description |
|---|---|
| `.antinuke` | Show current status, log channel & whitelist |
| `.antinuke enable` | Enable all protections |
| `.antinuke disable` | Disable all protections |
| `.antinuke setlog #channel` | Set the log channel for all alerts |
| `.antinuke whitelist` | View the whitelist |
| `.antinuke whitelist add @user` | Add a user to bypass all protections |
| `.antinuke whitelist remove @user` | Remove a user from the whitelist |

---

## 🛡️ Features

### 🔴 AntiNuke — Mass Channel Deletion
- **Trigger:** More than 2 channels deleted within 5 seconds
- **Action:** Actor is **banned** + all deleted channels are **restored**
- **Exempt:** Server owner + whitelisted users only

### 🟡 AntiMod — Unauthorized Mentions
- **Trigger:** Anyone (including admins) pings @everyone, @here, or any role without being whitelisted
- **Action:** Message deleted → DM warning → **10 minute timeout**
- **Exempt:** Server owner + whitelisted users only

### 🟠 Swear Word Filter
- **Trigger:** Message containing blacklisted profanity
- **Action:** Message deleted → DM warning
- **Exempt:** Server owner + whitelisted users only

### 📋 Logging
- Every action is logged to your **configured log channel**
- Every action is also **DM'd to the server owner** automatically

---

## 🔧 Customization

In `bot.py`:
```python
NUKE_THRESHOLD = 2   # channels deleted to trigger antinuke
NUKE_WINDOW    = 5   # time window in seconds

SWEAR_WORDS = [...]  # add or remove words freely
```

---

## 📁 Files

| File | Purpose |
|---|---|
| `bot.py` | Main bot code |
| `requirements.txt` | Python dependencies |
| `antinuke_data.json` | Auto-created — stores settings & whitelist |
