#!/usr/bin/env python3
"""
Dukascopy Historical Data Downloader
=====================================
Descarga datos tick de Dukascopy y los convierte a OHLCV M1 con bid/ask.

Uso:
    python scripts/download_dukascopy.py --start 2022-01-01 --end 2023-12-31 --output data/EURUSD_real.csv

Requiere:
    pip install requests lzma pandas numpy tqdm
"""

import argparse
import struct
import requests

# LZMA fallback for systems without native support
try:
    import lzma
except ImportError:
    try:
        from backports import lzma
    except ImportError:
        print("ERROR: Install lzma support with: pip install backports.lzma")
        print("       Or use: conda install -c conda-forge python-lzma")
        raise
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import time
import random
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Dukascopy almacena datos en UTC
# Estructura del tick: timestamp (4 bytes), ask (4 bytes), bid (4 bytes), ask_vol (4 bytes), bid_vol (4 bytes)
TICK_STRUCT = struct.Struct('>IIIff')

# URL base de Dukascopy
BASE_URL = "https://datafeed.dukascopy.com/datafeed/{symbol}/{year}/{month:02d}/{day:02d}/{hour:02d}h_ticks.bi5"

# Símbolos disponibles (punto base para conversión de precio)
SYMBOLS = {
    'EURUSD': 5,  # 5 decimales
    'GBPUSD': 5,
    'USDJPY': 3,
    'USDCHF': 5,
    'AUDUSD': 5,
    'USDCAD': 5,
    'XAUUSD': 5,
}


def download_hour(symbol: str, dt: datetime, max_retries: int = 10) -> list:
    """Descarga datos de una hora específica."""
    url = BASE_URL.format(
        symbol=symbol,
        year=dt.year,
        month=dt.month - 1,  # Dukascopy usa meses 0-indexed
        day=dt.day,
        hour=dt.hour
    )
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return []  # No hay datos para esta hora (fin de semana, etc.)
            response.raise_for_status()
            
            # Descomprimir LZMA
            try:
                decompressed = lzma.decompress(response.content)
            except lzma.LZMAError:
                return []  # Archivo corrupto o vacío
            
            # Parsear ticks
            ticks = []
            point = 10 ** SYMBOLS.get(symbol, 5)
            
            for i in range(0, len(decompressed), 20):
                if i + 20 > len(decompressed):
                    break
                    
                chunk = decompressed[i:i+20]
                ms_offset, ask_int, bid_int, ask_vol, bid_vol = TICK_STRUCT.unpack(chunk)
                
                tick_time = dt + timedelta(milliseconds=ms_offset)
                ask = ask_int / point
                bid = bid_int / point
                
                ticks.append({
                    'timestamp': tick_time,
                    'bid': bid,
                    'ask': ask,
                    'bid_volume': bid_vol,
                    'ask_volume': ask_vol
                })
            
            return ticks
            
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                # Exponential backoff con jitter: 2^attempt + random(0,1)
                # attempt 0: 1s
                # attempt 1: 2s
                # attempt 2: 4s
                # ...
                sleep_time = (2 ** attempt) + random.uniform(0, 1)
                
                # Si es error 503 (Service Unavailable) o 429 (Too Many Requests), esperar más
                if hasattr(e, 'response') and e.response is not None:
                    if e.response.status_code in [503, 429]:
                        sleep_time += 10 # Penalización extra
                        
                time.sleep(sleep_time)
            else:
                logger.warning(f"Failed to download {url}: {e}")
                return []
    
    return []


def ticks_to_ohlcv(ticks_df: pd.DataFrame, timeframe: str = '1min') -> pd.DataFrame:
    """Convierte ticks a OHLCV con bid/ask."""
    if ticks_df.empty:
        return pd.DataFrame()
    
    ticks_df = ticks_df.set_index('timestamp')
    
    # Precio mid para OHLC
    ticks_df['mid'] = (ticks_df['bid'] + ticks_df['ask']) / 2
    ticks_df['spread'] = ticks_df['ask'] - ticks_df['bid']
    ticks_df['volume'] = ticks_df['bid_volume'] + ticks_df['ask_volume']
    
    # Resamplear a M1
    ohlc = ticks_df['mid'].resample(timeframe).ohlc()
    ohlc.columns = ['open', 'high', 'low', 'close']
    
    # Agregar bid/ask promedio, spread y volumen
    ohlc['bid'] = ticks_df['bid'].resample(timeframe).last()
    ohlc['ask'] = ticks_df['ask'].resample(timeframe).last()
    ohlc['spread'] = ticks_df['spread'].resample(timeframe).mean()
    ohlc['volume'] = ticks_df['volume'].resample(timeframe).sum()
    
    # Dropear filas sin datos iniciales para limpiar
    # ohlc = ohlc.dropna(subset=['open', 'close']) # ELIMINADO: Queremos continuous time series
    
    # Crear rango completo de tiempo
    full_idx = pd.date_range(start=ticks_df.index.min().floor(timeframe), 
                             end=ticks_df.index.max().ceil(timeframe), 
                             freq=timeframe)
    
    # Reindexar para rellenar huecos
    ohlc = ohlc.reindex(full_idx)
    
    # Rellenar precios con Forward Fill (el precio se mantiene si no hay operaciones)
    cols_ffill = ['close', 'bid', 'ask', 'spread']
    ohlc[cols_ffill] = ohlc[cols_ffill].ffill()
    
    # Para Open, High, Low de velas vacías, usar el Close anterior
    # Si acabamos de hacer ffill en close, el close actual es el close del anterior.
    # Por tanto, si Open es NaT (o NaN), debe ser igual al Close actual (que ya es el anterior).
    mask_missing = ohlc['open'].isna()
    ohlc.loc[mask_missing, 'open'] = ohlc.loc[mask_missing, 'close']
    ohlc.loc[mask_missing, 'high'] = ohlc.loc[mask_missing, 'close']
    ohlc.loc[mask_missing, 'low'] = ohlc.loc[mask_missing, 'close']
    
    # Rellenar volumen con 0
    ohlc['volume'] = ohlc['volume'].fillna(0)
    
    # Renombrar índice
    ohlc.index.name = 'timestamp'
    
    return ohlc.reset_index()


