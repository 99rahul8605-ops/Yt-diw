from flask import Flask
import threading
import asyncio
import os
from bot import YouTubeDownloaderBot, main as bot_main

app = Flask(__name__)

# Keep-alive endpoint for Render
@app.route('/')
def home():
    return "YouTube Downloader Bot is running!"

# Health check endpoint
@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    """Run the Telegram bot in background"""
    asyncio.run(bot_main())

if __name__ == '__main__':
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Start Flask server on Render's port
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
