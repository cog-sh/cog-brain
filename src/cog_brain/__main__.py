"""Start a transport only when explicitly serving; CLI/API remain MCP-free."""
import sys


def main():
    if not sys.argv[1:] or sys.argv[1] in ("--http", "--simple-http"):
        from cog_brain.server import main as run
    else:
        from cog_brain.cli import main as run
    run()


if __name__ == "__main__":
    main()
