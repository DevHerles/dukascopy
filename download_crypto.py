#!/usr/bin/env python3
"""
Crypto Historical Data Downloader
=================================
Descarga OHLCV de pares cripto (BTCUSD, ETHUSD) desde APIs públicas
como Binance o Coinbase y genera series continuas en pandas.

Uso:
    python download_crypto.py --exchange binance --symbol BTCUSD \
        --start 2023-01-01 --end 2023-01-07 --output data/BTCUSD_binance.csv

Requiere:
    requests, pandas, tqdm
"""

import argparse
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


TIMEFRAME_SECONDS = {
    '1min': 60,
    '5min': 300,
    '15min': 900,
    '1h': 3600,
    '1d': 86400,
}

TIMEFRAME_FREQ = {
    '1min': '1min',
    '5min': '5min',
    '15min': '15min',
    '1h': '1h',
    '1d': '1d',
}

BINANCE_INTERVALS = {
    '1min': '1m',
    '5min': '5m',
    '15min': '15m',
    '1h': '1h',
    '1d': '1d',
}

BINANCE_SYMBOL_MAP = {
    'BTCUSD': 'BTCUSDT',
    'ETHUSD': 'ETHUSDT',
}

COINBASE_SYMBOL_MAP = {
    'BTCUSD': 'BTC-USD',
    'ETHUSD': 'ETH-USD',
}


def normalize_symbol(symbol: str, exchange: str) -> str:
    cleaned = symbol.replace('-', '').upper()

    if exchange == 'binance':
        return BINANCE_SYMBOL_MAP.get(cleaned, cleaned)

    if exchange == 'coinbase':
        if '-' in symbol:
            candidate = symbol.upper()
        elif len(cleaned) > 3:
            candidate = f"{cleaned[:-3]}-{cleaned[-3:]}"
        else:
            candidate = cleaned
        return COINBASE_SYMBOL_MAP.get(cleaned, candidate)

    return symbol


def binance_download(symbol: str, start: datetime, end: datetime, timeframe: str) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    interval = BINANCE_INTERVALS[timeframe]
    step_ms = TIMEFRAME_SECONDS[timeframe] * 1000
    start_utc = start.replace(tzinfo=timezone.utc)
    end_utc = end.replace(tzinfo=timezone.utc)
    start_ms = int(start_utc.timestamp() * 1000)
    end_ms = int(end_utc.timestamp() * 1000)
    rows = []

    with tqdm(desc="Binance", unit="batch") as bar:
        while start_ms < end_ms:
            params = {
                'symbol': symbol,
                'interval': interval,
                'startTime': start_ms,
                'endTime': end_ms,
                'limit': 1000,
            }
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if not data:
                break

            for entry in data:
                open_time = datetime.fromtimestamp(entry[0] / 1000, tz=timezone.utc)
                if open_time >= end_utc:
                    continue
                rows.append({
                    'timestamp': open_time,
                    'open': float(entry[1]),
                    'high': float(entry[2]),
                    'low': float(entry[3]),
                    'close': float(entry[4]),
                    'volume': float(entry[5]),
                })

            start_ms = data[-1][0] + step_ms
            bar.update(1)
            time.sleep(0.1)

    return pd.DataFrame(rows)


def coinbase_download(symbol: str, start: datetime, end: datetime, timeframe: str) -> pd.DataFrame:
    url = f"https://api.exchange.coinbase.com/products/{symbol}/candles"
    granularity = TIMEFRAME_SECONDS[timeframe]
    chunk_seconds = granularity * 300
    rows = []
    start_utc = start.replace(tzinfo=timezone.utc)
    end_utc = end.replace(tzinfo=timezone.utc)
    current = start_utc

    with tqdm(desc="Coinbase", unit="chunk") as bar:
        while current < end_utc:
            chunk_end = min(end_utc, current + timedelta(seconds=chunk_seconds))
            params = {
                'start': current.isoformat(),
                'end': chunk_end.isoformat(),
                'granularity': granularity,
            }

            candles = []
            for attempt in range(5):
                try:
                    response = requests.get(url, params=params, timeout=30)
                    response.raise_for_status()
                    candles = response.json()
                    break
                except requests.HTTPError as e:
                    status = e.response.status_code if e.response is not None else None
                    if attempt < 4 and status in {429, 500, 503}:
                        sleep_time = (2 ** attempt) + random.uniform(0, 1)
                        time.sleep(sleep_time)
                        continue
                    if status == 400:
                        logger.warning(f"Coinbase devolvió 400 para {current}→{chunk_end}; se omite el bloque")
                        break
                    logger.warning(f"Coinbase error {status} en {current}→{chunk_end}: {e}")
                    break
                except requests.RequestException as e:
                    if attempt < 4:
                        sleep_time = (2 ** attempt) + random.uniform(0, 1)
                        time.sleep(sleep_time)
                        continue
                    logger.warning(f"Fallo de red en {current}→{chunk_end}: {e}; se omite el bloque")
                    break

            if candles:
                for candle in candles:
                    ts = datetime.fromtimestamp(candle[0], tz=timezone.utc)
                    if ts < start_utc or ts >= end_utc:
                        continue
                    rows.append({
                        'timestamp': ts,
                        'open': float(candle[3]),
                        'high': float(candle[2]),
                        'low': float(candle[1]),
                        'close': float(candle[4]),
                        'volume': float(candle[5]),
                    })

            current = chunk_end
            bar.update(1)
            time.sleep(0.2)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values('timestamp')


