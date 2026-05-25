#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股驾驶舱数据更新脚本（稳健版）
仅使用 yfinance + 本地计算，尽可能避免网络封锁。
手动补充部分低频数据（Margin Debt / Put Call）
"""

import json
import time
import random
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

# ---------- 1. 计算市场宽度（模拟）----------
# 真实市场宽度需要全市场数据，这里用 SPY 与 RSP 的偏离度 + 一个基准值来模拟趋势
def get_market_breadth_estimate():
    """
    返回 {'pct_above_50': float, 'pct_above_200': float}
    基于 SPY vs RSP (等权重 S&P500) 的相对表现估算。
    当 SPY 跑赢 RSP 较多时，宽度较低（巨头驱动）；跑输时宽度较高。
    """
    try:
        spy = yf.download("SPY", period="3mo", progress=False)
        rsp = yf.download("RSP", period="3mo", progress=False)
        if spy.empty or rsp.empty:
            return {"pct_above_50": 52.0, "pct_above_200": 53.0}
        # 计算最近60日相对超额收益
        spy_ret = spy["Close"].pct_change(60).iloc[-1] * 100
        rsp_ret = rsp["Close"].pct_change(60).iloc[-1] * 100
        diff = spy_ret - rsp_ret
        # 经验公式：diff > 5% => 宽度~45-50%; diff < -5% => 宽度~65-70%
        base_50 = 55.0
        base_200 = 56.0
        adj = -diff * 1.5  # diff越大，宽度越小
        pct_50 = max(30, min(80, base_50 + adj))
        pct_200 = max(30, min(80, base_200 + adj))
        return {"pct_above_50": round(pct_50, 1), "pct_above_200": round(pct_200, 1)}
    except Exception as e:
        print(f"市场宽度估算失败: {e}")
        return {"pct_above_50": 52.0, "pct_above_200": 53.0}


# ---------- 2. 板块 YTD 回报（使用 yfinance）----------
def get_sector_ytd():
    """使用 Sector ETF 直接获取 YTD"""
    etfs = {
        "XLB": "原材料", "XLC": "通讯服务", "XLE": "能源", "XLF": "金融",
        "XLI": "工业", "XLK": "科技", "XLP": "必需消费", "XLU": "公用事业",
        "XLV": "医疗保健", "XLY": "可选消费", "XLRE": "房地产"
    }
    results = []
    for ticker, name in etfs.items():
        try:
            data = yf.download(ticker, period="ytd", progress=False)
            if len(data) >= 2:
                start = data["Close"].iloc[0]
                end = data["Close"].iloc[-1]
                ytd = (end - start) / start * 100
                results.append({"name": ticker, "ytd": round(ytd, 2)})
            else:
                results.append({"name": ticker, "ytd": 0.0})
            time.sleep(random.uniform(0.5, 1.5))  # 礼貌延迟
        except Exception as e:
            print(f"获取 {ticker} YTD 失败: {e}")
            results.append({"name": ticker, "ytd": 0.0})
    results.sort(key=lambda x: x["ytd"], reverse=True)
    return results


# ---------- 3. 派发日（使用 SPY）----------
def count_distribution_days(days_back=15):
    spy = yf.download("SPY", period="1mo", progress=False)
    if spy.empty:
        return 0
    spy["VolumePrev"] = spy["Volume"].shift(1)
    spy["CloseDown"] = spy["Close"] < spy["Close"].shift(1)
    spy["VolumeUp"] = spy["Volume"] > spy["VolumePrev"]
    spy["Distribution"] = spy["CloseDown"] & spy["VolumeUp"]
    recent = spy.iloc[-days_back-1:-1]
    return int(recent["Distribution"].sum())


# ---------- 4. XLY/XLP 涨跌幅 ----------
def get_xly_xlp_change():
    try:
        xly = yf.download("XLY", period="2d", progress=False)
        xlp = yf.download("XLP", period="2d", progress=False)
        xly_change = (xly["Close"].iloc[-1] - xly["Close"].iloc[-2]) / xly["Close"].iloc[-2] * 100 if len(xly) >= 2 else 0.0
        xlp_change = (xlp["Close"].iloc[-1] - xlp["Close"].iloc[-2]) / xlp["Close"].iloc[-2] * 100 if len(xlp) >= 2 else 0.0
        return {"xly_change": round(xly_change, 2), "xlp_change": round(xlp_change, 2)}
    except:
        return {"xly_change": 0.0, "xlp_change": 0.0}


# ---------- 5. Finviz 板块数据（简化版，从 yfinance 获取部分估值太难，改为静态示例 + 实时涨跌幅）----------
def get_finviz_sectors():
    """返回板块列表，包含当日涨跌幅（从 ETF 获取），P/E/PEG 使用预估值（从 yfinance 无法轻易获取，展示为静态参考）"""
    sector_etfs = {
        "科技": "XLK", "金融": "XLF", "医疗保健": "XLV", "可选消费": "XLY",
        "必需消费": "XLP", "工业": "XLI", "能源": "XLE", "原材料": "XLB",
        "公用事业": "XLU", "房地产": "XLRE", "通讯服务": "XLC"
    }
    # 静态估值数据（基于某日参考，用户可自行修改）
    static_data = {
        "科技": {"pe": "38.6", "peg": "1.19", "stocks": "779", "mktCap": "31.1T", "div": "0.54%"},
        "金融": {"pe": "16.0", "peg": "1.38", "stocks": "1092", "mktCap": "13.9T", "div": "1.97%"},
        "医疗保健": {"pe": "28.8", "peg": "2.02", "stocks": "1075", "mktCap": "8.33T", "div": "1.60%"},
        "可选消费": {"pe": "30.4", "peg": "1.56", "stocks": "545", "mktCap": "9.36T", "div": "0.78%"},
        "必需消费": {"pe": "26.9", "peg": "2.94", "stocks": "246", "mktCap": "4.49T", "div": "2.37%"},
        "工业": {"pe": "32.0", "peg": "1.67", "stocks": "690", "mktCap": "7.59T", "div": "1.08%"},
        "能源": {"pe": "19.8", "peg": "1.39", "stocks": "256", "mktCap": "4.74T", "div": "3.43%"},
        "原材料": {"pe": "22.7", "peg": "1.24", "stocks": "283", "mktCap": "2.88T", "div": "1.94%"},
        "公用事业": {"pe": "21.0", "peg": "1.79", "stocks": "109", "mktCap": "1.96T", "div": "2.93%"},
        "房地产": {"pe": "32.7", "peg": "3.34", "stocks": "255", "mktCap": "1.80T", "div": "3.72%"},
        "通讯服务": {"pe": "39.1", "peg": "2.23", "stocks": "263", "mktCap": "13.7T", "div": "0.50%"},
    }

    result = []
    for name, ticker in sector_etfs.items():
        try:
            data = yf.download(ticker, period="2d", progress=False)
            if len(data) >= 2:
                change = (data["Close"].iloc[-1] - data["Close"].iloc[-2]) / data["Close"].iloc[-2] * 100
                change_str = f"{'+' if change >=0 else ''}{change:.2f}%"
            else:
                change_str = "0.00%"
            # 获取成交量（最近一天）
            vol = data["Volume"].iloc[-1] if not data.empty and "Volume" in data else 0
            vol_str = f"{vol/1e9:.2f}B" if vol > 1e9 else f"{vol/1e6:.0f}M"
        except:
            change_str = "0.00%"
            vol_str = "N/A"
        info = static_data.get(name, {})
        result.append({
            "name": name,
            "stocks": info.get("stocks", "-"),
            "mktCap": info.get("mktCap", "-"),
            "div": info.get("div", "-"),
            "pe": info.get("pe", "-"),
            "fwdPe": info.get("fwdPe", "-"),   # 我们静态数据没有，留空
            "peg": info.get("peg", "-"),
            "change": change_str,
            "volume": vol_str
        })
    return result


# ---------- 6. 泡沫指标（手动维护或从 ycharts 抓取，这里使用静态示例 + 提示手动更新）----------
def get_bubble_indicators():
    # 由于 ycharts 可能被屏蔽，我们提供本地 JSON 文件覆盖机制
    # 用户可手动编辑 margin_debt.json 和 put_call.json 来更新
    margin = {"value": "1,304,281", "yoy": "+53.34%", "date": "2026-04-01"}
    put_call = {"ratio": "0.55", "ma20": "0.51", "date": "2026-05-22"}

    # 尝试从本地文件加载用户手动更新的数据
    try:
        with open("margin_debt.json", "r") as f:
            custom_margin = json.load(f)
            margin.update(custom_margin)
    except FileNotFoundError:
        pass
    try:
        with open("put_call.json", "r") as f:
            custom_pc = json.load(f)
            put_call.update(custom_pc)
    except FileNotFoundError:
        pass

    return {"marginDebt": margin, "putCall": put_call}


# ---------- 主函数 ----------
def main():
    print("🚀 开始更新美股驾驶舱数据（稳健模式）...")
    # 1. 市场宽度估算
    breadth = get_market_breadth_estimate()
    print(f"✅ 市场宽度估算: 50日={breadth['pct_above_50']}%, 200日={breadth['pct_above_200']}%")

    # 2. 板块 YTD
    sector_ytd = get_sector_ytd()
    print(f"✅ 板块 YTD 获取 {len(sector_ytd)} 个")

    # 3. 派发日
    dist_days = count_distribution_days()
    print(f"✅ 派发日计数: {dist_days}")

    # 4. XLY/XLP
    xly_xlp = get_xly_xlp_change()
    print(f"✅ XLY: {xly_xlp['xly_change']}% , XLP: {xly_xlp['xlp_change']}%")

    # 5. Finviz 板块（简化版）
    finviz_data = get_finviz_sectors()
    print(f"✅ 板块数据 {len(finviz_data)} 个")

    # 6. 泡沫指标
    bubble = get_bubble_indicators()
    print(f"✅ 保证金债务: {bubble['marginDebt']['value']} ({bubble['marginDebt']['date']})")
    print(f"✅ Put/Call: {bubble['putCall']['ratio']} (MA20 {bubble['putCall']['ma20']})")

    # 组装 JSON
    data = {
        "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "breadth": breadth,
        "sectorYtd": sector_ytd,
        "distributionDays": dist_days,
        "xlyXlp": xly_xlp,
        "finvizSectors": finviz_data,
        "bubble": bubble
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("🎉 数据已保存到 data.json，可以打开 dashboard.html 查看。")
    print("提示：若需精确保证金债务或 Put/Call 数据，请手动编辑 margin_debt.json 和 put_call.json")


if __name__ == "__main__":
    main()