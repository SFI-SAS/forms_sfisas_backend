import mimetypes
import os
import smtplib
import json
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime
from typing import List, Dict

from fastapi import UploadFile

from app.models import Response, Form
from app.schemas import EmailAnswerItem


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
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
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
                <p>Safemetrics le recuerda que tiene formularios asignados a su usuario que deben ser completados.</p>

                <table style="width: 100%; text-align: left; margin-top: 15px; border-collapse: collapse;">
                    {form_list_html}
                </table>

                <p style="margin-top: 20px;">Le solicitamos que complete estos formularios a la brevedad.</p>
                
                 <a href="https://forms.sfisas.com.co/" style="color: #007bff; text-decoration: underline;" target="_blank">
  
</a>
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
        msg["Subject"] = "📎 Respuestas adjuntas - Safemetrics"
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
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



def send_welcome_email(email: str, name: str, password: str) -> bool:
    try:
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        msg = EmailMessage()
        msg["Subject"] = "👋 ¡Bienvenido a Safemetrics!"
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = formataddr((name, email))

        html_content = f"""
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; font-size: 16px; text-align: center; padding: 40px; background-color: #f4f4f4;">

            <table align="center" style="width: 100%; max-width: 520px; background-color: white; border-radius: 12px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); padding: 25px;">
                <tr>
                    <td align="center">
                        <h2 style="color: #00498C;">¡Bienvenido a Safemetrics, {name}!</h2>
                        
                        <p>Tu cuenta ha sido creada con éxito. A continuación, te compartimos tus credenciales de acceso:</p>            
                        <ul style="list-style: none; padding: 0; text-align: left; display: inline-block;">
                            <li><strong>Email:</strong> {email}</li>
                            <li><strong>Contraseña:</strong> {password}</li>
                        </ul>
                      
                      


                        <hr style="margin: 30px 0;">
                      
                             <a href="https://forms.sfisas.com.co/" style="color: #007bff; text-decoration: underline;" target="_blank">
  Ir a Safemetrics
</a>
                      <br>
                        <p style="font-size: 13px; color: #888;">Enviado el <strong>{current_date}</strong></p>
                    </td>
                </tr>
            </table>

        </body>
        </html>
        """

        msg.set_content(html_content, subtype="html")

        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)

        print(f"📧 Correo de bienvenida enviado exitosamente a {email}.")
        return True

    except Exception as e:
        print(f"❌ Error al enviar el correo de bienvenida a {email}: {str(e)}")
        return False
    
    
    

def send_email_plain_approval_status(
    to_email: str,
    name_form: str,
    to_name: str,
    body_text: str,
    subject: str  # Añadimos el parámetro 'subject'
) -> bool:
    try:
        msg = EmailMessage()
        msg["Subject"] = subject  # Usamos el parámetro 'subject' aquí
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = formataddr((to_name, to_email))

        current_date = datetime.now().strftime("%d/%m/%Y")

        # Aquí ajustamos el contenido HTML para reflejar que el formato fue autorizado
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; font-size: 16px; padding: 20px;">
            
            <p>El formato <strong>{name_form}</strong> ha sido autorizado.</p>
           
                        <pre style="background-color: #f4f4f4; padding: 15px; border-radius: 5px; font-family: monospace;">
{body_text}
            </pre>
            <p style="font-size: 12px; color: #999;">Enviado el {current_date}</p>
        </body>
        </html>
        """

        msg.set_content(f"Estimado/a {to_name},\n\n{body_text}")
        msg.add_alternative(html_content, subtype="html")

        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)

        print(f"✅ Correo enviado a {to_email}")
        return True

    except Exception as e:
        print(f"❌ Error al enviar correo a {to_email}: {str(e)}")
        return False


def send_email_plain_approval_status_vencidos(
    to_email: str,
    name_form: str,
    to_name: str,
    body_html: str,   # Ahora es un string HTML
    subject: str
) -> bool:
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = formataddr((to_name, to_email))

        current_date = datetime.now().strftime("%d/%m/%Y")

        # 🔄 Construir el cuerpo del correo
        msg.set_content(f"Estimado/a {to_name},\n\nAprobaciones vencidas para el formato {name_form}.")
        msg.add_alternative(body_html, subtype="html")  # 💡 Aquí ya pasamos el HTML directamente

        # 📬 Enviar el correo
        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)

        print(f"✅ Correo enviado a {to_email}")
        return True

    except Exception as e:
        print(f"❌ Error al enviar correo a {to_email}: {str(e)}")
        return False


def send_email_aprovall_next(
    to_email: str,
    name_form: str,
    to_name: str,
    body_html: str,
    subject: str
) -> bool:
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = formataddr((to_name, to_email))

        msg.set_content(f"Estimado/a {to_name},\n\nAprobaciones vencidas para el formato {name_form}.")
        msg.add_alternative(body_html, subtype="html")

        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)

        print(f"✅ Correo enviado a {to_email}")
        return True

    except Exception as e:
        print(f"❌ Error al enviar correo a {to_email}: {str(e)}")
        return False


def send_rejection_email(to_email: str, to_name: str, formato: dict, usuario_respondio: dict, aprobador_rechazo: dict, todos_los_aprobadores: list):
    try:
        msg = EmailMessage()
        msg["Subject"] = f"Formulario rechazado: {formato['titulo']}"
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = formataddr((to_name, to_email))

        current_date = datetime.now().strftime("%d/%m/%Y")

        # HTML de lista de aprobadores
        aprobadores_html = ""
        for aprobador in todos_los_aprobadores:
            aprobadores_html += f"""
                <tr>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador['secuencia']}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador['nombre']}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador['email']}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador['status'].value.capitalize()}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador.get('mensaje', 'Sin mensaje')}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador.get('reviewed_at', 'No disponible')}</td>
                </tr>
            """

        html_content = f"""
        <html>
        <body style="font-family: 'Segoe UI', sans-serif; background-color: #f9f9f9; margin: 0; padding: 30px;">
            <table width="100%" cellspacing="0" cellpadding="0" style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 30px;">
                <tr>
                    <td>
                        <h2 style="color: #b02a37; margin-bottom: 10px;">Formulario Rechazado</h2>
