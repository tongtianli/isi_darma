from googleapiclient import discovery
from abc import ABC, abstractmethod
from requests import get, post
import operator
import time

API_KEY = 'AIzaSyC30WbnABE2zjzK4Be58ytkatxgOC3yg9I'


class ModerationClassifier(ABC):

	@abstractmethod
	def needs_moderation(self, toxicity):
		pass


class PerspectiveAPIModerator(ModerationClassifier):

	def __init__(self, logger) -> None:

		self.perspec_client = discovery.build(
			"commentanalyzer",
			"v1alpha1",
			developerKey=API_KEY,
			discoveryServiceUrl="https://commentanalyzer.googleapis.com/$discovery/rest?version=v1alpha1",
			static_discovery=False,
		)

		self.toxicity_threshold = 0.5
		self.logger = logger
		self.moderator_endpoint = "http://127.0.0.1:5050"

	# self.behav_types = self.get_behavTypes(self.tox_classifier_behavtypes, self.toxicity_endpoint)

	def needs_moderation(self, toxicity) -> bool:
		return toxicity >= self.toxicity_threshold

	def measure_toxicity(self, comment) -> (float, str):

		analyze_request = {
			'comment': {'text': comment},
			'requestedAttributes': {
				'TOXICITY': {},
				'SEVERE_TOXICITY': {},
				'IDENTITY_ATTACK': {},
				'INSULT': {},
				'PROFANITY': {},
				'THREAT': {},
			}
		}

		try:
			perspec_response = self.perspec_client.comments().analyze(body=analyze_request).execute()
			needs_mod, toxicity_score, behav_type = self.map_behavtypes(perspec_response)
			moderator_response = self.get_moderator_response(comment)
			final_decision = self.intersect_moderation(needs_mod, moderator_response)
			return final_decision, toxicity_score, behav_type

		except Exception as e:

			if e.status_code == 429:
				self.logger.debug(f"API rate limit reached. Waiting for 60 seconds.")
				time.sleep(60)
				self.logger.debug(f'Retrying toxicity measurement for comment: {analyze_request["comment"]["text"]}')
				needs_mod, toxicity_score, behav_type = self.measure_toxicity(comment)

			else:
				self.logger.error(f"Exception occurred with code {e.status_code}: {e} for comment: {analyze_request['comment']['text']}. Setting toxicity to 0 with empty behaviour type.")
				needs_mod, toxicity_score, behav_type = False, 0, ""

		return needs_mod, toxicity_score, behav_type

	def map_behavtypes(self, toxicity_scores):
		mapping = {
					"toxicity": toxicity_scores["attributeScores"]["TOXICITY"]["summaryScore"]["value"],
					"severe toxicity": toxicity_scores["attributeScores"]["SEVERE_TOXICITY"]["summaryScore"]["value"],
					"behav_types": {
						"namecalling": toxicity_scores["attributeScores"]["INSULT"]["summaryScore"]["value"],
						"ad-hominem_attacking": toxicity_scores["attributeScores"]["IDENTITY_ATTACK"]["summaryScore"]["value"],
						"obscene/vulgar": toxicity_scores["attributeScores"]["PROFANITY"]["summaryScore"]["value"],
						"dehumanizing": toxicity_scores["attributeScores"]["THREAT"]["summaryScore"]["value"]
					}
				}

		self.logger.info(f"Toxicity scores after mapping: {mapping}")

		if self.needs_moderation(mapping["toxicity"]) or self.needs_moderation(mapping["severe toxicity"]):
			needs_mod = True
			behav_type = max(mapping["behav_types"].items(), key=operator.itemgetter(1))[0]
			score = mapping["behav_types"][behav_type]
			self.logger.info(f"Current max Toxicity Behaviour type is '{behav_type}' with score = {score}")

		else:
			self.logger.info(f'Toxicity score: {mapping["toxicity"]} or Severe Toxicity score: {mapping["severe toxicity"]} is below threshold {self.toxicity_threshold}. Setting behaviour type to empty string.')
			needs_mod, score, behav_type = False, 0.0, ""

		return needs_mod, score, behav_type

	def get_moderator_response(self, comment):
		request = { "1": { "comment" : comment } }
		resp = post(self.moderator_endpoint, json=request)
		if resp.status_code == 200:
			return resp.json()["0"]["score"]
		else:
			self.logger.info(f"Endpoint {endpoint} is not healthy. Returning status code {endpoint_health}.")
			return {}
