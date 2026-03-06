# -*- coding: utf-8 -*-
"""
===================================
数据源测试脚本
===================================

独立的数据源测试工具，支持：
1. 单个数据源测试
2. 按优先级自动切换测试
3. 历史数据获取测试
4. 实时行情获取测试
5. 数据源状态检查
6. ETF专用数据源测试（天天基金）

使用方法：
    # 测试所有数据源（按优先级）
    python scripts/test_data_sources.py

    # 测试指定股票
    python scripts/test_data_sources.py --stock 600519

    # 测试指定日期范围
    python scripts/test_data_sources.py --stock 000001 --days 60

    # 测试单个数据源
    python scripts/test_data_sources.py --fetcher efinance

    # 测试 ETF 数据（使用天天基金数据源）
    python scripts/test_data_sources.py --etf
    python scripts/test_data_sources.py --etf --fetcher eastmoney_fund

    # 测试实时行情
    python scripts/test_data_sources.py --realtime

    # 详细模式
    python scripts/test_data_sources.py --verbose

    # 显示数据源列表
    python scripts/test_data_sources.py --list
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import pandas as pd


# 配置日志
def setup_logging(verbose: bool = False):
    """配置日志输出"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger(__name__)


logger = setup_logging()


# === 数据源导入 ===
def import_data_sources():
    """动态导入所有数据源"""
    try:
        # 检查依赖
        import pandas
        import numpy

        from data_provider.base import (
            DataFetcherManager,
            BaseFetcher,
        )
        from data_provider.efinance_fetcher import EfinanceFetcher
        from data_provider.akshare_fetcher import AkshareFetcher
        from data_provider.tushare_fetcher import TushareFetcher
        from data_provider.pytdx_fetcher import PytdxFetcher
        from data_provider.baostock_fetcher import BaostockFetcher
        from data_provider.yfinance_fetcher import YfinanceFetcher
        from data_provider.eastmoney_fund_fetcher import EastMoneyFundFetcher

        return {
            'manager': DataFetcherManager,
            'base': BaseFetcher,
            'efinance': EfinanceFetcher,
            'akshare': AkshareFetcher,
            'tushare': TushareFetcher,
            'pytdx': PytdxFetcher,
            'baostock': BaostockFetcher,
            'yfinance': YfinanceFetcher,
            'eastmoney_fund': EastMoneyFundFetcher,
        }
    except ImportError as e:
        logger.error(f"导入数据源失败: {e}")
        logger.error("请确保已安装所有依赖: pip install -r requirements.txt")
        logger.error("或使用项目的虚拟环境运行此脚本")
        sys.exit(1)


# === 数据源信息 ===
FETCHER_INFO = {
    'eastmoney_fund': {
        'name': 'EastMoneyFundFetcher',
        'priority': -1,  # ETF专用，最高优先级
        'description': '天天基金（ETF专用，免费、无需Token）',
        'module': 'eastmoney_fund'
    },
    'efinance': {
        'name': 'EfinanceFetcher',
        'priority': 0,
        'description': '东方财富数据源（免费、无需Token）',
        'module': 'efinance'
    },
    'akshare': {
        'name': 'AkshareFetcher',
        'priority': 1,
        'description': 'Akshare数据源（免费、无需Token）',
        'module': 'akshare'
    },
    'tushare': {
        'name': 'TushareFetcher',
        'priority': -1,  # 配置Token后动态提升
        'description': 'Tushare Pro（需要Token，数据质量最高）',
        'module': 'tushare'
    },
    'pytdx': {
        'name': 'PytdxFetcher',
        'priority': 2,
        'description': '通达信数据源（本地数据）',
        'module': 'pytdx'
    },
    'baostock': {
        'name': 'BaostockFetcher',
        'priority': 3,
        'description': 'Baostock数据源（免费但数据有限）',
        'module': 'baostock'
    },
    'yfinance': {
        'name': 'YfinanceFetcher',
        'priority': 4,
        'description': 'Yahoo Finance（美股专用）',
        'module': 'yfinance'
    },
}


# === 格式化输出 ===
def print_header(text: str, char: str = "=", width: int = 80):
    """打印标题"""
    print(f"\n{text} {char * (width - len(text) - 2)}")


def print_sub_header(text: str, char: str = "-", width: int = 80):
    """打印子标题"""
    print(f"\n{text} {char * (width - len(text) - 2)}")


