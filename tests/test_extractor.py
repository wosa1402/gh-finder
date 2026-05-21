import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_proxy_scanner.extractor import extract_values


class ExtractorTests(unittest.TestCase):
    def test_extracts_public_proxy_candidates(self):
        text = """
        http://8.8.8.8:8080
        socks5://example.com:1080
        1.1.1.1:3128
        """

        values = set(extract_values(text))

        self.assertIn("http://8.8.8.8:8080", values)
        self.assertIn("socks5://example.com:1080", values)
        self.assertIn("1.1.1.1:3128", values)

    def test_skips_private_addresses_and_auth_fragments_by_default(self):
        text = """
        127.0.0.1:8080
        192.168.1.10:8080
        user:pass@8.8.8.8:8080
        """

        values = set(extract_values(text))

        self.assertNotIn("127.0.0.1:8080", values)
        self.assertNotIn("192.168.1.10:8080", values)
        self.assertNotIn("8.8.8.8:8080", values)

    def test_skips_invalid_ports(self):
        text = "8.8.8.8:99999\n8.8.4.4:0"

        values = set(extract_values(text))

        self.assertEqual(values, set())


if __name__ == "__main__":
    unittest.main()
