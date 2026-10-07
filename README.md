# Dormitory expense Telegram bot

Google Sheets-backed expense bot. Install requirements.txt, copy config.example.json to config.json and mappings.example.json to mappings.json, then provide your own Telegram token, sheet ID, service-account file and worksheet row mappings locally. The reserved administrative role is admin. Launch python bot.py only after configuration.

This distribution starts with fresh history and removes the historical Telegram token, local paths and personal administrative role. Configurations, credentials, resident mappings and saved user registrations are ignored. Synthetic empty mapping examples require setup; no resident data is bundled.
