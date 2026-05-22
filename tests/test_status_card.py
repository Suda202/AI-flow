import unittest
from unittest import mock

import main


class StatusCardTests(unittest.TestCase):
    def test_status_card_disabled_skips_feishu_send(self):
        with mock.patch.object(main, "FEISHU_SEND_STATUS_CARD", False), \
             mock.patch.object(main, "send_card_to_feishu") as send_card_to_feishu, \
             mock.patch.object(main, "send_card_to_webhook") as send_card_to_webhook:
            sent = main.send_status_to_feishu("No videos", "Nothing new today")

        self.assertFalse(sent)
        send_card_to_feishu.assert_not_called()
        send_card_to_webhook.assert_not_called()

    def test_status_card_enabled_sends_feishu_card(self):
        with mock.patch.object(main, "FEISHU_SEND_STATUS_CARD", True), \
             mock.patch.object(main, "send_card_to_feishu", return_value=True) as send_card_to_feishu, \
             mock.patch.object(main, "send_card_to_webhook") as send_card_to_webhook:
            sent = main.send_status_to_feishu("No videos", "Nothing new today")

        self.assertTrue(sent)
        send_card_to_feishu.assert_called_once()
        send_card_to_webhook.assert_not_called()


if __name__ == "__main__":
    unittest.main()
