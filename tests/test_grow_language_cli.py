import io
import unittest
from contextlib import redirect_stdout

from grow_language import _make_progress_reporter


class GrowLanguageCliTests(unittest.TestCase):
    def test_default_progress_reporter_hides_raw_llm_tokens(self):
        buffer = io.StringIO()
        reporter = _make_progress_reporter(verbose_llm=False)

        with redirect_stdout(buffer):
            reporter('{"language_name":"bad"}')
            reporter("\n[seed candidate 1/5]\n")
            reporter("plain token")

        self.assertEqual(buffer.getvalue(), "[seed candidate 1/5]\n")


if __name__ == "__main__":
    unittest.main()
