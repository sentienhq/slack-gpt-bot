import openai
import os
import requests
import csv
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQyhvq0jSw9hW0yoGasTjKdgYtABTP8M77WtcOOEG_eNExzIYDCFmwSze5b3xnElTbCQnN_B0u2_DAn/pub?gid=0&single=true&output=csv"
response = requests.get(url)

# Use the response's content as input to a CSV reader
csv_reader = csv.reader(response.content.decode('utf-8').splitlines())
csv_rows = []
for row in csv_reader:
    csv_rows.append(row)

for row in csv_rows:
    print(row[0])

from utils import (N_CHUNKS_TO_CONCAT_BEFORE_UPDATING, OPENAI_API_KEY,
                   SLACK_APP_TOKEN, SLACK_BOT_TOKEN, WAIT_MESSAGE,
                   num_tokens_from_messages, process_conversation_history,
                   update_chat)

app = App(token=SLACK_BOT_TOKEN)
openai.api_key = OPENAI_API_KEY


def get_conversation_history(channel_id, thread_ts):
    return app.client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
        inclusive=True
    )

@app.event("app_mention")
def command_handler(body, context):
    try:
        channel_id = body['event']['channel']
        thread_ts = body['event'].get('thread_ts', body['event']['ts'])
        bot_user_id = context['bot_user_id']
        slack_resp = app.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=WAIT_MESSAGE
        )
        reply_message_ts = slack_resp['message']['ts']
        conversation_history = get_conversation_history(channel_id, thread_ts)
        for message in conversation_history['messages'][:-1]:
            role = "assistant" if message['user'] == bot_user_id else "user"
            message_text = message['text']
            if message_text:
                print({"role": role, "content": message_text})


        # messages = process_conversation_history(conversation_history, bot_user_id)
        # # print('Messages: ', messages)
        # num_tokens = num_tokens_from_messages(messages)
        # print(f"Number of tokens: {num_tokens}")

        # openai_response = openai.ChatCompletion.create(
        #     model="gpt-3.5-turbo",
        #     messages=messages,
        #     stream=True
        # )

        # response_text = ""
        # ii = 0
        # for chunk in openai_response:
        #     if chunk.choices[0].delta.get('content'):
        #         ii = ii + 1
        #         response_text += chunk.choices[0].delta.content
        #         if ii > N_CHUNKS_TO_CONCAT_BEFORE_UPDATING:
        #             update_chat(app, channel_id, reply_message_ts, response_text)
        #             ii = 0
        #     elif chunk.choices[0].finish_reason == 'stop':
        #         update_chat(app, channel_id, reply_message_ts, response_text)
    except Exception as e:
        print(f"Error: {e}")
        app.client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"I can't provide a response. Encountered an error:\n`\n{e}\n`")


if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
