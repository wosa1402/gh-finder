import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_proxy_scanner.models import ProxyCandidate
from github_proxy_scanner.storage import append_candidates


class StorageTests(unittest.TestCase):
    def test_append_candidates_deduplicates_by_value(self):
        candidate = ProxyCandidate(
            value="http://8.8.8.8:8080",
            host="8.8.8.8",
            port=8080,
            scheme="http",
            source_url="https://github.com/example/repo/blob/main/proxies.txt",
            repository="example/repo",
            path="proxies.txt",
            line=1,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "proxies.csv"
            jsonl_path = Path(temp_dir) / "proxies.jsonl"

            first_new, first_total = append_candidates([candidate], csv_path=csv_path, jsonl_path=jsonl_path)
            second_new, second_total = append_candidates([candidate], csv_path=csv_path, jsonl_path=jsonl_path)

            self.assertEqual((first_new, first_total), (1, 1))
            self.assertEqual((second_new, second_total), (0, 1))

            with csv_path.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
