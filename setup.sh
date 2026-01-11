#!/bin/bash

# YouTube Downloader Bot Setup Script

echo "📦 Setting up YouTube Downloader Bot..."

# Update system packages
sudo apt-get update

# Install Python dependencies
echo "🐍 Installing Python dependencies..."
sudo apt-get install -y python3-pip python3-venv

# Install FFmpeg
echo "🎬 Installing FFmpeg..."
sudo apt-get install -y ffmpeg

# Optional: Install aria2c for faster downloads
echo "⚡ Installing aria2c (optional for faster downloads)..."
sudo apt-get install -y aria2

# Create virtual environment
echo "🏗️ Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python packages
echo "📦 Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "🔑 Creating .env file..."
    echo "TELEGRAM_BOT_TOKEN=your_bot_token_here" > .env
    echo "⚠️ Please edit .env file and add your Telegram Bot Token"
fi

# Create directories
mkdir -p temp_downloads
mkdir -p logs

echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Edit .env file and add your Telegram Bot Token"
echo "2. Get token from @BotFather on Telegram"
echo "3. Run: source venv/bin/activate"
echo "4. Run: python bot.py"
echo ""
echo "🤖 Bot commands:"
echo "   /start - Start the bot"
echo "   /help - Show help message"
echo "   /about - About this bot"
