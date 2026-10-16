FROM python:3.12-slim

# Sin ARG/ENV de configuración: todo lo que lee el backend (DATABASE_URL,
# SECRET_KEY, MAIL_*, REDIS_*, ENCRYPTION_KEY, AWS_*...) llega como variable
# de entorno AL ARRANCAR el contenedor (CapRover, ECS task definition,
# docker run --env-file...). Así la imagen no lleva secretos y la misma sirve
# para cualquier cliente.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Librerías del sistema que necesita WeasyPrint para los PDF.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 libgdk-pixbuf-2.0-0 \
    libffi-dev shared-mime-info fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Carpetas de archivos subidos: van vacías en la imagen (los de cada
# instalación viven en un volumen o, más adelante, en S3).
RUN mkdir -p documents uploaded_files approval_attachments logo form_instructivos

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