<p style="font-size: 16px; color: #333;">
    Estimado/a <strong>{to_name}</strong>,<br><br>
    Le informamos que las respuestas al formulario titulado <strong>“{formato['titulo']}”</strong> han sido <span style="color: #b02a37;"><strong>rechazadas</strong></span>.
</p>


                        <hr style="margin: 25px 0; border: none; border-top: 1px solid #e0e0e0;">

                        <h3 style="color: #333; font-size: 17px;">📄 Detalles del Formulario</h3>
                        <ul style="padding-left: 20px; color: #555; font-size: 15px;">
                            <li><strong>Título:</strong> {formato['titulo']}</li>
                            <li><strong>Descripción:</strong> {formato['descripcion']}</li>
                            <li><strong>Tipo:</strong> {formato['tipo_formato'].capitalize()}</li>
                            <li><strong>Creado por:</strong> {formato['creado_por']['nombre']} ({formato['creado_por']['email']})</li>
                        </ul>

                        <h3 style="color: #333; font-size: 17px;">👤 Usuario que respondió</h3>
                        <ul style="padding-left: 20px; color: #555; font-size: 15px;">
                            <li><strong>Nombre:</strong> {usuario_respondio['nombre']}</li>
                            <li><strong>Email:</strong> {usuario_respondio['email']}</li>
                            <li><strong>Teléfono:</strong> {usuario_respondio['telefono']}</li>
                            <li><strong>Documento:</strong> {usuario_respondio['num_documento']}</li>
                        </ul>

                        <h3 style="color: #333; font-size: 17px;">🔒 Revisión</h3>
                        <ul style="padding-left: 20px; color: #555; font-size: 15px;">
                            <li><strong>Revisado por:</strong> {aprobador_rechazo['nombre']} ({aprobador_rechazo['email']})</li>
                            <li><strong>Mensaje:</strong> {aprobador_rechazo.get('mensaje', 'Sin mensaje')}</li>
                            <li><strong>Fecha de revisión:</strong> {aprobador_rechazo.get('reviewed_at', 'No disponible')}</li>
                        </ul>

                        <h3 style="color: #333; font-size: 17px;">📋 Todos los aprobadores</h3>
                        <table width="100%" style="border-collapse: collapse; font-size: 14px;">
                            <thead>
                                <tr style="background-color: #f0f0f0;">
                                    <th style="padding: 5px; border: 1px solid #ccc;">Secuencia</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Nombre</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Email</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Estado</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Mensaje</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Fecha</th>
                                </tr>
                            </thead>
                            <tbody>
                                {aprobadores_html}
                            </tbody>
                        </table>

                        <p style="font-size: 14px; color: #999; margin-top: 30px;">
                            Enviado el {current_date} 
                        </p>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        msg.set_content(
            f"El formulario \"{formato['titulo']}\" ha sido rechazado por {aprobador_rechazo['nombre']}."
        )
        msg.add_alternative(html_content, subtype="html")

        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)

        print(f"✅ Correo de rechazo enviado a {to_email}")
        return True

    except Exception as e:
        print(f"❌ Error al enviar correo de rechazo a {to_email}: {str(e)}")
        return False



