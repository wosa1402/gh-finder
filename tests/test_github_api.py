import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_proxy_scanner.github_api import GitHubClient


class GitHubClientTests(unittest.TestCase):
    def test_build_url_escapes_spaces_in_api_file_path(self):
        client = GitHubClient(token="token")

        url = client._build_url(
            "/repositories/204249844/contents/proxy source.txt?ref=efea013788aa8a1e20f4caf609bf3c92883681a4",
            None,
        )

        self.assertIn("proxy%20source.txt", url)
        self.assertNotIn("proxy source.txt", url)

    def test_build_url_keeps_search_query_encoding(self):
        client = GitHubClient(token="token")

        url = client._build_url(
            "/search/code",
            {"q": '"https://" "proxy" extension:txt', "page": "1", "per_page": "50"},
        )

        self.assertIn("%22https%3A%2F%2F%22", url)
        self.assertIn("per_page=50", url)


if __name__ == "__main__":
    unittest.main()
