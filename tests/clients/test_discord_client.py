import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.clients.discord_client import DiscordClient


class TestDiscordClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = DiscordClient()

    @patch("aiohttp.ClientSession")
    async def test_refresh_attachment_url_success(self, mock_session_cls):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "refreshed_urls": [{"refreshed": "https://cdn.discordapp.com/refreshed.gif"}]
        })

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_cm
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_cls.return_value = mock_session

        url = "https://cdn.discordapp.com/old.gif"
        refreshed = await self.client.refresh_attachment_url(url)
        self.assertEqual(refreshed, "https://cdn.discordapp.com/refreshed.gif")

    @patch("aiohttp.ClientSession")
    async def test_refresh_attachment_url_fallback_on_error(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session.post.side_effect = Exception("Network failure")
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session_cls.return_value = mock_session

        url = "https://cdn.discordapp.com/original.gif"
        result = await self.client.refresh_attachment_url(url)
        self.assertEqual(result, url)

    async def test_set_mirror_service(self):
        mock_service = MagicMock()
        self.client.set_mirror_service(mock_service)
        self.assertEqual(self.client.mirror_service, mock_service)


if __name__ == "__main__":
    unittest.main()