def make_continuous(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if df.empty:
        return df

    freq = TIMEFRAME_FREQ[timeframe]
    df = df.drop_duplicates(subset='timestamp').sort_values('timestamp')
    df = df.set_index('timestamp')

    full_idx = pd.date_range(
        start=df.index.min().floor(freq),
        end=df.index.max().ceil(freq),
        freq=freq,
        tz=df.index.tz,
    )

    df = df.reindex(full_idx)
    df['close'] = df['close'].ffill()
    df['open'] = df['open'].fillna(df['close'])
    df['high'] = df['high'].fillna(df['close'])
    df['low'] = df['low'].fillna(df['close'])
    df['volume'] = df['volume'].fillna(0)

    df.index = df.index.tz_localize(None)
    df.index.name = 'timestamp'

    return df.reset_index()


def download_range(exchange: str, symbol: str, start_date: datetime, end_date: datetime,
                   timeframe: str, output_path: Path) -> pd.DataFrame:
    normalized_symbol = normalize_symbol(symbol, exchange)
    logger.info("=" * 60)
    logger.info("🪙 CRYPTO DATA DOWNLOADER")
    logger.info("=" * 60)
    logger.info(f"Exchange: {exchange}")
    logger.info(f"Símbolo solicitado: {symbol} -> {normalized_symbol}")
    logger.info(f"Período: {start_date} → {end_date}")
    logger.info(f"Timeframe: {timeframe}")

    if exchange == 'binance':
        raw = binance_download(normalized_symbol, start_date, end_date, timeframe)
    elif exchange == 'coinbase':
        raw = coinbase_download(normalized_symbol, start_date, end_date, timeframe)
    else:
        raise ValueError("Exchange no soportado. Usa binance o coinbase.")

    if raw.empty:
        logger.error("❌ No se obtuvieron datos")
        return pd.DataFrame()

    logger.info(f"✅ Descargadas {len(raw):,} velas crudas")

    ohlcv = make_continuous(raw, timeframe)
    if ohlcv.empty:
        logger.error("❌ Error al normalizar datos")
        return pd.DataFrame()

    logger.info(f"✅ Serie continua con {len(ohlcv):,} filas")
    logger.info(f"Rango final: {ohlcv['timestamp'].min()} → {ohlcv['timestamp'].max()}")
    logger.info(f"Volumen total: {ohlcv['volume'].sum():,.2f}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(output_path, index=False)
    logger.info(f"💾 Datos guardados en: {output_path}")

    return ohlcv


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, '%Y-%m-%d')


def main():
    parser = argparse.ArgumentParser(description="Descarga OHLCV de criptomonedas desde APIs públicas")
    parser.add_argument('--exchange', type=str, default='binance', choices=['binance', 'coinbase'],
                        help='Exchange a consultar')
    parser.add_argument('--symbol', type=str, default='BTCUSD',
                        help='Símbolo lógico (BTCUSD, ETHUSD) o nativo del exchange')
    parser.add_argument('--start', type=parse_date, default=parse_date('2023-01-01'),
                        help='Fecha inicio (YYYY-MM-DD)')
    parser.add_argument('--end', type=parse_date, default=parse_date('2023-01-07'),
                        help='Fecha fin (YYYY-MM-DD)')
    parser.add_argument('--output', type=str, default='data/BTCUSD_crypto.csv',
                        help='Archivo CSV de salida')
    parser.add_argument('--timeframe', type=str, default='1min', choices=list(TIMEFRAME_SECONDS.keys()),
                        help='Timeframe (1min, 5min, 15min, 1h, 1d)')

    args = parser.parse_args()
    output_path = Path(args.output)

    download_range(
        exchange=args.exchange,
        symbol=args.symbol,
        start_date=args.start,
        end_date=args.end,
        timeframe=args.timeframe,
        output_path=output_path,
    )


if __name__ == '__main__':
    main()