def send_reconsideration_email(to_email: str, to_name: str, formato: dict, usuario_solicita: dict, mensaje_reconsideracion: str, aprobador_que_rechazo: dict, todos_los_aprobadores: list):
    try:
        msg = EmailMessage()
        msg["Subject"] = f"Solicitud de reconsideración: {formato['titulo']}"
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = formataddr((to_name, to_email))

        current_date = datetime.now().strftime("%d/%m/%Y")

        # HTML de lista de aprobadores
        aprobadores_html = ""
        for aprobador in todos_los_aprobadores:
            aprobadores_html += f"""
                <tr>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador['secuencia']}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador['nombre']}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador['email']}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador['status'].value.capitalize()}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador.get('mensaje', 'Sin mensaje')}</td>
                    <td style="padding: 5px; border: 1px solid #ccc;">{aprobador.get('reviewed_at', 'No disponible')}</td>
                </tr>
            """

        html_content = f"""
        <html>
        <body style="font-family: 'Segoe UI', sans-serif; background-color: #f9f9f9; margin: 0; padding: 30px;">
            <table width="100%" cellspacing="0" cellpadding="0" style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 30px;">
                <tr>
                    <td>
                        <h2 style="color: #f39c12; margin-bottom: 10px;">🔄 Solicitud de Reconsideración</h2>
                        <p style="font-size: 16px; color: #333;">
                            Estimado/a <strong>{to_name}</strong>,<br><br>
                            Le informamos que <strong>{usuario_solicita['nombre']}</strong> ha solicitado una reconsideración 
                            para el formulario <strong>"{formato['titulo']}"</strong> que fue previamente rechazado.
                        </p>

                        <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 5px; padding: 15px; margin: 20px 0;">
                            <h4 style="color: #856404; margin: 0 0 10px 0;">💬 Mensaje de reconsideración:</h4>
                            <p style="color: #856404; margin: 0; font-style: italic;">"{mensaje_reconsideracion}"</p>
                        </div>

                        <hr style="margin: 25px 0; border: none; border-top: 1px solid #e0e0e0;">

                        <h3 style="color: #333; font-size: 17px;">📄 Detalles del Formulario</h3>
                        <ul style="padding-left: 20px; color: #555; font-size: 15px;">
                            <li><strong>Título:</strong> {formato['titulo']}</li>
                            <li><strong>Descripción:</strong> {formato['descripcion']}</li>
                            <li><strong>Creado por:</strong> {formato['creado_por']['nombre']} ({formato['creado_por']['email']})</li>
                        </ul>

                        <h3 style="color: #333; font-size: 17px;">👤 Usuario que solicita reconsideración</h3>
                        <ul style="padding-left: 20px; color: #555; font-size: 15px;">
                            <li><strong>Nombre:</strong> {usuario_solicita['nombre']}</li>
                            <li><strong>Email:</strong> {usuario_solicita['email']}</li>
                            <li><strong>Teléfono:</strong> {usuario_solicita['telefono']}</li>
                            <li><strong>Documento:</strong> {usuario_solicita['num_documento']}</li>
                        </ul>

                        <h3 style="color: #333; font-size: 17px;">❌ Aprobador que rechazó originalmente</h3>
                        <ul style="padding-left: 20px; color: #555; font-size: 15px;">
                            <li><strong>Nombre:</strong> {aprobador_que_rechazo['nombre']} ({aprobador_que_rechazo['email']})</li>
                            <li><strong>Motivo del rechazo:</strong> {aprobador_que_rechazo.get('mensaje', 'Sin mensaje')}</li>
                            <li><strong>Fecha de rechazo:</strong> {aprobador_que_rechazo.get('reviewed_at', 'No disponible')}</li>
                        </ul>

                        <h3 style="color: #333; font-size: 17px;">📋 Todos los aprobadores</h3>
                        <table width="100%" style="border-collapse: collapse; font-size: 14px;">
                            <thead>
                                <tr style="background-color: #f0f0f0;">
                                    <th style="padding: 5px; border: 1px solid #ccc;">Secuencia</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Nombre</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Email</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Estado</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Mensaje</th>
                                    <th style="padding: 5px; border: 1px solid #ccc;">Fecha</th>
                                </tr>
                            </thead>
                            <tbody>
                                {aprobadores_html}
                            </tbody>
                        </table>

                        <div style="background-color: #e8f5e8; border: 1px solid #c3e6c3; border-radius: 5px; padding: 15px; margin: 20px 0;">
                            <p style="color: #2d5a2d; margin: 0; font-size: 14px;">
                                <strong>Acción requerida:</strong> Se solicita revisar nuevamente las respuestas del formulario 
                                considerando la justificación proporcionada por el usuario.
                            </p>
                        </div>

                        <p style="font-size: 14px; color: #999; margin-top: 30px;">
                            Enviado el {current_date} 
                        </p>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        msg.set_content(
            f"Solicitud de reconsideración para el formulario \"{formato['titulo']}\" por {usuario_solicita['nombre']}. Mensaje: {mensaje_reconsideracion}"
        )
        msg.add_alternative(html_content, subtype="html")

        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)

        print(f"✅ Correo de reconsideración enviado a {to_email}")
        return True

    except Exception as e:
        print(f"❌ Error al enviar correo de reconsideración a {to_email}: {str(e)}")
        return False
    
    
async def send_action_notification_email(action: str, recipient: str, form, current_date: str, pdf_bytes=None, pdf_filename=None, db=None, current_user=None):
    """
    Versión mejorada de send_action_notification_email que incluye tabla de reporte para generate_report.
    
    Args:
        action (str): Tipo de acción (send_download_link, send_pdf_attachment, generate_report)
        recipient (str): Email del destinatario
        form: Objeto Form de la base de datos
        current_date (str): Fecha actual formateada
        pdf_bytes (bytes, optional): Bytes del PDF generado
        pdf_filename (str, optional): Nombre del archivo PDF
        db: Sesión de base de datos (requerida para generate_report)
        current_user: Usuario actual (requerido para generate_report)
    
    Returns:
        bool: True si el envío fue exitoso, False en caso contrario
    """
    from app.crud import get_form
    try:
        msg = EmailMessage()
        
        # Configurar asunto y contenido según el tipo de acción
        action_configs = {
            'send_download_link': {
                'subject': f"Enlace de descarga - {form.title}",
                'title': "Enlace de Descarga Disponible",
                'icon': "📥",
                'message': "Se ha generado un enlace de descarga para las respuestas del formulario en formato Excel.",
                'color': "#2563eb"
            },
            'send_pdf_attachment': {
                'subject': f"PDF del formulario - {form.title}",
                'title': "PDF del Formulario",
                'icon': "📄",
                'message': "Se ha procesado el formulario y se adjunta el PDF con las respuestas.",
                'color': "#dc2626"
            },
            'generate_report': {
                'subject': f"Reporte generado - {form.title}",
                'title': "Reporte Generado",
                'icon': "📊",
                'message': "Se ha generado un reporte con las respuestas del formulario.",
                'color': "#16a34a"
            }
        }
        
        config = action_configs.get(action, {
            'subject': f"Notificación - {form.title}",
            'title': "Notificación del Formulario",
            'icon': "📋",
            'message': f"Se ha procesado la acción: {action}",
            'color': "#6b7280"
        })
        
        msg["Subject"] = config['subject']
        msg["From"] = formataddr(("Safemetrics", MAIL_FROM_ADDRESS_ALT))
        msg["To"] = recipient
        
        # Contenido adicional según el tipo de acción
        additional_content = ""
        
        if action == 'send_download_link':
            # URL del nuevo endpoint que funciona igual al original 
            excel_download_url = f"https://api-forms-sfi.service.saferut.com/forms/{form.id}/answers/excel/all-users"
            
            additional_content = f"""
            <div style="margin: 20px 0; padding: 15px; background-color: #e3f2fd; border-radius: 5px; border-left: 4px solid #2563eb;">
                <p style="margin: 0 0 15px 0; color: #1565c0; font-size: 15px;">
                    <strong>📥 Descarga de datos:</strong><br>
                    Haz clic en el botón para descargar el archivo Excel con todas las respuestas del formulario.
                </p>
                <div style="text-align: center;">
                    <a href="{excel_download_url}" 
                    style="display: inline-block; 
                            background-color: #2563eb; 
                            color: white; 
                            padding: 15px 30px; 
                            text-decoration: none; 
                            border-radius: 8px; 
                            font-weight: bold; 
                            font-size: 16px;
                            box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        📊 Descargar Excel
                    </a>
                </div>
                <p style="margin: 15px 0 0 0; color: #666; font-size: 12px; text-align: center;">
                    📄 Archivo: Formulario_{form.id}_respuestas.xlsx
                </p>
            </div>
            """
        elif action == 'send_pdf_attachment':
            additional_content = f"""
            <div style="margin: 20px 0; padding: 15px; background-color: #ffebee; border-radius: 5px; border-left: 4px solid #dc2626;">
                <p style="margin: 0; color: #c62828; font-size: 15px;">
                    <strong>📎 Archivo adjunto:</strong> {pdf_filename}<br>
                    El PDF con las respuestas del formulario se encuentra adjunto a este correo.
                </p>
            </div>
            """
        elif action == 'generate_report':
            # Para generate_report, necesitamos obtener los datos del formulario
            if db and current_user:
                try:
                    # Obtener datos del formulario usando la función get_form
                    form_data = get_form(db, form.id, current_user.id)
                    
                    if form_data:
                        report_table = generate_report_table_html(form_data)
                        additional_content = report_table
                    else:
                        additional_content = """
                        <div style="margin: 20px 0; padding: 15px; background-color: #fff3cd; border-radius: 5px; border-left: 4px solid #ffc107;">
                            <p style="margin: 0; color: #856404; font-size: 15px;">
                                <strong>⚠️ Advertencia:</strong> No se pudieron obtener los datos del formulario para generar el reporte.
                            </p>
                        </div>
                        """
                except Exception as e:
                    additional_content = f"""
                    <div style="margin: 20px 0; padding: 15px; background-color: #f8d7da; border-radius: 5px; border-left: 4px solid #dc3545;">
                        <p style="margin: 0; color: #721c24; font-size: 15px;">
                            <strong>❌ Error:</strong> No se pudo generar el reporte. {str(e)}
                        </p>
                    </div>
                    """
            else:
                additional_content = """
                <div style="margin: 20px 0; padding: 15px; background-color: #e2e3e5; border-radius: 5px; border-left: 4px solid #6c757d;">
                    <p style="margin: 0; color: #495057; font-size: 15px;">
                        <strong>📊 Reporte generado:</strong> Los datos del formulario han sido procesados exitosamente.
                    </p>
                </div>
                """
        
        html_content = f"""
        <html>
        <body style="font-family: 'Segoe UI', sans-serif; background-color: #f9f9f9; margin: 0; padding: 30px;">
            <table width="100%" cellspacing="0" cellpadding="0" style="max-width: 800px; margin: auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 30px;">
                <tr>
                    <td>
                        <h2 style="color: {config['color']}; margin-bottom: 10px;">{config['icon']} {config['title']}</h2>
                        <p style="font-size: 16px; color: #333;">
                            Estimado/a usuario,<br><br>
                            {config['message']}
                        </p>
                        
                        <hr style="margin: 25px 0; border: none; border-top: 1px solid #e0e0e0;">
                        
                        <h3 style="color: #333; font-size: 17px;">📄 Detalles del Formulario</h3>
                        <ul style="padding-left: 20px; color: #555; font-size: 15px;">
                            <li><strong>Título:</strong> {form.title}</li>
                            <li><strong>Descripción:</strong> {form.description or 'Sin descripción'}</li>
                            <li><strong>Tipo:</strong> {form.format_type.value.capitalize()}</li>
                            <li><strong>Creado por:</strong> {form.user.name} ({form.user.email})</li>
                            <li><strong>Fecha de creación:</strong> {form.created_at.strftime('%d/%m/%Y')}</li>
                        </ul>
                        
                        <h3 style="color: #333; font-size: 17px;">⚙️ Configuración Ejecutada</h3>
                        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; border-left: 4px solid {config['color']};">
                            <p style="margin: 0; color: #555; font-size: 15px;">
                                <strong>Acción seleccionada:</strong> {action.replace('_', ' ').title()}<br>
                                <strong>Destinatario:</strong> {recipient}<br>
                                <strong>Formulario ID:</strong> {form.id}
                            </p>
                        </div>
                        
                        {additional_content}
                        
                        <p style="font-size: 14px; color: #999; margin-top: 30px;">
                            Enviado el {current_date}
                        </p>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        
        # Contenido de texto plano
        text_content = f"""
        {config['title']}
        
        {config['message']}
        
        Detalles del formulario:
        - Título: {form.title}
        - Descripción: {form.description or 'Sin descripción'}
        - Tipo: {form.format_type.value.capitalize()}
        - Creado por: {form.user.name} ({form.user.email})
        - Fecha de creación: {form.created_at.strftime('%d/%m/%Y')}
        
        Configuración ejecutada: {action.replace('_', ' ').title()}
        Destinatario: {recipient}
        Formulario ID: {form.id}
        
        {"Para descargar el archivo Excel, visita: https://api-forms-sfi.service.saferut.com/forms/" + str(form.id) + "/answers/excel/all-users" if action == 'send_download_link' else ""}
        
        Enviado el {current_date}
        """
        
        msg.set_content(text_content)
        msg.add_alternative(html_content, subtype="html")
        
        # Adjuntar PDF si es necesario
        if action == 'send_pdf_attachment' and pdf_bytes:
            msg.add_attachment(
                pdf_bytes,
                maintype='application',
                subtype='pdf',
                filename=pdf_filename
            )
        
        # Enviar el correo
        with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
            smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
            smtp.send_message(msg)
        
        print(f"✅ Correo de acción '{action}' enviado a {recipient}")
        return True
        
    except Exception as e:
        print(f"❌ Error al enviar correo de acción '{action}' a {recipient}: {str(e)}")
        return False
    
    
