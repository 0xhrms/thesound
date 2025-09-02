#!/usr/bin/env python3
"""
Telegram Music Bot - Automatically sends random music from YouTube playlists
Author: Assistant
Description: A bot that periodically downloads and sends random music from configured playlists
"""

import os
import json
import logging
import random
import asyncio
import tempfile
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

import yt_dlp
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('music_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MusicBot:
    def __init__(self, token: str, user_id: int):
        """
        Initialize the Music Bot
        
        Args:
            token: Telegram bot token
            user_id: Your Telegram user ID (the bot will only send to this user)
        """
        self.token = token
        self.user_id = user_id
        self.config_file = 'bot_config.json'
        self.scheduler = AsyncIOScheduler()
        self.application = None
        
        # Load or create configuration
        self.config = self.load_config()
        
        # Set up yt-dlp options for different formats
        self.ytdl_opts_audio = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'audioquality': '192',
            'outtmpl': '%(title)s.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        self.ytdl_opts_video = {
            'format': 'best[filesize<50M]/best[height<=480]/worst',
            'outtmpl': '%(title)s.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
        }

    def load_config(self) -> Dict:
        """Load configuration from JSON file or create default config"""
        default_config = {
            'playlists': [
                # Add your playlist URLs here
                # 'https://youtube.com/playlist?list=PLxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
                # 'https://youtube.com/playlist?list=PLyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy',
            ],
            'interval_minutes': 1,
            'download_format': 'audio',  # 'audio' or 'video'
            'max_file_size_mb': 50,
            'enabled': False
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                # Merge with defaults to handle new config options
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
            else:
                self.save_config(default_config)
                return default_config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return default_config

    def save_config(self, config: Dict = None) -> None:
        """Save configuration to JSON file"""
        try:
            config_to_save = config or self.config
            with open(self.config_file, 'w') as f:
                json.dump(config_to_save, f, indent=2)
            logger.info("Configuration saved successfully")
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    async def get_playlist_videos(self, playlist_url: str) -> List[str]:
        """Extract video URLs from a YouTube playlist"""
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                playlist_info = ydl.extract_info(playlist_url, download=False)
                if 'entries' in playlist_info:
                    video_urls = []
                    for entry in playlist_info['entries']:
                        if entry and 'webpage_url' in entry:
                            video_urls.append(entry['webpage_url'])
                    return video_urls
                else:
                    logger.warning(f"No videos found in playlist: {playlist_url}")
                    return []
        except Exception as e:
            logger.error(f"Error extracting playlist {playlist_url}: {e}")
            return []

    async def download_and_convert(self, video_url: str, download_format: str) -> Optional[str]:
        """Download and convert video to specified format"""
        try:
            # Create temporary directory
            temp_dir = tempfile.mkdtemp()
            
            # Choose appropriate yt-dlp options
            if download_format == 'audio':
                ytdl_opts = self.ytdl_opts_audio.copy()
                ytdl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')
            else:
                ytdl_opts = self.ytdl_opts_video.copy()
                ytdl_opts['outtmpl'] = os.path.join(temp_dir, '%(title)s.%(ext)s')
            
            with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                # Extract info first to get the title
                info = ydl.extract_info(video_url, download=False)
                title = info.get('title', 'Unknown')
                
                # Download the video/audio
                ydl.download([video_url])
                
                # Find the downloaded file
                for file in os.listdir(temp_dir):
                    file_path = os.path.join(temp_dir, file)
                    file_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
                    
                    # Check if file size is acceptable
                    if file_size <= self.config['max_file_size_mb']:
                        logger.info(f"Downloaded: {title} ({file_size:.1f}MB)")
                        return file_path
                    else:
                        logger.warning(f"File too large: {title} ({file_size:.1f}MB)")
                        os.remove(file_path)
                        return None
                        
        except Exception as e:
            logger.error(f"Error downloading {video_url}: {e}")
            return None

    async def send_random_music(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Main function to send random music from playlists"""
        try:
            if not self.config['playlists']:
                logger.warning("No playlists configured")
                return
                
            if not self.config['enabled']:
                logger.info("Bot is disabled, skipping music send")
                return

            # Randomly select a playlist
            playlist_url = random.choice(self.config['playlists'])
            logger.info(f"Selected playlist: {playlist_url}")
            
            # Get videos from the playlist
            video_urls = await self.get_playlist_videos(playlist_url)
            
            if not video_urls:
                logger.warning("No videos found in selected playlist")
                return
            
            # Randomly select a video
            video_url = random.choice(video_urls)
            logger.info(f"Selected video: {video_url}")
            
            # Download the video/audio
            file_path = await self.download_and_convert(video_url, self.config['download_format'])
            
            if file_path and os.path.exists(file_path):
                # Send the file to Telegram
                try:
                    if self.config['download_format'] == 'audio':
                        await context.bot.send_audio(
                            chat_id=self.user_id,
                            audio=open(file_path, 'rb'),
                            caption=f"🎵 Random music from your playlists!\n\n🔗 {video_url}"
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=self.user_id,
                            video=open(file_path, 'rb'),
                            caption=f"🎬 Random video from your playlists!\n\n🔗 {video_url}"
                        )
                    
                    logger.info("Successfully sent file to Telegram")
                    
                except Exception as e:
                    logger.error(f"Error sending file to Telegram: {e}")
                
                finally:
                    # Clean up the downloaded file
                    try:
                        os.remove(file_path)
                        # Remove empty temp directory
                        temp_dir = os.path.dirname(file_path)
                        if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                            os.rmdir(temp_dir)
                        logger.info("Cleaned up temporary files")
                    except Exception as e:
                        logger.error(f"Error cleaning up files: {e}")
            
        except Exception as e:
            logger.error(f"Error in send_random_music: {e}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        welcome_message = """
🎵 **Music Bot is Ready!**

I'll automatically send you random music from your configured playlists.

**Available Commands:**
• `/help` - Show all commands
• `/status` - Show current status
• `/enable` - Start automatic music sending
• `/disable` - Stop automatic music sending
• `/add_playlist <URL>` - Add a new playlist
• `/remove_playlist <number>` - Remove playlist by number
• `/list_playlists` - Show all playlists
• `/set_interval <minutes>` - Set sending interval
• `/set_format <audio/video>` - Set download format
• `/send_now` - Send random music immediately

**Setup Instructions:**
1. Add your playlists with `/add_playlist <URL>`
2. Configure settings with `/set_interval` and `/set_format`
3. Enable the bot with `/enable`

Get started by adding your first playlist!
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command"""
        help_text = """
🤖 **Music Bot Commands:**

**Playlist Management:**
• `/add_playlist <URL>` - Add YouTube playlist
• `/remove_playlist <number>` - Remove playlist (see numbers with /list_playlists)
• `/list_playlists` - Show all configured playlists

**Bot Control:**
• `/enable` - Start automatic music sending
• `/disable` - Stop automatic music sending
• `/status` - Show bot status and settings
• `/send_now` - Send random music immediately

**Settings:**
• `/set_interval <minutes>` - Set how often to send music (default: 1 minute)
• `/set_format <audio/video>` - Choose 'audio' for MP3 or 'video' for MP4

**Examples:**
• `/add_playlist https://youtube.com/playlist?list=PLxxxxx`
• `/set_interval 5` (send every 5 minutes)
• `/set_format audio` (download as MP3)
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command"""
        status = "🎵 **Music Bot Status**\n\n"
        status += f"**Enabled:** {'✅ Yes' if self.config['enabled'] else '❌ No'}\n"
        status += f"**Interval:** {self.config['interval_minutes']} minute(s)\n"
        status += f"**Format:** {self.config['download_format'].upper()}\n"
        status += f"**Max File Size:** {self.config['max_file_size_mb']}MB\n"
        status += f"**Playlists:** {len(self.config['playlists'])} configured\n\n"
        
        if self.config['playlists']:
            status += "**Next random selection from:**\n"
            for i, playlist in enumerate(self.config['playlists'][:3], 1):
                status += f"{i}. {playlist[:50]}...\n"
            if len(self.config['playlists']) > 3:
                status += f"... and {len(self.config['playlists']) - 3} more\n"
        else:
            status += "⚠️ **No playlists configured!** Add some with `/add_playlist`"
        
        await update.message.reply_text(status, parse_mode='Markdown')

    async def add_playlist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /add_playlist command"""
        if not context.args:
            await update.message.reply_text("Please provide a playlist URL. Example:\n`/add_playlist https://youtube.com/playlist?list=PLxxxxx`", parse_mode='Markdown')
            return
        
        playlist_url = context.args[0]
        
        # Basic URL validation
        if 'youtube.com/playlist' not in playlist_url and 'youtu.be/playlist' not in playlist_url:
            await update.message.reply_text("❌ Please provide a valid YouTube playlist URL")
            return
        
        if playlist_url in self.config['playlists']:
            await update.message.reply_text("⚠️ This playlist is already in your list!")
            return
        
        # Test the playlist
        await update.message.reply_text("🔍 Testing playlist... Please wait.")
        
        video_urls = await self.get_playlist_videos(playlist_url)
        
        if video_urls:
            self.config['playlists'].append(playlist_url)
            self.save_config()
            await update.message.reply_text(f"✅ Playlist added successfully!\nFound {len(video_urls)} videos.\n\nTotal playlists: {len(self.config['playlists'])}")
        else:
            await update.message.reply_text("❌ Could not access this playlist. Please check the URL and make sure the playlist is public.")

    async def remove_playlist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /remove_playlist command"""
        if not context.args:
            await update.message.reply_text("Please provide the playlist number. Use `/list_playlists` to see numbers.")
            return
        
        try:
            playlist_num = int(context.args[0]) - 1
            if 0 <= playlist_num < len(self.config['playlists']):
                removed_playlist = self.config['playlists'].pop(playlist_num)
                self.save_config()
                await update.message.reply_text(f"✅ Removed playlist #{playlist_num + 1}\n`{removed_playlist[:60]}...`", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"❌ Invalid playlist number. Use `/list_playlists` to see valid numbers.")
        except ValueError:
            await update.message.reply_text("❌ Please provide a valid number.")

    async def list_playlists_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /list_playlists command"""
        if not self.config['playlists']:
            await update.message.reply_text("📭 No playlists configured.\n\nAdd one with: `/add_playlist <URL>`")
            return
        
        message = "🎵 **Your Playlists:**\n\n"
        for i, playlist in enumerate(self.config['playlists'], 1):
            message += f"{i}. `{playlist}`\n\n"
        
        message += f"**Total:** {len(self.config['playlists'])} playlist(s)\n"
        message += "Use `/remove_playlist <number>` to remove a playlist"
        
        await update.message.reply_text(message, parse_mode='Markdown')

    async def enable_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /enable command"""
        if not self.config['playlists']:
            await update.message.reply_text("❌ Cannot enable: No playlists configured!\nAdd playlists first with `/add_playlist <URL>`")
            return
        
        self.config['enabled'] = True
        self.save_config()
        
        # Restart scheduler with new settings
        await self.setup_scheduler()
        
        await update.message.reply_text(f"✅ **Music Bot Enabled!**\n\nSending random music every {self.config['interval_minutes']} minute(s)\nFormat: {self.config['download_format'].upper()}")

    async def disable_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /disable command"""
        self.config['enabled'] = False
        self.save_config()
        
        # Stop scheduler
        if self.scheduler.running:
            self.scheduler.remove_all_jobs()
        
        await update.message.reply_text("❌ **Music Bot Disabled**\n\nAutomatic music sending stopped.")

    async def set_interval_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set_interval command"""
        if not context.args:
            await update.message.reply_text("Please specify interval in minutes. Example: `/set_interval 5`")
            return
        
        try:
            interval = int(context.args[0])
            if interval < 1:
                await update.message.reply_text("❌ Interval must be at least 1 minute")
                return
            
            self.config['interval_minutes'] = interval
            self.save_config()
            
            # Restart scheduler if enabled
            if self.config['enabled']:
                await self.setup_scheduler()
            
            await update.message.reply_text(f"✅ Interval set to {interval} minute(s)")
            
        except ValueError:
            await update.message.reply_text("❌ Please provide a valid number of minutes")

    async def set_format_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set_format command"""
        if not context.args:
            await update.message.reply_text("Please specify format: `audio` or `video`\nExample: `/set_format audio`", parse_mode='Markdown')
            return
        
        format_choice = context.args[0].lower()
        if format_choice not in ['audio', 'video']:
            await update.message.reply_text("❌ Format must be either 'audio' or 'video'")
            return
        
        self.config['download_format'] = format_choice
        self.save_config()
        
        format_desc = "MP3 audio files" if format_choice == 'audio' else "MP4 video files (under 50MB)"
        await update.message.reply_text(f"✅ Download format set to: **{format_choice.upper()}**\nWill send: {format_desc}", parse_mode='Markdown')

    async def send_now_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /send_now command"""
        if not self.config['playlists']:
            await update.message.reply_text("❌ No playlists configured! Add some with `/add_playlist <URL>`")
            return
        
        await update.message.reply_text("🎵 Selecting and downloading random music... Please wait!")
        await self.send_random_music(context)

    async def setup_scheduler(self) -> None:
        """Set up the APScheduler for automatic music sending"""
        # Remove existing jobs
        if self.scheduler.running:
            self.scheduler.remove_all_jobs()
        
        if self.config['enabled'] and self.config['playlists']:
            # Add the job
            self.scheduler.add_job(
                func=self.send_random_music,
                trigger=IntervalTrigger(minutes=self.config['interval_minutes']),
                args=[None],  # We'll pass context differently
                id='send_music_job',
                replace_existing=True
            )
            
            if not self.scheduler.running:
                self.scheduler.start()
            
            logger.info(f"Scheduler started - sending music every {self.config['interval_minutes']} minute(s)")

    async def setup_bot_commands(self) -> None:
        """Set up bot commands for the Telegram menu"""
        commands = [
            BotCommand('start', 'Start the bot and see instructions'),
            BotCommand('help', 'Show all available commands'),
            BotCommand('status', 'Show bot status and settings'),
            BotCommand('enable', 'Enable automatic music sending'),
            BotCommand('disable', 'Disable automatic music sending'),
            BotCommand('add_playlist', 'Add a new YouTube playlist'),
            BotCommand('remove_playlist', 'Remove a playlist by number'),
            BotCommand('list_playlists', 'Show all configured playlists'),
            BotCommand('set_interval', 'Set sending interval in minutes'),
            BotCommand('set_format', 'Set download format (audio/video)'),
            BotCommand('send_now', 'Send random music immediately'),
        ]
        
        await self.application.bot.set_my_commands(commands)

    async def check_user_permission(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if the user is authorized to use the bot"""
        if update.effective_user.id != self.user_id:
            await update.message.reply_text("🚫 You are not authorized to use this bot.")
            return False
        return True

    async def authorized_command(self, handler_func):
        """Decorator to check user authorization"""
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if await self.check_user_permission(update, context):
                return await handler_func(update, context)
        return wrapper

    async def run(self) -> None:
        """Run the bot"""
        try:
            # Create application
            self.application = Application.builder().token(self.token).build()
            
            # Add command handlers with authorization check
            handlers = [
                ('start', self.start_command),
                ('help', self.help_command),
                ('status', self.status_command),
                ('enable', self.enable_command),
                ('disable', self.disable_command),
                ('add_playlist', self.add_playlist_command),
                ('remove_playlist', self.remove_playlist_command),
                ('list_playlists', self.list_playlists_command),
                ('set_interval', self.set_interval_command),
                ('set_format', self.set_format_command),
                ('send_now', self.send_now_command),
            ]
            
            for command, handler in handlers:
                authorized_handler = await self.authorized_command(handler)
                self.application.add_handler(CommandHandler(command, authorized_handler))
            
            # Set up bot commands menu
            await self.setup_bot_commands()
            
            # Set up scheduler
            await self.setup_scheduler()
            
            logger.info("🎵 Music Bot started successfully!")
            
            # Start polling
            await self.application.run_polling(drop_pending_updates=True)
            
        except Exception as e:
            logger.error(f"Error running bot: {e}")
        finally:
            if self.scheduler.running:
                self.scheduler.shutdown()

def main():
    """Main function to run the bot"""
    
    # Configuration - REPLACE WITH YOUR VALUES
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Get from @BotFather
    USER_ID = 123456789  # Your Telegram user ID (get from @userinfobot)
    
    # Validate configuration
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Error: Please set your BOT_TOKEN in the script")
        print("1. Create a bot with @BotFather on Telegram")
        print("2. Replace 'YOUR_BOT_TOKEN_HERE' with your actual bot token")
        return
    
    if USER_ID == 123456789:
        print("❌ Error: Please set your USER_ID in the script")
        print("1. Message @userinfobot on Telegram to get your user ID")
        print("2. Replace '123456789' with your actual user ID")
        return
    
    # Create and run bot
    bot = MusicBot(BOT_TOKEN, USER_ID)
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")

if __name__ == "__main__":
    main()
