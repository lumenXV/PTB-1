"""Stability checks for PTB-1 research runs and dataset loading."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from ptb1.historian import load_price_history


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


class HistorianValidationTests(unittest.TestCase):
    """Verify that Historian rejects malformed historical datasets clearly."""

    def test_empty_csv_rejected(self) -> None:
        """An empty CSV file should not be accepted as price history."""
        with self.assertRaisesRegex(ValueError, "No CSV header"):
            load_price_history(FIXTURES / "empty.csv")

    def test_header_only_csv_rejected(self) -> None:
        """A CSV with headers but no rows should not run as a dataset."""
        with self.assertRaisesRegex(ValueError, "No historical rows"):
            load_price_history(FIXTURES / "header_only.csv")

    def test_missing_required_column_rejected(self) -> None:
        """A CSV missing required columns should name the missing column."""
        with self.assertRaisesRegex(ValueError, "close"):
            load_price_history(FIXTURES / "missing_close.csv")

    def test_bad_numeric_value_rejected(self) -> None:
        """A non-numeric price or volume should be rejected."""
        with self.assertRaisesRegex(ValueError, "Invalid numeric value"):
            load_price_history(FIXTURES / "bad_number.csv")

    def test_bad_date_rejected(self) -> None:
        """An invalid date should be rejected."""
        with self.assertRaisesRegex(ValueError, "Invalid date"):
            load_price_history(FIXTURES / "bad_date.csv")


class CliStabilityTests(unittest.TestCase):
    """Verify that repeated CLI research runs remain stable."""

    def test_repeated_single_dataset_runs_are_identical(self) -> None:
        """The same dataset should produce the same report on repeated runs."""
        first_run = self._run_ptb1("--data", "datasets/sample_prices.csv")
        second_run = self._run_ptb1("--data", "datasets/sample_prices.csv")

        self.assertEqual(first_run.returncode, 0)
        self.assertEqual(second_run.returncode, 0)
        self.assertEqual(first_run.stdout, second_run.stdout)
        self.assertIn("Overall Winner: RSI", first_run.stdout)

    def test_all_datasets_run_successfully(self) -> None:
        """All demo datasets should run together without crashing."""
        result = self._run_ptb1("--all-datasets")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Datasets loaded: 3", result.stdout)
        self.assertIn("Overall Cross-Dataset Winner:", result.stdout)

    def test_cli_displays_bad_dataset_errors_without_traceback(self) -> None:
        """The CLI should display validation errors instead of Python tracebacks."""
        result = self._run_ptb1("--data", "tests/fixtures/missing_close.csv")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Error: Missing required column", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def _run_ptb1(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run PTB-1 as a user would from the command line."""
        return subprocess.run(
            [sys.executable, "-m", "ptb1", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
