import sys

# ANSI color codes
GREEN_COLOR = '\033[0;32m'
YELLOW_COLOR = '\033[1;33m'
RED_COLOR = '\033[0;31m'
RESET_COLOR = '\033[0m'
CYAN_COLOR = '\033[0;36m'
BLUE_COLOR = '\033[0;34m'
MAGENTA_COLOR = '\033[0;35m'


def _status(label: str, color: str, msg: str, *, stream=sys.stdout):
    print(f"[{color}{label}{RESET_COLOR}] {msg}", file=stream)


def info(msg: str):
    print(f"{CYAN_COLOR}{msg}{RESET_COLOR}")


def warning(msg: str):
    _status("WARN", YELLOW_COLOR, msg)


def error(msg: str):
    _status("FAIL", RED_COLOR, msg, stream=sys.stderr)


def success(msg: str):
    _status(" OK ", GREEN_COLOR, msg)


def skip(msg: str):
    _status("SKIP", BLUE_COLOR, msg)


def deleted(msg: str):
    _status("DEL ", MAGENTA_COLOR, msg)
