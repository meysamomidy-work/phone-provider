"""Focused tests for public staff-email discovery and append-only output."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dealer_email import extract_staff_email_records, find_staff_page_urls
from enrich_dealers import enrich_staff_emails_file


class StaffEmailExtractionTests(unittest.TestCase):
    def test_staff_card_keeps_name_role_and_email(self) -> None:
        html = """
        <section class="staff-card">
          <h3>Jordan Lee</h3>
          <p class="job-title">General Manager</p>
          <a href="mailto:jordan.lee@northstarauto.com">Email Jordan</a>
        </section>
        """
        self.assertEqual(
            extract_staff_email_records(html, "https://northstarauto.com/our-team"),
            [
                {
                    "email": "jordan.lee@northstarauto.com",
                    "name": "Jordan Lee",
                    "role": "General Manager",
                    "source_url": "https://northstarauto.com/our-team",
                }
            ],
        )

    def test_json_ld_and_obfuscated_public_email_are_collected(self) -> None:
        html = """
        <script type="application/ld+json">
          {"@context":"https://schema.org","@type":"Person","name":"Avery Kim",
           "jobTitle":"Service Director","email":"avery@northstarauto.com"}
        </script>
        <p>Contact sales at sales [at] northstarauto [dot] com</p>
        """
        records = extract_staff_email_records(html, "https://northstarauto.com/contact")
        self.assertEqual([record["email"] for record in records], ["avery@northstarauto.com", "sales@northstarauto.com"])
        self.assertEqual(records[0]["name"], "Avery Kim")
        self.assertEqual(records[0]["role"], "Service Director")

    def test_unlabelled_card_name_and_role_are_inferred(self) -> None:
        html = """
        <div class="team-member">
          <strong>Taylor Morgan</strong>
          <p>Finance Director</p>
          <a href="mailto:taylor@northstarauto.com">Contact</a>
        </div>
        """
        record = extract_staff_email_records(html, "https://northstarauto.com/team")[0]
        self.assertEqual(record["name"], "Taylor Morgan")
        self.assertEqual(record["role"], "Finance Director")

    def test_staff_page_links_are_same_site_ranked_and_bounded(self) -> None:
        html = """
        <a href="/contact-us">Contact Us</a>
        <a href="/meet-our-team">Meet Our Team</a>
        <a href="/inventory">Inventory</a>
        <a href="https://other.example/team">External team</a>
        """
        self.assertEqual(
            find_staff_page_urls(html, "https://northstarauto.com/", limit=2),
            [
                "https://northstarauto.com/meet-our-team",
                "https://northstarauto.com/contact-us",
            ],
        )


class StaffEmailOutputTests(unittest.TestCase):
    def test_staff_only_preserves_source_columns_and_does_not_run_other_enrichment(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "dealers.csv"
            output = Path(temp_dir) / "staff-emails.csv"
            source.write_text(
                "Process ID,Dealer Name,Website,Existing Value\n"
                "11,Northstar Auto,https://northstarauto.com,keep me\n"
                "12,No Website,,also keep\n",
                encoding="utf-8",
            )
            discovered = [
                {
                    "email": "jordan.lee@northstarauto.com",
                    "name": "Jordan Lee",
                    "role": "General Manager",
                    "source_url": "https://northstarauto.com/our-team",
                }
            ]
            with patch("enrich_dealers._collect_staff_records", return_value=(discovered, True, 2)) as scan:
                enrich_staff_emails_file(
                    source,
                    output,
                    website_col=None,
                    state_col=None,
                    threads=1,
                    timeout=1,
                    fetch_mode="http",
                )
            scan.assert_called_once()
            with output.open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))

        self.assertEqual(
            list(rows[0]),
            ["Process ID", "Dealer Name", "Website", "Existing Value", "Staff Emails"],
        )
        self.assertEqual(rows[0]["Process ID"], "11")
        self.assertEqual(rows[0]["Existing Value"], "keep me")
        self.assertEqual(json.loads(rows[0]["Staff Emails"]), discovered)
        self.assertEqual(rows[1]["Existing Value"], "also keep")
        self.assertEqual(rows[1]["Staff Emails"], "[]")
        self.assertNotIn("Website Provider", rows[0])


if __name__ == "__main__":
    unittest.main()
