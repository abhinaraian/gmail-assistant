"""
Gmail Assistant — entry point.

Run with default settings:
    python main.py

Run with a custom instruction:
    python main.py --instruction "Create 5 labels focused on work and finance."
"""

import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gmail Assistant — AI-powered inbox organizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py
  python main.py -i "Organize my inbox with work, finance, and newsletter labels"
  python main.py -i "Clean up newsletters only and archive them"
  python main.py -i "Keep it simple — 5 broad labels covering 80% of my inbox"
  python main.py -i "Only look at the last 90 days in:inbox after:2024/01/01"
        """,
    )
    parser.add_argument(
        "--instruction",
        "-i",
        type=str,
        default=(
            "Analyze my inbox and organize it with smart, meaningful labels. "
            "Be comprehensive and aim to label at least 75% of my emails."
        ),
        help="Natural-language instruction for the assistant",
    )
    args = parser.parse_args()

    # ── Preflight checks ────────────────────────────────────────────────
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.")
        print("  1. Copy .env.example to .env")
        print("  2. Add your key:  ANTHROPIC_API_KEY=sk-ant-...")
        print("  See SETUP.md Step 3 for details.")
        sys.exit(1)

    if not os.path.exists("credentials/credentials.json"):
        print("Error: credentials/credentials.json not found.")
        print("  Follow SETUP.md Step 2 to create Gmail API credentials.")
        sys.exit(1)

    # ── Run ─────────────────────────────────────────────────────────────
    try:
        from src.agent import GmailAgent
        agent = GmailAgent()
        agent.run(args.instruction)
    except KeyboardInterrupt:
        print("\n\nInterrupted — goodbye.")
        sys.exit(0)
    except FileNotFoundError as exc:
        print(f"\nSetup error: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        raise


if __name__ == "__main__":
    main()
