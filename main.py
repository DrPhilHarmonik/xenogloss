#!/usr/bin/env python3
"""Xenogloss -- Alien Language Decoder"""

import sys
from pathlib import Path

# Ensure local imports work from any cwd
sys.path.insert(0, str(Path(__file__).parent))

from engine.campaign import Campaign
from ui.app import XenoglossApp


def main():
    saves = Campaign.list_saves()

    if saves and "--new" not in sys.argv:
        print("\nXENOGLOSS -- Alien Language Decoder")
        print("=" * 40)
        print("\nExisting campaigns:\n")
        for i, s in enumerate(saves):
            print(f"  [{i + 1}] {s['language_name']} ({s['species_name']})  "
                  f"-- {s['codex_size']} words decoded  --  {s['created_at'][:10]}")
        print(f"\n  [N] Start new campaign")
        print(f"  [Q] Quit\n")

        choice = input("Select: ").strip().lower()

        if choice == "q":
            return
        elif choice == "n" or choice == "":
            campaign = None
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(saves):
                    campaign = Campaign.load(saves[idx]["campaign_id"])
                else:
                    print("Invalid choice.")
                    return
            except ValueError:
                campaign = None
    else:
        campaign = None

    app = XenoglossApp(existing_campaign=campaign)
    app.run()


if __name__ == "__main__":
    main()
