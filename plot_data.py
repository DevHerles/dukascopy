#!/usr/bin/env python3
import argparse
import pandas as pd
import plotly.graph_objects as go
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Generate dynamic plot with EMA50 and EMA200")
    parser.add_argument('--data', type=str, required=True, help='Path to the dataset CSV file')
    args = parser.parse_args()

    file_path = Path(args.data)
    if not file_path.exists():
        logger.error(f"❌ File not found: {file_path}")
        return

    logger.info(f"📂 Loading data from {file_path}...")
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        logger.error(f"❌ Error loading CSV: {e}")
        return

    if 'close' not in df.columns:
        logger.error("❌ CSV must contain a 'close' column")
        return
    
    # Ensure timestamp is datetime
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Calculate EMAs
    logger.info("📈 Calculating EMA50 and EMA200...")
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()

    # Create Plot
    logger.info("🎨 Generating plot...")
    fig = go.Figure()

    # Candlestick chart
    fig.add_trace(go.Candlestick(
        x=df['timestamp'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name='OHLC'
    ))

    # EMA50
    fig.add_trace(go.Scatter(
        x=df['timestamp'],
        y=df['EMA50'],
        mode='lines',
        name='EMA 50',
        line=dict(color='orange', width=1.5)
    ))

    # EMA200
    fig.add_trace(go.Scatter(
        x=df['timestamp'],
        y=df['EMA200'],
        mode='lines',
        name='EMA 200',
        line=dict(color='blue', width=2)
    ))

    # Layout updates
    fig.update_layout(
        title=f'Price Chart with EMA50 & EMA200 - {file_path.name}',
        yaxis_title='Price',
        xaxis_title='Time',
        template='plotly_dark',
        xaxis_rangeslider_visible=False
    )

    output_file = file_path.with_suffix('.html')
    fig.write_html(output_file)
    logger.info(f"💾 Plot saved to: {output_file}")
    logger.info("✅ Done!")

if __name__ == "__main__":
    main()
