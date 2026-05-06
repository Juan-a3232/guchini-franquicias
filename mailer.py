import os
import resend

RESEND_API_KEY    = os.environ.get("RESEND_API_KEY", "")
GMAIL_FROM        = os.environ.get("GMAIL_FROM", "franquicias@guchini.com.ar")
CALENDAR_LINK     = os.environ.get("CALENDAR_LINK", "")
WELCOME_CUTOFF_ID = int(os.environ.get("WELCOME_CUTOFF_ID", "683"))

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


def send_email(to: str, subject: str, body: str) -> bool:
    if not RESEND_API_KEY:
        print(f"[mailer] RESEND_API_KEY no configurada — mail no enviado a {to}")
        return False
    try:
        # Usar dominio verificado si está configurado, sino el de prueba de Resend
        from_addr = f"Guchini Franquicias <{GMAIL_FROM}>" if os.environ.get("DOMAIN_VERIFIED") else "Guchini Franquicias <onboarding@resend.dev>"
        resend.Emails.send({
            "from": from_addr,
            "to": [to],
            "subject": subject,
            "text": body,
        })
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
