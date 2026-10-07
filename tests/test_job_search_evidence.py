"""Synthetic offline integrity tests; never represent these fixtures as live evidence."""
import copy
import unittest
from datetime import datetime, timedelta, timezone

import job_search_evidence as d


class EvidenceTests(unittest.TestCase):
    def fixture(self, round_number=1):
        manifest = d.plan("2026-10-02", round_number)
        cards, ledger = [], []
        for i, cell in enumerate(manifest["cells"]):
            row = {**cell, "page": 1, "status": "exhausted", "has_next_page": False,
                   "filtered_results_url": "https://example.test/filtered",
                   "timestamp": "2026-10-02T21:01:00+00:00", "evidence": "Synthetic fixture: no next page",
                   "card_count": 1 if i < 7 else 0, "no_results_evidence": "Synthetic no results",
                   "page_end_observed": True, "sort_control_observed": True}
            ledger.append(row)
            if i < 7:
                cards.append({"cell_id": cell["cell_id"], "page": 1, "company": f"Company {i}",
                              "title": "Example Role", "url": f"https://example.test/{i}",
                              "captured_at": row["timestamp"]})
        return manifest, {"candidate_cards": cards, "coverage": ledger}

    def analysis(self, check):
        at = (datetime.fromisoformat(check["persisted_at"]) + timedelta(seconds=1)).isoformat()
        roles = []
        for i, score in enumerate([7.0, 6.9, 5.9, 8.0, 8.0]):
            roles.append({"company": f"Company {i}", "title": "Example Role", "jd_accessible": True,
                          "jd_evidence": "Synthetic JD text", "jd_checked_at": at,
                          "assessed_at": at, "fit_score": score, "fit_rationale": "Synthetic resume evidence",
                          "supported_capabilities": ["example_capability"] if i == 4 else [],
                          "capability_evidence": {"example_capability": "Synthetic evidence match"} if i == 4 else {}})
        roles.append({"company": "Company 5", "title": "Example Role", "jd_accessible": True,
                      "jd_evidence": "Synthetic hard requirement", "jd_checked_at": at,
                      "mandatory_gap_excluded": True, "mandatory_gaps": [{"category": "licence",
                      "jd_requirement": "Mandatory licence", "resume_gap": "No evidence"}]})
        return {"tracker_snapshot": {"complete": True, "read_at": at,
                "rows": [{"company": "COMPANY 6", "title": "example role"}]}, "roles": roles}

    def test_normalization_exact_pair(self):
        self.assertEqual(d.normalize(" A & B, Inc. "), d.normalize("a and b inc"))
        self.assertNotEqual(d.normalize("Sr Analyst"), d.normalize("Senior Analyst"))

    def test_every_configured_query_and_primary_windows(self):
        cfg = d.read(d.DEFAULT_CONFIG)
        manifest = d.plan("2026-10-02")
        self.assertEqual(len(manifest["cells"]), 2 * sum(map(len, cfg["core_queries"].values())))
        self.assertTrue(all(c["days"] == 1 for c in manifest["cells"]))
        second = d.plan("2026-10-02", 2)
        self.assertTrue(all(c["days"] == 1 for c in second["cells"] if c["source"] != "Eluta"))
        self.assertTrue(set(c["cell_id"] for c in manifest["cells"]) <= set(c["cell_id"] for c in second["cells"]))

    def test_missing_page_stops_scoring(self):
        manifest, raw = self.fixture()
        raw["coverage"][0].update(status="searched", has_next_page=True)
        check = d.checkpoint(raw, manifest)
        self.assertFalse(check["collection_resolved"])
        self.assertEqual([p['page'] for p in check['missing_or_invalid_page_cells']], [2])
        with self.assertRaisesRegex(ValueError, "Scoring barrier"):
            d.measure(check, self.analysis(check))

    def test_partial_page_or_unverified_linkedin_sort_stops_scoring(self):
        manifest, raw = self.fixture()
        raw["coverage"][0]["page_end_observed"] = False
        check = d.checkpoint(raw, manifest)
        self.assertFalse(check["collection_resolved"])
        self.assertTrue(any("results-list end" in p for p in check["problems"]))
        with self.assertRaisesRegex(ValueError, "Scoring barrier"):
            d.measure(check, self.analysis(check))

        manifest, raw = self.fixture()
        raw["coverage"][0]["sort_control_observed"] = False
        check = d.checkpoint(raw, manifest)
        self.assertFalse(check["collection_resolved"])
        self.assertTrue(any("Most recent sort" in p for p in check["problems"]))

    def test_second_page_with_more_results_is_disclosed_as_capped(self):
        manifest, raw = self.fixture()
        first = raw["coverage"][0]
        first.update(status="searched", has_next_page=True)
        raw["coverage"].append({**first, "page": 2, "status": "searched", "has_next_page": True})
        raw["candidate_cards"].append({"cell_id": first["cell_id"], "page": 2,
                                       "company": "Another Company", "title": "Example Role",
                                       "url": "https://example.test/another", "captured_at": first["timestamp"]})
        check = d.checkpoint(raw, manifest)
        self.assertTrue(check["collection_resolved"])
        self.assertEqual(check["page_cap_reached_cells"], [first["cell_id"]])

    def test_empty_loading_is_not_exhaustion(self):
        manifest, raw = self.fixture()
        del raw["coverage"][-1]["no_results_evidence"]
        check = d.checkpoint(raw, manifest)
        self.assertEqual(check["coverage_status"], "incomplete_coverage")
        self.assertTrue(check["missing_or_invalid_cells"])

    def test_filter_drift_and_card_totals_rejected(self):
        manifest, raw = self.fixture()
        raw["coverage"][0]["days"] = 7
        self.assertFalse(d.checkpoint(raw, manifest)["collection_resolved"])
        manifest, raw = self.fixture()
        raw["coverage"][0]["card_count"] = 500
        self.assertFalse(d.checkpoint(raw, manifest)["collection_resolved"])

    def test_blocked_attempt_preserves_incomplete_coverage(self):
        manifest, raw = self.fixture(2)
        raw["coverage"][-1].update(status="blocked", blocker="Synthetic access challenge", has_next_page=None)
        check = d.checkpoint(raw, manifest)
        self.assertTrue(check["collection_resolved"])
        self.assertEqual(d.measure(check, self.analysis(check))["strong_fit_yield"]["coverage_status"], "incomplete_coverage")

    def test_deterministic_yield_and_tie_ranking(self):
        manifest, raw = self.fixture(2)
        check = d.checkpoint(raw, manifest)
        result = d.measure(check, self.analysis(check))
        m = result["strong_fit_yield"]
        self.assertEqual([m[k] for k in ["captured_unique_cards", "tracker_exclusions", "accessible_jds",
                          "assessed_roles", "score_at_least_7", "score_below_6", "mandatory_gap_exclusions"]],
                         [7, 1, 6, 5, 3, 1, 1])
        self.assertEqual(result["ranked_roles"][0]["company"], "Company 4")
        self.assertEqual(result["ranked_roles"][0]["fit_score"], 8)
        self.assertEqual(m["coverage_status"], "complete")

    def test_tracker_pair_or_unreadable_jd_cannot_be_scored(self):
        manifest, raw = self.fixture()
        check = d.checkpoint(raw, manifest)
        analysis = self.analysis(check)
        analysis["roles"][0]["company"] = "Company 6"
        with self.assertRaises(ValueError):
            d.measure(check, analysis)
        analysis = self.analysis(check)
        analysis["roles"][0]["jd_accessible"] = False
        with self.assertRaises(ValueError):
            d.measure(check, analysis)

    def test_pre_checkpoint_score_rejected_and_prior_checkpoint_reused(self):
        manifest, raw = self.fixture()
        first = d.checkpoint(raw, manifest)
        analysis = self.analysis(first)
        analysis["roles"][0]["assessed_at"] = "2026-10-01T00:00:00+00:00"
        with self.assertRaises(ValueError):
            d.measure(first, analysis)
        manifest, raw = self.fixture(2)
        second = d.checkpoint(raw, manifest)
        second["persisted_at"] = (datetime.fromisoformat(first["persisted_at"]) + timedelta(hours=1)).isoformat()
        analysis = self.analysis(first)
        analysis["prior_checkpoints"] = [first]
        for role in analysis["roles"]:
            role["collection_checkpoint"] = first["persisted_at"]
        self.assertEqual(d.measure(second, analysis)["strong_fit_yield"]["assessed_roles"], 5)

    def test_study_unknowns_and_policy_mismatch(self):
        study = d.study("2026-10-02")
        self.assertEqual(len(study["slots"]), 10)
        self.assertTrue(all(s["strong_fit_yield"] is None for s in study["slots"]))
        self.assertTrue(all(d.date.fromisoformat(s["date"]).weekday() in (1, 2, 3, 4) for s in study["slots"]))
        manifest, raw = self.fixture(2)
        check = d.checkpoint(raw, manifest)
        daily = d.measure(check, self.analysis(check))
        d.record_study(study, daily)
        self.assertEqual(study["complete_comparable_days"], 1)
        self.assertEqual(study["comparisons"], [])
        bad = copy.deepcopy(daily)
        bad["config_fingerprint"] = "different"
        with self.assertRaises(ValueError):
            d.record_study(study, bad)

    def test_shrunken_manifest_cannot_claim_full_coverage(self):
        manifest, raw = self.fixture()
        manifest['cells'] = manifest['cells'][:7]
        raw['coverage'] = raw['coverage'][:7]
        with self.assertRaisesRegex(ValueError, 'full configured matrix'):
            d.checkpoint(raw, manifest)

    def test_comparisons_skip_incomplete_and_preserve_gaps(self):
        study = d.study('2026-10-02')
        manifest, raw = self.fixture(2)
        check = d.checkpoint(raw, manifest)
        daily = d.measure(check, self.analysis(check))
        d.record_study(study, daily)
        later = copy.deepcopy(daily)
        later['run_date'] = study['slots'][1]['date']
        later['strong_fit_yield']['coverage_status'] = 'incomplete_coverage'
        d.record_study(study, later)
        self.assertEqual(study['complete_comparable_days'], 1)
        later['run_date'] = study['slots'][2]['date']
        later['strong_fit_yield']['coverage_status'] = 'complete'
        later['round_yield']['1']['mandatory_gap_categories']['licence'] += 1
        d.record_study(study, later)
        self.assertEqual(study['complete_comparable_days'], 2)
        self.assertEqual(study['comparisons'][0]['mandatory_gap_deltas']['licence'], 1)


if __name__ == "__main__":
    unittest.main()
