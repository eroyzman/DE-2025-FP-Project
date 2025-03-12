# DE-2025-FP-Project
Modules & Components
0. Prerequisites
There should be a database with preexisting data. Someone needs to:

Make a tutorial on how to create, set up, and connect to the database using the UI dashboard (for example, pgAdmin for Postgres database)
Make a code example on how to connect to the database using Python and the database credentials
Create SQL migrations that will create all the necessary tables in the database
Create a seed script that will add initial data into the tables


Proposed table structure:


Companies (table that has the data about several companies that will be tracked )
- ID (unique id)
- NAME (Apple / Microsoft / Facebook)
- TICKER (APPL / MSFT / META)


News (news table, should have a foreign key and many-to-one relation to “Companies” table, because one company – many news)
- ID (unique id)
- COMPANY_ID (foreign key to Companies table)
- NEWS_TEXT (actual text retrieved from the news article)
- TIME (time when the news got retrieved)

StockPrice (table that stock price data will be saved to, should have a foreign key and many-to-one relation to “Companies” table, because one company – many stock price snapshots).
- ID (unique id)
- COMPANY_ID (foreign key to Companies table)
- PRICE (stock price)
- TIME (time when the stock price data got retrieved)


Correlation (table that will store data when news affects stock price, should have a foreign key and many-to-one relation to “Companies” table, a foreign key and one-to-one relation to “News” table, a foreign key and one-to-one relation to “StockPrice” table)
- ID (unique id)
- COMPANY_ID (foreign key to Companies table)
- NEWS_ID (foreign key to News table)
- STOCK_PRICE_ID (foreign key to StockPrice table)
- CORRELATION_INDEX (is this a strong, moderate or weak price spike / correlation?)



Proposed seed data: There’s only a need to fill in the “Companies” table; the API requests will fill out the rest of the tables. So I think the “Companies” table should be filled with:

| ID | NAME      | TICKER |
| -- | --------- | ------ |
| 1  | Apple     | APPL   |
| 2  | Microsoft | MSFT   |

1. Data Collection Layer
Cron job responsible for fetching stock prices and financial news, that runs on specified schedule. For example, once per 10 minutes. Use `yahoo_fin` package or any similar one to obtain financial data

News Fetcher (Yahoo Finance News Scraper). Cron job that runs every 10 minutes. It retrieves all companies from the “Companies” table described above. Then runs through all the companies in a loop and retrieves news via “yahoo_fin” Python package. Populates “News” table described above. 



Stock Price Tracker (Yahoo Finance API). Cron job that runs every 10 minutes. It retrieves all companies from the “Companies” table described above. Then runs through all the companies in a loop and retrieves stock price data via “yahoo_fin” Python package. Populates “StockPrice” table described above. 

2. Data Processing Layer
This layer processes data in the database and identifies correlations. 

Correlation Analyzer. Cron job that runs every 10 minutes. It retrieves all stock price entries for a specific timeslot (for example, during the last hour) from the “StockPrice” table described above. If the stock price is much higher / lower than the previous entry in the database – something happened and you’ll need to look in the “News” table for a specified time if there are any news that could lead to that price drop / increase.

If there’s a news entry about the time of the price change, add a new entry to the “Correlation” table. Use % from the Stock Price value to determine if the price change is significant. For example, a 2% change is not significant, and 10% is highly significant but will rarely happen, especially to big companies.

3. Notification & API Layer
Provides access to processed data. When API endpoint is called via POST request — provide some data from the DB
