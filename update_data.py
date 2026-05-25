#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股驾驶舱数据更新脚本（稳健版 v2）
修复了 Series 比较错误，增加重试和错误处理
"""

import json
import time
import random
from datetime import datetime

import yfinance as yf
import pandas as pd

# ---------- 辅助函数：安全获取标量 ----------
def safe_scalar(series, default=0.0):
    """将 pandas Series 或单个值转换为 Python 标量"""
    if isinstance(series, pd.Series):
        if len(series) > 0:
            val = series.iloc[-1]
        else:
            val = default
    elif isinstance(series, (pd.DataFrame, pd.Index)):
        if len(series) > 0:
            val = series.iloc[-1] if hasattr(series, 'iloc') else series[-1]
        else:
            val = default
    else:
        val = series
    # 处理 NaN
    if pd.isna(val):
        val = default
    return float(val)

# ---------- 1. 市场宽度（基于 SPY vs RSP 偏离度估算）----------
def get_market_breadth_estimate():
    try:
        spy = yf.download("SPY", period="3mo", progress=False)
        rsp = yf.download("RSP", period="3mo", progress=False)
        if spy.empty or rsp.empty or len(spy) < 60 or len(rsp) < 60:
            return {"pct_above_50": 52.0, "pct_above_200": 53.0}
        
        # 计算最近60日收益率（标量）
        spy_start = safe_scalar(spy["Close"].iloc[0])
        spy_end = safe_scalar(spy["Close"].iloc[-1])
        spy_ret = (spy_end - spy_start) / spy_start * 100
        
        rsp_start = safe_scalar(rsp["Close"].iloc[0])
        rsp_end = safe_scalar(rsp["Close"].iloc[-1])
        rsp_ret = (rsp_end - rsp_start) / rsp_start * 100
        
        diff = spy_ret - rsp_ret  # 正值表示巨头跑赢，宽度应该降低
        base_50, base_200 = 55.0, 56.0
        adj = -diff * 1.5
        pct_50 = max(30.0, min(80.0, base_50 + adj))
        pct_200 = max(30.0, min(80.0, base_200 + adj))
        return {"pct_above_50": round(pct_50, 1), "pct_above_200": round(pct_200, 1)}
    except Exception as e:
        print(f"市场宽度估算失败: {e}")
        return {"pct_above_50": 52.0, "pct_above_200": 53.0}

# ---------- 2. 板块 YTD 回报（使用 yfinance，增加重试）----------
def get_sector_ytd():
    etfs = {
        "XLB": "原材料", "XLC": "通讯服务", "XLE": "能源", "XLF": "金融",
        "XLI": "工业", "XLK": "科技", "XLP": "必需消费", "XLU": "公用事业",
        "XLV": "医疗保健", "XLY": "可选消费", "XLRE": "房地产"
    }
    results = []
    for ticker, name in etfs.items():
        ytd_val = 0.0
        try:
            data = yf.download(ticker, period="ytd", progress=False)
            if len(data) >= 2:
                start = safe_scalar(data["Close"].iloc[0])
                end = safe_scalar(data["Close"].iloc[-1])
                if start != 0:
                    ytd_val = (end - start) / start * 100
            time.sleep(random.uniform(0.5, 1.0))
        except Exception as e:
            print(f"获取 {ticker} YTD 失败: {e}")
        results.append({"name": ticker, "ytd": round(ytd_val, 2)})
    # 按 YTD 降序排序
    results.sort(key=lambda x: x["ytd"], reverse=True)
    return results

# ---------- 3. 派发日（使用 SPY）----------
def count_distribution_days(days_back=15):
    try:
        spy = yf.download("SPY", period="1mo", progress=False)
        if spy.empty or len(spy) < days_back + 2:
            return 0
        spy["VolumePrev"] = spy["Volume"].shift(1)
        spy["CloseDown"] = spy["Close"] < spy["Close"].shift(1)
        spy["VolumeUp"] = spy["Volume"] > spy["VolumePrev"]
        spy["Distribution"] = spy["CloseDown"] & spy["VolumeUp"]
        recent = spy.iloc[-days_back-1:-1]  # 跳过当天（未完整）
        count = int(recent["Distribution"].sum())
        return count
    except Exception as e:
        print(f"派发日计算失败: {e}")
        return 0

# ---------- 4. XLY/XLP 涨跌幅 ----------
def get_xly_xlp_change():
    try:
        xly = yf.download("XLY", period="2d", progress=False)
        xlp = yf.download("XLP", period="2d", progress=False)
        xly_change = 0.0
        xlp_change = 0.0
        if len(xly) >= 2:
            prev = safe_scalar(xly["Close"].iloc[-2])
            curr = safe_scalar(xly["Close"].iloc[-1])
            if prev != 0:
                xly_change = (curr - prev) / prev * 100
        if len(xlp) >= 2:
            prev = safe_scalar(xlp["Close"].iloc[-2])
            curr = safe_scalar(xlp["Close"].iloc[-1])
            if prev != 0:
                xlp_change = (curr - prev) / prev * 100
        return {"xly_change": round(xly_change, 2), "xlp_change": round(xlp_change, 2)}
    except Exception as e:
        print(f"XLY/XLP 获取失败: {e}")
        return {"xly_change": 0.0, "xlp_change": 0.0}

# ---------- 5. Finviz 板块数据（实时涨跌幅 + 静态估值）----------
def get_finviz_sectors():
    sector_etfs = {
        "科技": "XLK", "金融": "XLF", "医疗保健": "XLV", "可选消费": "XLY",
        "必需消费": "XLP", "工业": "XLI", "能源": "XLE", "原材料": "XLB",
        "公用事业": "XLU", "房地产": "XLRE", "通讯服务": "XLC"
    }
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
        change_str = "0.00%"
        vol_str = "N/A"
        try:
            data = yf.download(ticker, period="2d", progress=False)
            if len(data) >= 2:
                prev = safe_scalar(data["Close"].iloc[-2])
                curr = safe_scalar(data["Close"].iloc[-1])
                if prev != 0:
                    change = (curr - prev) / prev * 100
                    change_str = f"{'+' if change >= 0 else ''}{change:.2f}%"
                # 成交量
                vol = safe_scalar(data["Volume"].iloc[-1], default=0)
                if vol > 1e9:
                    vol_str = f"{vol/1e9:.2f}B"
                elif vol > 1e6:
                    vol_str = f"{vol/1e6:.0f}M"
                else:
                    vol_str = f"{vol:.0f}"
        except Exception as e:
            print(f"获取 {name} 实时涨跌幅失败: {e}")
        info = static_data.get(name, {})
        result.append({
            "name": name,
            "stocks": info.get("stocks", "-"),
            "mktCap": info.get("mktCap", "-"),
            "div": info.get("div", "-"),
            "pe": info.get("pe", "-"),
            "fwdPe": info.get("fwdPe", "-"),
            "peg": info.get("peg", "-"),
            "change": change_str,
            "volume": vol_str
        })
    return result

# ---------- 6. 泡沫指标（支持手动覆盖）----------
def get_bubble_indicators():
    margin = {"value": "1,304,281", "yoy": "+53.34%", "date": "2026-04-01"}
    put_call = {"ratio": "0.55", "ma20": "0.51", "date": "2026-05-22"}
    # 尝试加载本地手动更新的 JSON 文件（如果存在）
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
    print("🚀 开始更新美股驾驶舱数据（稳健模式 v2）...")
    
    breadth = get_market_breadth_estimate()
    print(f"✅ 市场宽度估算: 50日={breadth['pct_above_50']}%, 200日={breadth['pct_above_200']}%")
    
    sector_ytd = get_sector_ytd()
    print(f"✅ 板块 YTD 获取 {len(sector_ytd)} 个")
    
    dist_days = count_distribution_days()
    print(f"✅ 派发日计数: {dist_days}")
    
    xly_xlp = get_xly_xlp_change()
    print(f"✅ XLY: {xly_xlp['xly_change']}% , XLP: {xly_xlp['xlp_change']}%")
    
    finviz_data = get_finviz_sectors()
    print(f"✅ 板块数据 {len(finviz_data)} 个")
    
    bubble = get_bubble_indicators()
    print(f"✅ 保证金债务: {bubble['marginDebt']['value']} ({bubble['marginDebt']['date']})")
    print(f"✅ Put/Call: {bubble['putCall']['ratio']} (MA20 {bubble['putCall']['ma20']})")
    
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
    print("🎉 数据已保存到 data.json")

if __name__ == "__main__":
    main()
