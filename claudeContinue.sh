#!/bin/bash
#
# Claude Continue - iTerm2 Automation for Claude Code
# by Anomaly Alpha
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

export CLAUDE_CONTINUE_LOG_CONSOLE="${CLAUDE_CONTINUE_LOG_CONSOLE:-false}"
export CLAUDE_CONTINUE_SHOW_BANNER="${CLAUDE_CONTINUE_SHOW_BANNER:-false}"

if [[ "${CLAUDE_CONTINUE_SHOW_BANNER}" == "true" ]]; then
    echo -e "${BLUE}╔═══════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${YELLOW}     CLAUDE CONTINUE by Anomaly Alpha      ${BLUE}║${NC}"
    echo -e "${BLUE}║${YELLOW}     iTerm2 Automation for Claude Code     ${BLUE}║${NC}"
    echo -e "${BLUE}║${YELLOW}             addicted.bot                  ${BLUE}║${NC}"
    echo -e "${BLUE}╚═══════════════════════════════════════════╝${NC}"
fi

# Check if venv exists
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo -e "${YELLOW}Virtual environment not found at $VENV_DIR${NC}"
    echo "Please run: pip install -r requirements.txt"
    exit 1
fi

# Check for arguments
ARGS=""
if [ "$1" == "--test" ]; then
    if [[ "${CLAUDE_CONTINUE_SHOW_BANNER}" == "true" ]]; then
        echo -e "${GREEN}Running in test mode (no iTerm2 connection)${NC}"
    fi
    ARGS="--test"
elif [ "$1" == "--debug" ]; then
    if [[ "${CLAUDE_CONTINUE_SHOW_BANNER}" == "true" ]]; then
        echo -e "${GREEN}Running in debug mode${NC}"
    fi
    ARGS="--debug"
elif [ "$1" == "--setup" ]; then
    if [[ "${CLAUDE_CONTINUE_SHOW_BANNER}" == "true" ]]; then
        echo -e "${GREEN}Running setup wizard${NC}"
    fi
    ARGS="--setup"
elif [ "$1" == "--no-web" ]; then
    if [[ "${CLAUDE_CONTINUE_SHOW_BANNER}" == "true" ]]; then
        echo -e "${GREEN}Running without web GUI${NC}"
    fi
    ARGS="--no-web"
elif [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --test     Run in test mode (pattern detection only, no iTerm2)"
    echo "  --debug    Run with debug logging"
    echo "  --setup    Run the setup wizard"
    echo "  --no-web   Disable the web GUI (port 7777)"
    echo "  --help     Show this help message"
    echo ""
    echo "Web GUI: http://localhost:7777"
    exit 0
fi

# Start the daemon
cd "$SCRIPT_DIR"
if [[ "${CLAUDE_CONTINUE_SHOW_BANNER}" == "true" ]]; then
    echo -e "${GREEN}Starting Claude Continue daemon...${NC}"
    echo ""
fi

exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/src/daemon.py" $ARGS
