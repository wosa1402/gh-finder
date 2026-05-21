import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_proxy_scanner.web import normalize_queries, read_csv_rows


class WebHelperTests(unittest.TestCase):
    def test_normalize_queries_accepts_textarea_content(self):
        queries = normalize_queries("one\n\n two \n")

        self.assertEqual(queries, ["one", "two"])

    def test_read_csv_rows_returns_latest_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rows.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["value"])
                writer.writeheader()
                writer.writerow({"value": "first"})
                writer.writerow({"value": "second"})

            payload = read_csv_rows(path, limit=1)

            self.assertEqual(payload["count"], 2)
            self.assertEqual(payload["rows"], [{"value": "second"}])


if __name__ == "__main__":
    unittest.main()
