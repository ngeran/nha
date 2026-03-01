#!/bin/bash

# RIB Monitor Startup Script
# Simplifies the process of launching the backend and TUI

set -e

# Colors for output
BLUE='\033[0;34m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}=======================================${NC}"
echo -e "${BLUE}   Unified RIB Monitor - Launcher      ${NC}"
echo -e "${BLUE}=======================================${NC}"

# Check for Docker
if ! [ -x "$(command -v docker)" ]; then
  echo -e "${RED}Error: docker is not installed.${NC}" >&2
  exit 1
fi

# 1. Build and Start Backend Services
echo -e "${CYAN}1. Launching containers (Redis, Backend, Worker)...${NC}"
docker compose up -d --build redis backend worker

# 2. Check Backend Health
echo -e "${CYAN}2. Waiting for backend to be ready...${NC}"
until curl -s http://localhost:8000/api/rib > /dev/null; do
  sleep 2
  echo -n "."
done
echo -e "\n${GREEN}Backend is up!${NC}"

# 3. Final Instructions
echo -e "${BLUE}=======================================${NC}"
echo -e "${GREEN}SUCCESS! The RIB Monitor stack is running.${NC}"
echo -e ""
echo -e "To access the ${CYAN}Live TUI Dashboard${NC}, run the following command:"
echo -e "${GREEN}   docker compose run --rm tui ${NC}"
echo -e ""
echo -e "Or if you want to run the TUI attached to the current shell right now,"
echo -e "press ${GREEN}Enter${NC}. Otherwise, press ${CYAN}Ctrl+C${NC} to exit."
echo -e "${BLUE}=======================================${NC}"

read

# 4. Launch TUI
docker compose run --rm tui
