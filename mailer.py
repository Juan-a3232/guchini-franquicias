import os
import base64
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

CALENDAR_LINK = os.environ.get("CALENDAR_LINK", "")

BROCHURE_PATH = os.path.join(os.path.dirname(__file__), "Brochure Guchini.pdf")


def _get_access_token() -> str:
    client_id     = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "")

    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret,
    })
    if not resp.ok:
        raise Exception(f"OAuth {resp.status_code}: {resp.text}")
    return resp.json()["access_token"]


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    gmail_from = os.environ.get("GMAIL_FROM", "franquicias@guchini.com.ar")
    if not os.environ.get("GMAIL_REFRESH_TOKEN"):
        msg = "GMAIL_REFRESH_TOKEN no configurado"
        print(f"[mailer] {msg}", flush=True)
        return False, msg
    try:
        access_token = _get_access_token()
        mime = MIMEText(body)
        mime["to"]      = to
        mime["from"]    = f"Guchini Franquicias <{gmail_from}>"
        mime["subject"] = subject
        mime["cc"]      = gmail_from
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        resp = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
        resp.raise_for_status()
        print(f"[mailer] ✓ Enviado a {to}: {subject}", flush=True)
        return True, "ok"
    except Exception as e:
        print(f"[mailer] ✗ Error enviando a {to}: {e}", flush=True)
        return False, str(e)


def mail_bienvenida(nombre: str, email: str) -> bool:
    subject = "Recibimos tu solicitud · Guchini Franquicias"
    body = f"""Hola {nombre},

Gracias por tu interés en ser parte de Guchini. Recibimos tu solicitud y estamos analizando tu perfil junto al equipo.

En los próximos días vamos a estar en contacto con novedades.

¡Saludos!
Equipo Guchini"""
    ok, _ = send_email(email, subject, body)
    return ok


def mail_convocatoria(nombre: str, email: str) -> bool:
    gmail_from = os.environ.get("GMAIL_FROM", "franquicias@guchini.com.ar")
    if not os.environ.get("GMAIL_REFRESH_TOKEN"):
        print("[mailer] GMAIL_REFRESH_TOKEN no configurado", flush=True)
        return False

    link = CALENDAR_LINK or "[LINK_CALENDARIO]"
    subject = "Tu perfil fue seleccionado · Guchini Franquicias"
    body = f"""Hola {nombre},

Buenas noticias — tu perfil destacó entre los candidatos y queremos avanzar.

Te adjuntamos el brochure de Guchini con todos los detalles de la franquicia. El próximo paso es una reunión virtual con el equipo.

Agendá un slot en el calendario desde acá:
{link}

¡Esperamos tu mensaje!
Guchini"""

    try:
        access_token = _get_access_token()

        mime = MIMEMultipart()
        mime["to"]      = email
        mime["from"]    = f"Guchini Franquicias <{gmail_from}>"
        mime["subject"] = subject
        mime["cc"]      = gmail_from
        mime.attach(MIMEText(body))

        # Adjuntar brochure si existe
        if os.path.exists(BROCHURE_PATH):
            with open(BROCHURE_PATH, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename="Brochure Guchini.pdf")
            mime.attach(part)
            print(f"[mailer] Brochure adjuntado ({os.path.getsize(BROCHURE_PATH)//1024} KB)", flush=True)
        else:
            print(f"[mailer] ⚠ Brochure no encontrado en {BROCHURE_PATH}", flush=True)

        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        resp = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
        resp.raise_for_status()
        print(f"[mailer] ✓ Convocatoria enviada a {email}", flush=True)
        return True
    except Exception as e:
        print(f"[mailer] ✗ Error enviando convocatoria a {email}: {e}", flush=True)
        return False
