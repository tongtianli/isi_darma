import os
from logging import Logger
import yaml
import re
import json
import praw
from typing import Dict
from praw.models import Redditor

CRED_FN = os.environ.get("CRED_FP", "/isi_darma/isi_darma/src/isi_darma/creds.yaml")


def get_username(redditor_obj: Redditor):
	"""
    Get the username of a redditor
    Redditor object reference: https://praw.readthedocs.io/en/latest/code_overview/models/redditor.html#praw.models.Redditor
    """
	return redditor_obj.author


def load_credentials(logger: Logger, creds_fn: str = CRED_FN) -> Dict[str, str]:
	with open(creds_fn, "r") as f:
		creds = yaml.safe_load(f)

	logger.debug(f"Loaded credentials: {creds}")
	return creds


def load_reddit_client(logger):
	creds = load_credentials(logger)

	reddit = praw.Reddit(
		user_agent=f"reddit:darma:0 (by u/{creds['username']})",
		client_id=creds["client_id"],
		client_secret=creds["client_secret"],
		username=creds["username"],
		password=creds["password"]
	)

	return reddit


def check_for_opt_out(comment_str: str) -> bool:
	"""
	Check if the comment contains the opt out phrase
	"""

	print('Before Regex: ', comment_str)
	# Remove all non-alphanumeric characters using regex
	re.sub('[\W_]+', '', comment_str)
	print('After Regex: ', comment_str)

	# Covert comment to lowercase
	comment_lower = comment_str.lower()

	if "opt out" in comment_lower or "optout" in comment_lower:
		return True

	return False


def read_db( filename : str = "db.json"):
	"""
	Read the json file for opt-out users
	"""
	return json.loads( open(filename, "r").read() )


def add_to_db(db : dict, username: str, toxicity_score: float, behav_type: str):
	"""
	Save the username to the redis store
	"""
	db[username] = {
					'toxicity_score' : toxicity_score,
	                'behav_type': behav_type
				   }

	with open("db.json", "w") as f:
		f.write(json.dumps(db))

	return db


def search_db(db : dict, username: str):
	"""
	Search the redis store for the username
	"""
	if username in db.keys():
		return True
	return False
