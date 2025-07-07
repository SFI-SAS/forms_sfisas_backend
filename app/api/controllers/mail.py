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
async def send_action_notification_email(action: str, recipient: str, form, current_date: str, pdf_bytes=None, pdf_filename=None):
    """
    Envía un correo de notificación específico según el tipo de acción.
    
    Args:
        action (str): Tipo de acción (send_download_link, send_pdf_attachment, generate_report)
        recipient (str): Email del destinatario
        form: Objeto Form de la base de datos
        current_date (str): Fecha actual formateada
        pdf_bytes (bytes, optional): Bytes del PDF generado
        pdf_filename (str, optional): Nombre del archivo PDF
    
    Returns:
        bool: True si el envío fue exitoso, False en caso contrario
    """
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
            
            
            # excel_download_url = f"http://127.0.0.1:8000/forms/{form.id}/answers/excel/all-users"
            
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
        
        html_content = f"""
        <html>
        <body style="font-family: 'Segoe UI', sans-serif; background-color: #f9f9f9; margin: 0; padding: 30px;">
            <table width="100%" cellspacing="0" cellpadding="0" style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 30px;">
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
        
        {"Para descargar el archivo Excel, visita: https://tu-dominio.com/api/" + str(form.id) + "/questions-answers/excel" if action == 'send_download_link' else ""}
        
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