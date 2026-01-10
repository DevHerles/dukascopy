#!/usr/bin/env python3
import subprocess
import time
import random
import argparse
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Bulk download Dukascopy data")
    parser.add_argument('--symbol', type=str, default='XAUUSD', help='Currency pair (e.g., XAUUSD, EURUSD)')
    args = parser.parse_args()

    years = range(2010, 2016) # 2010 to 2015 inclusive
    symbol = args.symbol
    
    for i, year in enumerate(years):
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        output_file = f"data/{symbol}_{year}.csv"
        
        logger.info(f"🚀 Starting download for Year: {year}")
        logger.info(f"   Range: {start_date} -> {end_date}")
        
        cmd = [
            "python", "download_dukascopy.py",
            "--symbol", symbol,
            "--start", start_date,
            "--end", end_date,
            "--output", output_file,
            "--timeframe", "1min",
            "--workers", "6"
        ]
        
        try:
            subprocess.run(cmd, check=True)
            logger.info(f"✅ Completed download for {year}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Error downloading {year}: {e}")
            continue
            
        # Pause between years, but not after the last one
        if i < len(years) - 1:
            sleep_time = random.randint(60, 120)
            logger.info(f"😴 Sleeping for {sleep_time} seconds to avoid rate limiting...")
            time.sleep(sleep_time)

    logger.info("🎉 All downloads completed!")

if __name__ == "__main__":
    main()