def format_dataframe(df: pd.DataFrame, max_rows: int = 10) -> str:
    """格式化DataFrame输出"""
    if df is None or df.empty:
        return "  (无数据)"

    lines = []
    lines.append(f"  形状: {df.shape}")
    lines.append(f"  列名: {list(df.columns)}")
    lines.append(f"\n  数据预览 (最多显示 {max_rows} 行):")
    lines.append("  " + str(df.head(max_rows).to_string()))
    return "\n".join(lines)


# === 测试函数 ===
def test_single_fetcher(fetcher_class, stock_code: str, days: int = 30):
    """测试单个数据源"""
    print_sub_header(f"测试 {fetcher_class.name}")

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    print(f"  股票代码: {stock_code}")
    print(f"  日期范围: {start_date} ~ {end_date}")
    print(f"  优先级: {fetcher_class.priority}")

    try:
        # 创建数据源实例
        fetcher = fetcher_class()
        print(f"  初始化: 成功")

        # 获取历史数据
        start_time = time.time()
        df = fetcher.get_daily_data(
            stock_code=stock_code,
            start_date=start_date,
            end_date=end_date
        )
        elapsed = time.time() - start_time

        if df is not None and not df.empty:
            print(f"  获取历史数据: 成功 ({len(df)} 条记录, 耗时 {elapsed:.2f}秒)")
            print(format_dataframe(df))
            return True, fetcher.name, df
        else:
            print(f"  获取历史数据: 失败 (返回空数据)")
            return False, fetcher.name, None

    except Exception as e:
        print(f"  测试失败: {type(e).__name__}: {e}")
        return False, fetcher_class.name, None


