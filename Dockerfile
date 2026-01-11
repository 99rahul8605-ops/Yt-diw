FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p temp cookies logs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV BOT_TOKEN=your_bot_token_here
ENV PORT=8080

# Expose the port
EXPOSE 8080

# Run the bot
CMD ["python", "bot.py"]
