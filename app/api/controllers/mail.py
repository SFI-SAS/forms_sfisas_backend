import mimetypes
import os
import smtplib
import json
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime
from typing import List, Dict

from fastapi import UploadFile

# Configuración del servidor SMTP alternativo
MAIL_HOST_ALT = os.getenv("MAIL_HOST_ALT")
MAIL_PORT_ALT = os.getenv("MAIL_PORT_ALT")
MAIL_USERNAME_ALT = os.getenv("MAIL_USERNAME_ALT")
MAIL_PASSWORD_ALT = os.getenv("MAIL_PASSWORD_ALT")
MAIL_FROM_ADDRESS_ALT = os.getenv("MAIL_FROM_ADDRESS_ALT")

def send_email_daily_forms(user_email: str, user_name: str, forms: List[Dict]) -> bool:

    try:
        # Validar que los datos sean correctos
        if not user_email or not user_name:
            print(f"⚠️ Datos inválidos para el correo: user_email={user_email}, user_name={user_name}")
            return False

        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Construcción del HTML con los formularios
        form_list_html = "".join(
            f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #ddd;">
                    <h3 style="color: #00498C; margin: 5px 0;">{form.get('title', 'Formulario sin título')}</h3>
                    <p style="margin: 5px 0; color: #555;">{form.get('description', 'Sin descripción')}</p>
                </td>
            </tr>
            """ 
            for form in forms
        )


        # Verificar que haya formularios antes de enviar el email
        if not form_list_html:
            print(f"⚠️ No hay formularios para enviar a {user_email}.")
            return False

        # Construcción del mensaje
        msg = EmailMessage()
        subject = f"📋 Formulario(s) Pendiente(s) para Hoy - {current_date}"
        msg["Subject"] = subject
        msg["From"] = formataddr(("SFI SAS", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = formataddr((user_name, user_email))

        html_content = f"""
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-size: 17px; text-align: center; padding: 40px; background-color: #f4f4f4;">

    <table align="center" style="width: 100%; max-width: 500px; background-color: white; border-radius: 10px; box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1); padding: 25px;">
        <tr>
            <td align="center">
                <h2 style="color: #00498C;">📋 Formularios Pendientes</h2>
                <p>Estimado/a <strong>{user_name}</strong>,</p>
                <p>Isometría le recuerda que tiene formularios asignados a su usuario que deben ser completados el día de hoy.</p>

                <table style="width: 100%; text-align: left; margin-top: 15px; border-collapse: collapse;">
                    {form_list_html}
                </table>

                <p style="margin-top: 20px;">Le solicitamos que complete estos formularios a la brevedad.</p>
                                        <hr style="margin: 30px 0;">
                        <p style="font-size: 13px; color: #888;">Enviado el <strong>{current_date}</strong></p>
            </td>
        </tr>
    </table>

    

</body>
</html>

        """

        if not html_content:
            print("⚠️ El contenido del email está vacío, no se enviará el correo.")
            return False

        msg.set_content(html_content, subtype="html")

        # Enviar el correo usando SMTP alternativo
        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)

        print(f"📧 Correo enviado exitosamente a {user_email}.")
        return True

    except Exception as e:
        print(f"❌ Error al enviar el correo a {user_email}: {str(e)}")
        return False


from datetime import datetime

def send_email_with_attachment(
    to_email: str,
    name_form: str,
    to_name: str,
    upload_file: UploadFile,
) -> bool:
    try:
        msg = EmailMessage()
        msg["Subject"] = "📎 Respuestas adjuntas - Isometría"
        msg["From"] = formataddr(("SFI SAS", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = formataddr((to_name, to_email))

        current_date = datetime.now().strftime("%d/%m/%Y")

        # HTML elegante con name_form
        html_content = f"""
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; font-size: 16px; text-align: center; padding: 40px; background-color: #f4f4f4;">

            <table align="center" style="width: 100%; max-width: 520px; background-color: white; border-radius: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); padding: 25px;">
                <tr>
                    <td align="center">
                        <h2 style="color: #00498C;">📋 Respuestas de formulario</h2>
                        
                        <p>Se adjunta el archivo que contiene las respuestas proporcionadas por el usuario <strong>{to_name}</strong> correspondientes al formulario <strong>“{name_form}”</strong>.</p>
                        <p>Por favor, revise el documento adjunto.</p>

                        <hr style="margin: 30px 0;">
                        <p style="font-size: 13px; color: #888;">Enviado el <strong>{current_date}</strong></p>
                    </td>
                </tr>
            </table>

        </body>
        </html>
        """

        # Texto alternativo por si el correo no soporta HTML
        msg.set_content(
            f"Estimado/a {to_name},\n\nAdjunto encontrará el archivo con las respuestas del formulario \"{name_form}\"."
        )

        msg.add_alternative(html_content, subtype="html")

        # Adjuntar archivo tal cual fue subido
        upload_file.file.seek(0)
        file_data = upload_file.file.read()

        mime_type, _ = mimetypes.guess_type(upload_file.filename)
        maintype, subtype = ("application", "octet-stream")
        if mime_type:
            maintype, subtype = mime_type.split("/")

        msg.add_attachment(
            file_data,
            maintype=maintype,
            subtype=subtype,
            filename=upload_file.filename
        )

        # Envío del correo
        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)

        print(f"✅ Archivo enviado a {to_email}")
        return True

    except Exception as e:
        print(f"❌ Error al enviar archivo a {to_email}: {str(e)}")
        return False
