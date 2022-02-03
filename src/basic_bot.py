from requests import post
from logging_setup import logger
from isi_darma.utils import load_credentials, load_reddit_client, get_username
from isi_darma.comments_utils import format_dialogue, get_dialogue_text
from isi_darma.pipeline.response_generators import SpolinBotRG
from typing import List
from argparse import ArgumentParser

SUBREDDIT = "darma_test"
# Assuming (for MVP) that the RTG MT will run on the same machine as this project.
RTG_API = 'http://localhost:6060/translate'
CREDS = load_credentials()


def needs_moderation(dialogue: List[str], title:str="", post:str="", subreddit_guidelines:str=""):
    """
    Skeleton code for moderation classification  
    Expand to take in more parameters (post, subreddit guidelines, etc.)
    """
    return bool(dialogue)

def determine_moderation_strategy(comment_str: str, moderation_decision_result: str = None):
    """
    Skeleton code for determining specific moderation strategy 
    """
    return "respond"


def detect_language(comment_str: str):
    """
    Skeleton code for language detection
    TODO: Check if RTG has an API to enable this.
    """

    return "english"


def translate(comment_str: str, language: str = "english"):
    """
    Skeleton code for translating to target language 
    """

    source = {'source': [comment_str]}
    logger.info(f'Sending source to RTG for translation: {source}')
    try:
        response = post(RTG_API, json=source)
        if response.ok:
            response = response.json()
            logger.info(f'Received translation from RTG for {response["source"]} -> {response["translation"]}')
            return response["translation"][0]
        else:
            logger.warning(f'Translation failed with {response.status_code} -> {response.reason}!')
            logger.warning(f'Response Body from RTG:\n{response.json()}')
            return comment_str

    except Exception as e:
        logger.error(f'Error connecting to RTG API: {e}')
        return comment_str


def main():

    parser = ArgumentParser()
    parser.add_argument("--test", "-t", action="store_true")
    args = parser.parse_args()

    reddit_client = load_reddit_client()
    logger.info("Instantiated Reddit Client")

    # get replies 
    subreddit = reddit_client.subreddit(SUBREDDIT)

    # instantiate response generator
    response_generator = SpolinBotRG()

    for submission in subreddit.stream.submissions():
        title = submission.title
        post_body = submission.selftext

        submission.comments.replace_more(limit=None)
        comment_queue = submission.comments[:]  # Seed with top-level

        dialogues = format_dialogue(comment_queue)

        for d in dialogues: 
            last_comment = d[-1]

            # don't reply to threads for which the bot's response is the last one
            username = get_username(last_comment.author)
            if username == CREDS["username"]:
                continue

            dialogue_text = get_dialogue_text(d)
                # otherwise, respond
            logger.info(f"Retrieved dialogue: {dialogue_text}")

            # 1: translate 
            # 1-1: detect language based on last comment
            source_language = detect_language(last_comment.body)
            logger.info(f"Translating all turns in dialogue")
            translated_dialogue = [translate(comment.body, language="english") for comment in d]
            logger.info(f"Received Translated dialogue: {translated_dialogue}")

            # 2: determine if moderation is needed 
            if not needs_moderation(dialogue=dialogue_text, post=post_body, title=title):
                continue

            # 3: determine the moderation strategy
            moderation_strategy = determine_moderation_strategy(translated_dialogue)

            if moderation_strategy == "respond":
                # 4: generate a response
                best_response = response_generator.generate_response(translated_dialogue)
                # 5: translate back to source language
                logger.info(f"Sending best response for translation: {best_response}")
                final_response = translate(best_response, language=source_language)

            # TODO:  Add logic for when bot the decides NOT to respond, final_response empty in that case
            logger.info(f"Generated response: {final_response}")

            # only actually reply if not run in test mode 
            if not args.test: 
                last_comment.reply(final_response)
                logger.info(f"Replied to comment in subreddit {last_comment.subreddit}")
    return


if __name__ == "__main__":
    main()
