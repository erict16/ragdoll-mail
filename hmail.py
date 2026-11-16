"""Old name of ragdoll.py (before 0.4.0). Kept so older copies can still update themselves
and older scripts that `import hmail` keep working. Use ragdoll.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ragdoll  # noqa: E402

if __name__ == "__main__":
    ragdoll.main()
else:
    sys.modules[__name__] = ragdoll
