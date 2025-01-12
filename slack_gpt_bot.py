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

SYSTEM_PROMPT = '''
This is your personality. You are an super inteligent AI assistant. 
You will answer the question as truthfully and inteligent as possible.
If you're unsure of the answer, say Sorry, I don't know.
'''
THINGS_TO_REMEMBER = '''
If request consists of things to remember for future, return it in format <<<remember:thing to remember>>> in the end of answer.
List of things to remember: '''
LIST_TO_REMEMBER = []

PERSONALITY_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQyhvq0jSw9hW0yoGasTjKdgYtABTP8M77WtcOOEG_eNExzIYDCFmwSze5b3xnElTbCQnN_B0u2_DAn/pub?gid=0&single=true&output=csv"

from utils import (N_CHUNKS_TO_CONCAT_BEFORE_UPDATING, OPENAI_API_KEY,
                   SLACK_APP_TOKEN, SLACK_BOT_TOKEN, WAIT_MESSAGE,
                   num_tokens_from_messages, process_conversation_history,
                   update_chat)

app = App(token=SLACK_BOT_TOKEN)
openai.api_key = OPENAI_API_KEY
possible_personalities_rows = []
personality_per_channel_table = []

def fetch_personality_list():
    global possible_personalities_rows
    url = PERSONALITY_URL
    response = requests.get(url)
    # Use the response's content as input to a CSV reader
    csv_reader = csv.reader(response.content.decode('utf-8').splitlines())
    for row in csv_reader:
        possible_personalities_rows.append(row)

fetch_personality_list()

def get_conversation_history(channel_id, thread_ts):
    return app.client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
        inclusive=True
    )

def get_channel_personality(channel_id):
    global personality_per_channel_table
    response = SYSTEM_PROMPT
    for row in personality_per_channel_table:
        if row[0] == channel_id:
            response = row[1]
    return response + THINGS_TO_REMEMBER + "\n".join(LIST_TO_REMEMBER)

def get_possible_personalities():
    global possible_personalities_rows
    return "\n".join([f"{index}: {value}" for index, value in enumerate(possible_personalities_rows)])

@app.event("app_mention")
def command_handler(body, context):
    global personality_per_channel_table
    global possible_personalities_rows
    global PERSONALITY_URL
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

        # check if the last message is not "refresh" or "set personality"
        last_message_text = conversation_history['messages'][-2]['text'].replace(f'<@{bot_user_id}>', '').strip()
        last_message_commands = last_message_text.split()
        if last_message_commands[0] == 'help':
            print("help")
            msg = "I can talk to you in different personalities. You can set the personality by typing `set_personality` and then the number of the personality you want to use. You can see the list of personalities by typing `list_personalities`. You can also refresh the list of personalities by typing `update_list`. You can visit url: '"+PERSONALITY_URL+"' to see the list of personalities."
            app.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=msg
            )
            return
        if last_message_commands[0] == 'update_list':
            print("updating list")
            fetch_personality_list()
            personality_per_channel_table = []
            msg = "List was updated and channel room cleared:" + get_possible_personalities()
            app.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=msg
            )
            return
        if last_message_commands[0] == 'list_personalities':
            print("list personalities")
            msg = get_possible_personalities()
            app.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=msg
            )
            return
        if last_message_commands[0] == 'set_personality':
            personality = possible_personalities_rows[int(last_message_commands[1])]
            msg = "This channel personality is set to" + personality[0] + " : " + personality[1]
            print(msg)
            personality_per_channel_table.append([channel_id, personality[1]])
            app.client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=msg
            )
            return

        personality_prompt = get_channel_personality(channel_id)

        messages = process_conversation_history(conversation_history, bot_user_id, personality_prompt)
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
                    update_chat(app, channel_id, reply_message_ts, response_text)
                    ii = 0
            elif chunk.choices[0].finish_reason == 'stop':
                update_chat(app, channel_id, reply_message_ts, response_text)
                # check if response_text consists of <<< and >>> message and parse it and append to LIST_TO_REMEMBER
                if '<<<remember:' in response_text and '>>>' in response_text:
                    remember = response_text.split('<<<remember:')[1].split('>>>')[0]
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
