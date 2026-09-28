# -*- coding: utf-8 -*-

import subprocess
import smtplib
import os
import re
import socket
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ============ НАСТРОЙКИ ============
HOSTS_FILE   = "/home/tc/scripts/hosts.txt"
OUTPUT_DIR   = "/home/tc/backups"

SSH_USER     = "user"
SSH_PASSWORD = "password"
SSH_PORT     = portssh
SSH_TIMEOUT  = 20

SMTP_SERVER  = "smtp.server"
SMTP_PORT    = port
SMTP_USER    = "email"
SMTP_PASS    = "secret/pass"
MAIL_FROM    = "mailFrom"
MAIL_TO      = ["mailto"]
# ===================================


def read_hosts(path):
    """Читает hosts.txt и возвращает список кортежей (name, ip)."""
    hosts = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                name, ip = line.split("=", 1)
                hosts.append((name.strip(), ip.strip()))
            else:
                hosts.append((line, line))
    return hosts


def safe_name(s):
    """Оставляет в имени только безопасные символы."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def run_export(host):
    """Подключается к микротику по SSH и выполняет /export."""
    cmd = [
        "sshpass", "-p", SSH_PASSWORD,
        "ssh",
        "-p", str(SSH_PORT),
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=%d" % SSH_TIMEOUT,
        "-o", "PreferredAuthentications=password",
        "-o", "PubkeyAuthentication=no",
        "%s@%s" % (SSH_USER, host),
        "/export",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SSH_TIMEOUT + 20
        )
        if result.returncode != 0:
            return None, (result.stderr or "unknown error").strip()
        return result.stdout, None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, str(e)


def save_rsc(name, ip, output, now, hostname):
    """Сохраняет вывод одного микротика в отдельный .rsc файл."""
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    filename = "%s_%s_%s.rsc" % (safe_name(name), safe_name(ip), stamp)
    filepath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# RouterOS export\n")
        f.write("# Device name: %s\n" % name)
        f.write("# Device IP:   %s\n" % ip)
        f.write("# Generated:   %s\n" % now.isoformat())
        f.write("# Source host: %s\n" % hostname)
        f.write("# ============================================\n\n")
        f.write(output)

    return filepath, filename


def send_mail(subject, body, attachments):
    """Отправляет письмо с вложениями через SMTP (STARTTLS)."""
    msg = MIMEMultipart()
    msg["From"] = MAIL_FROM
    msg["To"] = ", ".join(MAIL_TO)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for path in attachments:
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                'attachment; filename="%s"' % os.path.basename(path)
            )
            msg.attach(part)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=60) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(MAIL_FROM, MAIL_TO, msg.as_string())


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    hostname = socket.gethostname()
    now = datetime.now()
    subject = "RouterOS export - %s - %s" % (
        hostname, now.strftime("%Y-%m-%d %H:%M")
    )

    hosts = read_hosts(HOSTS_FILE)
    print("[*] Найдено хостов: %d" % len(hosts))

    saved_files = []
    ok_list = []
    error_list = []

    for name, ip in hosts:
        print("[*] %s (%s)..." % (name, ip))
        output, err = run_export(ip)
        if output is None:
            print("    [!] Ошибка: %s" % err)
            error_list.append((name, ip, err))
            continue

        filepath, filename = save_rsc(name, ip, output, now, hostname)
        saved_files.append(filepath)
        ok_list.append((name, ip))
        print("    [+] Сохранён: %s (%d байт)" % (filename, len(output)))

    body_lines = [
        "Автоматический бэкап RouterOS",
        "Дата:      %s" % now.strftime("%Y-%m-%d %H:%M:%S"),
        "Сервер:    %s" % hostname,
        "Устройств: %d" % len(hosts),
        "Успешно:   %d" % len(ok_list),
        "Ошибок:    %d" % len(error_list),
        "",
        "Успешные экспорты:",
    ]
    for name, ip in ok_list:
        body_lines.append("  + %s (%s)" % (name, ip))
    if error_list:
        body_lines.append("")
        body_lines.append("Ошибки:")
        for name, ip, err in error_list:
            body_lines.append("  - %s (%s): %s" % (name, ip, err))

    body = "\n".join(body_lines)

    if not saved_files:
        print("[!] Нет ни одного успешного экспорта - письмо не отправляем")
        return 1

    try:
        send_mail(subject, body, saved_files)
        print("[*] Письмо отправлено, вложений: %d" % len(saved_files))
    except Exception as e:
        print("[!] Ошибка отправки письма: %s" % e)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
