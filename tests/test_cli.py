"""
Tests for the CLI layer: exit codes, argument handling, and interactive mode.

The exit codes are a public contract - callers in other languages branch on
them - so each one is pinned to the exception that produces it.
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from parth_dl import cli
from parth_dl.utils import (
    EXIT_DOWNLOAD_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_OK,
    EXIT_RATE_LIMITED,
    EXIT_USAGE,
    EXIT_VALIDATION_ERROR,
    DownloadError,
    NetworkError,
    RateLimitError,
    ValidationError,
)


def run_main(argv, stdin_tty=False, stdout_tty=False):
    """Drive cli.main() with a fake argv and controllable TTY-ness"""
    stdout, stderr = io.StringIO(), io.StringIO()
    stdout.isatty = lambda: stdout_tty
    stderr.isatty = lambda: False

    stdin = io.StringIO()
    stdin.isatty = lambda: stdin_tty

    with mock.patch.object(sys, 'argv', ['parth-dl'] + argv), \
         mock.patch.object(sys, 'stdout', stdout), \
         mock.patch.object(sys, 'stderr', stderr), \
         mock.patch.object(sys, 'stdin', stdin), \
         mock.patch.object(cli, 'harden_stdio'):
        code = cli.main()

    return code, stdout.getvalue(), stderr.getvalue()


class ExitCodeTest(unittest.TestCase):
    """Each exception kind maps to its own exit code"""

    CASES = [
        (ValidationError('bad'), EXIT_VALIDATION_ERROR),
        (RateLimitError('slow down'), EXIT_RATE_LIMITED),
        (NetworkError('offline'), EXIT_NETWORK_ERROR),
        (DownloadError('private'), EXIT_DOWNLOAD_ERROR),
    ]

    def test_each_exception_has_its_own_code(self):
        for exc, expected in self.CASES:
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(cli.InstagramDownloader, 'download', side_effect=exc):
                    code, _, err = run_main(['https://www.instagram.com/reel/Cxyz123AbCd/'])

                self.assertEqual(code, expected)
                self.assertIn(str(exc), err)

    def test_success(self):
        with mock.patch.object(cli.InstagramDownloader, 'download', return_value='out.mp4'):
            code, _, _ = run_main(['https://www.instagram.com/reel/Cxyz123AbCd/'])

        self.assertEqual(code, EXIT_OK)

    def test_first_failure_wins_but_every_url_is_attempted(self):
        urls = ['https://www.instagram.com/p/Cxyz123AbCd/',
                'https://www.instagram.com/p/Dxyz123AbCd/']

        with mock.patch.object(cli.InstagramDownloader, 'download',
                               side_effect=[NetworkError('down'), 'ok.mp4']) as dl:
            code, _, _ = run_main(urls)

        self.assertEqual(code, EXIT_NETWORK_ERROR)
        self.assertEqual(dl.call_count, 2)   # the second URL is still tried


class UsageTest(unittest.TestCase):

    def test_no_urls_is_a_usage_error(self):
        code, _, err = run_main([])

        self.assertEqual(code, EXIT_USAGE)
        self.assertIn('at least one URL', err)

    def test_output_flag_rejected_for_multiple_urls(self):
        # One -o filename cannot name two different downloads
        code, _, err = run_main([
            'https://www.instagram.com/p/Cxyz123AbCd/',
            'https://www.instagram.com/p/Dxyz123AbCd/',
            '-o', 'one.mp4',
        ])

        self.assertEqual(code, EXIT_USAGE)
        self.assertIn('-o/--output cannot be used with multiple URLs', err)

    def test_interactive_rejected_with_json(self):
        # --json is a one-shot machine contract; there is nobody to prompt
        code, _, err = run_main(['-i', '--json', 'https://www.instagram.com/p/Cxyz123AbCd/'])

        self.assertEqual(code, EXIT_USAGE)
        self.assertIn('cannot be combined', err)

    def test_json_rejects_multiple_urls(self):
        code, _, err = run_main([
            '--json',
            'https://www.instagram.com/p/Cxyz123AbCd/',
            'https://www.instagram.com/p/Dxyz123AbCd/',
        ])

        self.assertEqual(code, EXIT_USAGE)
        self.assertIn('exactly one URL', err)

    def test_interactive_rejects_single_output_filename(self):
        code, _, err = run_main([
            '-i', '-o', 'clip.mp4',
            'https://www.instagram.com/p/Cxyz123AbCd/',
        ], stdin_tty=True, stdout_tty=True)

        self.assertEqual(code, EXIT_USAGE)
        self.assertIn('cannot be used', err)

    def test_output_and_paths_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit) as raised:
            run_main([
                '-o', 'clip.mp4', '-P', 'downloads',
                'https://www.instagram.com/p/Cxyz123AbCd/',
            ])

        self.assertEqual(raised.exception.code, EXIT_USAGE)

    def test_quiet_and_verbose_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit) as raised:
            run_main([
                '--quiet', '--verbose',
                'https://www.instagram.com/p/Cxyz123AbCd/',
            ])

        self.assertEqual(raised.exception.code, EXIT_USAGE)

    def test_cli_passes_explicit_output_modes(self):
        with mock.patch.object(cli.InstagramDownloader, 'download', return_value='x') as dl:
            run_main(['-o', 'clip', 'https://www.instagram.com/p/Cxyz123AbCd/'])
            self.assertEqual(dl.call_args.kwargs['output_mode'], 'file')

        with mock.patch.object(cli.InstagramDownloader, 'download', return_value='x') as dl:
            run_main(['-P', 'downloads.v1', 'https://www.instagram.com/p/Cxyz123AbCd/'])
            self.assertEqual(dl.call_args.kwargs['output_mode'], 'directory')


class BatchFileTest(unittest.TestCase):

    def write(self, text):
        path = Path(tempfile.mkdtemp()) / 'urls.txt'
        path.write_text(text, encoding='utf-8')
        return str(path)

    def test_comments_and_blanks_are_ignored(self):
        path = self.write(
            '# my list\n'
            'https://www.instagram.com/p/Cxyz123AbCd/\n'
            '\n'
            '   # indented comment\n'
            '  https://www.instagram.com/p/Dxyz123AbCd/  \n'
        )

        urls = cli.read_batch_file(path)

        self.assertEqual(urls, ['https://www.instagram.com/p/Cxyz123AbCd/',
                                'https://www.instagram.com/p/Dxyz123AbCd/'])

    def test_missing_file_raises(self):
        with self.assertRaises(ValidationError):
            cli.read_batch_file('no-such-file.txt')

    def test_invalid_utf8_is_reported_as_usage_error(self):
        path = Path(tempfile.mkdtemp()) / 'urls.txt'
        path.write_bytes(b'\xff\xfe\xfa')

        code, _, err = run_main(['-a', str(path)])

        self.assertEqual(code, EXIT_USAGE)
        self.assertIn('Could not read batch file', err)

    def test_batch_file_urls_are_downloaded(self):
        path = self.write('https://www.instagram.com/p/Cxyz123AbCd/\n')

        with mock.patch.object(cli.InstagramDownloader, 'download',
                               return_value='x.mp4') as dl:
            code, _, _ = run_main(['-a', path])

        self.assertEqual(code, EXIT_OK)
        dl.assert_called_once()


class BannerTest(unittest.TestCase):
    """The banner must never pollute machine-readable output"""

    def test_suppressed_for_json(self):
        with mock.patch.object(cli.InstagramDownloader, 'get_info', return_value={'id': 'x'}):
            _, out, _ = run_main(['--json', 'https://www.instagram.com/p/Cxyz123AbCd/'],
                                 stdout_tty=True)

        self.assertNotIn('parth-dl v', out)
        self.assertTrue(out.strip().startswith('{'))   # clean JSON, parseable as-is

    def test_verbose_json_keeps_diagnostics_on_stderr(self):
        with mock.patch(
            'parth_dl.core.MediaExtractor.extract', return_value={'id': 'x'},
        ):
            code, out, err = run_main([
                '--json', '--verbose',
                'https://www.instagram.com/p/Cxyz123AbCd/',
            ])

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out), {'id': 'x'})
        self.assertIn('Detected media URL', err)

    def test_suppressed_when_piped(self):
        with mock.patch.object(cli.InstagramDownloader, 'download', return_value='x.mp4'):
            _, out, _ = run_main(['https://www.instagram.com/reel/Cxyz123AbCd/'],
                                 stdout_tty=False)

        self.assertNotIn('Instagram Media Downloader', out)

    def test_printed_on_a_tty(self):
        with mock.patch.object(cli.InstagramDownloader, 'download', return_value='x.mp4'):
            _, out, _ = run_main(['https://www.instagram.com/reel/Cxyz123AbCd/'],
                                 stdout_tty=True)

        self.assertIn('Instagram Media Downloader', out)
        self.assertIn('Developed by Parthmax', out)
        self.assertIn('parth-dl', out)
        self.assertNotIn('╔', out)
        self.assertNotIn('(Public Content Only)', out)


class InteractiveTest(unittest.TestCase):

    def test_prompts_for_the_next_url_until_empty(self):
        with mock.patch.object(cli.InstagramDownloader, 'download',
                               return_value='x.mp4') as dl, \
             mock.patch.object(cli, 'prompt_for_url',
                               side_effect=['https://www.instagram.com/p/Dxyz123AbCd/', None]):

            code, _, _ = run_main(['-i', 'https://www.instagram.com/reel/Cxyz123AbCd/'],
                                  stdin_tty=True, stdout_tty=True)

        # The seed URL, then the one typed at the prompt
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(dl.call_count, 2)

    def test_starts_with_no_urls_at_all(self):
        # `parth-dl -i` on its own should drop straight into the prompt
        with mock.patch.object(cli.InstagramDownloader, 'download',
                               return_value='x.mp4') as dl, \
             mock.patch.object(cli, 'prompt_for_url',
                               side_effect=['https://www.instagram.com/p/Cxyz123AbCd/', None]):

            code, _, _ = run_main(['-i'], stdin_tty=True, stdout_tty=True)

        self.assertEqual(code, EXIT_OK)
        self.assertEqual(dl.call_count, 1)

    def test_a_failed_url_does_not_end_the_session(self):
        with mock.patch.object(cli.InstagramDownloader, 'download',
                               side_effect=[DownloadError('private'), 'ok.mp4']) as dl, \
             mock.patch.object(cli, 'prompt_for_url',
                               side_effect=['https://www.instagram.com/p/Cxyz123AbCd/',
                                            'https://www.instagram.com/p/Dxyz123AbCd/',
                                            None]):

            code, _, _ = run_main(['-i'], stdin_tty=True, stdout_tty=True)

        self.assertEqual(dl.call_count, 2)          # kept going after the failure
        self.assertEqual(code, EXIT_DOWNLOAD_ERROR)  # but still reports it

    def test_not_offered_when_piped(self):
        # A script piping into parth-dl must never be blocked on input()
        with mock.patch.object(cli.InstagramDownloader, 'download', return_value='x.mp4'), \
             mock.patch.object(cli, 'prompt_for_url') as prompt:

            run_main(['-i', 'https://www.instagram.com/reel/Cxyz123AbCd/'],
                     stdin_tty=False, stdout_tty=False)

        prompt.assert_not_called()

    def test_eof_at_the_prompt_ends_cleanly(self):
        with mock.patch('builtins.input', side_effect=EOFError):
            self.assertIsNone(cli.prompt_for_url())


class ServeDispatchTest(unittest.TestCase):

    def test_serve_subcommand_is_routed_before_url_parsing(self):
        with mock.patch('parth_dl.server.serve', return_value=0) as serve:
            code, _, _ = run_main(['serve', '--port', '9999', '--no-open'])

        self.assertEqual(code, 0)
        self.assertEqual(serve.call_args.kwargs['port'], 9999)
        self.assertFalse(serve.call_args.kwargs['open_browser'])

    def test_server_startup_failure_is_reported_without_traceback(self):
        with mock.patch.object(cli, 'run_serve', side_effect=OSError('port in use')):
            code, _, err = run_main(['serve', '--no-open'])

        self.assertEqual(code, EXIT_DOWNLOAD_ERROR)
        self.assertIn('could not start server: port in use', err)


if __name__ == '__main__':
    unittest.main()
