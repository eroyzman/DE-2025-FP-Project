from typing import List, Dict, Optional
import yfinance as yf
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime, timedelta
import logging
import random

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()
scheduler = BlockingScheduler()


# Database connection
def get_db_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        dbname="stock_tracker",
        user="postgres",
        password="password",  # Replace with your actual password
        host="localhost",
        cursor_factory=RealDictCursor
    )


# Database setup
def setup_database():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100),
                ticker VARCHAR(10) UNIQUE
            );
            CREATE TABLE IF NOT EXISTS stockprice (
                id SERIAL PRIMARY KEY,
                company_id INTEGER REFERENCES companies(id),
                price FLOAT,
                time TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                company_id INTEGER REFERENCES companies(id),
                news_text TEXT,
                time TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS correlation (
                id SERIAL PRIMARY KEY,
                company_id INTEGER REFERENCES companies(id),
                news_id INTEGER REFERENCES news(id),
                stock_price_id INTEGER REFERENCES stockprice(id),
                correlation_index FLOAT,
                time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("INSERT INTO companies (name, ticker) VALUES ('Apple', 'AAPL') ON CONFLICT (ticker) DO NOTHING;")
        cur.execute(
            "INSERT INTO companies (name, ticker) VALUES ('Microsoft', 'MSFT') ON CONFLICT (ticker) DO NOTHING;")
        conn.commit()
    conn.close()
    logger.info("Tables created and seeded.")


# Fetch companies
def fetch_companies(conn: psycopg2.extensions.connection) -> List[Dict[str, any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM companies")
        return cur.fetchall()


# Fetch news via yfinance with nested content handling
# def fetch_news(ticker: str) -> List[Dict[str, any]]:
#     try:
#         logger.info(f"Fetching news for ticker: {ticker} via yfinance")
#         stock = yf.Ticker(ticker)
#         news_items = stock.news[:3]  # Get top 3 news items
#         logger.info(f"Raw news response: {news_items}")
#         result = []
#         for item in news_items:
#             content = item.get("content", {})
#             if "title" in content and "providerPublishTime" in content:
#                 result.append({
#                     "text": content["title"],
#                     "time": datetime.fromtimestamp(content["providerPublishTime"])
#                 })
#             else:
#                 logger.warning(f"Skipping news item due to missing keys: {item}")
#         logger.info(f"Processed news: {result}")
#         return result
#     except Exception as e:
#         logger.error(f"Error fetching news for {ticker}: {e}", exc_info=True)
#         return []

def fetch_news(ticker: str) -> List[Dict[str, any]]:
    try:
        logger.info(f"Fetching news for ticker: {ticker} via yfinance")
        stock = yf.Ticker(ticker)
        news_items = stock.news[:3]  # Get top 3 news items
        logger.info(f"Raw news response: {news_items}")
        result = []
        for item in news_items:
            content = item.get("content", {})
            if "title" in content and "pubDate" in content:
                # Parse ISO 8601 timestamp from pubDate
                pub_date = datetime.strptime(content["pubDate"], "%Y-%m-%dT%H:%M:%SZ")
                result.append({
                    "text": content["title"],
                    "time": pub_date
                })
            else:
                logger.warning(f"Skipping news item due to missing keys: {item}")
        logger.info(f"Processed news: {result}")
        return result
    except Exception as e:
        logger.error(f"Error fetching news for {ticker}: {e}", exc_info=True)
        return []


# Save news with deduplication
def save_news(conn: psycopg2.extensions.connection, company_id: int, news_items: List[Dict[str, any]]) -> None:
    try:
        with conn.cursor() as cur:
            for item in news_items:
                cur.execute(
                    "SELECT id FROM news WHERE company_id = %s AND news_text = %s AND time = %s",
                    (company_id, item["text"], item["time"])
                )
                if not cur.fetchone():  # Only insert if not already present
                    cur.execute(
                        "INSERT INTO news (company_id, news_text, time) VALUES (%s, %s, %s)",
                        (company_id, item["text"], item["time"])
                    )
            conn.commit()
        logger.info(f"News committed for company_id {company_id}")
    except Exception as e:
        logger.error(f"Error saving news for company_id {company_id}: {e}")
        conn.rollback()


# Fetch live stock price with temporary randomization for testing
def fetch_stock_price(ticker: str) -> Optional[float]:
    try:
        logger.info(f"Fetching price for {ticker} via yfinance...")
        stock = yf.Ticker(ticker)
        price = stock.info["regularMarketPrice"]  # Live price
        # price *= random.uniform(0.99, 1.01)  # ±1% variation for testing
        logger.info(f"Price fetched for {ticker}: {price}")
        return float(price)
    except Exception as e:
        logger.error(f"Error fetching price for {ticker}: {e}")
        return None


# Save stock price
def save_stock_price(conn: psycopg2.extensions.connection, company_id: int, price: Optional[float]) -> None:
    if price is None:
        logger.info(f"Skipping save: No price provided for company_id {company_id}")
        return
    try:
        price = float(price)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO stockprice (company_id, price, time) VALUES (%s, %s, %s)",
                (company_id, price, datetime.now())
            )
            conn.commit()
        logger.info(f"Price {price} committed for company_id {company_id}")
    except Exception as e:
        logger.error(f"Error saving price for company_id {company_id}: {e}")
        conn.rollback()


# Analyze correlation with wider time window and lower threshold for testing
def analyze_correlation(prices: List[Dict[str, any]], news: List[Dict[str, any]], threshold: float = 0.002) -> List[
    Dict[str, any]]:
    logger.info(f"Analyzing correlation: {len(prices)} prices, {len(news)} news items")
    if len(prices) < 2:
        logger.info("Not enough prices for correlation")
        return []
    prev_price = float(prices[-2]["price"])
    curr_price = float(prices[-1]["price"])
    price_change = abs(curr_price - prev_price) / prev_price
    logger.info(f"Price change: {price_change}, threshold: {threshold}")
    if price_change < threshold:
        logger.info("Price change below threshold")
        return []
    relevant_news = [n for n in news if abs((n["time"] - prices[-1]["time"]).total_seconds()) < 3600]  # 1 hour window
    logger.info(f"Relevant news items: {len(relevant_news)}")
    return [{"news_id": n["id"], "stock_price_id": prices[-1]["id"], "correlation_index": price_change} for n in
            relevant_news]


# Save correlation
def save_correlation(conn: psycopg2.extensions.connection, company_id: int, correlations: List[Dict[str, any]]) -> None:
    if not correlations:
        logger.info(f"No correlations to save for company_id {company_id}")
        return
    try:
        with conn.cursor() as cur:
            for corr in correlations:
                cur.execute(
                    "INSERT INTO correlation (company_id, news_id, stock_price_id, correlation_index) VALUES (%s, %s, %s, %s)",
                    (company_id, corr["news_id"], corr["stock_price_id"], corr["correlation_index"])
                )
            conn.commit()
        logger.info(f"Correlations committed for company_id {company_id}")
    except Exception as e:
        logger.error(f"Error saving correlations for company_id {company_id}: {e}")
        conn.rollback()


# Jobs
def collect_news_job():
    logger.info("Running collect_news_job...")
    conn = get_db_connection()
    companies = fetch_companies(conn)
    logger.info(f"Found {len(companies)} companies: {companies}")
    for company in companies:
        news_items = fetch_news(company["ticker"])
        logger.info(f"News for {company['ticker']}: {news_items}")
        logger.info(f"Saving news for {company['ticker']}...")
        save_news(conn, company["id"], news_items)
        logger.info(f"News saved for {company['ticker']}.")
    conn.close()
    logger.info("collect_news_job completed.")


def collect_stock_price_job():
    logger.info("Running collect_stock_price_job...")
    conn = get_db_connection()
    companies = fetch_companies(conn)
    logger.info(f"Found {len(companies)} companies: {companies}")
    for company in companies:
        price = fetch_stock_price(company["ticker"])
        logger.info(f"Price for {company['ticker']}: {price}")
        logger.info(f"Saving price for {company['ticker']}...")
        save_stock_price(conn, company["id"], price)
        logger.info(f"Price saved for {company['ticker']}.")
    conn.close()
    logger.info("collect_stock_price_job completed.")


def analyze_correlation_job():
    logger.info("Running analyze_correlation_job...")
    conn = get_db_connection()
    companies = fetch_companies(conn)
    logger.info(f"Found {len(companies)} companies: {companies}")
    for company in companies:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM stockprice WHERE company_id = %s AND time > %s ORDER BY time",
                (company["id"], datetime.now() - timedelta(hours=1))
            )
            prices = cur.fetchall()
            logger.info(f"Prices for {company['ticker']}: {prices}")
            cur.execute(
                "SELECT * FROM news WHERE company_id = %s AND time > %s ORDER BY time",
                (company["id"], datetime.now() - timedelta(hours=1))
            )
            news = cur.fetchall()
            logger.info(f"News for {company['ticker']}: {news}")
        correlations = analyze_correlation(prices, news)
        logger.info(f"Correlations for {company['ticker']}: {correlations}")
        save_correlation(conn, company["id"], correlations)
    conn.close()
    logger.info("analyze_correlation_job completed.")


# Main execution with enhanced crash logging
if __name__ == "__main__":
    try:
        # logger.info("Setting up database...")
        # setup_database()
        # logger.info("Database setup complete.")

        logger.info("Adding jobs to scheduler...")
        scheduler.add_job(collect_news_job, "interval", minutes=10)
        scheduler.add_job(collect_stock_price_job, "interval", minutes=10)
        scheduler.add_job(analyze_correlation_job, "interval", minutes=10)
        logger.info("Jobs added.")
        scheduler.print_jobs()

        logger.info("Running jobs once immediately...")
        collect_news_job()
        collect_stock_price_job()
        analyze_correlation_job()
        logger.info("Immediate run complete. Starting scheduler...")

        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user.")
        scheduler.shutdown()
    except Exception as e:
        logger.error(f"Unexpected error causing crash: {e}", exc_info=True)
        scheduler.shutdown()
    finally:
        logger.info("Ensuring all connections are closed.")