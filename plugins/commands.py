# Modified by [@AbirHasan2005]
# Now We Can Save UserIDs on a 2nd DB & Broadcast to the DB Users!

import os
import traceback
import datetime
import asyncio
import string
import random
import time
import logging
import datetime
import aiofiles
import aiofiles.os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from info import INLINESEARCH_MSG, CHANNELS, ADMINS
from utils import Media
from database import Database

logger = logging.getLogger(__name__)

## --- MongoDB --- ##
SEC_DB = os.environ.get("SEC_DB", "") # Put 2nd MongoDB URL for Saving UserID
mongodb = Database(SEC_DB, "AbirHasan2005")
broadcast_ids = {}

@Client.on_message(filters.command('inlinesearch'))
async def inlinesearch(bot, message):
    """Inlinesearch command handler"""
    buttons = [[
        InlineKeyboardButton('Search Here', switch_inline_query_current_chat=''),
        InlineKeyboardButton('Go Inline', switch_inline_query=''),
    ]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply(INLINESEARCH_MSG, reply_markup=reply_markup)
    # Add UserID to DB
    if not await mongodb.is_user_exist(message.from_user.id):
        await mongodb.add_user(message.from_user.id)


@Client.on_message(filters.command('channel') & filters.user(ADMINS))
async def channel_info(bot, message):
    """Send basic information of channel"""
    if isinstance(CHANNELS, (int, str)):
        channels = [CHANNELS]
    elif isinstance(CHANNELS, list):
        channels = CHANNELS
    else:
        raise ValueError("Unexpected type of CHANNELS")

    for channel in channels:
        channel_info = await bot.get_chat(channel)
        string = str(channel_info)
        if len(string) > 4096:
            filename = (channel_info.title or channel_info.first_name) + ".txt"
            with open(filename, 'w') as f:
                f.write(string)
            await message.reply_document(filename)
            os.remove(filename)
        else:
            await message.reply(str(channel_info))


@Client.on_message(filters.command('total') & filters.user(ADMINS))
async def total(bot, message):
    """Show total files in database"""
    msg = await message.reply("Processing...⏳", quote=True)
    try:
        total = await Media.count_documents()
        await msg.edit(f'📁 Saved files: {total}')
    except Exception as e:
        logger.exception('Failed to check total files')
        await msg.edit(f'Error: {e}')


@Client.on_message(filters.command('logger') & filters.user(ADMINS))
async def log_file(bot, message):
    """Send log file"""
    try:
        await message.reply_document('TelegramBot.log')
    except Exception as e:
        await message.reply(str(e))


@Client.on_message(filters.command('delete') & filters.user(ADMINS))
async def delete(bot, message):
    """Delete file from database"""
    reply = message.reply_to_message
    if reply and reply.media:
        msg = await message.reply("Processing...⏳", quote=True)
    else:
        await message.reply('Reply to file with /delete which you want to delete', quote=True)
        return

    for file_type in ("document", "video", "audio"):
        media = getattr(reply, file_type, None)
        if media is not None:
            break
    else:
        await msg.edit('This is not supported file format')
        return

    result = await Media.collection.delete_one({
        'file_name': media.file_name,
        'file_size': media.file_size,
        'mime_type': media.mime_type,
        'caption': reply.caption
    })
    if result.deleted_count:
        await msg.edit('File is successfully deleted from database')
    else:
        await msg.edit('File not found in database')


## --- Status | Broadcast --- ##

@Client.on_message(filters.private & filters.command('status') & filters.user(ADMINS))
async def sts(bot, message):
    total_users = await mongodb.total_users_count()
    await message.reply_text(text=f"Total Users in DB: {total_users}", quote=True)

async def forwarder(user_id, message):
    try:
        await message.forward(chat_id=user_id)
        return 200, None
    except FloodWait as e:
        await asyncio.sleep(e.x)
        return forwarder(user_id, message)
    except InputUserDeactivated:
        return 400, f"{user_id} - deactivated\n"
    except UserIsBlocked:
        return 400, f"{user_id} - blocked the bot\n"
    except PeerIdInvalid:
        return 400, f"{user_id} - user id invalid\n"
    except Exception as e:
        return 500, f"{user_id} - {traceback.format_exc()}\n"

@Client.on_message(filters.private & filters.command('broadcast') & filters.user(ADMINS) & filters.reply)
async def broadcast_(bot, message):
    all_users = await mongodb.get_all_users()
    broadcast_msg = message.reply_to_message
    while True:
        broadcast_id = ''.join([random.choice(string.ascii_letters) for i in range(3)])
        if not broadcast_ids.get(broadcast_id):
            break
    out = await message.reply_text(
        text = f"Broadcast Started! You will be notified with a log file when all the users are notified."
    )
    start_time = time.time()
    total_users = await mongodb.total_users_count()
    done = 0
    failed = 0
    success = 0
    broadcast_ids[broadcast_id] = dict(
        total = total_users,
        current = done,
        failed = failed,
        success = success
    )
    async with aiofiles.open('broadcast.txt', 'w') as broadcast_log_file:
        async for user in all_users:
            
            sts, msg = await forwarder(
                user_id = int(user['id']),
                message = broadcast_msg
            )
            if msg is not None:
                await broadcast_log_file.write(msg)
            
            if sts == 200:
                success += 1
            else:
                failed += 1
            
            if sts == 400:
                await mongodb.delete_user(user['id'])
            
            done += 1
            if broadcast_ids.get(broadcast_id) is None:
                break
            else:
                broadcast_ids[broadcast_id].update(
                    dict(
                        current = done,
                        failed = failed,
                        success = success
                    )
                )
    if broadcast_ids.get(broadcast_id):
        broadcast_ids.pop(broadcast_id)
    completed_in = datetime.timedelta(seconds=int(time.time()-start_time))
    await asyncio.sleep(3)
    await out.delete()
    if failed == 0:
        await message.reply_text(
            text=f"broadcast completed in `{completed_in}`\n\nTotal users {total_users}.\nTotal done {done}, {success} success and {failed} failed.",
            quote=True
        )
    else:
        await message.reply_document(
            document='broadcast.txt',
            caption=f"broadcast completed in `{completed_in}`\n\nTotal users {total_users}.\nTotal done {done}, {success} success and {failed} failed.",
            quote=True
        )
    
    await aiofiles.os.remove('broadcast.txt')
