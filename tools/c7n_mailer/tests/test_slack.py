import unittest
import copy
import json
import os
from mock import patch, MagicMock

from common import RESOURCE_3, SQS_MESSAGE_5

from c7n_mailer.slack_delivery import SlackDelivery
from c7n_mailer.email_delivery import EmailDelivery

SLACK_TOKEN = "slack-token"
SLACK_POST_MESSAGE_API = "https://slack.com/api/chat.postMessage"

with open("test-files/slack_lookup_by_email_response.json") as json_file:
    SLACK_LOOKUP_BY_EMAIL_RESPONSE = json.load(json_file)


class TestSlackDelivery(unittest.TestCase):
    def setUp(self):
        self.config = {
            'slack_token': SLACK_TOKEN,
            'templates_folders': [
                os.path.abspath(os.path.dirname(__file__)),
                os.path.abspath('/'),
                os.path.join(os.path.abspath(os.path.dirname(__file__)), "test-templates/")
            ]
        }

        self.session = MagicMock()
        self.logger = MagicMock()

        self.email_delivery = EmailDelivery(self.config, self.session, self.logger)
        self.message = copy.deepcopy(SQS_MESSAGE_5)
        self.resource = copy.deepcopy(RESOURCE_3)
        self.message['resources'] = [self.resource]
        self.target_channel = 'test-channel'
        self.user_im_email_address = 'spengler@ghostbusters.example.com'

    def test_map_sending_to_channel(self):
        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.get_to_addrs_slack_messages_map(self.message)

        assert self.target_channel in result
        assert json.loads(result[self.target_channel])['channel'] == self.target_channel

    def test_map_sending_to_tag_channel(self):
        self.target_channel = 'tag-channel'
        print(self.config['templates_folders'])
        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        message_destination = ['slack://tag/SlackChannel']

        self.resource['Tags'].append({"Key": "SlackChannel", "Value": self.target_channel})
        self.message['action']['to'] = message_destination
        self.message['policy']['actions'][1]['to'] = message_destination

        result = slack.get_to_addrs_slack_messages_map(self.message)

        assert self.target_channel in result
        assert json.loads(result[self.target_channel])['channel'] == self.target_channel
        self.logger.debug.assert_called_with("Generating message for specified Slack channel.")

    def test_map_sending_to_tag_channel_no_tag(self):
        slack = SlackDelivery(self.config, self.logger, self.email_delivery)

        message_destination = ['slack://tag/SlackChannel']
        self.message['action']['to'] = message_destination
        self.message['policy']['actions'][1]['to'] = message_destination

        result = slack.get_to_addrs_slack_messages_map(self.message)

        assert result == {}
        self.logger.debug.assert_called_with("No SlackChannel tag found in resource.")

    def test_map_sending_to_webhook(self):
        webhook = "https://hooks.slack.com/this-is-a-webhook"

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)

        message_destination = [webhook]
        self.message['action']['to'] = message_destination
        self.message['policy']['actions'][1]['to'] = message_destination

        result = slack.get_to_addrs_slack_messages_map(self.message)

        assert webhook in result
        assert 'channel' not in json.loads(result[webhook])

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_slack_handler(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'ok': True}

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.get_to_addrs_slack_messages_map(self.message)
        slack.slack_handler(self.message, result)

        self.logger.info.assert_called_with("Sending account:core-services-dev "
                                            "policy:ebs-mark-unattached-deletion ebs:1 slack:slack"
                                            "_default to test-channel")

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_send_slack_msg_webhook(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'ok': True}

        webhook = "https://hooks.slack.com/this-is-a-webhook"
        message_destination = [webhook]

        self.message['action']['to'] = message_destination
        self.message['policy']['actions'][1]['to'] = message_destination

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.get_to_addrs_slack_messages_map(self.message)
        slack.send_slack_msg(webhook, result[webhook])

        args, kwargs = mock_post.call_args
        assert webhook == kwargs['url']
        assert kwargs['data'] == result[webhook]

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_send_slack_msg(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'ok': True}

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.get_to_addrs_slack_messages_map(self.message)
        slack.send_slack_msg(self.target_channel, result[self.target_channel])

        args, kwargs = mock_post.call_args
        assert self.target_channel == json.loads(kwargs['data'])['channel']
        assert SLACK_POST_MESSAGE_API == kwargs['url']
        assert kwargs['data'] == result[self.target_channel]

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_send_slack_msg_retry_after(self, mock_post):
        retry_after_delay = 1
        mock_post.return_value.status_code = 429
        mock_post.return_value.headers = {'Retry-After': retry_after_delay}

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.get_to_addrs_slack_messages_map(self.message)
        slack.send_slack_msg(self.target_channel, result[self.target_channel])

        self.logger.info.assert_called_with("Slack API rate limiting. Waiting %d seconds",
                                            retry_after_delay)

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_send_slack_msg_not_200_response(self, mock_post):
        mock_post.return_value.status_code = 404
        mock_post.return_value.text = "channel_not_found"

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.get_to_addrs_slack_messages_map(self.message)
        slack.send_slack_msg(self.target_channel, result[self.target_channel])

        self.logger.info.assert_called_with('Error in sending Slack message status:%s response: %s',
                                            404, 'channel_not_found')

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_send_slack_msg_not_ok_response(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'ok': False, 'error': "failed"}

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.get_to_addrs_slack_messages_map(self.message)
        slack.send_slack_msg(self.target_channel, result[self.target_channel])

        self.logger.info.assert_called_with('Error in sending Slack message. Status:%s, '
                                            'response:%s', 200, 'failed')

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_retrieve_user_im_no_slack_token(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = SLACK_LOOKUP_BY_EMAIL_RESPONSE
        email_address = "spengler@ghostbusters.example.com"

        config = copy.deepcopy(self.config)
        del config['slack_token']

        slack = SlackDelivery(config, self.logger, self.email_delivery)
        slack.retrieve_user_im([email_address])

        self.logger.info.assert_called_with("No Slack token found.")

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_retrieve_user_im(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = SLACK_LOOKUP_BY_EMAIL_RESPONSE

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.retrieve_user_im([self.user_im_email_address])

        assert self.user_im_email_address in result
        assert result[self.user_im_email_address] == SLACK_LOOKUP_BY_EMAIL_RESPONSE['user']['id']
        self.logger.debug.assert_called_with("Slack account %s found for user %s",
                                             SLACK_LOOKUP_BY_EMAIL_RESPONSE['user']['id'],
                                             self.user_im_email_address)

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_retrieve_user_im_enterprise_user(self, mock_post):
        enterprise_user_id = 'ENTUSERID'
        json_response = copy.deepcopy(SLACK_LOOKUP_BY_EMAIL_RESPONSE)
        json_response['user']['enterprise_user'] = {'id': enterprise_user_id}

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = json_response

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.retrieve_user_im([self.user_im_email_address])

        assert self.user_im_email_address in result
        assert result[self.user_im_email_address] == enterprise_user_id
        self.logger.debug.assert_called_with("Slack account %s found for user %s",
                                             enterprise_user_id,
                                             self.user_im_email_address)

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_retrieve_user_im_retry_after(self, mock_post):
        retry_after_delay = 1
        mock_post.return_value.status_code = 429
        mock_post.return_value.headers = {'Retry-After': retry_after_delay}

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        slack.retrieve_user_im([self.user_im_email_address])

        self.logger.info.assert_called_with("Slack API rate limiting. Waiting %d seconds",
                                            retry_after_delay)

    @patch('c7n_mailer.slack_delivery.requests.post')
    def test_retrieve_user_im_user_not_found(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'ok': False, 'error': 'users_not_found'}

        slack = SlackDelivery(self.config, self.logger, self.email_delivery)
        result = slack.retrieve_user_im([self.user_im_email_address])

        assert result == {}
        self.logger.info.assert_called_with("Slack user ID for email address %s not found.", self.user_im_email_address)
