import os, sys, io, traceback, asyncio, random, requests, pymongo
from collections import deque
from datetime import datetime, timedelta
from io import BytesIO
from telethon import TelegramClient, events, types
from telethon.tl.functions.stories import SendStoryRequest
from telethon.tl.types import InputMediaUploadedPhoto, InputMediaUploadedDocument, InputPrivacyValueAllowAll
import subprocess

# Telegram client credentials
api_id = 28731539
api_hash = "7501dd35f99436e403118ac545d50b4b"
client = TelegramClient("Pragyan", api_id, api_hash)

# MongoDB setup
MONGO_URI = "mongodb+srv://PihuMusic:PihuMusic@cluster0.w3eiu.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client_mongo = pymongo.MongoClient(MONGO_URI)
db = client_mongo.PragyanMeta
allowed_users_collection = db.allowed_users

# Owner IDs with full access
owner_ids = [8025794193, 7523749663]
allowed_users = set(user['user_id'] for user in allowed_users_collection.find({"expires_at": {"$gt": datetime.utcnow()}}))

# GPT-4 API details
API_URL = "https://mpzxsmlptc4kfw5qw2h6nat6iu0hvxiw.lambda-url.us-east-2.on.aws/process"
GPT_CHAT_HISTORY = deque(maxlen=30)
TELEGRAM_CHAR_LIMIT = 4096
API_KEY = "sk-proj-hZn6l5KJd6n8kLJzHzyAT3BlbkFJitztuVQn17ElVhezrFyI"

# Helper to check access
def is_allowed(user_id):
    return user_id in owner_ids or user_id in allowed_users

# Command to evaluate Python code with copyable output
@client.on(events.NewMessage(pattern="\.eval", func=lambda e: is_allowed(e.sender_id)))
async def eval(event):
    r = await event.respond("Processing...")
    try:
        code = event.text.split(maxsplit=1)[1]
    except IndexError:
        return await r.edit("❌ **Error:**\n\n*Provide some Python code to execute.*")
    NEWOUT, NEWER = io.StringIO(), io.StringIO()
    sys.stdout, sys.stderr = NEWOUT, NEWER
    try:
        await aexec(code, event)
    except Exception:
        output = traceback.format_exc()
    output = output or NEWOUT.getvalue() or NEWER.getvalue() or "Success"
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    await r.edit(f"**Evaluated Code:**\n```{code}```\n\n**Result:**\n```{output.strip()}```")

async def aexec(code, event):
    exec("async def __aexec(event):\n " + "\n".join(f" {l_}" for l_ in code.split("\n")))
    return await locals()["__aexec"](event)

# Bash command execution with copyable output
# Bash command execution with copyable output
@client.on(events.NewMessage(pattern="\.bash", func=lambda e: is_allowed(e.sender_id)))
async def bash_handler(event):
    try:
        cmd = event.text.split(" ", maxsplit=1)[1]
    except IndexError:
        return await event.reply("❌ **Error:**\n\n*Provide a command to execute.*")
    
    processing_message = await event.reply("⚙️ Processing command...")
    stdout, stderr = await bash(cmd)
    
    # Combine the stdout and stderr
    result = f"Output:\n```{stdout}```" if stdout else "✔️ No Output"
    if stderr:
        result += f"\n❌ **Errors:**\n```{stderr}```"
    
    # Check if the result exceeds the Telegram character limit
    if len(result) > TELEGRAM_CHAR_LIMIT:
        # Save the result to a file named pragyan.txt and send it
        with open("pragyan.txt", "w") as file:
            file.write(result)
        
        await event.client.send_file(event.chat_id, "pragyan.txt", caption=f"Result of `{cmd}`", reply_to=event.id)
        os.remove("pragyan.txt")  # Clean up the file after sending
    else:
        await processing_message.edit(result)

async def bash(cmd):
    process = await asyncio.create_subprocess_shell(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = await process.communicate()
    return stdout.decode(), stderr.decode()


# Generate responses using GPT with copyable output
@client.on(events.NewMessage(pattern="\.gpt(?: (.+)|$)", func=lambda e: is_allowed(e.sender_id)))
async def generate_response(event):
    query = event.pattern_match.group(1) or (await event.get_reply_message()).message
    if query == "-c":
        GPT_CHAT_HISTORY.clear()
        return await event.reply("🧹 **Chat History Cleared!**")
    GPT_CHAT_HISTORY.append({"role": "user", "content": query})
    response = requests.post(API_URL, headers={"Authorization": f"Bearer {API_KEY}"}, json={
        "model": "gpt-4o", "temperature": 0.9, "messages": list(GPT_CHAT_HISTORY)})
    result = response.json()["choices"][0]["message"]["content"]
    GPT_CHAT_HISTORY.append({"role": "assistant", "content": result})
    await event.reply(f"**Query:** ```{query}```\n\n**Response:** ```{result}```")

# Upload a Story
@client.on(events.NewMessage(pattern=r"\.story", func=lambda e: is_allowed(e.sender_id)))
async def upload_story(event):
    reply = await event.get_reply_message()
    if not reply or not isinstance(reply.media, (types.MessageMediaDocument, types.MessageMediaPhoto)):
        return await event.reply("❌ Reply to a valid photo or video.")
    status_message = await event.reply("Uploading...")
    media_file = await client.download_media(reply.media, file='temp_media')
    uploaded_media = await client.upload_file(media_file)
    random_id = random.randint(1, 2**32)
    if isinstance(reply.media, types.MessageMediaDocument):
        media = InputMediaUploadedDocument(file=uploaded_media)
    else:
        media = InputMediaUploadedPhoto(file=uploaded_media)
    await client(SendStoryRequest(media=media, random_id=random_id, privacy_rules=[InputPrivacyValueAllowAll()]))
    await status_message.edit("✅ Uploaded!")

# Add a user temporarily
@client.on(events.NewMessage(pattern=r"\.add (\d+|\S+) (\d+\w+)", func=lambda e: is_allowed(e.sender_id)))
async def add_user(event):
    args = event.text.split(maxsplit=2)
    if len(args) < 3:
        return await event.reply("❌ **Error:** Provide a user and duration (e.g., `1day` or `3hr`).")
    user_id_or_name, duration_str = args[1], args[2]
    try:
        value, unit = int(duration_str[:-3].strip()), duration_str[-3:].strip()
        duration = timedelta(days=value) if "day" in unit else timedelta(hours=value)
        expires_at = datetime.utcnow() + duration
        user_id = int(user_id_or_name) if user_id_or_name.isdigit() else (await client.get_entity(user_id_or_name)).id
        allowed_users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "expires_at": expires_at}},
            upsert=True
        )
        allowed_users.add(user_id)
        await event.reply(f"✅ **Success:** User added for {duration_str}.")
    except Exception as e:
        await event.reply(f"❌ **Error:** {str(e)}")

# Ping command
@client.on(events.NewMessage(pattern=r"\.ping", func=lambda e: is_allowed(e.sender_id)))
async def ping(event):
    start_time = datetime.now()
    msg = await event.respond("🏓 Pong!")
    end_time = datetime.now()
    ping_duration = (end_time - start_time).microseconds / 1000
    await msg.edit(f"🏓 Pong!\nPing: {ping_duration:.2f} ms")

# Help command with bold commands
@client.on(events.NewMessage(pattern=r"\.help", func=lambda e: is_allowed(e.sender_id)))
async def help_command(event):
    help_text = """
**Command List:**

1. **.eval <code>** - Evaluate Python code.
2. **.bash <command>** - Execute a bash command.
3. **.gpt <query>** - Generate a response using GPT-4.
4. **.story** - Upload a replied media (photo or video) as a story.
5. **.add <username or user_id> <duration>** - Add a user temporarily (e.g., 1day, 3hr).
6. **.ping** - Check the bot's response time.
7. **.help** - Display this help message.
"""
    await event.respond(help_text)

# List all added users
# List all added users
@client.on(events.NewMessage(pattern=r"\.listadd", func=lambda e: is_allowed(e.sender_id)))
async def list_added_users(event):
    users = allowed_users_collection.find()

    # Convert cursor to list and check if it's empty
    users_list = list(users)
    if len(users_list) == 0:
        return await event.reply("ℹ️ **No added users found.**")

    message = "**Added Users:**\n\n"
    for user in users_list:
        user_info = f"User ID: `{user['user_id']}`\nExpires At: `{user['expires_at'].strftime('%Y-%m-%d %H:%M:%S')}`\n"
        message += user_info + "\n"
    
    await event.reply(message)


# Remove a user from the allowed list
@client.on(events.NewMessage(pattern=r"\.rem (\d+|\S+)", func=lambda e: is_allowed(e.sender_id)))
async def remove_user(event):
    user_id_or_name = event.pattern_match.group(1)
    
    try:
        if user_id_or_name.isdigit():
            user_id = int(user_id_or_name)
        else:
            user_entity = await client.get_entity(user_id_or_name)
            user_id = user_entity.id

        # Remove user from the database and local set
        result = allowed_users_collection.delete_one({"user_id": user_id})
        allowed_users.discard(user_id)
        
        if result.deleted_count > 0:
            await event.reply(f"✅ **Success:** User `{user_id}` has been removed.")
        else:
            await event.reply(f"❌ **Error:** User `{user_id}` not found in the allowed list.")
    
    except Exception as e:
        await event.reply(f"❌ **Error:** {str(e)}")


# Start the bot
async def main():
    await client.start()
    await client.run_until_disconnected()

asyncio.get_event_loop().run_until_complete(main())
