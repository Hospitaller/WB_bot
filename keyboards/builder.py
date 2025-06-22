from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

def inline_btn(text, callback_data):
    return InlineKeyboardButton(text, callback_data=callback_data)

def inline_kb(buttons: list):
    return InlineKeyboardMarkup(buttons)

def reply_btn(text):
    return KeyboardButton(text)

def reply_kb(buttons: list):
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
