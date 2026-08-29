import json
import unittest
from pathlib import Path

from posting.instagram import InstagramCarouselPublisher


class FakeAssetStore:
    def __init__(self):
        self.uploaded = []
        self.deleted = []

    def upload(self, local_path):
        key = f"key-{len(self.uploaded) + 1}"
        self.uploaded.append(local_path)
        return key, f"https://media.example/{key}.png"

    def delete(self, object_key):
        self.deleted.append(object_key)


class FakeInstagramPublisher(InstagramCarouselPublisher):
    def __init__(self, asset_store):
        super().__init__(asset_store, instagram_user_id="123", access_token="token")
        self.requests = []

    def _post(self, route, values):
        self.requests.append((route, values))
        return {"id": str(len(self.requests))}

    def _get(self, route, values):
        return {"status_code": "FINISHED"}

    def _as_jpeg(self, asset, temporary_directory, asset_index):
        return Path(asset)


class InstagramPublisherTests(unittest.TestCase):
    def test_publishes_a_ready_carousel_with_persisted_caption_and_hashtags(self):
        store = FakeAssetStore()
        publisher = FakeInstagramPublisher(store)
        package = {
            "package_platform": "instagram", "package_account": "o2_english",
            "content_format": "instagram_idiom_carousel", "assets": json.dumps(["slide1.png", "slide2.png"]),
            "caption": "Learn an idiom", "hashtags": json.dumps(["#English", "#Idioms"]),
        }
        external_id = publisher.publish_package(package)
        self.assertEqual(external_id, "4")
        self.assertEqual(store.uploaded, ["slide1.png", "slide2.png"])
        self.assertEqual(store.deleted, ["key-1", "key-2"])
        self.assertEqual(publisher.requests[2][1]["caption"], "Learn an idiom #English #Idioms")

    def test_rejects_a_package_outside_the_o2_instagram_contract_before_upload(self):
        store = FakeAssetStore()
        publisher = FakeInstagramPublisher(store)
        package = {
            "package_platform": "instagram", "package_account": "o2_english",
            "content_format": "instagram_idiom_carousel", "assets": json.dumps(["slide1.png"]),
            "caption": "Learn an idiom", "hashtags": json.dumps(["#English"]),
        }

        with self.assertRaisesRegex(ValueError, "two to ten"):
            publisher.publish_package(package)

        self.assertEqual(store.uploaded, [])
