# -*- coding: utf-8 -*-
"""
===================================
EastMoneyFundFetcher - ETF专用数据源 (Priority -1)
===================================

数据来源：天天基金网（东方财富旗下基金数据平台）
特点：免费、无需 Token、ETF数据准确、净值数据完整
网站：http://fund.eastmoney.com/

仅用于 ETF 数据查询，非 ETF 代码会抛出异常以允许降级到其他数据源。

天天基金 API：
- 历史净值：http://api.fund.eastmoney.com/f10/lsjz
- 实时估值：http://fundgz.eastmoney.com/js/{fund_code}.js

防封禁策略：
1. 每次请求前随机休眠 1.0-2.0 秒
2. 随机轮换 User-Agent
3. 使用 tenacity 实现指数退避重试
4. 熔断器机制：连续失败后自动冷却
"""

import logging
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS


logger = logging.getLogger(__name__)


# User-Agent 池，用于随机轮换
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]


def _is_etf_code(stock_code: str) -> bool:
    """
    Determine if the code is an ETF fund code.

    ETF code rules:
    - Shanghai ETF: 51xxxx, 52xxxx, 56xxxx, 58xxxx
    - Shenzhen ETF: 15xxxx, 16xxxx, 18xxxx

    Args:
        stock_code: Stock/fund code

    Returns:
        True if ETF code, False otherwise
    """
    etf_prefixes = ('51', '52', '56', '58', '15', '16', '18')
    return stock_code.startswith(etf_prefixes) and len(stock_code) == 6


