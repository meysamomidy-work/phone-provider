"""Focused tests for public staff-email discovery and append-only output."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dealer_email import extract_emails_from_html, extract_staff_email_records, find_staff_page_urls
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
            extract_staff_email_records(html),
            [
                {
                    "email": "jordan.lee@northstarauto.com",
                    "name": "Jordan Lee",
                    "role": "General Manager",
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
        records = extract_staff_email_records(html)
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
        record = extract_staff_email_records(html)[0]
        self.assertEqual(record["name"], "Taylor Morgan")
        self.assertEqual(record["role"], "Finance Director")

    def test_kendall_style_h3_h4_card_is_linked_to_email(self) -> None:
        # Kendall Toyota of Anchorage presents each employee this way: a card
        # with H3 name, H4 job title, and a following "Email Me" link.
        html = """
        <ul><li>
          <img alt="Tim Toth" src="tim.jpg">
          <h3>Tim Toth</h3><h4>General Manager</h4>
          <div class="employee-actions"><a href="mailto:tim.toth@kendallauto.com">Email Me</a></div>
        </li></ul>
        """
        self.assertEqual(
            extract_staff_email_records(html),
            [{"email": "tim.toth@kendallauto.com", "name": "Tim Toth", "role": "General Manager"}],
        )

    def test_job_title_with_call_is_not_rejected(self) -> None:
        html = """
        <li class="staff-item"><h3>Darlene Snow</h3><h4>Call Center Lead</h4>
        <a href="mailto:darlenesnow@kendallauto.com">Email Me</a></li>
        """
        self.assertEqual(
            extract_staff_email_records(html),
            [{"email": "darlenesnow@kendallauto.com", "name": "Darlene Snow", "role": "Call Center Lead"}],
        )

    def test_script_and_template_emails_are_not_staff_contacts(self) -> None:
        html = """
        <script>const packageAuthor = "bootstrap@packages.example";</script>
        <template>react-maintainer@packages.example</template>
        <style>.x::after { content: "styles@packages.example"; }</style>
        <p>Sales: <a href="mailto:sales@northstarauto.com">sales@northstarauto.com</a></p>
        """
        self.assertEqual(
            extract_staff_email_records(html),
            [{"email": "sales@northstarauto.com", "name": "", "role": ""}],
        )
        self.assertEqual(extract_emails_from_html(html), ["sales@northstarauto.com"])

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

    def test_existing_staff_json_is_migrated_without_a_rescan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "dealers.csv"
            output = Path(temp_dir) / "staff-emails.csv"
            source.write_text(
                "Dealer Name,Website,Staff Emails\n"
                'Northstar Auto,https://northstarauto.com,"[{""email"":""jordan@northstarauto.com"",""name"":""Jordan Lee"",""source_url"":""https://northstarauto.com/team""}]"\n',
                encoding="utf-8",
            )
            with patch("enrich_dealers._collect_staff_records") as scan:
                enrich_staff_emails_file(
                    source,
                    output,
                    website_col=None,
                    state_col=None,
                    threads=1,
                    timeout=1,
                    fetch_mode="http",
                )
            scan.assert_not_called()
            with output.open(newline="", encoding="utf-8") as file:
                row = next(csv.DictReader(file))

        self.assertEqual(
            json.loads(row["Staff Emails"]),
            [{"email": "jordan@northstarauto.com", "name": "Jordan Lee"}],
        )


if __name__ == "__main__":
    unittest.main()
