"""
Command-line interface for parth-dl
"""

import argparse
import json
import sys

from . import __description__, __version__
from .core import InstagramDownloader
from .utils import (
    EXIT_DOWNLOAD_ERROR,
    EXIT_INTERRUPTED,
    EXIT_NETWORK_ERROR,
    EXIT_OK,
    EXIT_RATE_LIMITED,
    EXIT_USAGE,
    EXIT_VALIDATION_ERROR,
    DownloadError,
    NetworkError,
    RateLimitError,
    ValidationError,
    harden_stdio,
    style,
    symbols,
)


def print_banner():
    """Print a compact terminal-native identity block."""
    print()
    brand = style('parth-dl', 'bold', 'purple')
    version = style(f'v{__version__}', 'dim')
    subtitle = style('Instagram Media Downloader · public content', 'dim')
    credit = style('Developed by Parthmax', 'dim')
    print(f"{brand}  {version}")
    print(subtitle)
    print(credit)
    print()


def create_parser():
    """Create command-line argument parser"""
    parser = argparse.ArgumentParser(
        prog='parth-dl',
        description=__description__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Download a reel:
    parth-dl https://www.instagram.com/reel/ABC123/

  Keep going - prompts for the next URL after each download:
    parth-dl -i

  Open the web UI in your browser:
    parth-dl serve

  Download several posts at once:
    parth-dl https://www.instagram.com/p/ABC123/ https://www.instagram.com/p/DEF456/

  Download every URL listed in a file (one per line):
    parth-dl -a urls.txt

  Download profile picture:
    parth-dl https://www.instagram.com/username/

  Write into a directory (created if missing):
    parth-dl https://www.instagram.com/reel/ABC123/ -P ~/Downloads/insta

  Write to a specific filename:
    parth-dl https://www.instagram.com/reel/ABC123/ -o my_video.mp4

  Print metadata as JSON without downloading:
    parth-dl https://www.instagram.com/reel/ABC123/ --json

Exit codes:
  0 success   1 download failed   2 bad usage
  3 network   4 rate limited      5 invalid input   130 interrupted

Supported Content:
  Reels (with audio), video posts, image posts (single & carousel),
  profile pictures. Stories, highlights and private accounts are NOT
  supported - they require authentication.

Note: This tool only works with PUBLIC Instagram content.
        """
    )

    parser.add_argument(
        'urls',
        nargs='*',
        metavar='URL',
        help='One or more Instagram URLs (post, reel, or profile)'
    )

    parser.add_argument(
        '-a', '--batch-file',
        metavar='FILE',
        help='File containing URLs to download, one per line (# comments allowed)'
    )

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        '-o', '--output',
        metavar='PATH',
        help='Output filename (single item) - use -P for a destination directory'
    )

    output_group.add_argument(
        '-P', '--paths',
        metavar='DIR',
        help='Directory to download into (created if it does not exist)'
    )

    parser.add_argument(
        '-q', '--quality',
        choices=['best', 'worst'],
        default='best',
        help='Quality preference (default: best)'
    )

    parser.add_argument(
        '-f', '--force',
        action='store_true',
        help='Overwrite existing files (default: skip them)'
    )

    parser.add_argument(
        '-i', '--interactive',
        action='store_true',
        help='Keep prompting for the next URL after each download'
    )

    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose/debug output'
    )

    verbosity_group.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress all output except errors'
    )

    parser.add_argument(
        '--no-banner',
        action='store_true',
        help='Do not print the banner'
    )

    parser.add_argument(
        '--list-formats',
        action='store_true',
        help='List all available formats without downloading'
    )

    parser.add_argument(
        '--json',
        dest='dump_json',
        action='store_true',
        help='Print media metadata as JSON without downloading'
    )

    parser.add_argument(
        '--no-rate-limit',
        action='store_true',
        help='Disable rate limiting (not recommended)'
    )

    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}'
    )

    return parser


def read_batch_file(path):
    """Read URLs from a batch file, one per line"""
    try:
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeError) as e:
        raise ValidationError(f"Could not read batch file: {e}")

    return [line.strip() for line in lines
            if line.strip() and not line.strip().startswith('#')]


def collect_urls(args):
    """Assemble the URL list from positional args and any batch file"""
    urls = list(args.urls)

    if args.batch_file:
        urls.extend(read_batch_file(args.batch_file))

    return urls


def run_one(downloader, url, args):
    """Run the requested action for a single URL; returns an exit code"""
    sym = symbols(sys.stderr)

    try:
        if args.dump_json:
            print(json.dumps(downloader.get_info(url), indent=2, ensure_ascii=False))
        elif args.list_formats:
            downloader.list_formats(url)
        else:
            downloader.download(
                url=url,
                output_path=args.output if args.output is not None else args.paths,
                quality=args.quality,
                output_mode='file' if args.output is not None else (
                    'directory' if args.paths is not None else 'auto'
                ),
            )
        return EXIT_OK

    except ValidationError as e:
        print(f"\n[parth-dl] {sym['fail']} Invalid input: {e}", file=sys.stderr)
        return EXIT_VALIDATION_ERROR

    except RateLimitError as e:
        print(f"\n[parth-dl] {sym['fail']} Rate limit error: {e}", file=sys.stderr)
        print("Tip: Wait a few minutes before trying again.", file=sys.stderr)
        return EXIT_RATE_LIMITED

    except NetworkError as e:
        print(f"\n[parth-dl] {sym['fail']} Network error: {e}", file=sys.stderr)
        print("Tip: Check your internet connection and try again.", file=sys.stderr)
        return EXIT_NETWORK_ERROR

    except DownloadError as e:
        print(f"\n[parth-dl] {sym['fail']} Download failed: {e}", file=sys.stderr)
        return EXIT_DOWNLOAD_ERROR


def interactive_available(args):
    """
    Whether the "next URL?" prompt can run.

    It needs a human on both ends: piping into or out of parth-dl means the
    caller is a script, and blocking it on a prompt would hang it.
    """
    if not args.interactive:
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_for_url():
    """Ask for the next URL. Returns None when the user is done."""
    try:
        return input("\n[parth-dl] Next URL (press Enter to quit) > ").strip() or None
    except (EOFError, KeyboardInterrupt):
        # Ctrl-D / Ctrl-C at the prompt is a normal way to leave
        print()
        return None


def run_serve(argv):
    """Handle `parth-dl serve` - kept out of the main parser, which takes bare URLs"""
    from .server import create_serve_parser, serve

    args = create_serve_parser().parse_args(argv)
    return serve(
        host=args.host,
        port=args.port,
        download_dir=args.dir,
        open_browser=not args.no_open,
        verbose=args.verbose,
    )


def main():
    """Main CLI entry point"""
    harden_stdio()

    # `serve` is a subcommand, but the main parser takes bare positional URLs,
    # so it has to be peeled off before argparse sees it.
    if len(sys.argv) > 1 and sys.argv[1] == 'serve':
        try:
            return run_serve(sys.argv[2:])
        except ValidationError as e:
            print(f"[parth-dl] error: {e}", file=sys.stderr)
            return EXIT_USAGE
        except Exception as e:
            print(f"[parth-dl] error: could not start server: {e}", file=sys.stderr)
            return EXIT_DOWNLOAD_ERROR

    parser = create_parser()
    args = parser.parse_args()
    sym = symbols(sys.stderr)

    try:
        urls = collect_urls(args)
    except ValidationError as e:
        print(f"[parth-dl] {sym['fail']} {e}", file=sys.stderr)
        return EXIT_USAGE

    # Machine-readable output is a one-shot contract; there is nobody to prompt
    if args.interactive and (args.dump_json or args.list_formats):
        print(f"[parth-dl] {sym['fail']} -i/--interactive cannot be combined with "
              f"--json or --list-formats", file=sys.stderr)
        return EXIT_USAGE

    if args.dump_json and len(urls) != 1:
        print(f"[parth-dl] {sym['fail']} --json requires exactly one URL",
              file=sys.stderr)
        return EXIT_USAGE

    if args.interactive and args.output:
        print(f"[parth-dl] {sym['fail']} -o/--output cannot be used with "
              f"-i/--interactive; use -P/--paths instead", file=sys.stderr)
        return EXIT_USAGE

    # `parth-dl -i` with no URLs is legitimate: it drops straight into the prompt
    if not urls and not interactive_available(args):
        parser.print_usage(sys.stderr)
        print("[parth-dl] error: provide at least one URL, or -a/--batch-file",
              file=sys.stderr)
        return EXIT_USAGE

    # -o names a single output file, so it cannot be shared across several URLs
    if args.output and len(urls) > 1:
        print(f"[parth-dl] {sym['fail']} -o/--output cannot be used with multiple URLs; "
              f"use -P/--paths instead", file=sys.stderr)
        return EXIT_USAGE

    # Machine-readable output must not be polluted by the banner
    structured = args.dump_json or args.list_formats
    if not (args.no_banner or args.quiet or structured or not sys.stdout.isatty()):
        print_banner()

    try:
        downloader = InstagramDownloader(
            verbose=args.verbose,
            rate_limit=not args.no_rate_limit,
            quiet=args.quiet,
            overwrite=args.force,
        )

        exit_code = EXIT_OK
        for url in urls:
            result = run_one(downloader, url, args)
            # Report the first failure, but keep going through the rest
            if result != EXIT_OK and exit_code == EXIT_OK:
                exit_code = result

        # Keep taking URLs until the user is done, so grabbing the next video
        # doesn't mean re-running the whole command
        while interactive_available(args):
            url = prompt_for_url()
            if not url:
                print(f"[parth-dl] {sym['ok']} Done.", file=sys.stderr)
                break

            result = run_one(downloader, url, args)
            if result != EXIT_OK and exit_code == EXIT_OK:
                exit_code = result

        return exit_code

    except KeyboardInterrupt:
        print(f"\n\n[parth-dl] {sym['warn']} Cancelled by user "
              f"(partial downloads are kept as .part files and will resume)",
              file=sys.stderr)
        return EXIT_INTERRUPTED

    except Exception as e:
        print(f"\n[parth-dl] {sym['fail']} Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return EXIT_DOWNLOAD_ERROR


if __name__ == '__main__':
    sys.exit(main())
