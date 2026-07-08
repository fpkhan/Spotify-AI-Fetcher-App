FROM python:3.13-slim

# Install system dependencies required for Azure SQL Server connections (ODBC Driver 18)
RUN apt-get update && apt-get install -y \
    curl gnupg build-essential ca-certificates \
    portaudio19-dev flac ffmpeg\
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements from the local server folder and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your server files
COPY . .

EXPOSE 8000

CMD ["python", "main.py"]