# YouTube Downloader Telegram Bot

A feature-rich Telegram bot for downloading YouTube videos with real-time progress tracking.

## Features

- 📥 Download individual YouTube videos
- 📁 Bulk download via .txt files
- 🎯 Multiple resolution support
- 🍪 YouTube cookies support (for age-restricted videos)
- 🔄 Real-time download/upload progress
- 🎬 Original title and thumbnail preservation
- ⚡ Fast and efficient downloading

## Deployment on Render

### 1. Prerequisites
- Render account
- Telegram Bot Token from [@BotFather](https://t.me/botfather)
- Python 3.11+

### 2. Deployment Steps

#### Method A: Using Render Dashboard
1. Fork/upload this repository to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. Click "New +" → "Web Service"
4. Connect your GitHub repository
5. Configure:
   - **Name:** youtube-downloader-bot
   - **Environment:** Python
   - **Region:** Choose nearest
   - **Branch:** main
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Plan:** Free or higher

6. Add environment variable:
   - `BOT_TOKEN`: Your Telegram bot token

7. Click "Create Web Service"

#### Method B: Using Render CLI
```bash
# Install Render CLI
npm install -g render-cli

# Login to Render
render login

# Deploy from current directory
render deploy
