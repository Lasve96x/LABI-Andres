import os
import platform
import subprocess
import time
import re

import psutil
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv("/home/lasve/LABI/configs/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

CPU_ALERT = int(os.getenv("CPU_ALERT", "85"))
RAM_ALERT = int(os.getenv("RAM_ALERT", "85"))
DISK_ALERT = int(os.getenv("DISK_ALERT", "90"))

ALERT_INTERVAL = int(os.getenv("ALERT_INTERVAL", "60"))
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "600"))

_last_alert_ts = 0  # anti-spam cooldown


def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == ADMIN_ID


def get_metrics():
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    return cpu, ram, disk


def fmt_uptime() -> str:
    try:
        return subprocess.check_output(["uptime", "-p"], text=True).strip()
    except Exception:
        return "uptime non disponibile"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        "✅ LABI Master online.\n"
        "Comandi: /status /uptime /logs /reboot /alerts\n"
        f"Soglie: CPU>{CPU_ALERT}% RAM>{RAM_ALERT}% DISK>{DISK_ALERT}%"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    cpu, ram, disk = get_metrics()

    msg = (
        "🤖 *LABI STATUS*\n\n"
        f"CPU: {cpu}%\n"
        f"RAM: {ram}%\n"
        f"DISK: {disk}%\n\n"
        f"HOST: {platform.node()}\n"
        f"OS: {platform.system()} {platform.release()}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def uptime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(f"⏱️ {fmt_uptime()}")


async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    log_path = "/home/lasve/LABI/logs/master_bot.log"
    err_path = "/home/lasve/LABI/logs/master_bot.err.log"

    def tail(path: str, n: int = 30) -> str:
        if not os.path.exists(path):
            return f"(file non trovato: {path})"
        try:
            out = subprocess.check_output(["tail", "-n", str(n), path], text=True, stderr=subprocess.STDOUT)
            return out.strip() if out.strip() else "(vuoto)"
        except Exception as e:
            return f"(errore lettura log: {e})"

    text = (
        "📄 *master_bot.log* (ultime 30 righe)\n"
        "```text\n" + tail(log_path) + "\n```\n\n"
        "⚠️ *master_bot.err.log* (ultime 30 righe)\n"
        "```text\n" + tail(err_path) + "\n```"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    text = (
        "🔔 ALERT SETTINGS\n\n"
        f"CPU_ALERT: {CPU_ALERT}%\n"
        f"RAM_ALERT: {RAM_ALERT}%\n"
        f"DISK_ALERT: {DISK_ALERT}%\n\n"
        f"ALERT_INTERVAL: {ALERT_INTERVAL}s\n"
        f"ALERT_COOLDOWN: {ALERT_COOLDOWN}s"
    )
    await update.message.reply_text(text)  # niente Markdown


async def reboot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text("♻️ Riavvio Raspberry in corso…")
    subprocess.Popen(["sudo", "reboot"])


async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    global _last_alert_ts

    cpu, ram, disk = get_metrics()
    problems = []
    if cpu >= CPU_ALERT:
        problems.append(f"🔥 CPU alta: {cpu}% (soglia {CPU_ALERT}%)")
    if ram >= RAM_ALERT:
        problems.append(f"🧠 RAM alta: {ram}% (soglia {RAM_ALERT}%)")
    if disk >= DISK_ALERT:
        problems.append(f"💾 DISK alto: {disk}% (soglia {DISK_ALERT}%)")

    if not problems:
        return

    now = int(time.time())
    if now - _last_alert_ts < ALERT_COOLDOWN:
        return

    _last_alert_ts = now
    msg = "🚨 *LABI ALERT*\n\n" + "\n".join(problems) + "\n\n" + f"⏱️ {fmt_uptime()}"
    await context.bot.send_message(chat_id=ADMIN_ID, text=msg)

def sanitize_service_name(name: str) -> str:
    name = name.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", name):
        raise ValueError("Nome non valido (usa a-z 0-9 _ -)")
    return name

def run_systemctl(action: str, service: str) -> str:
    try:
        out = subprocess.check_output(
            ["sudo", "systemctl", action, service],
            text=True,
            stderr=subprocess.STDOUT
        )
        return out.strip() or "OK"
    except subprocess.CalledProcessError as e:
        return (e.output or "").strip()

async def bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    out = subprocess.check_output(
        ["systemctl", "list-units", "--type=service", "--all", "labi-*.service", "--no-pager"],
        text=True
    )
    lines = [l for l in out.splitlines() if "labi-" in l and ".service" in l]
    if not lines:
        await update.message.reply_text("Nessun servizio LABI trovato.")
        return
    await update.message.reply_text(
        "🧩 LABI SERVICES\n\n" + "\n".join(lines[:20])
    )

async def bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    text = update.message.text.strip()
    parts = text.split()

    if len(parts) < 2:
        await update.message.reply_text("Uso: /bot_status example")
        return

    try:
        name = sanitize_service_name(parts[1])
        service = f"labi-{name}.service"
        out = run_systemctl("status", service)
        await update.message.reply_text(out[-3500:])
    except Exception as e:
        await update.message.reply_text(str(e))

async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("Uso: /bot_start example")
        return

    try:
        name = sanitize_service_name(parts[1])
        service = f"labi-{name}.service"
        out = run_systemctl("start", service)
        await update.message.reply_text(f"▶️ {service}\n{out}")
    except Exception as e:
        await update.message.reply_text(str(e))

async def bot_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("Uso: /bot_stop example")
        return

    try:
        name = sanitize_service_name(parts[1])
        service = f"labi-{name}.service"
        out = run_systemctl("stop", service)
        await update.message.reply_text(f"⏹️ {service}\n{out}")
    except Exception as e:
        await update.message.reply_text(str(e))

async def bot_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("Uso: /bot_restart example")
        return

    try:
        name = sanitize_service_name(parts[1])
        service = f"labi-{name}.service"
        out = run_systemctl("restart", service)
        await update.message.reply_text(f"🔄 {service}\n{out}")
    except Exception as e:
        await update.message.reply_text(str(e))

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN mancante. Controlla configs/.env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("bots", bots))
    app.add_handler(CommandHandler("bot_status", bot_status))
    app.add_handler(CommandHandler("bot_start", bot_start))
    app.add_handler(CommandHandler("bot_stop", bot_stop))
    app.add_handler(CommandHandler("bot_restart", bot_restart))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("uptime", uptime_cmd))
    app.add_handler(CommandHandler("logs", logs))
    app.add_handler(CommandHandler("alerts", alerts))
    app.add_handler(CommandHandler("reboot", reboot))
    app.add_handler(MessageHandler(filters.Regex(r"^/alerts(@\w+)?$"), alerts))

    # job monitor automatico
    app.job_queue.run_repeating(monitor_job, interval=ALERT_INTERVAL, first=15)

    app.run_polling()


if __name__ == "__main__":
    main()