def download_range(symbol: str, start_date: datetime, end_date: datetime, 
                   output_path: Path, timeframe: str = '1min', workers: int = 8) -> pd.DataFrame:
    """Descarga un rango de fechas completo."""
    
    # Generar lista de horas a descargar
    hours = []
    current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    while current <= end_date:
        hours.append(current)
        current += timedelta(hours=1)
    
    logger.info(f"📥 Descargando {len(hours)} horas de datos para {symbol}")
    logger.info(f"   Período: {start_date.date()} → {end_date.date()}")
    
    all_ticks = []
    
    # Descargar en paralelo con barra de progreso
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download_hour, symbol, h): h for h in hours}
        
        for future in tqdm(as_completed(futures), total=len(futures), desc="Downloading"):
            hour = futures[future]
            try:
                ticks = future.result()
                all_ticks.extend(ticks)
            except Exception as e:
                logger.error(f"Error processing {hour}: {e}")
    
    if not all_ticks:
        logger.error("❌ No se descargaron datos")
        return pd.DataFrame()
    
    logger.info(f"✅ Descargados {len(all_ticks):,} ticks")
    
    # Convertir a DataFrame
    ticks_df = pd.DataFrame(all_ticks)
    ticks_df = ticks_df.sort_values('timestamp').reset_index(drop=True)
    
    # Convertir a OHLCV M1
    logger.info("🔄 Convirtiendo ticks a OHLCV M1...")
    ohlcv = ticks_to_ohlcv(ticks_df, timeframe)
    
    if ohlcv.empty:
        logger.error("❌ Error al convertir ticks a OHLCV")
        return pd.DataFrame()
    
    logger.info(f"✅ Generadas {len(ohlcv):,} velas M1")
    
    # Estadísticas de calidad
    logger.info("\n📊 ESTADÍSTICAS DE CALIDAD:")
    logger.info(f"   Período: {ohlcv['timestamp'].min()} → {ohlcv['timestamp'].max()}")
    logger.info(f"   Total velas: {len(ohlcv):,}")
    logger.info(f"   Spread promedio: {ohlcv['spread'].mean() * 10000:.2f} pips")
    logger.info(f"   Spread máximo: {ohlcv['spread'].max() * 10000:.2f} pips")
    
    # Verificar velas planas
    flat_candles = ((ohlcv['high'] - ohlcv['low']).abs() < 1e-6).sum()
    logger.info(f"   Velas planas (rango=0): {flat_candles} ({100*flat_candles/len(ohlcv):.2f}%)")
    
    # Guardar
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ohlcv.to_csv(output_path, index=False)
    logger.info(f"\n💾 Datos guardados en: {output_path}")
    
    # Guardar también ticks raw por si se necesitan
    ticks_path = output_path.with_suffix('.ticks.parquet')
    ticks_df.to_parquet(ticks_path, index=False)
    logger.info(f"💾 Ticks raw guardados en: {ticks_path}")
    
    return ohlcv


def main():
    parser = argparse.ArgumentParser(description="Descarga datos históricos de Dukascopy")
    parser.add_argument('--symbol', type=str, default='EURUSD', 
                        choices=list(SYMBOLS.keys()),
                        help='Par de divisas')
    parser.add_argument('--start', type=str, default='2022-01-01',
                        help='Fecha inicio (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2023-12-31',
                        help='Fecha fin (YYYY-MM-DD)')
    parser.add_argument('--output', type=str, default='data/EURUSD_dukascopy.csv',
                        help='Archivo de salida')
    parser.add_argument('--workers', type=int, default=8,
                        help='Número de workers paralelos')
    parser.add_argument('--timeframe', type=str, default='1min',
                        help='Timeframe pandas (e.g., 1min, 5min, 1H)')
    
    args = parser.parse_args()
    
    start_date = datetime.strptime(args.start, '%Y-%m-%d')
    end_date = datetime.strptime(args.end, '%Y-%m-%d')
    output_path = Path(args.output)
    
    logger.info("=" * 60)
    logger.info("🏦 DUKASCOPY DATA DOWNLOADER")
    logger.info("=" * 60)
    
    df = download_range(
        symbol=args.symbol,
        start_date=start_date,
        end_date=end_date,
        output_path=output_path,
        timeframe=args.timeframe,
        workers=args.workers
    )
    
    if not df.empty:
        logger.info("\n✅ DESCARGA COMPLETADA EXITOSAMENTE")
        logger.info(f"   Columnas: {list(df.columns)}")
        logger.info(f"   Shape: {df.shape}")
    else:
        logger.error("\n❌ DESCARGA FALLIDA")


if __name__ == '__main__':
    main()
