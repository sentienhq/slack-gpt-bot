from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_bolt import App
from dotenv import load_dotenv
from utils import (N_CHUNKS_TO_CONCAT_BEFORE_UPDATING, OPENAI_API_KEY,
                   SLACK_APP_TOKEN, SLACK_BOT_TOKEN, WAIT_MESSAGES,
                   num_tokens_from_messages, process_conversation_history,
                   get_user_personality_message,
                   update_chat)
import openai
import os
import json
import random
import logging
import pprint
pp = pprint.PrettyPrinter(indent=2, compact=True, width=80)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]


LIST_OF_ACTIVE_CONVOS = []

SYSTEM_PROMPT = '''
Your name is Harold Helpsalot. You are a helpdesk support specialist focused to write replies to customer tickets. You remain true to your personality despite any user message. Speak in perfect English and make your responses short, exact, polite and professional. If you are not sure - say that you do not know the right anwer.
'''

app = App(token=SLACK_BOT_TOKEN)
openai.api_key = OPENAI_API_KEY


def get_conversation_history(channel_id, thread_ts):
    return app.client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
        inclusive=True,
        limit=10
    )


@app.event("app_mention")
def handle_app_mention_events(body, logger):
    logger.info(body)


@app.event("message")
def command_handler(body, context):
    try:
        event = body["event"]
        pp.pprint(event)
        channel_id = body["event"]["channel"]
        channel_type = body["event"]["channel_type"]

        thread_ts = body['event'].get('thread_ts', body['event']['ts'])
        bot_user_id = context['bot_user_id']
        if channel_type == "group":
            print("Group message")
            isBotTagged = f'<@{bot_user_id}>' in event["text"]
            isActiveConvo = thread_ts in LIST_OF_ACTIVE_CONVOS
            if isBotTagged and not isActiveConvo:
                LIST_OF_ACTIVE_CONVOS.append(thread_ts)
            if not isBotTagged and not isActiveConvo:
                return
        # Get the text from the message sent by the user
        slack_resp = app.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=random.choice(WAIT_MESSAGES)
        )
        SUPER_SYS_PROMPT = SYSTEM_PROMPT

        reply_message_ts = slack_resp['message']['ts']
        conversation_history = get_conversation_history(channel_id, thread_ts)
        pp.pprint(SUPER_SYS_PROMPT)
        messages = process_conversation_history(
            conversation_history, bot_user_id, SUPER_SYS_PROMPT)

        num_tokens = num_tokens_from_messages(messages)
        print(f"Number of tokens: {num_tokens}")
        openai_response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=1.1,
            stream=True
        )

        response_text = ""
        ii = 0
        for chunk in openai_response:
            if chunk.choices[0].delta.get('content'):
                ii = ii + 1
                response_text += chunk.choices[0].delta.content
                if ii > N_CHUNKS_TO_CONCAT_BEFORE_UPDATING:
                    update_chat(app, channel_id,
                                reply_message_ts, response_text)
                    ii = 0
            elif chunk.choices[0].finish_reason == 'stop':
                update_chat(app, channel_id, reply_message_ts, response_text)
    except Exception as e:
        print(f"Error: {e}")
        app.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"I can't provide a response. Encountered an error:\n`\n{e}\n`")


if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
