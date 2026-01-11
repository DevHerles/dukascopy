# Dukascopy Data Downloader

## Setup
1. Create virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## Usage
Run the script to download historical tick data converted to M1 OHLCV:
```bash
python download_dukascopy.py --start <START_DATE> --end <END_DATE> --output <OUTPUT_FILE> --workers <N> --symbol <SYMBOL>
```

### Arguments
- `--symbol`: Currency pair (e.g., EURUSD, XAUUSD).
- `--start`: Start date (YYYY-MM-DD).
- `--end`: End date (YYYY-MM-DD).
- `--output`: Output CSV file path.
- `--workers`: Number of parallel download threads.

## Example
Download XAUUSD data for January 2010:
```bash
python download_dukascopy.py --start 2010-01-01 --end 2010-01-31 --output data/XUAUSD_dukascopy_2010.csv --workers 16 --symbol XAUUSD
```

## Output
The script generates:
1. A CSV file with M1 OHLCV data (including spread and bid/ask volumes).

## Bulk Download (2010-2015)
To download XAUUSD data from 2010 to 2015 with automatic pauses to avoid rate limiting:

To download XAUUSD data from 2010 to 2015 with automatic pauses to avoid rate limiting:

```bash
python download_wrapper.py --symbol XAUUSD
```

You can also specify other symbols (default is XAUUSD):
```bash
python download_wrapper.py --symbol EURUSD
```

This script will:
1. Iterate through years 2010 to 2015.
2. Download data for each year into `data/{SYMBOL}_{year}.csv`.
3. Sleep for a random interval (60-120 seconds) between years.

## Features & Reliability
- **Forward Fill**: The script automatically fills missing minutes (where no ticks occurred) with the previous close price and volume=0. This ensures a continuous time series suitable for backtesting and ML.
- **Resilient Downloads**: Includes exponential backoff for handling 503/429 errors from Dukascopy, ensuring downloads continue even under rate limiting.
- **Bulk Wrapper**: `download_wrapper.py` handles multi-year downloads with automatic pauses to be friendly to the server limits.

## Visualization
To generate a dynamic HTML chart with EMA50 and EMA200:

```bash
python plot_data.py --data data/YOUR_FILE.csv
```

Example:
```bash
python plot_data.py --data data/XAUUSD_2010.csv
```
This will create `data/XAUUSD_2010.html` which you can open in any web browser.