def test_manager_with_priority(sources: dict, stock_code: str, days: int = 30):
    """测试按优先级获取数据"""
    print_sub_header("测试按优先级自动切换")

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    print(f"  股票代码: {stock_code}")
    print(f"  日期范围: {start_date} ~ {end_date}")

    try:
        # 创建管理器
        manager = sources['manager']()
        print(f"  管理器初始化: 成功")

        # 显示数据源优先级
        print(f"\n  数据源优先级:")
        for fetcher in sorted(manager._fetchers, key=lambda f: f.priority):
            # 检查是否有 is_available 方法（TushareFetcher 有这个方法）
            if hasattr(fetcher, 'is_available'):
                status = "可用" if fetcher.is_available() else "不可用"
            else:
                status = "未检查"
            print(f"    {fetcher.priority}. {fetcher.name} - {status}")

        # 获取数据（自动切换）
        print(f"\n  开始获取数据...")
        start_time = time.time()
        df, source_name = manager.get_daily_data(
            stock_code=stock_code,
            start_date=start_date,
            end_date=end_date
        )
        elapsed = time.time() - start_time

        if df is not None and not df.empty:
            print(f"  获取成功: 使用数据源 [{source_name}] ({len(df)} 条记录, 耗时 {elapsed:.2f}秒)")
            print(format_dataframe(df))
            return True, source_name, df
        else:
            print(f"  获取失败: 所有数据源均失败")
            return False, None, None

    except Exception as e:
        print(f"  测试失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False, None, None


def test_realtime_quote(sources: dict, stock_code: str):
    """测试实时行情获取"""
    print_sub_header("测试实时行情获取")

    print(f"  股票代码: {stock_code}")

    try:
        manager = sources['manager']()

        start_time = time.time()
        quote = manager.get_realtime_quote(stock_code)
        elapsed = time.time() - start_time

        if quote:
            print(f"  获取成功: 数据源=[{quote.source.name}] (耗时 {elapsed:.2f}秒)")
            print(f"\n  实时行情数据:")
            print(f"    代码: {quote.code}")
            print(f"    名称: {quote.name}")
            print(f"    最新价: {quote.price}")
            print(f"    涨跌幅: {quote.change_pct}%")
            print(f"    涨跌额: {quote.change_amount}")
            print(f"    成交量: {quote.volume}")
            print(f"    成交额: {quote.amount}")
            if quote.volume_ratio is not None:
                print(f"    量比: {quote.volume_ratio}")
            if quote.turnover_rate is not None:
                print(f"    换手率: {quote.turnover_rate}%")
            if quote.pe_ratio is not None:
                print(f"    市盈率: {quote.pe_ratio}")
            if quote.pb_ratio is not None:
                print(f"    市净率: {quote.pb_ratio}")
            return True
        else:
            print(f"  获取失败: 无法获取实时行情")
            return False

    except Exception as e:
        print(f"  测试失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all_fetchers(sources: dict, stock_code: str, days: int = 30):
    """测试所有数据源"""
    print_sub_header("测试所有数据源")

    results = []

    # 注意：eastmoney_fund 仅支持 ETF 代码
    for fetcher_key, fetcher_class in [('eastmoney_fund', sources['eastmoney_fund']),
                                         ('efinance', sources['efinance']),
                                         ('akshare', sources['akshare']),
                                         ('tushare', sources['tushare']),
                                         ('pytdx', sources['pytdx']),
                                         ('baostock', sources['baostock']),
                                         ('yfinance', sources['yfinance'])]:
        print(f"\n{'=' * 80}")
        success, name, df = test_single_fetcher(fetcher_class, stock_code, days)
        results.append({
            'key': fetcher_key,
            'name': name,
            'success': success,
            'records': len(df) if df is not None else 0
        })
        time.sleep(1)  # 避免请求过快

    # 打印汇总
    print_header("测试结果汇总")
    print(f"\n  {'数据源':<25} {'状态':<10} {'记录数':<10}")
    print(f"  {'-' * 45}")
    for r in results:
        status = "成功" if r['success'] else "失败"
        print(f"  {r['name']:<25} {status:<10} {r['records']:<10}")

    success_count = sum(1 for r in results if r['success'])
    print(f"\n  总计: {success_count}/{len(results)} 个数据源可用")

    return results


def list_fetchers(sources: dict):
    """列出所有数据源"""
    print_header("数据源列表")

    print(f"\n  {'优先级':<8} {'名称':<20} {'描述'}")
    print(f"  {'-' * 80}")

    # 按优先级排序
    sorted_fetchers = sorted(FETCHER_INFO.items(), key=lambda x: x[1]['priority'])

    for key, info in sorted_fetchers:
        priority = info['priority']
        name = info['name']
        desc = info['description']
        print(f"  {priority:<8} {name:<20} {desc}")


# === 主函数 ===
def main():
    parser = argparse.ArgumentParser(
        description='数据源测试工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/test_data_sources.py                       # 测试按优先级获取
  python scripts/test_data_sources.py --stock 600519        # 测试指定股票
  python scripts/test_data_sources.py --fetcher efinance    # 测试单个数据源
  python scripts/test_data_sources.py --all                 # 测试所有数据源
  python scripts/test_data_sources.py --realtime            # 测试实时行情
  python scripts/test_data_sources.py --list                # 列出数据源
  python scripts/test_data_sources.py --etf                 # 测试 ETF（使用512880）
  python scripts/test_data_sources.py --etf --fetcher eastmoney_fund  # 测试天天基金
        """
    )

    parser.add_argument('--stock', type=str, default='600519',
                        help='股票代码 (默认: 600519)')
    parser.add_argument('--days', type=int, default=30,
                        help='获取天数 (默认: 30)')
    parser.add_argument('--fetcher', type=str,
                        choices=['eastmoney_fund', 'efinance', 'akshare', 'tushare', 'pytdx', 'baostock', 'yfinance'],
                        help='测试单个数据源')
    parser.add_argument('--etf', action='store_true',
                        help='使用 ETF 示例代码 (512880) 进行测试')
    parser.add_argument('--all', action='store_true',
                        help='测试所有数据源')
    parser.add_argument('--realtime', action='store_true',
                        help='测试实时行情获取')
    parser.add_argument('--list', action='store_true',
                        help='列出所有数据源')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细模式')

    args = parser.parse_args()

    # 重新配置日志（如果需要详细模式）
    if args.verbose:
        setup_logging(verbose=True)

    # 处理 --etf 选项
    stock_code = args.stock
    if args.etf:
        stock_code = '512880'  # 证券ETF作为默认ETF测试代码
        print(f"  [ETF模式] 使用 ETF 示例代码: {stock_code}")

    # 导入数据源
    sources = import_data_sources()

    print_header("股票数据源测试工具")
    print(f"  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  测试股票: {stock_code}")

    # 执行测试
    if args.list:
        list_fetchers(sources)
    elif args.fetcher:
        test_single_fetcher(sources[args.fetcher], stock_code, args.days)
    elif args.all:
        test_all_fetchers(sources, stock_code, args.days)
    else:
        # 默认：测试按优先级获取
        test_manager_with_priority(sources, stock_code, args.days)

    # 如果指定，测试实时行情
    if args.realtime and not args.list:
        test_realtime_quote(sources, stock_code)

    print(f"\n{'=' * 80}\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断测试")
        sys.exit(0)
    except Exception as e:
        logger.error(f"程序异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
