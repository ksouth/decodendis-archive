#!/bin/bash
# Setup script for SCRAPE project

set -e

echo "🚀 Setting up SCRAPE..."

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check Python version
echo -e "${BLUE}Checking Python version...${NC}"
python3 --version

# Create virtual environment
echo -e "${BLUE}Creating virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
echo -e "${BLUE}Upgrading pip...${NC}"
pip install --upgrade pip

# Install dependencies
echo -e "${BLUE}Installing Python dependencies...${NC}"
pip install -r requirements.txt

# Copy environment file
if [ ! -f .env ]; then
    echo -e "${BLUE}Creating .env file...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✓ Created .env file (edit as needed)${NC}"
fi

# Setup frontend
if [ -d frontend ]; then
    echo -e "${BLUE}Setting up frontend...${NC}"
    cd frontend
    npm install
    cd ..
    echo -e "${GREEN}✓ Frontend dependencies installed${NC}"
fi

# Create necessary directories
mkdir -p logs data

echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Edit .env if needed"
echo "2. Configure data sources in config/sources.yaml"
echo "3. Start with: docker-compose up -d"
echo "4. Test scraper: python scripts/run_scraper.py --dry-run"
echo ""
