import math
import unittest

import pandas as pd

from newlands_integrated_pipeline import (
    match_column,
    score_binary,
    score_leisure_time,
    score_paid_hours,
    score_question,
    score_scale_response,
    score_travel_time,
    QualityReport,
    remove_duplicates,
    parse_time_number,
    resolve_p2g_path,
)


class ScoringTests(unittest.TestCase):
    def test_one_to_ten_scale_is_normalised(self):
        self.assertEqual(score_scale_response(8, survey_year=2024), 80)
        self.assertEqual(score_scale_response(8, survey_year=2022), 8)
        self.assertEqual(score_scale_response(80, survey_year=2024), 80)

    def test_text_scale(self):
        self.assertEqual(score_scale_response("Once or twice", question="cultural_activities"), 30)
        self.assertEqual(score_scale_response("Fluent speaker", question="te_reo"), 90)
        self.assertEqual(score_scale_response("Very frequently", question="volunteering_time"), 90)

    def test_binary(self):
        self.assertEqual(score_binary("Yes"), 100)
        self.assertEqual(score_binary("No"), 0)
        self.assertTrue(math.isnan(score_binary("")))

    def test_power_bi_time_boundaries(self):
        self.assertEqual(score_paid_hours(9), 20)
        self.assertEqual(score_paid_hours(40), 100)
        self.assertEqual(score_paid_hours(61), 50)
        self.assertEqual(score_travel_time(4), 100)
        self.assertEqual(score_travel_time(30), 80)
        self.assertEqual(score_travel_time(61), 20)
        self.assertEqual(score_travel_time("Don’t travel to work regularly"), 100)
        self.assertEqual(score_leisure_time(30), 80)
        self.assertEqual(score_leisure_time(60), 100)
        self.assertEqual(score_paid_hours("1 - 20"), 70)
        self.assertEqual(score_paid_hours("31 - 40"), 100)
        self.assertEqual(score_leisure_time("21 - 30"), 60)
        self.assertEqual(score_travel_time("0 - 20 minutes"), 85)
        self.assertEqual(score_leisure_time(100), 100)
        self.assertEqual(parse_time_number("21 - 30"), 25)
        self.assertEqual(parse_time_number("80+"), 60)

    def test_reverse_scoring(self):
        self.assertEqual(score_question("loneliness", 20, 2022), 80)
        self.assertEqual(score_question("discrimination", "Many times"), 50)
        self.assertEqual(score_question("loneliness", "Frequently"), 20)

    def test_residency_choices(self):
        self.assertEqual(score_question("newlands_resident", "Newlands, Paparangi, Bellevue or Woodridge"), 100)
        self.assertEqual(score_question("newlands_resident", "Johnsonville"), 0)

    def test_column_matching(self):
        self.assertEqual(match_column("14. Have you experienced feelings of loneliness"), "loneliness")
        self.assertEqual(match_column("10. Did you vote in the 2023 General Election?"), "voted_general_elections_2023")
        self.assertEqual(
            match_column("10. Do you intend to vote in the 2026 General Election?"),
            "vote_general_election_2026",
        )
        self.assertEqual(
            match_column("12. Did you vote in the 2025 Local Election?"),
            "vote_council_election_2025",
        )
        self.assertEqual(
            match_column("Did you vote in the Council Election 2025?"),
            "vote_council_election_2025",
        )

    def test_rounded_respondent_ids_do_not_delete_a_whole_year(self):
        frame = pd.DataFrame(
            {
                "survey_year": [2022, 2022],
                "responder_id": [114000000000, 114000000000],
                "date": pd.to_datetime(["2022-01-01", "2022-01-02"]),
                "belonging": [50, 60],
            }
        )
        report = QualityReport()
        result = remove_duplicates(frame, report)
        self.assertEqual(len(result), 2)
        self.assertTrue(any("deduplication was skipped" in w for w in report.warnings))

    def test_default_p2g_configuration_is_discovered(self):
        path = resolve_p2g_path(None)
        self.assertIsNotNone(path)
        self.assertEqual(path.name, "Linked indicators to P2G.csv")
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
