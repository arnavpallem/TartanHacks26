"""
Finance Automation Slack Bot - Main Entry Point

This bot automates club financial management for Spring Carnival Committee:
- Receipt processing via Slack
- TPR form automation
- Google Drive uploads
- Budget spreadsheet updates
- Gmail monitoring for receipts
"""
import asyncio
import logging
import sys
import schedule
from datetime import datetime

from config.settings import validate_config, SlackConfig
from services.slack_bot import start_slack_bot, get_slack_bot
from services.gmail_monitor import run_daily_gmail_check

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)


async def schedule_gmail_check():
    """
    Schedule daily Gmail checks.
    Runs once per day to check for new receipt emails.
    """
    # Get the Slack bot to send notifications
    bot = get_slack_bot()
    
    # Define the notification channel (configure as needed)
    notification_channel = None  # Set to a specific channel ID if needed
    
    while True:
        # Wait 24 hours between checks
        await asyncio.sleep(86400)  # 24 hours in seconds
        
        try:
            logger.info("Running daily Gmail check...")
            if bot.client and notification_channel:
                await run_daily_gmail_check(notification_channel, bot.client)
            else:
                logger.warning("Slack client not available for Gmail notifications")
        except Exception as e:
            logger.error(f"Error in Gmail check: {e}")


async def main():
    """Main entry point for the Finance Bot."""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║     Finance Automation Bot - Spring Carnival Committee    ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  📄 Receipt Processing    📝 TPR Automation               ║
    ║  ☁️  Google Drive         📊 Sheets Integration           ║
    ║  📧 Gmail Monitoring                                      ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Validate configuration
    logger.info("Validating configuration...")
    missing = validate_config()
    
    if missing:
        logger.error("Missing required configuration:")
        for item in missing:
            logger.error(f"  - {item}")
        logger.error("\nPlease check your .env file and credentials.")
        print("\n⚠️  Configuration incomplete. See above for details.")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    
    logger.info("Configuration validated ✓")
    
    # Start services
    try:
        # Start Gmail monitoring in background
        gmail_task = asyncio.create_task(schedule_gmail_check())
        
        # Start Slack bot (this blocks)
        logger.info("Starting Slack bot...")
        print("\n✅ Bot is running! Mention it in Slack with a receipt to get started.")
        print("   Format: @FinanceBot [receipt.pdf] Description of purchase")
        print("\n   Press Ctrl+C to stop.\n")
        
        await start_slack_bot()
        
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        print("\n👋 Goodbye!")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
