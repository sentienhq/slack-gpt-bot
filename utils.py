import os
import re

import tiktoken
from trafilatura import extract, fetch_url
from trafilatura.settings import use_config

newconfig = use_config()
newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

WAIT_MESSAGES = ["hmmm...", "I'm thinking...", "...", "Let me think...", "I'm thinking...", "Wait, the mind is working...", "Wait a minute, crunchy thoughts...",
                 "Wait, the brain is in overdrive...", "Hmmm, let me think about that...", "Wait a second, the gears are turning ...", "oh ..."]
N_CHUNKS_TO_CONCAT_BEFORE_UPDATING = 20
MAX_TOKENS = 8192


def num_tokens_from_messages(messages, model="gpt-4"):
    """Returns the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        print("Warning: model not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    if model == "gpt-3.5-turbo":
        print("Warning: gpt-3.5-turbo may change over time. Returning num tokens assuming gpt-3.5-turbo-0301.")
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0301")
    elif model == "gpt-4":
        print(
            "Warning: gpt-4 may change over time. Returning num tokens assuming gpt-4-0314.")
        return num_tokens_from_messages(messages, model="gpt-4-0314")
    elif model == "gpt-3.5-turbo-0301":
        # every message follows <|start|>{role/name}\n{content}<|end|>\n
        tokens_per_message = 4
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif model == "gpt-4-0314":
        tokens_per_message = 3
        tokens_per_name = 1
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not implemented for model {model}. See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens.""")
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens


def process_conversation_history(conversation_history, bot_user_id, sys_prompt):
    messages = [{"role": "system", "content": sys_prompt}]
    for message in conversation_history['messages'][:-1]:
        role = "assistant" if message['user'] == bot_user_id else "user"
        message_text = process_message(message, bot_user_id)
        if message_text:
            messages.append({"role": role, "content": message_text})
    return messages


def process_message(message, bot_user_id):
    message_text = message['text']
    role = "assistant" if message['user'] == bot_user_id else "user"
    message_text = clean_message_text(message_text, role, bot_user_id)
    return message_text


def get_user_personality_message(user):
    PSYCHO_SYS_PROMPT = "You are the renowned Dr. Sarah ‘Mastermind’ Freud, a compassionate and accessible psychologist and HR specialist, renowned for her inventive applications of psychoanalysis in a work environment. Analyze profound psychological profiles based on their comments and examine their emotional state. Keep the analysis brief and engaging at all times. Inject-provoking ideas that promote self-reflection, extending advice with a tender and patient touch. Highlight and comment on patterns you perceive in the user's mindset, emotional responses, or activities. Be transparent. Uphold a congenial, critical style, steering clear. Never mention AI, LLM, or large language models. Based on input, analyze what might be the expected company position. Do not include any explanations, only provide a  RFC8259 compliant JSON response  following this format without deviation.: '''[{\"id\": id, \"name\": name, \"expected_position\": expected position in max 30 symbols, \"expected_personality_type\": personality type described in max 50 symbols, \"expected_importance_level\": 10}]''' For importance level use range from 0 to 10 and 10 is maximum importance."
    messages = [{"role": "system", "content": PSYCHO_SYS_PROMPT}]
    messages.append({"role": "user", "content": str(user)})
    return messages


def clean_message_text(message_text, role, bot_user_id):
    if (f'<@{bot_user_id}>' in message_text) or (role == "assistant"):
        message_text = message_text.replace(f'<@{bot_user_id}>', '').strip()
        return message_text
    return message_text


def update_chat(app, channel_id, reply_message_ts, response_text):
    app.client.chat_update(
        channel=channel_id,
        ts=reply_message_ts,
        text=response_text
    )