class EastMoneyFundFetcher(BaseFetcher):
    """
    TianTian Fund (EastMoney Fund) data source implementation

    Priority: -1 (Highest, ETF only)
    Data source: TianTian Fund (EastMoney's fund platform)

    This fetcher ONLY supports ETF codes. Non-ETF codes will raise DataFetchError
    to allow fallback to other data sources.

    Key features:
    - Fetches historical NAV data from TianTian Fund API
    - Anti-scraping: random sleep 1.0-2.0 seconds, User-Agent rotation
    - Retry mechanism: up to 3 attempts with exponential backoff
    """

    name = "EastMoneyFundFetcher"
    priority = -1  # Highest priority for ETF queries

    # API endpoints
    HISTORICAL_NAV_URL = "http://api.fund.eastmoney.com/f10/lsjz"
    REALTIME_ESTIMATE_URL = "http://fundgz.eastmoney.com/js/{fund_code}.js"

    def __init__(self, sleep_min: float = 1.0, sleep_max: float = 2.0):
        """
        Initialize EastMoneyFundFetcher

        Args:
            sleep_min: Minimum sleep time (seconds)
            sleep_max: Maximum sleep time (seconds)
        """
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._last_request_time: Optional[float] = None
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        """Get or create requests session with random User-Agent"""
        if self._session is None:
            self._session = requests.Session()
            self._set_random_user_agent()
        return self._session

    def _set_random_user_agent(self) -> None:
        """Set random User-Agent for anti-scraping"""
        if self._session:
            random_ua = random.choice(USER_AGENTS)
            self._session.headers.update({
                'User-Agent': random_ua,
                'Referer': 'http://fundf10.eastmoney.com/',
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            })
            logger.debug(f"Set User-Agent: {random_ua[:50]}...")

    def _anti_scraping_sleep(self) -> None:
        """Random sleep to avoid being blocked"""
        sleep_time = random.uniform(self.sleep_min, self.sleep_max)
        logger.debug(f"Anti-scraping sleep: {sleep_time:.2f}s")
        time.sleep(sleep_time)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, DataFetchError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch raw historical NAV data from TianTian Fund API

        Args:
            stock_code: ETF fund code (must be ETF)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            DataFrame with raw data from API

        Raises:
            DataFetchError: If code is not ETF or API request fails
        """
        # Check if code is ETF - if not, raise exception to allow fallback
        if not _is_etf_code(stock_code):
            raise DataFetchError(
                f"[{self.name}] Only supports ETF codes. "
                f"'{stock_code}' is not an ETF code (expected prefixes: 51,52,56,58,15,16,18)"
            )

        logger.info(f"[{self.name}] Fetching ETF data for {stock_code}...")

        # Anti-scraping: random sleep before request
        self._anti_scraping_sleep()

        # Prepare request
        session = self._get_session()
        self._set_random_user_agent()  # Rotate User-Agent

        # Calculate page size (estimate ~250 trading days per year)
        # API returns at most 40 records per page
        page_size = 40
        page = 1

        all_data = []

        while True:
            # Use correct parameter names (camelCase as required by API)
            # Note: API has issues with recent year dates, so we always use empty startDate
            # and filter on client side instead
            params = {
                'callback': 'jQuery',  # JSONP callback required
                'fundCode': stock_code,  # Note: camelCase, not fund_code
                'pageIndex': page,
                'pageSize': page_size,
                'startDate': '',
                'endDate': '',
            }

            try:
                response = session.get(
                    self.HISTORICAL_NAV_URL,
                    params=params,
                    timeout=30,
                )
                response.raise_for_status()

                # Parse JSONP response: callback({...})
                content = response.text
                data = None

                # Try to parse JSONP format
                import re
                import json
                match = re.search(r'^(?:\w+)\((.*)\)$', content.strip(), re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                    except json.JSONDecodeError:
                        pass
                else:
                    # Try direct JSON parsing as fallback
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError:
                        pass

                # Debug: log response structure
                logger.debug(f"[{self.name}] API response for {stock_code}: {str(data)[:500] if data else 'None'}")

                if not data or 'Data' not in data or data['Data'] is None:
                    if page == 1:
                        # Log more details for debugging
                        logger.warning(f"[{self.name}] Unexpected response for {stock_code}: {content[:500]}")
                        raise DataFetchError(f"[{self.name}] No data returned for {stock_code}")
                    break

                records = data['Data'].get('LSJZList', []) or []
                if not records:
                    break

                all_data.extend(records)

                # Check if there are more pages
                # TotalCount is at the top level of the response, not inside Data
                total_count = data.get('TotalCount', 0) or 0
                if len(all_data) >= total_count or len(records) < page_size:
                    break

                page += 1
                self._anti_scraping_sleep()

            except requests.RequestException as e:
                logger.error(f"[{self.name}] Request failed: {e}")
                raise DataFetchError(f"[{self.name}] API request failed: {e}")

        if not all_data:
            raise DataFetchError(f"[{self.name}] No historical data found for ETF {stock_code}")

        # Convert to DataFrame
        df = pd.DataFrame(all_data)
        logger.info(f"[{self.name}] Fetched {len(df)} total records for {stock_code}")

        # Filter by date range on client side
        # (since we fetch all data without date filter due to API issues with recent dates)
        from datetime import datetime
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')

        df['FSRQ_dt'] = pd.to_datetime(df['FSRQ'])
        df = df[(df['FSRQ_dt'] >= start_dt) & (df['FSRQ_dt'] <= end_dt)]
        df = df.drop(columns=['FSRQ_dt'])

        logger.info(f"[{self.name}] Filtered to {len(df)} records for {stock_code} in date range {start_date} ~ {end_date}")

        if df.empty:
            raise DataFetchError(f"[{self.name}] No data found for ETF {stock_code} in date range {start_date} ~ {end_date}")

        return df

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        Normalize raw data to standard format

        TianTian Fund API fields mapping:
        - FSRQ -> date (date)
        - DWJZ -> close (unit NAV)
        - JZZZL -> pct_chg (change percentage)
        - LJJZ -> accumulated NAV (not used in standard columns)

        Note: TianTian Fund does not provide open/high/low/volume/amount,
        so we fill these with close (for O/H/L) and 0 (for volume/amount).

        Args:
            df: Raw DataFrame from API
            stock_code: ETF fund code

        Returns:
            Normalized DataFrame with STANDARD_COLUMNS
        """
        if df.empty:
            raise DataFetchError(f"[{self.name}] Empty data for {stock_code}")

        # Create normalized DataFrame
        normalized = pd.DataFrame()

        # Date
        normalized['date'] = pd.to_datetime(df['FSRQ']).dt.strftime('%Y-%m-%d')

        # Close price (unit NAV as close price)
        normalized['close'] = pd.to_numeric(df['DWJZ'], errors='coerce')

        # For ETF, we don't have open/high/low, use close for all
        normalized['open'] = normalized['close']
        normalized['high'] = normalized['close']
        normalized['low'] = normalized['close']

        # Volume and amount are not available for ETF NAV data
        normalized['volume'] = 0
        normalized['amount'] = 0

        # Change percentage
        # JZZZL may be empty for the first record, fill with 0
        normalized['pct_chg'] = pd.to_numeric(df['JZZZL'], errors='coerce').fillna(0)

        # Sort by date ascending (oldest first)
        normalized = normalized.sort_values('date').reset_index(drop=True)

        # Ensure column order matches STANDARD_COLUMNS
        normalized = normalized[STANDARD_COLUMNS]

        logger.info(f"[{self.name}] Normalized {len(normalized)} records for {stock_code}")

        return normalized

    def get_realtime_quote(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        Get realtime ETF estimate from TianTian Fund

        Args:
            stock_code: ETF fund code

        Returns:
            Dict with realtime quote data, or None if not available
        """
        if not _is_etf_code(stock_code):
            return None

        try:
            self._anti_scraping_sleep()

            session = self._get_session()
            self._set_random_user_agent()

            url = self.REALTIME_ESTIMATE_URL.format(fund_code=stock_code)
            response = session.get(url, timeout=10)
            response.raise_for_status()

            # Parse JS response: var fund_gz = {...};
            content = response.text

            # Extract JSON from JS variable
            import json
            import re

            match = re.search(r'var\s+fund_gz\s*=\s*(\{.*?\});', content, re.DOTALL)
            if not match:
                logger.warning(f"[{self.name}] Could not parse realtime data for {stock_code}")
                return None

            data = json.loads(match.group(1))

            return {
                'code': stock_code,
                'name': data.get('name', ''),
                'price': float(data.get('gsz', 0)),
                'change_pct': float(data.get('gszzl', 0)),
                'time': data.get('gztime', ''),
                'source': self.name,
            }

        except Exception as e:
            logger.warning(f"[{self.name}] Failed to get realtime quote for {stock_code}: {e}")
            return None