def generate_report_table_html(form_data):
    """
    Genera una tabla HTML con los datos del formulario para incluir en el correo de reporte.
    
    Args:
        form_data: Datos del formulario obtenidos de get_form()
    
    Returns:
        str: HTML de la tabla con los datos del reporte
    """
    if not form_data or not form_data.get('questions'):
        return "<p>No hay datos disponibles para mostrar.</p>"
    
    # Crear encabezados de la tabla basados en las preguntas
    headers = []
    question_map = {}
    
    for question in form_data['questions']:
        headers.append(question['question_text'])
        question_map[question['id']] = question['question_text']
    
    # Si no hay respuestas, mostrar solo las preguntas
    if not form_data.get('responses'):
        table_html = f"""
        <div style="margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-radius: 5px; border-left: 4px solid #16a34a;">
            <h4 style="color: #16a34a; margin: 0 0 15px 0;">📊 Estructura del Formulario</h4>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; background-color: white; border-radius: 5px; overflow: hidden;">
                    <thead>
                        <tr style="background-color: #16a34a; color: white;">
                            <th style="padding: 12px; text-align: left; border-bottom: 2px solid #ddd;">Pregunta</th>
                            <th style="padding: 12px; text-align: left; border-bottom: 2px solid #ddd;">Tipo</th>
                            <th style="padding: 12px; text-align: left; border-bottom: 2px solid #ddd;">Requerida</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for i, question in enumerate(form_data['questions']):
            row_color = "#f9f9f9" if i % 2 == 0 else "white"
            required_text = "Sí" if question.get('required', False) else "No"
            
            table_html += f"""
                        <tr style="background-color: {row_color};">
                            <td style="padding: 10px; border-bottom: 1px solid #ddd; font-weight: 500;">{question['question_text']}</td>
                            <td style="padding: 10px; border-bottom: 1px solid #ddd;">{question['question_type'].capitalize()}</td>
                            <td style="padding: 10px; border-bottom: 1px solid #ddd;">{required_text}</td>
                        </tr>
            """
        
        table_html += """
                    </tbody>
                </table>
            </div>
            <p style="margin: 15px 0 0 0; color: #666; font-size: 13px;">
                📝 Este formulario aún no tiene respuestas registradas.
            </p>
        </div>
        """
        
        return table_html
    
    # Crear tabla con respuestas
    table_html = f"""
    <div style="margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-radius: 5px; border-left: 4px solid #16a34a;">
        <h4 style="color: #16a34a; margin: 0 0 15px 0;">📊 Reporte de Respuestas</h4>
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; background-color: white; border-radius: 5px; overflow: hidden;">
                <thead>
                    <tr style="background-color: #16a34a; color: white;">
                        <th style="padding: 12px; text-align: left; border-bottom: 2px solid #ddd;">ID Respuesta</th>
    """
    
    # Agregar encabezados de preguntas
    for header in headers:
        table_html += f'<th style="padding: 12px; text-align: left; border-bottom: 2px solid #ddd;">{header}</th>'
    
    table_html += """
                    </tr>
                </thead>
                <tbody>
    """
    
    # Agregar filas con respuestas
    for i, response in enumerate(form_data['responses']):
        row_color = "#f9f9f9" if i % 2 == 0 else "white"
        
        table_html += f"""
                    <tr style="background-color: {row_color};">
                        <td style="padding: 10px; border-bottom: 1px solid #ddd; font-weight: 500;">{response['id']}</td>
        """
        
        # Crear un diccionario de respuestas por question_id
        answers_by_question = {}
        for answer in response.get('answers', []):
            answers_by_question[answer['question_id']] = answer['answer_text']
        
        # Agregar celdas para cada pregunta
        for question in form_data['questions']:
            answer_text = answers_by_question.get(question['id'], '-')
            # Truncar texto muy largo
            if len(answer_text) > 100:
                answer_text = answer_text[:100] + "..."
            
            table_html += f'<td style="padding: 10px; border-bottom: 1px solid #ddd;">{answer_text}</td>'
        
        table_html += "</tr>"
    
    table_html += """
                </tbody>
            </table>
        </div>
        <p style="margin: 15px 0 0 0; color: #666; font-size: 13px;">
            📈 Total de respuestas: """ + str(len(form_data['responses'])) + """
        </p>
    </div>
    """
    
    return table_html

def send_response_answers_email(
    to_emails: list[str],
    form_title: str,
    response_id: int,
    answers: list[EmailAnswerItem],
):
    try:
        current_date = datetime.now().strftime("%d de %B de %Y")
        current_time = datetime.now().strftime("%H:%M")

        answers_html = ""
        for idx, item in enumerate(answers):
            value = item.answer_text or '<span style="color:#94a3b8;font-style:italic;">Sin respuesta</span>'

            if item.file_path:
                value += f'''
                    <br>
                    <a href="{item.file_path}" 
                       style="display:inline-flex;align-items:center;gap:6px;margin-top:8px;padding:6px 12px;background:#3b82f6;color:white;text-decoration:none;border-radius:6px;font-size:13px;font-weight:500;">
                        <span>📎</span>
                        <span>Ver archivo adjunto</span>
                    </a>
                '''

            # Fila con alternancia de colores
            row_bg = "#f8fafc" if idx % 2 == 0 else "#ffffff"
            
            answers_html += f'''
                <tr style="background-color:{row_bg};">
                    <td style="padding:16px 20px;border-bottom:1px solid #e2e8f0;font-weight:500;color:#334155;width:40%;vertical-align:top;">
                        {item.question_text}
                    </td>
                    <td style="padding:16px 20px;border-bottom:1px solid #e2e8f0;color:#475569;width:60%;vertical-align:top;">
                        {value}
                    </td>
                </tr>
            '''

        html_content = f'''
        <!DOCTYPE html>
        <html lang="es">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Respuestas del Formulario</title>
        </head>
        <body style="margin:0;padding:0;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background-color:#f1f5f9;">
            
            <!-- Contenedor principal -->
            <div style="max-width:800px;margin:40px auto;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.1);">
                
                <!-- Header con gradiente -->
                <div style="background:linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);padding:40px 30px;text-align:center;">
                    <div style="background-color:rgba(255,255,255,0.2);width:64px;height:64px;border-radius:50%;margin:0 auto 20px;display:flex;align-items:center;justify-content:center;font-size:32px;">
                        📋
                    </div>
                    <h1 style="margin:0;color:#ffffff;font-size:28px;font-weight:600;letter-spacing:-0.5px;">
                        Nueva Respuesta de Formulario
                    </h1>
                    <p style="margin:12px 0 0;color:#e0e7ff;font-size:16px;">
                        {form_title}
                    </p>
                </div>

                <!-- Información del formulario -->
                <div style="padding:30px;background-color:#f8fafc;border-bottom:1px solid #e2e8f0;">
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
                        <div style="background-color:#ffffff;padding:20px;border-radius:8px;border-left:4px solid #3b82f6;">
                            <div style="color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
                                ID de Respuesta
                            </div>
                            <div style="color:#1e293b;font-size:20px;font-weight:700;">
                                #{response_id}
                            </div>
                        </div>
                        <div style="background-color:#ffffff;padding:20px;border-radius:8px;border-left:4px solid #10b981;">
                            <div style="color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
                                Fecha y Hora
                            </div>
                            <div style="color:#1e293b;font-size:16px;font-weight:600;">
                                {current_date}
                            </div>
                            <div style="color:#64748b;font-size:14px;margin-top:4px;">
                                {current_time}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Título de la tabla -->
                <div style="padding:30px 30px 20px;">
                    <h2 style="margin:0;color:#1e293b;font-size:20px;font-weight:600;display:flex;align-items:center;gap:10px;">
                        <span style="display:inline-block;width:4px;height:24px;background:#3b82f6;border-radius:2px;"></span>
                        Respuestas Detalladas
                    </h2>
                </div>

                <!-- Tabla de respuestas -->
                <div style="padding:0 30px 30px;">
                    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:0;border-radius:8px;overflow:hidden;border:1px solid #e2e8f0;">
                        <thead>
                            <tr style="background:linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);">
                                <th style="padding:16px 20px;text-align:left;font-size:13px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cbd5e1;">
                                    Pregunta
                                </th>
                                <th style="padding:16px 20px;text-align:left;font-size:13px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #cbd5e1;">
                                    Respuesta
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {answers_html}
                        </tbody>
                    </table>
                </div>

                <!-- Footer -->
                <div style="padding:30px;background-color:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;">
                    <div style="margin-bottom:16px;">
                        <img src="https://via.placeholder.com/120x40/3b82f6/ffffff?text=SafeMetrics" alt="SafeMetrics" style="height:32px;">
                    </div>
                    <p style="margin:0 0 8px;color:#64748b;font-size:14px;">
                        Este correo fue generado automáticamente por SafeMetrics
                    </p>
                    <p style="margin:0;color:#94a3b8;font-size:12px;">
                        © 2024 SafeMetrics. Todos los derechos reservados.
                    </p>
                </div>

            </div>

            <!-- Nota de confidencialidad -->
            <div style="max-width:800px;margin:20px auto;padding:20px;text-align:center;">
                <p style="margin:0;color:#94a3b8;font-size:12px;line-height:1.6;">
                    <strong>Aviso de confidencialidad:</strong> Este mensaje y sus archivos adjuntos están dirigidos exclusivamente 
                    a su destinatario y pueden contener información privilegiada o confidencial. Si no es el destinatario previsto, 
                    elimínelo de inmediato.
                </p>
            </div>

        </body>
        </html>
        '''

        for email in to_emails:
            msg = EmailMessage()
            msg["Subject"] = f"✓ Nueva Respuesta: {form_title}"
            msg["From"] = formataddr(("SafeMetrics Platform", MAIL_FROM_ADDRESS_ALT))
            msg["To"] = email

            # Texto plano alternativo
            plain_text = f'''
NUEVA RESPUESTA DE FORMULARIO
════════════════════════════════

Formulario: {form_title}
ID de Respuesta: #{response_id}
Fecha: {current_date} - {current_time}

RESPUESTAS:
────────────────────────────────
'''
            for item in answers:
                plain_text += f'\n{item.question_text}\n'
                plain_text += f'→ {item.answer_text or "Sin respuesta"}\n'
                if item.file_path:
                    plain_text += f'  📎 Archivo: {item.file_path}\n'
                plain_text += '\n'

            plain_text += '''
────────────────────────────────
Este correo fue generado automáticamente por SafeMetrics.
© 2024 SafeMetrics. Todos los derechos reservados.
'''

            msg.set_content(plain_text)
            msg.add_alternative(html_content, subtype="html")

            with smtplib.SMTP_SSL(MAIL_HOST_ALT, int(MAIL_PORT_ALT)) as smtp:
                smtp.login(MAIL_USERNAME_ALT, MAIL_PASSWORD_ALT)
                smtp.send_message(msg)

        return True

    except Exception as e:
        print(f"❌ Error al enviar correo: {str(e)}")
        return False