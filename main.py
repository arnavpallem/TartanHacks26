"""
Finance Automation Slack Bot - Main Entry Point

This bot automates club financial management for Spring Carnival Committee:
- Receipt processing via Slack
- TPR form automation
- Google Drive uploads
- Budget spreadsheet updates
- Email webhook for receipt forwarding
"""
import asyncio
import logging
import sys
from datetime import datetime

import argparse

from config.settings import validate_config, SlackConfig, MailgunConfig
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
    
    # Parse command line arguments first
    parser = argparse.ArgumentParser(description='Finance Automation Bot')
    parser.add_argument('--demo', action='store_true', 
                      help='Run in demo mode (skip actual TPR submission)')
    parser.add_argument('--webhook', action='store_true',
                      help='Run email webhook server for Mailgun inbound emails')
    args = parser.parse_args()
    
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║     Finance Automation Bot - Spring Carnival Committee    ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  📄 Receipt Processing    📝 TPR Automation               ║
    ║  ☁️  Google Drive         📊 Sheets Integration           ║
    ║  📧 Email Webhook                                         ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    if args.demo:
        print("🎬 DEMO MODE ENABLED - TPR forms will not be submitted")
    
    if args.webhook:
        print(f"📧 EMAIL WEBHOOK ENABLED - Listening on port {MailgunConfig.WEBHOOK_PORT}")
    
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
        tasks = []
        
        # Start Gmail monitoring in background
        gmail_task = asyncio.create_task(schedule_gmail_check())
        tasks.append(gmail_task)
        
        # Start webhook server if enabled
        if args.webhook:
            from services.email_webhook import run_webhook_server_async, set_demo_mode
            # Set demo mode for email webhook processing
            set_demo_mode(args.demo)
            logger.info("Starting email webhook server...")
            webhook_task = asyncio.create_task(run_webhook_server_async())
            tasks.append(webhook_task)
        
        # Start Slack bot (this blocks)
        logger.info("Starting Slack bot...")
        print("\n✅ Bot is running! Mention it in Slack with a receipt to get started.")
        print("   Format: @FinanceBot [receipt.pdf] Description of purchase")
        if args.webhook:
            print(f"\n📧 Webhook listening at: http://localhost:{MailgunConfig.WEBHOOK_PORT}/webhook/mailgun")
        print("\n   Press Ctrl+C to stop.\n")
        
        await start_slack_bot(demo_mode=args.demo)
        
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        print("\n👋 Goodbye!")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

