import os
import re
import ast
import tweepy
import twikit
import asyncio
from random import randint
import pandas as pd
from datetime import datetime
from playwright.async_api import async_playwright
from config.settings import Settings

# Get configuration from Settings
settings = Settings()

# Twitter API credentials from Settings
TWITTER_API_KEY = settings.TWITTER_API_KEY
TWITTER_API_KEY_SECRET = settings.TWITTER_API_KEY_SECRET
TWITTER_BEARER = settings.TWITTER_BEARER_TOKEN
TWITTER_ACCESS_TOKEN = settings.TWITTER_ACCESS_TOKEN
TWITTER_ACCESS_TOKEN_SECRET = settings.TWITTER_ACCESS_TOKEN_SECRET
TWITTER_CLIENT_ID = settings.TWITTER_CLIENT_ID
TWITTER_CLIENT_SECRET = settings.TWITTER_CLIENT_SECRET
TWITTER_USER = settings.TWITTER_USER
TWITTER_EMAIL = settings.TWITTER_EMAIL
TWITTER_PASSWORD = settings.TWITTER_PASSWORD

async def main():
    twitter_client = twikit.Client(language='en-US')
    # Authenticate to Twitter using cookies
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cookies_path = os.path.join(script_dir, 'twitter_cookies.json')
    await twitter_client.login(auth_info_1=TWITTER_USER, auth_info_2=TWITTER_EMAIL, password=TWITTER_PASSWORD)
    twitter_client.save_cookies('twitter_cookies.json')

if __name__ == "__main__":
    asyncio.run(main())

