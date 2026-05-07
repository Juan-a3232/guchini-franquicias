import os
import base64
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GMAIL_FROM        = os.environ.get("GMAIL_FROM", "franquicias@guchini.com.ar")
CALENDAR_LINK     = os.environ.get("CALENDAR_LINK", "")
WELCOME_CUTOFF_ID = int(os.environ.get("WELCOME_CUTOFF_ID", "683"))

GMAIL_CLIENT_ID     = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "")


def _gmail_service():
    creds = Credentials(
        token=None,
        refresh_token=GMAIL_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GMAIL_CLIENT_ID,
        client_secret=GMAIL_CLIENT_SECRET,
    )
    return build("gmail", "v1", credentials=creds)


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    if not GMAIL_REFRESH_TOKEN:
        msg = "GMAIL_REFRESH_TOKEN no configurado"
        print(f"[mailer] {msg}", flush=True)
        return False, msg
    try:
        service = _gmail_service()
        mime = MIMEText(body)
        mime["to"] = to
        mime["from"] = f"Guchini Franquicias <{GMAIL_FROM}>"
        mime["subject"] = subject
        mime["cc"] = GMAIL_FROM
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
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
    link = CALENDAR_LINK or "[LINK_CALENDARIO]"
    subject = "Tu perfil fue seleccionado · Guchini Franquicias"
    body = f"""Hola {nombre},

Buenas noticias — tu perfil destacó entre los candidatos y queremos avanzar.

El próximo paso es una primera reunión virtual con el equipo de Guchini para conocernos y contarte los detalles de la franquicia.

Para coordinar la reunión, agendá un slot en el calendario desde acá:
{link}

¡Esperamos tu mensaje!
Guchini"""
    ok, _ = send_email(email, subject, body)
    return ok
