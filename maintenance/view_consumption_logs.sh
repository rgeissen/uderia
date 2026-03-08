#!/bin/bash
#
# View consumption tracking cron job logs
# Quick access to all maintenance job logs
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the absolute path to the uderia directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDERIA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$UDERIA_DIR/logs"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Consumption Tracking Job Logs${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if log directory exists
if [ ! -d "$LOG_DIR" ]; then
    echo -e "${YELLOW}Log directory not found: $LOG_DIR${NC}"
    echo "No logs have been created yet."
    exit 0
fi

# Function to show log summary
show_log_summary() {
    local log_file=$1
    local log_name=$2
    
    if [ -f "$log_file" ]; then
        local line_count=$(wc -l < "$log_file")
        local file_size=$(du -h "$log_file" | cut -f1)
        local last_modified=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$log_file" 2>/dev/null || stat -c "%y" "$log_file" 2>/dev/null | cut -d'.' -f1)
        
        echo -e "${GREEN}✓${NC} $log_name"
        echo -e "   Path: $log_file"
        echo -e "   Size: $file_size | Lines: $line_count | Modified: $last_modified"
    else
        echo -e "${YELLOW}○${NC} $log_name (no logs yet)"
    fi
    echo ""
}

# Show log summaries
echo -e "${BLUE}Log Files:${NC}"
echo ""
show_log_summary "$LOG_DIR/cron_hourly.log" "Hourly Rate Limit Reset"
show_log_summary "$LOG_DIR/cron_daily.log" "Daily Velocity Update"
show_log_summary "$LOG_DIR/cron_monthly.log" "Monthly Period Rollover"
show_log_summary "$LOG_DIR/cron_reconcile.log" "Weekly Reconciliation"

# Menu for viewing logs
echo -e "${BLUE}View Options:${NC}"
echo ""
echo "  1) Tail hourly log (follow)"
echo "  2) Tail daily log (follow)"
echo "  3) Tail monthly log (follow)"
echo "  4) Tail reconcile log (follow)"
echo "  5) Show last 50 lines of all logs"
echo "  6) Search logs for errors"
echo "  7) Clear all logs"
echo "  0) Exit"
echo ""
read -p "Enter choice [0-7]: " choice

case $choice in
    1)
        if [ -f "$LOG_DIR/cron_hourly.log" ]; then
            echo -e "${BLUE}Following hourly log (Ctrl+C to stop)...${NC}"
            tail -f "$LOG_DIR/cron_hourly.log"
        else
            echo -e "${YELLOW}No hourly log file found${NC}"
        fi
        ;;
    2)
        if [ -f "$LOG_DIR/cron_daily.log" ]; then
            echo -e "${BLUE}Following daily log (Ctrl+C to stop)...${NC}"
            tail -f "$LOG_DIR/cron_daily.log"
        else
            echo -e "${YELLOW}No daily log file found${NC}"
        fi
        ;;
    3)
        if [ -f "$LOG_DIR/cron_monthly.log" ]; then
            echo -e "${BLUE}Following monthly log (Ctrl+C to stop)...${NC}"
            tail -f "$LOG_DIR/cron_monthly.log"
        else
            echo -e "${YELLOW}No monthly log file found${NC}"
        fi
        ;;
    4)
        if [ -f "$LOG_DIR/cron_reconcile.log" ]; then
            echo -e "${BLUE}Following reconcile log (Ctrl+C to stop)...${NC}"
            tail -f "$LOG_DIR/cron_reconcile.log"
        else
            echo -e "${YELLOW}No reconcile log file found${NC}"
        fi
        ;;
    5)
        echo -e "${BLUE}Last 50 lines from all logs:${NC}"
        echo ""
        for log_file in "$LOG_DIR"/cron_*.log; do
            if [ -f "$log_file" ]; then
                echo -e "${GREEN}═══════════════════════════════════════${NC}"
                echo -e "${GREEN}$(basename $log_file)${NC}"
                echo -e "${GREEN}═══════════════════════════════════════${NC}"
                tail -50 "$log_file"
                echo ""
            fi
        done
        ;;
    6)
        echo -e "${BLUE}Searching for errors in all logs...${NC}"
        echo ""
        if grep -i "error\|failed\|exception" "$LOG_DIR"/cron_*.log 2>/dev/null; then
            echo ""
            echo -e "${RED}Errors found in logs${NC}"
        else
            echo -e "${GREEN}No errors found${NC}"
        fi
        ;;
    7)
        read -p "Clear all consumption tracking logs? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -f "$LOG_DIR"/cron_*.log
            echo -e "${GREEN}✓ All logs cleared${NC}"
        else
            echo -e "${YELLOW}Cancelled${NC}"
        fi
        ;;
    0)
        echo "Exiting..."
        exit 0
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac
