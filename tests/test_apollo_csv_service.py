import os
import unittest
from services.apollo_csv_service import (
    clean_apollo_phone,
    determine_apollo_lead_category,
    parse_apollo_csv_bytes,
)


class TestApolloCsvService(unittest.TestCase):
    def test_clean_apollo_phone_strips_leading_quote(self):
        self.assertEqual(clean_apollo_phone("'+1 415-420-6461"), "+1 415-420-6461")
        self.assertEqual(clean_apollo_phone("  '+63 917 123 4567 "), "+63 917 123 4567")
        self.assertEqual(clean_apollo_phone(""), "")
        self.assertEqual(clean_apollo_phone("N/A"), "")

    def test_determine_apollo_lead_category(self):
        # Executive / C-suite / VP / Head / Recruiter / Manager with Verified email -> Hot Prospect
        self.assertEqual(
            determine_apollo_lead_category("CEO", "C suite", "Verified", "Cold"),
            "Hot Prospect",
        )
        self.assertEqual(
            determine_apollo_lead_category("Tech Recruiter", "Entry", "Verified", "Cold"),
            "Hot Prospect",
        )
        # Entry/Senior Software Engineer with Cold stage -> New Lead
        self.assertEqual(
            determine_apollo_lead_category("Software Engineer", "Entry", "Verified", "Cold"),
            "New Lead",
        )
        # Explicit override
        self.assertEqual(
            determine_apollo_lead_category("Software Engineer", "Entry", "Verified", "Cold", "VIP"),
            "VIP",
        )

    def test_parse_sample_apollo_csv_file(self):
        sample_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "public",
            "assets",
            "aistudio",
            "apollo-contacts-export_e68a65f0.csv",
        )
        with open(sample_path, "rb") as f:
            raw_bytes = f.read()

        result = parse_apollo_csv_bytes(
            csv_bytes=raw_bytes,
            source_filename="apollo-contacts-export.csv",
            file_id="file_test1234",
            category_override="auto",
        )
        self.assertEqual(result["rows_parsed"], 25)
        contacts = result["contacts"]
        self.assertEqual(len(contacts), 25)

        # Row 1: Sahil Gaba -> Col E = Google, Col F = gsahil@google.com, Col T = +1 415-420-6461
        first = contacts[0]
        self.assertEqual(first["first_name"], "Sahil")
        self.assertEqual(first["last_name"], "Gaba")
        self.assertEqual(first["company"], "Google")
        self.assertEqual(first["email_address"], "gsahil@google.com")
        self.assertEqual(first["contact_number"], "+1 415-420-6461")
        self.assertEqual(first["category"], "New Lead")

        # Row 2: Jhoom Choudhary (Tech Recruiter) -> Hot Prospect
        second = contacts[1]
        self.assertEqual(second["first_name"], "Jhoom")
        self.assertEqual(second["company"], "Google")
        self.assertEqual(second["email_address"], "jhoom@google.com")
        self.assertEqual(second["contact_number"], "+1 415-420-6461")
        self.assertEqual(second["category"], "Hot Prospect")

        # Row 3: Dinesh Varyani (Technical Lead, Manager) -> Hot Prospect
        lead = next(c for c in contacts if c["email_address"] == "dineshvaryani@google.com")
        self.assertEqual(lead["first_name"], "Dinesh")
        self.assertEqual(lead["last_name"], "Varyani")
        self.assertEqual(lead["company"], "Google")
        self.assertEqual(lead["contact_number"], "+1 415-420-6461")
        self.assertEqual(lead["category"], "Hot Prospect")


if __name__ == "__main__":
    unittest.main()
