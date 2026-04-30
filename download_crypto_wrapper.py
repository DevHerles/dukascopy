#!/usr/bin/env python3
import argparse
import logging
import random
import subprocess
import time


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Bulk download crypto OHLCV using download_crypto.py")
    parser.add_argument('--symbol', type=str, default='BTCUSD', help='Símbolo lógico (BTCUSD, ETHUSD)')
    parser.add_argument('--exchange', type=str, default='binance', choices=['binance', 'coinbase'],
                        help='Exchange a consultar')
    parser.add_argument('--start-year', type=int, default=2010, help='Año inicial (inclusive)')
    parser.add_argument('--end-year', type=int, default=2026, help='Año final (inclusive)')
    parser.add_argument('--years', type=int, nargs='+', help='Lista explícita de años a descargar (prioridad sobre start/end)')
    parser.add_argument('--timeframe', type=str, default='1min',
                        choices=['1min', '5min', '15min', '1h', '1d'],
                        help='Timeframe de velas')
    parser.add_argument('--sleep-min', type=int, default=5, help='Pausa mínima entre años (segundos)')
    parser.add_argument('--sleep-max', type=int, default=15, help='Pausa máxima entre años (segundos)')
    parser.add_argument('--retry-rounds', type=int, default=1, help='Número de rondas de reintento para años fallidos')
    args = parser.parse_args()

    if args.years:
        years = args.years
    else:
        years = range(args.start_year, args.end_year + 1)

    def run_year(year: int) -> bool:
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        output_file = f"data/{args.symbol}_{args.exchange}_{year}.csv"

        logger.info(f"🚀 Descargando {args.symbol} {year} en {args.exchange}")
        logger.info(f"   Rango: {start_date} -> {end_date}")
        logger.info(f"   Output: {output_file}")

        cmd = [
            "python", "download_crypto.py",
            "--exchange", args.exchange,
            "--symbol", args.symbol,
            "--start", start_date,
            "--end", end_date,
            "--output", output_file,
            "--timeframe", args.timeframe,
        ]

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"✅ Año {year} completado")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Error en el año {year}: {e}")
            return False

    failed_years = []

    for i, year in enumerate(years):
        success = run_year(year)
        if not success:
            failed_years.append(year)

        if i < len(years) - 1:
            sleep_time = random.randint(args.sleep_min, args.sleep_max)
            logger.info(f"😴 Pausa de {sleep_time}s antes del siguiente año")
            time.sleep(sleep_time)

    for retry_round in range(args.retry_rounds):
        if not failed_years:
            break
        to_retry = failed_years
        failed_years = []
        logger.info(f"♻️ Reintento {retry_round + 1}/{args.retry_rounds} para años: {to_retry}")
        for idx, year in enumerate(to_retry):
            success = run_year(year)
            if not success:
                failed_years.append(year)
            if idx < len(to_retry) - 1:
                sleep_time = random.randint(args.sleep_min, args.sleep_max)
                logger.info(f"😴 Pausa de {sleep_time}s antes del siguiente reintento")
                time.sleep(sleep_time)

    if failed_years:
        logger.warning(f"⚠️ Años aún fallidos tras reintentos: {failed_years}")
    logger.info("🎉 Descargas finalizadas")


if __name__ == "__main__":
    main()
