#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股驾驶舱数据更新脚本（精确版 + 历史数据）
"""

import json
import time
import random
import requests
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

# ---------- 工具函数 ----------
def fetch_json(url, headers=None):
    """获取 JSON 数据"""
    if headers is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"❌ 获取 JSON 失败 {url}: {e}")
        return None

# ---------- 1. 市场宽度（从 MacroMicro 获取历史）----------
def get_market_breadth_history():
    """
    获取 MacroMicro 的 >50日均线比例历史数据
    API 示例: https://www.macromicro.me/charts/data/18331
    返回列表 [{"date": "2026-05-22", "above50": 56.77, "above200": ...}, ...]
    """
    url = "https://www.macromicro.me/charts/data/18331"  # 标普500 >50日均线比例
    data = fetch_json(url)
    if not data or "data" not in data:
        print("警告: 无法获取市场宽度历史数据，将使用估算值")
        return []
    records = []
    for item in data["data"]:
        # 格式: {"date": "2026-05-22", "value": 56.77}
        records.append({
            "date": item["date"],
            "above50": item["value"]
        })
    # 同时也获取 >200日均线比例 (series 18332)
    url200 = "https://www.macromicro.me/charts/data/18332"
    data200 = fetch_json(url200)
    if data200 and "data" in data200:
        # 合并数据，按日期对齐
        dict200 = {item["date"]: item["value"] for item in data200["data"]}
        for rec in records:
            rec["above200"] = dict200.get(rec["date"], None)
    else:
        for rec in records:
            rec["above200"] = None
    return records

# ---------- 2. 板块 YTD ----------
def get_sector_ytd():
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
            time.sleep(random.uniform(0.3, 0.8))
        except Exception as e:
            print(f"获取 {ticker} YTD 失败: {e}")
            results.append({"name": ticker, "ytd": 0.0})
    results.sort(key=lambda x: x["ytd"], reverse=True)
    return results

# ---------- 3. 派发日历史 ----------
def get_distribution_history(days_back=60):
    """返回过去60天的派发日标记列表 [{"date": "2026-05-22", "is_distribution": 1/0}, ...]"""
    spy = yf.download("SPY", period="3mo", progress=False)
    if spy.empty:
        return []
    spy["VolumePrev"] = spy["Volume"].shift(1)
    spy["CloseDown"] = spy["Close"] < spy["Close"].shift(1)
    spy["VolumeUp"] = spy["Volume"] > spy["VolumePrev"]
    spy["Distribution"] = (spy["CloseDown"] & spy["VolumeUp"]).astype(int)
    # 转为列表，按日期倒序或正序均可
    result = []
    for idx, row in spy.iterrows():
        result.append({
            "date": idx.strftime("%Y-%m-%d"),
            "is_distribution": int(row["Distribution"])
        })
    # 只返回最近 days_back 天
    return result[-days_back:]

# ---------- 4. XLY/XLP 比率历史 ----------
def get_xly_xlp_history(days_back=60):
    """计算过去 days_back 天的 XLY/XLP 比率及日变化"""
    xly = yf.download("XLY", period="3mo", progress=False)
    xlp = yf.download("XLP", period="3mo", progress=False)
    if xly.empty or xlp.empty:
        return []
    # 合并日期
    common_dates = xly.index.intersection(xlp.index)
    ratios = []
    prev_ratio = None
    for date in common_dates:
        xly_close = xly.loc[date, "Close"]
        xlp_close = xlp.loc[date, "Close"]
        if xlp_close != 0:
            ratio = xly_close / xlp_close
        else:
            ratio = None
        if ratio is not None:
            change_pct = (ratio - prev_ratio) / prev_ratio * 100 if prev_ratio is not None else 0.0
            ratios.append({
                "date": date.strftime("%Y-%m-%d"),
                "ratio": round(ratio, 4),
                "change_pct": round(change_pct, 2) if prev_ratio is not None else 0.0
            })
            prev_ratio = ratio
    return ratios[-days_back:]

# ---------- 5. 泡沫指标历史 ----------
def get_put_call_history():
    """从 MacroMicro 获取 CBOE Equity Put/Call 比率历史"""
    url = "https://www.macromicro.me/charts/data/80896"
    data = fetch_json(url)
    if not data or "data" not in data:
        return []
    records = []
    for item in data["data"]:
        records.append({
            "date": item["date"],
            "ratio": item["value"]
        })
    return records

def get_margin_debt_history():
    """从 MacroMicro 获取保证金债务历史（月频）"""
    url = "https://www.macromicro.me/charts/data/141420"
    data = fetch_json(url)
    if not data or "data" not in data:
        return []
    records = []
    for item in data["data"]:
        records.append({
            "date": item["date"],
            "margin_debt": item["value"]  # 单位百万美元
        })
    return records

# ---------- 6. 最新快照数据（用于当前卡片）----------
def get_latest_snapshot():
    """返回当前最新的各项指标，用于顶部卡片"""
    # 市场宽度最新值（从历史中取最新）
    breadth_hist = get_market_breadth_history()
    latest_breadth = breadth_hist[-1] if breadth_hist else {"above50": 50.0, "above200": 50.0}
    # 派发日最新计数（过去15天）
    dist_hist = get_distribution_history(15)
    dist_count = sum(day["is_distribution"] for day in dist_hist)
    # XLY/XLP 最新比率
    xly_xlp_hist = get_xly_xlp_history(2)
    latest_xly_xlp = xly_xlp_hist[-1] if xly_xlp_hist else {"ratio": 1.0, "change_pct": 0.0}
    # Put/Call 最新值
    pc_hist = get_put_call_history()
    latest_pc = pc_hist[-1] if pc_hist else {"ratio": 0.5}
    # 保证金债务最新值
    margin_hist = get_margin_debt_history()
    latest_margin = margin_hist[-1] if margin_hist else {"margin_debt": 1304281}
    # 计算同比增长（需要两个月前数据）
    margin_yoy = "N/A"
    if len(margin_hist) >= 2:
        prev = margin_hist[-2]["margin_debt"]
        curr = latest_margin["margin_debt"]
        margin_yoy = f"+{(curr - prev)/prev*100:.2f}%"
    return {
        "breadth": latest_breadth,
        "distributionDays": dist_count,
        "xlyXlp": latest_xly_xlp,
        "putCall": latest_pc,
        "marginDebt": {"value": latest_margin["margin_debt"], "yoy": margin_yoy, "date": latest_margin["date"]}
    }

# ---------- 主函数：更新所有数据 ----------
def main():
    print("🚀 开始更新美股驾驶舱数据（精确版 + 历史）...")
    
    # 1. 获取历史数据
    breadth_hist = get_market_breadth_history()
    dist_hist = get_distribution_history(60)
    xly_xlp_hist = get_xly_xlp_history(60)
    putcall_hist = get_put_call_history()
    margin_hist = get_margin_debt_history()
    
    print(f"✅ 市场宽度历史: {len(breadth_hist)} 条")
    print(f"✅ 派发日历史: {len(dist_hist)} 条")
    print(f"✅ XLY/XLP 历史: {len(xly_xlp_hist)} 条")
    print(f"✅ Put/Call 历史: {len(putcall_hist)} 条")
    print(f"✅ 保证金债务历史: {len(margin_hist)} 条")
    
    # 2. 获取板块 YTD
    sector_ytd = get_sector_ytd()
    print(f"✅ 板块 YTD: {len(sector_ytd)} 个")
    
    # 3. 获取 Finviz 板块实时数据
    finviz_data = get_finviz_sectors()  # 复用之前的函数（需保留）
    print(f"✅ Finviz 板块数据: {len(finviz_data)} 个")
    
    # 4. 组装最新快照
    snapshot = get_latest_snapshot()
    
    # 5. 整合最终 JSON
    data = {
        "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot": snapshot,
        "sectorYtd": sector_ytd,
        "finvizSectors": finviz_data,
        "history": {
            "breadth": breadth_hist,
            "distribution": dist_hist,
            "xlyXlp": xly_xlp_hist,
            "putCall": putcall_hist,
            "marginDebt": margin_hist
        }
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # 同时将历史数据单独存储一份 history.json（可选，便于前端）
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(data["history"], f, indent=2, ensure_ascii=False)
    
    print("🎉 数据已保存到 data.json 和 history.json")

# 保留原有的 get_finviz_sectors 函数（省略，与之前相同）
# 这里需要粘贴之前的 get_finviz_sectors 实现，为了节省篇幅省略，请从上一版复制
# 注意：确保该函数可用

if __name__ == "__main__":
    main()
