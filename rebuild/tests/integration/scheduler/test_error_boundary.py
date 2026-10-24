"""No-network regression for observed SDK exception leakage at CLI boundaries."""
import contextlib
import io
import unittest
from unittest.mock import patch

from tests.integration.scheduler import check, reconcile


class ErrorBoundaryTest(unittest.TestCase):
    def test_raw_sdk_error_never_reaches_terminal(self):
        for module in (check, reconcile):
            with self.subTest(module=module.__name__):
                output, errors = io.StringIO(), io.StringIO()
                with patch.object(module, "main", side_effect=RuntimeError("synthetic-secret-DSN-body")):
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                        code = module.cli()
                self.assertEqual(code, 1)
                self.assertIn("failed", output.getvalue())
                self.assertNotIn("synthetic-secret", output.getvalue())
                self.assertNotIn("Traceback", output.getvalue())
                self.assertEqual(errors.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
