"""
Command-line interface for parth-dl
"""

import sys
import argparse
from . import __version__, __description__
from .core import InstagramDownloader
from .utils import DownloadError, RateLimitError, NetworkError, ValidationError


def print_banner():
    """Print application banner"""
    banner = f"""
╔═══════════════════════════════════════════════════════════════╗
║                         parth-dl v{__version__}                        ║
║              Instagram Media Downloader                       ║
║                  (Public Content Only)                        ║
╚═══════════════════════════════════════════════════════════════╝
"""
    print(banner)


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
  
  Download a post:
    parth-dl https://www.instagram.com/p/ABC123/
  
  Download profile picture:
    parth-dl https://www.instagram.com/username/
  
  Download with custom output:
    parth-dl https://www.instagram.com/reel/ABC123/ -o my_video.mp4
  
  List available formats:
    parth-dl https://www.instagram.com/reel/ABC123/ --list-formats
  
  Enable verbose logging:
    parth-dl https://www.instagram.com/reel/ABC123/ -v

Supported Content:
  ✓ Reels (with audio)
  ✓ Video posts (with audio)
  ✓ Image posts (single & carousel)
  ✓ Profile pictures
  ✗ Stories (requires authentication)
  ✗ Highlights (requires authentication)
  ✗ Private accounts (not supported)

Note: This tool only works with PUBLIC Instagram content.
        """
    )
    
    # Positional arguments
    parser.add_argument(
        'url',
        help='Instagram URL (post, reel, or profile)'
    )
    
    # Optional arguments
    parser.add_argument(
        '-o', '--output',
        metavar='PATH',
        help='Output file or directory path'
    )
    
    parser.add_argument(
        '-q', '--quality',
        choices=['best', 'worst'],
        default='best',
        help='Video quality preference (default: best)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose/debug output'
    )
    
    parser.add_argument(
        '--list-formats',
        action='store_true',
        help='List all available formats without downloading'
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


def main():
    """Main CLI entry point"""
    parser = create_parser()
    args = parser.parse_args()
    
    # Print banner for non-quiet operations
    if not args.list_formats:
        print_banner()
    
    try:
        # Create downloader instance
        downloader = InstagramDownloader(
            verbose=args.verbose,
            rate_limit=not args.no_rate_limit
        )
        
        # Execute command
        if args.list_formats:
            downloader.list_formats(args.url)
        else:
            downloader.download(
                url=args.url,
                output_path=args.output,
                quality=args.quality
            )
        
        return 0
    
    except KeyboardInterrupt:
        print("\n\n[parth-dl] ⚠ Download cancelled by user", file=sys.stderr)
        return 130
    
    except ValidationError as e:
        print(f"\n[parth-dl] ✗ Invalid input: {e}", file=sys.stderr)
        return 1
    
    except RateLimitError as e:
        print(f"\n[parth-dl] ✗ Rate limit error: {e}", file=sys.stderr)
        print("Tip: Wait a few minutes before trying again.", file=sys.stderr)
        return 1
    
    except NetworkError as e:
        print(f"\n[parth-dl] ✗ Network error: {e}", file=sys.stderr)
        print("Tip: Check your internet connection and try again.", file=sys.stderr)
        return 1
    
    except DownloadError as e:
        print(f"\n[parth-dl] ✗ Download failed: {e}", file=sys.stderr)
        return 1
    
    except Exception as e:
        print(f"\n[parth-dl] ✗ Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())