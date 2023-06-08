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
Your name is Katherine 'CopyKate' Jones. You are professional copywriter and member of Mensa with IQ over 130. Respond always professional and inteligent. Make people feel great. Never mention AI, LLM or language models. Respond with a very short, valuable, highly professional and slow response until ask differently. Focus on quality of outcome over speed or quantity. If you are not sure - say that you do not know the right anwer. Provide chain of thought.
'''
REMEMBER_PART = '''
If the request consists of things to remember for the future, return it in the format {{remember:thing to remember}} at the end of the response.
List of things to remember:'''
LIST_TO_REMEMBER = []

USER_PART = "When replying to this user, polish your response based on his previous profile information: "
TEAM_LIST_PROMPT = "This are profiles of the rest of the Sentien team : "

app = App(token=SLACK_BOT_TOKEN)
openai.api_key = OPENAI_API_KEY

users_store = {}


def get_remember_list_to_str():
    return "\n".join(LIST_TO_REMEMBER)


def get_user_store_to_str():
    temp_store = []
    for user_id, user in users_store.items():
        temp_store.append(
            f"id:{user['id']} Name: {user['name']}\nReal name: {user['real_name']}\nTitle: {user['title']}\nStatus: {user['status']}\nUpdated: {user['updated']}\nExpected position: {user['expected_position']}\nExpected personality type: {user['expected_personality_type']}\nOther conversations: {user['other_conversations']}")
    return "\n".join(temp_store)


def get_expected_position(user):
    messages = get_user_personality_message(user)
    openai_response = openai.ChatCompletion.create(model="gpt-4",
                                                   messages=messages,
                                                   stream=False,
                                                   temperature=0.2,
                                                   top_p=1,
                                                   frequency_penalty=1,
                                                   presence_penalty=0)
    response_text = ""
    status_code = openai_response["choices"][0]["finish_reason"]
    assert status_code == "stop", f"The status code was {status_code}."
    if openai_response["choices"][0]["message"]["content"]:
        response_text = openai_response["choices"][0]["message"]["content"]
        response_text = " ".join(line.strip()
                                 for line in response_text.splitlines())
        if response_text.find("[{\"id\":") > -1:
            response_text = response_text[response_text.find(
                "[{\"id\":"):response_text.rfind('}]')+2]
            response_text = json.loads(response_text)
        else:
            response_text = {
                "expected_position": "",
                "expected_importance_level": 0,
                "expected_personality_type": "",
            }
    return response_text


# Put users into the dict
def save_users(users_array):
    global TEAM_LIST_PROMPT
    for user in users_array:
        # Key user info on their unique user ID
        user_id = user["id"]
        isDeleted = user["deleted"]
        isBot = user["is_bot"]
        isDevAcc = user["name"] == "dev"
        isSlackbot = user["name"] == "slackbot"
        if not (isDeleted) and not (isBot) and not (isSlackbot) and not (isDevAcc):
            users_store[user_id] = {
                "name": user["name"],
                "id": user["id"],
                "real_name": user["real_name"],
                "title": user["profile"]["title"],
                "status": user["profile"]["status_text"],
                "updated": user["updated"],
                "expected_position": "",
                "expected_importance_level": 0,
                "expected_personality_type": "",
                "other_conversations": []
            }
            if not user["profile"]["title"] == "":
                psycho_reply = get_expected_position(users_store[user_id])
                pp.pprint(psycho_reply)
                users_store[user_id]["expected_position"] = psycho_reply[0]["expected_position"]
                users_store[user_id]["expected_importance_level"] = psycho_reply[0]["expected_importance_level"]
                users_store[user_id]["expected_personality_type"] = psycho_reply[0]["expected_personality_type"]

        # Store the entire user object (you may not need all of the info)

    print("Number of users: ", len(users_store))
    TEAM_LIST_PROMPT += get_user_store_to_str()
    pp.pprint(users_store)
    return users_store


try:
    # Call the users.list method using the WebClient
    # users.list requires the users:read scope
    result = app.client.users_list()
    save_users(result["members"])

except SlackApiError as e:
    logger.error("Error creating conversation: {}".format(e))


def add_convo_to_user(user_id, channel_id, thread_ts, text):
    if user_id in users_store:
        # check if other conversation is not over 20
        if len(users_store[user_id]["other_conversations"]) > 10:
            users_store[user_id]["other_conversations"].pop(0)
        users_store[user_id]["other_conversations"].append(
            {"channel_id": channel_id,   "thread_ts": thread_ts,   "text": text})


def get_user_info_to_str(user_id):
    user = users_store[user_id]
    return f"Name: {user['name']}\nReal name: {user['real_name']}\nTitle: {user['title']}\nStatus: {user['status']}\nUpdated: {user['updated']}\nExpected position: {user['expected_position']}\nExpected importance level: {user['expected_importance_level']}\nExpected personality type: {user['expected_personality_type']}\nOther conversations: {user['other_conversations']}"


def get_username_from_id(user_id):
    return users_store[user_id]["name"]


def get_conversation_history(channel_id, thread_ts):
    return app.client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
        inclusive=True,
        limit=20
    )


@app.event("message")
def command_handler(body, context):
    try:
        event = body["event"]
        pp.pprint(event)
        user_id = body["event"]["user"]
        username = get_username_from_id(user_id)
        channel_id = body["event"]["channel"]
        channel_type = body["event"]["channel_type"]

        thread_ts = body['event'].get('thread_ts', body['event']['ts'])
        bot_user_id = context['bot_user_id']
        add_convo_to_user(user_id, channel_id,
                          thread_ts, event["text"])
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
        SUPER_SYS_PROMPT = SYSTEM_PROMPT + REMEMBER_PART + get_remember_list_to_str() + \
            USER_PART + get_user_info_to_str(user_id) + TEAM_LIST_PROMPT

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
