import unittest
from src.core.models import MediaAttachment, Announcement


class TestModels(unittest.TestCase):
    def test_media_attachment_detection(self):
        att_gif = MediaAttachment(
            url="https://example.com/test.gif",
            filename="dance.gif",
            content_type="image/gif",
            is_animation=True
        )
        self.assertTrue(att_gif.is_animation)
        self.assertFalse(att_gif.is_image)
        self.assertFalse(att_gif.is_video)

        att_png = MediaAttachment(
            url="https://example.com/photo.png",
            filename="photo.png",
            content_type="image/png"
        )
        self.assertFalse(att_png.is_animation)
        self.assertTrue(att_png.is_image)
        self.assertFalse(att_png.is_video)

        att_mp4 = MediaAttachment(
            url="https://example.com/video.mp4",
            filename="video.mp4",
            content_type="video/mp4"
        )
        self.assertFalse(att_mp4.is_animation)
        self.assertFalse(att_mp4.is_image)
        self.assertTrue(att_mp4.is_video)

        att_doc = MediaAttachment(
            url="https://example.com/doc.pdf",
            filename="document.pdf",
            content_type="application/pdf"
        )
        self.assertFalse(att_doc.is_animation)
        self.assertFalse(att_doc.is_image)
        self.assertFalse(att_doc.is_video)

    def test_announcement_defaults(self):
        ann = Announcement(
            source_message_id=123,
            channel_id=456,
            author_name="Alice",
            author_is_bot=False,
            content="Hello world"
        )
        self.assertEqual(ann.source_message_id, 123)
        self.assertEqual(ann.attachments, [])
        self.assertEqual(ann.raw_embeds, [])
        self.assertIsNone(ann.animation_url)


if __name__ == "__main__":
    unittest.main()
