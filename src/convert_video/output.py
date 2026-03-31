import sys

# ANSI color codes
GREEN_COLOR = '\033[0;32m'
YELLOW_COLOR = '\033[1;33m'
RED_COLOR = '\033[0;31m'
RESET_COLOR = '\033[0m'
CYAN_COLOR = '\033[0;36m'


def info(msg: str):
    print(f"{GREEN_COLOR}{msg}{RESET_COLOR}")


def warning(msg: str):
    print(f"{YELLOW_COLOR}{msg}{RESET_COLOR}")


def error(msg: str):
    print(f"{RED_COLOR}{msg}{RESET_COLOR}", file=sys.stderr)
