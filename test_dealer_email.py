"""Focused tests for public staff-email discovery and append-only output."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dealer_email import extract_emails_from_html, extract_staff_email_records, find_staff_page_urls
from enrich_dealers import _collect_staff_records, _enriched_output_root, _previous_website_email, enrich_staff_emails_file


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

    def test_prose_is_not_mistaken_for_obfuscated_email(self) -> None:
        self.assertEqual(extract_staff_email_records("<p>Schedule service at our shop when convenient.</p>"), [])

    def test_footer_email_does_not_inherit_dealership_name_or_hours(self) -> None:
        html = """<footer><h3>TEDS CAR CENTER</h3><h4>Business Hours</h4>
        <a href="mailto:teds.carcenter@yahoo.com">Email</a></footer>"""
        self.assertEqual(
            extract_staff_email_records(html),
            [{"email": "teds.carcenter@yahoo.com", "name": "", "role": ""}],
        )

    def test_generic_hours_heading_is_not_a_person(self) -> None:
        html = """<div class="staff-info"><h3>Business Hours</h3>
        <a href="mailto:teds.carcenter@yahoo.com">Email</a></div>"""
        self.assertEqual(
            extract_staff_email_records(html),
            [{"email": "teds.carcenter@yahoo.com", "name": "", "role": ""}],
        )

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

    def test_bios_link_is_discovered(self) -> None:
        self.assertEqual(
            find_staff_page_urls('<a href="/bios">Our Bios</a>', "https://northstarauto.com/"),
            ["https://northstarauto.com/bios"],
        )

    def test_unlinked_staff_path_is_probed_within_page_limit(self) -> None:
        home = ("https://northstarauto.com/", "<html><body>Home</body></html>")
        staff = ("https://northstarauto.com/about-us/staff/", """
            <li class="staff-card"><h3>Jordan Lee</h3><h4>General Manager</h4>
            <a href="mailto:jordan@northstarauto.com">Email Me</a></li>""")
        with patch("enrich_dealers.fetch_dealer_html", return_value=home), patch(
            "enrich_dealers._fetch_staff_page", return_value=staff
        ) as fetch:
            records, loaded, count, failed = _collect_staff_records(
                home[0], timeout=1, fetch_mode="http", headed=False, page_limit=1
            )
        self.assertTrue(loaded)
        self.assertEqual(count, 2)
        self.assertEqual(failed, 0)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(records[0]["name"], "Jordan Lee")

    def test_vendor_email_is_not_reused_as_dealer_contact(self) -> None:
        self.assertIsNone(_previous_website_email("hey@intice.com", "https://northstarauto.com"))

    def test_staff_link_on_about_page_is_followed(self) -> None:
        site = "https://northstarauto.com/"
        home = (site, '<a href="/about-us">About Us</a>')
        about = (site + "about-us", '<a href="/about-us/staff/">Meet Our Staff</a>')
        staff = (site + "about-us/staff/", """
            <li><h3>Jordan Lee</h3><h4>General Manager</h4>
            <a href="mailto:jordan@northstarauto.com">Email Me</a></li>""")
        with patch("enrich_dealers.fetch_dealer_html", return_value=home), patch(
            "enrich_dealers._fetch_staff_page", side_effect=[about, staff]
        ) as fetch:
            records, loaded, count, failed = _collect_staff_records(
                site, timeout=1, fetch_mode="http", headed=False, page_limit=2
            )
        self.assertTrue(loaded)
        self.assertEqual(count, 3)
        self.assertEqual(failed, 0)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(records[0]["email"], "jordan@northstarauto.com")


class StaffEmailOutputTests(unittest.TestCase):
    def test_versioned_input_writes_to_next_version(self) -> None:
        with TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "enriched_v8"
            input_dir.mkdir()
            self.assertEqual(_enriched_output_root(input_dir).name, "enriched_v9")
            self.assertEqual(_enriched_output_root(input_dir / "Alaska.csv").name, "enriched_v9")

    def test_empty_result_notes_distinguish_no_email_from_failed_fetch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "v7.csv"
            output = Path(temp_dir) / "v8.csv"
            source.write_text(
                "Website,Staff Emails\n"
                "https://loaded.example,[]\n"
                "https://blocked.example,[]\n",
                encoding="utf-8",
            )
            def scan(website: str, **kwargs: object) -> tuple[list[dict[str, str]], bool, int, int]:
                return ([], True, 2, 1) if "loaded" in website else ([], False, 0, 3)
            with patch("enrich_dealers._collect_staff_records", side_effect=scan):
                enrich_staff_emails_file(
                    source, output, website_col=None, state_col=None,
                    threads=1, timeout=1, fetch_mode="http",
                )
            with output.open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
        self.assertEqual(rows[0]["Staff Emails"], "[]")
        self.assertIn("No public email extracted from 2 loaded page(s)", rows[0]["Staff Email Scan Notes"])
        self.assertIn("1 page fetch(es) failed", rows[0]["Staff Email Scan Notes"])
        self.assertEqual(rows[1]["Staff Emails"], "[]")
        self.assertIn("could not be loaded", rows[1]["Staff Email Scan Notes"])

    def test_empty_staff_array_is_rescanned_and_other_columns_preserved(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "v7.csv"
            output = Path(temp_dir) / "v8.csv"
            source.write_text(
                'Website,Website Email,Staff Emails,Existing Value\n'
                'https://northstarauto.com,sales@northstarauto.com,[],keep me\n',
                encoding="utf-8",
            )
            discovered = [{"email": "jordan@northstarauto.com", "name": "Jordan Lee", "role": "Manager"}]
            with patch("enrich_dealers._collect_staff_records", return_value=(discovered, True, 2, 0)) as scan:
                enrich_staff_emails_file(
                    source, output, website_col=None, state_col=None, threads=1,
                    timeout=1, fetch_mode="http",
                )
            with output.open(newline="", encoding="utf-8") as file:
                row = next(csv.DictReader(file))
        scan.assert_called_once()
        self.assertEqual(json.loads(row["Staff Emails"]), discovered)
        self.assertEqual(row["Website Email"], "sales@northstarauto.com")
        self.assertEqual(row["Existing Value"], "keep me")
        self.assertEqual(row["Staff Email Scan Notes"], "Found 1 email(s) on 2 loaded page(s).")

    def test_prior_same_site_email_is_used_when_scan_found_none(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "v7.csv"
            output = Path(temp_dir) / "v8.csv"
            source.write_text(
                'Website,Website Email,Staff Emails\n'
                'https://northstarauto.com,sales@northstarauto.com,[]\n',
                encoding="utf-8",
            )
            with patch("enrich_dealers._collect_staff_records", return_value=([], False, 0, 2)):
                enrich_staff_emails_file(
                    source, output, website_col=None, state_col=None, threads=1,
                    timeout=1, fetch_mode="http",
                )
            with output.open(newline="", encoding="utf-8") as file:
                row = next(csv.DictReader(file))
        self.assertEqual(json.loads(row["Staff Emails"]), [
            {"email": "sales@northstarauto.com", "name": "", "role": ""}
        ])
        self.assertIn("reused existing Website Email", row["Staff Email Scan Notes"])
        self.assertIn("2 page fetch(es) failed", row["Staff Email Scan Notes"])

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
            with patch("enrich_dealers._collect_staff_records", return_value=(discovered, True, 2, 0)) as scan:
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
            ["Process ID", "Dealer Name", "Website", "Existing Value", "Staff Emails", "Staff Email Scan Notes"],
        )
        self.assertEqual(rows[0]["Process ID"], "11")
        self.assertEqual(rows[0]["Existing Value"], "keep me")
        self.assertEqual(json.loads(rows[0]["Staff Emails"]), discovered)
        self.assertEqual(rows[1]["Existing Value"], "also keep")
        self.assertEqual(rows[1]["Staff Emails"], "[]")
        self.assertEqual(rows[1]["Staff Email Scan Notes"], "No usable website URL.")
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
        self.assertEqual(row["Staff Email Scan Notes"], "Existing staff emails retained; not rescanned.")


if __name__ == "__main__":
    unittest.main()
