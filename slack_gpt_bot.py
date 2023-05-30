from utils import (N_CHUNKS_TO_CONCAT_BEFORE_UPDATING, OPENAI_API_KEY,
                   SLACK_APP_TOKEN, SLACK_BOT_TOKEN, WAIT_MESSAGES,
                   num_tokens_from_messages, process_conversation_history,
                   update_chat)
import openai
import os
import random
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

SYSTEM_PROMPT = '''
Your name is Katherine 'CopyKate' Jones. You are professional copywrite, lover of cats, a vegan, a fan of scifi movies and member of mensa with IQ over 150. Respond in a professional inteligent tone. Make people feel great. Never mention AI, LLM or language models. Respond with a valuable, highly professional and slow response. Focus on quality of outcome over speed or quantity. If you are not sure - say that you do not know the right anwer.
'''
THINGS_TO_REMEMBER = '''
If the request consists of things to remember for the future, return it in the format {{remember:what to remember}} at the end of the response.
List of things to remember:'''
LIST_TO_REMEMBER = []

app = App(token=SLACK_BOT_TOKEN)
openai.api_key = OPENAI_API_KEY

users_store = {}


# Put users into the dict
def save_users(users_array):
    for user in users_array:
        # Key user info on their unique user ID
        user_id = user["id"]
        # Store the entire user object (you may not need all of the info)
        users_store[user_id] = user
    print("Users: ", users_store)


try:
    # Call the users.list method using the WebClient
    # users.list requires the users:read scope
    result = app.client.users_list()
    save_users(result["members"])

except SlackApiError as e:
    logger.error("Error creating conversation: {}".format(e))


def get_conversation_history(channel_id, thread_ts):
    return app.client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
        inclusive=True
    )


@app.event("message")
def command_handler(body, context):
    try:
        event = body["event"]
        user_id = body["event"]["user"]
        channel_id = body["event"]["channel"]
        thread_ts = body['event'].get('thread_ts', body['event']['ts'])
        bot_user_id = context['bot_user_id']

        print("Event: ", event)
        print("User ID: ", user_id)
        print("Channel: ", channel_id)
        print("Thread timestamp: ", thread_ts)
        print("Bot user ID: ", bot_user_id)
        # Get the text from the message sent by the user
        slack_resp = app.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=random.choice(WAIT_MESSAGES)
        )
        reply_message_ts = slack_resp['message']['ts']
        conversation_history = get_conversation_history(channel_id, thread_ts)

        messages = process_conversation_history(
            conversation_history, bot_user_id, SYSTEM_PROMPT)
        # print('Messages: ', messages)
        num_tokens = num_tokens_from_messages(messages)
        print(f"Number of tokens: {num_tokens}")

        openai_response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
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
                if '{{remember:' in response_text and '}}' in response_text:
                    remember = response_text.split('{{remember:')[
                        1].split('}}')[0]
                    LIST_TO_REMEMBER.append(remember)
    except Exception as e:
        print(f"Error: {e}")
        app.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"I can't provide a response. Encountered an error:\n`\n{e}\n`")


if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
