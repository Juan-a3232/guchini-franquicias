import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_FROM         = os.environ.get("GMAIL_FROM", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
CALENDAR_LINK      = os.environ.get("CALENDAR_LINK", "")
WELCOME_CUTOFF_ID  = int(os.environ.get("WELCOME_CUTOFF_ID", "683"))


def send_email(to: str, subject: str, body: str) -> bool:
    if not GMAIL_FROM or not GMAIL_APP_PASSWORD:
        print(f"[mailer] Credenciales no configuradas — mail no enviado a {to}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Guchini Franquicias <{GMAIL_FROM}>"
        msg["To"]      = to
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_FROM, to, msg.as_string())
        print(f"[mailer] ✓ Enviado a {to}: {subject}")
        return True
    except Exception as e:
        print(f"[mailer] ✗ Error enviando a {to}: {e}")
        return False


def mail_bienvenida(nombre: str, email: str) -> bool:
    subject = "Recibimos tu solicitud · Guchini Franquicias"
    body = f"""Hola {nombre},

Gracias por tu interés en ser parte de Guchini. Recibimos tu solicitud y estamos analizando tu perfil junto al equipo.

En los próximos días vamos a estar en contacto con novedades.

¡Saludos!
Equipo Guchini"""
    return send_email(email, subject, body)


def mail_convocatoria(nombre: str, email: str) -> bool:
    link = CALENDAR_LINK or "[LINK_CALENDARIO]"
    subject = "Tu perfil fue seleccionado · Guchini Franquicias"
    body = f"""Hola {nombre},

Buenas noticias — tu perfil destacó entre los candidatos y queremos avanzar.

El próximo paso es una primera reunión virtual con el equipo de Guchini para conocernos y contarte los detalles de la franquicia.

Para coordinar la reunión, agendá un slot en el calendario desde acá:
{link}

¡Esperamos tu mensaje!
Guchini"""
    return send_email(email, subject, body)
