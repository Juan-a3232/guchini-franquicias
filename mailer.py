import os
import base64
import requests
from email.mime.text import MIMEText

CALENDAR_LINK     = os.environ.get("CALENDAR_LINK", "")
WELCOME_CUTOFF_ID = int(os.environ.get("WELCOME_CUTOFF_ID", "683"))


def _get_access_token() -> str:
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "refresh_token",
        "refresh_token": os.environ.get("GMAIL_REFRESH_TOKEN", ""),
        "client_id":     os.environ.get("GMAIL_CLIENT_ID", ""),
        "client_secret": os.environ.get("GMAIL_CLIENT_SECRET", ""),
    })
    resp.raise_for_status()
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
